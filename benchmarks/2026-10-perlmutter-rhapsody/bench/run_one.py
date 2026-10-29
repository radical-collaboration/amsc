#!/usr/bin/env python3
"""Run ONE benchmark cell via rhapsody's flux backend.

Measures backend launch overhead (bringup/teardown, timed separately), task
throughput (steady-state), physical-core utilization, and placement.  Tasks
write placement records to a node-local dir; we gather them once at the end.

  usage: run_one.py --sched {simple,fluxion} --nodes N
                    --workload {zero,d1,d4,d16,d32,het} --out DIR
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

import rhapsody_rm
from rhapsody import ComputeTask
from rhapsody import Session
from rhapsody.backends.execution.flux.flux_backend import FluxExecutionBackend

import common
import workloads

TASKRUN = os.environ["RHAP_TASKRUN"]
BENCH = os.path.dirname(os.path.abspath(__file__))
WARMUP = 8
TIMEOUT = 1800


def make_tasks(specs, records_dir):
    env = {k: v for k, v in os.environ.items() if k != "FLUX_URI"}
    tasks = []
    for i, (dur, cores) in enumerate(specs):
        uid = f"t{i:06d}"
        tasks.append(ComputeTask(
            executable=TASKRUN,
            arguments=[str(dur), str(cores), uid, records_dir],
            backend="bench",
            cpu_reqs={"cpu_processes": 1, "cpu_threads": cores},
            environment=env,
        ))
    return tasks


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sched", default="simple", choices=["simple", "fluxion"])
    ap.add_argument("--nodes", type=int, required=True)
    ap.add_argument("--workload", required=True, choices=list(workloads.WORKLOADS))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    # Scheduler selection is environment-driven: the caller sources
    # fluxion_modprobe.env.sh (sets FLUX_MODPROBE_PATH_APPEND) for fluxion, or
    # nothing for sched-simple.  FluxService's `flux start` inherits it.
    # --sched here is only a label for the summary.

    cfg = rhapsody_rm.RMConfig(requested_nodes=args.nodes)
    rm = rhapsody_rm.ResourceManager.get_instance(name="SLURM", cfg=cfg)
    spec = rhapsody_rm.partition_spec(rm, part_id="bench", n_nodes=args.nodes)
    hosts = common.hostlist(spec)
    print(f"partition: {hosts}")

    records = common.local_records_dir(f"rh-{args.sched}-{args.workload}-N{args.nodes}")
    specs = workloads.WORKLOADS[args.workload](args.nodes)  # taskrun self-creates the dir

    t = time.perf_counter()
    backend = await FluxExecutionBackend(name="bench", resources={"partition": spec})
    bringup = time.perf_counter() - t

    session = Session(backends=[backend])
    try:
        warm = make_tasks([(0, 1)] * WARMUP, records)
        await session.submit_tasks(warm)
        await session.wait_tasks(warm, timeout=TIMEOUT)

        tasks = make_tasks(specs, records)
        t = time.perf_counter()
        # rhapsody's flux backend submit has a 60s per-call timeout, so large
        # workloads are submitted in chunks (also keeps the pipeline filling
        # while earlier chunks run).
        CHUNK = 4000
        for i in range(0, len(tasks), CHUNK):
            await session.submit_tasks(tasks[i:i + CHUNK])
        await session.wait_tasks(tasks, timeout=TIMEOUT)
        makespan = time.perf_counter() - t
        n_done = sum(1 for x in tasks if x["state"] == "DONE")
    finally:
        t = time.perf_counter()
        await session.close()
        teardown = time.perf_counter() - t

    dest = os.path.join(args.out, "records")
    common.gather(hosts, args.nodes, records, dest)
    summary = {
        "backend": "rhapsody-flux", "sched": args.sched, "nodes": args.nodes,
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
