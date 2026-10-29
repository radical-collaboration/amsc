#!/bin/bash
#SBATCH -N 4 -C cpu -q regular -t 02:00:00 -A m5290 -J rhap-pxy4
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/pxy-N4r.out
NODE_SCALES="4" bash /pscratch/sd/m/merzky/radical/bench/run_proxy.sh
