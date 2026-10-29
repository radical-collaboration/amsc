#!/usr/bin/env python3
"""Aggregate all cell summaries under a results dir into a table + CSV."""
import csv
import glob
import json
import os
import sys

root = sys.argv[1]
rows = []
for path in sorted(glob.glob(os.path.join(root, "*", "summary.json"))):
    try:
        rows.append(json.load(open(path)))
    except (OSError, json.JSONDecodeError):
        pass

cols = ["workload", "nodes", "backend", "sched", "n_done", "n_tasks",
        "bringup_s", "teardown_s", "makespan_s",
        "throughput_steady", "throughput_overall", "utilization"]

def fmt(v):
    if isinstance(v, float):
        return f"{v:.3f}" if v < 100 else f"{v:.1f}"
    return "" if v is None else str(v)

rows.sort(key=lambda d: (d.get("workload", ""), d.get("nodes", 0),
                         d.get("backend", ""), d.get("sched", "")))

w = {c: max(len(c), *(len(fmt(r.get(c))) for r in rows)) if rows else len(c) for c in cols}
line = "  ".join(c.ljust(w[c]) for c in cols)
print(line); print("-" * len(line))
for r in rows:
    print("  ".join(fmt(r.get(c)).ljust(w[c]) for c in cols))

csv_path = os.path.join(root, "results.csv")
with open(csv_path, "w", newline="") as f:
    wr = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
    wr.writeheader()
    wr.writerows(rows)
print(f"\n{len(rows)} cells -> {csv_path}")
