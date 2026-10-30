"""F4: pitzDaily optimization, local (Dragon on one node) vs. through ORBIT.

Local: `dragon driver-*.py` wall time on one Perlmutter CPU node (includes
Dragon start). ORBIT: endpoint start (job start -> session and radex store
ready, median of 8 psij-started endpoints; Slurm queue wait excluded), then
the client's optimization wall time (client on a login node). Overnight
2026-10-29 runs (Slurm 60517323 local; f4staged/f4video ORBIT)."""
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

rows = [  # scenario, local_total, orbit_start, orbit_optimization
    ("staged\n5 per batch, 4 iter.", 113.2, 36.0, 104.6),
    ("video size\n4 per batch, 4 iter.", 109.0, 36.0, 105.7),
]
with open("data/f4_app_overhead.csv", "w") as f:
    w = csv.writer(f)
    w.writerow(["scenario", "local_total_s", "orbit_endpoint_start_s", "orbit_optimization_s"])
    w.writerows([(r[0].replace("\n", " "),) + r[1:] for r in rows])

plt.rcParams.update({"font.size": 16})
fig, ax = plt.subplots(figsize=(9, 5))
y = range(len(rows))
h = 0.36
ax.barh([i - h / 2 for i in y], [r[1] for r in rows], h, color="#718096", label="local (Dragon on 1 node, incl. start)")
ax.barh([i + h / 2 for i in y], [r[2] for r in rows], h, color="#d69e2e", label="ORBIT: endpoint start (excl. queue)")
ax.barh([i + h / 2 for i in y], [r[3] for r in rows], h, left=[r[2] for r in rows], color="#2b6cb0", label="ORBIT: optimization")
ax.set_yticks(list(y))
ax.set_yticklabels([r[0] for r in rows])
ax.invert_yaxis()
ax.set_xlabel("wall time (s)")
ax.set_title("pitzDaily optimization: local vs. through ORBIT")
ax.legend(fontsize=12, loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=2, frameon=False)
fig.tight_layout()
fig.savefig("f4_app_overhead.png", dpi=200)
fig.savefig("f4_app_overhead.svg")
