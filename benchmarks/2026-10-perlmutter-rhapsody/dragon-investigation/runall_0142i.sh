#!/bin/bash
# Interactive 0.14.2 runner. Runs under: salloc -N4 ... bash runall_0142i.sh
# (bash executes on login; P & T1 use `dragon` directly; proxy tests place the
#  driver on a compute node via srun so the host child can co-locate).
set +e
DI=/pscratch/sd/m/merzky/radical/dragon-investigation
cd "$DI"
source ./env_0142.sh >/dev/null 2>&1
export RHAPSODY_MP_LOGLEVEL=INFO
if [ -z "${SLURM_CPUS_ON_NODE:-}" ]; then
  export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
fi
N0=$(scontrol show hostnames "$SLURM_NODELIST" | head -1)
DH2=$(scontrol show hostnames "$SLURM_NODELIST" | head -2 | paste -sd,)
echo "=== dragon 0.14.2 | JOB=$SLURM_JOB_ID nodelist=$SLURM_NODELIST N0=$N0 CPUS_ON_NODE=$SLURM_CPUS_ON_NODE ==="
python -c "from dragon.version import __version__ as v; print('dragon version:', v)"

echo; echo "########## P: probe under dragon (mp-patch state) ##########"
timeout 180 dragon python probe.py v0142 2>&1; echo "[P exit=$?]"
pkill -u "$USER" -x dragon 2>/dev/null; sleep 3

echo; echo "########## T1: in-process rhapsody-dragon, 2 nodes, 100 tasks ##########"
timeout 300 dragon -N 2 --wlm slurm --hostlist "$DH2" python rh_dragon.py --nodes 2 --ntasks 100 2>&1
echo "[T1 exit=$?]"
pkill -u "$USER" -f 'rh_dragon' 2>/dev/null; pkill -u "$USER" -x dragon 2>/dev/null; sleep 4

echo; echo "########## T2a: proxy 1-node co-located (driver on $N0), --shim NONE ##########"
srun -N1 --ntasks=1 --nodelist="$N0" --overlap bash -c \
  "cd $DI; source ./env_0142.sh >/dev/null 2>&1; export SLURM_CPUS_ON_NODE=$SLURM_CPUS_ON_NODE; \
   timeout 180 python dtest.py --nodes 1 --ntasks 10 --patch default --shim none --part-id v2aNONE --timeout 120" 2>&1
echo "[T2a exit=$?]"
pkill -u "$USER" -f 'multiproc.host' 2>/dev/null; pkill -u "$USER" -x dragon 2>/dev/null; sleep 4

echo; echo "########## T2b: proxy 1-node co-located (driver on $N0), --shim shimhost ##########"
srun -N1 --ntasks=1 --nodelist="$N0" --overlap bash -c \
  "cd $DI; source ./env_0142.sh >/dev/null 2>&1; export SLURM_CPUS_ON_NODE=$SLURM_CPUS_ON_NODE; \
   timeout 220 python dtest.py --nodes 1 --ntasks 50 --patch default --shim shimhost --part-id v2bSHIM --timeout 180" 2>&1
echo "[T2b exit=$?]"
pkill -u "$USER" -f 'multiproc.host' 2>/dev/null; pkill -u "$USER" -f 'shimhost' 2>/dev/null; pkill -u "$USER" -x dragon 2>/dev/null; sleep 4

echo; echo "=== runall_0142i DONE ==="
