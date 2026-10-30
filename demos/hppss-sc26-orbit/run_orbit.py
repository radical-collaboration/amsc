"""Run one or more driver-orbit.py clients against one fresh ORBIT endpoint.

Hosts the embedded broker, submits the endpoint job, waits for it to
register, runs the clients as subprocesses (in parallel), then stops the
endpoint and the broker.  Endpoint start-up timings go to ``timings.json``.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import orbit_harness as oh                                           # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--tag', required=True)
    p.add_argument('--account', default='amsc007')
    p.add_argument('--pitzdaily-dir', default=os.path.join(
        os.environ.get('PSCRATCH', '.'),
        'hppss/rhapsody-plugins-openfoam/examples/pitzDaily-optimize'),
        help='example dir providing pitzdaily_case.py')
    p.add_argument('--clients', type=int, default=1)
    p.add_argument('--minutes', type=int, default=30)
    p.add_argument('--client-timeout', type=int, default=1500)
    p.add_argument('--launch', choices=['sbatch', 'psij'], default='sbatch',
                   help='psij: the broker hosts psij and the client starts the endpoint through ORBIT (W4)')
    p.add_argument('--no-uid-offset', action='store_true',
                   help='do not give clients separate task-uid ranges (tests the ORBIT fix)')
    p.add_argument('--targets', default=None,
                   help='comma-separated avgInlets targets, one per client')
    p.add_argument('driver_args', nargs=argparse.REMAINDER)
    args = p.parse_args()

    # run directories go under the current directory (shared filesystem)
    workdir = os.path.join(os.getcwd(), '%s-%s' % (args.tag, time.strftime('%H%M%S')))
    os.makedirs(workdir)
    shutil.copy(os.path.join(HERE, 'driver-orbit.py'), workdir)
    shutil.copy(os.path.join(args.pitzdaily_dir, 'pitzdaily_case.py'), workdir)
    os.chdir(workdir)
    timings = {'tag': args.tag}

    broker, url = oh.start_broker(plugins='psij' if args.launch == 'psij' else '')
    print('broker', url, flush=True)
    name = 'ovn-%s' % args.tag
    t_submit = time.time()
    rt = oh.connect(url)
    psij = None
    if args.launch == 'psij':
        psij = rt.get_plugin('broker', 'psij')
        epdir = os.path.join(workdir, 'endpoint')
        os.makedirs(epdir)
        t_submit = time.time()
        res = psij.submit_tunneled({
            'executable': os.path.join(oh.VE, 'bin', 'radical-orbit-endpoint-wrapper.sh'),
            'arguments': ['-n', name, '-u', url, '-c', os.environ['RADICAL_ORBIT_BROKER_CERT'],
                          '-p', 'rhapsody'],
            'directory': epdir,
            'environment': {'RADICAL_ORBIT_SETUP': 'source %s' % oh.ENV},
            'attributes': {'duration': str(args.minutes * 60), 'account': args.account},
            'resources': {'node_count': 1},
            'custom_attributes': {'slurm.constraint': 'cpu', 'slurm.qos': 'debug'},
        }, executor='slurm', tunnel='none')
        job = res['job_id']
        timings['native_id'] = res.get('native_id')
        timings['submit_call'] = time.time() - t_submit
        print('endpoint submitted through ORBIT psij:', res, flush=True)
    else:
        job = oh.sbatch_endpoint(url, name, os.path.join(workdir, 'endpoint'),
                                 minutes=args.minutes, account=args.account)
        print('endpoint job', job, flush=True)
    rc = 1
    try:
        timings['registered_after_submit'] = oh.wait_endpoint(rt, name, timeout=1500)
        timings['job'] = job
        print('endpoint registered after %.1fs' % timings['registered_after_submit'], flush=True)
        procs = []
        for i in range(args.clients):
            prefix = chr(ord('A') + i) if args.clients > 1 else 'pD'
            cmd = [sys.executable, 'driver-orbit.py', '--broker-url', url,
                   '--endpoint', name, '--prefix', prefix] + [a for a in args.driver_args if a != '--']
            if args.targets:
                cmd += ['--target', args.targets.split(',')[i]]
            if args.clients > 1 and not args.no_uid_offset:
                cmd += ['--uid-offset', str(100000 * i)]
            if args.clients == 2:
                cmd += ['--foreign-prefix', 'B' if prefix == 'A' else 'A']
            log = open('client-%s.log' % prefix, 'w')
            procs.append((prefix, subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)))
        t_clients = time.time()
        rcs = []
        for prefix, proc in procs:
            try:
                rcs.append(proc.wait(timeout=max(1, args.client_timeout - (time.time() - t_clients))))
            except subprocess.TimeoutExpired:
                proc.kill()
                rcs.append(-9)
        timings['clients_wall'] = time.time() - t_clients
        timings['client_rcs'] = dict(zip([p for p, _ in procs], rcs))
        rc = 0 if all(r == 0 for r in rcs) else 1
    finally:
        t_cancel = time.time()
        if psij is not None:
            try:
                timings['cancel'] = psij.cancel_job(job)
            except Exception as e:
                timings['cancel'] = repr(e)
                if timings.get('native_id'):
                    oh.scancel(timings['native_id'])
        else:
            oh.scancel(job)
        try:
            timings['gone_after_cancel'] = oh.wait_endpoint_gone(rt, name)
        except Exception as e:
            timings['gone_after_cancel'] = repr(e)
        rt.stop()
        broker.stop()
        timings['total'] = time.time() - t_submit
        timings['t_cancel_rel'] = t_cancel - t_submit
        with open('timings.json', 'w') as fout:
            json.dump(timings, fout, indent=2)
        print('TIMINGS', json.dumps(timings), flush=True)
    print('RUN RESULT', 'PASS' if rc == 0 else 'FAIL', flush=True)
    sys.exit(rc)


if __name__ == '__main__':
    main()
