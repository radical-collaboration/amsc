#!/bin/bash
#SBATCH -N 128 -C cpu -q regular -t 02:00:00 -A m5290 -J rhap-rapBig
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/rap-big.out
NODE_SCALES="32 128" WORKLOADS="zero d1 d4 d16 d32 het" CELL_TIMEOUT=1800 \
  bash /pscratch/sd/m/merzky/radical/bench/run_raptor.sh
