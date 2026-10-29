#!/bin/bash
# rhapsody-dragon ‖ native-flux, 2+2, inside a 4-node alloc
set -u
cd "$(dirname "$0")"; source ./env.sh
if [ -z "${SLURM_CPUS_ON_NODE:-}" ]; then
  export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
fi
RESULTS=${RESULTS:-$SCRATCH/radical/bench/results/partB-2x2}
for wl in zero d32 het; do
  out=$RESULTS/split-$wl
  [ -f "$out/rhapsody-dragon/summary.json" ] && [ -f "$out/native-flux/summary.json" ] && { echo "skip $wl"; continue; }
  mkdir -p "$out"; echo "=== 2+2 split $wl $(date +%H:%M:%S) ==="
  timeout 900 python run_split.py --workload "$wl" --out "$out" --nper 2
  pkill -u "$USER" -f 'rhapsody_dragon|native_dragon' 2>/dev/null; rm -rf /dev/shm/*dragon* 2>/dev/null; sleep 3
done
echo "=== 2x2 split done ==="
