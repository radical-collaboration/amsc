#!/bin/bash
# One repeat SAMPLE into results/reps/$TAG (mirrors matrix-full + mix layout).
# Env: TAG (req), SCALES, WL, MIX_NPER. Runs matrix(flux/dragon)+proxy+raptor+mix.
set -u
cd /pscratch/sd/m/merzky/radical/bench
TAG=${TAG:?need TAG}
SCALES=${SCALES:-"1 2 4"}
WL=${WL:-"d4 d32 het"}
MIX_NPER=${MIX_NPER:-"2 4"}
REP=/pscratch/sd/m/merzky/radical/bench/results/reps/$TAG
MAT=$REP/matrix-full
echo "### repeat $TAG  scales=[$SCALES] wl=[$WL]  alloc=${SLURM_NNODES:-?}N  $(date)"
RESULTS=$MAT NODE_SCALES="$SCALES" WORKLOADS="$WL" CELL_TIMEOUT=700 \
  COMBOS="native-dragon:dragon native-flux:simple native-flux:fluxion rhapsody-flux:simple" \
  bash ./run_matrix.sh
RESULTS=$MAT NODE_SCALES="$SCALES" WORKLOADS="$WL" CELL_TIMEOUT=900 bash ./run_proxy.sh
RESULTS=$MAT NODE_SCALES="$SCALES" WORKLOADS="$WL" CELL_TIMEOUT=700 bash ./run_raptor.sh
# mix (patched clone)
source /pscratch/sd/m/merzky/radical/dragon-investigation/env.sh
export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
for nper in $MIX_NPER; do
  [ $((2*nper)) -gt ${SLURM_NNODES:-0} ] && { echo "skip mix nper=$nper (>alloc)"; continue; }
  for wl in het d32; do
    [ $nper -eq 2 ] && suf="" || suf="-N$nper"
    out="$REP/mix/${wl}${suf}"
    [ -f "$out/flux/summary.json" ] && { echo "skip mix $wl nper$nper"; continue; }
    mkdir -p "$out"; echo "=== rep mix $wl nper$nper $(date +%H:%M:%S) ==="
    timeout 900 python run_mix.py --nper $nper --workload "$wl" --out "$out"
    pkill -u "$USER" -f 'shimhost' 2>/dev/null
    pkill -u "$USER" -f 'rhapsody.backends.multiproc.host' 2>/dev/null
    rm -rf /dev/shm/*dragon* 2>/dev/null; sleep 3
  done
done
echo "### repeat $TAG DONE $(date)"
