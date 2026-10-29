#!/bin/sh
# Replace sched-simple with fluxion on rank 0.  Two things both matter:
#   * remove sched-simple first, else both schedulers fight over the resource
#     acquisition ("Device or resource busy" / can't populate graph), and
#   * give fluxion-resource an explicit load-allowlist so it can populate its
#     graph from the enclosing instance's resource set.
# Selected purely via FLUX_RC_EXTRA -> no change to rhapsody source.

if [ "$(flux getattr rank)" = "0" ]; then
    flux module remove -f sched-simple
    flux module load sched-fluxion-resource  load-allowlist=node,core,gpu
    flux module load sched-fluxion-qmanager
fi
