#!/usr/bin/env python3
"""rhapsody-dragon, IN-PROCESS DragonExecutionBackend, run UNDER the dragon
launcher (`dragon --hostlist <partition> python rh_dragon.py ...`).

This is the released rhapsody dragon backend (dragon.workflows.batch.Batch)
driven through a rhapsody Session -- confined to a node subset purely by the
dragon launcher's --hostlist (no RemoteBackendProxy, no AF_UNIX control plane,
so dragon head-node placement is irrelevant).  No shim needed: nothing here
touches multiprocessing.connection.

  usage: dragon ... python rh_dragon.py --nodes N --ntasks M
"""
from __future__ import annotations
import argparse, asyncio, socket, sys, time

import dragon  # noqa: F401  (under the dragon launcher)
from rhapsody import ComputeTask, Session
from rhapsody.backends.execution.dragon import DragonExecutionBackend


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, required=True)
    ap.add_argument("--ntasks", type=int, default=100)
    ap.add_argument("--exe", default="/bin/true")
    args = ap.parse_args()

    print(f"[rh_dragon] host={socket.gethostname()} nodes={args.nodes} ntasks={args.ntasks}", flush=True)
    t0 = time.perf_counter()
    backend = await DragonExecutionBackend(
        batch_kwargs={"num_nodes": args.nodes, "disable_telem": True}, name="dragon")
    bringup = time.perf_counter() - t0
    session = Session(backends=[backend])
    tasks = [ComputeTask(executable=args.exe, arguments=[], backend="dragon",
                         cpu_reqs={"cpu_processes": 1, "cpu_threads": 1})
             for _ in range(args.ntasks)]
    try:
        t0 = time.perf_counter()
        await session.submit_tasks(tasks)
        await session.wait_tasks(tasks, timeout=300)
        makespan = time.perf_counter() - t0
        done = sum(1 for t in tasks if t["state"] == "DONE")
        print(f"RH_DRAGON_RESULT done={done} n={args.ntasks} bringup={bringup:.1f} makespan={makespan:.2f}", flush=True)
    finally:
        await session.close()
    return 0 if done == args.ntasks else 3


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
