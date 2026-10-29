#!/bin/bash
# Stage 2: prove the sitecustomize shim fixes rhapsody-dragon end-to-end.
set +e
cd /pscratch/sd/m/merzky/radical/dragon-investigation
source ./env.sh >/dev/null 2>&1
export RHAPSODY_MP_LOGLEVEL=INFO
SHIM=/pscratch/sd/m/merzky/radical/dragon-investigation/shim

# rhapsody_rm needs SLURM_CPUS_ON_NODE (not set in the salloc submission env)
if [ -z "${SLURM_CPUS_ON_NODE:-}" ]; then
  export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
fi
echo "=================================================================="
echo "JOB $SLURM_JOB_ID nodes=$SLURM_NNODES nodelist=$SLURM_NODELIST CPUS_ON_NODE=$SLURM_CPUS_ON_NODE"
echo "=================================================================="

echo; echo "########## S0: micro-probe under dragon WITH shim (expect Client REAL) ##########"
PYTHONPATH="$SHIM:$PYTHONPATH" timeout 180 dragon python probe.py with-shim 2>&1
echo "[S0 exit=$?]"

echo; echo "########## C1: dtest patch=default, NO shim (expect failure: NoneType) ##########"
timeout 200 python dtest.py --nodes 2 --ntasks 10 --patch default --part-id cNOSHIM --timeout 90 2>&1
echo "[C1 exit=$?]"
pkill -u "$USER" -f 'multiproc.host' 2>/dev/null; sleep 3

echo; echo "########## F1: dtest patch=default, WITH shim, 100 tasks (expect DONE=100) ##########"
PYTHONPATH="$SHIM:$PYTHONPATH" timeout 300 python dtest.py --nodes 2 --ntasks 100 --patch default --part-id fSHIM --timeout 240 2>&1
echo "[F1 exit=$?]"
pkill -u "$USER" -f 'multiproc.host' 2>/dev/null; sleep 2
echo; echo "=== runall2 DONE ==="
