#!/bin/bash
#SBATCH -N 8 -C cpu -q debug -t 00:30:00 -A m5290 -J fn-raptor
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/fn/sched_raptor.out
cd /pscratch/sd/m/merzky/radical/bench; source fn/env_raptor.sh
for n in 1 2 4 8; do
  d=/pscratch/sd/m/merzky/radical/bench/results/fn/matrix/raptor-fnzero-N$n; [ -f $d/summary.json ] || timeout 500 $PYTHON fn/fn_raptor.py --nodes $n --dur 0 --count $((50000*n)) --nslots 128 --out $d
  pkill -u $USER -f 'raptor_standalone.worker' 2>/dev/null; sleep 4
  d=/pscratch/sd/m/merzky/radical/bench/results/fn/matrix/raptor-fnutil-N$n; [ -f $d/summary.json ] || timeout 500 $PYTHON fn/fn_raptor.py --nodes $n --dur 2 --ncores 4 --count $((1000*n)) --nslots 32 --out $d
  pkill -u $USER -f 'raptor_standalone.worker' 2>/dev/null; sleep 4
done; echo "raptor sched done"
