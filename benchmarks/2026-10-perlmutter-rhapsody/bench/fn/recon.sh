#!/bin/bash
set -u
cd /pscratch/sd/m/merzky/radical/bench
source fn/env.sh
export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
echo "### dispatch reconciliation  alloc=${SLURM_NNODES}N  $(date)"
echo "=== C: RAW dragon mp.Pool, no-op, no rhapsody, no record I/O ==="
timeout 400 dragon python fn/fn_recon.py --count 200000 --procs 256 2>&1 | grep -E "RAW|Error|Traceback" | tail -8
echo "=== B: rhapsody-dragon, no-op payload (Session overhead, no record I/O) ==="
timeout 400 dragon python fn/fn_dragon.py --nodes 2 --dur 0 --count 100000 --noop --out results/fn/recon-dragon-noop 2>&1 | grep -E "throughput_overall|n_done|makespan_s" | tail -4
echo "### A (reference): rhapsody-dragon WITH per-task record = ~300/s (matrix)"
echo "### done $(date)"
