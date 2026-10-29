#!/usr/bin/env python3
"""ORBIT performance benchmarks on Perlmutter (figures F1, F2, F5).

Modes:
  direct          local rhapsody.Session, no ORBIT (F2 baseline, F1 local bars)
  orbit  --tag T  embedded broker here (login node), one endpoint job; F1 + F2
  f5     --tag T  embedded broker here, two endpoint jobs; one vs two endpoints

Every phase runs in its own cwd so radical.prof files never collide.  The
endpoint job gets its own workdir as well.  Results go to <out>/results.jsonl
(one JSON record per measurement); analyze.py turns them into figures.
"""

import argparse
import asyncio
import json
import os
import socket
import sys
import time

OVN = os.environ.get('OVN', '/pscratch/sd/m/merzky/overnight-2026-10-29')
sys.path.insert(0, os.path.join(OVN, 'harness'))

import orbit_harness as oh                                           # noqa: E402

import rhapsody                                                      # noqa: E402
from rhapsody.api.session import Session                             # noqa: E402
from rhapsody.api.task import ComputeTask                            # noqa: E402
from rhapsody.backends.execution.orbit import OrbitExecutionBackend  # noqa: E402

# Workaround (not a repo edit): the rhapsody client splits submissions at
# WS_PAYLOAD_LIMIT = 8 MiB, but the ORBIT frame cap is 4 MiB, so batches of
# ~4.6k+ tasks fail to pack and the client hangs.  Split at 3 MiB instead.
import radical.orbit.plugin_rhapsody as _prh                         # noqa: E402
_prh.WS_PAYLOAD_LIMIT = 3 * 1024 * 1024

SIZES   = [2 ** i for i in range(15)]          # 1 .. 16384
REPS    = 3
F1_N    = 200
F1_WARM = 20


BATCH_TMO = 300


class Stalled(Exception):
    def __init__(self, n, done, waited):
        super().__init__('batch %d stalled: %d done after %.0fs' % (
            n, done, waited))
        self.n, self.done, self.waited = n, done, waited


def _noop():
    return True


def _noop_arg(x):
    return x


class Out:
    def __init__(self, path):
        self._f = open(path, 'a')

    def __call__(self, **rec):
        rec.setdefault('host', socket.gethostname())
        self._f.write(json.dumps(rec) + '\n')
        self._f.flush()


def log(*args):
    print(time.strftime('%H:%M:%S'), *args, flush=True)


def set_profiling(on):
    '''radical.prof reads RADICAL_PROFILE when a Profiler is constructed.'''
    os.environ['RADICAL_PROFILE'] = 'True' if on else 'False'


def enter(path):
    os.makedirs(path, exist_ok=True)
    os.chdir(path)
    return path


# ---------------------------------------------------------------------------
# F2: throughput vs batch size

def make_tasks(n, hetero, backend=None):
    kw = {'backend': backend} if backend else {}
    if hetero:
        return [ComputeTask(function=_noop_arg, args=(i,), **kw)
                for i in range(n)]
    return [ComputeTask(function=_noop, **kw) for _ in range(n)]


async def run_batch(session, n, hetero, backends=None):
    if backends:          # F5: spread the batch round-robin over backends
        tasks = []
        for i, b in enumerate(backends):
            k = n // len(backends) + (1 if i < n % len(backends) else 0)
            tasks += make_tasks(k, hetero, b)
    else:
        tasks = make_tasks(n, hetero)
    t0 = time.time()
    await session.submit_tasks(tasks)
    t1 = time.time()
    try:
        await asyncio.wait_for(session.wait_tasks(tasks), timeout=BATCH_TMO)
    except (asyncio.TimeoutError, TimeoutError):
        done = sum(1 for t in tasks if t.state == 'DONE')
        raise Stalled(n, done, time.time() - t0)
    t2 = time.time()
    bad = sum(1 for t in tasks if t.state != 'DONE')
    return {'batch_size': n, 'submit_time': t1 - t0, 'wait_time': t2 - t1,
            'total_time': t2 - t0, 'tasks_per_sec': n / (t2 - t0),
            'failed': bad}


