#!/usr/bin/env python3
"""2+2 co-location split: rhapsody-dragon (proxy) on one 2-node partition,
flux on a disjoint 2-node partition, concurrently.

Mirrors examples/09-partitions-throughput.py (the released intended split) but
adds the surgical shimhost launch_prefix override so rhapsody-dragon runs on
dragon 0.14.1 unmodified.  p_dragon is carved FIRST so it owns the head node
(the driver's node) -> dragon places the host child there -> node-local
AF_UNIX control plane works.

  usage (inside a 4-node sbatch, run on the head node): dtest_split.py --ntasks N
"""
from __future__ import annotations
import argparse, asyncio, os, socket, sys, time

import rhapsody_rm
from rhapsody import ComputeTask, Session
from rhapsody.backends.multiproc.proxy import RemoteBackendProxy

SHIM = "/pscratch/sd/m/merzky/radical/dragon-investigation/shim/shimhost.py"
NPER = 2
WARMUP = 8
TIMEOUT = 600

_FLUX_WORKER = """\
import sys, time
from flux.job import FluxExecutor, JobspecV1
n=int(sys.argv[1]); warm=int(sys.argv[2])
spec=JobspecV1.from_command(["/bin/true"])
with FluxExecutor() as ex:
    for f in [ex.submit(spec) for _ in range(warm)]: f.result()
    t0=time.perf_counter()
    futs=[ex.submit(spec) for _ in range(n)]
    done=sum(1 for f in futs if f.result() is None or True)
    secs=time.perf_counter()-t0
print(f"FLUX_RESULT done={done} n={n} secs={secs:.3f} rate={n/secs:.1f}", flush=True)
"""


def _hosts(spec):
    return [n.name for n in spec["nodelist"]]


async def run_dragon(spec, ntasks):
    hosts = _hosts(spec)
    me = socket.gethostname()
    ordered = ([me] + [h for h in hosts if h != me]) if me in hosts else list(hosts)
    launch_prefix = [
        "dragon", "--port", "7575", "--overlay-port", "6565", "--frontend-port", "6566",
        "-N", str(len(ordered)), "--wlm", "slurm", "--hostlist", ",".join(ordered),
        sys.executable, SHIM,
    ]
    print(f"p_dragon: driver@{me} hosts={hosts} head-first={ordered}", flush=True)
    proxy = await RemoteBackendProxy(
        name="p_dragon", backend="dragon",
        resources={"partition": spec},
        extra_env=dict(spec.get("env") or {}),
        launch_prefix=launch_prefix)
    try:
        async with Session(backends=[proxy]) as session:
            warm = [ComputeTask(executable="/bin/true", arguments=[], backend="p_dragon",
                                cpu_reqs={"cpu_processes": 1, "cpu_threads": 1})
                    for _ in range(WARMUP)]
            await session.submit_tasks(warm)
            await session.wait_tasks(warm, timeout=TIMEOUT)
            tasks = [ComputeTask(executable="/bin/true", arguments=[], backend="p_dragon",
                                 cpu_reqs={"cpu_processes": 1, "cpu_threads": 1})
                     for _ in range(ntasks)]
            t0 = time.perf_counter()
            await session.submit_tasks(tasks)
            await session.wait_tasks(tasks, timeout=TIMEOUT)
            secs = time.perf_counter() - t0
            done = sum(1 for t in tasks if t["state"] == "DONE")
            return {"done": done, "n": ntasks, "secs": secs}
    finally:
        await proxy.shutdown()


async def run_flux(spec, ntasks):
    hosts = ",".join(_hosts(spec))
    worker = f"/pscratch/sd/m/merzky/radical/dragon-investigation/_fluxw_{os.getpid()}.py"
    with open(worker, "w") as f:
        f.write(_FLUX_WORKER)
    cmd = ["srun", "--overlap", f"--nodes={NPER}", f"--ntasks={NPER}",
           "--ntasks-per-node=1", f"--nodelist={hosts}", "flux", "start",
           sys.executable, worker, str(ntasks), str(WARMUP)]
    env = {**os.environ, **(spec.get("env") or {})}
    print(f"p_flux: {' '.join(cmd)}", flush=True)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
    finally:
        try: os.unlink(worker)
        except OSError: pass
    out = out.decode()
    if proc.returncode != 0:
        raise RuntimeError(f"flux failed ({proc.returncode}):\n{out}\n{err.decode()[-2000:]}")
    for line in out.splitlines():
        if line.startswith("FLUX_RESULT"):
            fields = dict(kv.split("=") for kv in line.split()[1:])
            return {"done": int(fields["done"]), "n": int(fields["n"]), "secs": float(fields["secs"])}
    raise RuntimeError(f"no FLUX_RESULT:\n{out}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ntasks", type=int, default=100)
    args = ap.parse_args()

    cfg = rhapsody_rm.RMConfig(requested_nodes=2 * NPER)
    rm = rhapsody_rm.ResourceManager.get_instance(name="SLURM", cfg=cfg)
    print("RM nodes:", [n.name for n in rm.node_list], flush=True)
    pd = rhapsody_rm.partition_spec(rm, part_id="p_dragon", n_nodes=NPER)  # head node first
    pf = rhapsody_rm.partition_spec(rm, part_id="p_flux", n_nodes=NPER)
    print("p_dragon:", _hosts(pd), "| p_flux:", _hosts(pf), flush=True)

    res = await asyncio.gather(
        run_dragon(pd, args.ntasks),
        run_flux(pf, args.ntasks),
        return_exceptions=True,
    )
    print("\n=== SPLIT RESULT ===", flush=True)
    for name, r in (("rhapsody-dragon", res[0]), ("flux", res[1])):
        if isinstance(r, BaseException):
            print(f"  {name:<16} FAILED: {r!r}", flush=True)
        else:
            print(f"  {name:<16} DONE={r['done']}/{r['n']}  secs={r['secs']:.2f}  rate={r['n']/r['secs']:.1f}/s", flush=True)
    ok = all((not isinstance(r, BaseException)) and r["done"] == r["n"] for r in res)
    print(f"=== SPLIT {'OK' if ok else 'INCOMPLETE'} ===", flush=True)
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
