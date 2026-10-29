#!/bin/bash
#SBATCH -N 1 -C cpu -q debug -t 00:15:00 -A m5290 -J dragon-inv
#SBATCH -o /pscratch/sd/m/merzky/radical/dragon-investigation/t2b_dbg.log
set +e
cd /pscratch/sd/m/merzky/radical/dragon-investigation
source ./env_0142.sh >/dev/null 2>&1
export RHAPSODY_MP_LOGLEVEL=DEBUG
if [ -z "${SLURM_CPUS_ON_NODE:-}" ]; then
  export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
fi
echo "=== 0.14.2 proxy+shim 1-node co-located, DEBUG | head=$(hostname) ==="
python -c "from dragon.version import __version__ as v; print('dragon', v)"
timeout -k 15 180 python dtest.py --nodes 1 --ntasks 20 --patch default --shim shimhost --part-id dbg --timeout 120 2>&1 | tail -60
echo "[exit=$?]"
pkill -u "$USER" -f 'multiproc.host' 2>/dev/null; pkill -u "$USER" -f 'shimhost' 2>/dev/null; pkill -u "$USER" -x dragon 2>/dev/null
echo "=== t2b_dbg DONE ==="
