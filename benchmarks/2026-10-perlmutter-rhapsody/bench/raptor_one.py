#!/usr/bin/env python3
"""raptor cell: standalone pilot-free Raptor (extracted from RADICAL-Pilot)
driven through a rhapsody Session — the 6th backend. The backend srun-launches
its own master+workers across the allocation (no pilot/agent/mongo). Run on a
compute node (sbatch).

  usage: raptor_one.py --nodes N --workload W --out DIR
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
import workloads

TASKRUN = os.environ["RHAP_TASKRUN"]
TIMEOUT = 1800
NSLOTS = 128  # concurrent task slots per worker = physical cores / node


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, required=True)
    ap.add_argument("--workload", required=True, choices=list(workloads.WORKLOADS))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    records = common.local_records_dir(f"rap-{args.workload}-N{args.nodes}")
    specs = workloads.WORKLOADS[args.workload](args.nodes)

    t = time.perf_counter()
    be = await RaptorStandaloneBackend(
        workdir=os.path.join(args.out, "raptor"),
        nworkers=args.nodes, nslots=NSLOTS, bulk_size=16, prefetch=4,
        launch_workers=True)
    bringup = time.perf_counter() - t

    session = Session(backends=[be])
    try:
        tasks = [ComputeTask(uid=f"t{i:06d}", executable=TASKRUN,
                             arguments=[str(d), str(c), f"t{i:06d}", records],
                             backend="raptor")
                 for i, (d, c) in enumerate(specs)]
        t = time.perf_counter()
        await session.submit_tasks(tasks)
        await session.wait_tasks(tasks, timeout=TIMEOUT)
        makespan = time.perf_counter() - t
        n_done = sum(1 for x in tasks if x["state"] == "DONE")
    finally:
        t = time.perf_counter()
        await session.close()
        teardown = time.perf_counter() - t

    dest = os.path.join(args.out, "records")
    common.gather(os.environ.get("SLURM_NODELIST", ""),
                  int(os.environ.get("SLURM_NNODES", args.nodes)), records, dest)
    summary = {
        "backend": "raptor", "sched": "raptor", "nodes": args.nodes,
        "workload": args.workload, "n_tasks": len(specs), "n_done": n_done,
        "bringup_s": round(bringup, 2), "teardown_s": round(teardown, 2),
        "makespan_s": round(makespan, 2),
        **common.analyse(dest, args.nodes, makespan),
    }
    with open(os.path.join(args.out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
