#!/bin/bash
#SBATCH -N 1 -C cpu -q debug -t 00:29:00 -A m5290 -J rhap-pxy1
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/pxy-N1.out
NODE_SCALES="1" bash /pscratch/sd/m/merzky/radical/bench/run_proxy.sh