async def f2_sweep(out, cfg, mk_backends, base, sizes=SIZES, reps=REPS,
                   spread=False):
    for rep in range(reps):
        for hetero in (False, True):
            kind = 'hetero' if hetero else 'homo'
            enter(os.path.join(base, 'f2-%s-rep%d-%s' % (cfg, rep, kind)))
            bes = [await b for b in mk_backends()]
            names = [b.name for b in bes] if spread else None
            session = Session(backends=bes)
            try:
                await run_batch(session, 1, hetero, names)     # warmup
                for n in sizes:
                    r = await run_batch(session, n, hetero, names)
                    out(fig='F2', cfg=cfg, rep=rep, kind=kind, **r)
                    log('F2 %-12s rep%d %-6s %6d  %8.1f t/s' % (
                        cfg, rep, kind, n, r['tasks_per_sec']))
            except Stalled as e:
                # record and skip the larger sizes of this rep
                out(fig='F2-stall', cfg=cfg, rep=rep, kind=kind,
                    batch_size=e.n, done=e.done, waited=e.waited)
                log('F2 %s rep%d %s STALL' % (cfg, rep, kind), e)
            finally:
                try:
                    await asyncio.wait_for(session.close(), timeout=60)
                except Exception as e:
                    log('session close failed:', repr(e))


# ---------------------------------------------------------------------------
# F1: sequential single-task latency

async def f1_seq(out, cfg, kind, backend, base, n=F1_N, warm=F1_WARM):
    phase = enter(os.path.join(base, 'f1-%s-%s' % (cfg, kind)))
    be = await backend
    session = Session(backends=[be])
    try:
        for i in range(warm + n):
            if kind == 'fn':
                t = ComputeTask(function=_noop)
            else:
                t = ComputeTask(executable='/bin/true')
            t0 = time.time()
            await session.submit_tasks([t])
            t1 = time.time()
            await asyncio.wait_for(session.wait_tasks([t]), timeout=120)
            t2 = time.time()
            if i >= warm:
                out(fig='F1', cfg=cfg, kind=kind, uid=str(t.uid),
                    state=str(t.state), t0=t0, t1=t1, t2=t2, phase=phase)
        log('F1 %s %s done' % (cfg, kind))
    finally:
        await asyncio.wait_for(session.close(), timeout=120)


# ---------------------------------------------------------------------------
# modes

async def direct(out, base):
    set_profiling(False)
    await f1_seq(out, 'local', 'fn', rhapsody.get_backend('noop'), base)
    await f1_seq(out, 'local', 'exe', rhapsody.get_backend('concurrent'), base)
    await f2_sweep(out, 'direct', lambda: [rhapsody.get_backend('noop')],
                   base)


def orbit_be(url, ep, remote, name='orbit', batch_window=None):
    return OrbitExecutionBackend(broker_url=url, endpoint_name=ep,
                                 backends=[remote], name=name,
                                 batch_window=batch_window, init_timeout=300)


async def orbit_phases(out, url, ep, tag, base, phases, f2cfg=None):
    if 'f1' in phases:
        set_profiling(True)
        # default client batch window (0.25 s); endpoint as launched
        await f1_seq(out, '%s' % tag, 'fn',  orbit_be(url, ep, 'noop'), base)
        await f1_seq(out, '%s' % tag, 'exe', orbit_be(url, ep, 'concurrent'),
                     base)
        # client batch window off: one request per submit_tasks call
        await f1_seq(out, '%s-bw0' % tag, 'fn',
                     orbit_be(url, ep, 'noop', batch_window=0), base)
        await f1_seq(out, '%s-bw0' % tag, 'exe',
                     orbit_be(url, ep, 'concurrent', batch_window=0), base)
    if 'f2' in phases:
        set_profiling(False)
        await f2_sweep(out, f2cfg or 'orbit-%s' % tag,
                       lambda: [orbit_be(url, ep, 'noop')], base)
    if 'f2bw0' in phases:
        set_profiling(False)
        await f2_sweep(out, (f2cfg or 'orbit-%s' % tag) + '-bw0',
                       lambda: [orbit_be(url, ep, 'noop', batch_window=0)],
                       base)


