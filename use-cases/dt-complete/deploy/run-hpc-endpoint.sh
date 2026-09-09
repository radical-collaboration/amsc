#!/usr/bin/env bash
# Run the demo's HPC endpoint -- INSIDE a compute allocation.
#
#   ./run-hpc-endpoint.sh <broker-host>
#
# The endpoint is launched via the ``dragon`` launcher: rhapsody's dragon
# backend drives Dragon's Batch API, which only works inside a
# Dragon-launched process tree.  DT_DIR as in setup-hpc-endpoint.sh.
set -euo pipefail
BROKER="${1:?usage: $0 <broker-host>}"
DT_DIR="${DT_DIR:-$HOME/digital_twins}"
VENV="$DT_DIR/ve.demo"

# dragon resolves its helpers BY NAME through srun on the task side
export PATH="$VENV/bin:$PATH"
export RADICAL_ORBIT_BROKER_URL="wss://$BROKER:8000"
export RADICAL_ORBIT_BROKER_CERT="$HOME/.radical/orbit/broker_cert.pem"
export RADICAL_ORBIT_RHAPSODY_BACKEND=dragon_v3
export RADICAL_ORBIT_RHAPSODY_NOTIFY_WINDOW=0
export SLURM_EXPORT_ENV=ALL          # inner sruns must not scrub the env
export DT_STREAM_BACKEND=orbit
export DT_ENDPOINT_TAG=hpc
# training snapshots belong on scratch where available
export M3DC1_WORKSPACE="${M3DC1_WORKSPACE:-${SCRATCH:-$HOME}/m3dc1_workspace}"

exec "$VENV/bin/dragon" "$VENV/bin/radical-orbit-endpoint.py" -n hpc \
    2>&1 | tee endpoint.log
