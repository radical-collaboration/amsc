#!/bin/bash
#SBATCH -N 8 -C cpu -q regular -t 02:00:00 -A m5290 -J rhap-rap8
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/rap-N8.out
NODE_SCALES="8" bash /pscratch/sd/m/merzky/radical/bench/run_raptor.sh
