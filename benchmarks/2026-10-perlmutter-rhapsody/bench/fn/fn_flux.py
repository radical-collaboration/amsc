#!/usr/bin/env python3
"""Flux FUNCTION-task cell (patched rhapsody clone with the function->flux
wrapper). Submits `count` ComputeTasks carrying a Python callable (fnpayload.
taskfn); the patched FluxExecutionBackend cloudpickles each and launches the
wrapper as a flux job. Measures whether/how fast Flux runs functions.

  usage: fn_flux.py --nodes N --dur D --ncores C --count K --out DIR
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

import rhapsody_rm
from rhapsody.api.session import Session
from rhapsody.api.task import ComputeTask
from rhapsody.backends.execution.flux.flux_backend import FluxExecutionBackend

import common
import fnpayload

TIMEOUT = 3600


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, required=True)
    ap.add_argument("--dur", type=float, default=0.0)
    ap.add_argument("--ncores", type=int, default=1)
    ap.add_argument("--count", type=int, required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    args.out = os.path.abspath(args.out)  # workers may run from a different CWD

    records = os.path.join(args.out, "records")
    os.makedirs(records, exist_ok=True)
    os.environ["RHAP_FN_WRAP_DIR"] = os.path.join(args.out, "blobs")

    cfg = rhapsody_rm.RMConfig(requested_nodes=args.nodes)
    rm = rhapsody_rm.ResourceManager.get_instance(name="SLURM", cfg=cfg)
    spec = rhapsody_rm.partition_spec(rm, part_id="fn", n_nodes=args.nodes)

    t = time.perf_counter()
    be = await FluxExecutionBackend(name="fn", resources={"partition": spec})
    bringup = time.perf_counter() - t
    session = Session(backends=[be])

    tasks = [ComputeTask(uid=f"t{i:07d}", function=fnpayload.taskfn,
                         args=(args.dur, args.ncores, f"t{i:07d}", records),
                         backend="fn",
                         cpu_reqs={"cpu_processes": 1, "cpu_threads": args.ncores})
             for i in range(args.count)]
    try:
        t = time.perf_counter()
        await session.submit_tasks(tasks)
        await session.wait_tasks(tasks, timeout=TIMEOUT)
        makespan = time.perf_counter() - t
        n_done = sum(1 for x in tasks if x["state"] == "DONE")
    finally:
        t = time.perf_counter()
        await session.close()
        teardown = time.perf_counter() - t

    summary = {"backend": "flux-fn", "sched": "fn", "nodes": args.nodes,
               "mode": "function", "dur": args.dur, "ncores": args.ncores,
               "n_tasks": args.count, "n_done": n_done,
               "bringup_s": round(bringup, 2), "teardown_s": round(teardown, 2),
               "makespan_s": round(makespan, 2),
               **common.analyse(records, args.nodes, makespan)}
    with open(os.path.join(args.out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
