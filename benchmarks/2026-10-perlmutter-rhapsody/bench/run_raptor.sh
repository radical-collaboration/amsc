#!/bin/bash
# raptor scaling cells (standalone pilot-free Raptor). Runs in a batch alloc;
# backend srun-launches its own master+workers. Resumable.
set -u
cd /pscratch/sd/m/merzky/radical/bench
source /pscratch/sd/m/merzky/radical/raptor-standalone/bin/env.sh
export RHAP_TASKRUN=/pscratch/sd/m/merzky/radical/bench/taskrun
RESULTS=${RESULTS:-/pscratch/sd/m/merzky/radical/bench/results/matrix-full}
NODE_SCALES=${NODE_SCALES:-"1 2 4"}
WORKLOADS=${WORKLOADS:-"zero d1 d4 d16 d32 het"}
CELL_TIMEOUT=${CELL_TIMEOUT:-1500}
for nodes in $NODE_SCALES; do
  [ "$nodes" -gt "${SLURM_NNODES:-0}" ] && { echo "skip N$nodes>alloc"; continue; }
  for wl in $WORKLOADS; do
    name="raptor-raptor-${wl}-N${nodes}"; out="$RESULTS/$name"
    [ -f "$out/summary.json" ] && { echo "skip(done) $name"; continue; }
    mkdir -p "$out"; echo "=== $(date +%H:%M:%S) $name ==="
    timeout "$CELL_TIMEOUT" ${PYTHON} raptor_one.py --nodes "$nodes" --workload "$wl" --out "$out" > "$out/run.log" 2>&1
    echo "  rc=$?"
    pkill -u "$USER" -f 'raptor_standalone.worker' 2>/dev/null; sleep 3
  done
done
echo "raptor sweep done ($NODE_SCALES)"
