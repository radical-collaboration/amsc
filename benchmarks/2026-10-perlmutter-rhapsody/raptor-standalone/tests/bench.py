"""Milestone 4 benchmark: standalone-raptor throughput/utilization sweep.

Runs the rhapsody RaptorStandaloneBackend at a given worker (node) count with
configurable slots/bulk/prefetch, submitting taskrun tasks of a known duration,
and reports throughput and core utilization.

Utilization = (n_tasks * task_dur) / (walltime * nodes * slots_per_node)
which is the fraction of worker slot-time actually spent running tasks.
"""

import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rhapsody.api.session import Session
from rhapsody.api.task import ComputeTask
from raptor_standalone.rhapsody_backend import RaptorStandaloneBackend


async def one_run(workdir, nworkers, nslots, bulk, prefetch, ntasks, taskrun, dur):
    outdir = os.path.join(workdir, 'task_out')
    os.makedirs(outdir, exist_ok=True)

    be = RaptorStandaloneBackend(
        workdir=workdir, nworkers=nworkers, nslots=nslots,
        bulk_size=bulk, prefetch=prefetch, launch_workers=True)
    t_init0 = time.time()
    await be
    t_init = time.time() - t_init0

    session = Session(backends=[be])

    tasks = []
    for i in range(ntasks):
        uid = 'b.%06d' % i
        tasks.append(ComputeTask(uid=uid, executable=taskrun,
                                 arguments=[str(dur), '1', uid, outdir],
                                 backend='raptor'))

    t0 = time.time()
    await session.submit_tasks(tasks)
    await session.wait_tasks(tasks, timeout=3600)
    dt = time.time() - t0

    done = sum(1 for t in tasks if t.get('state') == 'DONE')
    failed = ntasks - done
    thr = ntasks / dt if dt else 0
    total_slots = nworkers * nslots
    util = (ntasks * float(dur)) / (dt * total_slots) if dt and total_slots else 0

    print('[cfg nodes=%d slots=%d bulk=%d prefetch=%d dur=%s ntasks=%d] '
          'init=%.1fs wall=%.2fs DONE=%d FAIL=%d thr=%.1f/s util=%.1f%%'
          % (nworkers, nslots, bulk, prefetch, dur, ntasks,
             t_init, dt, done, failed, thr, 100 * util), flush=True)

    await session.close()
    return {'nodes': nworkers, 'slots': nslots, 'bulk': bulk,
            'prefetch': prefetch, 'dur': dur, 'ntasks': ntasks,
            'wall': dt, 'done': done, 'failed': failed,
            'throughput': thr, 'util': util, 'init': t_init}


async def main():
    p = argparse.ArgumentParser()
    p.add_argument('--workdir', required=True)
    p.add_argument('--taskrun', required=True)
    p.add_argument('--nodes', type=int, required=True,
                   help='max nodes in this allocation')
    p.add_argument('--node-sweep', default=None,
                   help='comma list of node counts (default: 1,2,..,nodes)')
    p.add_argument('--slots', type=int, default=128)
    p.add_argument('--bulk-sweep', default='1,8,32')
    p.add_argument('--prefetch', type=int, default=4)
    p.add_argument('--ntasks', type=int, default=2000)
    p.add_argument('--dur', default='0')
    args = p.parse_args()

    if args.node_sweep:
        node_list = [int(x) for x in args.node_sweep.split(',')]
    else:
        node_list = []
        k = 1
        while k <= args.nodes:
            node_list.append(k)
            k *= 2
        if node_list[-1] != args.nodes:
            node_list.append(args.nodes)

    bulks = [int(x) for x in args.bulk_sweep.split(',')]

    results = []
    run_id = 0
    for nodes in node_list:
        for bulk in bulks:
            wd = os.path.join(args.workdir, 'run_%02d_n%d_b%d' % (run_id, nodes, bulk))
            os.makedirs(wd, exist_ok=True)
            try:
                r = await one_run(wd, nodes, args.slots, bulk, args.prefetch,
                                  args.ntasks, args.taskrun, args.dur)
                results.append(r)
            except Exception as e:
                print('[cfg nodes=%d bulk=%d] FAILED: %s' % (nodes, bulk, e),
                      flush=True)
            run_id += 1
            await asyncio.sleep(2)

    import json
    with open(os.path.join(args.workdir, 'bench_results.json'), 'w') as f:
        json.dump(results, f, indent=2)
    print('BENCH DONE: %d configs' % len(results), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
