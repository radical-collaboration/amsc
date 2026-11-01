# HOWTO: run the HPPSS SC26 demo on Perlmutter

This guide reproduces both parts of the HPPSS demo (plan:
[2026-11-15-hppss-sc26.md](2026-11-15-hppss-sc26.md)) on Perlmutter, from a
fresh shell, using the shared deployment. You build nothing.

- **Part 1:** the OpenFOAM `pitzDaily` inlet optimization runs locally under
  Dragon on one CPU node. RHAPSODY drives the solvers, and each case writes its
  result into a radex store.
- **Part 2:** the same optimization is driven from a client on a login node.
  The solvers and the radex store run in an ORBIT endpoint on a compute node,
  which the client starts and stops through ORBIT. Two independent clients
  share one endpoint and must not see each other's data.

Background, the build, and the measurements are in the
[Perlmutter runbook](2026-11-15-hppss-sc26-perlmutter-runbook.md). This file
covers only how to run the demo.

## 0. Prerequisites

- **NERSC account and allocation:** a NERSC account in the `amsc007` Unix
  group. The shared deployment is readable by that group only. To charge
  another project, use your own allocation with `-A`/`--account` below.
- **Shell:** a login shell on Perlmutter (`ssh perlmutter.nersc.gov`).
- **Run on scratch:** Dragon, OpenFOAM and the endpoint job write a lot of
  small files, so work under `$PSCRATCH`, not `$HOME`.

## 1. The shared deployment (read-only)

| What | Where | Version |
|---|---|---|
| Environment file | `/pscratch/sd/m/merzky/hppss-demo/env.sh` | sources everything below |
| Python venv | `/pscratch/sd/m/merzky/hppss-demo/ve` | cray-python 3.12.12, dragonhpc 0.15.0 |
| RHAPSODY | branch `demo/hppss` of `radical-cybertools/rhapsody` | Dragon 0.15.0 pin + `OrbitDataBackend` + sid filter |
| radical.orbit | branch `demo/hppss` of `radical-cybertools/radical.orbit` | devel with the session-scoped notification fix |
| radical.prof | `radical-cybertools/radical.profile` `2bf1eb1` | |
| radex (C++ library and Python client) | `/pscratch/sd/m/merzky/hppss-d015/radex/install`, commit `c4b4d1f` | Dragon backend |
| `radexWrite` function objects | `/pscratch/sd/m/merzky/hppss-d015/of-user` | `CrayLabs/rhapsody-plugins-openfoam` `306d3f4` |
| OpenFOAM | `/pscratch/sd/m/merzky/hppss/openfoam/OpenFOAM-v2412` | ESI v2412 |
| Example cases and drivers | `/pscratch/sd/m/merzky/hppss-d015/runs/{openfoam-cases,pitzDaily-optimize}` | from the plugin repo |

Quick check that you can read it:

```sh
source /pscratch/sd/m/merzky/hppss-demo/env.sh
python -c "import radical.orbit, rhapsody, radex, rhapsody_plugins.openfoam; print('ok')"
ls $FOAM_USER_LIBBIN            # libradexBase/IO/Read/Write.so
which simpleFoam
```

## 2. Your working directory

Everything you run writes here: run directories, logs, Dragon and RHAPSODY
output.

```sh
export W=$PSCRATCH/hppss-demo-run           # any directory on scratch
mkdir -p $W && cd $W
git clone -b feature/hppss-demo https://github.com/radical-collaboration/amsc.git
```

### 2.1 A TLS pair and a token for the demo broker

In part 2 the client hosts the ORBIT broker itself (an embedded broker on the
login node). The broker needs a TLS pair, and endpoints authenticate with a
token. Create both for the demo only.

Don't reuse `~/.radical/orbit/`, which another ORBIT deployment may rely on.

```sh
mkdir -p $W/tls && chmod 700 $W/tls
openssl req -x509 -newkey rsa:4096 -nodes -days 30 -subj "/CN=hppss-demo" \
    -keyout $W/tls/broker_key.pem -out $W/tls/broker_cert.pem
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > $W/tls/broker.token
chmod 600 $W/tls/*
```

### 2.2 Your environment file

The endpoint job sources this file too, so it must use absolute paths.

```sh
cat > $W/my-env.sh <<EOF
# HPPSS demo: shared deployment + my own TLS pair and token
source /pscratch/sd/m/merzky/hppss-demo/env.sh
export HPPSS_WORK=$W
export ORBIT_DEMO_VE=/pscratch/sd/m/merzky/hppss-demo/ve
export ORBIT_DEMO_ENV=\$HPPSS_WORK/my-env.sh
export RADICAL_ORBIT_BROKER_CERT=\$HPPSS_WORK/tls/broker_cert.pem
export RADICAL_ORBIT_BROKER_KEY=\$HPPSS_WORK/tls/broker_key.pem
export RADICAL_ORBIT_BROKER_TOKEN=\$(cat \$HPPSS_WORK/tls/broker.token)
EOF
source $W/my-env.sh
```

