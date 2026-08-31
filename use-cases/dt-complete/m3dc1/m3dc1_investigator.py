"""
M3DC1 streaming digital twin.

This is a version of the M3DC1 streaming surrogate that uses the digital twin
framework.

Because we are using one active learner and only care about one physics
property, it's simplest to use just a single DT model investigator (no need for
a ScienceAgent. The point of a science agent is in the event you have various
surrogates with separate ALs)

One tricky part is that the simulation task itself is waiting for streaming data
(opposed to the pipeline waiting and then launching the sim.). This requires a
way to transfer data from the investigator to the simulation task as the
simulation task is running. This example uses REDIS from the Rhapsody Data
Backend.

"""

DO_PRINT = False

import asyncio
import json
import os
from pathlib import Path

import cloudpickle
from digitaltwin import (
    ModelInvestigator,
    RuntimeAPI,
    TypedData,
    UtilityTask,
)
import numpy as np
import pandas as pd
from radical.asyncflow import WorkflowEngine
from rose import LearnerConfig, TaskConfig
from rose import Learner

from .m3dc1_dtypes import *

# Workspace for iteration artefacts (parquet snapshots, metric JSON).
# Resolved INSIDE the function, at task runtime: this module ships by
# value to the service and its tasks run on the remote endpoint, so a
# module-global path (evaluated on the client) would name a directory
# that does not exist there.  M3DC1_WORKSPACE overrides (e.g. $SCRATCH
# on an HPC endpoint); the default lands in the executing host's home.


def _workspace_iter(iteration: int, label: str) -> Path:
    base = Path(os.environ.get("M3DC1_WORKSPACE", "")
                or Path.home() / "m3dc1_workspace")
    d = base / f"{label}" / f"iter_{iteration:03d}"
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
        *,
        candidates: list[str],
        max_iter: int,
        buffer_max: int,
        window_size: int,
        r2_threshold: float,
    ):
        super().__init__(flow)

        self.learner = Learner(flow)
        self.candidates = candidates
        self.max_iter = max_iter
        self.r2_threshold = r2_threshold
        self.buffer_max = buffer_max
        self.window_size = window_size
        self.all_data: list[dict] = []
        self.input_counter = 0

        self.all_data_update = asyncio.Event()

        # ── Simulation task ───────────────────────────────────────────────────────
        # KEY CHANGE vs amsc_stream. Buffered inputs come in from the investigator's
        # input callback

        @self.learner.simulation_task(as_executable=False)
        async def simulation(rows, **kwargs) -> dict:
            import pandas as pd

            it = int(kwargs.get("iteration", 0))
            label = str(kwargs["learner_label"])

            if DO_PRINT:
                print(
                    f"[M3DC1 Investigator]: [sim {label} iter={it}] waiting for {window_size} more rows",
                    flush=True,
                )

            if DO_PRINT:
                print(
                    f"[M3DC1 Investigator]:  [sim {label} iter={it}] Received {window_size} rows. Total: {len(rows)}",
                    flush=True,
                )

            df = pd.DataFrame(rows)

            out_dir = _workspace_iter(it, label)
            parquet = out_dir / "sensor_snapshot.parquet"
            df.to_parquet(parquet, index=False)

            meta = {
                "iteration": it,
                "learner_label": label,
                "dataset": str(parquet),
                "n_rows": len(df),
            }
            (out_dir / "simulation.json").write_text(json.dumps(meta, indent=2))
            return meta

        # ── Training task ─────────────────────────────────────────────────────────
        # Fits a surrogate model locally using sklearn.
        # Replace with subprocess to surge_train.py if running on HPC.

        self.sim_task = simulation

        @self.learner.training_task(as_executable=False)
        async def training(sim_result: str, **kwargs) -> dict:
            print("TRAIN ..........................")
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

        self.train_task = training

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

        self.active_learn_task = active_learn

        # ── Stop criterion ────────────────────────────────────────────────────────
        @self.learner.utility_task(as_executable=False)
        async def stop_on_r2(*args, **kwargs) -> dict:
            it = int(kwargs.get("iteration", 0))
            label = str(kwargs["learner_label"])
            path = _workspace_iter(it, label) / "surge_metrics.json"
            meta = json.loads(path.read_text())
            r2 = float(meta["val_r2"])
            forced = it >= max_iter - 1 and r2 < r2_threshold
            return {"val_r2": r2_threshold if forced else r2}

        self.stop_criterion = stop_on_r2

        @self.flow.function_task
        async def do_inference(in_data: TypedData, model=None, iter=0, label=""):
            # the ASMC_stream.py demo doesn't tackle streaming inference.
            # Put streaming inference code here.
            if model is None:
                return TypedData(M3DC1_PREDICTION, None)

            with open(model, "rb") as f:
                model_obj = cloudpickle.load(f)

            df = pd.DataFrame([in_data.data])

            X = df.drop(columns=["output_gamma"]).values
            out = model_obj.predict(X)

            return TypedData(M3DC1_PREDICTION, out)

        self.inference = do_inference

    async def input_callback(self, in_data: TypedData):
        # add the data to large database
        print(f"GOT : {in_data.data}")
        self.all_data.append(in_data.data)

        if len(self.all_data) > self.buffer_max:
            self.all_data.pop(0)

        self.input_counter += 1

        if self.input_counter >= self.window_size:
            self.input_counter = 0
            self.all_data_update.set()

    async def main_loop(self, runtime: RuntimeAPI):
        # run the pipeline
        print("START ..........................")

        runtime.subscribe_to_topic(runtime.ON_INPUT, self.input_callback)
        runtime.set_inference_task(self.inference)
        runtime.publish_new_model({"model": None})

        rows: list[dict] = []

        iteration = 0
        while True:
            await self.all_data_update.wait()
            rows = self.all_data
            # do pipeline
            kwargs = {
                "iteration": iteration,
                "learner_label": self.candidates[0],
                "model_family": self.candidates[0],
            }
            sim = self.sim_task(rows, **kwargs)

            model = self.train_task(sim, **kwargs)

            out = await self.active_learn_task(sim, model, **kwargs)

            runtime.publish_new_model(
                {"model": out["model"]},
                {"acc": out["val_r2"]},
            )

            self.all_data_update.clear()
