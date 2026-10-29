#!/bin/bash
#SBATCH -N 4 -C cpu -q debug -t 00:29:00 -A m5290 -J rhap-rap4
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/rap-N4.out
NODE_SCALES="4" bash /pscratch/sd/m/merzky/radical/bench/run_raptor.sh
