#!/usr/bin/env python3
"""Single-driver heterogeneous mix: ONE rhapsody Session orchestrating a dragon
partition (via RemoteBackendProxy, AF_INET) AND a flux partition (via
FluxExecutionBackend), concurrently on disjoint node sets — the multi-backend
scenario the partitions/proxy work exists for (cf. example 09).

Both partitions run the same workload at the same time, submitted from one
Session; we report each backend's numbers so they can be compared to standalone
(interference) and to confirm one-driver flux+dragon orchestration works.

Requires the AF_INET+shim patched clone; run on a COMPUTE node (sbatch):
  source /pscratch/sd/m/merzky/radical/dragon-investigation/env.sh
  python run_mix.py --nper N --workload W --out DIR
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import socket
import sys
import time

import rhapsody_rm
from rhapsody import ComputeTask
from rhapsody import Session
from rhapsody.backends.execution.flux.flux_backend import FluxExecutionBackend
from rhapsody.backends.multiproc.proxy import RemoteBackendProxy

import common
import workloads

TASKRUN = os.environ["RHAP_TASKRUN"]
SHIM = "/pscratch/sd/m/merzky/radical/dragon-investigation/shim/shimhost.py"
TIMEOUT = 1800


def make(specs, records, backend):
    return [ComputeTask(
        executable=TASKRUN,
        arguments=[str(d), str(c), f"{backend}-t{i:06d}", records],
        backend=backend, cpu_reqs={"cpu_processes": 1, "cpu_threads": c})
        for i, (d, c) in enumerate(specs)]


def summarize(tag, backend, nper, wl, tasks, records, makespan, out):
    # records are written straight to this shared-FS dir by the tasks (no
    # node-local gather — that undercounted at scale when one srun step failed
    # to reach every node).
    dest = records
    n_done = sum(1 for t in tasks if t["state"] == "DONE")
    # per-side makespan from THIS backend's own records (co-run shares wall-clock,
    # but each backend's util/throughput should be over its own active span).
    recs = []
    for p in glob.glob(os.path.join(dest, "*.json")):
        try:
            recs.append(json.load(open(p)))
        except (OSError, json.JSONDecodeError):
            pass
    side_mk = (max(r["t_end"] for r in recs) - min(r["t_start"] for r in recs)) if recs else makespan
    s = {"backend": backend, "sched": "mix", "nodes": nper, "workload": wl,
         "n_tasks": len(tasks), "n_done": n_done, "makespan_s": round(side_mk, 2),
         "makespan_shared_s": round(makespan, 2),
         **common.analyse(dest, nper, side_mk)}
    os.makedirs(os.path.join(out, tag), exist_ok=True)
    with open(os.path.join(out, tag, "summary.json"), "w") as f:
        json.dump(s, f, indent=2)
    print(json.dumps(s, indent=2))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nper", type=int, default=2)
    ap.add_argument("--workload", required=True, choices=list(workloads.WORKLOADS))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    nper = args.nper

    cfg = rhapsody_rm.RMConfig(requested_nodes=2 * nper)
    rm = rhapsody_rm.ResourceManager.get_instance(name="SLURM", cfg=cfg)
    pd = rhapsody_rm.partition_spec(rm, part_id="p_dragon", n_nodes=nper)
    pf = rhapsody_rm.partition_spec(rm, part_id="p_flux", n_nodes=nper)
    dhosts = ",".join(n.name for n in pd["nodelist"])
    fhosts = ",".join(n.name for n in pf["nodelist"])
    me = socket.gethostname()
    ordered = ([me] + [h for h in dhosts.split(",") if h != me]) if me in dhosts.split(",") else dhosts.split(",")
    launch_prefix = ["dragon", "--port", "7575", "--overlay-port", "6565",
                     "--frontend-port", "6566", "-N", str(nper), "--wlm", "slurm",
                     "--hostlist", ",".join(ordered), sys.executable, SHIM]
    print(f"driver={me} dragon={dhosts} flux={fhosts}")

    # one Session, two heterogeneous backends, concurrently
    dragon = await RemoteBackendProxy(
        name="p_dragon", backend="dragon", resources={"partition": pd},
        extra_env=dict(pd["env"] or {}), launch_prefix=launch_prefix)
    flux = await FluxExecutionBackend(name="p_flux", resources={"partition": pf})
    session = Session(backends=[dragon, flux])

    # shared-FS records dirs (reliable at any scale; taskrun writes here directly)
    drecs = os.path.join(args.out, "dragon", "records"); os.makedirs(drecs, exist_ok=True)
    frecs = os.path.join(args.out, "flux", "records"); os.makedirs(frecs, exist_ok=True)
    dtasks = make(workloads.WORKLOADS[args.workload](nper), drecs, "p_dragon")
    ftasks = make(workloads.WORKLOADS[args.workload](nper), frecs, "p_flux")

    try:
        t = time.perf_counter()
        await session.submit_tasks(dtasks + ftasks)
        await session.wait_tasks(dtasks + ftasks, timeout=TIMEOUT)
        makespan = time.perf_counter() - t
    finally:
        await session.close()

    summarize("dragon", "mix-dragon-proxy", nper, args.workload, dtasks, drecs, makespan, args.out)
    summarize("flux", "mix-flux", nper, args.workload, ftasks, frecs, makespan, args.out)
    print(f"MIX done: dragon {sum(1 for t in dtasks if t['state']=='DONE')}/{len(dtasks)} "
          f"flux {sum(1 for t in ftasks if t['state']=='DONE')}/{len(ftasks)} makespan={makespan:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
