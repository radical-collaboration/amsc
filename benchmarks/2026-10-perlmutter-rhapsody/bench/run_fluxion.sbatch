#!/bin/bash
#SBATCH -N 8 -C cpu -q regular -t 05:00:00 -A m5290 -J rhap-fluxion
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/fluxion-matrix.out
export RESULTS=/pscratch/sd/m/merzky/radical/bench/results/matrix-full
NODE_SCALES="1 2 4 8" COMBOS="native-flux:fluxion rhapsody-flux:fluxion" CELL_TIMEOUT=1800 \
  bash /pscratch/sd/m/merzky/radical/bench/run_matrix.sh
