"""
M3DC1 streaming digital twin.

This is a version of the M3DC1 streaming surrogate that uses the digital twin
framework.

Because we are using one active learner and only care about one physics
property, it's simplest to use just a single DT model investigator (no need for
a ScienceAgent. The point of a science agent is in the event you have various
surrogates with separate ALs)

Also, in the M3DC1 streaming example, it assumes a ThreadedPoolExecutor, and all
tasks running on the same machine. This is due to the use of "buffer" inside the
simulation task. However, we want to demonstrate this code working across
machines, so this restriction must be lifted.

A key point here is that the simulation task "waits" for new data. As the
ParallelActiveLearner is used, we don't have the flexibility to trigger the
simulation when we want to ourselves.

Currently, the purpose of the simulation is to simply wait until the data is
available. So,

"""

import asyncio
import json
from pathlib import Path
import shlex

import cloudpickle
from digitaltwin import (
    ModelInvestigator,
    RuntimeAPI,
    TypedData,
    UtilityTask,
    WindowedTypeData,
)
import numpy as np
import pandas as pd
from radical.asyncflow import WorkflowEngine
from rose import LearnerConfig, TaskConfig
from rose.al import ParallelActiveLearner
import redis
from dtypes import M3DC1_PREDICTION

# ── Row-budget policy (mirrors amsc.py's growing-pool logic) ─────────────────
# At iteration i, the simulation task requests N_BASE + i * N_STEP rows from
# the buffer.  Increase N_STEP to consume more data per iteration.
N_BASE = 100
N_STEP = 100


# Workspace for iteration artefacts (parquet snapshots, metric JSON)
_HERE = Path(__file__).resolve().parent
_WORKSPACE = _HERE / "workspace"


def _workspace_iter(iteration: int, label: str) -> Path:
    d = _WORKSPACE / f"{label}" / f"iter_{iteration:03d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _candidate_configs(candidates: list[str], max_iter: int) -> list[LearnerConfig]:
    configs = []
    for idx, family in enumerate(candidates):
        label = f"{idx}_{family}"
        kwargs = {"learner_label": label, "model_family": family}
        schedule = {
            i: TaskConfig(kwargs={**kwargs, "iteration": i})
            for i in range(max_iter + 1)
        }
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


