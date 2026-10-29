#!/bin/bash
set -u
cd /pscratch/sd/m/merzky/radical/bench
source fn/env.sh
export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
BASE=/pscratch/sd/m/merzky/radical/rhapsody/src
CHUNK=/pscratch/sd/m/merzky/radical/rhapsody-chunk/src
FN=/pscratch/sd/m/merzky/radical/bench/fn:/pscratch/sd/m/merzky/radical/bench
RES=/pscratch/sd/m/merzky/radical/bench/results/fn/cmp
echo "### chunk vs baseline  alloc=${SLURM_NNODES}N  $(date)"
run(){ # label src extra count
  local label=$1 src=$2 cnt=$3; shift 3
  echo "--- $label (count=$cnt $*) ---"
  PYTHONPATH=$src:$FN dragon python fn/fn_dragon.py --nodes 2 --dur 0 --count $cnt "$@" --out $RES/$label 2>&1 \
    | grep -E '"throughput_overall"|"n_done"|"makespan_s"' | tr -d ' ,'
  pkill -u $USER -f 've.rh/bin/dragon' 2>/dev/null; rm -rf /dev/shm/*dragon* 2>/dev/null; sleep 4
}
run base-rec-40k   $BASE  40000
run chunk-rec-40k  $CHUNK 40000
run base-rec-100k  $BASE  100000
run chunk-rec-100k $CHUNK 100000
run base-noop-100k $BASE  100000 --noop
run chunk-noop-100k $CHUNK 100000 --noop
echo "### done $(date)"
