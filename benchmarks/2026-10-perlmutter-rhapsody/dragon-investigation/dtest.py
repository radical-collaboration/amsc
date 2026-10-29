#!/usr/bin/env python3
"""rhapsody-dragon via RemoteBackendProxy -> dragon Batch, end-to-end.

Runs as PLAIN python (inside an salloc).  The proxy spawns a child
`dragon ... python -m rhapsody.backends.multiproc.host` confined to the
partition via build_launch_prefix(); the child runs the released
DragonExecutionBackend (dragon.workflows.batch.Batch).

  usage: dtest.py --nodes N --ntasks M --patch {off,on,default} [--part-id ID]

--patch off     : inject DRAGON_PATCH_MP="" into the child env (candidate fix)
--patch on      : inject DRAGON_PATCH_MP="True" (force the documented failure)
--patch default : leave DRAGON_PATCH_MP as inherited (no override)
"""
from __future__ import annotations
import argparse, asyncio, os, socket, sys, time

import rhapsody_rm
from rhapsody import ComputeTask, Session
from rhapsody.backends.multiproc.proxy import RemoteBackendProxy

TASKRUN = os.environ.get("RHAP_TASKRUN", "/bin/true")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, required=True)
    ap.add_argument("--ntasks", type=int, default=100)
    ap.add_argument("--patch", default="off", choices=["off", "on", "default"])
    ap.add_argument("--part-id", default="d0")
    ap.add_argument("--exe", default="/bin/true")
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--shim", default="none", choices=["none", "shimhost"],
                    help="shimhost = surgical launch_prefix override using shim/shimhost.py")
    ap.add_argument("--port-offset", type=int, default=0,
                    help="dragon port triplet offset (disjoint per co-located instance)")
    args = ap.parse_args()

    SHIM = "/pscratch/sd/m/merzky/radical/dragon-investigation/shim/shimhost.py"

    cfg = rhapsody_rm.RMConfig(requested_nodes=args.nodes)
    rm = rhapsody_rm.ResourceManager.get_instance(name="SLURM", cfg=cfg)
    spec = rhapsody_rm.partition_spec(rm, part_id=args.part_id, n_nodes=args.nodes)
    hosts = [n.name for n in spec["nodelist"]]
    print(f"[dtest] driver host={socket.gethostname()} partition {args.part_id}: {hosts}", flush=True)

    extra = dict(spec.get("env") or {})
    if args.patch == "off":
        extra["DRAGON_PATCH_MP"] = ""
    elif args.patch == "on":
        extra["DRAGON_PATCH_MP"] = "True"
    print(f"[dtest] patch={args.patch}  DRAGON_PATCH_MP in extra_env = "
          f"{extra.get('DRAGON_PATCH_MP','<inherit>')!r}", flush=True)

    launch_prefix = None
    if args.shim == "shimhost":
        off = args.port_offset
        launch_prefix = [
            "dragon",
            "--port", str(7575 + off),
            "--overlay-port", str(6565 + off),
            "--frontend-port", str(6566 + off),
        ]
        # Put the DRIVER's own node first so dragon places the head process
        # (the host child) on it -> AF_UNIX control socket is node-local.
        ordered = list(hosts)
        me = socket.gethostname()
        if me in ordered:
            ordered.remove(me)
            ordered.insert(0, me)
        if ordered:
            launch_prefix += ["-N", str(len(ordered)), "--wlm", "slurm",
                              "--hostlist", ",".join(ordered)]
        launch_prefix += [sys.executable, SHIM]
        print(f"[dtest] launch_prefix override: {' '.join(launch_prefix)}", flush=True)

    t0 = time.perf_counter()
    proxy = await RemoteBackendProxy(
        name=args.part_id, backend="dragon",
        resources={"partition": spec}, extra_env=extra,
        launch_prefix=launch_prefix)
    bringup = time.perf_counter() - t0
    print(f"[dtest] proxy READY (bringup {bringup:.1f}s)", flush=True)

    session = Session(backends=[proxy])
    tasks = []
    for i in range(args.ntasks):
        tasks.append(ComputeTask(
            executable=args.exe, arguments=[],
            backend=args.part_id,
            cpu_reqs={"cpu_processes": 1, "cpu_threads": 1},
        ))
    try:
        t0 = time.perf_counter()
        await session.submit_tasks(tasks)
        await session.wait_tasks(tasks, timeout=args.timeout)
        makespan = time.perf_counter() - t0
        n_done = sum(1 for t in tasks if t["state"] == "DONE")
        states = {}
        for t in tasks:
            states[t["state"]] = states.get(t["state"], 0) + 1
        print(f"[dtest] RESULT nodes={args.nodes} ntasks={args.ntasks} "
              f"DONE={n_done}/{args.ntasks} states={states} makespan={makespan:.1f}s",
              flush=True)
    finally:
        await session.close()
    print("[dtest] closed cleanly", flush=True)
    return 0 if n_done == args.ntasks else 3


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
