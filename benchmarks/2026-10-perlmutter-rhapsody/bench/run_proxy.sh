#!/bin/bash
# rhapsody-dragon-proxy scaling cells (AF_INET proxy, patched clone). Runs
# inside a batch alloc (driver must be on a compute node). Resumable.
set -u
cd /pscratch/sd/m/merzky/radical/bench
source /pscratch/sd/m/merzky/radical/dragon-investigation/env.sh   # patched clone
if [ -z "${SLURM_CPUS_ON_NODE:-}" ]; then
  export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"')
fi
RESULTS=${RESULTS:-/pscratch/sd/m/merzky/radical/bench/results/matrix-full}
NODE_SCALES=${NODE_SCALES:-"1 2 4"}
WORKLOADS=${WORKLOADS:-"zero_c d1_c d4 d16 d32 het"}
CELL_TIMEOUT=${CELL_TIMEOUT:-1500}
k=0   # per-cell dragon port offset: repeated launches on fixed ports clash
for nodes in $NODE_SCALES; do
  [ "$nodes" -gt "${SLURM_NNODES:-0}" ] && { echo "skip N$nodes>alloc"; continue; }
  for wl in $WORKLOADS; do
    name="rhapsody-dragon-proxy-dragon-${wl}-N${nodes}"; out="$RESULTS/$name"
    [ -f "$out/summary.json" ] && { echo "skip(done) $name"; continue; }
    mkdir -p "$out"; echo "=== $(date +%H:%M:%S) $name (port-offset $((k*20))) ==="
    timeout "$CELL_TIMEOUT" python rhapsody_dragon_proxy.py --nodes "$nodes" --workload "$wl" \
        --out "$out" --port-offset $((k*20)) > "$out/run.log" 2>&1
    echo "  rc=$?"; k=$((k+1))
    # clean slate: leftover shim/host + lingering dragon launcher + shm segs
    pkill -u "$USER" -f 'shimhost' 2>/dev/null
    pkill -u "$USER" -f 'rhapsody.backends.multiproc.host' 2>/dev/null
    pkill -u "$USER" -f 've.rh/bin/dragon' 2>/dev/null
    rm -rf /dev/shm/*dragon* 2>/dev/null; sleep 5
  done
done
echo "proxy sweep done ($NODE_SCALES)"