def with_endpoints(tag, names, env, minutes, account, body, qos='debug'):
    '''Broker here, one endpoint job per name, run body(url), always scancel.'''
    base = enter(os.path.join(OVN, 'runs', 'perf', tag))
    set_profiling(True)                      # broker.prof for F1 hop costs
    broker, url = oh.start_broker()
    log('broker', url)
    jobs = []
    rt = None
    try:
        for name in names:
            jobs.append(oh.sbatch_endpoint(
                url, name, os.path.join(base, 'endpoint-%s' % name),
                minutes=minutes, account=account, env=env,
                qos=qos))
            log('endpoint job', name, jobs[-1])
        enter(os.path.join(base, 'client'))
        rt = oh.connect(url)
        for name in names:
            log('endpoint %s registered after %.1fs' % (
                name, oh.wait_endpoint(rt, name, timeout=3600)))
        for name, job in zip(names, jobs):
            log('JOBINFO', name, job)
        body(url, base)
    finally:
        for job in jobs:
            oh.scancel(job)
        if rt:
            for name in names:
                try:
                    oh.wait_endpoint_gone(rt, name)
                except Exception as e:
                    log('gone check', name, e)
            rt.stop()
        broker.stop()
        log('shut down')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['direct', 'orbit', 'f5'])
    ap.add_argument('--tag', default='default')
    ap.add_argument('--notify-window', default=None)
    ap.add_argument('--phases', default='f1,f2')
    ap.add_argument('--minutes', type=int, default=25)
    ap.add_argument('--account', default='amsc007')
    ap.add_argument('--f2cfg', default=None)
    ap.add_argument('--batch-timeout', type=float, default=300)
    ap.add_argument('--qos', default='debug')
    args = ap.parse_args()

    if args.mode == 'direct':
        base = enter(os.path.join(OVN, 'runs', 'perf', 'direct'))
        out = Out(os.path.join(base, 'results.jsonl'))
        asyncio.run(direct(out, base))
        return

    global BATCH_TMO
    BATCH_TMO = args.batch_timeout
    env = {'RADICAL_PROFILE': 'True'}
    if args.notify_window is not None:
        env['RADICAL_ORBIT_RHAPSODY_NOTIFY_WINDOW'] = args.notify_window
    phases = args.phases.split(',')

    if args.mode == 'orbit':
        ep = 'perf-%s' % args.tag

        def body(url, base):
            out = Out(os.path.join(base, 'results.jsonl'))
            asyncio.run(orbit_phases(out, url, ep, args.tag, base, phases,
                                     args.f2cfg))

        with_endpoints(args.tag, [ep], env, args.minutes, args.account, body,
                       args.qos)

    else:   # f5
        eps = ['perf-%s-a' % args.tag, 'perf-%s-b' % args.tag]
        sizes = [2 ** i for i in range(6, 15)]

        def body(url, base):
            out = Out(os.path.join(base, 'results.jsonl'))

            async def run():
                set_profiling(False)
                await f2_sweep(out, 'f5-one', lambda: [orbit_be(url, eps[0],
                               'noop')], base, sizes=sizes)
                await f2_sweep(out, 'f5-two', lambda: [
                    orbit_be(url, eps[0], 'noop', name='orbit_a'),
                    orbit_be(url, eps[1], 'noop', name='orbit_b')],
                    base, sizes=sizes, spread=True)
            asyncio.run(run())

        with_endpoints(args.tag, eps, env, args.minutes, args.account, body,
                       args.qos)


if __name__ == '__main__':
    main()
