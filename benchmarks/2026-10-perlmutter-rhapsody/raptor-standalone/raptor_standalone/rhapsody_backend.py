"""A rhapsody execution backend driving the standalone (pilot-free) Raptor.

This module subclasses rhapsody's ``BaseBackend`` and is attachable to a
rhapsody ``Session`` exactly like the built-in backends -- but it drives a
``raptor_standalone.RaptorMaster`` + srun-launched workers instead of a full
RADICAL-Pilot session/pilot/agent.  No rp.Session, pilot, agent bootstrap, or
MongoDB is involved.

Contract implemented (see rhapsody.backends.base.BaseBackend and the other
execution backends):
  * ``__await__`` / ``_async_init`` : register state maps, start the master +
    workers, wait for worker registration.
  * ``register_callback(func)``     : Session hands us its state-manager
    callback; we invoke ``func(task, state)`` on the event loop for every
    completed task.
  * ``submit_tasks(tasks)``         : translate ComputeTask dicts to raptor
    task dicts and submit them to the master.
  * ``get_task_states_map`` / ``state`` / ``cancel_task`` / ``shutdown`` / ...

Completed results arrive from the master's ZMQ collector thread; we bridge
them onto the asyncio loop with ``loop.call_soon_threadsafe`` so the Session's
futures resolve correctly.

Construction (typical, inside a Slurm allocation)::

    from raptor_standalone.rhapsody_backend import RaptorStandaloneBackend
    be = await RaptorStandaloneBackend(
             workdir='/pscratch/.../run',
             nworkers=2,            # srun --ntasks (one worker per task)
             nslots=64,             # concurrent task slots per worker
             bulk_size=16)
    session = Session(backends=[be])
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import subprocess
import sys
import uuid
from typing import Any
from typing import Callable

from rhapsody.backends.base import BaseBackend
from rhapsody.backends.constants import BackendMainStates
from rhapsody.backends.constants import StateMapper

from .master import RaptorMaster


def _get_logger() -> logging.Logger:
    return logging.getLogger(__name__)


class RaptorStandaloneBackend(BaseBackend):
    """Pilot-free Raptor execution backend for rhapsody."""

    def __init__(
        self,
        workdir: str | None = None,
        nworkers: int = 1,
        nslots: int = 0,
        bulk_size: int = 1,
        prefetch: int = 2,
        launch_workers: bool = True,
        srun_args: list[str] | None = None,
        worker_python: str | None = None,
        name: str = "raptor",
    ) -> None:
        super().__init__(name=name)

        self.logger = _get_logger()
        self._workdir = os.path.abspath(workdir or os.getcwd())
        self._nworkers = nworkers
        self._nslots = nslots
        self._bulk_size = bulk_size
        self._prefetch = prefetch
        self._launch_workers = launch_workers
        self._srun_args = srun_args
        self._worker_python = worker_python or sys.executable

        self.tasks: dict[str, dict] = {}
        self._callback_func: Callable = lambda t, s: None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._master: RaptorMaster | None = None
        self._worker_proc: subprocess.Popen | None = None
        self._initialized = False
        self._backend_state = BackendMainStates.INITIALIZED

    # ------------------------------------------------------------------ init
    def __await__(self):
        return self._async_init().__await__()

    async def _async_init(self):
        if self._initialized:
            return self

        StateMapper.register_backend_states_with_defaults(backend=self)
        # master emits canonical "DONE"/"FAILED"/"CANCELED"/"RUNNING"
        StateMapper.register_backend_tasks_states_with_defaults(backend=self)

        self._loop = asyncio.get_running_loop()

        os.makedirs(self._workdir, exist_ok=True)
        self._master = RaptorMaster(
            workdir=self._workdir,
            bulk_size=self._bulk_size,
            result_cb=self._on_result,
        )
        self.logger.info("raptor master up: %s (info %s)",
                         self._master.uid, self._master.info_file)

        if self._launch_workers:
            self._start_workers()

        # wait for workers to register (so submit sees a live pool)
        await asyncio.get_running_loop().run_in_executor(
            None, self._master.wait_workers, self._nworkers, 180
        )
        self.logger.info("raptor workers registered: %s",
                         list(self._master.workers.keys()))

        self._backend_state = BackendMainStates.INITIALIZED
        self._initialized = True
        return self

    def _start_workers(self) -> None:
        """Launch N workers via srun inside the current Slurm allocation.

        The master's ZMQ bridge addresses are baked straight into the srun
        argv (``--req-addr`` etc.), so workers bootstrap with no shared-FS
        round-trip.  The info file is still written by the master and remains
        available as a fallback.
        """
        worker_cmd = [
            self._worker_python, "-m", "raptor_standalone.worker",
            *self._master.worker_cli_args(),
            "--prefetch", str(self._prefetch),
        ]
        if self._nslots > 0:
            worker_cmd += ["--nslots", str(self._nslots)]

        if self._srun_args is not None:
            srun = ["srun"] + self._srun_args
        else:
            srun = [
                "srun",
                "--nodes=%d" % self._nworkers,
                "--ntasks=%d" % self._nworkers,
                "--ntasks-per-node=1",
                "--cpu-bind=none",
                "--overlap",
            ]
        cmd = srun + worker_cmd

        # workers must import the raptor_standalone package
        pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = dict(os.environ)
        env["PYTHONPATH"] = pkg_root + os.pathsep + env.get("PYTHONPATH", "")

        self.logger.info("launching workers: %s", " ".join(shlex.quote(c) for c in cmd))
        wlog = open(os.path.join(self._workdir, "workers.log"), "wb")
        self._worker_proc = subprocess.Popen(cmd, cwd=pkg_root, env=env,
                                              stdout=wlog, stderr=wlog)

    # -------------------------------------------------------------- callbacks
    def register_callback(self, func: Callable[[dict, str], None]) -> None:
        self._callback_func = func

    def _on_result(self, task: dict, state: str) -> None:
        """Runs in the master's ZMQ collector thread -> bridge to the loop."""
        uid = task["uid"]
        original = self.tasks.get(uid)
        if original is None:
            return
        original["stdout"] = task.get("stdout", "")
        original["stderr"] = task.get("stderr", "")
        original["exit_code"] = task.get("exit_code")
        original["return_value"] = task.get("return_value")
        if task.get("exception"):
            original["exception"] = task["exception"]

        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._callback_func, original, state)
        else:
            self._callback_func(original, state)

    # ---------------------------------------------------------------- submit
    def get_task_states_map(self):
        return StateMapper(backend=self)

    def build_task(self, uid, task_desc, task_specific_kwargs=None):
        """Translate a rhapsody ComputeTask dict to a raptor task dict."""
        executable = task_desc.get("executable")
        if not executable:
            raise ValueError(
                "RaptorStandaloneBackend only supports executable ComputeTasks"
            )
        kw = task_desc.get("task_backend_specific_kwargs", {}) or {}
        return {
            "uid": uid,
            "executable": executable,
            "arguments": [str(a) for a in (task_desc.get("arguments") or [])],
            "environment": kw.get("environment", {}),
            "cores": kw.get("cores", 1),
            "timeout": kw.get("timeout"),
            "sandbox": kw.get("sandbox"),
        }

    async def submit_tasks(self, tasks: list[dict[str, Any]]) -> None:
        if self._backend_state != BackendMainStates.RUNNING:
            self._backend_state = BackendMainStates.RUNNING
        if self._loop is None:
            self._loop = asyncio.get_running_loop()

        raptor_tasks = []
        for task in tasks:
            uid = task.setdefault("uid", f"raptor.{uuid.uuid4().hex[:8]}")
            self.tasks[uid] = task
            raptor_tasks.append(self.build_task(uid, task))

        self._master.submit(raptor_tasks)

    async def cancel_task(self, uid: str) -> bool:
        # the standalone raptor has no mid-flight cancellation yet
        return False

    async def state(self) -> str:
        return self._backend_state.value

    def task_state_cb(self, task, state):
        pass

    def link_explicit_data_deps(self, src_task=None, dst_task=None,
                                file_name=None, file_path=None):
        pass

    def link_implicit_data_deps(self, src_task, dst_task):
        pass

    async def shutdown(self) -> None:
        self._backend_state = BackendMainStates.SHUTDOWN
        if self._master is not None:
            self._master.terminate()
        if self._worker_proc is not None:
            try:
                self._worker_proc.wait(timeout=20)
            except Exception:
                self._worker_proc.kill()
        self.logger.info("raptor standalone backend shutdown complete")

    async def __aenter__(self):
        if not self._initialized:
            await self._async_init()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.shutdown()

    @classmethod
    async def create(cls, **kwargs) -> "RaptorStandaloneBackend":
        backend = cls(**kwargs)
        return await backend
