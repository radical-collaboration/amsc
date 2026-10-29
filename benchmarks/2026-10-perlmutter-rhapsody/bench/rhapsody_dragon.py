#!/usr/bin/env python3
"""rhapsody-dragon cell: the RELEASED rhapsody dragon backend.

Drives rhapsody's in-process `DragonExecutionBackend` (dragon.workflows.batch
.Batch) through a rhapsody `Session`, run UNDER the dragon launcher
(`dragon [--hostlist <nodes>] python rhapsody_dragon.py ...`).  This is the
released rhapsody-dragon path — no RemoteBackendProxy / AF_UNIX control plane,
so dragon head-node placement is irrelevant.  native_dragon.py (raw dragon
Batch, no rhapsody) is the baseline that isolates rhapsody's dragon-layer cost.

  usage: dragon python rhapsody_dragon.py --nodes N --workload W --out DIR
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

import dragon  # noqa: F401  (activates the dragon runtime under the launcher)
from rhapsody import ComputeTask
from rhapsody import Session
from rhapsody.backends.execution.dragon import DragonExecutionBackend

import common
import workloads

TASKRUN = os.environ["RHAP_TASKRUN"]
WARMUP = 8
TIMEOUT = 1800


def make_tasks(specs, records):
    tasks = []
    for i, (dur, cores) in enumerate(specs):
        uid = f"t{i:06d}"
        tasks.append(ComputeTask(
            executable=TASKRUN,
            arguments=[str(dur), str(cores), uid, records],
            backend="dragon",
            cpu_reqs={"cpu_processes": 1, "cpu_threads": cores}))
    return tasks


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, required=True)
    ap.add_argument("--workload", required=True, choices=list(workloads.WORKLOADS))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    records = common.local_records_dir(f"rd-{args.workload}-N{args.nodes}")
    specs = workloads.WORKLOADS[args.workload](args.nodes)

    t = time.perf_counter()
    backend = await DragonExecutionBackend(
        batch_kwargs={"num_nodes": args.nodes, "disable_telem": True}, name="dragon")
    bringup = time.perf_counter() - t

    session = Session(backends=[backend])
    try:
        warm = make_tasks([(0, 1)] * WARMUP, records)
        await session.submit_tasks(warm)
        await session.wait_tasks(warm, timeout=TIMEOUT)

        tasks = make_tasks(specs, records)
        t = time.perf_counter()
        await session.submit_tasks(tasks)
        await session.wait_tasks(tasks, timeout=TIMEOUT)
        makespan = time.perf_counter() - t
        n_done = sum(1 for x in tasks if x["state"] == "DONE")
    finally:
        t = time.perf_counter()
        await session.close()
        teardown = time.perf_counter() - t

    hosts = os.environ.get("SLURM_NODELIST", "")
    alloc = int(os.environ.get("SLURM_NNODES", args.nodes))
    dest = os.path.join(args.out, "records")
    common.gather(hosts, alloc, records, dest)
    summary = {
        "backend": "rhapsody-dragon", "sched": "dragon", "nodes": args.nodes,
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
