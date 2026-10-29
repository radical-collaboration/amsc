#!/bin/bash
#SBATCH -N 32 -C cpu -q regular -t 02:00:00 -A m5290 -J rhap-bigM32
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/big-matrix-32.out
export RESULTS=/pscratch/sd/m/merzky/radical/bench/results/matrix-full
NODE_SCALES="32" WORKLOADS="d16 het" CELL_TIMEOUT=1800 \
COMBOS="native-dragon:dragon native-flux:simple native-flux:fluxion rhapsody-flux:simple rhapsody-flux:fluxion rhapsody-dragon:dragon" \
  bash /pscratch/sd/m/merzky/radical/bench/run_matrix.sh
