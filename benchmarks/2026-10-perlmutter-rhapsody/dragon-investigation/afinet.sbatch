#!/bin/bash
#SBATCH -N 4 -C cpu -q debug -t 00:30:00 -A m5290 -J dragon-inv
#SBATCH -o /pscratch/sd/m/merzky/radical/dragon-investigation/afinet.log
set +e
cd /pscratch/sd/m/merzky/radical/dragon-investigation
source ./env.sh >/dev/null 2>&1            # ve.rh = dragon 0.14.1 runtime (read-only), patched clone on PYTHONPATH
export RHAPSODY_MP_LOGLEVEL=INFO
if [ -z "${SLURM_CPUS_ON_NODE:-}" ]; then
  export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"' 2>/dev/null)
fi
echo "=== AF_INET proxy on dragon $(python -c 'from dragon.version import __version__ as v;print(v)') | head=$(hostname) nodelist=$SLURM_NODELIST ==="

run () {  # $1=nodes $2=tag $3=portoffset
  echo "----- $2 : dtest --nodes $1 --ntasks 100 --shim shimhost (port-offset $3) -----"
  timeout -k 20 240 python dtest.py --nodes "$1" --ntasks 100 --patch default \
      --shim shimhost --port-offset "$3" --part-id "$2" --timeout 200 2>&1 \
      | grep -E 'driver host|shimhost\] running|Client restored|proxy READY|RESULT|FileNotFoundError|TypeError|Traceback'
  echo "[$2 exit=$?]"
  pkill -u "$USER" -f 'multiproc.host' 2>/dev/null; pkill -u "$USER" -f 'shimhost' 2>/dev/null
  pkill -u "$USER" -x dragon 2>/dev/null; sleep 6
}

echo; echo "########## 2-node partition x3 ##########"
run 2 n2a 0
run 2 n2b 100
run 2 n2c 200

echo; echo "########## 4-node partition x3 (head often NOT co-located with driver) ##########"
run 4 n4a 300
run 4 n4b 400
run 4 n4c 500

echo; echo "=== afinet DONE ==="
