#!/bin/bash
set -e

module load conda
. ~/MATEY/prep

cd ~/MATEY/examples
export PYTHONPATH="${PYTHONPATH}:$HOME/MATEY"
export MASTER_ADDR=$(hostname -i)
export MASTER_PORT=$(python -c 'import socket; s=socket.socket(); s.bind(("", 0)); print(s.getsockname()[1]); s.close()')

exec "$@"
