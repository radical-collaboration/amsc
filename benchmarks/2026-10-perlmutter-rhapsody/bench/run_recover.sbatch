#!/bin/bash
#SBATCH -N 8 -C cpu -q regular -t 01:00:00 -A m5290 -J rhap-recover
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/recover.out
export RESULTS=/pscratch/sd/m/merzky/radical/bench/results/matrix-full
NODE_SCALES="8" COMBOS="rhapsody-flux:simple" WORKLOADS="zero d1" CELL_TIMEOUT=1800   bash /pscratch/sd/m/merzky/radical/bench/run_matrix.sh
