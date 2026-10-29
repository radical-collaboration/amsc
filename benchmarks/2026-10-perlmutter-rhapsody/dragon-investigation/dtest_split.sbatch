#!/bin/bash
#SBATCH -N 4 -C cpu -q debug -t 00:25:00 -A m5290 -J dragon-inv
#SBATCH -o /pscratch/sd/m/merzky/radical/dragon-investigation/sbatch_split.log
set +e
cd /pscratch/sd/m/merzky/radical/dragon-investigation
source ./env.sh >/dev/null 2>&1
export RHAPSODY_MP_LOGLEVEL=INFO
if [ -z "${SLURM_CPUS_ON_NODE:-}" ]; then
  export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
fi
echo "sbatch head=$(hostname) JOB=$SLURM_JOB_ID nodelist=$SLURM_NODELIST CPUS_ON_NODE=$SLURM_CPUS_ON_NODE"
echo "########## SPLIT: rhapsody-dragon (2n) || flux (2n), 100 tasks each ##########"
timeout 600 python dtest_split.py --ntasks 100 2>&1
echo "[SPLIT exit=$?]"
pkill -u "$USER" -f 'multiproc.host' 2>/dev/null
pkill -u "$USER" -f 'shimhost'      2>/dev/null
pkill -u "$USER" -f '_fluxw_'       2>/dev/null
echo "=== sbatch_split DONE ==="
