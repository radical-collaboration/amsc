from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from pathlib import Path
import sys

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import numpy as np
import redis

STREAM_KEY = "m3dc1:sensor"

_M3DC1_RANGES: dict[str, tuple[float, float]] = {
    "input_batemanscale": (0.5,   2.0),
    "input_ntor":         (1.0,  15.0),
    "input_pscale":       (0.5,   2.0),
    "eq_a":               (0.1,   0.5),
    "eq_R0":              (1.5,   6.0),
    "eq_kappa":           (1.0,   2.5),
    "eq_delta":           (0.0,   0.8),
    "eq_simag":          (-2.0,   0.0),
    "eq_sibry":          (-5.0,  -0.5),
    "eq_current":         (0.5,  15.0),
    "q0":                 (0.8,   2.5),
    "q95":                (3.0,   8.0),
    "p0":                 (1e4,   1e6),
}

COLUMNS: list[str] = list(_M3DC1_RANGES) + ["output_gamma"]


class SensorStream(ABC):
    @abstractmethod
    async def read_one(self) -> dict[str, float]: ...

    async def stream(self) -> AsyncIterator[dict[str, float]]:
        while True:
            yield await self.read_one()


class MockM3DC1Sensor(SensorStream):
    def __init__(self, rate_hz: float = 2.0, seed: int = 42, noise_std: float = 0.005) -> None:
        self._delay     = 1.0 / max(rate_hz, 1e-6)
        self._rng       = np.random.default_rng(seed)
        self._noise_std = noise_std

    async def read_one(self) -> dict[str, float]:
        await asyncio.sleep(self._delay)
        return self._sample()

    def _sample(self) -> dict[str, float]:
        rng = self._rng
        obs: dict[str, float] = {
            col: float(rng.uniform(lo, hi))
            for col, (lo, hi) in _M3DC1_RANGES.items()
        }
        obs["output_gamma"] = float(max(
            0.0,
            0.08 * obs["input_batemanscale"] * (obs["input_ntor"] / 8.0)
            + 0.06 * obs["input_pscale"] / max(obs["q95"], 0.1)
            + 0.04 * obs["eq_kappa"] * obs["eq_delta"]
            - 0.02 * obs["q0"]
            + float(rng.normal(0.0, self._noise_std)),
        ))
        return obs


class SensorDaemon:
    def __init__(self, sensor: SensorStream, redis_endpoint: str, maxlen: int = 10_000) -> None:
        host, port = redis_endpoint.rsplit(":", 1)
        self._sensor = sensor
        self._r      = redis.Redis(host=host, port=int(port), decode_responses=True)
        self._maxlen = maxlen
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="sensor-daemon")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        async for obs in self._sensor.stream():
            fields = {k: str(v) for k, v in obs.items()}
            await asyncio.to_thread(self._r.xadd, STREAM_KEY, fields, maxlen=self._maxlen)
