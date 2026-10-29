"""Standalone-raptor driver / benchmark.

Two modes:
  * --local N       : spawn N worker processes locally (login-node smoke test)
  * (default)       : workers are launched externally (e.g. via srun); the
                      driver waits for --workers to register, then submits.

Submits --ntasks tasks running --exe with --args, waits for completion, and
reports throughput.
"""

import os
import sys
import time
import json
import argparse
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from raptor_standalone import RaptorMaster


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--workdir',  required=True)
    p.add_argument('--ntasks',   type=int, default=100)
    p.add_argument('--workers',  type=int, default=1,
                   help='number of workers to wait for before submitting')
    p.add_argument('--bulk',     type=int, default=1)
    p.add_argument('--exe',      default='/bin/true')
    p.add_argument('--dur',      default=None,
                   help='if set, treat --exe as taskrun: exe dur cores uid outdir')
    p.add_argument('--outdir',   default=None)
    p.add_argument('--local',    type=int, default=0,
                   help='spawn N local worker subprocesses for a smoke test')
    p.add_argument('--nslots',   type=int, default=0)
    p.add_argument('--prefetch', type=int, default=2)
    args = p.parse_args()

    os.makedirs(args.workdir, exist_ok=True)

    counters = {'done': 0, 'failed': 0}
    def cb(task, state):
        if state == 'DONE': counters['done']   += 1
        else              : counters['failed'] += 1

    m = RaptorMaster(workdir=args.workdir, bulk_size=args.bulk, result_cb=cb)
    print('master up: %s' % m.uid)
    print('info file: %s' % m.info_file)

    local_procs = []
    if args.local > 0:
        venv_py = sys.executable
        for i in range(args.local):
            env = dict(os.environ)
            env['SLURM_PROCID'] = str(i)
            lp = subprocess.Popen(
                [venv_py, '-m', 'raptor_standalone.worker',
                 *m.worker_cli_args(),
                 '--nslots', str(args.nslots or 2),
                 '--prefetch', str(args.prefetch)],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                env=env)
            local_procs.append(lp)

    print('waiting for %d worker(s)...' % args.workers)
    n = m.wait_workers(args.workers, timeout=180)
    print('%d workers registered: %s' % (n, list(m.workers.keys())))

    # build tasks
    tasks = []
    for i in range(args.ntasks):
        uid = 'task.%06d' % i
        if args.dur is not None:
            outdir = args.outdir or os.path.join(args.workdir, 'task_out')
            os.makedirs(outdir, exist_ok=True)
            tasks.append({'uid': uid, 'executable': args.exe,
                          'arguments': [args.dur, '1', uid, outdir]})
        else:
            tasks.append({'uid': uid, 'executable': args.exe, 'arguments': []})

    t0 = time.time()
    m.submit(tasks)
    print('submitted %d tasks' % args.ntasks)
    m.wait(count=args.ntasks, timeout=1200)
    t1 = time.time()

    dt = t1 - t0
    print('--- RESULT ---')
    print('tasks     : %d' % args.ntasks)
    print('done      : %d' % counters['done'])
    print('failed    : %d' % counters['failed'])
    print('walltime  : %.3f s' % dt)
    print('throughput: %.1f tasks/s' % (args.ntasks / dt if dt else 0))
    print('workers   : %d  slots/worker: %s' %
          (n, [w.get('nslots') for w in m.workers.values()]))
    print('stats     : %s' % m.stats)

    summary = {'ntasks': args.ntasks, 'done': counters['done'],
               'failed': counters['failed'], 'walltime': dt,
               'throughput': args.ntasks / dt if dt else 0,
               'workers': n, 'bulk': args.bulk,
               'nslots': [w.get('nslots') for w in m.workers.values()]}
    with open(os.path.join(args.workdir, 'summary.json'), 'w') as f:
        json.dump(summary, f, indent=2)

    m.terminate()
    for lp in local_procs:
        try:
            lp.wait(timeout=10)
        except Exception:
            lp.kill()
    print('done.')


if __name__ == '__main__':
    main()
