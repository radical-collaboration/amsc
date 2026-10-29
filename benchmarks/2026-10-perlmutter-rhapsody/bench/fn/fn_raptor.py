#!/usr/bin/env python3
"""Raptor FUNCTION-task cell: standalone pilot-free Raptor (function-capable
clone) running a Python callable in-worker (no fork/exec per task). Run on a
compute node (sbatch); the backend srun-launches its workers.

  usage: fn_raptor.py --nodes N --dur D --ncores C --count K --nslots S --out DIR
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

from rhapsody.api.session import Session
from rhapsody.api.task import ComputeTask
from raptor_standalone.rhapsody_backend import RaptorStandaloneBackend

import common
import fnpayload

TIMEOUT = 3600


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, required=True)
    ap.add_argument("--dur", type=float, default=0.0)
    ap.add_argument("--ncores", type=int, default=1)
    ap.add_argument("--count", type=int, required=True)
    ap.add_argument("--nslots", type=int, default=128)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    args.out = os.path.abspath(args.out)  # workers may run from a different CWD

    records = os.path.join(args.out, "records")
    os.makedirs(records, exist_ok=True)
    os.environ["RHAP_FN_WRAP_DIR"] = os.path.join(args.out, "blobs")

    t = time.perf_counter()
    be = await RaptorStandaloneBackend(
        workdir=os.path.join(args.out, "raptor"),
        nworkers=args.nodes, nslots=args.nslots, bulk_size=16, prefetch=4,
        launch_workers=True)
    bringup = time.perf_counter() - t

    session = Session(backends=[be])
    try:
        tasks = [ComputeTask(uid=f"t{i:07d}", function=fnpayload.taskfn,
                             args=(args.dur, args.ncores, f"t{i:07d}", records),
                             backend="raptor")
                 for i in range(args.count)]
        t = time.perf_counter()
        await session.submit_tasks(tasks)
        await session.wait_tasks(tasks, timeout=TIMEOUT)
        makespan = time.perf_counter() - t
        n_done = sum(1 for x in tasks if x["state"] == "DONE")
        if n_done < len(tasks):  # diagnostic: surface the first failure
            bad = next((x for x in tasks if x["state"] != "DONE"), None)
            if bad is not None:
                print("DIAG first non-DONE task:", {k: bad.get(k) for k in
                      ("uid", "state", "exit_code", "exception", "stderr",
                       "mode", "function_blob", "args")}, flush=True)
    finally:
        t = time.perf_counter()
        await session.close()
        teardown = time.perf_counter() - t

    summary = {"backend": "raptor-fn", "sched": "fn", "nodes": args.nodes,
               "mode": "function", "dur": args.dur, "ncores": args.ncores,
               "nslots": args.nslots, "n_tasks": args.count, "n_done": n_done,
               "bringup_s": round(bringup, 2), "teardown_s": round(teardown, 2),
               "makespan_s": round(makespan, 2),
               **common.analyse(records, args.nodes, makespan)}
    with open(os.path.join(args.out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
