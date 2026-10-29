#!/bin/bash
set -u
cd /pscratch/sd/m/merzky/radical/bench
source fn/env_raptor.sh
echo "### raptor-fn spot alloc=${SLURM_NNODES}N $(date)"
echo "=== raptor-fn zero-dur x 20000 (native dispatch rate) ==="
timeout 600 $PYTHON fn/fn_raptor.py --nodes 2 --dur 0 --ncores 1 --count 20000 --nslots 128 --out results/fn/spot-raptor-zero 2>&1 | tail -18
echo "=== raptor-fn 2s x 4-core x 256, nslots=32 (core-aware util) ==="
timeout 600 $PYTHON fn/fn_raptor.py --nodes 2 --dur 2 --ncores 4 --count 256 --nslots 32 --out results/fn/spot-raptor-d2c4 2>&1 | tail -18
echo "### done $(date)"
