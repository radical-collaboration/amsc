#!/bin/bash
#SBATCH -N 128 -C cpu -q regular -t 01:00:00 -A m5290 -J rhap-rf128
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/rhap-rf128.out
cd /pscratch/sd/m/merzky/radical/bench
export RESULTS=/pscratch/sd/m/merzky/radical/bench/results/matrix-full; NODE_SCALES=128 WORKLOADS=d32 CELL_TIMEOUT=1800 COMBOS='native-flux:simple native-flux:fluxion rhapsody-flux:simple' bash run_matrix.sh
