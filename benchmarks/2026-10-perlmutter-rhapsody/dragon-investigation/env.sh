# Investigation env: identical stack to bench/env.sh, but PYTHONPATH points at
# the FRESH clones under dragon-investigation (never the in-use checkouts).
DI=/pscratch/sd/m/merzky/radical/dragon-investigation

module load python
source /pscratch/sd/m/merzky/radical/ve.rh/bin/activate      # dragonhpc 0.14.1 venv

# flux (spack), wired by hand (same as bench/env.sh)
export SPACK_ROOT=/pscratch/sd/m/merzky/spack
source "$SPACK_ROOT/share/spack/setup-env.sh"
FLUX_CORE=$(spack location -i flux-core@0.89.0)
FLUXION=$(spack location -i flux-sched@0.55.0)
export PATH="$FLUX_CORE/bin:$PATH"
export FLUX_MODULE_PATH="$FLUXION/lib/flux/modules:$FLUX_CORE/lib/flux/modules"

# PYTHONPATH: MY clones first, then flux bindings, then venv site-packages
VENV_SITE=/pscratch/sd/m/merzky/radical/ve.rh/lib/python3.13/site-packages
export PYTHONPATH="$DI/rhapsody/src:$DI/rhapsody_rm/src:$FLUX_CORE/lib/python3.13/site-packages:$VENV_SITE"

export RHAP_TASKRUN=/pscratch/sd/m/merzky/radical/bench/taskrun
export SLURM_EXPORT_ENV=ALL
