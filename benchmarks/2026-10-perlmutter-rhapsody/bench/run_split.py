#!/usr/bin/env python3
"""Part B: co-located 4+4 split.

native-dragon on one 4-node partition and native-flux on a disjoint 4-node
partition, launched concurrently with the same workload, to measure
cross-backend co-location on a shared allocation.

rhapsody_rm.partition_spec carves the allocation and hands each partition a
SLURM env scoped to its node subset; applying the dragon partition's env to the
dragon subprocess makes dragon's `--wlm slurm` see only its 4 nodes, disjoint
from the flux partition (which is pinned via `srun --nodelist`).

  usage (inside an >=8-node alloc):
    python run_split.py --workload W --out DIR [--nper 4]
"""

from __future__ import annotations

import argparse
import os
import subprocess

import rhapsody_rm

BENCH = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workload", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--nper", type=int, default=4)
    args = ap.parse_args()
    nper = args.nper

    cfg = rhapsody_rm.RMConfig(requested_nodes=2 * nper)
    rm = rhapsody_rm.ResourceManager.get_instance(name="SLURM", cfg=cfg)
    # carve p_dragon first so it owns the allocation's head node
    pd = rhapsody_rm.partition_spec(rm, part_id="p_dragon", n_nodes=nper)
    pf = rhapsody_rm.partition_spec(rm, part_id="p_flux", n_nodes=nper)
    dhosts = ",".join(n.name for n in pd["nodelist"])
    fhosts = ",".join(n.name for n in pf["nodelist"])
    print("dragon:", dhosts, "| flux:", fhosts)

    dout = os.path.join(args.out, "rhapsody-dragon"); os.makedirs(dout, exist_ok=True)
    fout = os.path.join(args.out, "native-flux"); os.makedirs(fout, exist_ok=True)

    # dragon: released rhapsody-dragon, confined to its partition via the dragon
    # launcher's --hostlist plus the partition's SLURM env.
    denv = {**os.environ, **(pd["env"] or {})}
    dcmd = ["dragon", "-N", str(nper), "--wlm", "slurm", "--hostlist", dhosts,
            "python", f"{BENCH}/rhapsody_dragon.py",
            "--nodes", str(nper), "--workload", args.workload, "--out", dout]
    # flux: pinned to its partition via --nodelist
    fcmd = ["srun", "--overlap", f"--nodes={nper}", f"--ntasks={nper}",
            "--ntasks-per-node=1", f"--nodelist={fhosts}", "flux", "start",
            "python", f"{BENCH}/native_flux.py",
            "--nodes", str(nper), "--workload", args.workload, "--out", fout]

    with open(os.path.join(dout, "run.log"), "w") as dl, \
         open(os.path.join(fout, "run.log"), "w") as fl:
        dp = subprocess.Popen(dcmd, env=denv, stdout=dl, stderr=subprocess.STDOUT)
        fp = subprocess.Popen(fcmd, stdout=fl, stderr=subprocess.STDOUT)
        drc = dp.wait()
        frc = fp.wait()
    print(f"split done: dragon rc={drc} flux rc={frc}")


if __name__ == "__main__":
    main()
