#!/bin/bash
#SBATCH -N 32 -C cpu -q regular -t 02:00:00 -A m5290 -J rhap-bigP32
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/big-proxy-32.out
NODE_SCALES="32" WORKLOADS="d32 het" CELL_TIMEOUT=1800 bash /pscratch/sd/m/merzky/radical/bench/run_proxy.sh
