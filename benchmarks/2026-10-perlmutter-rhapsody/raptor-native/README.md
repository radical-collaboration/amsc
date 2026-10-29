# Raptor without RHAPSODY: native baseline (2026-10-28)

The `raptor` cells of the main study (`../bench/results/matrix-full/raptor-raptor-*`)
drove Raptor through a RHAPSODY Session
(`RaptorStandaloneBackend`). This directory adds the missing baseline: the
same Raptor, workloads and payload, driven directly with no `rhapsody` import
and no Session.

## What ran

`raptor_native_one.py` reproduces what `RaptorStandaloneBackend` plus
`bench/raptor_one.py` do, minus the RHAPSODY layer:

- `RaptorMaster(workdir, bulk_size=16)`;
- workers started with the backend's exact `srun` line (`--nodes=N --ntasks=N
  --ntasks-per-node=1 --cpu-bind=none --overlap`, `--nslots 128 --prefetch 4`,
  addresses passed on argv);
- `wait_workers(N, 180)`, counted in `bringup_s` as in `raptor_one.py`;
- the task dicts `build_task` produces (`cores=1`, no env, timeout or sandbox),
  all handed to one `master.submit()` call, then `master.wait(timeout=1800)`;
- teardown is `master.terminate()` plus a 20 s wait on the `srun` step,
  matching `backend.shutdown()`.

Workloads (`zero d1 d4 d16 d32 het`, weak scaling) and helpers come from
`../bench/workloads.py` and `../bench/common.py`, imported read-only from
scratch. `raptor_standalone/` was not modified.

`summary.json` follows the post-processed raptor summaries in
`matrix-full`. It holds the `common.analyse` fields plus `*_e2e` (the
driver-measured makespan) and `*_record` (`max(t_end) - min(t_start)` over the
task records). `throughput_overall` and `utilization` are the record-based
values. The script that added these fields to the `matrix-full` summaries was
not kept; this definition reproduces their stored values. `backend` is
`raptor-native`, and native cells also record `n_failed`.

## Stack

Same as the via-RHAPSODY raptor cells: NERSC `python/3.13-26.8.1`, venv
`raptor-standalone/ve.raptor`, `raptor_standalone` as committed in
`../raptor-standalone/` (identical to the scratch copy), and the static
`taskrun` payload. Perlmutter CPU nodes, 128 physical cores per node.

## Commands and jobs

All of it ran under `/pscratch/sd/m/merzky/radical/raptor-native/`.

| Job | sbatch | What |
|---|---|---|
| 60474417 | `smoke_N1.sbatch` (debug, 1 node) | smoke test: zero, N1 (`results/smoke/`, `smoke-N1.out`) |
| 60474463 | `matrix.sbatch` (regular, 8 nodes, 1 h; 35:49 used) | nodes 1, 2, 4, 8 x all six workloads (`results/matrix/`, `matrix.out`) |

Account `amsc007`, `-C cpu`. `run_raptor_native.sh` is the resumable cell
loop: same environment, `RHAP_TASKRUN` and 1500 s cell timeout as
`bench/run_raptor.sh`. Comparison:

    python compare.py results/matrix \
        /pscratch/sd/m/merzky/radical/bench/results/matrix-full \
        results/raptor-native-vs-rhapsody.csv

## Results

All 24 native cells completed (rc=0, every task DONE, none failed).
Throughput is record-based, in tasks/s; utilization is against physical cores.
"rh" is the via-RHAPSODY cell. Teardown is 2.00 s on both sides in every cell.

| workload | N | tasks | thr nat | thr rh | nat/rh | util nat | util rh | bringup s nat | bringup s rh |
|---|---|---|---|---|---|---|---|---|---|
| zero | 1 | 4000 | 909.5 | 905.0 | 1.00 | 0.0% | 0.0% | 14.43 | 14.11 |
| zero | 2 | 8000 | 1593.8 | 1568.9 | 1.02 | 0.0% | 0.0% | 15.07 | 17.51 |
| zero | 4 | 16000 | 1583.8 | 1575.0 | 1.01 | 0.0% | 0.0% | 17.52 | 14.51 |
| zero | 8 | 32000 | 1572.9 | 1564.5 | 1.01 | 0.0% | 0.0% | 17.28 | 15.12 |
| d1 | 1 | 3000 | 123.3 | 123.3 | 1.00 | 96.4% | 96.4% | 14.47 | 14.09 |
| d1 | 2 | 6000 | 246.7 | 247.1 | 1.00 | 96.4% | 96.5% | 14.68 | 13.95 |
| d1 | 4 | 12000 | 493.8 | 494.0 | 1.00 | 96.4% | 96.5% | 14.91 | 14.10 |
| d1 | 8 | 24000 | 986.4 | 982.2 | 1.00 | 96.3% | 95.9% | 15.71 | 14.08 |
| d4 | 1 | 768 | 31.6 | 31.6 | 1.00 | 98.9% | 98.6% | 14.19 | 13.88 |
| d4 | 2 | 1536 | 54.5 | 54.6 | 1.00 | 85.2% | 85.3% | 14.66 | 14.10 |
| d4 | 4 | 3072 | 109.4 | 109.4 | 1.00 | 85.5% | 85.5% | 14.65 | 13.90 |
| d4 | 8 | 6144 | 218.6 | 218.7 | 1.00 | 85.4% | 85.4% | 15.56 | 14.52 |
| d16 | 1 | 640 | 8.0 | 8.0 | 1.00 | 99.6% | 99.7% | 14.28 | 13.89 |
| d16 | 2 | 1280 | 13.3 | 15.9 | 0.84 | 83.2% | 99.6% | 14.78 | 13.89 |
| d16 | 4 | 2560 | 31.9 | 31.9 | 1.00 | 99.5% | 99.5% | 14.69 | 13.92 |
| d16 | 8 | 5120 | 63.5 | 63.5 | 1.00 | 99.2% | 99.2% | 14.89 | 14.08 |
| d32 | 1 | 512 | 4.0 | 4.0 | 1.00 | 99.8% | 99.7% | 14.92 | 13.87 |
| d32 | 2 | 1024 | 8.0 | 8.0 | 1.00 | 99.8% | 99.7% | 14.69 | 14.52 |
| d32 | 4 | 2048 | 16.0 | 16.0 | 1.00 | 99.7% | 99.7% | 16.16 | 13.90 |
| d32 | 8 | 4096 | 31.8 | 31.8 | 1.00 | 99.5% | 99.5% | 15.54 | 14.16 |
| het | 1 | 1716 | 50.1 | 50.0 | 1.00 | 87.6% | 87.5% | 14.18 | 14.12 |
| het | 2 | 3432 | 94.9 | 94.8 | 1.00 | 82.9% | 82.8% | 15.52 | 14.31 |
| het | 4 | 6864 | 185.1 | 185.0 | 1.00 | 80.9% | 80.9% | 14.98 | 14.32 |
| het | 8 | 13728 | 368.6 | 366.5 | 1.01 | 80.6% | 80.1% | 15.31 | 14.29 |

`results/raptor-native-vs-rhapsody.csv` has the full set: both sides' counts,
bringup, teardown, makespan, record, e2e and steady throughput, utilization,
and the native/rhapsody ratios.

**Reading.** The RHAPSODY layer costs Raptor next to nothing. Throughput and
utilization agree within 2% in 23 of 24 cells, with native at most 1.6%
ahead (zero, the launch-bound case: about 1,570-1,590 tasks/s against about
1,565-1,575 tasks/s). Bringup is about 14-17 s on both sides; it is `srun`
plus worker start and registration, and RHAPSODY adds nothing measurable.
Native bringup actually came out about 0.5-1 s *higher* on average, which is
run-to-run noise.

## Caveats

- Single runs per cell on each side, on different days and node sets. The
  via-RHAPSODY cells came from separate per-N jobs (`bench/rap_N*.sbatch`,
  account `m5290`). Here all four scales ran in one 8-node allocation, with
  an N-node cell using the first N nodes.
- **d16-N2 native (83% against 99.6%) is a Raptor load-balancing outlier, not
  a native cost.** The two workers received 656 and 624 tasks instead of 640
  each. One extra 16-task bulk (`bulk_size=16`) gave one worker a sixth 16 s
  wave, stretching the makespan from about 80 s to 96 s. The same bulk-level
  imbalance explains the about 85% d4 utilization at N≥2 *in both stacks*:
  workers get 752 or 784 tasks (768 ideal), so half of them run a seventh
  4 s wave. Request distribution in bulks of 16 with prefetch 4 is
  pull-based and not exactly fair. A smaller `bulk_size` or prefetch, or
  workload sizes that are multiples of `nworkers x bulk_size` per wave,
  would remove it.
- Raptor ignores task core counts: `build_task` defaults `cores=1` when no
  backend kwargs are given, and the worker runs any task in one slot. In
  `het`, a 4- or 8-core task therefore takes one of 128 slots, while
  `taskrun` busy-occupies its N cores and the records count `ncores`. Both
  stacks behave the same here, so the comparison holds, but het numbers are
  not comparable to core-aware schedulers.
- `bench/results/matrix-full/raptor-raptor-d32-N2/summary.json` was never
  post-processed. It lacks the `*_e2e`/`*_record` fields, so its
  `throughput_overall` and `utilization` there are e2e-based (makespan from
  the driver), which differs by under 0.1% for d32.
