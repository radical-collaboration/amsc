#!/bin/bash
#SBATCH -N 8 -C cpu -q regular -t 01:30:00 -A m5290 -J rhap-hetP
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/het-proxy.out
NODE_SCALES="1 2 4 8" WORKLOADS="het" bash /pscratch/sd/m/merzky/radical/bench/run_proxy.sh
