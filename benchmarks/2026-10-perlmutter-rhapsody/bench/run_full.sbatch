#!/bin/bash
#SBATCH -N 8
#SBATCH -C cpu
#SBATCH -q regular
#SBATCH -t 10:00:00
#SBATCH -A m5290
#SBATCH -J rhap-matrix
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/matrix-full.out
# Full scaling matrix: node scales {1,2,4,8} x 5 backend/sched x 6 workloads.
# Resumable into the same RESULTS dir; re-submit this script to continue.
export RESULTS=/pscratch/sd/m/merzky/radical/bench/results/matrix-full
# fluxion deferred: flux-0.89 + fluxion-0.55 under Slurm hits a
# slurm-expiration-sync "resource-define" timeout (documented in NOTES.md).
export COMBOS="native-dragon:dragon native-flux:simple rhapsody-flux:simple"
NODE_SCALES="1 2 4 8" CELL_TIMEOUT=1800 \
  bash /pscratch/sd/m/merzky/radical/bench/run_matrix.sh