class M3DC1_Investigator(ModelInvestigator):
    def __init__(
        self,
        flow: WorkflowEngine,
        candidates: list[str],
        max_iter: int,
        buffer_max: int,
        r2_threshold: float,
        redis_endpoint: str,
        redis_key: str,
    ):
        super().__init__(flow)

        self.learner = ParallelActiveLearner(flow)
        self.candidates = candidates
        self.max_iter = max_iter
        self.r2_threshold = r2_threshold
        self.buffer_max = buffer_max

        self.all_data: list[dict] = []

        # use REDIS for communication from the investigator to the Simulation.
        # see note at top of file. This is required as the simulation task
        # itself it waiting for data. (Other DT examples have it where the
        # simulation task is fired after receiving the data.)
        host, port = redis_endpoint.rsplit(":", 1)
        self.redis = redis.Redis(host=host, port=int(port), decode_responses=True)
        self.redis_key = redis_key
        # ensure start clear
        for candidate in self.candidates:
            self.redis.delete(f"{redis_key}/{candidate}")

        # ── Simulation task ───────────────────────────────────────────────────────
        # KEY CHANGE vs amsc_stream. Buffered inputs come in from the DT.

        @self.learner.simulation_task(as_executable=False)
        async def simulation(*args, **kwargs) -> dict:
            import time
            import redis as _redis
            import pandas as pd

            it = int(kwargs.get("iteration", 0))
            label = str(kwargs["learner_label"])
            n_rows = N_BASE + it * N_STEP
            family = str(kwargs["model_family"])

            host, port_str = redis_endpoint.rsplit(":", 1)
            redis_client = _redis.Redis(
                host=host, port=int(port_str), decode_responses=True
            )

            print(f"  [sim {label} iter={it}] waiting for {n_rows} rows …", flush=True)
            deadline = time.monotonic() + 600.0
            while not redis_client.exists(
                redis_key + "/MAIN"
            ) or not redis_client.exists(f"{redis_key}/{family}"):
                time.sleep(0.5)
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Timeout waiting for {n_rows} sensor rows")

            resp = redis_client.get(redis_key + "/MAIN")
            assert resp is not None
            rows = json.loads(resp)
            redis_client.delete(f"{redis_key}/{family}")

            df = pd.DataFrame(rows)

            out_dir = _workspace_iter(it, label)
            parquet = out_dir / "sensor_snapshot.parquet"
            df.to_parquet(parquet, index=False)

            meta = {
                "iteration": it,
                "learner_label": label,
                "dataset": str(parquet),
                "n_rows": len(df),
                "source": "redis_stream",
            }
            (out_dir / "simulation.json").write_text(json.dumps(meta, indent=2))
            return meta

        # ── Training task ─────────────────────────────────────────────────────────
        # Fits a surrogate model locally using sklearn.
        # Replace with subprocess to surge_train.py if running on HPC.

        @self.learner.training_task(as_executable=False)
        async def training(sim_result: str, **kwargs) -> dict:
            import pandas as pd
            from sklearn.ensemble import (
                GradientBoostingRegressor,
                RandomForestRegressor,
            )
            from sklearn.linear_model import Ridge
            from sklearn.metrics import mean_squared_error, r2_score
            from sklearn.model_selection import train_test_split
            from sklearn.neural_network import MLPRegressor
            from sklearn.preprocessing import StandardScaler
            from sklearn.pipeline import Pipeline

            it = int(kwargs.get("iteration", sim_result["iteration"]))
            label = str(kwargs["learner_label"])
            family = str(kwargs.get("model_family", "rf"))

            df = pd.read_parquet(sim_result["dataset"])
            X = df.drop(columns=["output_gamma"]).values
            y = df["output_gamma"].values

            X_train, X_val, y_train, y_val = train_test_split(
                X, y, test_size=0.2, random_state=it
            )

            _models = {
                "rf": RandomForestRegressor(
                    n_estimators=100, random_state=42, n_jobs=-1
                ),
                "mlp": Pipeline(
                    [
                        ("scaler", StandardScaler()),
                        (
                            "net",
                            MLPRegressor(
                                hidden_layer_sizes=(64, 64),
                                max_iter=500,
                                random_state=42,
                            ),
                        ),
                    ]
                ),
                "gbr": GradientBoostingRegressor(n_estimators=100, random_state=42),
                "ridge": Pipeline(
                    [
                        ("scaler", StandardScaler()),
                        ("reg", Ridge()),
                    ]
                ),
            }
            model = _models.get(family, _models["rf"])
            model.fit(X_train, y_train)

            y_pred = model.predict(X_val)
            val_r2 = float(r2_score(y_val, y_pred))
            val_rmse = float(np.sqrt(mean_squared_error(y_val, y_pred)))

            metrics = {
                "iteration": it,
                "learner_label": label,
                "model_family": family,
                "val_r2": val_r2,
                "val_rmse": val_rmse,
                "n_train": int(len(X_train)),
                "n_val": int(len(X_val)),
            }
            out_dir = _workspace_iter(it, label)
            (out_dir / "surge_metrics.json").write_text(json.dumps(metrics, indent=2))

            # save
            model_path = str((out_dir / "model.pkl"))
            with open(model_path, "wb") as f:
                cloudpickle.dump(model, f)
            return {"simulation": sim_result, "surge": metrics, "model": model_path}

        # ── Active-learning task ──────────────────────────────────────────────────
        @self.learner.active_learn_task(as_executable=False)
        async def active_learn(sim_result: dict, train_bundle: dict, **kwargs) -> dict:
            it = int(kwargs.get("iteration", train_bundle["simulation"]["iteration"]))
            label = str(kwargs["learner_label"])
            surge = train_bundle["surge"]

            decision = {
                "iteration": it,
                "learner_label": label,
                "policy": "monitor_best_val_r2",
                "val_r2": surge["val_r2"],
                "val_rmse": surge["val_rmse"],
                "model": train_bundle["model"],
            }
            out_dir = _workspace_iter(it, label)
            (out_dir / "active.json").write_text(json.dumps(decision, indent=2))
            return {
                "iteration": it,
                "learner_label": label,
                "train": train_bundle,
                "val_r2": surge["val_r2"],
                "val_rmse": surge["val_rmse"],
                "model": train_bundle["model"],
            }

        # ── Stop criterion ────────────────────────────────────────────────────────
        @self.learner.as_stop_criterion(
            metric_name="val_r2",
            threshold=r2_threshold,
            operator=">=",
            as_executable=False,
        )
        async def stop_on_r2(*args, **kwargs) -> float:
            it = int(kwargs.get("iteration", 0))
            label = str(kwargs["learner_label"])
            path = _workspace_iter(it, label) / "surge_metrics.json"
            meta = json.loads(path.read_text())
            r2 = float(meta["val_r2"])
            forced = it >= max_iter - 1 and r2 < r2_threshold
            return r2_threshold if forced else r2

        @self.flow.function_task
        async def do_inference(in_data: WindowedTypeData, model=None):
            # the ASMC_stream.py demo doesn't tackle streaming inference.
            # Put streaming inference code here.
            if model is None:
                return TypedData(M3DC1_PREDICTION, None)

            with open(model, "rb") as f:
                model_obj = cloudpickle.load(f)

            df = pd.DataFrame(in_data.sequence)

            X = df.drop(columns=["output_gamma"]).values
            out = model_obj.predict(X)

            return TypedData(M3DC1_PREDICTION, out)

        self.inference = do_inference

    async def input_callback(self, in_data: WindowedTypeData):
        # add the data to large database
        self.all_data += in_data.sequence
        # trigger event
        # put all_data onto redis

        if len(self.all_data) > self.buffer_max:
            self.all_data = self.all_data[-self.buffer_max :]

        self.redis.set(self.redis_key + "/MAIN", json.dumps(self.all_data))
        for c in self.candidates:
            self.redis.set(f"{self.redis_key}/{c}", 1)

    async def main_loop(self, runtime: RuntimeAPI):
        # call the pipeline

        runtime.subscribe_to_topic(runtime.ON_INPUT, self.input_callback)
        runtime.set_inference_task(self.inference)
        runtime.publish_new_model({"model": None})

        configs = _candidate_configs(self.candidates, self.max_iter)
        rows: list[dict] = []

        async for state in self.learner.start(
            parallel_learners=len(self.candidates),
            max_iter=self.max_iter,
            learner_configs=configs,
        ):
            label = self.candidates[int(state.learner_id)]
            rows.append(
                {
                    "learner": label,
                    "iter": state.iteration,
                    "val_r2": state.val_r2,
                    "val_rmse": state.val_rmse,
                }
            )
            print(
                "\nMODEL PUBLISHED -----------------------------------"
                f"  learner={label}  iter={state.iteration}\n"
                f"  val_r2={state.val_r2:.5f}  val_rmse={state.val_rmse:.5f}\n"
                f"  buffer={len(self.all_data)} obs\n"
                f" ---------------------------------------------------\n",
                flush=True,
            )

            # publish model with stats
            runtime.publish_new_model({"model": state.model}, rows[-1])

            if len(rows) >= len(self.candidates) * self.max_iter:
                break


# this is needed to
class OutputSink(UtilityTask):
    def __init__(self, flow):
        super().__init__(flow)

    async def main_loop(self, runtime, in_data: TypedData):
        print("Received: ", in_data.data)
