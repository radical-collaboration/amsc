#!/bin/bash
#SBATCH -N 32 -C cpu -q regular -t 00:45:00 -A m5290 -J rhap-rd32
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/rhap-rd32.out
cd /pscratch/sd/m/merzky/radical/bench
export RESULTS=/pscratch/sd/m/merzky/radical/bench/results/matrix-full; NODE_SCALES=32  WORKLOADS=d32 CELL_TIMEOUT=900  COMBOS='native-dragon:dragon' bash run_matrix.sh
