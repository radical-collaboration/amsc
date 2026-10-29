"""Workload definitions for the rhapsody scaling tests.

A *task spec* is ``(duration_seconds, n_cores)`` where ``n_cores`` counts
*physical* cores.  A workload is a list of task specs, weak-scaling with the
node count so a cell is comparable across 1/2/4/8 nodes.

This file is the declarative "what was run" the group reviews.
"""

from __future__ import annotations

import random

PHYS_CORES_PER_NODE = 128  # Perlmutter CPU node (physical)

# Per-node task counts, sized so every run reaches steady state (err long):
#   - launch-bound workloads (zero, short durations) get thousands of tasks
#   - duration-bound workloads get several waves of full-node occupancy
PER_NODE = {
    "zero": ("n", 4000, 0),    # (mode, count/node, duration) ; n = fixed count
    "d1":   ("n", 3000, 1),
    "d4":   ("w", 6, 4),       # w = waves of PHYS_CORES_PER_NODE 1-core tasks
    "d16":  ("w", 5, 16),
    "d32":  ("w", 4, 32),
}

# Heterogeneous mix, per node.  (n_cores, duration_s, count).  Dominated by
# small 1-core tasks and sized so total work (~3840 core-s/node) exceeds
# cores*longest-task (128*16), so the longest task never sets a makespan floor
# above the packed time: backfill fills the whole span -> util ~ homogeneous.
HET_PER_NODE = [
    (8, 16, 4),    # largest tasks (8 cores, 16 s)
    (4, 8, 16),
    (2, 4, 32),
    (1, 4, 128),
    (1, 2, 512),
    (1, 1, 1024),  # small-task backfill mass -> packs like homogeneous
]


def _simple(name: str, nodes: int) -> list[tuple[float, int]]:
    mode, val, dur = PER_NODE[name]
    if mode == "n":
        count = val * nodes
    else:  # waves
        count = val * PHYS_CORES_PER_NODE * nodes
    return [(dur, 1)] * count


def het(nodes: int, seed: int = 42) -> list[tuple[float, int]]:
    specs: list[tuple[float, int]] = []
    for cores, dur, count in HET_PER_NODE:
        specs += [(dur, cores)] * (count * nodes)
    random.Random(seed).shuffle(specs)  # identical queue for every scheduler
    return specs


WORKLOADS = {name: (lambda nodes, n=name: _simple(n, nodes)) for name in PER_NODE}
WORKLOADS["het"] = het

# Capped launch-bound variants for the proxy series: the RemoteBackendProxy
# relays per-task state over a socket, so we first measure its overhead with a
# fixed (non-scaling) task count instead of the full 4k/node & 3k/node sweeps.
PROXY_CAP = 4000
WORKLOADS["zero_c"] = lambda nodes: [(0, 1)] * PROXY_CAP
WORKLOADS["d1_c"] = lambda nodes: [(1, 1)] * PROXY_CAP
