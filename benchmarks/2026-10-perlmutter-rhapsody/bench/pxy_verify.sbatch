#!/bin/bash
#SBATCH -N 2 -C cpu -q debug -t 00:25:00 -A m5290 -J rhap-pxyv
#SBATCH -o /pscratch/sd/m/merzky/radical/bench/pxy-verify.out
cd /pscratch/sd/m/merzky/radical/bench
source /pscratch/sd/m/merzky/radical/dragon-investigation/env.sh
export SLURM_CPUS_ON_NODE=$(srun -N1 --ntasks=1 --overlap bash -c 'printf %s "$SLURM_CPUS_ON_NODE"')
out=/pscratch/sd/m/merzky/radical/bench/results/pxy-verify/rhapsody-dragon-proxy-dragon-d32-N2
mkdir -p "$out"
echo "which rhapsody: $(python -c 'import rhapsody,os;print(os.path.dirname(rhapsody.__file__))')"
timeout 500 python rhapsody_dragon_proxy.py --nodes 2 --workload d32 --out "$out"
echo "verify rc=$?"
