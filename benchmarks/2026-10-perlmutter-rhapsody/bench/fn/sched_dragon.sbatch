#!/bin/bash
#SBATCH -N 8 -C cpu -q debug -t 00:30:00 -A m5290 -J fn-dragon
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/fn/sched_dragon.out
cd /pscratch/sd/m/merzky/radical/bench; source fn/env.sh
export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"')
for n in 1 2 4 8; do
  d=/pscratch/sd/m/merzky/radical/bench/results/fn/matrix/dragon-fnzero-N$n; [ -f $d/summary.json ] || timeout 500 dragon python fn/fn_dragon.py --nodes $n --dur 0 --count $((20000*n)) --out $d
  pkill -u $USER -f 've.rh/bin/dragon' 2>/dev/null; rm -rf /dev/shm/*dragon* 2>/dev/null; sleep 4
  d=/pscratch/sd/m/merzky/radical/bench/results/fn/matrix/dragon-fnutil-N$n; [ -f $d/summary.json ] || timeout 500 dragon python fn/fn_dragon.py --nodes $n --dur 2 --ncores 4 --count $((1000*n)) --out $d
  pkill -u $USER -f 've.rh/bin/dragon' 2>/dev/null; rm -rf /dev/shm/*dragon* 2>/dev/null; sleep 4
done; echo "dragon sched done"
