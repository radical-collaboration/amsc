#!/bin/bash
# raptor-native scaling cells: standalone pilot-free Raptor driven directly
# (raptor_native_one.py, no rhapsody). Modelled on bench/run_raptor.sh: same
# env, payload, workloads and cell timeout. Runs in a batch alloc; the driver
# srun-launches its own workers. Resumable (cells with summary.json skipped).
set -u
HERE=/pscratch/sd/m/merzky/radical/raptor-native
cd "$HERE"
source /pscratch/sd/m/merzky/radical/raptor-standalone/bin/env.sh
export RHAP_TASKRUN=/pscratch/sd/m/merzky/radical/bench/taskrun
export PYTHONDONTWRITEBYTECODE=1   # no __pycache__ into bench/ or raptor-standalone/
RESULTS=${RESULTS:-$HERE/results/matrix}
NODE_SCALES=${NODE_SCALES:-"1 2 4 8"}
WORKLOADS=${WORKLOADS:-"zero d1 d4 d16 d32 het"}
CELL_TIMEOUT=${CELL_TIMEOUT:-1500}
for nodes in $NODE_SCALES; do
  [ "$nodes" -gt "${SLURM_NNODES:-0}" ] && { echo "skip N$nodes>alloc"; continue; }
  for wl in $WORKLOADS; do
    name="raptor-native-${wl}-N${nodes}"; out="$RESULTS/$name"
    [ -f "$out/summary.json" ] && { echo "skip(done) $name"; continue; }
    mkdir -p "$out"; echo "=== $(date +%H:%M:%S) $name ==="
    timeout "$CELL_TIMEOUT" ${PYTHON} raptor_native_one.py --nodes "$nodes" --workload "$wl" --out "$out" > "$out/run.log" 2>&1
    echo "  rc=$?"
    pkill -u "$USER" -f 'raptor_standalone.worker' 2>/dev/null; sleep 3
  done
done
echo "raptor-native sweep done ($NODE_SCALES)"
