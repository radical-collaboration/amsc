#!/usr/bin/env python3
"""
HEAT Optical Heat Flux Surrogate via ROSE — Edge Service version

Combines the service scaffolding from run_rose_via_service.py with the
HEAT active-learning workflow from rose_heat_workflow_v2.py.

Architecture
============

  Client (this script, login node or laptop)
        │
        │  HTTPS / WebSocket
        ▼
   ╔══════════╗      ┌── pre-existing edge   (HPC compute node, ready to run)
   ║  Bridge  ║─────►├── pre-existing edge   (HPC login node, runs PsiJ)
   ╚══════════╝      ├── new edge ★          (spawned via IRI)
                     └── new edge ★          (spawned via PsiJ ↦ submit_tunneled)

run_rose_workflow() runs the HEAT surrogate loop on whichever edge comes
up first.  The synthetic sim/train loop from run_rose_via_service.py is
replaced entirely by the HEAT physics workflow:

  simulation  (as_executable=True)  → podman-hpc command, edge executes it
  training    (as_executable=False) → parses HEAT CSV, trains GP surrogate
  active_learn(as_executable=False) → max-uncertainty sampling, seeds next run
  check_convergence (stop criterion) → mean(GP_std / y_std), stops at 0.05

Surrogate learns: (lqCN, lqCF, S, P, radFrac, fracCN, fracCF) → q_max [MW/m²]
Physics: Eich optical heat flux on NSTX-U geometry
"""

import asyncio
import logging
import os
import sys
import time
import uuid
from pathlib import Path

import numpy as np

from radical.edge.client import BridgeClient

import rhapsody
from radical.asyncflow      import WorkflowEngine
from rose.al.active_learner import SequentialActiveLearner
from rose.learner           import LearnerConfig, TaskConfig
from rose.integrations.mlflow_tracker import MLflowTracker

rhapsody.enable_logging(level=logging.WARNING)


# ─────────────────────────────────────────────────────────────────────────────
#  HEAT workflow knobs
# ─────────────────────────────────────────────────────────────────────────────

WORK_DIR = Path("/global/homes/a/aymen64/RADICAL/M3CD1-AMSC-MAY-DEMO/HEAT-WORK/HEATrun")
DATA_DIR = Path("/global/homes/a/aymen64/RADICAL/M3CD1-AMSC-MAY-DEMO/HEAT-WORK/output")
IMAGE    = "docker.io/plasmapotential/heat:test-build"

STATE_FILE = WORK_DIR / "rose_state.pkl"

PARAM_KEYS = ["lqCN", "lqCF", "S", "P", "radFrac", "fracCN", "fracCF"]
PARAM_LO   = np.array([0.5,  2.0, 0.5,  5.0, 0.1, 0.4, 0.1])
PARAM_HI   = np.array([5.0, 15.0, 5.0, 20.0, 0.8, 0.8, 0.6])

MAX_ITER             = 10
CONVERGENCE_THRESHOLD = 0.05


# ─────────────────────────────────────────────────────────────────────────────
#  Service knobs
# ─────────────────────────────────────────────────────────────────────────────

EDGE_WAIT_SECONDS = 30 * 60 * 1000

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

AMSC_DIR = Path(os.environ.get('AMSC_DIR') or Path.home() / '.amsc').expanduser()


# Inject X-Api-Key into all MLflow REST calls
def enable_amsc_x_api_key():

    import mlflow.utils.rest_utils as rest_utils
    api_key = os.environ["AM_SC_API_KEY"]
    if api_key:
        _orig = rest_utils.http_request
        def patched(host_creds, endpoint, method, *args, **kwargs):
            h = dict(kwargs.get("headers") or kwargs.get("extra_headers") or {})
            h["X-Api-Key"] = api_key
            kwargs["headers" if "headers" in kwargs else "extra_headers"] = h
            return _orig(host_creds, endpoint, method, *args, **kwargs)
        rest_utils.http_request = patched


enable_amsc_x_api_key()





# ─────────────────────────────────────────────────────────────────────────────
#  Prompt helpers (unchanged from run_rose_via_service.py)
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
#  Target discovery (unchanged from run_rose_via_service.py)
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
#  IRI launch path (unchanged from run_rose_via_service.py)
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
#  PsiJ launch path (unchanged from run_rose_via_service.py)
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
#  Wait for first edge (unchanged from run_rose_via_service.py)
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
#  ROSE / HEAT workflow — replaces the synthetic run_rose_workflow.
#
#  Tasks are defined as closures so they carry everything they need when
#  serialised and shipped to the remote edge (no module-level imports assumed
#  present on the HPC side).  Each task does its own imports internally.
#
#  State is shared via a pickle file on the bind-mounted filesystem
#  (same mechanism as rose_heat_workflow_v2.py).
# ─────────────────────────────────────────────────────────────────────────────

