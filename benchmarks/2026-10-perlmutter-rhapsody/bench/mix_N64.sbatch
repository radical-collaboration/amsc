#!/bin/bash
#SBATCH -N 128 -C cpu -q regular -t 02:00:00 -A m5290 -J rhap-mix64
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/mix-N64.out
cd /pscratch/sd/m/merzky/radical/bench
source /pscratch/sd/m/merzky/radical/dragon-investigation/env.sh
export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"')
RES=/pscratch/sd/m/merzky/radical/bench/results/mix
for wl in het d32; do
  out="$RES/${wl}-N64"
  [ -f "$out/dragon/summary.json" ] && [ -f "$out/flux/summary.json" ] && { echo "skip $wl"; continue; }
  mkdir -p "$out"; echo "=== mix 64+64 $wl $(date +%H:%M:%S) ==="
  timeout 1500 python run_mix.py --nper 64 --workload "$wl" --out "$out"
  pkill -u "$USER" -f 'shimhost' 2>/dev/null; pkill -u "$USER" -f 'rhapsody.backends.multiproc.host' 2>/dev/null
  rm -rf /dev/shm/*dragon* 2>/dev/null; sleep 3
done
echo "=== mix 64+64 done ==="
