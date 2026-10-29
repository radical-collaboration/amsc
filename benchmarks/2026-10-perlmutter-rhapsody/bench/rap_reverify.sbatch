#!/bin/bash
#SBATCH -N 2 -C cpu -q debug -t 00:15:00 -A m5290 -J rhap-rapRV
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/rap-reverify.out
cd /pscratch/sd/m/merzky/radical/bench
source /pscratch/sd/m/merzky/radical/raptor-standalone/bin/env.sh
export RHAP_TASKRUN=/pscratch/sd/m/merzky/radical/bench/taskrun
out=/pscratch/sd/m/merzky/radical/bench/results/rap-reverify/raptor-raptor-d32-N2; mkdir -p "$out"
timeout 400 ${PYTHON} raptor_one.py --nodes 2 --workload d32 --out "$out"; echo "rc=$?"
