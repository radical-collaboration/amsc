#!/usr/bin/env python3
"""Raw dragon Batch per-task ceiling (NO rhapsody): the true target for the
rhapsody-dragon submit path. Two variants isolate the per-task options() cost:
  reuse-options   : build options once, reuse for every function()  (lower bound)
  per-task-options: batch.options(...).function() per task, like rhapsody does
Run: dragon python raw_batch_bench.py --count 40000
"""
import argparse, time
import dragon                               # noqa: F401
from dragon.workflows.batch import Batch


def no_op():
    pass


def bench(label, batch, N, per_task_options):
    t = time.perf_counter()
    if per_task_options:
        for i in range(N):
            batch.options(name=f"t{i}", timeout=1e9, stdout=None, stderr=None).function(no_op)
    else:
        opts = batch.options(timeout=1e9)
        for i in range(N):
            opts.function(no_op)
    batch.fence()
    dt = time.perf_counter() - t
    print(f"{label:26} N={N:<7} {N/dt:10.1f} tasks/s  ({dt:.2f}s)", flush=True)
    try:
        batch.clear_results()
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=40000)
    args = ap.parse_args()
    batch = Batch(task_logs=False)
    print(f"Batch up: {batch.num_workers} workers / {batch.num_managers} managers", flush=True)
    opts = batch.options(timeout=1e9)                 # warmup
    for _ in range(1000):
        opts.function(no_op)
    batch.fence()
    try:
        batch.clear_results()
    except Exception:
        pass
    for N in (10000, 40000):
        bench("raw-batch reuse-options", batch, N, False)
        bench("raw-batch per-task-opts", batch, N, True)
    try:
        batch.join(timeout=10.0)
    except Exception:
        pass


if __name__ == "__main__":
    main()
