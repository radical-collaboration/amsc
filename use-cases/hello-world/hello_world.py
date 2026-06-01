#!/usr/bin/env python3
"""hello-world: end-to-end smoke test for the AmSC edge infrastructure.

Spawns an edge on Perlmutter via NERSC IRI, runs ``hostname`` as an
executable task pinned to each of ``N_NODES`` nodes (one task per node)
through Rhapsody / Dragon, then tears the edge down.  There is no
application workload here — this only proves the chain

    laptop  ->  bridge  ->  IRI  ->  edge  ->  Rhapsody / Dragon

works, including per-node placement, before you wire in a real workload.

Executable ``stdout`` is captured to files on the **compute side** (it
does not cross the edge result channel), so this script reports where
each task was pinned and its final state, and tells you where to find
the captured output.  Staging that output back to the client is left
for later.

Run on the laptop, with the bridge already running on the bridge host:

    export RADICAL_BRIDGE_URL="https://<bridge-host>:8000"
    python hello_world.py
"""
import asyncio
import base64
import os

import cloudpickle
import rhapsody

from rhapsody.api        import ComputeTask, Session
from radical.edge.client import BridgeClient

# === adjust to your NERSC account / layout ==================================
ACCOUNT      = 'm5290'                  # Perlmutter allocation / project
LOGIN_HOST   = 'perlmutter.nersc.gov'   # login host for the forward SSH tunnel
HOME_DIR     = '/global/u2/m/merzky'    # your $HOME on Perlmutter
N_NODES      = 2
WALLTIME_MIN = 30
QUEUE        = 'debug'
AMSC_DIR     = os.environ.get('AMSC_DIR', os.path.expanduser('~/.amsc'))
# ============================================================================

EDGE_NAME = 'hello.0'


def main():
    token = open(f'{AMSC_DIR}/token_nersc').read().strip()

    bc  = BridgeClient()                          # URL + cert from env / files
    cx  = bc.get_edge_client('bridge').get_plugin('iri_connect')
    iri = cx.connect(endpoint='nersc', token=token)

    wrapper  = f'{HOME_DIR}/.amsc/ve/bin/radical-edge-wrapper.sh'
    job_spec = {
        'executable' : wrapper,
        'arguments'  : ['--name', EDGE_NAME, '--url', bc.url,
                        '--tunnel', 'forward', '--tunnel-via', LOGIN_HOST],
        'name'       : EDGE_NAME,
        'resources'  : {'node_count': N_NODES},
        'attributes' : {'queue_name': QUEUE,
                        'duration'  : WALLTIME_MIN * 60,
                        'account'   : ACCOUNT},
        'environment': {'RADICAL_BRIDGE_URL': bc.url,
                        'RADICAL_EDGE_SETUP': 'module load openmpi'},
    }

    print(f'submitting IRI job (nersc -> perlmutter, edge {EDGE_NAME}) ...')
    job = iri.submit_job('perlmutter', job_spec)
    print(f'  job_id: {job["job_id"]}')

    try:
        print('waiting for the edge (queue + boot)', end='', flush=True)
        bc.wait_for_edge([EDGE_NAME],
                         on_heartbeat=lambda: print('.', end='', flush=True))
        print(f'\nedge {EDGE_NAME} is up')

        nodelist = bc.get_edge_client(EDGE_NAME) \
                     .get_plugin('queue_info').nodelist()
        print(f'allocation ({len(nodelist)} nodes): {nodelist}')

        asyncio.run(_run(bc.url, EDGE_NAME, nodelist))

    finally:
        print('tearing down ...')
        try:    iri.cancel_job('perlmutter', job['job_id'])
        except Exception as e: print(f'  cancel failed: {e}')
        try:    cx.disconnect('nersc')
        except Exception as e: print(f'  disconnect failed: {e}')
        bc.close()


async def _run(bridge_url, edge_name, nodelist):
    # Dragon Policy is constructed here, on the client, and cloudpickled to
    # the edge — so this import requires dragon to be importable locally.
    from dragon.infrastructure.policy import Policy

    def _pin(host):
        # Dragon Policy is a C-extension object that msgpack cannot
        # serialise; ride rhapsody's ``_pickled_fields`` escape hatch and
        # cloudpickle the whole kwargs dict.  The edge decodes it back into
        # a real Policy before handing the task to Dragon.
        raw = {'process_template': {'policy': Policy(
                   placement=Policy.Placement.HOST_NAME, host_name=host)}}
        return 'cloudpickle::' + base64.b64encode(cloudpickle.dumps(raw)).decode()

    # One task per node, each pinned to its host.
    tasks = [ComputeTask(
                 uid          = f'hello.{i:02d}',
                 executable   = '/bin/bash',
                 arguments    = ['-c', 'hostname'],
                 capture_stdio= True,           # -> <uid>.stdout on compute side
                 task_backend_specific_kwargs = _pin(host),
                 _pickled_fields = ['task_backend_specific_kwargs'])
             for i, host in enumerate(nodelist)]

    backend = await rhapsody.get_backend('edge', bridge_url=bridge_url,
                                         edge_name=edge_name)
    async with Session(backends=[backend]) as session:
        print(f'submitting {len(tasks)} hostname task(s), one per node ...')
        await session.submit_tasks(tasks)
        await asyncio.gather(*tasks)

    print('\nresults:')
    for t, host in zip(tasks, nodelist):
        print(f'  {t.uid}   pinned -> {host:>12s}   state={t.state}')

    print('\nexecutable stdout/stderr are captured on the COMPUTE side, under')
    print('the edge\'s rhapsody session directory:')
    print('    <edge cwd>/<session-id>/<uid>.stdout')
    print('find <session-id> in the edge log on Perlmutter:')
    print(f'    grep "Registered session" ~/.radical/edge/logs/{edge_name}.log')


if __name__ == '__main__':
    main()
