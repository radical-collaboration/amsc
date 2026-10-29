#!/bin/bash
#SBATCH -N 2 -C cpu -q debug -t 00:29:00 -A m5290 -J rhap-rap2
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/rap-N2.out
NODE_SCALES="2" bash /pscratch/sd/m/merzky/radical/bench/run_raptor.sh
