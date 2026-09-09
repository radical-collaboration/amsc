#!/usr/bin/env python3
"""
End-to-end IRI test: launch an ORBIT endpoint on an HPC machine via its
IRI facility API, then drive a minimal ROSE active-learning loop on it.

Flow
====

  Client (this script)
        │
        ▼  EndpointRuntime()                 ← connects to the running broker
        │
        ▼  broker connect plugin             ← per-target: 'sfapi_connect'
        │  ('sfapi_connect' | 'iri_connect')   (client id + PEM) for NERSC,
        │                                       'iri_connect' (bearer token)
        │                                       for OLCF — creds from local file
        ▼  iri.submit_job(...)               ← batch job runs the endpoint
        │                                      wrapper from the orbit ve
        ▼  topology poll                     ← wait until the endpoint dials in
        │
        ▼  rhapsody.get_backend('orbit')     ← execution backend on the endpoint
        ▼  WorkflowEngine.create(engine)     ← asyncflow on top
        ▼  SequentialActiveLearner           ← ROSE driver, pure-stdlib
                                               function tasks (no app payload)

Usage
-----
::

    python iri_test.py perlmutter|odo [<max_iter>]

Exactly one target per run; ``max_iter`` bounds the ROSE loop (default 2).

Prerequisites
-------------
- A broker is running and reachable; URL / cert / token resolve the
  standard radical.orbit way (env > file, see DEPLOYMENT.md).
- The broker TLS cert is staged on the target
  (``~/.radical/orbit/broker_cert.pem``).
- The orbit ve exists on the target at the path configured in ``TARGETS``
  (must include rhapsody + dragon; the test tasks themselves need nothing
  beyond the python stdlib).
- Credentials sit next to this script and are read locally, sent to the
  broker once at ``connect()`` time, and held there in process memory only:
    * perlmutter (SFAPI direct, ``sfapi_connect``): ``sfapi_perlmutter.id``
      (OAuth2 client id) and ``sfapi_perlmutter.pem`` (RSA private key PEM).
    * odo (S3M bearer, ``iri_connect``): ``token_odo``, literal token string
      only.
"""

import asyncio
import base64
import logging
import os
import sys
import time

from pathlib import Path

import rhapsody

from radical.asyncflow      import WorkflowEngine
from radical.orbit          import EndpointRuntime
from radical.orbit          import utils as orbit_utils
from rose.al.active_learner import SequentialActiveLearner

rhapsody.enable_logging(level=logging.WARNING)


# ─────────────────────────────────────────────────────────────────────────────
#  Configuration.
#
#  One entry per supported target, selected by the first CLI argument.
#  ``connect`` names the broker connect plugin to use ('sfapi_connect' or
#  'iri_connect'); ``iri_endpoint`` is the endpoint key that plugin knows
#  (it resolves the API URL); ``orbit_ve`` is the virtualenv on the target
#  that carries the endpoint wrapper.
# ─────────────────────────────────────────────────────────────────────────────

N_NODES               = 1
WALLTIME_MIN          = 30
MAX_ITER              = 2         # default ROSE iterations; CLI-overridable
ENDPOINT_WAIT_SECONDS = 30 * 60   # max queue wait for the endpoint job

TARGETS = {
    'perlmutter': {
        'connect'     : 'sfapi_connect',
        'iri_endpoint': 'nersc',
        'auth'        : 'sfapi',
        'resource_id' : 'perlmutter',
        'login_host'  : 'perlmutter.nersc.gov',
        'tunnel'      : 'forward',
        'account'     : 'amsc007',
        'queue_name'  : 'debug',
        'constraint'  : 'cpu',
        'workdir'     : None,
        'orbit_ve'    : '/global/u2/m/merzky/radical/radical.orbit/ve3',
        # The wrapper now owns PATH (prepends the orbit ve's bin so dragon's
        # srun-launched helpers resolve BY NAME) and SLURM_EXPORT_ENV=ALL
        # (so --export=NONE submissions do not scrub inner job steps) — no
        # per-target setup needed.
        # NB: do NOT re-add dragon logging via ARGS="-l dragon_file=DEBUG
        # -l stderr=DEBUG" — dragon 0.14's logging channel deadlocks the
        # backend bring-up right after BEIsUp/FENodeIdxBE.
        'setup'       : [],
    },
    'odo': {
        'connect'     : 'iri_connect',
        'iri_endpoint': 'olcf',
        'auth'        : 's3m',
        'resource_id' : 'odo',
        'login_host'  : 'login1.frontier.olcf.ornl.gov',
        'tunnel'      : 'reverse',
        'account'     : 'fus183',
        'queue_name'  : 'batch',
        'constraint'  : None,
        # Top-level ``directory`` is required by Frontier-class SLURM (OLCF).
        'workdir'     : '/gpfs/wolf2/olcf/fus183/proj-shared',
        'orbit_ve'    : '/autofs/nccsopen-svm1_home/merzky'
                        '/radical/radical.orbit/ve3',
        'setup'       : ['module load cray-python/3.11.7'],
    },
}


