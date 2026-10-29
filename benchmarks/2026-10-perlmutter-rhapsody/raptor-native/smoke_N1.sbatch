#!/bin/bash
#SBATCH -N 1 -C cpu -q debug -t 00:30:00 -A amsc007 -J rapn-smoke
#SBATCH -o /pscratch/sd/m/merzky/radical/raptor-native/smoke-N1.out
RESULTS=/pscratch/sd/m/merzky/radical/raptor-native/results/smoke \
NODE_SCALES="1" WORKLOADS="zero" bash /pscratch/sd/m/merzky/radical/raptor-native/run_raptor_native.sh
