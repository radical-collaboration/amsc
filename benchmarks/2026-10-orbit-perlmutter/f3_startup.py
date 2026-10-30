"""F3: ORBIT endpoint start-up on Perlmutter (psij via ORBIT, debug QOS).

Per run: Slurm queue wait, job start -> endpoint registered with the broker,
registered -> client session ready (radex store up). Data from the overnight
2026-10-29 runs (timings.json + sacct Submit/Start)."""
import csv
import datetime
import json
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

runs = sys.argv[1:]          # run dirs containing timings.json
rows = []
for d in runs:
    t = json.load(open(d + "/timings.json"))
    nid = t.get("native_id")
    if not nid:
        continue
    sub, start = subprocess.run(["sacct", "-nXP", "-j", str(nid), "-o", "Submit,Start"],
                                capture_output=True, text=True).stdout.split("\n")[0].split("|")
    q = (datetime.datetime.fromisoformat(start) - datetime.datetime.fromisoformat(sub)).total_seconds()
    reg = t["registered_after_submit"]
    ready = None
    for line in open(d + "/client-" + ("A" if "client_rcs" in t and "A" in t["client_rcs"] else "pD") + ".log"):
        if "radex store up" in line:
            ready = float(line.split("]")[0].strip("[ s"))
            break
    rows.append((t["tag"], q, reg - q, ready or 0.0))

with open("data/f3_startup.csv", "w") as f:
    w = csv.writer(f)
    w.writerow(["run", "queue_s", "start_to_registered_s", "registered_to_ready_s"])
    w.writerows(rows)

plt.rcParams.update({"font.size": 16})
fig, ax = plt.subplots(figsize=(9, 5.6))
labels = ["run %d" % (i + 1) for i in range(len(rows))]
q = [r[1] for r in rows]; s = [r[2] for r in rows]; c = [r[3] for r in rows]
ax.barh(labels, q, color="#bbbbbb", label="Slurm queue wait")
ax.barh(labels, s, left=q, color="#2b6cb0", label="job start → endpoint registered")
ax.barh(labels, c, left=[a + b for a, b in zip(q, s)], color="#d69e2e", label="→ session + radex store ready")
ax.set_xlabel("seconds after submit (through ORBIT psij)")
ax.invert_yaxis()
ax.legend(fontsize=12, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2, frameon=False)
ax.set_title("ORBIT endpoint start-up on Perlmutter")
fig.tight_layout()
fig.savefig("f3_startup.png", dpi=200)
fig.savefig("f3_startup.svg")
for r in rows:
    print("%-8s queue %5.1f  start->reg %5.1f  ->ready %4.1f" % r)
