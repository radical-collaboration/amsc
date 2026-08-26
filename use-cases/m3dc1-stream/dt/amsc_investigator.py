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
        r2_threshold: float,
    ):
        super().__init__(flow)

        self.learner = ParallelActiveLearner(flow)
        self.candidates = candidates
        self.max_iter = max_iter
        self.r2_threshold = r2_threshold

        # each surrogate gets their own event
        self.data_event: dict[str, asyncio.Event] = {}

        for candidate in self.candidates:
            self.data_event[candidate] = asyncio.Event()

        # ── Simulation task ───────────────────────────────────────────────────────
        # KEY CHANGE vs amsc_stream. Buffered inputs come in from the DT.

        @self.learner.simulation_task
        async def simulation(*args, **kwargs) -> str:
            it = int(kwargs.get("iteration", 0))
            label = str(kwargs["learner_label"])
            family = str(kwargs["model_family"])

            n_rows = N_BASE + it * N_STEP
            out_dir = _workspace_iter(it, label)
            parquet = out_dir / "sensor_snapshot.parquet"

            print(
                f"  [sim {label} iter={it}] Now has {n_rows} sensor rows …", flush=True
            )

            await self.data_event[family].wait()
            n_written = len(self.all_data)

            meta = {
                "iteration": it,
                "learner_label": label,
                "dataset": str(parquet),
                "n_rows": n_written,
                "source": "sensor_stream",
            }
            (out_dir / "simulation.json").write_text(json.dumps(meta, indent=2))

            self.data_event[family].clear()

            # workaround: I know, looks a little goofy. Read the notes at top of
            # file. Parameter is passed via `out_dir/simulation.json`
            #
            # Consequence of this workaround: on shutdown, AsyncFlow will
            # complain that the future is missing some attributes.
            # This is because AsyncFlow stamps the attributes when the cmdline
            # is returned. It doesn't hurt accuracy in any way, just doesn't
            # look as clean.
            return f"echo {shlex.quote(str(out_dir / "simulation.json"))}"

        # ── Training task ─────────────────────────────────────────────────────────
        # Fits a surrogate model locally using sklearn.
        # Replace with subprocess to surge_train.py if running on HPC.
        @self.learner.training_task(as_executable=False)
        async def training(sim_result_path: str, **kwargs) -> dict:
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

            with open(sim_result_path, "r") as f:
                sim_result = json.load(f)

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
        for v in self.data_event.values():
            v.set()

    async def main_loop(self, runtime: RuntimeAPI):
        # call the pipeline

        runtime.subscribe_to_topic(runtime.ON_INPUT, self.input_callback)
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
                f"  learner={label}  iter={state.iteration}"
                f"  val_r2={state.val_r2:.5f}  val_rmse={state.val_rmse:.5f}"
                f"  buffer={len(self.all_data)} obs",
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
