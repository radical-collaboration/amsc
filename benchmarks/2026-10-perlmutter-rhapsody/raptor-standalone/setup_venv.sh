#!/bin/bash
set -e
module load python/3.13-26.8.1
cd /pscratch/sd/m/merzky/radical/raptor-standalone
python -m venv ve.raptor
source ve.raptor/bin/activate
python -m pip install --upgrade pip wheel setuptools
# download sources (not the in-use venv) + install into our own venv
python -m pip install radical.pilot radical.utils pyzmq msgpack
echo "=== versions ==="
python -c "import radical.pilot as rp, radical.utils as ru; print('rp', rp.version); print('ru', ru.version)"
echo "DONE_SETUP"
