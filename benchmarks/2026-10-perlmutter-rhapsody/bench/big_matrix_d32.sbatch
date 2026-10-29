#!/bin/bash
#SBATCH -N 128 -C cpu -q regular -t 03:00:00 -A m5290 -J rhap-bigM
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/big-matrix-d32.out
export RESULTS=/pscratch/sd/m/merzky/radical/bench/results/matrix-full
NODE_SCALES="32 128" WORKLOADS="d32" CELL_TIMEOUT=2400 \
COMBOS="native-dragon:dragon native-flux:simple native-flux:fluxion rhapsody-flux:simple rhapsody-flux:fluxion rhapsody-dragon:dragon" \
  bash /pscratch/sd/m/merzky/radical/bench/run_matrix.sh
