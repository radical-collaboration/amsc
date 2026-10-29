#!/bin/bash
#SBATCH -N 4 -C cpu -q debug -t 00:29:00 -A m5290 -J rhap-mix
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/mix.out
cd /pscratch/sd/m/merzky/radical/bench
source /pscratch/sd/m/merzky/radical/dragon-investigation/env.sh   # patched clone (AF_INET)
export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"')
RES=/pscratch/sd/m/merzky/radical/bench/results/mix
for wl in het d32; do
  out="$RES/$wl"
  [ -f "$out/dragon/summary.json" ] && [ -f "$out/flux/summary.json" ] && { echo "skip $wl"; continue; }
  mkdir -p "$out"; echo "=== mix $wl $(date +%H:%M:%S) ==="
  timeout 700 python run_mix.py --nper 2 --workload "$wl" --out "$out"
  pkill -u "$USER" -f 'shimhost' 2>/dev/null; pkill -u "$USER" -f 'rhapsody.backends.multiproc.host' 2>/dev/null
  rm -rf /dev/shm/*dragon* 2>/dev/null; sleep 3
done
echo "=== mix done ==="
