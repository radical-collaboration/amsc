# Environment for the flux-function prototype: base bench env, but the PATCHED
# rhapsody clone (function->flux wrapper) takes precedence, plus the payload dir.
source /pscratch/sd/m/merzky/radical/bench/env.sh
export PYTHONPATH=/pscratch/sd/m/merzky/radical/rhapsody-fnflux/src:/pscratch/sd/m/merzky/radical/bench/fn:/pscratch/sd/m/merzky/radical/bench:$PYTHONPATH
export RHAP_FN_WRAPPER=/pscratch/sd/m/merzky/radical/bench/fn/flux_fn_wrapper.py
