#!/bin/bash
set -u
cd /pscratch/sd/m/merzky/radical/bench
source fn/env.sh
export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
BASE=/pscratch/sd/m/merzky/radical/rhapsody/src
CHUNK=/pscratch/sd/m/merzky/radical/rhapsody-chunk2/src
FN=/pscratch/sd/m/merzky/radical/bench/fn:/pscratch/sd/m/merzky/radical/bench
RES=/pscratch/sd/m/merzky/radical/bench/results/fn/cmp2
echo "### ported-chunk vs baseline (feature/flux)  alloc=${SLURM_NNODES}N  $(date)"
run(){ local label=$1 src=$2; shift 2
  echo "--- $label ---"
  timeout 700 env PYTHONPATH=$src:$FN dragon python fn/fn_dragon.py --nodes 2 --dur 0 --count 100000 "$@" --out $RES/$label 2>&1 \
    | grep -E '"throughput_overall"|"n_done"|"makespan_s"' | tr -d ' ,'
  pkill -u $USER -f 've.rh/bin/dragon' 2>/dev/null; rm -rf /dev/shm/*dragon* 2>/dev/null; sleep 5
}
run base-rec-100k   $BASE
run chunk-rec-100k  $CHUNK
run base-noop-100k  $BASE  --noop
run chunk-noop-100k $CHUNK --noop
echo "### done $(date)"
