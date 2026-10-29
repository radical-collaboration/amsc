# RHAPSODY / Flux / Dragon / Raptor scaling benchmarks on Perlmutter (2026-10)

Scripts, configuration and result summaries of the RHAPSODY scaling study on
Perlmutter CPU nodes (1-128 nodes), run 2026-10-18 to 2026-10-22 (result directory dates). The results
are summarized in the live report
<https://claude.ai/artifact/5EKu75xWxrfjzTkk81g8ny> (access-restricted).

Parked here so the material survives the scratch purge. It is a copy of
`/pscratch/sd/m/merzky/radical/{bench,raptor-standalone,raptor-standalone-fn,dragon-investigation}`
as of 2026-10-28, not a maintained harness: the scripts hard-code those
`/pscratch/sd/m/merzky/...` paths and have not been made relocatable.

## Stack

| Piece | Version |
|---|---|
| Python | NERSC `python` module 3.13.15, venv `ve.rh` |
| Dragon | `dragonhpc` 0.14.1 |
| Flux | flux-core 0.89.0 (+systemd), flux-sched 0.55.0, from spack in `$SCRATCH/spack`; scheduler `sched-simple` (fluxion deferred, see `bench/NOTES.md`) |
| RHAPSODY | `radical-cybertools/rhapsody` `b5097bb` (`feature/flux`), plus the uncommitted edits in `patches/` |
| rhapsody_rm | `radical-cybertools/rhapsody_rm` `b751f42` (`main`) |

## Backends compared

- **native-flux:** flux `FluxExecutor` directly (`bench/native_flux.py`).
- **native-dragon:** the dragon Batch API directly (`bench/native_dragon.py`).
- **rhapsody-flux:** RHAPSODY Session with the flux backend (`bench/run_one.py`).
- **rhapsody-dragon:** RHAPSODY Session with the in-process dragon backend,
  run under the dragon launcher (`bench/rhapsody_dragon.py`).
- **rhapsody-dragon-proxy:** the dragon backend hosted out of process via
  `RemoteBackendProxy` (`bench/rhapsody_dragon_proxy.py`).
- **raptor:** standalone, pilot-free Raptor **driven through a RHAPSODY
  Session** by a custom backend, `RaptorStandaloneBackend`
  (`raptor-standalone/raptor_standalone/rhapsody_backend.py`): a
  `RaptorMaster` plus `srun`-launched workers, with no RADICAL-Pilot session,
  pilot, agent or MongoDB. Matrix cells: `bench/run_raptor.sh` →
  `bench/raptor_one.py`. The native-Raptor baseline (no RHAPSODY) was added
  later in `raptor-native/`.

## Layout

- `bench/`: the main harness.
  - `NOTES.md`: the harness's original notes (environment, workloads, the
    fluxion problem). Written early; it still lists rhapsody-dragon as
    deferred, which later runs superseded.
  - `common.py`, `workloads.py`: shared code and workload definitions.
    Workloads are weak-scaling per node: `zero` (4000 tasks of 0 s), `d1`
    (3000 tasks of 1 s), `d4`/`d16`/`d32` (waves of 1-core tasks), `het`
    (mixed 1-16 cores, 0-32 s, with 16-core/32 s blockers).
  - `taskrun.c`: the static C payload that busy-occupies its cores and
    records host, affinity and timestamps. Build it with a static `cc`; the
    binary is not committed.
  - Matrix drivers: `run_matrix.sh`, `run_raptor.sh`, `run_proxy.sh`,
    `repeat_driver.sh` and the `*.sbatch` job files (`big_*`, `het_*`,
    `pxy_*`, `mix_*`).
  - Co-location: `run_split.py` / `run_split2x2.sh` (native dragon and flux
    on disjoint partitions), `run_mix.py` (one Session driving a dragon and
    a flux partition).
  - `fn/`: function-dispatch throughput (`fn_dragon.py`, `fn_flux.py`,
    `fn_raptor.py`, `fn_recon.py`) and `dragon-throughput-plan.md`.
    `libspin.so` is not committed.
  - `aggregate.py`: turns a results directory into a table and
    `results.csv`. `report_data.json` and `split_data.json` are the data
    behind the live report.
  - `results/`: one directory per cell with `summary.json` and `run.log`,
    plus the `results.csv` files; `*.out` are the Slurm job logs.
- `raptor-standalone/`: the pilot-free Raptor (`raptor_standalone/`), its
  RHAPSODY backend, launch and job scripts (`bin/`), tests and benchmark
  drivers (`tests/`) and milestone results (`results/`).
  - `variants/fn/`: the two files that differ in the function-dispatch copy
    (`raptor-standalone-fn/` on scratch): `rhapsody_backend.py` and
    `worker.py`.
- `raptor-native/`: the same Raptor cells driven directly, without RHAPSODY
  (2026-10-28, nodes 1-8), with a native vs via-RHAPSODY comparison.
- `dragon-investigation/`: the debugging of rhapsody-dragon on multiple
  nodes (the dragon `multiprocessing` monkeypatch vs. `RemoteBackendProxy`,
  and the 2+2 dragon/flux split). Its nested `rhapsody` copy was at
  `b5097bb` with the edits in `patches/dragon-investigation-rhapsody.diff`;
  its `rhapsody_rm` copy was clean at `b751f42`.
- `patches/`: uncommitted RHAPSODY edits some runs used, as `git diff`
  against `b5097bb`:
  - `rhapsody.diff`: the main checkout (flux helper).
  - `rhapsody-fnflux.diff`: flux function dispatch.
  - `rhapsody-chunk2.diff`: chunked submission (flux helper, dragon backend).
  - `dragon-investigation-rhapsody.diff`: see above.

## Not included

- Per-task data: `results/**/records/`, function payloads (`blobs/*.pkl`,
  about 37,000 files), `runinfo/`, the `rhapsody.session.*` directories.
- Binaries and environments: `taskrun`, `libspin.so`, the venvs, `__pycache__`.
- The nested `rhapsody` and `rhapsody_rm` copies in `dragon-investigation/`
  (recorded above by commit plus patch).

These stay on Perlmutter scratch until it is purged.
