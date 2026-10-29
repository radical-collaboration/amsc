# Rhapsody / Flux / Dragon scaling benchmarks — Perlmutter

All under `$SCRATCH` (purge-eligible): spack flux stack in `$SCRATCH/spack`,
repos + venv + this harness in `$SCRATCH/radical`.

## Environment
`source bench/env.sh` — NERSC python 3.13.15 venv (`ve.rh`, dragonhpc 0.14.1),
spack flux-core 0.89.0 (+systemd) & flux-sched 0.55.0, rhapsody @ `b5097bb`,
rhapsody_rm @ main. Physical cores = 128 / CPU node; utilization is vs physical.

## Backends compared
- `native-dragon`  — dragon Batch API directly (scheduled), no rhapsody.
- `native-flux`    — flux FluxExecutor directly, no rhapsody.
- `rhapsody-flux`  — rhapsody Session → FluxExecutionBackend.
- `rhapsody-dragon`— DEFERRED: dragon 0.14.1 monkeypatches
  `multiprocessing.connection.Client` (`_original_Client` is None) → the
  RemoteBackendProxy child cannot connect back. Not simple; native-dragon
  covers dragon throughput instead.

## Scheduler comparison (sched-simple vs fluxion) — fluxion DEFERRED
Single-node fluxion works. Multi-node fluxion under Slurm (flux-core 0.89 +
fluxion 0.55) fails at bringup:
- remove sched-simple + load fluxion-resource → `slurm-expiration-sync:
  Timed out waiting for resource-define event` (the slurm-sync module never
  sees fluxion emit resource-define; sched-simple does).
- leave sched-simple + reload fluxion → `can't populate graph resource
  database` / `Device or resource busy`.
Likely a flux-0.89/fluxion-0.55 + Slurm-bootstrap incompatibility. Needs
flux-ops follow-up (fluxion config under the modprobe rc system, a different
fluxion build, or disabling slurm-expiration-sync). All runs currently use
sched-simple.

## Running
- One cell: `python run_one.py --sched simple --nodes N --workload W --out DIR`
  (rhapsody-flux); native-flux via `srun … flux start python native_flux.py …`;
  native-dragon via `dragon python native_dragon.py …`.
- Matrix: `run_matrix.sh` (resumable: a cell with summary.json is skipped;
  continue-on-failure). Full matrix: `sbatch run_full.sbatch`.
- Aggregate: `python aggregate.py <results_dir>` → table + results.csv.

## Workloads (weak-scaling, per node)
zero (4000 0s tasks), d1 (3000 1s), d4/d16/d32 (waves of 1-core tasks),
het (mixed 1–16 core, 0–32s, with 16-core/32s blockers). Payload `taskrun`
(static C) busy-occupies its cores and records host/affinity/timestamps to a
node-local dir; gathered once per run.
