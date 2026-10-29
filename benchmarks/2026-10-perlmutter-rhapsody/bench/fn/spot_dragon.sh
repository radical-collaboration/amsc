#!/bin/bash
set -u
cd /pscratch/sd/m/merzky/radical/bench
source fn/env.sh
export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
echo "### dragon-fn spot  alloc=${SLURM_NNODES}N $(date)"
echo "=== dragon-fn zero-dur x 20000 (native dispatch rate) ==="
timeout 600 dragon python fn/fn_dragon.py --nodes 2 --dur 0 --ncores 1 --count 20000 --out results/fn/spot-dragon-zero 2>&1 | tail -18
echo "=== dragon-fn 2s x 4-core x 512 (multi-core util) ==="
timeout 600 dragon python fn/fn_dragon.py --nodes 2 --dur 2 --ncores 4 --count 512 --out results/fn/spot-dragon-d2c4 2>&1 | tail -18
echo "### done $(date)"
