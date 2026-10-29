# Single source of truth for the benchmark environment.
#   source this before compiling or running anything in bench/.
#
# Everything lives under $SCRATCH (purge-eligible, fine for these runs).

BENCH=$SCRATCH/radical/bench

# --- python + rhapsody stack ------------------------------------------------
module load python                                   # NERSC python 3.13.15
source "$SCRATCH/radical/ve.rh/bin/activate"         # dragonhpc 0.14.1 venv
export PYTHONPATH="$SCRATCH/radical/rhapsody/src:$SCRATCH/radical/rhapsody_rm/src"

# --- flux (spack) + fluxion -------------------------------------------------
# Wire flux by hand rather than `spack load`: the latter drags spack's own
# python into the environment and shadows the venv.  flux-core is built with
# RPATH to its deps, so bin + python-bindings + module path is enough.
export SPACK_ROOT=$SCRATCH/spack
source "$SPACK_ROOT/share/spack/setup-env.sh"        # defines `spack`, leaves python alone
FLUX_CORE=$(spack location -i flux-core@0.89.0)
FLUXION=$(spack location -i flux-sched@0.55.0)
export PATH="$FLUX_CORE/bin:$PATH"
export PYTHONPATH="$PYTHONPATH:$FLUX_CORE/lib/python3.13/site-packages"
export FLUX_MODULE_PATH="$FLUXION/lib/flux/modules:$FLUX_CORE/lib/flux/modules"

# flux runs its rc scripts under spack's own python (not our venv); expose the
# venv site-packages on PYTHONPATH so that interpreter also finds cffi / ply /
# jsonschema / pyyaml (same 3.13.15 ABI).  Without this the brokers die with
# "No module named '_cffi_backend'".
export PYTHONPATH="$PYTHONPATH:$SCRATCH/radical/ve.rh/lib/python3.13/site-packages"

# --- the compiled payload ---------------------------------------------------
export RHAP_TASKRUN=$BENCH/taskrun

# srun must forward our env (FLUX_*, PYTHONPATH, ...) to the compute nodes
export SLURM_EXPORT_ENV=ALL
