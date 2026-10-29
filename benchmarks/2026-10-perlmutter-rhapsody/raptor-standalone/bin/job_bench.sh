#!/bin/bash
#SBATCH -A m5290
#SBATCH -C cpu
#SBATCH -q interactive
#SBATCH -N 4
#SBATCH -t 00:50:00
#SBATCH -J raptor-sa-bench
#SBATCH -o /pscratch/sd/m/merzky/radical/raptor-standalone/results/bench_%j.out
#SBATCH -e /pscratch/sd/m/merzky/radical/raptor-standalone/results/bench_%j.err

set -x
source /pscratch/sd/m/merzky/radical/raptor-standalone/bin/env.sh

RES=/pscratch/sd/m/merzky/radical/raptor-standalone/results/bench_$SLURM_JOB_ID
mkdir -p $RES
TR=/pscratch/sd/m/merzky/radical/bench/taskrun

echo "=== allocation: $SLURM_JOB_NODELIST  nodes=$SLURM_NNODES ==="

# ---- Milestone 2/3 validation: multi-node, pilot-free, >=100 tasks ----
echo "=== M2/M3 multi-node validation (2 nodes, /bin/true-ish taskrun x200) ==="
$PYTHON /pscratch/sd/m/merzky/radical/raptor-standalone/tests/test_m3_rhapsody.py \
    --workdir $RES/m3_validate --ntasks 200 --workers 2 \
    --nslots 128 --bulk 16 --taskrun $TR --dur 0

# ---- Milestone 4 benchmark sweep: 1,2,4 nodes x bulk sweep ----
echo "=== M4 benchmark sweep ==="
$PYTHON /pscratch/sd/m/merzky/radical/raptor-standalone/tests/bench.py \
    --workdir $RES/sweep --taskrun $TR --nodes 4 \
    --node-sweep 1,2,4 --slots 128 --bulk-sweep 1,16,64 \
    --prefetch 4 --ntasks 4000 --dur 1

echo "=== ALL DONE ==="
