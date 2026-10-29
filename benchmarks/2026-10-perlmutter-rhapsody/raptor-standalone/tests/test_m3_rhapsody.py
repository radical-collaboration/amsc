"""Milestone 3: end-to-end rhapsody Session + standalone Raptor backend.

Runs executable tasks (taskrun or /bin/true) and asserts they reach DONE.

Modes:
  * --local N  : backend spawns workers itself is skipped; instead this driver
                 starts N worker subprocesses locally and the backend attaches
                 to them (launch_workers=False).
  * (default)  : backend launches workers via srun (run inside an allocation).
"""

import argparse
import asyncio
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rhapsody.api.session import Session
from rhapsody.api.task import ComputeTask
from raptor_standalone.rhapsody_backend import RaptorStandaloneBackend


async def run(args):
    local_procs = []
    launch = args.local == 0

    be = RaptorStandaloneBackend(
        workdir=args.workdir,
        nworkers=args.workers if launch else args.local,
        nslots=args.nslots,
        bulk_size=args.bulk,
        launch_workers=launch,
    )

    if not launch:
        # spawn workers locally; backend will just wait for them to register
        pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # the master info file is created during _async_init, so create the
        # backend's master first by awaiting init in a background task after
        # starting a placeholder; simplest: await init, which blocks on
        # wait_workers -- so spawn workers *before* awaiting.
        # We therefore construct the master eagerly here:
        from raptor_standalone.master import RaptorMaster  # noqa
        # trick: build backend object, manually init master, spawn, then await
        # the rest. To keep it simple we instead pre-create workers after the
        # info file exists by polling for it.

    # Kick off backend init in a task so we can spawn local workers once the
    # info file appears.
    t_bring0 = time.time()
    init_task = asyncio.create_task(be._async_init())

    if not launch:
        # wait for the backend to create its master, then spawn local workers
        # bootstrapped via ADDRESS ARGS (no info-file read).
        for _ in range(600):
            if be._master is not None:
                break
            await asyncio.sleep(0.1)
        pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        addr_args = be._master.worker_cli_args()
        for i in range(args.local):
            env = dict(os.environ)
            env['SLURM_PROCID'] = str(i)
            env['PYTHONPATH'] = pkg_root + os.pathsep + env.get('PYTHONPATH', '')
            lp = subprocess.Popen(
                [sys.executable, '-m', 'raptor_standalone.worker',
                 *addr_args, '--nslots', str(args.nslots or 2),
                 '--prefetch', str(args.prefetch)],
                cwd=pkg_root, env=env)
            local_procs.append(lp)

    await init_task
    bringup = time.time() - t_bring0
    print('bringup: %.2f s (master + workers up & registered)' % bringup)

    session = Session(backends=[be])

    outdir = os.path.join(args.workdir, 'task_out')
    os.makedirs(outdir, exist_ok=True)
    tasks = []
    for i in range(args.ntasks):
        uid = 'ct.%06d' % i
        if args.taskrun:
            tasks.append(ComputeTask(uid=uid, executable=args.taskrun,
                                     arguments=[args.dur, '1', uid, outdir],
                                     backend='raptor'))
        else:
            tasks.append(ComputeTask(uid=uid, executable='/bin/true',
                                     backend='raptor'))

    t0 = time.time()
    await session.submit_tasks(tasks)
    await session.wait_tasks(tasks, timeout=1200)
    dt = time.time() - t0

    done = sum(1 for t in tasks if t.get('state') == 'DONE')
    failed = sum(1 for t in tasks if t.get('state') == 'FAILED')
    print('--- M3 RESULT ---')
    print('tasks   : %d' % len(tasks))
    print('DONE    : %d' % done)
    print('FAILED  : %d' % failed)
    print('walltime: %.3f s   throughput: %.1f tasks/s'
          % (dt, len(tasks) / dt if dt else 0))
    print('sample  : uid=%s state=%s exit=%s'
          % (tasks[0]['uid'], tasks[0].get('state'), tasks[0].get('exit_code')))

    await session.close()
    for lp in local_procs:
        try:
            lp.wait(timeout=10)
        except Exception:
            lp.kill()

    assert done == len(tasks), 'not all tasks DONE: %d/%d' % (done, len(tasks))
    print('M3 PASS')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--workdir', required=True)
    p.add_argument('--ntasks', type=int, default=100)
    p.add_argument('--workers', type=int, default=2)
    p.add_argument('--local', type=int, default=0)
    p.add_argument('--nslots', type=int, default=0)
    p.add_argument('--bulk', type=int, default=1)
    p.add_argument('--prefetch', type=int, default=2)
    p.add_argument('--taskrun', default=None, help='path to taskrun binary')
    p.add_argument('--dur', default='0')
    args = p.parse_args()
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
