#!/usr/bin/env python3
"""
Example 4 - ROSE ParallelActiveLearner model race — Edge Service version

Combines the service scaffolding from run_rose_via_service.py with the
SURGE parallel model race from 04_example_parallel_model_race.py.

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

run_rose_workflow() runs the ParallelActiveLearner SURGE race on whichever
edge comes up first.  The ConcurrentExecutionBackend from the original is
replaced by rhapsody.get_backend('edge', ...).

CLI flags (--dataset, --candidates, --max-iter, --r2-threshold, …) still
control the SURGE workflow; edge selection is handled interactively by the
service infrastructure.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import subprocess
import sys
import time
import uuid
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import rhapsody

rhapsody.enable_logging(level=logging.DEBUG)

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

from radical.edge.client import BridgeClient
from radical.asyncflow import WorkflowEngine

# _EX   — client-side path (resolved at import time, used for CLI helpers)
# _REMO — remote HPC path (hardcoded, captured into task closures so the
#          remote Dragon worker can find dataset_utils / surge_train.py etc.)
_EX   = Path(__file__).resolve().parent
_REMO = "/path/to/SURGE/examples/rose_orchestration"

if str(_EX) not in sys.path:
    sys.path.insert(0, str(_EX))


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
#  Service knobs
# ─────────────────────────────────────────────────────────────────────────────

EDGE_WAIT_SECONDS = 30 * 60

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
        edge         = bc.get_edge_client(name)
        plugins      = edge.list_plugins()
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
    args  = ['--name', edge_name, '--url', bridge_url]
    if cfg['tunnel']:
        args += ['--tunnel', '--tunnel-via', cfg['login_host']]
    attrs = {
        'duration'  : cfg['walltime_min'] * 60,
        'account'   : cfg['account'],
    }
    if cfg.get('queue_name'):
        attrs['queue_name'] = cfg['queue_name']
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
    home       = edge.get_plugin('sysinfo').homedir().rstrip('/')
    amsc       = (cfg.get('amsc_dir') or '.amsc').strip('/')
    wrapper    = f'{home}/{amsc}/ve/bin/radical-edge-wrapper.sh'
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
#  SURGE workflow helpers (module-level for pickling)
# ─────────────────────────────────────────────────────────────────────────────

def _candidate_configs(dataset: str, candidates: list[str], max_iter: int, growing_pool: bool):
    from rose.learner import LearnerConfig, TaskConfig
    from demo_common import canonical_workflow

    configs = []
    for idx, family in enumerate(candidates):
        workflow = canonical_workflow(dataset, family)
        label    = f"{idx}_{family}"
        kwargs   = {
            "learner_label": label,
            "workflow"     : workflow,
            "dataset"      : dataset,
            "growing_pool" : growing_pool,
        }
        schedule    = {i: TaskConfig(kwargs={**kwargs, "iteration": i}) for i in range(max_iter + 1)}
        schedule[-1] = TaskConfig(kwargs={**kwargs, "iteration": max_iter})
        configs.append(
            LearnerConfig(
                simulation=schedule,
                training=schedule,
                active_learn=schedule,
                criterion=schedule,
            )
        )
    return configs


# ─────────────────────────────────────────────────────────────────────────────
#  ROSE / SURGE workflow — replaces ConcurrentExecutionBackend with edge backend.
#
#  Signature matches the service pattern: (bridge_url, edge_name) plus
#  the SURGE-specific keyword args forwarded from main().
# ─────────────────────────────────────────────────────────────────────────────

async def run_rose_workflow(
    bridge_url: str,
    edge_name: str,
    *,
    dataset: str,
    candidates: list[str],
    max_iter: int,
    r2_threshold: float,
    growing_pool: bool,
    live_progress: bool,
    log_file: str | None,
    quiet: bool,
) -> None:
    from rose.al.active_learner import ParallelActiveLearner
    #from rose.integrations.clearml_tracker import ClearMLTracker
    from rose.integrations.mlflow_tracker import MLflowTracker

    from live_report import default_log_path, reset_log_file
    from orch_report import RunTimer, print_run_header

    print(f'\n— Running SURGE race on edge "{edge_name}" (bridge: {bridge_url}) —')

    os.environ["SURGE_ROSE_WORKSPACE_NAMESPACE"] = "example_04"
    log_path = Path(log_file) if log_file else default_log_path("example_04")
    if live_progress:
        reset_log_file(log_path)
    timer = RunTimer()

    if not live_progress:
        print_run_header(
            example="4 - ParallelActiveLearner model race (edge service)",
            max_iter=max_iter,
            workers=1,          # edge backend manages its own parallelism
            quiet=quiet,
            extra=(
                f"Dataset={dataset}. Candidates={candidates}. "
                f"Pool policy={'growing subset' if growing_pool else 'full dataset'}. "
                f"Stop each learner when val_r2 >= {r2_threshold}."
            ),
        )
    else:
        print(
            f"Example 4: Parallel SURGE model race | dataset={dataset} | "
            f"candidates={candidates} | log={log_path}",
            flush=True,
        )

    # ── Edge backend (replaces ConcurrentExecutionBackend) ───────────────────
    engine    = await rhapsody.get_backend('edge', bridge_url=bridge_url,
                                           edge_name=edge_name)
    asyncflow = await WorkflowEngine.create(engine)
    learner   = ParallelActiveLearner(asyncflow)

    #learner.add_tracker(
    #    ClearMLTracker(
    #        project_name="ROSE-AMSC-DEMO",
    #        task_name="surge_ensemble-run-02",
    #        learner_names=[f'Surge_{c.upper()}_Learner' for c in candidates],
    #    )
    #)


    # ── Task definitions (closures, identical to original _demo) ─────────────

    @learner.simulation_task(as_executable=False)
    async def simulation(*args, **kwargs):
        import sys as _sys
        import pandas as pd
        if _REMO not in _sys.path:
            _sys.path.insert(0, _REMO)
        from dataset_utils import build_training_parquet, training_row_plan, write_iteration_state
        from demo_common import workflow_fixed_rows

        it            = int(kwargs.get("iteration", 0))
        label         = str(kwargs["learner_label"])
        ns            = f"example_04/{label}"
        workflow      = str(kwargs["workflow"])
        fixed_rows    = workflow_fixed_rows(dataset, workflow, growing_pool=growing_pool)
        use_full_dataset = dataset == "m3dc1" and not growing_pool and fixed_rows is None
        plan = training_row_plan(
            it,
            dataset=dataset,
            fixed_rows=fixed_rows,
            use_full_dataset=use_full_dataset,
        )
        path = build_training_parquet(
            it,
            dataset=dataset,
            fixed_rows=fixed_rows,
            use_full_dataset=use_full_dataset,
            namespace=ns,
        )
        n    = pd.read_parquet(path).shape[0]
        meta = {
            "iteration"    : it,
            "learner_label": label,
            "workflow"     : workflow,
            "dataset"      : str(path),
            "n_rows"       : n,
            "n_rows_total" : plan["n_rows_total"],
            "row_policy"   : plan["row_policy"],
        }
        write_iteration_state(it, "simulation", meta, namespace=ns)
        return meta

    @learner.training_task(as_executable=False)
    async def training(sim_result, **kwargs):
        import sys as _sys
        import os as _os
        import subprocess as _subprocess
        from pathlib import Path as _Path
        if _REMO not in _sys.path:
            _sys.path.insert(0, _REMO)
        from dataset_utils import read_iteration_state

        it    = int(kwargs.get("iteration", sim_result["iteration"]))
        label = str(kwargs["learner_label"])
        ns    = f"example_04/{label}"
        cmd   = [
            _sys.executable,
            str(_Path(_REMO) / "surge_train.py"),
            "--workflow",      str(kwargs["workflow"]),
            "--iteration",     str(it),
            "--namespace",     ns,
            "--dataset-path",  str(sim_result["dataset"]),
            "--output-dir",    _REMO,
            "--run-tag-prefix", f"rose_parallel_{label}",
        ]
        _remote_log = str(_Path(_REMO) / "workspace" / "example_04" / "execution.log")
        if live_progress:
            cmd.extend(["--log-file", _remote_log])
        if not quiet and not live_progress:
            cmd.append("--verbose")
        env      = _os.environ.copy()
        root     = str(_Path(_REMO).parents[1])
        prev     = env.get("PYTHONPATH", "").strip()
        env["PYTHONPATH"] = root if not prev else root + _os.pathsep + prev
        completed = _subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        if completed.stdout and live_progress:
            with _Path(_remote_log).open("a", encoding="utf-8") as handle:
                handle.write("\n")
                handle.write(f"Parallel learner {label} command output:\n")
                handle.write(completed.stdout)
        out = read_iteration_state(it, "surge_metrics", namespace=ns)
        return {"simulation": sim_result, "surge": out}

    @learner.active_learn_task(as_executable=False)
    async def active_learn(sim_result, train_bundle, **kwargs):
        import sys as _sys
        if _REMO not in _sys.path:
            _sys.path.insert(0, _REMO)
        from dataset_utils import write_iteration_state

        it    = int(kwargs.get("iteration", train_bundle["simulation"]["iteration"]))
        label = str(kwargs["learner_label"])
        ns    = f"example_04/{label}"
        surge = train_bundle["surge"]
        decision = {
            "iteration"    : it,
            "learner_label": label,
            "policy"       : "monitor_best_val_r2",
            "val_r2"       : surge["val_r2"],
            "val_rmse"     : surge["val_rmse"],
            "splits"       : surge.get("splits", {}),
        }
        write_iteration_state(it, "active", decision, namespace=ns)
        return {
            "iteration"    : it,
            "learner_label": label,
            "train"        : train_bundle,
            # Flatten surge metrics so ROSE exposes them as state.* attributes,
            # letting _run_stream read them without touching the remote filesystem.
            "val_r2"       : surge["val_r2"],
            "val_rmse"     : surge["val_rmse"],
            "splits"       : surge.get("splits", {}),
            "run_tag"      : surge.get("run_tag", ""),
            "workflow"     : surge.get("workflow", ""),
        }

    @learner.as_stop_criterion(
        metric_name="val_r2",
        threshold=r2_threshold,
        operator=">=",
        as_executable=False,
    )
    async def stop_on_r2(*args, **kwargs):
        import sys as _sys
        if _REMO not in _sys.path:
            _sys.path.insert(0, _REMO)
        from dataset_utils import read_iteration_state, write_iteration_state

        it    = int(kwargs.get("iteration", 0))
        label = str(kwargs["learner_label"])
        ns    = f"example_04/{label}"
        meta  = read_iteration_state(it, "surge_metrics", namespace=ns)
        r2    = float(meta["val_r2"])
        forced_stop = it >= max_iter - 1 and r2 < r2_threshold
        write_iteration_state(
            it,
            "criterion",
            {
                "iteration"               : it,
                "metric"                  : "val_r2",
                "value"                   : r2,
                "forced_stop_after_max_iter": forced_stop,
            },
            namespace=ns,
        )
        return r2_threshold if forced_stop else r2

    # ── Active-learning loop ─────────────────────────────────────────────────
    configs = _candidate_configs(dataset, candidates, max_iter, growing_pool)
    rows: list[dict] = []

    learner.add_tracker(
        MLflowTracker(
            experiment_name="ROSE-SURGE-Surrogate-0005",
            run_name="surge_ensemble-run",
        )
    )


    async def _run_stream(progress=None) -> None:
        from orch_report import progress_bar

        async for state in learner.start(
            parallel_learners=len(candidates),
            max_iter=max_iter,
            learner_configs=configs,
        ):
            label = candidates[int(state.learner_id)]
            # Read metrics from ROSE state (returned by active_learn on the
            # remote side) — avoids reading remote filesystem from the client.
            meta  = {
                "val_r2"  : state.val_r2,
                "val_rmse": state.val_rmse,
                "splits"  : state.splits   or {},
                "run_tag" : state.run_tag  or "",
                "workflow": state.workflow or "",
            }
            rows.append({"learner": label, **meta})
            if progress:
                progress.update(
                    1,
                    learner=label,
                    r2=f"{float(meta['val_r2']):.4f}",
                    rmse=f"{float(meta['val_rmse']):.4g}",
                )
            else:
                print(
                    f"parallel {progress_bar(len(rows), len(candidates) * max_iter)} "
                    f"learner={label} iter={state.iteration} "
                    f"val_r2={float(meta['val_r2']):.5f} val_rmse={float(meta['val_rmse']):.5f} "
                    f"split={meta.get('splits', {}).get('train', '?')}/"
                    f"{meta.get('splits', {}).get('val', '?')}/"
                    f"{meta.get('splits', {}).get('test', '?')}",
                    flush=True,
                )
            if len(rows) >= len(candidates) * max_iter:
                learner.stop()
                break

    if live_progress:
        from live_report import LiveProgress, capture_output_to_log
        with LiveProgress(
            total=len(candidates) * max_iter,
            desc="SURGE candidates",
            enabled=True,
            unit="model",
        ) as progress:
            with capture_output_to_log(log_path):
                await _run_stream(progress)
                await learner.shutdown()
    else:
        await _run_stream(None)
        await learner.shutdown()

    from dataset_utils import workspace_dir
    rows.sort(key=lambda row: float(row["val_r2"]), reverse=True)
    print("\nExample 4 summary")
    print(f"Wall time: {timer.seconds():.1f}s")
    print(f"{'rank':>4}  {'learner':<8}  {'workflow':<12}  {'val_r2':>9}  {'val_rmse':>10}  {'run_tag'}")
    for rank, row in enumerate(rows, start=1):
        print(
            f"{rank:>4}  {row['learner']:<8}  {row['workflow']:<12}  "
            f"{float(row['val_r2']):>9.5f}  {float(row['val_rmse']):>10.6f}  {row['run_tag']}",
            flush=True,
        )
    print(f"Workspace: {workspace_dir('example_04')}")
    print(f"Log file:  {log_path}")


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
#  Main — parse SURGE args, then run service infrastructure
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    warnings.filterwarnings("ignore", message=".*GPflow.*", category=UserWarning)

    # ── Parse SURGE workflow args ─────────────────────────────────────────────
    from demo_common import add_dataset_cli, add_reporting_cli
    parser = argparse.ArgumentParser(
        description="Parallel ROSE/Rhapsody orchestration of SURGE candidates — edge service.")
    add_dataset_cli(parser)
    add_reporting_cli(parser)
    parser.add_argument(
        "--candidates",
        default="rf,mlp",
        help="Comma-separated model families: rf,mlp,gpr,gpflow_gpr.",
    )
    parser.add_argument("--max-iter",     type=int,   default=1)
    parser.add_argument("--r2-threshold", type=float, default=0.95)
    args       = parser.parse_args()
    candidates = [x.strip() for x in args.candidates.split(",") if x.strip()]
    invalid    = sorted(set(candidates) - {"rf", "mlp", "gpr", "gpflow_gpr"})
    if invalid:
        raise ValueError(f"Unsupported candidates: {invalid}; use rf and/or mlp.")
    if len(candidates) < 2:
        raise ValueError("Example 4 needs at least two candidates for ParallelActiveLearner.")

    rose_kwargs = dict(
        dataset=args.dataset,
        candidates=candidates,
        max_iter=args.max_iter,
        r2_threshold=args.r2_threshold,
        growing_pool=args.growing_pool,
        live_progress=not args.no_live_progress,
        log_file=args.log_file,
        quiet=args.quiet,
    )

    # ── Single-instance guard ─────────────────────────────────────────────────
    import fcntl
    _lock = open('/tmp/amsc.lock', 'w')
    try:    fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit('another instance is already running; kill it first.')

    # ── Service infrastructure ────────────────────────────────────────────────
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
            asyncio.run(run_rose_workflow(bridge_url, first, **rose_kwargs))

        finally:
            teardown(bc, created)

    finally:
        bc.close()

    print('\nDone.')


if __name__ == "__main__":
    main()
