#!/bin/bash
#SBATCH -N 8 -C cpu -q regular -t 03:00:00 -A m5290 -J rhap-pxy8
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/pxy-N8b.out
NODE_SCALES="8" bash /pscratch/sd/m/merzky/radical/bench/run_proxy.sh
