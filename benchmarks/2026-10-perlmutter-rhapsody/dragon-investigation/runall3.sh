#!/bin/bash
# Stage 3: surgical shimhost launch_prefix override, 2-node end-to-end.
set +e
cd /pscratch/sd/m/merzky/radical/dragon-investigation
source ./env.sh >/dev/null 2>&1
export RHAPSODY_MP_LOGLEVEL=INFO
if [ -z "${SLURM_CPUS_ON_NODE:-}" ]; then
  export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
fi
echo "JOB $SLURM_JOB_ID nodes=$SLURM_NNODES nodelist=$SLURM_NODELIST CPUS_ON_NODE=$SLURM_CPUS_ON_NODE"

echo; echo "########## F2: rhapsody-dragon, surgical shimhost, 2 nodes, 100 tasks ##########"
timeout 360 python dtest.py --nodes 2 --ntasks 100 --patch default \
    --shim shimhost --part-id fSURG --timeout 300 2>&1
echo "[F2 exit=$?]"
pkill -u "$USER" -f 'multiproc.host' 2>/dev/null
pkill -u "$USER" -f 'shimhost'      2>/dev/null; sleep 3
echo; echo "=== runall3 DONE ==="
