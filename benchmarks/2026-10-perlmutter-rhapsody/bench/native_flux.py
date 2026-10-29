#!/usr/bin/env python3
"""Native-flux cell: submit the workload straight to flux via FluxExecutor.

Runs INSIDE a flux instance (launched by the orchestration as
``srun ... flux start python native_flux.py``), with no rhapsody in the path --
this is the raw-flux baseline the rhapsody numbers are compared against.  The
scheduler (sched-simple vs fluxion) is chosen by the FLUX_RC_EXTRA the
orchestration set before `flux start`.

  usage: native_flux.py --nodes N --workload W --out DIR
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time

from flux.job import FluxExecutor
from flux.job import JobspecV1

import common
import workloads

TASKRUN = os.environ["RHAP_TASKRUN"]
WARMUP = 8


def jobspec(dur, cores, uid, records):
    spec = JobspecV1.from_command(
        [TASKRUN, str(dur), str(cores), uid, records],
        num_tasks=1, cores_per_task=cores)
    spec.duration = 0  # unlimited
    return spec


def run(executor, specs, records):
    futs = [executor.submit(jobspec(d, c, f"t{i:06d}", records))
            for i, (d, c) in enumerate(specs)]
    done = 0
    for f in futs:
        if f.result() == 0:
            done += 1
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, required=True)
    ap.add_argument("--workload", required=True, choices=list(workloads.WORKLOADS))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    records = common.local_records_dir(f"nf-{args.workload}-N{args.nodes}")
    specs = workloads.WORKLOADS[args.workload](args.nodes)

    with FluxExecutor() as ex:
        run(ex, [(0, 1)] * WARMUP, records)          # warmup
        t = time.perf_counter()
        n_done = run(ex, specs, records)
        makespan = time.perf_counter() - t

    # gather node-local records off every broker rank, then analyse
    dest = os.path.join(args.out, "records")
    os.makedirs(dest, exist_ok=True)
    subprocess.run(["flux", "exec", "-r", "all", "bash", "-c",
                    f"cp -n {records}/*.json {dest}/ 2>/dev/null; rm -rf {records}; true"],
                   check=False)

    summary = {
        "backend": "native-flux", "sched": os.environ.get("BENCH_SCHED", "simple"),
        "nodes": args.nodes, "workload": args.workload,
        "n_tasks": len(specs), "n_done": n_done,
        "makespan_s": round(makespan, 2),
        **common.analyse(dest, args.nodes, makespan),
    }
    with open(os.path.join(args.out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
