#!/bin/bash
#SBATCH -N 8 -C cpu -q regular -t 01:30:00 -A m5290 -J rhap-hetM
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/het-matrix.out
export RESULTS=/pscratch/sd/m/merzky/radical/bench/results/matrix-full
NODE_SCALES="1 2 4 8" WORKLOADS="het" CELL_TIMEOUT=600 \
COMBOS="native-dragon:dragon native-flux:simple native-flux:fluxion rhapsody-flux:simple rhapsody-flux:fluxion rhapsody-dragon:dragon" \
  bash /pscratch/sd/m/merzky/radical/bench/run_matrix.sh
