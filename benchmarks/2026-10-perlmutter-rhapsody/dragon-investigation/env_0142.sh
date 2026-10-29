# ISOLATED env for dragonhpc 0.14.2 test. Uses the fresh ve.0142 venv.
# Leaves the in-use ve.rh venv and checkouts completely untouched.
DI=/pscratch/sd/m/merzky/radical/dragon-investigation
module load python
source "$DI/ve.0142/bin/activate"                       # dragonhpc 0.14.2 venv
VENV_SITE="$DI/ve.0142/lib/python3.13/site-packages"
export PYTHONPATH="$DI/rhapsody/src:$DI/rhapsody_rm/src:$VENV_SITE"
export RHAP_TASKRUN=/pscratch/sd/m/merzky/radical/bench/taskrun
export SLURM_EXPORT_ENV=ALL
