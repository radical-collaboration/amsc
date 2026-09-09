#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import warnings
from pathlib import Path

import rhapsody
from rhapsody.backends.data.redis import RedisDataBackend

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from sensor_daemon import STREAM_KEY, MockHeatSensor, SensorDaemon  # noqa: E402

from radical.asyncflow import WorkflowEngine                         # noqa: E402
from rose.al import SequentialActiveLearner                          # noqa: E402
from rose.learner import LearnerConfig, TaskConfig                   # noqa: E402

N_BASE = 50
N_STEP = 25

CONVERGENCE_THRESHOLD = 0.05

_WORKSPACE = _HERE / "workspace"


def _workspace_iter(iteration: int) -> Path:
    directory = _WORKSPACE / f"iter_{iteration:03d}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _build_learner_config(max_iter: int, redis_endpoint: str) -> LearnerConfig:
    kwargs   = {"redis_endpoint": redis_endpoint}
    schedule = {i: TaskConfig(kwargs={**kwargs, "iteration": i}) for i in range(max_iter + 1)}
    schedule[-1] = TaskConfig(kwargs={**kwargs, "iteration": max_iter})
    return LearnerConfig(
        simulation=schedule,
        training=schedule,
        active_learn=schedule,
        criterion=schedule,
    )


async def run_rose_workflow(
    endpoint,
    *,
    max_iter: int,
    convergence_threshold: float,
) -> None:
    import redis as _redis

    engine    = await rhapsody.get_backend("concurrent")
    asyncflow = await WorkflowEngine.create(engine)
    learner   = SequentialActiveLearner(asyncflow)

    redis_endpoint = endpoint.serialize()
    redis_client   = _redis.Redis(host=endpoint.host, port=endpoint.port, decode_responses=True)

    @learner.simulation_task(as_executable=False)
    async def simulation(*args, **kwargs) -> dict:
        import time
        import redis as _redis
        import pandas as pd

        it       = int(kwargs.get("iteration", 0))
        redis_ep = str(kwargs["redis_endpoint"])
        n_rows   = N_BASE + it * N_STEP

        host, port_str = redis_ep.rsplit(":", 1)
        redis_client   = _redis.Redis(host=host, port=int(port_str), decode_responses=True)

        print(f"  [sim iter={it}] waiting for {n_rows} rows …", flush=True)
        deadline = time.monotonic() + 600.0
        while redis_client.xlen(STREAM_KEY) < n_rows:
            if time.monotonic() > deadline:
                raise TimeoutError(f"Timeout waiting for {n_rows} sensor rows")
            time.sleep(0.5)

        entries = redis_client.xrevrange(STREAM_KEY, count=n_rows)
        entries.reverse()

        rows      = [{key: float(val) for key, val in fields.items()} for _, fields in entries]
        df        = pd.DataFrame(rows)
        out_dir   = _workspace_iter(it)
        parquet   = out_dir / "sensor_snapshot.parquet"
        df.to_parquet(parquet, index=False)

        meta = {
            "iteration": it,
            "dataset"  : str(parquet),
            "n_rows"   : len(df),
            "source"   : "redis_stream",
        }
        (out_dir / "simulation.json").write_text(json.dumps(meta, indent=2))
        return meta

    @learner.training_task(as_executable=False)
    async def training(sim_result: dict, **kwargs) -> dict:
        import numpy as np
        import pandas as pd
        from sklearn.gaussian_process         import GaussianProcessRegressor
        from sklearn.gaussian_process.kernels import Matern
        from sklearn.model_selection          import train_test_split
        from sklearn.preprocessing            import StandardScaler

        it  = int(kwargs.get("iteration", sim_result["iteration"]))

        df      = pd.read_parquet(sim_result["dataset"])
        X       = df.drop(columns=["q_max"]).values
        y       = df["q_max"].values

        X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=it)

        scaler = StandardScaler().fit(X_train)
        gp     = GaussianProcessRegressor(
            kernel=Matern(nu=2.5),
            n_restarts_optimizer=3,
            normalize_y=True,
        )
        gp.fit(scaler.transform(X_train), y_train)

        y_pred, y_std = gp.predict(scaler.transform(X_val), return_std=True)
        mean_uncertainty = float(y_std.mean() / max(y_train.std(), 1e-6))

        metrics = {
            "iteration"       : it,
            "n_train"         : int(len(X_train)),
            "n_val"           : int(len(X_val)),
            "mean_uncertainty": mean_uncertainty,
        }
        out_dir = _workspace_iter(it)
        (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
        return {"simulation": sim_result, "metrics": metrics}

    @learner.active_learn_task(as_executable=False)
    async def active_learn(sim_result: dict, train_bundle: dict, **kwargs) -> dict:
        it      = int(kwargs.get("iteration", train_bundle["simulation"]["iteration"]))
        metrics = train_bundle["metrics"]

        decision = {
            "iteration"       : it,
            "policy"          : "stream_consume",
            "mean_uncertainty": metrics["mean_uncertainty"],
        }
        out_dir = _workspace_iter(it)
        (out_dir / "active.json").write_text(json.dumps(decision, indent=2))
        return {
            "iteration"       : it,
            "train"           : train_bundle,
            "mean_uncertainty": metrics["mean_uncertainty"],
        }

    @learner.as_stop_criterion(
        metric_name="mean_uncertainty",
        threshold=convergence_threshold,
        operator="<",
        as_executable=False,
    )
    async def check_convergence(*args, **kwargs) -> float:
        it   = int(kwargs.get("iteration", 0))
        path = _workspace_iter(it) / "metrics.json"
        meta = json.loads(path.read_text())
        return float(meta["mean_uncertainty"])

    initial_config = _build_learner_config(max_iter, redis_endpoint)
    print("\nStarting HEAT surrogate stream loop\n" + "─" * 60, flush=True)

    try:
        async for state in learner.start(max_iter=max_iter, initial_config=initial_config):
            stream_len = await asyncio.to_thread(redis_client.xlen, STREAM_KEY)
            print(
                f"[iter {state.iteration}]"
                f"  uncertainty={state.metric_value:.4f}"
                f"  (target <{convergence_threshold})"
                f"  stream={stream_len} obs",
                flush=True,
            )
    finally:
        await asyncflow.shutdown()


def main() -> None:
    warnings.filterwarnings("ignore", category=UserWarning)

    parser = argparse.ArgumentParser(
        description="HEAT streaming surrogate — RedisDataBackend version."
    )
    parser.add_argument("--max-iter",             type=int,   default=10)
    parser.add_argument("--convergence-threshold", type=float, default=CONVERGENCE_THRESHOLD)
    parser.add_argument("--sensor-rate",           type=float, default=10.0,
                        help="Mock sensor rate in obs/s.")
    parser.add_argument("--sensor-seed",           type=int,   default=42)
    parser.add_argument("--buffer-maxlen",         type=int,   default=10_000)
    # HPC: set --redis-port and --redis-cmd for remote Redis launch
    parser.add_argument("--redis-port", type=int,  default=None)
    parser.add_argument("--redis-cmd",  default=None,
                        help='e.g. "srun --nodelist={host} redis-server --port {port}"')

    args = parser.parse_args()

    redis_backend = RedisDataBackend(
        **({"cmd": args.redis_cmd, "port": args.redis_port} if args.redis_cmd else {})
    )

    async def _main() -> None:
        await redis_backend.start()
        endpoint = redis_backend.endpoints[0]

        sensor = MockHeatSensor(rate_hz=args.sensor_rate, seed=args.sensor_seed)
        daemon = SensorDaemon(sensor, endpoint.serialize(), maxlen=args.buffer_maxlen)
        await daemon.start()

        print(
            f"Redis: {endpoint.serialize()}  sensor: {args.sensor_rate} Hz"
            f"  max_iter: {args.max_iter}  threshold: {args.convergence_threshold}",
            flush=True,
        )
        try:
            await run_rose_workflow(
                endpoint,
                max_iter=args.max_iter,
                convergence_threshold=args.convergence_threshold,
            )
        finally:
            await daemon.stop()
            await redis_backend.shutdown()
            print("Sensor daemon and Redis stopped.", flush=True)

    asyncio.run(_main())


if __name__ == "__main__":
    main()
