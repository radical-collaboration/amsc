#!/usr/bin/env python3
"""Native-dragon cell: submit the workload straight to the dragon Batch API.

Runs UNDER the dragon launcher (``dragon python native_dragon.py``), with no
rhapsody in the path -- the raw-dragon baseline.  Uses the same scheduled Batch
API that rhapsody's dragon backend uses, so it is a fair peer to native-flux,
but it bypasses rhapsody's multiprocessing proxy (which is broken on dragon
0.14.1).  ``Batch(num_nodes=N)`` gives per-cell node scaling.

  usage: native_dragon.py --nodes N --workload W --out DIR
"""

from __future__ import annotations

import argparse
import json
import os
import time

import dragon  # noqa: F401  (activates the dragon runtime / mp patch)
from dragon.native.process import ProcessTemplate
from dragon.workflows.batch import Batch

import common
import workloads

TASKRUN = os.environ["RHAP_TASKRUN"]
WARMUP = 8


def submit_and_wait(batch, specs, records):
    pending = set()
    for i, (dur, cores) in enumerate(specs):
        uid = f"t{i:06d}"
        opts = batch.options(name=uid)
        bt = opts.process(ProcessTemplate(
            TASKRUN, args=(str(dur), str(cores), uid, records)))
        pending.add(bt.uid)
    done = 0
    while pending:
        tuid = batch.poll(timeout=5.0)
        if tuid in pending:
            pending.discard(tuid)
            done += 1
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, required=True)
    ap.add_argument("--workload", required=True, choices=list(workloads.WORKLOADS))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    records = common.local_records_dir(f"nd-{args.workload}-N{args.nodes}")
    specs = workloads.WORKLOADS[args.workload](args.nodes)

    t = time.perf_counter()
    batch = Batch(num_nodes=args.nodes, disable_telem=True)
    bringup = time.perf_counter() - t
    try:
        submit_and_wait(batch, [(0, 1)] * WARMUP, records)  # warmup
        t = time.perf_counter()
        n_done = submit_and_wait(batch, specs, records)
        makespan = time.perf_counter() - t
    finally:
        t = time.perf_counter()
        batch.join(timeout=30.0)
        batch.destroy(timeout=30.0)
        teardown = time.perf_counter() - t

    # dragon chose which N nodes to use; gather from the whole allocation
    # (cp is a no-op on nodes with no records).
    hosts = os.environ.get("SLURM_NODELIST", "")
    alloc_nodes = int(os.environ.get("SLURM_NNODES", args.nodes))
    dest = os.path.join(args.out, "records")
    common.gather(hosts, alloc_nodes, records, dest)

    summary = {
        "backend": "native-dragon", "sched": "dragon",
        "nodes": args.nodes, "workload": args.workload,
        "n_tasks": len(specs), "n_done": n_done,
        "bringup_s": round(bringup, 2), "teardown_s": round(teardown, 2),
        "makespan_s": round(makespan, 2),
        **common.analyse(dest, args.nodes, makespan),
    }
    with open(os.path.join(args.out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
