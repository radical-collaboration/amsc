# ORBIT performance on Perlmutter (2026-10-29)

Slide figures for the ORBIT task path. One question per figure:

- **F2:** how many tasks/s does a RHAPSODY client push through ORBIT, compared with
  a local RHAPSODY session?
- **F1:** what does one remote task cost, and where does the time go?
- **F5:** does a second endpoint add throughput? (stretch goal)

| figure | file |
|---|---|
| F2 throughput vs. batch size | `f2_throughput.png` / `.svg` |
| F1 single-task latency and per-hop cost | `f1_latency.png` / `.svg` |
| F5 one vs. two endpoints | `f5_two_endpoints.png` / `.svg` (only if F5 ran, see below) |

## Topology

- **Client and broker:** the client runs on Perlmutter login node `login20`. The
  broker is an `EmbeddedBroker` (TLS) inside the client process.
- **Endpoint:** each endpoint is its own 1-node CPU job (`-C cpu`, QOS `debug`,
  account `amsc007`). It runs `radical-orbit-endpoint-wrapper.sh` with the
  `rhapsody` plugin under Dragon, and dials the broker over the HSN (`tunnel=none`).
- **Client side of the hop:** `rhapsody.backends.execution.orbit.OrbitExecutionBackend`.
  The remote backend is `noop` (rhapsody `NoopExecutionBackend`, which marks every
  task DONE without running it) or `concurrent` (a ThreadPoolExecutor, used for
  `/bin/true`).
- **Direct baseline:** a local `rhapsody.Session` on the same login node, with the
  same backend (`noop` or `concurrent`) and no ORBIT.

Software:

| component | version |
|---|---|
| radical.orbit | devel `52b2a0f` (0.8.0) |
| rhapsody | `demo/hppss-orbit` `6ae799b` (0.6.0) |
| radical.prof | radical.profile devel `2bf1eb1` |
| dragonhpc | 0.15.0 |
| Python | cray-python 3.12.12 |

The environment is `/pscratch/sd/m/merzky/overnight-2026-10-29/env.sh`. The
harness is `.../harness/orbit_harness.py`.

## What was measured

### F2: throughput vs. batch size (`bench.py`, `f2_sweep`)

- **Batches:** each batch of *n* noop function tasks (n = 1, 2, 4 … 16384) is
  submitted with one `session.submit_tasks` call and awaited with `wait_tasks`.
  Throughput is n / (submit + wait), as in `orbit/examples/example_rhapsody_throughput.py`.
- **Task types:** "identical" tasks are `ComputeTask(function=_noop)`; "per-task
  arguments" are `ComputeTask(function=_noop_arg, args=(i,))`.
- **Repetitions:** 3, each with a fresh backend and session in its own cwd, and one
  warm-up task first. The plot shows the median, with a min..max band.
- **Configurations:**
  - direct: local session, noop backend;
  - ORBIT default: client batch window 0.25 s, endpoint notify window 0.25 s;
  - ORBIT with `RADICAL_ORBIT_RHAPSODY_NOTIFY_WINDOW=0`: own endpoint job, client
    batch window still 0.25 s;
  - ORBIT with both windows 0: same endpoint job as the previous one, plus
    `batch_window=0` on the client.

### F1: single-task latency (`bench.py`, `f1_seq`)

- **Workload:** 20 warm-up tasks, then 200 tasks one at a time (submit, then wait
  for DONE), for a noop function task (`noop` backend) and for `/bin/true`
  (`concurrent` backend, which really forks).
- **Profiling:** `RADICAL_PROFILE=True`. radical.prof reads it when each `Profiler`
  is constructed and writes `<name>.prof` into the cwd at that moment.
- **Profiles per run:** the endpoint job has its own workdir. Every client phase has
  its own cwd. The broker profile sits in the run root.
- **Segments:** each one is a difference of two timestamps taken on the same host.
  Client and broker are both on the login node; the endpoint events are all on the
  compute node. No cross-host difference is ever taken.

