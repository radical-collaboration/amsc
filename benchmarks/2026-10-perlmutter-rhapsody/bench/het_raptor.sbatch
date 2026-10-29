#!/bin/bash
#SBATCH -N 8 -C cpu -q regular -t 01:00:00 -A m5290 -J rhap-hetR
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/het-raptor.out
NODE_SCALES="1 2 4 8" WORKLOADS="het" bash /pscratch/sd/m/merzky/radical/bench/run_raptor.sh
