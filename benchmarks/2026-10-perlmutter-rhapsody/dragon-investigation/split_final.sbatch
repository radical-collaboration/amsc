#!/bin/bash
#SBATCH -N 4 -C cpu -q debug -t 00:20:00 -A m5290 -J dragon-inv
#SBATCH -o /pscratch/sd/m/merzky/radical/dragon-investigation/split_final.log
set +e
cd /pscratch/sd/m/merzky/radical/dragon-investigation
source ./env.sh >/dev/null 2>&1
export RHAPSODY_MP_LOGLEVEL=WARNING
if [ -z "${SLURM_CPUS_ON_NODE:-}" ]; then
  export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
fi
echo "head=$(hostname) JOB=$SLURM_JOB_ID nodelist=$SLURM_NODELIST flux=$(command -v flux)"
echo "########## 2+2: rhapsody-dragon (2n, in-process) || flux (2n), 100 tasks each ##########"
timeout 500 python rh_split.py --ntasks 100 2>&1
echo "[split exit=$?]"
pkill -u "$USER" -f 'rh_dragon' 2>/dev/null; pkill -u "$USER" -x dragon 2>/dev/null
pkill -u "$USER" -f '_rhsplit_fluxw' 2>/dev/null
echo "=== split_final DONE ==="
