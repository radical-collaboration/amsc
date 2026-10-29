#!/bin/bash
#SBATCH -N 8 -C cpu -q debug -t 00:30:00 -A m5290 -J fn-flux
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/fn/sched_flux.out
cd /pscratch/sd/m/merzky/radical/bench; source fn/env.sh
export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"')
for n in 1 2 4 8; do
  d=/pscratch/sd/m/merzky/radical/bench/results/fn/matrix/flux-fnzero-N$n; [ -f $d/summary.json ] || timeout 400 python fn/fn_flux.py --nodes $n --dur 0 --ncores 1 --count 5000          --out $d
  d=/pscratch/sd/m/merzky/radical/bench/results/fn/matrix/flux-fnutil-N$n; [ -f $d/summary.json ] || timeout 400 python fn/fn_flux.py --nodes $n --dur 2 --ncores 4 --count $((1000*n))   --out $d
done; echo "flux sched done"
