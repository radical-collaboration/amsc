#!/usr/bin/env python3
"""raptor-native cell: standalone pilot-free Raptor driven DIRECTLY (no
rhapsody import, no Session) -- the native baseline for the "raptor" cells of
the rhapsody scaling study, which drove the same Raptor through a rhapsody
Session via ``RaptorStandaloneBackend``.

Everything below mirrors ``raptor_standalone/rhapsody_backend.py`` and
``bench/raptor_one.py`` so that the only difference is the rhapsody layer:

  * same ``RaptorMaster(workdir, bulk_size=16)``;
  * same worker launch: ``srun --nodes=N --ntasks=N --ntasks-per-node=1
    --cpu-bind=none --overlap python -m raptor_standalone.worker
    <master addrs> --prefetch 4 --nslots 128``, PYTHONPATH/cwd = package root;
  * same ``wait_workers(N, 180)`` before the clock starts (bringup);
  * same task dicts as ``RaptorStandaloneBackend.build_task`` produces for
    ``raptor_one.py``'s ComputeTasks (cores=1, no env/timeout/sandbox --
    raptor_one passes no backend kwargs, so multi-core het tasks also take a
    single worker slot there);
  * one ``master.submit(all_tasks)`` call, as the backend does;
  * same teardown: ``master.terminate()`` + wait 20 s for the srun step.

It writes ``summary.json`` with the schema of the (post-processed) raptor
summaries in ``results/matrix-full``: the ``common.analyse`` fields plus
``*_e2e`` (driver-measured makespan) and ``*_record`` (makespan from the task
records, ``max(t_end) - min(t_start)``); ``throughput_overall`` and
``utilization`` are the record-based values, as in those summaries.

  usage: raptor_native_one.py --nodes N --workload W --out DIR
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shlex
import subprocess
import sys
import threading
import time

BENCH = "/pscratch/sd/m/merzky/radical/bench"
sys.path.insert(0, BENCH)

import common       # noqa: E402  (bench/common.py, read-only)
import workloads    # noqa: E402  (bench/workloads.py, read-only)

import raptor_standalone                      # noqa: E402
from raptor_standalone.master import RaptorMaster  # noqa: E402

TASKRUN = os.environ["RHAP_TASKRUN"]
TIMEOUT = 1800      # as raptor_one.py's wait_tasks timeout
NSLOTS = 128        # as raptor_one.py
BULK_SIZE = 16      # as raptor_one.py
PREFETCH = 4        # as raptor_one.py
WORKER_WAIT = 180   # as RaptorStandaloneBackend._async_init


def start_workers(master: RaptorMaster, nworkers: int, workdir: str):
    """Copy of RaptorStandaloneBackend._start_workers (default srun args)."""
    worker_cmd = [sys.executable, "-m", "raptor_standalone.worker",
                  *master.worker_cli_args(), "--prefetch", str(PREFETCH)]
    if NSLOTS > 0:
        worker_cmd += ["--nslots", str(NSLOTS)]
    srun = ["srun", "--nodes=%d" % nworkers, "--ntasks=%d" % nworkers,
            "--ntasks-per-node=1", "--cpu-bind=none", "--overlap"]
    cmd = srun + worker_cmd

    pkg_root = os.path.dirname(os.path.dirname(
        os.path.abspath(raptor_standalone.__file__)))
    env = dict(os.environ)
    env["PYTHONPATH"] = pkg_root + os.pathsep + env.get("PYTHONPATH", "")
    print("launching workers:", " ".join(shlex.quote(c) for c in cmd), flush=True)
    wlog = open(os.path.join(workdir, "workers.log"), "wb")
    return subprocess.Popen(cmd, cwd=pkg_root, env=env, stdout=wlog, stderr=wlog)


def record_span(dest: str):
    t0, t1 = None, None
    for path in glob.glob(os.path.join(dest, "*.json")):
        try:
            with open(path) as f:
                r = json.loads(f.read())
        except (OSError, json.JSONDecodeError):
            continue
        t0 = r["t_start"] if t0 is None else min(t0, r["t_start"])
        t1 = r["t_end"] if t1 is None else max(t1, r["t_end"])
    return None if t0 is None else t1 - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, required=True)
    ap.add_argument("--workload", required=True, choices=list(workloads.WORKLOADS))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    records = common.local_records_dir(f"rapn-{args.workload}-N{args.nodes}")
    specs = workloads.WORKLOADS[args.workload](args.nodes)
    workdir = os.path.join(args.out, "raptor")
    os.makedirs(workdir, exist_ok=True)

    states: dict[str, int] = {}
    lock = threading.Lock()

    def on_result(task, state):          # master's collector thread
        with lock:
            states[state] = states.get(state, 0) + 1

    t = time.perf_counter()
    master = RaptorMaster(workdir=workdir, bulk_size=BULK_SIZE, result_cb=on_result)
    wproc = start_workers(master, args.nodes, workdir)
    master.wait_workers(args.nodes, WORKER_WAIT)
    bringup = time.perf_counter() - t
    print(f"workers registered: {sorted(master.workers)}", flush=True)

    try:
        tasks = [{"uid": f"t{i:06d}", "executable": TASKRUN,
                  "arguments": [str(d), str(c), f"t{i:06d}", records],
                  "environment": {}, "cores": 1, "timeout": None,
                  "sandbox": None}
                 for i, (d, c) in enumerate(specs)]
        t = time.perf_counter()
        master.submit(tasks)
        master.wait(count=len(tasks), timeout=TIMEOUT)
        makespan = time.perf_counter() - t
        n_done = states.get("DONE", 0)
    finally:
        t = time.perf_counter()
        master.terminate()
        try:
            wproc.wait(timeout=20)
        except Exception:
            wproc.kill()
        teardown = time.perf_counter() - t

    dest = os.path.join(args.out, "records")
    common.gather(os.environ.get("SLURM_NODELIST", ""),
                  int(os.environ.get("SLURM_NNODES", args.nodes)), records, dest)
    an = common.analyse(dest, args.nodes, makespan)
    summary = {
        "backend": "raptor-native", "sched": "raptor", "nodes": args.nodes,
        "workload": args.workload, "n_tasks": len(specs), "n_done": n_done,
        "n_failed": states.get("FAILED", 0),
        "bringup_s": round(bringup, 2), "teardown_s": round(teardown, 2),
        "makespan_s": round(makespan, 2),
        **an,
    }
    n_rec = an.get("n_records", 0)
    span = record_span(dest)
    if n_rec and span:
        util_e2e = an["utilization"]                 # analyse() used makespan
        summary.update({
            "throughput_e2e": n_rec / makespan,
            "utilization_e2e": util_e2e,
            "makespan_e2e_s": round(makespan, 2),
            "makespan_record_s": round(span, 2),
            "throughput_record": n_rec / span,
            "utilization_record": util_e2e * makespan / span,
        })
        summary["throughput_overall"] = summary["throughput_record"]
        summary["utilization"] = summary["utilization_record"]
    with open(os.path.join(args.out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
