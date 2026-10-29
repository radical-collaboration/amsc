#!/bin/bash
# Test campaign: 3 backends/schedulers x 3 workloads on $NODES nodes, one round.
# Each cell runs in a fresh python process with a timeout guard and a clean
# slate afterwards (the launch-overhead measurement wants cold starts).
# Run inside an allocation:  salloc -N2 ... bash run_test.sh
set -u
cd "$(dirname "$0")"
source ./env.sh

# rhapsody_rm needs SLURM_CPUS_ON_NODE, which Slurm sets only inside a step --
# the driver runs at the allocation level, so probe it once via a tiny srun.
if [ -z "${SLURM_CPUS_ON_NODE:-}" ] && [ -n "${SLURM_JOB_ID:-}" ]; then
  export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap \
      bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
fi
echo "SLURM_CPUS_ON_NODE=$SLURM_CPUS_ON_NODE"

NODES=${NODES:-2}
TS=$(date +%Y%m%d-%H%M%S)
RESULTS=$SCRATCH/radical/bench/results/test-$TS
mkdir -p "$RESULTS"
echo "results: $RESULTS   nodes: $NODES"

CELLS=(
  "dragon none    zero"    "dragon none    fixed32" "dragon none    het"
  "flux   simple  zero"    "flux   simple  fixed32" "flux   simple  het"
  "flux   fluxion zero"    "flux   fluxion fixed32" "flux   fluxion het"
)

for cell in "${CELLS[@]}"; do
  set -- $cell; backend=$1; sched=$2; wl=$3
  # optional filter, e.g. BACKEND_FILTER=flux to skip the dragon cells
  [ -n "${BACKEND_FILTER:-}" ] && [ "$backend" != "$BACKEND_FILTER" ] && continue
  name="${backend}-${sched}-${wl}-N${NODES}"
  out="$RESULTS/$name"; mkdir -p "$out"
  echo "=== $name ==="
  timeout "${CELL_TIMEOUT:-600}" python run_one.py --backend "$backend" --sched "$sched" \
      --nodes "$NODES" --workload "$wl" --out "$out" > "$out/run.log" 2>&1
  rc=$?
  [ $rc -ne 0 ] && echo "  exit=$rc FAILED (see $out/run.log)" || echo "  exit=0"
  # clean slate between runs (dragon can leak shm segments / ports)
  pkill -u "$USER" -f 'dragon' 2>/dev/null || true
  rm -rf /dev/shm/*dragon* 2>/dev/null || true
  sleep 3
done

echo; echo "=== SUMMARY ($RESULTS) ==="
python - "$RESULTS" <<'PY'
import glob, json, os, sys
root = sys.argv[1]
hdr = f"{'cell':<26}{'bringup':>8}{'teard':>7}{'makespan':>9}{'thru_ss':>9}{'util':>7}{'done':>10}"
print(hdr); print("-" * len(hdr))
for s in sorted(glob.glob(os.path.join(root, "*", "summary.json"))):
    d = json.load(open(s))
    cell = f"{d['backend']}-{d['sched']}-{d['workload']}"
    thr = d.get("throughput_steady") or 0
    util = d.get("utilization") or 0
    done = f"{d['n_done']}/{d['n_tasks']}"
    print(f"{cell:<26}{d['bringup_s']:>8}{d['teardown_s']:>7}{d['makespan_s']:>9}"
          f"{round(thr,1):>9}{round(util,3):>7}{done:>10}")
PY
