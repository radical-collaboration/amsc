#!/bin/bash
#SBATCH -N 128 -C cpu -q regular -t 01:00:00 -A m5290 -J rhap-rd128
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/rhap-rd128.out
cd /pscratch/sd/m/merzky/radical/bench
export RESULTS=/pscratch/sd/m/merzky/radical/bench/results/matrix-full; NODE_SCALES=128 WORKLOADS=d32 CELL_TIMEOUT=1500 COMBOS='native-dragon:dragon' bash run_matrix.sh
