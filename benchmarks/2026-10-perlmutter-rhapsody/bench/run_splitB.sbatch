#!/bin/bash
#SBATCH -N 8 -C cpu -q regular -t 01:00:00 -A m5290 -J rhap-splitB
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/splitB.out
cd /pscratch/sd/m/merzky/radical/bench
source ./env.sh
if [ -z "${SLURM_CPUS_ON_NODE:-}" ]; then
  export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
fi
RESULTS=/pscratch/sd/m/merzky/radical/bench/results/partB
for wl in zero d32 het; do
  out=$RESULTS/split-$wl
  [ -f "$out/native-flux/summary.json" ] && [ -f "$out/native-dragon/summary.json" ] && { echo "skip $wl"; continue; }
  mkdir -p "$out"; echo "=== split $wl $(date +%H:%M:%S) ==="
  timeout 1500 python run_split.py --workload "$wl" --out "$out"
  pkill -u "$USER" -f 'native_dragon' 2>/dev/null; rm -rf /dev/shm/*dragon* 2>/dev/null; sleep 3
done
echo "=== partB done ==="
