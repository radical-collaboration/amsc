#!/bin/bash
# All four node scales in one 8-node allocation (an N-node cell uses the first
# N nodes). About 27 min of cell time expected from the via-rhapsody runs.
#SBATCH -N 8 -C cpu -q regular -t 01:00:00 -A amsc007 -J rapn-matrix
#SBATCH -o /pscratch/sd/m/merzky/radical/raptor-native/matrix.out
NODE_SCALES="1 2 4 8" bash /pscratch/sd/m/merzky/radical/raptor-native/run_raptor_native.sh