| segment | events | host |
|---|---|---|
| RHAPSODY client API | my `t0` → `task_submit`, and `task_complete(DONE)` → my `t2` | login |
| client batch window | `task_submit` → `task_batch_flush` | login |
| client → broker | `task_batch_flush` (or `task_submit`) → `broker_route_request` | login |
| endpoint: recv → task submitted | `endpoint_recv` → `rh_submit_done` | compute |
| broker ↔ endpoint WS round trip | (`broker_route_response` − `broker_route_request`) − endpoint segment | login − compute duration |
| endpoint notify window + network | (last `broker_event_in` `task_status*` − `broker_route_request`) − endpoint segment | login − compute duration |
| broker → client delivery | last `broker_event_in` → `task_complete(DONE)` | login |

Tasks are matched by uid: client events and `rh_submit` carry the task uid.
`endpoint_recv` and the broker route events carry the request `corr_id`, linked
via the submit request that immediately precedes `rh_submit` on the endpoint.

### F5: one client, two endpoints (`bench.py f5`)

- **Setup:** two endpoint jobs on one broker. One Session holds two
  `OrbitExecutionBackend`s, and each batch is split evenly between them via the
  task `backend` field.
- **Comparison:** the same sweep against one endpoint only. Batch sizes 64 … 16384,
  3 repetitions, default windows.

## Key numbers

### F2 throughput

Tasks/s, median of 3:

| batch | direct (identical / per-task args) | ORBIT default | ORBIT notify window 0 | ORBIT both windows 0 |
|---:|---:|---:|---:|---:|
| 1 | 10.9k / 10.8k | 2.0 / 2.0 | 3.9 / 3.9 | 21 / 23 |
| 64 | 56k / 59k | 124 / 124 | 219 / 221 | 1.05k / 1.06k |
| 1024 | 62k / 57k | 7.3k / 7.4k | 2.1k / 1.9k | 2.2k / 1.8k |
| 4096 | 40k / 56k | 6.7k / 6.4k | stalls | stalls |
| 16384 | 40k / 41k | 6.9k / 7.1k | stalls | stalls |

The exact values are in `data/f2_summary.csv`; every repetition is in
`data/f2_throughput.csv`.

- **Below 1024 tasks, ORBIT is bound by its windows.** The client waits 0.25 s
  before it flushes, and the endpoint waits 0.25 s before it notifies, so a batch
  of n takes about 0.5 s and throughput is about n / 0.5 s.
- **At 1024 tasks a batch fills the client buffer** (`batch_limit=1024`) and is
  flushed at once. Throughput then plateaus at about **7k tasks/s**, about 8x below
  the local session (40–60k tasks/s).
- **The identical vs. per-task-arguments split makes no visible difference** on
  either path.
- **Notify window 0 lowers large-batch throughput** (about 2k vs. 7k tasks/s at
  1024), because every completion becomes its own event. Above about 2048 tasks
  it stalls (see Findings).

### F1 latency

p50 / p95 in ms, from `data/f1_summary.csv`:

| path | noop function | /bin/true |
|---|---:|---:|
| local RHAPSODY session | 0.09 / 0.10 | 2.3 / 3.0 |
| ORBIT, default windows | 506 / 507 | 507 / 519 |
| ORBIT, client batch window 0 | 255 / 256 | 257 / 260 |
| ORBIT, notify window 0 (client window default) | 256 / 281 | 256 / 283 |
| ORBIT, both windows 0 | 44 / 56 | 48 / 52 |

Per-hop p50 in the default configuration (noop function / `/bin/true`):

| hop | p50, ms |
|---|---|
| client API | 0.47 / 0.23 |
| client → broker | 1.1 / 0.9 |
| endpoint recv → task submitted | 1.1 / 2.1 |
| broker ↔ endpoint WebSocket round trip (login ↔ compute) | 1.1 / 1.3 |
| broker → client | 0.9 / 0.8 |

- **The windows dominate.** With default settings a single remote task costs about
  0.5 s, and almost all of that is the two 0.25 s coalescing windows. The ORBIT
  hops themselves cost about 1 ms each, so about 5 ms in total.
- **With both windows at 0, about 40 ms remain**, almost entirely between the
  broker receiving the completion event and the client marking the task DONE
  (`b2c` in `data/f1_summary.csv`). With only the client window at 0, or only the
  notify window at 0, that hop is about 1 ms. The 40 ms is consistent with a TCP
  delayed-ACK/Nagle interaction on the client WebSocket. It was not investigated
  further.

