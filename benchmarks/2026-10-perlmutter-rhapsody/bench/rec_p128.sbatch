#!/bin/bash
#SBATCH -N 128 -C cpu -q regular -t 01:00:00 -A m5290 -J rhap-rp128
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/rhap-rp128.out
cd /pscratch/sd/m/merzky/radical/bench
RESULTS=/pscratch/sd/m/merzky/radical/bench/results/matrix-full NODE_SCALES=128 WORKLOADS=d32 CELL_TIMEOUT=1500 bash run_proxy.sh
