#!/bin/bash
set -u
cd /pscratch/sd/m/merzky/radical/bench
source fn/env.sh
export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
BASE_PP="$PYTHONPATH"; CHUNK_PP="/pscratch/sd/m/merzky/radical/rhapsody-chunk2/src:$PYTHONPATH"
echo "=== baseline 100 (sanity) ==="
PYTHONPATH="$BASE_PP" timeout 120 dragon python fn/fn_dragon.py --nodes 1 --dur 0 --count 100 --out results/fn/diag/base100 2>&1 | grep -E 'throughput_overall|n_done|Error|Traceback' | tr -d ' ,' | tail -5
pkill -u $USER -f 've.rh/bin/dragon' 2>/dev/null; rm -rf /dev/shm/*dragon* 2>/dev/null; sleep 4
echo "=== chunk-port 100 (does it hang?) rc captured ==="
PYTHONPATH="$CHUNK_PP" timeout 120 dragon python fn/fn_dragon.py --nodes 1 --dur 0 --count 100 --out results/fn/diag/chunk100 2>&1 | tail -15
echo "chunk rc=$?"
pkill -u $USER -f 've.rh/bin/dragon' 2>/dev/null
echo "### diag done"
