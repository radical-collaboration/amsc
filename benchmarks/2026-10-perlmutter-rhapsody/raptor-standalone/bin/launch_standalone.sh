#!/bin/bash
# Launch the standalone (pilot-free) raptor master + srun workers by hand,
# WITHOUT the rhapsody backend -- the raw Milestone-2 path.
#
# Run this from inside a Slurm allocation (salloc/sbatch).  It starts the
# master (via tests/driver.py) which writes the info file, then the driver
# itself can either spawn workers or you launch them with srun separately.
#
# This helper demonstrates the fully manual split: master in one process,
# workers via an explicit srun step reading the same info file.
#
# Usage:  bin/launch_standalone.sh <workdir> <nworkers> <nslots> <ntasks> <bulk>

set -eux
source /pscratch/sd/m/merzky/radical/raptor-standalone/bin/env.sh

WORKDIR=${1:-$SCRATCH/raptor_sa_manual}
NWORKERS=${2:-2}
NSLOTS=${3:-64}
NTASKS=${4:-100}
BULK=${5:-8}
TR=/pscratch/sd/m/merzky/radical/bench/taskrun

mkdir -p $WORKDIR
INFO=$WORKDIR/raptor.master.json
rm -f $INFO

# 1) start master + driver in the background; it will wait for $NWORKERS
$PYTHON /pscratch/sd/m/merzky/radical/raptor-standalone/tests/driver.py \
    --workdir $WORKDIR --ntasks $NTASKS --workers $NWORKERS \
    --bulk $BULK --nslots $NSLOTS --exe $TR --dur 0 \
    --outdir $WORKDIR/task_out &
DRIVER_PID=$!

# 2) wait for the master to publish its info file
for i in $(seq 1 300); do [ -f "$INFO" ] && break; sleep 0.2; done

# 3) launch the workers via srun across the allocation (one per node)
srun --overlap --nodes=$NWORKERS --ntasks=$NWORKERS --ntasks-per-node=1 \
     --cpu-bind=none \
     $PYTHON -m raptor_standalone.worker --info $INFO --nslots $NSLOTS --prefetch 4 &
SRUN_PID=$!

# 4) wait for the driver to finish (it submits, waits, reports, terminates)
wait $DRIVER_PID
# workers exit on the terminate broadcast; reap the srun step
wait $SRUN_PID 2>/dev/null || true
echo "manual standalone run complete; see $WORKDIR/summary.json"
