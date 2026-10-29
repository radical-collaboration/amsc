#!/bin/bash
# Scaling matrix driver.  Runs inside an allocation (salloc/sbatch).
#   node scales x (backend:sched) x workloads, one round, full teardown.
# Resumable: a cell whose summary.json exists is skipped.  Continue-on-failure.
#
# Tunables (env):
#   RESULTS       output root (required for resume; default: timestamped)
#   NODE_SCALES   default "1 2 4 8"
#   COMBOS        default all 5 "backend:sched" pairs
#   WORKLOADS     default "zero d1 d4 d16 d32 het"
#   CELL_TIMEOUT  per-cell seconds (default 1200)
set -u
cd "$(dirname "$0")"
BENCH=$(pwd)
source ./env.sh
# rhapsody_rm needs SLURM_CPUS_ON_NODE (set only inside a step)
if [ -z "${SLURM_CPUS_ON_NODE:-}" ] && [ -n "${SLURM_JOB_ID:-}" ]; then
  export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
fi

NODE_SCALES=${NODE_SCALES:-"1 2 4 8"}
COMBOS=${COMBOS:-"native-dragon:dragon native-flux:simple native-flux:fluxion rhapsody-flux:simple rhapsody-flux:fluxion"}
WORKLOADS=${WORKLOADS:-"zero d1 d4 d16 d32 het"}
CELL_TIMEOUT=${CELL_TIMEOUT:-1200}
RESULTS=${RESULTS:-$SCRATCH/radical/bench/results/matrix-$(date +%Y%m%d-%H%M%S)}
mkdir -p "$RESULTS"
echo "RESULTS=$RESULTS  SLURM_CPUS_ON_NODE=$SLURM_CPUS_ON_NODE  alloc=$SLURM_NNODES nodes"

launch_cell() {   # nodes backend sched workload out
  local nodes=$1 backend=$2 sched=$3 wl=$4 out=$5
  # scheduler selection is environment-driven (verified fix):
  #   fluxion  -> FLUX_MODPROBE_PATH_APPEND (via fluxion_modprobe.env.sh)
  #   simple   -> default; make sure no fluxion/rc override leaks in
  if [ "$sched" = fluxion ]; then
    source "$BENCH/fluxion_modprobe.env.sh"
  else
    unset FLUX_MODPROBE_PATH_APPEND FLUX_RC_EXTRA
  fi
  case "$backend" in
    rhapsody-flux)
      timeout "$CELL_TIMEOUT" python run_one.py \
        --sched "$sched" --nodes "$nodes" --workload "$wl" --out "$out" ;;
    native-flux)
      BENCH_SCHED="$sched" \
      timeout "$CELL_TIMEOUT" srun --overlap --nodes="$nodes" --ntasks="$nodes" \
        --ntasks-per-node=1 flux start \
        python native_flux.py --nodes "$nodes" --workload "$wl" --out "$out" ;;
    native-dragon)
      timeout "$CELL_TIMEOUT" dragon python native_dragon.py \
        --nodes "$nodes" --workload "$wl" --out "$out" ;;
    rhapsody-dragon)
      timeout "$CELL_TIMEOUT" dragon python rhapsody_dragon.py \
        --nodes "$nodes" --workload "$wl" --out "$out" ;;
  esac
}

for nodes in $NODE_SCALES; do
  [ "$nodes" -gt "${SLURM_NNODES:-0}" ] && { echo "skip N$nodes (> alloc)"; continue; }
  for combo in $COMBOS; do
    backend=${combo%%:*}; sched=${combo##*:}
    for wl in $WORKLOADS; do
      name="${backend}-${sched}-${wl}-N${nodes}"
      out="$RESULTS/$name"
      [ -f "$out/summary.json" ] && { echo "skip (done) $name"; continue; }
      mkdir -p "$out"
      echo "=== $(date +%H:%M:%S) $name ==="
      launch_cell "$nodes" "$backend" "$sched" "$wl" "$out" > "$out/run.log" 2>&1
      rc=$?
      [ $rc -ne 0 ] && echo "  exit=$rc FAILED" || echo "  exit=0"
      # clean slate between runs
      pkill -u "$USER" -f 'native_dragon|multiproc.host' 2>/dev/null
      rm -rf /dev/shm/*dragon* 2>/dev/null
      sleep 2
    done
  done
done

echo "=== matrix complete: $RESULTS ==="
python aggregate.py "$RESULTS"
