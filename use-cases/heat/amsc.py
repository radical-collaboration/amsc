#!/usr/bin/env python3
"""
HEAT Optical Heat Flux Surrogate via ROSE — Edge Service version

Surrogate learns: (lqCN, lqCF, S, P, radFrac, fracCN, fracCF) → q_max [MW/m²]
Physics: Eich optical heat flux on NSTX-U geometry
"""

import asyncio
import logging
import sys
from pathlib import Path

import numpy as np
import rhapsody

from radical.asyncflow      import WorkflowEngine
from rose.al.active_learner import SequentialActiveLearner
from rose.learner           import LearnerConfig, TaskConfig
from rose.integrations.mlflow_tracker import MLflowTracker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import service_utils as service

rhapsody.enable_logging(level=logging.WARNING)
service.enable_amsc_x_api_key()


# ─────────────────────────────────────────────────────────────────────────────
#  HEAT workflow knobs — edit these for your setup
# ─────────────────────────────────────────────────────────────────────────────

WORK_DIR = Path("path/to/HEAT-WORK/HEATrun")
DATA_DIR = Path("path/to/HEAT-WORK/output")
IMAGE    = "plasmapotential/heat:test-build"

STATE_FILE = WORK_DIR / "rose_state.pkl"

PARAM_KEYS = ["lqCN", "lqCF", "S", "P", "radFrac", "fracCN", "fracCF"]
PARAM_LO   = np.array([0.5,  2.0, 0.5,  5.0, 0.1, 0.4, 0.1])
PARAM_HI   = np.array([5.0, 15.0, 5.0, 20.0, 0.8, 0.8, 0.6])

MAX_ITER              = 10
CONVERGENCE_THRESHOLD = 0.05


# ─────────────────────────────────────────────────────────────────────────────
#  ROSE / HEAT workflow
# ─────────────────────────────────────────────────────────────────────────────

async def run_rose_workflow(bridge_url, edge_name):
    """Run the HEAT surrogate AL loop on the named edge."""
    print(f'\n— Running HEAT surrogate on edge "{edge_name}" (bridge: {bridge_url}) —')

    _work_dir   = WORK_DIR
    _data_dir   = DATA_DIR
    _image      = IMAGE
    _state_file = STATE_FILE
    _param_keys = PARAM_KEYS

    backend   = rhapsody.get_backend('edge', bridge_url=bridge_url,
                                     edge_name=edge_name)
    engine    = await backend
    asyncflow = await WorkflowEngine.create(engine)
    learner   = SequentialActiveLearner(asyncflow)

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

    from scipy.stats import qmc
    sampler = qmc.LatinHypercube(d=len(_param_keys), seed=42)
    X_pool  = qmc.scale(sampler.random(n=50), PARAM_LO, PARAM_HI)

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

    @learner.simulation_task(as_executable=True, capture_stdio=True)
    async def simulation(*args):
        return (
            f"shifter --image={_image}"
            f" --volume={_work_dir}:/root/terminal;{_data_dir}:/root/HEAT"
            f" -- --m t --f /root/terminal/batchFile.dat"
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
            "unlabeled_count": len(X_pool_new),
            "next_lqCN":       float(next_params[0]),
            "next_P_MW":       float(next_params[3]),
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
            run_name="rose_heat_run",
        )
    )

    print('\nStarting HEAT surrogate loop\n' + '─' * 60, flush=True)
    async for state in learner.start(max_iter=MAX_ITER):
        print(f'[Iteration {state.iteration}]', flush=True)
        print(f'  uncertainty: {state.metric_value:.4f}  (target <{CONVERGENCE_THRESHOLD})',
              flush=True)

        if state.metric_value is not None and state.metric_value < 0.1:
            learner.set_next_config(
                LearnerConfig(active_learn=TaskConfig(kwargs={"n_select": 3}))
            )

        if state.unlabeled_count is not None and state.unlabeled_count < 3:
            print('Pool exhausted, stopping.', flush=True)
            break

    await asyncflow.shutdown()

    if _state_file.exists():
        _state_file.unlink()


if __name__ == '__main__':
    service.run(run_rose_workflow)
