#!/bin/bash
#SBATCH -N 1 -C cpu -q debug -t 00:29:00 -A m5290 -J rhap-rap1
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/rap-N1.out
NODE_SCALES="1" bash /pscratch/sd/m/merzky/radical/bench/run_raptor.sh
