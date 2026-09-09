#!/usr/bin/env bash
# DTaaS broker host for the dt-complete demo (e.g. radical.3).  Run there.
#
# Once per host, before the first run: broker_cert.pem, broker_key.pem and
# broker.token in ~/.radical/orbit/.  DT_DIR overrides where the
# digital.twins checkout + venv live (default: ~/digital_twins).
set -euo pipefail
DT_DIR="${DT_DIR:-$HOME/digital_twins}"

[ -d "$DT_DIR" ] || git clone https://github.com/radical-cybertools/digital.twins.git "$DT_DIR"
cd "$DT_DIR" && git checkout devel && git pull

./deploy/install.sh broker                                # pinned stack -> ./ve.demo
# the M3DC1 investigator instantiates on the broker and imports these
./ve.demo/bin/pip install -q pandas scikit-learn pyarrow

echo "done.  start the broker with:"
echo "  cd $DT_DIR && ./deploy/run-broker.sh \$PWD/ve.demo"
