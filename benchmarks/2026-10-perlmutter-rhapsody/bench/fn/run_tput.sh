#!/bin/bash
set -u
cd /pscratch/sd/m/merzky/radical/bench
source fn/env.sh                       # ve.rh + dragon 0.14.1 + rhapsody-fnflux(feature/flux) on PYTHONPATH
# use the throughput test from the feature/flux tree
export PYTHONPATH=/pscratch/sd/m/merzky/radical/rhapsody/src:$PYTHONPATH
SCRIPT=/pscratch/sd/m/merzky/radical/rhapsody/tests/integration/test-hpc/dragon/test_throughput.py
echo "### dragon throughput test  alloc=${SLURM_NNODES}N  $(date)"
echo "script: $SCRIPT"
timeout 600 dragon python "$SCRIPT" --min_tasks 10000 --max_tasks 40000 2>&1 \
  | grep -vE "warning:|PWD|DEBUG|INFO" | tail -30
echo "### done rc=? $(date)"
