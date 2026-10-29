#!/usr/bin/env python3
"""Native vs via-rhapsody Raptor: one table + CSV.

  usage: compare.py NATIVE_RESULTS_DIR RHAPSODY_RESULTS_DIR OUT_CSV

Reads native cells ``raptor-native-<wl>-N<n>/summary.json`` and the
via-rhapsody cells ``raptor-raptor-<wl>-N<n>/summary.json`` (only node counts
present in the native set). Metrics are the summary fields: throughput_overall
(record-based tasks/s), throughput_e2e (tasks / driver-measured makespan),
utilization (record-based, physical cores), bringup_s (launch overhead) and
teardown_s. ``ratio`` columns are native / rhapsody.
"""
import csv
import glob
import json
import os
import re
import sys

native_dir, rhap_dir, out_csv = sys.argv[1:4]
WL_ORDER = ["zero", "d1", "d4", "d16", "d32", "het"]
METRICS = ["n_done", "n_tasks", "bringup_s", "teardown_s", "makespan_s",
           "throughput_overall", "throughput_e2e", "throughput_steady",
           "utilization"]


def load(root, prefix):
    cells = {}
    for p in glob.glob(os.path.join(root, prefix + "-*-N*", "summary.json")):
        m = re.search(prefix + r"-(\w+)-N(\d+)/summary.json$", p)
        try:
            cells[(m.group(1), int(m.group(2)))] = json.load(open(p))
        except (OSError, json.JSONDecodeError):
            pass
    return cells


nat = load(native_dir, "raptor-native")
rap = load(rhap_dir, "raptor-raptor")
nodes = sorted({n for (_, n) in nat} or {1, 2, 4, 8})
keys = [(w, n) for w in WL_ORDER for n in nodes]

rows = []
for k in keys:
    a, b = nat.get(k), rap.get(k)
    row = {"workload": k[0], "nodes": k[1]}
    for side, s in (("native", a), ("rhapsody", b)):
        for mtr in METRICS:
            row[f"{side}_{mtr}"] = None if s is None else s.get(mtr)
    for mtr in ("throughput_overall", "throughput_e2e", "utilization", "bringup_s"):
        x, y = row[f"native_{mtr}"], row[f"rhapsody_{mtr}"]
        row[f"ratio_{mtr}"] = x / y if x and y else None
    rows.append(row)

with open(out_csv, "w", newline="") as f:
    wr = csv.DictWriter(f, fieldnames=list(rows[0]))
    wr.writeheader()
    wr.writerows(rows)


def f(v, nd=1):
    return "-" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


hdr = ("| workload | N | done (nat/rh) | thr/s nat | thr/s rh | ratio "
       "| e2e thr/s nat | e2e thr/s rh | util nat | util rh "
       "| bringup s nat | bringup s rh | teardown s nat | teardown s rh |")
print(hdr)
print("|" + "|".join(["---"] * 14) + "|")
for r in rows:
    def u(v):
        return "-" if v is None else f"{100 * v:.1f}%"
    done = f"{f(r['native_n_done'])}/{f(r['rhapsody_n_done'])} of {f(r['native_n_tasks'] or r['rhapsody_n_tasks'])}"
    print(f"| {r['workload']} | {r['nodes']} | {done} "
          f"| {f(r['native_throughput_overall'])} | {f(r['rhapsody_throughput_overall'])} "
          f"| {f(r['ratio_throughput_overall'], 2)} "
          f"| {f(r['native_throughput_e2e'])} | {f(r['rhapsody_throughput_e2e'])} "
          f"| {u(r['native_utilization'])} | {u(r['rhapsody_utilization'])} "
          f"| {f(r['native_bringup_s'], 2)} | {f(r['rhapsody_bringup_s'], 2)} "
          f"| {f(r['native_teardown_s'], 2)} | {f(r['rhapsody_teardown_s'], 2)} |")
print(f"\n{len(nat)} native cells, {sum(1 for k in keys if k in rap)} rhapsody cells -> {out_csv}")
