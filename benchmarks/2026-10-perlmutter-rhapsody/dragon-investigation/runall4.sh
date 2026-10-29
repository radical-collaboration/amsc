#!/bin/bash
# Stage 4 driver: runs ON A COMPUTE NODE (via srun). dragon is a direct child,
# host-child co-locates with the driver -> node-local AF_UNIX socket works.
set +e
cd /pscratch/sd/m/merzky/radical/dragon-investigation
source ./env.sh >/dev/null 2>&1
export RHAPSODY_MP_LOGLEVEL=INFO
if [ -z "${SLURM_CPUS_ON_NODE:-}" ]; then
  export SLURM_CPUS_ON_NODE=256
fi
echo "runall4 on host=$(hostname) JOB=$SLURM_JOB_ID nodelist=$SLURM_NODELIST"
echo "########## F3: rhapsody-dragon, surgical shimhost, 2 nodes, 100 tasks ##########"
timeout 360 python dtest.py --nodes 2 --ntasks 100 --patch default \
    --shim shimhost --part-id fCOLO --timeout 300 2>&1
echo "[F3 exit=$?]"
pkill -u "$USER" -f 'multiproc.host' 2>/dev/null
pkill -u "$USER" -f 'shimhost'      2>/dev/null
echo "=== runall4 DONE ==="
