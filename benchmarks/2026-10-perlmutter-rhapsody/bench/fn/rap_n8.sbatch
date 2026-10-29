#!/bin/bash
#SBATCH -N 8 -C cpu -q debug -t 00:20:00 -A m5290 -J fn-rapN8
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/fn/rap_n8.out
cd /pscratch/sd/m/merzky/radical/bench; source fn/env_raptor.sh
d=/pscratch/sd/m/merzky/radical/bench/results/fn/matrix/raptor-fnzero-N8
timeout 700 $PYTHON fn/fn_raptor.py --nodes 8 --dur 0 --count 80000 --nslots 128 --out $d
echo "rap N8 done"
