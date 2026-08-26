"""
SensorBuffer: accumulates observations from a SensorStream into a bounded
in-memory deque and surfaces snapshots as pandas DataFrames.

The buffer runs a background asyncio task that calls sensor.stream() and
appends each observation as it arrives.  Workflow tasks call wait_for(n) to
block until enough data is available, then take a snapshot for training.
"""
from __future__ import annotations

import asyncio
from collections import deque
from pathlib import Path

import pandas as pd

from sensor import SensorStream


class SensorBuffer:
    """Thread-of-execution-safe accumulator for a continuous sensor stream.

    Args:
        sensor:  Any SensorStream implementation (mock or real).
        maxlen:  Maximum observations to retain (oldest discarded when full).
                 Set to None for an unbounded buffer.
    """

    def __init__(self, sensor: SensorStream, maxlen: int | None = 10_000) -> None:
        self._sensor = sensor
        self._deque: deque[dict] = deque(maxlen=maxlen)
        self._event: asyncio.Event | None = None
        self._loop:  asyncio.AbstractEventLoop | None = None   # loop that owns the Event
        self._task:  asyncio.Task | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background ingestion task."""
        self._loop  = asyncio.get_running_loop()
        self._event = asyncio.Event()
        self._task  = asyncio.create_task(self._ingest(), name="sensor-ingest")

    async def stop(self) -> None:
        """Cancel the background ingestion task and wait for it to exit."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _ingest(self) -> None:
        async for obs in self._sensor.stream():
            self._deque.append(obs)
            self._event.set()   # wake any waiter; they will clear it themselves

    # ── Public API ───────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._deque)

    def snapshot(self, n: int | None = None) -> pd.DataFrame:
        """Return the most recent n observations as a DataFrame (no blocking)."""
        rows = list(self._deque)
        if n is not None:
            rows = rows[-n:]
        return pd.DataFrame(rows)

    async def wait_for(self, n: int, timeout: float | None = None) -> pd.DataFrame:
        """Block until at least n observations are buffered, then return them.

        Args:
            n:       Minimum number of observations required.
            timeout: Seconds to wait before raising TimeoutError (None = forever).

        Returns:
            DataFrame of the most recent n observations.

        Raises:
            TimeoutError: If timeout elapses before n observations arrive.
        """
        async def _wait() -> pd.DataFrame:
            while True:
                if len(self._deque) >= n:
                    return self.snapshot(n)
                # Double-check after clearing to avoid missing an arrival that
                # landed between the size check above and the clear below.
                self._event.clear()
                if len(self._deque) >= n:
                    return self.snapshot(n)
                # Always schedule event.wait() on the loop that owns the Event.
                # If the caller is on a different loop (e.g. WorkflowEngine's
                # internal loop), bridge via run_coroutine_threadsafe so the
                # wait runs on self._loop and the result is surfaced back here.
                if asyncio.get_running_loop() is self._loop:
                    await self._event.wait()
                else:
                    fut = asyncio.run_coroutine_threadsafe(
                        self._event.wait(), self._loop
                    )
                    await asyncio.wrap_future(fut)

        if timeout is not None:
            return await asyncio.wait_for(_wait(), timeout=timeout)
        return await _wait()

    async def write_snapshot(
        self,
        n: int,
        path: Path,
        *,
        timeout: float | None = None,
    ) -> int:
        """Wait for n observations, write them to a Parquet file, return row count."""
        df = await self.wait_for(n, timeout=timeout)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
        return len(df)
