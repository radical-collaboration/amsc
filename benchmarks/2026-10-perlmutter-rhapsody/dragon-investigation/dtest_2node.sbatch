#!/bin/bash
#SBATCH -N 2 -C cpu -q debug -t 00:20:00 -A m5290 -J dragon-inv
#SBATCH -o /pscratch/sd/m/merzky/radical/dragon-investigation/sbatch2.log
set +e
cd /pscratch/sd/m/merzky/radical/dragon-investigation
source ./env.sh >/dev/null 2>&1
export RHAPSODY_MP_LOGLEVEL=INFO
if [ -z "${SLURM_CPUS_ON_NODE:-}" ]; then
  export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
fi
echo "sbatch head host=$(hostname) JOB=$SLURM_JOB_ID nodelist=$SLURM_NODELIST CPUS_ON_NODE=$SLURM_CPUS_ON_NODE"
echo "########## F4: rhapsody-dragon, surgical shimhost, 2 nodes, 100 tasks (sbatch, direct child) ##########"
timeout 420 python dtest.py --nodes 2 --ntasks 100 --patch default \
    --shim shimhost --part-id fSB --timeout 360 2>&1
echo "[F4 exit=$?]"
pkill -u "$USER" -f 'multiproc.host' 2>/dev/null
pkill -u "$USER" -f 'shimhost'      2>/dev/null
echo "=== sbatch2 DONE ==="