## 3. Part 1: local run under Dragon (one CPU node)

```sh
cp -r /pscratch/sd/m/merzky/hppss-d015/runs/pitzDaily-optimize $W/part1
cat > $W/part1.sh <<'EOF'
#!/bin/bash
#SBATCH -N 1 -C cpu -q debug -t 00:20:00 -J hppss-part1
source $HPPSS_WORK/my-env.sh
cd $HPPSS_WORK/part1
echo "=== start $(date +%T) on $(hostname)"
/usr/bin/time -v dragon driver-video.py > video.log 2>&1
echo "=== rc=$? end $(date +%T)"
grep -E '^Iteration|WARNING|Traceback|Error' video.log | head -20
grep -E 'Elapsed \(wall' video.log
EOF
chmod +x $W/part1.sh
sbatch -A amsc007 -o $W/part1-%j.log --export=ALL,HPPSS_WORK=$W $W/part1.sh
```

`driver-video.py` is the demo size: 4 cases per batch, 4 batches.

What to expect in `$W/part1-<jobid>.log`:
- four `Iteration` lines, the best loss falling to about `1e-04`;
- an elapsed (wall) time of about 1:45 to 2:00.

Rehearsal on 2026-11-01 (Slurm 60647272, `nid005250`), from a fresh working
directory with exactly the steps above:

```
Iteration 1: ... avg_inlets=-2.36168, loss=0.21315
Iteration 2: ... avg_inlets=-2.03996, loss=0.0195879
Iteration 3: ... avg_inlets=-2.03996, loss=0.0195879
Iteration 4: ... avg_inlets=-1.8892, loss=0.000116553
Elapsed (wall clock) time: 1:52
```

The losses are identical to the runbook's video-size runs, and all 16 solver
logs report the radex connection.

- **Driver output:** `$W/part1/video.log`.
- **Solver output:** `$W/part1/rhapsody.session.*/task.*.{stdout,stderr}`.
  Each solver log contains
  `radexIO: connected to the radex store via dragon`.
- **Interactive alternative:** `salloc -N 1 -C cpu -q interactive -t 30
  -A amsc007`, then `source $W/my-env.sh; cd $W/part1; dragon driver-video.py`.

## 4. Part 2: through ORBIT (client on the login node)

Run this on the login node, in a terminal that stays open:

```sh
source $W/my-env.sh
mkdir -p $W/part2 && cd $W/part2
python $W/amsc/demos/hppss-sc26-orbit/run_orbit.py --tag part2 --launch psij \
    --account amsc007 \
    --pitzdaily-dir /pscratch/sd/m/merzky/hppss-d015/runs/pitzDaily-optimize \
    --clients 2 --no-uid-offset --targets=-1.9,-2.0 --minutes 20 \
    -- --ensemble-size 4 --max-iterations 4 --plot
```

What happens, in order:
1. **Broker:** the client starts an embedded ORBIT broker on a random port of
   the login node. The broker hosts the `psij` plugin.
2. **Endpoint:** the client starts the endpoint through ORBIT:
   `psij.submit_tunneled(tunnel='none')` submits a 1-node CPU job on the debug
   QOS. In it, `radical-orbit-endpoint-wrapper.sh` starts Dragon and the
   `rhapsody` plugin. The job sources `$ORBIT_DEMO_ENV`, which is your
   `my-env.sh`.
3. **Clients:** once the endpoint has registered, two clients start. They have
   different targets, `avgInlets` −1.9 and −2.0. Each client:
   - has its own radex store on the endpoint;
   - runs 4 batches of 4 cases;
   - prints one progress line per batch.
4. **Isolation check:** each client checks that the other client's results are
   not in its own store.
5. **Teardown:** the endpoint job is cancelled through ORBIT, and the broker
   stops.

