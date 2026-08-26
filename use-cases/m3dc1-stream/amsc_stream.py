#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import rhapsody
from rhapsody.backends.data.redis import RedisDataBackend

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from sensor_daemon import STREAM_KEY, MockM3DC1Sensor, SensorDaemon  # noqa: E402


from concurrent.futures import ProcessPoolExecutor

from rhapsody.backends import ConcurrentExecutionBackend
from radical.asyncflow import WorkflowEngine               # noqa: E402
from rose.al import ParallelActiveLearner                  # noqa: E402
from rose.learner import LearnerConfig, TaskConfig         # noqa: E402

N_BASE = 100
N_STEP = 100

_WORKSPACE = _HERE / "workspace"


def _workspace_iter(iteration: int, label: str) -> Path:
    d = _WORKSPACE / label / f"iter_{iteration:03d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _candidate_configs(
    candidates: list[str], max_iter: int, redis_endpoint: str
) -> list[LearnerConfig]:
    configs = []
    for idx, family in enumerate(candidates):
        label  = f"{idx}_{family}"
        kwargs = {
            "learner_label" : label,
            "model_family"  : family,
            "redis_endpoint": redis_endpoint,
        }
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


async def run_rose_workflow(
    endpoint,
    *,
    candidates: list[str],
    max_iter: int,
    r2_threshold: float,
) -> None:
    import redis as _redis

    engine    = await ConcurrentExecutionBackend(ProcessPoolExecutor())
    asyncflow = await WorkflowEngine.create(engine)
    learner   = ParallelActiveLearner(asyncflow)

    redis_endpoint = endpoint.serialize()
    redis_client = _redis.Redis(host=endpoint.host, port=endpoint.port, decode_responses=True)

    @learner.simulation_task(as_executable=False)
    async def simulation(*args, **kwargs) -> dict:
        import time
        import redis as _redis
        import pandas as pd

        it       = int(kwargs.get("iteration", 0))
        label    = str(kwargs["learner_label"])
        redis_ep = str(kwargs["redis_endpoint"])
        n_rows   = N_BASE + it * N_STEP

        host, port_str = redis_ep.rsplit(":", 1)
        redis_client = _redis.Redis(host=host, port=int(port_str), decode_responses=True)

        print(f"  [sim {label} iter={it}] waiting for {n_rows} rows …", flush=True)
        deadline = time.monotonic() + 600.0
        while redis_client.xlen(STREAM_KEY) < n_rows:
            if time.monotonic() > deadline:
                raise TimeoutError(f"Timeout waiting for {n_rows} sensor rows")
            time.sleep(0.5)

        entries = redis_client.xrevrange(STREAM_KEY, count=n_rows)
        entries.reverse()

        rows = [{key: float(val) for key, val in fields.items()} for _, fields in entries]
        df = pd.DataFrame(rows)

        out_dir = _workspace_iter(it, label)
        parquet = out_dir / "sensor_snapshot.parquet"
        df.to_parquet(parquet, index=False)

        meta = {
            "iteration"    : it,
            "learner_label": label,
            "dataset"      : str(parquet),
            "n_rows"       : len(df),
            "source"       : "redis_stream",
        }
        (out_dir / "simulation.json").write_text(json.dumps(meta, indent=2))
        return meta

    @learner.training_task(as_executable=False)
    async def training(sim_result: dict, **kwargs) -> dict:
        import pandas as pd
        from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
        from sklearn.linear_model import Ridge
        from sklearn.metrics import mean_squared_error, r2_score
        from sklearn.model_selection import train_test_split
        from sklearn.neural_network import MLPRegressor
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        it     = int(kwargs.get("iteration", sim_result["iteration"]))
        label  = str(kwargs["learner_label"])
        family = str(kwargs.get("model_family", "rf"))

        df = pd.read_parquet(sim_result["dataset"])
        X  = df.drop(columns=["output_gamma"]).values
        y  = df["output_gamma"].values

        X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=it)

        _models = {
            "rf":    RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1),
            "mlp":   Pipeline([
                         ("scaler", StandardScaler()),
                         ("net",    MLPRegressor(hidden_layer_sizes=(64, 64), max_iter=500, random_state=42)),
                     ]),
            "gbr":   GradientBoostingRegressor(n_estimators=100, random_state=42),
            "ridge": Pipeline([
                         ("scaler", StandardScaler()),
                         ("reg",    Ridge()),
                     ]),
        }
        model = _models.get(family, _models["rf"])
        model.fit(X_train, y_train)

        y_pred   = model.predict(X_val)
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

    @learner.as_stop_criterion(
        metric_name="val_r2",
        threshold=r2_threshold,
        operator=">=",
        as_executable=False,
    )
    async def stop_on_r2(*args, **kwargs) -> float:
        it     = int(kwargs.get("iteration", 0))
        label  = str(kwargs["learner_label"])
        path   = _workspace_iter(it, label) / "surge_metrics.json"
        meta   = json.loads(path.read_text())
        r2     = float(meta["val_r2"])
        forced = it >= max_iter - 1 and r2 < r2_threshold
        return r2_threshold if forced else r2

    configs = _candidate_configs(candidates, max_iter, redis_endpoint)
    rows: list[dict] = []

    try:
        async for state in learner.start(
            parallel_learners=len(candidates),
            max_iter=max_iter,
            learner_configs=configs,
        ):
            label       = candidates[int(state.learner_id)]
            stream_len  = await asyncio.to_thread(redis_client.xlen, STREAM_KEY)
            rows.append({
                "learner" : label,
                "iter"    : state.iteration,
                "val_r2"  : state.val_r2,
                "val_rmse": state.val_rmse,
            })
            print(
                f"  learner={label}  iter={state.iteration}"
                f"  val_r2={state.val_r2:.5f}  val_rmse={state.val_rmse:.5f}"
                f"  stream={stream_len} obs",
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


def main() -> None:
    warnings.filterwarnings("ignore", category=UserWarning)

    parser = argparse.ArgumentParser(
        description="M3DC1 streaming surrogate — RedisDataBackend version."
    )
    parser.add_argument("--candidates",    default="rf,mlp",
                        help="Comma-separated model families: rf, mlp, gbr, ridge.")
    parser.add_argument("--max-iter",      type=int,   default=3)
    parser.add_argument("--r2-threshold",  type=float, default=0.80)
    parser.add_argument("--sensor-rate",   type=float, default=10.0,
                        help="Mock sensor rate in obs/s.")
    parser.add_argument("--sensor-seed",   type=int,   default=42)
    parser.add_argument("--buffer-maxlen", type=int,   default=10_000,
                        help="Max stream length retained in Redis.")

    args       = parser.parse_args()
    candidates = [x.strip() for x in args.candidates.split(",") if x.strip()]

    

    async def _main() -> None:
        redis_backend = await RedisDataBackend()
        endpoint = redis_backend.endpoints[0]

        sensor = MockM3DC1Sensor(rate_hz=args.sensor_rate, seed=args.sensor_seed)
        daemon = SensorDaemon(sensor, endpoint.serialize(), maxlen=args.buffer_maxlen)
        await daemon.start()

        print(
            f"Redis: {endpoint.serialize()}  sensor: {args.sensor_rate} Hz"
            f"  candidates: {candidates}  max_iter: {args.max_iter}",
            flush=True,
        )
        try:
            await run_rose_workflow(
                endpoint,
                candidates=candidates,
                max_iter=args.max_iter,
                r2_threshold=args.r2_threshold,
            )
        finally:
            await daemon.stop()
            await redis_backend.shutdown()
            print("Sensor daemon and Redis stopped.", flush=True)

    asyncio.run(_main())


if __name__ == "__main__":
    main()
