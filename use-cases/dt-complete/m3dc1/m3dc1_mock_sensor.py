"""
Sensor stream interface and mock implementation for M3DC1 streaming workflows.

To plug in a real sensor, subclass SensorStream and implement read_one().
Everything else (SensorBuffer, amsc_stream.py) works unchanged.
"""

from __future__ import annotations

import argparse
import asyncio

from digitaltwin import ChannelPublisher
import numpy as np

from m3dc1_dtypes import *

# ── Physical parameter ranges for SPARC M3DC1 D1 ────────────────────────────
# Derived from sparc_m3dc1_D1_metadata.yaml (inputs + output_gamma).
# Replace bounds with real calibration data when integrating a live source.
_M3DC1_RANGES: dict[str, tuple[float, float]] = {
    "input_batemanscale": (0.5, 2.0),
    "input_ntor": (1.0, 15.0),  # toroidal mode number
    "input_pscale": (0.5, 2.0),
    "eq_a": (0.1, 0.5),  # minor radius [m]
    "eq_R0": (1.5, 6.0),  # major radius [m]
    "eq_kappa": (1.0, 2.5),  # elongation
    "eq_delta": (0.0, 0.8),  # triangularity
    "eq_simag": (-2.0, 0.0),  # poloidal flux at magnetic axis
    "eq_sibry": (-5.0, -0.5),  # poloidal flux at boundary
    "eq_current": (0.5, 15.0),  # plasma current [MA]
    "q0": (0.8, 2.5),  # safety factor on axis
    "q95": (3.0, 8.0),  # safety factor at 95 % flux
    "p0": (1e4, 1e6),  # peak pressure [Pa]
}

COLUMNS: list[str] = list(_M3DC1_RANGES) + ["output_gamma"]


class MockM3DC1Sensor:
    """Simulates a real-time M3DC1 physics sensor at a configurable rate.

    Observations are drawn from the realistic parameter ranges in _M3DC1_RANGES.
    output_gamma is a nonlinear surrogate of the MHD stability growth rate plus
    Gaussian noise — non-trivial enough to make the surrogate task meaningful.

    Args:
        rate_hz:   Target emission rate in observations per second.
        seed:      RNG seed for reproducibility.
        noise_std: Std-dev of Gaussian noise on output_gamma.
    """

    def __init__(
        self,
        rate_hz: float = 2.0,
        seed: int = 42,
        noise_std: float = 0.005,
    ) -> None:
        self._delay = 1.0 / max(rate_hz, 1e-6)
        self._rng = np.random.default_rng(seed)
        self._noise_std = noise_std

    async def read_one(self) -> dict[str, float]:
        await asyncio.sleep(self._delay)
        return self._sample()

    def _sample(self) -> dict[str, float]:
        rng = self._rng
        obs: dict[str, float] = {
            col: float(rng.uniform(lo, hi)) for col, (lo, hi) in _M3DC1_RANGES.items()
        }
        # Surrogate physics: gamma grows with mode number and pressure scale,
        # falls with safety factor — rough but nonlinear enough for surrogates.
        obs["output_gamma"] = float(
            max(
                0.0,
                0.08 * obs["input_batemanscale"] * (obs["input_ntor"] / 8.0)
                + 0.06 * obs["input_pscale"] / max(obs["q95"], 0.1)
                + 0.04 * obs["eq_kappa"] * obs["eq_delta"]
                - 0.02 * obs["q0"]
                + float(rng.normal(0.0, self._noise_std)),
            )
        )
        return obs


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="M3DC1 mock sensor.")
    parser.add_argument(
        "--sensor-rate",
        type=float,
        default=2.0,
        help="Mock sensor emission rate in observations/second (default: 2).",
    )
    parser.add_argument(
        "--sensor-seed",
        type=int,
        default=42,
        help="RNG seed for the mock sensor.",
    )

    args = parser.parse_args()

    async def main():
        publisher = await ChannelPublisher.open(M3DC1_MOCK_CHANNEL)

        sensor = MockM3DC1Sensor(rate_hz=args.sensor_rate, seed=args.sensor_seed)
        try:
            while True:
                val = await sensor.read_one()
                await publisher.publish(val)
        finally:
            await publisher.close()

    if __name__ == "__main__":
        asyncio.run(main())
