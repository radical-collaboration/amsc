#!/bin/bash
set -u
cd /pscratch/sd/m/merzky/radical/bench
source fn/env.sh                      # baseline = rhapsody-fnflux (feature/flux dragon) + bench/fn + bench
export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
BASE_PP="$PYTHONPATH"
CHUNK_PP="/pscratch/sd/m/merzky/radical/rhapsody-chunk2/src:$PYTHONPATH"
RES=/pscratch/sd/m/merzky/radical/bench/results/fn/cmp3
echo "### ported-chunk vs baseline  alloc=${SLURM_NNODES}N  $(date)"
run(){ local label=$1 pp=$2; shift 2
  echo "--- $label ---"
  PYTHONPATH="$pp" timeout 650 dragon python fn/fn_dragon.py --nodes 2 --dur 0 --count 60000 "$@" --out $RES/$label 2>&1 \
    | grep -E '"throughput_overall"|"n_done"|"makespan_s"' | tr -d ' ,'
  pkill -u $USER -f 've.rh/bin/dragon' 2>/dev/null; rm -rf /dev/shm/*dragon* 2>/dev/null; sleep 5
}
echo "--- chunk-smoke (3k, validate port runs) ---"
PYTHONPATH="$CHUNK_PP" timeout 300 dragon python fn/fn_dragon.py --nodes 2 --dur 0 --count 3000 --out $RES/chunk-smoke 2>&1 | grep -E 'throughput_overall|n_done' | tr -d ' ,'
pkill -u $USER -f 've.rh/bin/dragon' 2>/dev/null; rm -rf /dev/shm/*dragon* 2>/dev/null; sleep 5
run base-rec   "$BASE_PP"
run chunk-rec  "$CHUNK_PP"
run base-noop  "$BASE_PP"  --noop
run chunk-noop "$CHUNK_PP" --noop
echo "### done $(date)"
