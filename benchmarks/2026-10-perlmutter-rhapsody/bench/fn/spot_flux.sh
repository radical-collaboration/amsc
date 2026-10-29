#!/bin/bash
set -u
cd /pscratch/sd/m/merzky/radical/bench
source fn/env.sh
export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
echo "### flux-fn spot-check  alloc=${SLURM_NNODES}N  $(date)"
echo "=== flux-fn zero-dur x 2000 (dispatch rate) ==="
timeout 600 python fn/fn_flux.py --nodes 2 --dur 0  --ncores 1 --count 2000 --out results/fn/spot-flux-zero 2>&1 | tail -20
echo "=== flux-fn 2s x 4-core x 256 (multi-core util) ==="
timeout 600 python fn/fn_flux.py --nodes 2 --dur 2 --ncores 4 --count 256  --out results/fn/spot-flux-d2c4 2>&1 | tail -20
echo "### spot done $(date)"
