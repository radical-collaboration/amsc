#!/bin/bash
# fluxion_modprobe.env.sh
#
# Select Fluxion (flux-sched 0.55.0) as the scheduler on a Slurm-bootstrapped,
# MULTI-NODE flux-core 0.89.0 instance that uses the new "modprobe" rc system.
#
# TESTED WORKING on Perlmutter, 2 nodes (-C cpu, -q interactive):
#   flux resource list -> 2 nodes / 256 cores, `flux run -n1 /bin/true` -> OK,
#   `flux run -N2 -n2 hostname` -> OK, no slurm-expiration-sync timeout.
#
# Usage:
#   source /pscratch/sd/m/merzky/radical/bench/env.sh
#   source /pscratch/sd/m/merzky/radical/bench/fluxion_modprobe.env.sh
#   srun --overlap -N<n> --ntasks=<n> --ntasks-per-node=1 flux start <cmd>
#
# WHY this works (and the old remove/reload approach did not):
#  * flux-core 0.89 bootstraps modules via `flux modprobe rc1`. Modprobe reads
#    modprobe.d/*.toml config and loads the highest-priority provider of each
#    service. flux-sched ships a modprobe config that declares
#    sched-fluxion-qmanager  provides=["sched"]      priority=500
#    sched-fluxion-feasibility provides=["feasibility"] priority=500
#    which OUTRANK the builtin sched-simple (priority=50). Modprobe then loads
#    fluxion instead of sched-simple, in the correct dependency order
#    (after "resource" / "job-manager"), with load-allowlist already set.
#  * BUT that flux-sched modprobe config lives under the flux-sched prefix,
#    which is NOT on modprobe's default search path (flux-core prefix only).
#    So we must add it with FLUX_MODPROBE_PATH_APPEND. That is the whole fix.
#  * We must NOT leave FLUX_RC_EXTRA pointing at the old fluxion_rc dir: the
#    final modprobe task (run-all-rc1) still runs classic rc1.d/* scripts, so a
#    remove-sched-simple + load-fluxion-resource script would run AFTER modprobe
#    already brought fluxion up and re-break the instance. We unset it here.

# Derive the flux-sched prefix from FLUX_MODULE_PATH (set by env.sh).
_fluxion_mods="$(echo "$FLUX_MODULE_PATH" | tr ':' '\n' | grep -m1 flux-sched)"
if [ -n "$_fluxion_mods" ]; then
    _fluxion_prefix="${_fluxion_mods%/lib/flux/modules}"
    export FLUX_MODPROBE_PATH_APPEND="$_fluxion_prefix/etc/flux/modprobe"
else
    echo "fluxion_modprobe.env.sh: WARNING: no flux-sched entry in FLUX_MODULE_PATH" >&2
fi
unset _fluxion_mods _fluxion_prefix

# Do not let the old classic-rc remove/reload script run under modprobe.
unset FLUX_RC_EXTRA

# Optional: override module args (defaults in fluxion.toml already fine).
# export FLUXION_RESOURCE_OPTIONS="load-allowlist=node,core,gpu"
# export FLUXION_QMANAGER_OPTIONS="queue-policy=easy"