What to expect in the terminal (also in `run_orbit`'s log):

```
endpoint registered after <queue wait + ~25> s
[  72.8s] client A | iteration  1 | cases   4 (4/4 with results) | batch  64.4s | best loss 0.213
...
ISOLATION client A: B-0000 in own store: no (isolated): KeyNotFoundError(...)
RESULT client A: 4 iterations, 16 cases, ... avg_inlets=-1.8892, loss=0.000116553, wall 134.3s
RUN RESULT PASS
```

The progress lines and the `ISOLATION`/`RESULT` lines are in the client logs.
The terminal shows the endpoint start, a `TIMINGS` summary and `RUN RESULT`.

Rehearsal on 2026-11-01, from the same fresh working directory: the endpoint
was Slurm 60647290, and the whole run took 5:03.

| Step | Time |
|---|---|
| Endpoint submit → registered | 115 s: 91 s in the debug queue (part 1 was running at the same time), then 24 s from job start |
| Clients A and B, in parallel | 134 s each. The first batch takes about 64 s (Dragon warm-up); later batches take 17–21 s |
| Cancel through ORBIT → endpoint gone | 45 s |

| Client | Target `avgInlets` | Best loss per batch | Result |
|---|---|---|---|
| A | −1.9 | 0.213, 0.0196, 0.0196, 1.17e-04 | `avg_inlets` −1.8892, the same as part 1 |
| B | −2.0 | 0.131, 0.0016, 0.0016, 5.88e-06 | `avg_inlets` −2.0024 |

Both clients report `isolated`: neither finds the other's keys in its radex
store.

- **Where things land:**
  - run directory: `$W/part2/part2-<time>/`;
  - client logs: `client-A.log`, `client-B.log`;
  - loss plots: `loss-A.png`, `loss-B.png` (written with `--plot`);
  - the endpoint's Dragon and RHAPSODY output: `endpoint/`.
- **One client only:** use `--clients 1` and drop `--targets`.
- **Endpoint without psij:** `--launch sbatch` submits the same endpoint job
  directly with `sbatch` instead of through ORBIT.

## 5. Timing for the recording

- **Queue wait:** the debug QOS adds 15–70 s before the endpoint job starts,
  and Dragon then needs about 30 s until the endpoint registers.
- **For the recording:** start part 2 a minute ahead, or use a reservation.
  The optimization itself takes about 2 minutes per client.
- **Part 1** fits about 2 minutes including Dragon start-up.

## 6. Troubleshooting

- **`Permission denied` on `/pscratch/sd/m/merzky/...`:** your account is not
  in `amsc007` (check with `id -Gn`). Ask Andre for access.
- **All cases print `WARNING: <id> failed`:** read one task's `stdout`/`stderr`
  under `rhapsody.session.*`. The usual cause is an environment that was not
  sourced: `$FOAM_USER_LIBBIN` must contain `libradexWrite.so`.
- **Dragon hangs instead of exiting:**
  - start drivers with `dragon driver-*.py`, not `python`;
  - `my-env.sh` must be sourced, because it puts the venv `bin/` on `PATH` and
    sets `SLURM_EXPORT_ENV=ALL`.
- **Endpoint never registers:** check the endpoint job's output under
  `$W/part2/part2-*/endpoint/`. Compute nodes reach the login node's broker
  port directly; if that fails, the token or cert paths in `my-env.sh` are
  probably wrong.
- **Not a problem:**
  - `Address already in use` when the broker starts: the harness retries with
    another random port.
  - `pytest`/`__pycache__` write errors in the shared venv: it is read-only
    for you.

## 7. Not covered yet

- **The real broker host, three.radical:** that is where the recorded demo's
  broker will run. This guide uses the embedded broker on the login node,
  which stands in for it. To be added once that setup is tested.
- **A laptop client:** the client runs on a Perlmutter login node here.

## Appendix: how the shared deployment was built

The OpenFOAM, radex and `radexWrite` builds follow sections 3.2–3.4 of the
[runbook](2026-11-15-hppss-sc26-perlmutter-runbook.md). The venv and
`env.sh` in `/pscratch/sd/m/merzky/hppss-demo` were built with:

```sh
D=/pscratch/sd/m/merzky/hppss-demo; mkdir -p $D/src && cd $D
module unload python conda; module load cray-python/3.12.12
python3 -m venv $D/ve && source $D/ve/bin/activate
pip install -U pip
pip install dragonhpc==0.15.0 cython numpy scikit-optimize matplotlib
cd $D/src
git clone -b demo/hppss https://github.com/radical-cybertools/rhapsody.git
git clone -b demo/hppss https://github.com/radical-cybertools/radical.orbit.git
git clone https://github.com/radical-cybertools/radical.profile.git && git -C radical.profile checkout 2bf1eb1
(cd rhapsody && pip install '.[dragon,orbit]')
(cd radical.orbit && pip install .)
(cd radical.profile && pip install .)
export DRAGON_INCLUDE_DIR=$(dragon-config -o | sed 's/^-I *//')
export DRAGON_LIB_DIR=$(dragon-config -l | sed 's/^-L *//; s/ .*//')
export RADEX_INSTALL_DIR=/pscratch/sd/m/merzky/hppss-d015/radex/install RADEX_DIR=$RADEX_INSTALL_DIR
pip install /pscratch/sd/m/merzky/hppss-d015/radex/src/python
pip install /pscratch/sd/m/merzky/hppss-d015/rhapsody-plugins-openfoam
```

Never use `pip install -e`.

The `amsc007` group gets read access through ACLs:

```sh
setfacl -m g:amsc007:--x <each parent directory on the paths above>     # traverse only
setfacl -R -m g:amsc007:rX <the trees in section 1>
```

`$PSCRATCH` is purged after about 8 weeks without access. If the demo needs
to live longer, move the deployment to a CFS project directory.
