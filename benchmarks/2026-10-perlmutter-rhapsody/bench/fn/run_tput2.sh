#!/bin/bash
set -u
cd /pscratch/sd/m/merzky/radical/bench
source fn/env.sh
export PYTHONPATH=/pscratch/sd/m/merzky/radical/rhapsody/src:$PYTHONPATH
echo "### dragon throughput test (patched clear_results)  alloc=${SLURM_NNODES}N  $(date)"
timeout 600 dragon python fn/test_throughput_patched.py --min_tasks 10000 --max_tasks 40000 2>&1 \
  | grep -vE "warning:|PWD|DEBUG|INFO|clear_results skipped" | tail -25
echo "### done $(date)"