## Findings (ORBIT / RHAPSODY issues hit during the runs)

1. **Large submissions exceed the frame cap and hang the client.**
   - The client splits submissions at `WS_PAYLOAD_LIMIT = 8 MiB`
     (`radical/orbit/plugin_rhapsody.py`), but the protocol frame cap is
     `FRAME_CAP = 4 MiB` (`radical/orbit/protocol.py`).
   - A cloudpickled noop task is about 900 B, so batches from about 4.6k tasks
     produce 4–8 MiB requests. These fail with
     `[Runtime] failed to pack request: frame size 7424593 bytes exceeds cap 4194304 bytes`.
   - The client then hangs instead of failing the tasks.
   - `bench.py` works around this in its own process by setting
     `plugin_rhapsody.WS_PAYLOAD_LIMIT = 3 MiB`. All F2/F5 ORBIT points use that
     override.
2. **With `RADICAL_ORBIT_RHAPSODY_NOTIFY_WINDOW=0`, batches of 2048+ tasks never
   complete.**
   - The endpoint submits all tasks, and the broker forwards per-task
     `rhapsody/task_status` events.
   - The client logs `[Runtime] callback queue full; dropping callback '_on_task_done'`:
     the `EndpointRuntime` user-callback dispatcher is bounded at
     `_CALLBACK_QUEUE = 1024` (`radical/orbit/runtime.py`).
   - Dropped completions are never re-delivered, so `wait_tasks` waits forever. In
     all 12 sweeps (3 reps x 2 task types x 2 configs), 1500–2400 of 2048–4096
     tasks completed before a 60 s timeout.
   - Not patched here. The F2 curves for notify window 0 end where the stall
     starts (marked x).
3. **`examples/plot_profiles.py` is stale**, as already known. `analyze.py` here
   reads the current events directly.

## Caveats

- **Noop backend.** The tasks never run, so these are pure framework overheads, not
  application throughput.
- **Login-node client.** Client and embedded broker share one Python process on a
  shared login node (load average about 60–100 during the runs). Login-node noise
  shows up as the occasional outlier, for example the dip in the direct band at 256
  per-task-argument tasks.
- **Shared GIL.** The broker shares the GIL with the client, which probably caps the
  ORBIT plateau.
- **Profiling settings.** F2 ran with client-side profiling off. Broker and endpoint
  profiling stayed on in all runs; they log per request or per event, not per task.
  F1 ran with profiling on everywhere.
- **Repetitions.** F2 and F5 have 3 repetitions per point. F1 has one run of 200
  tasks per bar, and the bars are p50s of the segments, stacked; medians are not
  additive, so the labels give the p50 of the total.
- **Clock skew.** Only same-host differences are used. Durations measured on the
  compute node (the endpoint segment) are subtracted from durations measured on the
  login node; that is valid because both are durations, not timestamps.
- **The F1 "endpoint notify window + network" segment also covers** the noop
  completion and the watcher on the endpoint. It is not split further, because no
  profile event exists there today.

## Reproduce

```bash
source /pscratch/sd/m/merzky/overnight-2026-10-29/env.sh
python bench.py direct                                   # login node only
python bench.py orbit --tag default                      # F1 + F2, 1 endpoint job
python bench.py orbit --tag nw0 --notify-window 0 --phases f1,f2,f2bw0 --batch-timeout 60
python bench.py f5 --tag f5                              # 2 endpoint jobs
python analyze.py /pscratch/sd/m/merzky/overnight-2026-10-29/runs/perf .
```

On the ORBIT side, the runs that produced these data were:

| tag | job | contents |
|---|---|---|
| `default` | 60517145 | F1 only; its F2 hit finding 1 |
| `default-f2` | 60517577 | F2 with `--f2cfg orbit-default`, after the workaround |
| `nw0` | 60517658 | F1; its F2 hit finding 2 |
| `nw0-f2` | 60517898 | F2 for both window-0 configurations |

Raw `.prof` files and logs stay on scratch under
`/pscratch/sd/m/merzky/overnight-2026-10-29/runs/perf/`. `data/` holds the
per-measurement `results-*.jsonl` and the derived CSVs.