def abort(msg):
    """Print an ABORT line and exit with status 1.  No traceback."""
    print(f'ABORT  {msg}')
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
#  IRI launch path.
# ─────────────────────────────────────────────────────────────────────────────

def read_token(target):
    """Read ``token_<target>`` from the script's own directory."""
    path = Path(__file__).resolve().parent / f'token_{target}'
    if not path.exists():
        raise RuntimeError(
            f'token file missing: {path}  (put your IRI bearer token '
            f'there, literal string only)')
    token = path.read_text().strip()
    if not token:
        raise RuntimeError(f'token file is empty: {path}')
    return token


def read_sfapi_credentials(target):
    """Read ``sfapi_<target>.id`` + ``sfapi_<target>.pem`` from the script's
    own directory.  Returns ``(client_id, private_key)``; both are held only
    in this process and the broker's memory, never written elsewhere."""
    base     = Path(__file__).resolve().parent
    id_path  = base / f'sfapi_{target}.id'
    pem_path = base / f'sfapi_{target}.pem'
    for path in (id_path, pem_path):
        if not path.exists():
            raise RuntimeError(
                f'SFAPI credential file missing: {path}  (put your SFAPI '
                f'client id in sfapi_{target}.id and the RSA private key '
                f'PEM in sfapi_{target}.pem)')
    client_id   = id_path.read_text().strip()
    private_key = pem_path.read_text().strip()
    if not client_id:
        raise RuntimeError(f'SFAPI client id file is empty: {id_path}')
    if not private_key:
        raise RuntimeError(f'SFAPI private key file is empty: {pem_path}')
    return client_id, private_key


def _credential_env(broker_url):
    """Job-env broker URL + token for the child endpoint.

    Injects the broker's *current* token so the child does not depend on
    a possibly-stale ``~/.radical/orbit/broker.token`` on the target.
    The TLS cert is deliberately NOT injected: it is staged manually to
    ``~/.radical/orbit/broker_cert.pem`` on every connecting host (see
    DEPLOYMENT.md).
    """
    env = {'RADICAL_ORBIT_BROKER_URL': broker_url}
    token, _ = orbit_utils.resolve_broker_token()
    if token:
        env['RADICAL_ORBIT_BROKER_TOKEN'] = token
    return env


def _endpoint_argv(endpoint_name, broker_url, tunnel, login_host):
    """Build the ``radical-orbit-endpoint.py`` argv for the child endpoint.

    ``tunnel`` is one of ``'none'`` / ``'forward'`` / ``'reverse'``.
    Forward mode needs ``--tunnel-via`` (the login host the child opens
    ``ssh -L`` to); reverse / none do not.
    """
    args = ['--name', endpoint_name, '--url', broker_url]
    if tunnel != 'none':
        args += ['--tunnel', tunnel]
        if tunnel == 'forward':
            if not login_host:
                raise ValueError(
                    "tunnel 'forward' requires a login_host (the host the "
                    "child opens 'ssh -L' to)")
            args += ['--tunnel-via', login_host]
    return args


