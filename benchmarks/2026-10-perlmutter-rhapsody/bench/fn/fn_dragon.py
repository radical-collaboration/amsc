#!/usr/bin/env python3
"""Dragon FUNCTION-task cell: rhapsody DragonExecutionBackend native function
mode (batch.function() — direct in-runtime Python call, no per-task fork/exec).
Launch under the dragon runtime:

  dragon python fn_dragon.py --nodes N --dur D --ncores C --count K --out DIR
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

from rhapsody.api.session import Session
from rhapsody.api.task import ComputeTask
try:
    from rhapsody.backends.execution.dragon import DragonExecutionBackend
except ImportError:  # chunking branch predates the V3->DragonExecutionBackend rename
    from rhapsody.backends.execution.dragon import DragonExecutionBackendV3 \
        as DragonExecutionBackend

import common
import fnpayload

TIMEOUT = 3600
WARMUP = 64


NOOP = False  # set by --noop: dispatch-only payload (no per-task record write)


def make(count, dur, ncores, records):
    if NOOP:
        return [ComputeTask(uid=f"t{i:07d}", function=fnpayload.noop,
                            args=(f"t{i:07d}",), backend="dragon")
                for i in range(count)]
    return [ComputeTask(uid=f"t{i:07d}", function=fnpayload.taskfn,
                        args=(dur, ncores, f"t{i:07d}", records), backend="dragon",
                        cpu_reqs={"cpu_processes": 1, "cpu_threads": ncores})
            for i in range(count)]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, required=True)
    ap.add_argument("--dur", type=float, default=0.0)
    ap.add_argument("--ncores", type=int, default=1)
    ap.add_argument("--count", type=int, required=True)
    ap.add_argument("--noop", action="store_true")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    args.out = os.path.abspath(args.out)  # workers may run from a different CWD
    global NOOP
    NOOP = args.noop

    records = os.path.join(args.out, "records")
    os.makedirs(records, exist_ok=True)

    t = time.perf_counter()
    backend = await DragonExecutionBackend(
        batch_kwargs={"num_nodes": args.nodes, "disable_telem": True}, name="dragon")
    bringup = time.perf_counter() - t
    session = Session(backends=[backend])
    try:
        warm = make(WARMUP, 0, 1, records)
        await session.submit_tasks(warm)
        await session.wait_tasks(warm, timeout=TIMEOUT)

        tasks = make(args.count, args.dur, args.ncores, records)
        t = time.perf_counter()
        await session.submit_tasks(tasks)
        await session.wait_tasks(tasks, timeout=TIMEOUT)
        makespan = time.perf_counter() - t
        n_done = sum(1 for x in tasks if x["state"] == "DONE")
    finally:
        t = time.perf_counter()
        await session.close()
        teardown = time.perf_counter() - t

    summary = {"backend": "dragon-fn", "sched": "fn", "nodes": args.nodes,
               "mode": "function", "dur": args.dur, "ncores": args.ncores,
               "n_tasks": args.count, "n_done": n_done,
               "bringup_s": round(bringup, 2), "teardown_s": round(teardown, 2),
               "makespan_s": round(makespan, 2),
               **({"throughput_overall": n_done / makespan if makespan else None,
                   "n_records": 0, "noop": True}
                  if NOOP else common.analyse(records, args.nodes, makespan))}
    with open(os.path.join(args.out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
