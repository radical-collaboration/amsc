#!/bin/bash
#SBATCH -N 4 -C cpu -q debug -t 00:28:00 -A m5290 -J dragon-inv
#SBATCH -o /pscratch/sd/m/merzky/radical/dragon-investigation/split_run.log
set +e
cd /pscratch/sd/m/merzky/radical/dragon-investigation
source ./env.sh >/dev/null 2>&1
export RHAPSODY_MP_LOGLEVEL=INFO
if [ -z "${SLURM_CPUS_ON_NODE:-}" ]; then
  export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
fi
echo "head=$(hostname) JOB=$SLURM_JOB_ID nodelist=$SLURM_NODELIST"

echo; echo "########## A: RELIABLE in-process rhapsody-dragon (2n) || flux (2n) ##########"
timeout 500 python rh_split.py --ntasks 100 2>&1
echo "[A exit=$?]"
pkill -u "$USER" -f 'rh_dragon' 2>/dev/null; pkill -u "$USER" -x dragon 2>/dev/null
pkill -u "$USER" -f '_rhsplit_fluxw' 2>/dev/null; sleep 5

echo; echo "########## B: OPPORTUNISTIC RemoteBackendProxy split (short timeout; co-location coin-flip) ##########"
timeout 160 python dtest_split.py --ntasks 100 2>&1
echo "[B exit=$?]"
pkill -u "$USER" -f 'multiproc.host' 2>/dev/null; pkill -u "$USER" -f 'shimhost' 2>/dev/null
pkill -u "$USER" -x dragon 2>/dev/null; pkill -u "$USER" -f '_fluxw_' 2>/dev/null
echo; echo "=== split_run DONE ==="
