#!/bin/bash
# Stage 1: probes + reproduce + candidate fix.  Runs inside a 2-node salloc.
set +e
cd /pscratch/sd/m/merzky/radical/dragon-investigation
source ./env.sh >/dev/null 2>&1
export RHAPSODY_MP_LOGLEVEL=INFO
echo "=================================================================="
echo "JOB $SLURM_JOB_ID  nodes=$SLURM_NNODES  nodelist=$SLURM_NODELIST"
echo "python: $(which python)   dragon: $(which dragon)"
echo "=================================================================="

echo; echo "########## P1: plain python probe (no dragon launcher) ##########"
timeout 120 python probe.py plain 2>&1

echo; echo "########## P2: dragon python probe (models the host CHILD, default env) ##########"
timeout 180 dragon python probe.py under-dragon-default 2>&1
echo "[P2 exit=$?]"

echo; echo "########## P3: DRAGON_PATCH_MP='' dragon python probe (empty override) ##########"
DRAGON_PATCH_MP= timeout 180 dragon python probe.py under-dragon-empty 2>&1
echo "[P3 exit=$?]"

echo; echo "########## D1: rhapsody-dragon proxy, patch=on (REPRODUCE failure) ##########"
timeout 200 python dtest.py --nodes 2 --ntasks 20 --patch on --part-id dON 2>&1
echo "[D1 exit=$?]"
pkill -u "$USER" -f 'multiproc.host' 2>/dev/null; sleep 3

echo; echo "########## D2: rhapsody-dragon proxy, patch=off (CANDIDATE FIX) ##########"
timeout 240 python dtest.py --nodes 2 --ntasks 100 --patch off --part-id dOFF 2>&1
echo "[D2 exit=$?]"
pkill -u "$USER" -f 'multiproc.host' 2>/dev/null; sleep 3

echo; echo "########## D3: rhapsody-dragon proxy, patch=default (inherit) ##########"
timeout 200 python dtest.py --nodes 2 --ntasks 20 --patch default --part-id dDEF 2>&1
echo "[D3 exit=$?]"
pkill -u "$USER" -f 'multiproc.host' 2>/dev/null; sleep 2
echo; echo "=== runall1 DONE ==="
