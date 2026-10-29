#!/bin/bash
#SBATCH -N 2 -C cpu -q debug -t 00:20:00 -A m5290 -J dragon-inv
#SBATCH -o /pscratch/sd/m/merzky/radical/dragon-investigation/t2b_0142.log
set +e
cd /pscratch/sd/m/merzky/radical/dragon-investigation
source ./env_0142.sh >/dev/null 2>&1
export RHAPSODY_MP_LOGLEVEL=WARNING
if [ -z "${SLURM_CPUS_ON_NODE:-}" ]; then
  export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
fi
echo "=== 0.14.2 proxy+shim (head-node driver) | head=$(hostname) nodelist=$SLURM_NODELIST ==="
python -c "from dragon.version import __version__ as v; print('dragon', v)"
for r in 1 2 3; do
  echo "--- run $r: dtest --nodes 2 --shim shimhost --ntasks 100 ---"
  timeout 300 python dtest.py --nodes 2 --ntasks 100 --patch default --shim shimhost --part-id v2b$r --timeout 240 2>&1 \
    | grep -E 'driver host|shimhost\] running|Client restored|RESULT|proxy READY|FileNotFoundError|TypeError'
  echo "[run $r exit=$?]"
  pkill -u "$USER" -f 'multiproc.host' 2>/dev/null; pkill -u "$USER" -f 'shimhost' 2>/dev/null; pkill -u "$USER" -x dragon 2>/dev/null
  sleep 5
done
echo "=== t2b_0142 DONE ==="