def launch_iri(bc, target, cfg, broker_url):
    """Connect to the IRI facility and submit the endpoint job.

    Returns a record with the IRI client, job id and endpoint name so the
    caller can wait for the endpoint and cancel the job on teardown.
    """
    # Connect (idempotent — a reconnect refreshes the credential in place).
    # The connect plugin is per-target: NERSC/Perlmutter goes through the
    # standalone ``sfapi_connect`` plugin (client id + RSA private key);
    # the bearer endpoints (IRI / S3M) go through ``iri_connect`` (token).
    cx = bc.get_plugin('broker', cfg['connect'])
    if cfg.get('auth') == 'sfapi':
        client_id, private_key = read_sfapi_credentials(target)
        iri = cx.connect(endpoint=cfg['iri_endpoint'],
                         client_id=client_id, private_key=private_key)
    else:
        token = read_token(target)
        iri   = cx.connect(endpoint=cfg['iri_endpoint'], token=token)

    # Unique per run so successive tests never collide broker-side.
    endpoint_name = f'iri-test.{target}.{os.getpid()}'

    args = _endpoint_argv(endpoint_name, broker_url,
                          cfg['tunnel'], cfg.get('login_host'))

    attrs = {
        'queue_name': cfg['queue_name'],
        'duration'  : WALLTIME_MIN * 60,   # seconds
        'account'   : cfg['account'],
    }
    if cfg.get('constraint'):
        attrs['constraint'] = cfg['constraint']

    wrapper = (cfg['orbit_ve'].rstrip('/')
               + '/bin/radical-orbit-endpoint-wrapper.sh')

    env = _credential_env(broker_url)
    # Site-specific shell snippet — module loads etc.  The wrapper
    # ``eval``s this before exec-ing dragon / python.  Base64-encoded:
    # job APIs may compose the batch script with unquoted ``export
    # KEY=VALUE`` lines, which truncate multi-word values at the first
    # space (seen with IRI at NERSC).
    if cfg.get('setup'):
        env['RADICAL_ORBIT_SETUP_B64'] = base64.b64encode(
            '; '.join(cfg['setup']).encode()).decode('ascii')

    job_spec = {
        'executable' : wrapper,
        'arguments'  : args,
        'name'       : endpoint_name,
        'resources'  : {'node_count': N_NODES},
        'attributes' : attrs,
        'environment': env,
    }
    if cfg.get('workdir'):
        job_spec['directory'] = cfg['workdir']

    print(f'submit   : {cfg["iri_endpoint"]} → {cfg["resource_id"]}, '
          f'endpoint {endpoint_name}')
    job = iri.submit_job(cfg['resource_id'], job_spec)
    print(f'job id   : {job["job_id"]}')

    return {
        'iri'          : iri,
        'connect'      : cfg['connect'],
        'iri_endpoint' : cfg['iri_endpoint'],
        'resource_id'  : cfg['resource_id'],
        'job_id'       : job['job_id'],
        'endpoint_name': endpoint_name,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Wait for the endpoint to register.
# ─────────────────────────────────────────────────────────────────────────────

class _JobFailureWatch:
    """Subscribe to ``job_status`` notifications for one job and record its
    first *terminal failure*.

    The endpoint only registers once its HPC job reaches ``RUNNING``; if the
    job instead dies (bad submission, tunnel setup failure, scheduler
    rejection) the endpoint never appears and a plain topology poll would
    block for the full ``ENDPOINT_WAIT_SECONDS``.  Watching the job's own
    status lets the wait bail the moment the job fails.  IRI states are
    lower-case — compared case-folded to be safe.
    """

    _FAILED = {'failed', 'cancelled', 'canceled', 'error',
               'node_fail', 'timeout', 'out_of_memory', 'preempted',
               'deadline'}

    def __init__(self, bc, job_id):
        self._bc     = bc
        self._job_id = job_id
        self.failed  = False
        self.reason  = None
        # Bind the handler once: register/unregister match callbacks by
        # identity, and each ``self._on_status`` access is a fresh bound
        # method.
        self._cb     = self._on_status
        bc.register_callback(topic='job_status', callback=self._cb)

    def _on_status(self, endpoint, plugin, topic, data):
        # Runs on the callback-dispatcher thread; a malformed/None payload
        # must not raise here (it would kill that thread).
        if self.failed or not isinstance(data, dict):
            return
        if data.get('job_id') != self._job_id:
            return
        state = str(data.get('state', '')).lower()
        if state in self._FAILED:
            self.reason = (data.get('error') or data.get('details')
                           or f'job entered state {state!r}')
            self.failed = True

    def close(self):
        try:
            self._bc.unregister_callback(topic='job_status',
                                         callback=self._cb)
        except Exception:
            pass


def wait_for_endpoint(bc, name, failure):
    """Poll ``bc.topology()`` until *name* registers (heartbeat dots while
    waiting).  If *failure* trips first — the job died before its endpoint
    connected — raise immediately instead of blocking until the timeout."""
    start   = time.time()
    last_hb = start
    try:
        while time.time() - start < ENDPOINT_WAIT_SECONDS:
            if name in bc.topology():
                return name
            if failure.failed:
                raise RuntimeError(
                    f'endpoint {name!r} will not appear — its job failed: '
                    f'{failure.reason}')
            time.sleep(3.0)
            if time.time() - last_hb >= 10.0:
                sys.stdout.write('.')
                sys.stdout.flush()
                last_hb = time.time()
        raise TimeoutError(f'endpoint {name!r} did not appear within '
                           f'{ENDPOINT_WAIT_SECONDS}s')
    finally:
        sys.stdout.write('\n')
        sys.stdout.flush()


# ─────────────────────────────────────────────────────────────────────────────
#  ROSE workload — pure-stdlib function tasks.
#
#  The tasks are deliberately trivial: each is self-contained (imports
#  inside, no captured variables — they get cloudpickled to the endpoint),
#  needs nothing beyond the python stdlib, and reports the host / pid it
#  ran on so the round trip is visible client-side.
# ─────────────────────────────────────────────────────────────────────────────

async def run_rose_workload(broker_url, endpoint_name, max_iter):

    backend = rhapsody.get_backend('orbit', broker_url=broker_url,
                                   endpoint_name=endpoint_name)
    engine  = await backend
    flow    = await WorkflowEngine.create(engine)
    acl     = SequentialActiveLearner(flow)

    @acl.simulation_task(as_executable=False)
    async def simulation(*args):
        import math
        import os
        import random
        import socket
        xs = [random.uniform(0.0, 2.0 * math.pi) for _ in range(16)]
        ys = [math.sin(x) + random.gauss(0.0, 0.1) for x in xs]
        return {'sim_host'  : socket.gethostname(),
                'sim_pid'   : os.getpid(),
                'sim_y_mean': sum(ys) / len(ys)}

    @acl.training_task(as_executable=False)
    async def training(*args):
        import os
        import random
        import socket
        import statistics
        losses = [abs(random.gauss(0.0, 1.0)) for _ in range(8)]
        return {'train_host': socket.gethostname(),
                'train_pid' : os.getpid(),
                'train_loss': statistics.mean(losses)}

    @acl.active_learn_task(as_executable=False)
    async def active_learn(*args):
        import math
        import os
        import random
        import socket
        queries = [random.uniform(0.0, 2.0 * math.pi) for _ in range(4)]
        return {'al_host'   : socket.gethostname(),
                'al_pid'    : os.getpid(),
                'al_queries': len(queries)}

    try:
        async for state in acl.start(max_iter=max_iter):
            print(f'  iter {state.iteration}: '
                  f'sim [{state.sim_host}/{state.sim_pid}] '
                  f'y_mean={state.sim_y_mean:+.3f}  '
                  f'train [{state.train_host}/{state.train_pid}] '
                  f'loss={state.train_loss:.3f}  '
                  f'al [{state.al_host}/{state.al_pid}] '
                  f'queries={state.al_queries}')
    finally:
        await acl.shutdown()


# ─────────────────────────────────────────────────────────────────────────────
#  Teardown — only touch resources THIS SCRIPT created.
# ─────────────────────────────────────────────────────────────────────────────

def teardown(bc, rec):
    """Cancel the IRI job and disconnect the IRI facility.  Per-item
    failures are non-fatal — always push through to the next item."""
    if not rec:
        return
    try:
        rec['iri'].cancel_job(rec['resource_id'], rec['job_id'])
    except Exception as exc:
        print(f'  could not cancel IRI job {rec["job_id"]}: {exc}')
    try:
        bc.get_plugin('broker', rec['connect']).disconnect(rec['iri_endpoint'])
    except Exception as exc:
        print(f'  could not disconnect IRI {rec["iri_endpoint"]}: {exc}')


# ─────────────────────────────────────────────────────────────────────────────
#  Main.
# ─────────────────────────────────────────────────────────────────────────────

def main():

    args = sys.argv[1:]
    if not args or args[0] not in TARGETS:
        abort(f'usage: {sys.argv[0]} {"|".join(TARGETS)} [<max_iter>]')
    target   = args[0]
    max_iter = MAX_ITER
    if len(args) > 1:
        if not args[1].isdigit() or int(args[1]) <= 0:
            abort(f'max_iter must be a positive integer: got {args[1]!r}')
        max_iter = int(args[1])
    if len(args) > 2:
        abort(f'unrecognized arguments: {args[2:]}')

    cfg = TARGETS[target]

    # EndpointRuntime self-resolves broker URL / cert / token (env > file).
    bc = EndpointRuntime()
    bc.start(wait=True)
    broker_url = bc.broker_url
    print(f'broker   : {broker_url}')

    rec = None
    try:
        try:
            rec = launch_iri(bc, target, cfg, broker_url)
        except Exception as exc:
            abort(f'IRI launch failed: {exc}')

        t0    = time.time()
        watch = _JobFailureWatch(bc, rec['job_id'])
        try:
            wait_for_endpoint(bc, rec['endpoint_name'], failure=watch)
        except Exception as exc:
            abort(f'wait for endpoint failed: {exc}')
        finally:
            watch.close()
        print(f'endpoint : {rec["endpoint_name"]} '
              f'up after {int(time.time() - t0)}s')

        print(f'rose     : {max_iter} iteration(s)')
        try:
            asyncio.run(run_rose_workload(
                broker_url, rec['endpoint_name'], max_iter))
        except Exception as exc:
            abort(f'rose workload failed: {exc}')
        print('OK')
    finally:
        print('teardown : cancelling IRI job, disconnecting facility')
        teardown(bc, rec)
        bc.stop()


if __name__ == '__main__':
    main()
