from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from pathlib import Path
import sys

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import numpy as np
import redis

STREAM_KEY = "heat:sensor"

# Eich optical heat flux model — parameter ranges from NSTX-U operational space
_HEAT_RANGES: dict[str, tuple[float, float]] = {
    "lqCN"   : (0.5,  5.0),   # near-side decay length [mm]
    "lqCF"   : (2.0, 15.0),   # far-side decay length [mm]
    "S"      : (0.5,  5.0),   # spreading factor [mm]
    "P"      : (5.0, 20.0),   # input power [MW]
    "radFrac": (0.1,  0.8),   # radiated power fraction
    "fracCN" : (0.4,  0.8),   # near-side power fraction
    "fracCF" : (0.1,  0.6),   # far-side power fraction
}

COLUMNS: list[str] = list(_HEAT_RANGES) + ["q_max"]


class SensorStream(ABC):
    @abstractmethod
    async def read_one(self) -> dict[str, float]: ...

    async def stream(self) -> AsyncIterator[dict[str, float]]:
        while True:
            yield await self.read_one()


class MockHeatSensor(SensorStream):
    def __init__(self, rate_hz: float = 2.0, seed: int = 42, noise_std: float = 0.1) -> None:
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
            for col, (lo, hi) in _HEAT_RANGES.items()
        }
        # Eich-inspired approximation: q_max ~ P_net * (fracCN/lqCN + fracCF/lqCF)
        # Scaled to realistic NSTX-U range of ~2–50 MW/m²
        p_net = obs["P"] * (1.0 - obs["radFrac"])
        obs["q_max"] = float(max(
            0.0,
            2.0 * p_net * (obs["fracCN"] / max(obs["lqCN"], 0.01)
                           + obs["fracCF"] / max(obs["lqCF"], 0.01))
            + float(rng.normal(0.0, self._noise_std)),
        ))
        return obs


class SensorDaemon:
    def __init__(self, sensor: SensorStream, redis_endpoint: str, maxlen: int = 10_000) -> None:
        host, port = redis_endpoint.rsplit(":", 1)
        self._sensor = sensor
        self._redis  = redis.Redis(host=host, port=int(port), decode_responses=True)
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
            await asyncio.to_thread(self._redis.xadd, STREAM_KEY, fields, maxlen=self._maxlen)
