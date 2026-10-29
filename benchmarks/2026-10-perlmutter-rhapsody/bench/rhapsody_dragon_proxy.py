#!/usr/bin/env python3
"""rhapsody-dragon-proxy cell: dragon backend hosted OUT-OF-PROCESS via
RemoteBackendProxy (AF_INET control plane + shim).

This is the 5th series: the same released dragon Batch backend, but driven
through rhapsody's RemoteBackendProxy (the partitions path) instead of
in-process — measures the proxy/IPC hop's overhead.  Requires the AF_INET
patch + shim (clone-local, NOT released) — run with the dragon-investigation
env so `import rhapsody` resolves to the patched clone:

  source /pscratch/sd/m/merzky/radical/dragon-investigation/env.sh
  <on a compute node, sbatch -q debug/regular>  python rhapsody_dragon_proxy.py \
      --nodes N --workload W --out DIR [--port-offset K]

Driver MUST run on a compute node (AF_INET driver host must be reachable from
the dragon host child).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
import time

import rhapsody_rm
from rhapsody import ComputeTask
from rhapsody import Session
from rhapsody.backends.multiproc.proxy import RemoteBackendProxy

import common
import workloads

TASKRUN = os.environ["RHAP_TASKRUN"]
SHIM = "/pscratch/sd/m/merzky/radical/dragon-investigation/shim/shimhost.py"
WARMUP = 8
TIMEOUT = 1800


def make_tasks(specs, records):
    tasks = []
    for i, (dur, cores) in enumerate(specs):
        uid = f"t{i:06d}"
        tasks.append(ComputeTask(
            executable=TASKRUN,
            arguments=[str(dur), str(cores), uid, records],
            backend="p_dragon",
            cpu_reqs={"cpu_processes": 1, "cpu_threads": cores}))
    return tasks


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, required=True)
    ap.add_argument("--workload", required=True, choices=list(workloads.WORKLOADS))
    ap.add_argument("--out", required=True)
    ap.add_argument("--port-offset", type=int, default=0)  # distinct per co-resident instance
    args = ap.parse_args()

    cfg = rhapsody_rm.RMConfig(requested_nodes=args.nodes)
    rm = rhapsody_rm.ResourceManager.get_instance(name="SLURM", cfg=cfg)
    spec = rhapsody_rm.partition_spec(rm, part_id="p_dragon", n_nodes=args.nodes)
    hosts = [n.name for n in spec["nodelist"]]
    me = socket.gethostname()
    ordered = ([me] + [h for h in hosts if h != me]) if me in hosts else hosts
    k = args.port_offset
    launch_prefix = [
        "dragon", "--port", str(7575 + k), "--overlay-port", str(6565 + k),
        "--frontend-port", str(6566 + k), "-N", str(len(ordered)),
        "--wlm", "slurm", "--hostlist", ",".join(ordered), sys.executable, SHIM]
    print(f"driver={me} partition={hosts}")

    records = common.local_records_dir(f"pxy-{args.workload}-N{args.nodes}")
    specs = workloads.WORKLOADS[args.workload](args.nodes)

    t = time.perf_counter()
    proxy = await RemoteBackendProxy(
        name="p_dragon", backend="dragon", resources={"partition": spec},
        extra_env=dict(spec.get("env") or {}), launch_prefix=launch_prefix)
    bringup = time.perf_counter() - t

    session = Session(backends=[proxy])
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

    alloc = int(os.environ.get("SLURM_NNODES", args.nodes))
    dest = os.path.join(args.out, "records")
    common.gather(os.environ.get("SLURM_NODELIST", ""), alloc, records, dest)
    summary = {
        "backend": "rhapsody-dragon-proxy", "sched": "dragon", "nodes": args.nodes,
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
