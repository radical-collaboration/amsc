"""Helpers for the HPPSS ORBIT demo on Perlmutter.

The client process hosts an embedded broker on the login node; endpoints run
as their own 1-node batch jobs and dial the broker over the shared network.

Environment:
  ORBIT_DEMO_VE   venv with radical.orbit, rhapsody, radex, the plugin
                  (default: $PSCRATCH/hppss-orbit/ve)
  ORBIT_DEMO_ENV  file sourced by the endpoint job (modules, OpenFOAM, TLS)
                  (default: $PSCRATCH/hppss-orbit/env.sh)
"""

import os
import random
import subprocess
import time

from radical.orbit import EndpointRuntime
from radical.orbit.embedded import EmbeddedBroker

_BASE = os.path.join(os.environ.get('PSCRATCH', '.'), 'hppss-orbit')
VE  = os.environ.get('ORBIT_DEMO_VE',  os.path.join(_BASE, 've'))      # endpoint venv
ENV = os.environ.get('ORBIT_DEMO_ENV', os.path.join(_BASE, 'env.sh'))  # endpoint setup


def start_broker(port=None, plugins='', attempts=5):
    '''Start an embedded broker on a random high port; returns (broker, url).

    An explicit port that is taken raises in EmbeddedBroker, and other
    brokers on the shared login node use random ports too: retry.'''
    for attempt in range(attempts):
        broker = EmbeddedBroker(cert=os.environ['RADICAL_ORBIT_BROKER_CERT'],
                                key=os.environ['RADICAL_ORBIT_BROKER_KEY'],
                                port=port or random.randint(20000, 40000),
                                plugins=plugins)
        try:
            return broker, broker.start(timeout=30)
        except OSError:
            if port or attempt == attempts - 1:
                raise


def endpoint_script(url, name, workdir, minutes, plugins, env):
    '''The batch script for one endpoint job (no #SBATCH lines: sbatch args).'''
    exports = ''.join('export %s=%s\n' % (k, v) for k, v in env.items())
    return '''#!/bin/bash
export RADICAL_ORBIT_SETUP="source %(env)s"
%(exports)scd %(workdir)s
exec timeout %(tmo)dm %(ve)s/bin/radical-orbit-endpoint-wrapper.sh \\
    -n %(name)s -u %(url)s -c $RADICAL_ORBIT_BROKER_CERT -p %(plugins)s
''' % {'ve': VE, 'env': ENV, 'exports': exports, 'workdir': workdir,
       'tmo': max(1, minutes - 1), 'name': name, 'url': url,
       'plugins': plugins}


def sbatch_endpoint(url, name, workdir, minutes=30, account='amsc007',
                    qos='debug', plugins='rhapsody', env=None):
    '''Submit one endpoint job; returns the Slurm job id.'''
    os.makedirs(workdir, exist_ok=True)
    path = os.path.join(workdir, 'endpoint.sh')
    with open(path, 'w') as fout:
        fout.write(endpoint_script(url, name, workdir, minutes, plugins,
                                   env or {}))
    os.chmod(path, 0o755)
    out = subprocess.check_output(
        ['sbatch', '--parsable', '-N', '1', '-C', 'cpu', '-q', qos,
         '-t', '%d' % minutes, '-A', account, '-J', 'ovn-%s' % name,
         '-o', os.path.join(workdir, 'endpoint-%j.out'), path], text=True)
    return out.strip().split(';')[0]


def scancel(jobid):
    subprocess.call(['scancel', str(jobid)])


def connect(url):
    '''A participant runtime for topology queries.'''
    rt = EndpointRuntime(broker_url=url)
    rt.start(wait=True)
    return rt


def wait_endpoint(rt, name, timeout=1800, poll=5):
    '''Block until `name` is in the broker topology; returns seconds waited.'''
    t0 = time.time()
    while time.time() - t0 < timeout:
        if name in rt.topology():
            return time.time() - t0
        time.sleep(poll)
    raise TimeoutError('endpoint %s not registered after %ds' % (name, timeout))


def wait_endpoint_gone(rt, name, timeout=120, poll=5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if name not in rt.topology():
            return time.time() - t0
        time.sleep(poll)
    raise TimeoutError('endpoint %s still registered after %ds' % (name, timeout))


def job_state(jobid):
    out = subprocess.run(['sacct', '-nXP', '-j', str(jobid), '-o', 'State'],
                         capture_output=True, text=True).stdout.strip()
    return out.split('\n')[0] if out else ''
