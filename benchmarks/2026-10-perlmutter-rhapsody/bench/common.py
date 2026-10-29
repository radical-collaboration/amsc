"""Shared helpers for the rhapsody scaling benchmarks.

Records are written by each task to a *node-local* directory (fast, avoids a
shared-filesystem metadata storm that would otherwise cap launch throughput),
then gathered once per run via a single srun fan-out.  Utilization is reported
against *physical* cores (128 / Perlmutter CPU node).
"""

from __future__ import annotations

import glob
import json
import os
import subprocess

PHYS_CORES_PER_NODE = 128  # Perlmutter CPU node, physical cores


def hostlist(spec: dict) -> str:
    return ",".join(n.name for n in spec["nodelist"])


def local_records_dir(tag: str) -> str:
    """Per-run node-local directory (same path on every node)."""
    return f"/tmp/rhap_{os.environ.get('SLURM_JOB_ID', 'x')}_{tag}"


def _srun(hosts: str, nodes: int, *cmd: str) -> None:
    subprocess.run(
        ["srun", "--overlap", f"--nodes={nodes}", "--ntasks-per-node=1",
         f"--nodelist={hosts}", *cmd],
        check=False,
    )


def make_local_dir(hosts: str, nodes: int, local: str) -> None:
    """Create the node-local records dir on every partition node up front."""
    _srun(hosts, nodes, "mkdir", "-p", local)


def gather(hosts: str, nodes: int, local: str, dest: str) -> None:
    """Copy each node's local records into the shared dest dir (unique uids)."""
    os.makedirs(dest, exist_ok=True)
    _srun(hosts, nodes, "bash", "-c", f"cp -n {local}/*.json {dest}/ 2>/dev/null; true")
    _srun(hosts, nodes, "bash", "-c", f"rm -rf {local} 2>/dev/null; true")  # our own run dir only


def analyse(dest: str, nodes: int, makespan: float) -> dict:
    """Throughput + physical-core utilization from the gathered records."""
    recs = []
    for path in glob.glob(os.path.join(dest, "*.json")):
        try:
            with open(path) as f:
                recs.append(json.loads(f.read()))
        except (OSError, json.JSONDecodeError):
            pass
    if not recs:
        return {"n_records": 0}

    busy = sum(r["ncores"] * (r["t_end"] - r["t_start"]) for r in recs)
    capacity = nodes * PHYS_CORES_PER_NODE * makespan
    ends = sorted(r["t_end"] for r in recs)
    lo, hi = ends[len(ends) // 10], ends[(len(ends) * 9) // 10]
    window = hi - lo
    return {
        "n_records": len(recs),
        "utilization": busy / capacity if capacity else None,
        "throughput_overall": len(recs) / makespan if makespan else None,
        "throughput_steady": (len(ends) * 8 // 10) / window if window > 0 else None,
        "hosts": sorted({r["host"] for r in recs}),
    }
