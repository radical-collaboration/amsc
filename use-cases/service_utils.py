#!/usr/bin/env python3
"""
AMSC service infrastructure shared across all ROSE-aaS use cases.

Covers: BridgeClient setup, target discovery, IRI/PsiJ launch paths,
edge polling, MLflow auth patching, teardown, and the generic main() driver.
None of this is use-case specific.
"""

import fcntl
import os
import sys
import time
import uuid
from pathlib import Path

from radical.edge.client import BridgeClient


# ─────────────────────────────────────────────────────────────────────────────
#  Tunables
# ─────────────────────────────────────────────────────────────────────────────

EDGE_WAIT_SECONDS = 30 * 60 * 1000

AMSC_DIR = Path(os.environ.get('AMSC_DIR') or Path.home() / '.amsc').expanduser()


# ─────────────────────────────────────────────────────────────────────────────
#  Target / machine defaults
# ─────────────────────────────────────────────────────────────────────────────

IRI_DEFAULTS = {
    'nersc': {
        'enabled'     : True,
        'iri_url'     : 'https://api.iri.nersc.gov',
        'resource_id' : 'perlmutter',
        'login_host'  : 'perlmutter.nersc.gov',
        'home_dir'    : '/global/u2/m/merzky',
        'amsc_dir'    : None,
        'tunnel'      : True,
        'account'     : 'amsc007',
        'workdir'     : None,
        'queue_name'  : 'debug',
        'walltime_min': 30,
        'n_nodes'     : 1,
        'constraint'  : 'cpu',
        'reservation' : None,
        'environment' : {},
        'setup'       : [
            'module load openmpi',
        ],
    },
    'olcf': {
        'enabled'     : True,
        'iri_url'     : 'https://amsc-open.s3m.olcf.ornl.gov',
        'resource_id' : 'odo',
        'login_host'  : 'login1.frontier.olcf.ornl.gov',
        'home_dir'    : '/autofs/nccsopen-svm1_home/merzky',
        'amsc_dir'    : None,
        'tunnel'      : True,
        'account'     : 'fus183',
        'workdir'     : '/gpfs/wolf2/olcf/fus183/proj-shared',
        'queue_name'  : 'batch',
        'walltime_min': 30,
        'n_nodes'     : 1,
        'constraint'  : None,
        'reservation' : None,
        'environment' : {},
        'setup'       : None,
    },
}

