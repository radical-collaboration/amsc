#!/bin/bash
#SBATCH -A m5290
#SBATCH -C cpu
#SBATCH -q debug
#SBATCH -N 2
#SBATCH -t 00:10:00
#SBATCH -J raptor-sa-smoke
#SBATCH -o /pscratch/sd/m/merzky/radical/raptor-standalone/results/smoke_%j.out
#SBATCH -e /pscratch/sd/m/merzky/radical/raptor-standalone/results/smoke_%j.err

set -x
source /pscratch/sd/m/merzky/radical/raptor-standalone/bin/env.sh
RES=/pscratch/sd/m/merzky/radical/raptor-standalone/results/smoke_$SLURM_JOB_ID
mkdir -p $RES
TR=/pscratch/sd/m/merzky/radical/bench/taskrun

echo "=== allocation: $SLURM_JOB_NODELIST nodes=$SLURM_NNODES ==="
scontrol show hostnames $SLURM_JOB_NODELIST

# M2+M3 multi-node pilot-free validation: 100 taskrun tasks across 2 nodes.
# Backend launch mode -> workers bootstrap via ZMQ addresses baked into the
# srun argv (NO shared-FS info file read).
$PYTHON /pscratch/sd/m/merzky/radical/raptor-standalone/tests/test_m3_rhapsody.py \
    --workdir $RES/m3 --ntasks 100 --workers 2 \
    --nslots 64 --bulk 8 --taskrun $TR --dur 0

echo "=== worker bootstrap mode (expect 'bootstrap via argv', no info-file read) ==="
grep -E "bootstrap via|up:|exiting" $RES/m3/workers.log 2>/dev/null | head

echo "=== check which nodes ran tasks ==="
$PYTHON -c "
import glob,json
hosts={}
for f in glob.glob('$RES/m3/task_out/*.json'):
    try: r=json.load(open(f))
    except: continue
    hosts[r['host']]=hosts.get(r['host'],0)+1
print('tasks per host:', hosts)
print('distinct nodes:', len(hosts))
"
echo "=== SMOKE DONE ==="
