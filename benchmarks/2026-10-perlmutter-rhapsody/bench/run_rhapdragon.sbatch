#!/bin/bash
#SBATCH -N 8 -C cpu -q regular -t 04:00:00 -A m5290 -J rhap-rdmatrix
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/rdmatrix.out
export RESULTS=/pscratch/sd/m/merzky/radical/bench/results/matrix-full
NODE_SCALES="1 2 4 8" COMBOS="rhapsody-dragon:dragon" CELL_TIMEOUT=1800 \
  bash /pscratch/sd/m/merzky/radical/bench/run_matrix.sh
