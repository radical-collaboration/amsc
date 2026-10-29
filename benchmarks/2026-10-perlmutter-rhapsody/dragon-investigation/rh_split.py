#!/usr/bin/env python3
"""Reliable 2+2 split orchestrator (run_split.py style):
  rhapsody-dragon (in-process backend, `dragon --hostlist p_dragon python rh_dragon.py`)
  || flux (`srun --overlap --nodelist p_flux flux start python fluxworker`)
concurrently on disjoint node sets of one allocation.  No AF_UNIX / no proxy.
"""
from __future__ import annotations
import argparse, os, subprocess, sys

import rhapsody_rm

HERE = "/pscratch/sd/m/merzky/radical/dragon-investigation"
NPER = 2

_FLUX_WORKER = """\
import sys, time
from flux.job import FluxExecutor, JobspecV1
n=int(sys.argv[1])
spec=JobspecV1.from_command(["/bin/true"])
with FluxExecutor() as ex:
    for f in [ex.submit(spec) for _ in range(8)]: f.result()
    t0=time.perf_counter()
    futs=[ex.submit(spec) for _ in range(n)]
    done=sum(1 for f in futs if (f.result() or True))
    secs=time.perf_counter()-t0
print(f"FLUX_RESULT done={done} n={n} secs={secs:.3f}", flush=True)
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ntasks", type=int, default=100)
    args = ap.parse_args()

    cfg = rhapsody_rm.RMConfig(requested_nodes=2 * NPER)
    rm = rhapsody_rm.ResourceManager.get_instance(name="SLURM", cfg=cfg)
    pd = rhapsody_rm.partition_spec(rm, part_id="p_dragon", n_nodes=NPER)
    pf = rhapsody_rm.partition_spec(rm, part_id="p_flux", n_nodes=NPER)
    dh = ",".join(n.name for n in pd["nodelist"])
    fh = ",".join(n.name for n in pf["nodelist"])
    print(f"p_dragon={dh}  p_flux={fh}", flush=True)

    # dragon side: rhapsody in-process backend, confined via --hostlist
    denv = {**os.environ, **(pd["env"] or {})}
    dcmd = ["dragon", "-N", str(NPER), "--wlm", "slurm", "--hostlist", dh,
            sys.executable, f"{HERE}/rh_dragon.py", "--nodes", str(NPER),
            "--ntasks", str(args.ntasks)]

    worker = f"{HERE}/_rhsplit_fluxw_{os.getpid()}.py"
    with open(worker, "w") as f:
        f.write(_FLUX_WORKER)
    fcmd = ["srun", "--overlap", f"--nodes={NPER}", f"--ntasks={NPER}",
            "--ntasks-per-node=1", f"--nodelist={fh}", "flux", "start",
            sys.executable, worker, str(args.ntasks)]
    fenv = {**os.environ, **(pf["env"] or {})}

    print("dragon:", " ".join(dcmd), flush=True)
    print("flux:  ", " ".join(fcmd), flush=True)
    dlog = open(f"{HERE}/_rhsplit_dragon.out", "w")
    flog = open(f"{HERE}/_rhsplit_flux.out", "w")
    dp = subprocess.Popen(dcmd, env=denv, stdout=dlog, stderr=subprocess.STDOUT)
    fp = subprocess.Popen(fcmd, env=fenv, stdout=flog, stderr=subprocess.STDOUT)
    drc = dp.wait(); frc = fp.wait()
    dlog.close(); flog.close()
    try: os.unlink(worker)
    except OSError: pass

    dres = fres = "(none)"
    for line in open(f"{HERE}/_rhsplit_dragon.out"):
        if line.startswith("RH_DRAGON_RESULT"): dres = line.strip()
    for line in open(f"{HERE}/_rhsplit_flux.out"):
        if line.startswith("FLUX_RESULT"): fres = line.strip()
    print("\n=== RH SPLIT RESULT ===", flush=True)
    print(f"  rhapsody-dragon rc={drc}: {dres}", flush=True)
    print(f"  flux            rc={frc}: {fres}", flush=True)
    if drc != 0 or "RH_DRAGON_RESULT" not in dres:
        print("  --- dragon tail ---", flush=True)
        os.system(f"tail -25 {HERE}/_rhsplit_dragon.out")


if __name__ == "__main__":
    main()
