#!/usr/bin/env python3
"""
M3DC1 streaming surrogate — sensor-based input version.

Replaces the predefined dataset pool from amsc.py with a continuous sensor
stream (mocked by MockM3DC1Sensor).  The simulation task no longer slices
from a pre-loaded PKL; instead it calls buffer.wait_for(n) and consumes
however many observations the sensor has delivered so far.

Architecture
────────────
  SensorStream (sensor.py)          ← implement this for a real sensor
      │
  SensorBuffer (sensor_buffer.py)   ← background asyncio task, accumulates rows
      │
  simulation task                   ← waits for N rows, writes parquet
      │
  training task                     ← fits sklearn surrogate on that parquet
      │
  active_learn task                 ← records AL decision
      │
  stop_on_r2 criterion              ← stops when val_r2 ≥ threshold

To swap in a real sensor:
    class MyRealSensor(SensorStream):
        async def read_one(self) -> dict[str, float]:
            ...  # read from your hardware / REST API / Kafka / etc.

    sensor = MyRealSensor()
    # everything else in this file stays the same
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import rhapsody

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from sensor import MockM3DC1Sensor, SensorStream          # noqa: E402
from sensor_buffer import SensorBuffer                     # noqa: E402

from radical.asyncflow import WorkflowEngine               # noqa: E402
from rose.al import ParallelActiveLearner                  # noqa: E402
from rose.learner import LearnerConfig, TaskConfig         # noqa: E402

# ── Row-budget policy (mirrors amsc.py's growing-pool logic) ─────────────────
# At iteration i, the simulation task requests N_BASE + i * N_STEP rows from
# the buffer.  Increase N_STEP to consume more data per iteration.
N_BASE = 100
N_STEP = 100

# Workspace for iteration artefacts (parquet snapshots, metric JSON)
_WORKSPACE = _HERE / "workspace"


def _workspace_iter(iteration: int, label: str) -> Path:
    d = _WORKSPACE / f"{label}" / f"iter_{iteration:03d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _candidate_configs(candidates: list[str], max_iter: int) -> list[LearnerConfig]:
    configs = []
    for idx, family in enumerate(candidates):
        label    = f"{idx}_{family}"
        kwargs   = {"learner_label": label, "model_family": family}
        schedule = {i: TaskConfig(kwargs={**kwargs, "iteration": i}) for i in range(max_iter + 1)}
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


# ── ROSE workflow ─────────────────────────────────────────────────────────────

async def run_rose_workflow(
    buffer: SensorBuffer,
    *,
    candidates: list[str],
    max_iter: int,
    r2_threshold: float,
) -> None:
    engine    = await rhapsody.get_backend("concurrent")
    asyncflow = await WorkflowEngine.create(engine)
    learner   = ParallelActiveLearner(asyncflow)

    # ── Simulation task ───────────────────────────────────────────────────────
    # KEY CHANGE vs amsc.py: reads from sensor buffer, not from the PKL pool.
    # The buffer is captured by closure; swapping the sensor changes nothing here.
    @learner.simulation_task(as_executable=False)
    async def simulation(*args, **kwargs) -> dict:
        it    = int(kwargs.get("iteration", 0))
        label = str(kwargs["learner_label"])

        n_rows  = N_BASE + it * N_STEP
        out_dir = _workspace_iter(it, label)
        parquet = out_dir / "sensor_snapshot.parquet"

        print(f"  [sim {label} iter={it}] waiting for {n_rows} sensor rows …", flush=True)
        n_written = await buffer.write_snapshot(n_rows, parquet, timeout=600.0)

        meta = {
            "iteration"    : it,
            "learner_label": label,
            "dataset"      : str(parquet),
            "n_rows"       : n_written,
            "source"       : "sensor_stream",
        }
        (out_dir / "simulation.json").write_text(json.dumps(meta, indent=2))
        return meta

    # ── Training task ─────────────────────────────────────────────────────────
    # Fits a surrogate model locally using sklearn.
    # Replace with subprocess to surge_train.py if running on HPC.
    @learner.training_task(as_executable=False)
    async def training(sim_result: dict, **kwargs) -> dict:
        import pandas as pd
        from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
        from sklearn.linear_model import Ridge
        from sklearn.metrics import mean_squared_error, r2_score
        from sklearn.model_selection import train_test_split
        from sklearn.neural_network import MLPRegressor
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import Pipeline

        it     = int(kwargs.get("iteration", sim_result["iteration"]))
        label  = str(kwargs["learner_label"])
        family = str(kwargs.get("model_family", "rf"))

        df = pd.read_parquet(sim_result["dataset"])
        X  = df.drop(columns=["output_gamma"]).values
        y  = df["output_gamma"].values

        X_train, X_val, y_train, y_val = train_test_split(
            X, y, test_size=0.2, random_state=it
        )

        _models = {
            "rf":  RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1),
            "mlp": Pipeline([
                ("scaler", StandardScaler()),
                ("net",    MLPRegressor(hidden_layer_sizes=(64, 64), max_iter=500, random_state=42)),
            ]),
            "gbr": GradientBoostingRegressor(n_estimators=100, random_state=42),
            "ridge": Pipeline([
                ("scaler", StandardScaler()),
                ("reg",    Ridge()),
            ]),
        }
        model = _models.get(family, _models["rf"])
        model.fit(X_train, y_train)

        y_pred = model.predict(X_val)
        val_r2   = float(r2_score(y_val, y_pred))
        val_rmse = float(np.sqrt(mean_squared_error(y_val, y_pred)))

        metrics = {
            "iteration"    : it,
            "learner_label": label,
            "model_family" : family,
            "val_r2"       : val_r2,
            "val_rmse"     : val_rmse,
            "n_train"      : int(len(X_train)),
            "n_val"        : int(len(X_val)),
        }
        out_dir = _workspace_iter(it, label)
        (out_dir / "surge_metrics.json").write_text(json.dumps(metrics, indent=2))
        return {"simulation": sim_result, "surge": metrics}

    # ── Active-learning task ──────────────────────────────────────────────────
    @learner.active_learn_task(as_executable=False)
    async def active_learn(sim_result: dict, train_bundle: dict, **kwargs) -> dict:
        it    = int(kwargs.get("iteration", train_bundle["simulation"]["iteration"]))
        label = str(kwargs["learner_label"])
        surge = train_bundle["surge"]

        decision = {
            "iteration"    : it,
            "learner_label": label,
            "policy"       : "monitor_best_val_r2",
            "val_r2"       : surge["val_r2"],
            "val_rmse"     : surge["val_rmse"],
        }
        out_dir = _workspace_iter(it, label)
        (out_dir / "active.json").write_text(json.dumps(decision, indent=2))
        return {
            "iteration"    : it,
            "learner_label": label,
            "train"        : train_bundle,
            "val_r2"       : surge["val_r2"],
            "val_rmse"     : surge["val_rmse"],
        }

    # ── Stop criterion ────────────────────────────────────────────────────────
    @learner.as_stop_criterion(
        metric_name="val_r2",
        threshold=r2_threshold,
        operator=">=",
        as_executable=False,
    )
    async def stop_on_r2(*args, **kwargs) -> float:
        it    = int(kwargs.get("iteration", 0))
        label = str(kwargs["learner_label"])
        path  = _workspace_iter(it, label) / "surge_metrics.json"
        meta  = json.loads(path.read_text())
        r2    = float(meta["val_r2"])
        forced = it >= max_iter - 1 and r2 < r2_threshold
        return r2_threshold if forced else r2

    # ── Run ───────────────────────────────────────────────────────────────────
    configs = _candidate_configs(candidates, max_iter)
    rows: list[dict] = []

    try:
        async for state in learner.start(
            parallel_learners=len(candidates),
            max_iter=max_iter,
            learner_configs=configs,
        ):
            label = candidates[int(state.learner_id)]
            rows.append({
                "learner" : label,
                "iter"    : state.iteration,
                "val_r2"  : state.val_r2,
                "val_rmse": state.val_rmse,
            })
            print(
                f"  learner={label}  iter={state.iteration}"
                f"  val_r2={state.val_r2:.5f}  val_rmse={state.val_rmse:.5f}"
                f"  buffer={len(buffer)} obs",
                flush=True,
            )
            if len(rows) >= len(candidates) * max_iter:
                learner.stop()
                break
    finally:
        await asyncflow.shutdown()

    rows.sort(key=lambda r: float(r["val_r2"]), reverse=True)
    print("\n── Summary ──────────────────────────────────────────────────────")
    print(f"{'rank':>4}  {'learner':<8}  {'val_r2':>9}  {'val_rmse':>10}")
    for rank, row in enumerate(rows, 1):
        print(
            f"{rank:>4}  {row['learner']:<8}  "
            f"{float(row['val_r2']):>9.5f}  {float(row['val_rmse']):>10.6f}"
        )
    print(f"Workspace: {_WORKSPACE}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    warnings.filterwarnings("ignore", category=UserWarning)

    parser = argparse.ArgumentParser(
        description="M3DC1 streaming surrogate — sensor input version."
    )
    parser.add_argument(
        "--candidates",
        default="rf,mlp",
        help="Comma-separated model families: rf, mlp, gbr, ridge.",
    )
    parser.add_argument("--max-iter",     type=int,   default=3)
    parser.add_argument("--r2-threshold", type=float, default=0.80)
    parser.add_argument(
        "--sensor-rate",
        type=float,
        default=10.0,
        help="Mock sensor emission rate in observations/second (default: 10).",
    )
    parser.add_argument(
        "--sensor-seed",
        type=int,
        default=42,
        help="RNG seed for the mock sensor.",
    )
    parser.add_argument(
        "--buffer-maxlen",
        type=int,
        default=10_000,
        help="Maximum observations retained in the sensor buffer.",
    )
    args       = parser.parse_args()
    candidates = [x.strip() for x in args.candidates.split(",") if x.strip()]

    if len(candidates) < 2:
        parser.error("Need at least two candidates for ParallelActiveLearner.")

    sensor = MockM3DC1Sensor(rate_hz=args.sensor_rate, seed=args.sensor_seed)
    buffer = SensorBuffer(sensor, maxlen=args.buffer_maxlen)

    async def _main() -> None:
        await buffer.start()
        print(
            f"Sensor stream started  rate={args.sensor_rate} Hz"
            f"  candidates={candidates}  max_iter={args.max_iter}",
            flush=True,
        )
        try:
            await run_rose_workflow(
                buffer,
                candidates=candidates,
                max_iter=args.max_iter,
                r2_threshold=args.r2_threshold,
            )
        finally:
            await buffer.stop()
            print("Sensor stream stopped.", flush=True)

    asyncio.run(_main())


if __name__ == "__main__":
    main()