async def run_rose_workflow(bridge_url, edge_name):
    """Run the HEAT surrogate loop using the named edge as a Dragon backend."""
    print(f'\n— Running HEAT surrogate on edge "{edge_name}" (bridge: {bridge_url}) —')

    # Snapshot module-level constants so closures below capture plain values,
    # not the module globals (safer for serialisation across process boundaries).
    _work_dir   = WORK_DIR
    _data_dir   = DATA_DIR
    _image      = IMAGE
    _state_file = STATE_FILE
    _param_keys = PARAM_KEYS

    # ── Backend + learner ────────────────────────────────────────────────────
    backend   = rhapsody.get_backend('edge', bridge_url=bridge_url,
                                     edge_name=edge_name)
    engine    = await backend
    asyncflow = await WorkflowEngine.create(engine)
    learner   = SequentialActiveLearner(asyncflow)

    # ── Shared-state helpers (closures, not module-level, for portability) ──

    def _save_state(**kwargs):
        import pickle
        with open(_state_file, "wb") as f:
            pickle.dump(kwargs, f)

    def _load_state():
        import pickle
        with open(_state_file, "rb") as f:
            return pickle.load(f)

    def _write_nstxu_input_csv(params):
        import numpy as _np
        input_path = _work_dir / "nstx" / "NSTXU_input.csv"
        lines_out  = []
        with open(input_path) as f:
            for line in f:
                key = line.split(",")[0].strip()
                if key in _param_keys:
                    lines_out.append(
                        f"{key}, {params[_param_keys.index(key)]:.4f}\n")
                else:
                    lines_out.append(line)
        with open(input_path, "w") as f:
            f.writelines(lines_out)

    def _read_current_params():
        import numpy as _np
        params = {}
        with open(_work_dir / "nstx" / "NSTXU_input.csv") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "," in line:
                    k, v = [s.strip() for s in line.split(",", 1)]
                    params[k] = v
        return _np.array([float(params[k]) for k in _param_keys])

    def _parse_heat_q_max():
        import pandas as pd
        out_dir   = _data_dir / "data" / "nstx_204118_opticalExample"
        csv_files = list(out_dir.rglob("HF_optical_all.csv"))
        if not csv_files:
            raise FileNotFoundError(f"No HEAT output CSVs found under {out_dir}")
        q_max = 0.0
        for f in csv_files:
            df    = pd.read_csv(f, comment="#", header=None)
            q_max = max(q_max, float(df.iloc[:, 3].max()))
        return q_max

    # ── Seed the parameter pool (local math, no filesystem needed) ──────────
    from scipy.stats import qmc
    sampler = qmc.LatinHypercube(d=len(_param_keys), seed=42)
    X_pool  = qmc.scale(sampler.random(n=50), PARAM_LO, PARAM_HI)

    # ── Write NSTXU_input.csv + initial pickle on the remote edge ────────────
    # These files live on the HPC side, not on the client.  We ship a
    # self-contained function_task so all file I/O happens remotely.
    @asyncflow.function_task
    async def init_state(first_params_list: list, pool_rest_list: list,
                         work_dir_str: str, state_file_str: str,
                         param_keys: list):
        import numpy as np
        import pickle
        from pathlib import Path

        work_dir     = Path(work_dir_str)
        state_file   = Path(state_file_str)
        first_params = np.array(first_params_list)
        pool_rest    = np.array(pool_rest_list)

        input_path = work_dir / "nstx" / "NSTXU_input.csv"
        lines_out  = []
        with open(input_path) as f:
            for line in f:
                key = line.split(",")[0].strip()
                if key in param_keys:
                    lines_out.append(
                        f"{key}, {first_params[param_keys.index(key)]:.4f}\n")
                else:
                    lines_out.append(line)
        with open(input_path, "w") as f:
            f.writelines(lines_out)

        with open(state_file, "wb") as f:
            pickle.dump({"X_labeled": None, "y_labeled": None,
                         "X_pool": pool_rest, "gp": None, "scaler": None}, f)

    await init_state(X_pool[0].tolist(), X_pool[1:].tolist(),
                     str(_work_dir), str(_state_file), list(_param_keys))

    # ── Task definitions ─────────────────────────────────────────────────────

    @learner.simulation_task(as_executable=True, capture_stdio=True)
    async def simulation(*args):
        return (
            f"/global/u2/a/aymen64/.amsc/ve/bin/python3 /usr/bin/podman-hpc run --annotation podman_hpc.hook_tool=false --rm "
            f"-v {_work_dir}:/root/terminal "
            f"-v {_data_dir}:/root/HEAT "
            f"{_image} "
            f"--m t --f /root/terminal/batchFile.dat"
        )


    @learner.training_task(as_executable=False)
    async def training(*args, length_scale: float = 1.0):
        import numpy as np
        from sklearn.gaussian_process         import GaussianProcessRegressor
        from sklearn.gaussian_process.kernels import Matern
        from sklearn.preprocessing            import StandardScaler

        state     = _load_state()
        X_new     = _read_current_params().reshape(1, -1)
        y_new     = np.array([[_parse_heat_q_max()]])
        X_labeled = (np.vstack([state["X_labeled"], X_new])
                     if state["X_labeled"] is not None else X_new)
        y_labeled = (np.vstack([state["y_labeled"], y_new])
                     if state["y_labeled"] is not None else y_new)

        scaler = StandardScaler().fit(X_labeled)
        gp     = GaussianProcessRegressor(
            kernel=Matern(nu=2.5, length_scale=length_scale),
            n_restarts_optimizer=5,
            normalize_y=True,
        )
        gp.fit(scaler.transform(X_labeled), y_labeled.ravel())

        _save_state(X_labeled=X_labeled, y_labeled=y_labeled,
                    X_pool=state["X_pool"], gp=gp, scaler=scaler)
        return {"n_samples": len(y_labeled), "length_scale": length_scale}

    @learner.active_learn_task(as_executable=False)
    async def active_learn(*args, n_select: int = 1):
        import numpy as np

        state              = _load_state()
        gp, scaler, X_pool = state["gp"], state["scaler"], state["X_pool"]
        _, std             = gp.predict(scaler.transform(X_pool), return_std=True)
        best_i             = int(np.argmax(std))
        next_params        = X_pool[best_i]

        _write_nstxu_input_csv(next_params)
        X_pool_new = np.delete(X_pool, best_i, axis=0)
        _save_state(**{**state, "X_pool": X_pool_new})

        return {
            "unlabeled_count":  len(X_pool_new),
            "mean_uncertainty": float(np.mean(std)),
            "max_uncertainty":  float(np.max(std)),
            "next_lqCN":        float(next_params[0]),
            "next_P_MW":        float(next_params[3]),
        }

    @learner.as_stop_criterion(metric_name="mean_uncertainty",
                               threshold=CONVERGENCE_THRESHOLD,
                               operator="<",
                               as_executable=False)
    async def check_convergence(*args) -> float:
        import numpy as np

        state = _load_state()
        if state["gp"] is None or state["X_labeled"] is None:
            return 1.0
        gp, scaler, X_pool = state["gp"], state["scaler"], state["X_pool"]
        if len(X_pool) == 0:
            return 0.0
        if len(state["y_labeled"]) < 2:
            return 1.0
        y_std = float(state["y_labeled"].std())
        if y_std < 1e-6:
            return 1.0
        _, std = gp.predict(scaler.transform(X_pool), return_std=True)
        return float((std / y_std).mean())


    learner.add_tracker(
        MLflowTracker(
            experiment_name="ROSE-HEAT-Surrogate-0000",
            run_name= "rose_heat_run",
        )
    )



    # ── Active-learning loop ─────────────────────────────────────────────────
    print('\nStarting HEAT surrogate loop\n' + '─' * 60, flush=True)
    async for state in learner.start(max_iter=MAX_ITER):
        print(f'[Iteration {state.iteration}]', flush=True)
        print(f'  uncertainty: {state.metric_value:.4f}  (target <{CONVERGENCE_THRESHOLD})',
              flush=True)
        print(f'  labeled:     {state.n_samples}', flush=True)
        print(f'  pool left:   {state.unlabeled_count}', flush=True)
        print(f'  mean/max unc: {state.mean_uncertainty:.4f} / '
              f'{state.max_uncertainty:.4f}', flush=True)
        print(f'  next params: lqCN={state.next_lqCN:.2f} mm  '
              f'P={state.next_P_MW:.1f} MW', flush=True)

        if state.mean_uncertainty and state.mean_uncertainty < 0.1:
            learner.set_next_config(
                LearnerConfig(active_learn=TaskConfig(kwargs={"n_select": 3}))
            )

        if state.unlabeled_count is not None and state.unlabeled_count < 3:
            print('Pool exhausted, stopping.', flush=True)
            break

    print('\n' + '=' * 60, flush=True)
    print(state.to_dict())

    await asyncflow.shutdown()

    if _state_file.exists():
        _state_file.unlink()


# ─────────────────────────────────────────────────────────────────────────────
#  Teardown (unchanged from run_rose_via_service.py)
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
#  Main (unchanged from run_rose_via_service.py)
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import fcntl
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
            asyncio.run(run_rose_workflow(bridge_url, first))

        finally:
            teardown(bc, created)

    finally:
        bc.close()

    print('\nDone.')


if __name__ == '__main__':
    main()
