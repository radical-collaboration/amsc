#!/bin/bash
#SBATCH -N 4 -C cpu -q debug -t 00:30:00 -A m5290 -J dragon-inv
#SBATCH -o /pscratch/sd/m/merzky/radical/dragon-investigation/run_0142.log
set +e
cd /pscratch/sd/m/merzky/radical/dragon-investigation
source ./env_0142.sh >/dev/null 2>&1
export RHAPSODY_MP_LOGLEVEL=INFO
if [ -z "${SLURM_CPUS_ON_NODE:-}" ]; then
  export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
fi
echo "=== dragon 0.14.2 test | head=$(hostname) JOB=$SLURM_JOB_ID nodelist=$SLURM_NODELIST ==="
python -c "from dragon.version import __version__ as v; print('dragon version:', v)"

echo; echo "########## P: probe under dragon (DRAGON_PATCH_MP forced? Client patched? _original_Client?) ##########"
timeout 180 dragon python probe.py v0142-under-dragon 2>&1; echo "[P exit=$?]"
pkill -u "$USER" -x dragon 2>/dev/null; sleep 3

echo; echo "########## T1: in-process rhapsody-dragon, dragon --hostlist 2 nodes, 100 tasks ##########"
DH=$(scontrol show hostnames "$SLURM_NODELIST" | head -2 | paste -sd,)
echo "T1 hostlist=$DH"
timeout 300 dragon -N 2 --wlm slurm --hostlist "$DH" python rh_dragon.py --nodes 2 --ntasks 100 2>&1
echo "[T1 exit=$?]"
pkill -u "$USER" -f 'rh_dragon' 2>/dev/null; pkill -u "$USER" -x dragon 2>/dev/null; sleep 4

echo; echo "########## T2a: proxy 1-node partition (co-located), --shim NONE -> isolates mp-patch ##########"
timeout 200 python dtest.py --nodes 1 --ntasks 10 --patch default --shim none --part-id v2aNONE --timeout 120 2>&1
echo "[T2a exit=$?]"
pkill -u "$USER" -f 'multiproc.host' 2>/dev/null; pkill -u "$USER" -x dragon 2>/dev/null; sleep 4

echo; echo "########## T2b: proxy 1-node partition (co-located), --shim shimhost -> confirm shim works on 0.14.2 ##########"
timeout 240 python dtest.py --nodes 1 --ntasks 50 --patch default --shim shimhost --part-id v2bSHIM --timeout 180 2>&1
echo "[T2b exit=$?]"
pkill -u "$USER" -f 'multiproc.host\|shimhost' 2>/dev/null; pkill -u "$USER" -x dragon 2>/dev/null; sleep 4

echo; echo "########## T3: proxy 2-node partition, --shim shimhost, x3 -> co-location reliability ##########"
for r in 1 2 3; do
  echo "--- T3 run $r ---"
  timeout 220 python dtest.py --nodes 2 --ntasks 50 --patch default --shim shimhost --part-id v3r$r --timeout 150 2>&1 \
    | grep -E 'driver host|shimhost\] running|RESULT|FileNotFoundError|TypeError|proxy READY'
  echo "[T3 run $r exit=$?]"
  pkill -u "$USER" -f 'multiproc.host\|shimhost' 2>/dev/null; pkill -u "$USER" -x dragon 2>/dev/null; sleep 4
done
echo; echo "=== run_0142 DONE ==="
