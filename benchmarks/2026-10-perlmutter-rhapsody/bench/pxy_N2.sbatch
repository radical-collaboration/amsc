#!/bin/bash
#SBATCH -N 2 -C cpu -q debug -t 00:29:00 -A m5290 -J rhap-pxy2
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/pxy-N2.out
NODE_SCALES="2" bash /pscratch/sd/m/merzky/radical/bench/run_proxy.sh
