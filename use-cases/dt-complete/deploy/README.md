# Deploying the dt-complete demo as a service

Three tiers, one pinned stack: a broker host runs the ORBIT broker with
the `dt` plugin, an HPC host runs the rhapsody endpoint (dragon), and
the client machine drives the twin and the sensors.  Every host installs
via digital.twins' `deploy/install.sh`, which pins the same commit and
Python minor everywhere -- the wire rejects skew, and cloudpickle does
not survive it.

## One-time setup

    # broker host
    ./setup-broker.sh

    # HPC login node (fetches the broker's cert + token via scp)
    ./setup-hpc-endpoint.sh <broker-host>

    # client machine
    git clone https://github.com/radical-cybertools/digital.twins.git
    (cd digital_twins && ./deploy/install.sh client &&
     ./ve.demo/bin/pip install pandas scikit-learn pyarrow)
    scp <broker-host>:.radical/orbit/broker_cert.pem \
        <broker-host>:.radical/orbit/broker.token ~/.radical/orbit/

## Running (in this order)

    # 1. broker host
    cd ~/digital_twins && ./deploy/run-broker.sh $PWD/ve.demo

    # 2. HPC: get an allocation, then on the compute node
    salloc -N1 -C cpu -q interactive -t 2:00:00 -A <account>
    ./run-hpc-endpoint.sh <broker-host>        # watch for: registered as 'hpc'

    # 3. client: three terminals, each sourced
    source deploy/client-env.sh <broker-host>
    <ve.demo>/python m3dc1/m3dc1_mock_sensor.py        # terminal 1
    <ve.demo>/python negative_agent/rand_sensor.py     # terminal 2
    <ve.demo>/python run_me_service.py                 # terminal 3

Dashboard: `https://<broker-host>:8000/broker/dt/ui?live=1` (broker
token at the prompt).  The learning lane shows the ROSE window tasks;
the `val_r2` convergence bar fills as windows complete.

## Placement knobs (client env)

    DT_INFERENCE_ENDPOINT  (hpc)        DT_INFERENCE_BACKEND  (dragon_v3)
    DT_LEARNING_ENDPOINT   (=inference) DT_LEARNING_BACKEND   (concurrent)

A laptop-only run: point both endpoints at a local one and both
backends at `concurrent`.

## Hard-won constraints (do not relax casually)

- The endpoint MUST be launched via the `dragon` launcher (the run
  script does): rhapsody's dragon backend uses Dragon's Batch API,
  which only exists inside a Dragon-launched process tree.
- Python >= 3.12.1 on the endpoint: exactly 3.12.0 breaks dragon's
  transport import (CPython gh-112358).
- `SLURM_EXPORT_ENV=ALL`: dragon's inner sruns scrub their env
  otherwise and lose the venv PATH.
- joblib/sklearn `n_jobs != 1` breaks under Dragon's multiprocessing
  bridge (stdlib ThreadPool lands in DragonPool.__init__); the demo
  trains sequentially.
- The rhapsody install pins the `fix/dragon-cancel-idempotent` branch
  until its cancel-idempotency and traceback-logging fixes are merged
  upstream.