MACHINE_DEFAULTS = {
    'aurora': {
        'enabled'     : True,
        'account'     : 'Fusion-FM',
        'queue_name'  : 'debug',
        'walltime_min': 30,
        'n_nodes'     : 1,
        'constraint'  : None,
        'tunnel'      : True,
        'amsc_dir'    : None,
        'setup'       : None,
    },
    'perlmutter': {
        'enabled'     : True,
        'account'     : 'amsc007',
        'queue_name'  : None,
        'qos'         : 'express_amsc',
        'walltime_min': 30,
        'n_nodes'     : 1,
        'constraint'  : 'cpu',
        'tunnel'      : True,
        'amsc_dir'    : None,
        'setup'       : [],
    },
    'odo': {
        'enabled'     : True,
        'account'     : 'fus183',
        'queue_name'  : 'batch',
        'walltime_min': 30,
        'n_nodes'     : 1,
        'constraint'  : None,
        'tunnel'      : True,
        'amsc_dir'    : None,
        'setup'       : None,
    },
    'thinkie': {
        'enabled'     : False,
        'amsc_dir'    : None,
        'setup'       : None,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
#  MLflow auth
# ─────────────────────────────────────────────────────────────────────────────

def enable_amsc_x_api_key(tracking_uri: str | None = None) -> None:
    """Patch MLflow to inject X-Api-Key and point at the AMSC tracking server."""
    import mlflow
    import mlflow.utils.rest_utils as rest_utils

    uri = tracking_uri or os.environ.get('MLFLOW_TRACKING_URI', '').strip() or None
    if uri:
        mlflow.set_tracking_uri(uri)
    else:
        print(
            '[WARNING] enable_amsc_x_api_key: MLFLOW_TRACKING_URI is not set. '
            'MLflow will log locally. Pass tracking_uri= or export MLFLOW_TRACKING_URI.',
            flush=True,
        )

    try:
        api_key = os.environ['AM_SC_API_KEY']
    except KeyError:
        pass
    _orig = rest_utils.http_request

    def patched(host_creds, endpoint, method, *args, **kwargs):
        h = dict(kwargs.get('headers') or kwargs.get('extra_headers') or {})
        h['X-Api-Key'] = api_key
        kwargs['headers' if 'headers' in kwargs else 'extra_headers'] = h
        return _orig(host_creds, endpoint, method, *args, **kwargs)

    rest_utils.http_request = patched


# ─────────────────────────────────────────────────────────────────────────────
#  Interactive prompt helpers
# ─────────────────────────────────────────────────────────────────────────────

def ask(prompt, default=None):
    suffix = f' [{default}]' if default is not None else ''
    answer = input(f'{prompt}{suffix}: ').strip()
    return answer or (default if default is not None else '')


def ask_int(prompt, default):
    while True:
        raw = ask(prompt, str(default))
        try:               return int(raw)
        except ValueError: print(f'  not an integer: {raw!r} — try again')


def confirm(prompt, default=True):
    suffix = ' [Y/n]' if default else ' [y/N]'
    while True:
        answer = input(f'{prompt}{suffix}: ').strip().lower()
        if not answer:             return default
        if answer in ('y', 'yes'): return True
        if answer in ('n', 'no'):  return False
        print('  please answer y or n')


def select_many(items, prompt):
    if not items:
        return []
    print(f'\n{prompt}')
    for i, (label, _) in enumerate(items, start=1):
        print(f'  {i:2d}) {label}')
    raw = ask('  enter numbers (e.g. "1 3 5"), "all", or empty for none', '')
    if raw.lower() == 'all':
        return [v for _, v in items]
    picks = []
    for tok in raw.split():
        try:
            idx = int(tok)
        except ValueError:
            print(f'  ignored non-numeric: {tok!r}')
            continue
        if 1 <= idx <= len(items): picks.append(items[idx - 1][1])
        else:                      print(f'  ignored out-of-range: {idx}')
    return picks


# ─────────────────────────────────────────────────────────────────────────────
#  Target discovery
# ─────────────────────────────────────────────────────────────────────────────

def discover_targets(bc):
    targets = []
    for name in bc.list_edges():
        if name == 'bridge':
            continue
        if not MACHINE_DEFAULTS.get(name, {}).get('enabled', True):
            print(f'  (skipped {name}: disabled in MACHINE_DEFAULTS)')
            continue
        edge    = bc.get_edge_client(name)
        plugins = edge.list_plugins()
        has_rhapsody = 'rhapsody' in plugins
        has_psij     = 'psij'     in plugins
        try:
            info      = edge.get_plugin('sysinfo').host_role()
            role      = info.get('role',          'unknown')
            scheduler = info.get('scheduler',     'none')
            executor  = info.get('psij_executor', 'local')
        except Exception:
            role, scheduler, executor = 'unknown', 'none', 'local'
        if role in ('compute', 'standalone') and has_rhapsody:
            targets.append((
                f'[ready]    edge {name} ({role}, will run tasks here)',
                {'kind': 'compute', 'edge_name': name}))
        elif role == 'login' and has_psij:
            targets.append((
                f'[psij]     edge {name} (login node {scheduler}, '
                f'will submit a child via PsiJ)',
                {'kind'     : 'login',
                 'edge_name': name,
                 'executor' : executor}))
    try:
        cx = bc.get_edge_client('bridge').get_plugin('iri_connect')
        for ep_key, ep_info in cx.list_endpoints().items():
            if not IRI_DEFAULTS.get(ep_key, {}).get('enabled', True):
                print(f'  (skipped iri:{ep_key}: disabled in IRI_DEFAULTS)')
                continue
            note  = ' (already connected)' if ep_info.get('connected') \
                                           else ' (will submit a job)'
            label = (f'[iri]      {ep_key} — IRI endpoint at '
                     f'{ep_info["label"]}{note}')
            targets.append((label, {'kind': 'iri', 'endpoint': ep_key}))
    except Exception as exc:
        print(f'  (iri_connect unavailable: {exc})')
    return targets


# ─────────────────────────────────────────────────────────────────────────────
#  IRI launch path
# ─────────────────────────────────────────────────────────────────────────────

def configure_iri(endpoint):
    d = dict(IRI_DEFAULTS[endpoint])
    print(f'\n— Configure IRI endpoint: {endpoint} —')
    d['resource_id']  = ask     ('  resource id',                d['resource_id'])
    d['account']      = ask     ('  account / project',          d['account']) or None
    d['workdir']      = ask     ('  working directory (or empty)',
                                  d['workdir'] or '') or None
    d['home_dir']     = ask     ('  user $HOME on the target',
                                  d.get('home_dir') or '') or None
    d['queue_name']   = ask     ('  queue / partition',          d['queue_name'])
    d['walltime_min'] = ask_int ('  walltime (minutes)',         d['walltime_min'])
    d['n_nodes']      = ask_int ('  number of nodes',            d['n_nodes'])
    d['constraint']   = ask     ('  constraint (or empty)',      d['constraint'] or '') or None
    d['reservation']  = ask     ('  reservation (or empty)',     d['reservation'] or '') or None
    d['login_host']   = ask     ('  login host (for --tunnel)',  d['login_host'])
    d['tunnel']       = confirm ('  open SSH tunnel from compute node?', d['tunnel'])
    if not d['account']:
        raise RuntimeError(f'IRI {endpoint}: account/project is required')
    if not d['home_dir']:
        raise RuntimeError(f'IRI {endpoint}: home_dir on target is required '
                           f'(used to resolve <home>/{d.get("amsc_dir") or ".amsc"}'
                           f'/ve/bin/radical-edge-wrapper.sh)')
    return d


def read_token(endpoint):
    path = AMSC_DIR / f'token_{endpoint}'
    if not path.exists():
        raise RuntimeError(
            f'token file missing: {path}  (put your IRI bearer token '
            f'there, literal string only)')
    token = path.read_text().strip()
    if not token:
        raise RuntimeError(f'token file is empty: {path}')
    return token


def launch_iri(bc, endpoint, cfg, bridge_url):
    cx    = bc.get_edge_client('bridge').get_plugin('iri_connect')
    token = read_token(endpoint)
    iri   = cx.connect(endpoint=endpoint, token=token)
    edge_name = f'amsc-{endpoint}-{uuid.uuid4().hex[:6]}'
    args = ['--name', edge_name, '--url', bridge_url]
    if cfg['tunnel']:
        args += ['--tunnel', '--tunnel-via', cfg['login_host']]
    attrs = {
        'queue_name': cfg['queue_name'],
        'duration'  : cfg['walltime_min'] * 60,
        'account'   : cfg['account'],
    }
    if cfg['constraint']:  attrs['constraint']  = cfg['constraint']
    if cfg['reservation']: attrs['reservation'] = cfg['reservation']
    home    = cfg['home_dir'].rstrip('/')
    amsc    = (cfg.get('amsc_dir') or '.amsc').strip('/')
    wrapper = f'{home}/{amsc}/ve/bin/radical-edge-wrapper.sh'
    env = {'RADICAL_BRIDGE_URL': bridge_url}
    env.update(cfg['environment'])
    if cfg.get('setup'):
        env['RADICAL_EDGE_SETUP'] = '; '.join(cfg['setup'])
    job_spec = {
        'executable' : wrapper,
        'arguments'  : args,
        'name'       : edge_name,
        'resources'  : {'node_count': cfg['n_nodes'], 'process_count': 1},
        'attributes' : attrs,
        'environment': env,
    }
    if cfg.get('workdir'):
        job_spec['directory'] = cfg['workdir']
    print(f'  submitting IRI job ({endpoint} → {cfg["resource_id"]}, '
          f'edge name: {edge_name})…')
    job = iri.submit_job(cfg['resource_id'], job_spec)
    print(f'  IRI job_id: {job["job_id"]}')
    return {
        'kind'       : 'iri',
        'iri'        : iri,
        'endpoint'   : endpoint,
        'resource_id': cfg['resource_id'],
        'job_id'     : job['job_id'],
        'edge_name'  : edge_name,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  PsiJ launch path
# ─────────────────────────────────────────────────────────────────────────────

def configure_psij(edge_name, executor):
    d = MACHINE_DEFAULTS.get(edge_name, {})
    print(f'\n— Configure PsiJ submission via edge: {edge_name} '
          f'(executor: {executor}) —')
    cfg = {
        'executor'    : executor,
        'queue_name'  : ask     ('  queue / partition',
                                  d.get('queue_name') or '') or None,
        'account'     : ask     ('  account / project',
                                  d.get('account', '') or '') or None,
        'walltime_min': ask_int ('  walltime (minutes)',
                                  d.get('walltime_min', 30)),
        'n_nodes'     : ask_int ('  number of nodes',
                                  d.get('n_nodes', 1)),
        'constraint'  : ask     ('  constraint (or empty)',
                                  d.get('constraint') or '') or None,
        'tunnel'      : confirm ('  open SSH tunnel from compute node?',
                                  d.get('tunnel', True)),
        'amsc_dir'    : d.get('amsc_dir'),
        'setup'       : list(d.get('setup') or []),
        'qos'         : d.get('qos'),
    }
    if not cfg['account']:
        raise RuntimeError(f'edge {edge_name}: account/project is required')
    return cfg


def launch_psij(bc, edge_name, cfg, bridge_url):
    edge = bc.get_edge_client(edge_name)
    psij = edge.get_plugin('psij')
    home    = edge.get_plugin('sysinfo').homedir().rstrip('/')
    amsc    = (cfg.get('amsc_dir') or '.amsc').strip('/')
    wrapper = f'{home}/{amsc}/ve/bin/radical-edge-wrapper.sh'
    child_name = f'amsc-{edge_name}-{uuid.uuid4().hex[:6]}'
    attrs = {
        'duration'  : cfg['walltime_min'] * 60,
        'account'   : cfg['account'],
    }
    if cfg.get('queue_name'):
        attrs['queue_name'] = cfg['queue_name']
    custom_attrs = {}
    if cfg.get('constraint'):
        custom_attrs[f'{cfg["executor"]}.constraint'] = cfg['constraint']
    if cfg.get('qos'):
        custom_attrs[f'{cfg["executor"]}.qos'] = cfg['qos']
    env = {'RADICAL_BRIDGE_URL': bridge_url}
    if cfg.get('setup'):
        env['RADICAL_EDGE_SETUP'] = '; '.join(cfg['setup'])
    job_spec = {
        'executable'        : wrapper,
        'arguments'         : ['--name', child_name, '--url', bridge_url],
        'attributes'        : attrs,
        'custom_attributes' : custom_attrs,
        'resources'         : {'node_count': cfg['n_nodes'], 'process_count': 1},
        'environment'       : env,
    }
    print(f'  submitting PsiJ job via {edge_name} (executor: {cfg["executor"]}, '
          f'edge name: {child_name})…')
    res = psij.submit_tunneled(job_spec, executor=cfg['executor'],
                               tunnel=cfg['tunnel'])
    print(f'  PsiJ job_id: {res["job_id"]}')
    return {
        'kind'       : 'psij',
        'psij'       : psij,
        'parent_edge': edge_name,
        'job_id'     : res['job_id'],
        'edge_name'  : res.get('edge_name', child_name),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Edge polling
# ─────────────────────────────────────────────────────────────────────────────

def wait_for_first_edge(bc, expected_names, timeout=EDGE_WAIT_SECONDS,
                        poll=3.0, heartbeat=30.0):
    if not expected_names:
        raise RuntimeError('no expected edges — nothing to wait for')
    print(f'\n— Waiting for first edge to come up '
          f'(any of: {", ".join(expected_names)}) —')
    start_time = time.time()
    last_beat  = start_time
    while time.time() - start_time < timeout:
        live = set(bc.list_edges())
        for name in expected_names:
            if name in live:
                return name
        time.sleep(poll)
        if time.time() - last_beat >= heartbeat:
            elapsed = int(time.time() - start_time)
            print(f'  …{elapsed}s elapsed, {timeout - elapsed}s left')
            last_beat = time.time()
    raise TimeoutError(f'no edge appeared within {timeout}s; '
                       f'expected one of {expected_names}')


# ─────────────────────────────────────────────────────────────────────────────
#  Teardown
# ─────────────────────────────────────────────────────────────────────────────

def teardown(bc, created):
    print('\n— Tearing down resources we created —')
    for c in created:
        if c['kind'] != 'iri':
            continue
        try:
            c['iri'].cancel_job(c['resource_id'], c['job_id'])
            print(f'  cancelled IRI job {c["job_id"]}@{c["endpoint"]}')
        except Exception as exc:
            print(f'  could not cancel IRI job {c["job_id"]}: {exc}')
    for c in created:
        if c['kind'] != 'psij':
            continue
        try:
            c['psij'].cancel_job(c['job_id'])
            print(f'  cancelled PsiJ job {c["job_id"]} on {c["parent_edge"]}')
        except Exception as exc:
            print(f'  could not cancel PsiJ job {c["job_id"]}: {exc}')
    iri_eps = {c['endpoint'] for c in created if c['kind'] == 'iri'}
    if iri_eps:
        cx = bc.get_edge_client('bridge').get_plugin('iri_connect')
        for ep in iri_eps:
            try:
                cx.disconnect(ep)
                print(f'  disconnected IRI endpoint {ep}')
            except Exception as exc:
                print(f'  could not disconnect IRI {ep}: {exc}')


# ─────────────────────────────────────────────────────────────────────────────
#  Generic run driver — use-case agnostic
# ─────────────────────────────────────────────────────────────────────────────

def run(workflow_fn):
    """
    Generic AMSC service entry point.

    Handles BridgeClient setup, target discovery, edge selection, job launch,
    edge polling, and teardown.  Calls workflow_fn(bridge_url, edge_name) once
    the first edge is ready.  Use-case scripts call this as:

        if __name__ == '__main__':
            service_utils.run(run_rose_workflow)
    """
    _lock = open('/tmp/amsc.lock', 'w')
    try:    fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit('another instance is already running; kill it first.')

    bc         = BridgeClient()
    bridge_url = bc.url
    print(f'Bridge: {bridge_url}')
    try:
        targets = discover_targets(bc)
        if not targets:
            sys.exit('No usable targets discovered.  '
                     'Start at least one edge or expose iri_connect.')

        picks = select_many(targets, 'Pick targets to use:')
        if not picks:
            sys.exit('No targets selected.')

        created        = []
        expected_edges = []

        try:
            for t in picks:
                try:
                    if t['kind'] == 'compute':
                        expected_edges.append(t['edge_name'])
                        print(f'\n— Reusing ready edge: {t["edge_name"]} —')
                    elif t['kind'] == 'iri':
                        cfg = configure_iri(t['endpoint'])
                        rec = launch_iri(bc, t['endpoint'], cfg, bridge_url)
                        created.append(rec)
                        expected_edges.append(rec['edge_name'])
                    elif t['kind'] == 'login':
                        cfg = configure_psij(t['edge_name'], t['executor'])
                        rec = launch_psij(bc, t['edge_name'], cfg, bridge_url)
                        created.append(rec)
                        expected_edges.append(rec['edge_name'])
                except Exception as exc:
                    label = t.get('edge_name') or t.get('endpoint') or repr(t)
                    print(f'\n— launch failed for {label}: {exc} —')
                    print('  (continuing with remaining targets)')

            if not expected_edges:
                sys.exit('No targets launched successfully — nothing to run.')
            first = wait_for_first_edge(bc, expected_edges)
            print(f'\n— First edge up: {first} —')
            import asyncio
            asyncio.run(workflow_fn(bridge_url, first))

        finally:
            teardown(bc, created)

    finally:
        bc.close()

    print('\nDone.')
