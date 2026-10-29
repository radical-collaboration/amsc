#!/bin/bash
#SBATCH -N 32 -C cpu -q regular -t 00:45:00 -A m5290 -J rhap-rf32
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/rhap-rf32.out
cd /pscratch/sd/m/merzky/radical/bench
export RESULTS=/pscratch/sd/m/merzky/radical/bench/results/matrix-full; NODE_SCALES=32  WORKLOADS=d32 CELL_TIMEOUT=900  COMBOS='native-flux:simple native-flux:fluxion rhapsody-flux:simple' bash run_matrix.sh
