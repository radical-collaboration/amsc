#!/bin/bash
set -u
cd /pscratch/sd/m/merzky/radical/bench
source fn/env.sh
export PYTHONPATH=/pscratch/sd/m/merzky/radical/rhapsody/src:$PYTHONPATH
export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
echo "### Step 0  alloc=${SLURM_NNODES}N  $(date)"
echo "=== raw dragon Batch ceiling ==="
timeout 500 dragon python fn/raw_batch_bench.py --count 40000 2>&1 | grep -E "tasks/s|Batch up|Error|Traceback|Dragon" | tail -12
pkill -u $USER -f 've.rh/bin/dragon' 2>/dev/null; rm -rf /dev/shm/*dragon* 2>/dev/null; sleep 5
echo "=== profile rhapsody submit (40k no_op) ==="
timeout 500 dragon python -m cProfile -o fn/prof_submit.out fn/test_throughput_patched.py --min_tasks 40000 --max_tasks 40000 2>&1 | grep -E "throughput|[0-9]+ +[0-9]" | tail -6
echo "### done $(date)"
