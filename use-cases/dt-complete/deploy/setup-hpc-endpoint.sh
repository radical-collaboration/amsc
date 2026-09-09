#!/usr/bin/env bash
# DTaaS HPC-endpoint venv for the dt-complete demo (e.g. Perlmutter).
# Run on a login node.
#
#   ./setup-hpc-endpoint.sh <broker-host>
#
# DT_DIR overrides where the digital.twins checkout + venv live
# (default: ~/digital_twins).
set -euo pipefail
BROKER="${1:?usage: $0 <broker-host>}"
DT_DIR="${DT_DIR:-$HOME/digital_twins}"

# same Python minor as every other host -- the service rejects skew, and
# exactly 3.12.0 breaks dragon's transport import (needs >= 3.12.1)
module load python/3.12 2>/dev/null || true

[ -d "$DT_DIR" ] || git clone https://github.com/radical-cybertools/digital.twins.git "$DT_DIR"
cd "$DT_DIR" && git checkout devel && git pull

./deploy/install.sh endpoint                              # pinned stack -> ./ve.demo
# sklearn/parquet task bodies unpickle and run here
./ve.demo/bin/pip install -q pandas scikit-learn pyarrow
# dragon backend; the branch carries the idempotent-cancel and
# failure-traceback fixes (pending upstream merge)
./ve.demo/bin/pip install -q --force-reinstall --no-deps \
  "rhapsody-py[telemetry,dragon] @ git+https://github.com/radical-cybertools/rhapsody@fix/dragon-cancel-idempotent"

mkdir -p ~/.radical/orbit
scp "$BROKER:.radical/orbit/broker_cert.pem" "$BROKER:.radical/orbit/broker.token" ~/.radical/orbit/

echo "done.  get an allocation (e.g. salloc -N1 -C cpu -q interactive -t 2:00:00 -A <account>),"
echo "then run:  run-hpc-endpoint.sh $BROKER"
