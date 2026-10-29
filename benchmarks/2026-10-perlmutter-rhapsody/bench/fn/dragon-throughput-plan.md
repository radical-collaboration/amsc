# Plan — close the rhapsody-dragon function-dispatch throughput gap

## 0. STEP 0 RESULTS (2026-10-22) — THIS REshapes/HALTS the plan

Measured raw dragon **`Batch`** (no rhapsody, no record I/O), 2 nodes, 10k no_op:
- reuse-options: **832 tasks/s**  |  per-task-options: **886 tasks/s**
Rhapsody-dragon `test_throughput.py`, same 2 nodes, 10k: **893 tasks/s**.

Conclusions:
1. **Rhapsody is already at the dragon `Batch` ceiling.** ~860/s raw `Batch` vs ~893/s via rhapsody → rhapsody adds ~0 overhead on the clean path. The "~300/s" seen earlier was MY harness (per-task record write + per-task asyncio wait), which `test_throughput.py` already avoids via `backend.wait()`.
2. **`options()` per task is not a cost** (832 vs 886, reuse no faster) → the deferred memoization would buy nothing. Drop it entirely.
3. **The submit-thread (Step 3) will NOT help** — the event loop is not the bottleneck; dragon's `Batch` per-task dispatch (~1.2 ms/task at 2N) is. Do not implement it.
4. The "dragon native 13.5k/s" figure was `mp.Pool` — a *different, lighter* dragon API. The gap `Batch`→`Pool` is a dragon-API choice, **not** rhapsody overhead. Closing it would mean rhapsody dispatching via Pool/ProcessGroup/chunked instead of `Batch.function()` per task — a large redesign, not a minimal diff, and it would drop `Batch`'s result-tracking/cancellation features.

Net: **there is no minimal rhapsody-side fix** — rhapsody already matches native `Batch`. See "Revised options" at bottom. (Caveat: only the 10k raw point landed; the 40k raw point and >2-node scaling weren't captured, allocation revoked at walltime — a confirmation run is cheap if wanted.)

---

(original plan below, now largely moot — kept for the record)

# Plan — close the rhapsody-dragon function-dispatch throughput gap

Status: DRAFT for discussion. 2026-10-22.
Target branch: **feature/flux** (benchmarked, b5097bb; submit path ~identical to main).
Target performance: **parity with dragon-native per-task** — but see Step 0: the honest ceiling is raw dragon **`Batch`** per-task (rhapsody uses `Batch`, not `mp.Pool`), which may be below the ~13.5k/s `mp.Pool` figure and must be measured before we fix a number.
Scope: **must speed up heterogeneous batches too** — not a homogeneous-only fast path.

## 1. The gap (measured, dragon 0.14.1, Perlmutter CPU)

| path | tasks/s | per-task |
|---|---|---|
| raw dragon `mp.Pool`, per-task (chunksize=1) | ~13,500 | ~74 µs |
| raw dragon `mp.Pool`, batched (chunksize=64) | ~819,000 | — |
| **rhapsody-dragon** `test_throughput.py` (no_op, `backend.wait()`, task_logs off) | **~3,400** (64N); ~900 & degrading at 2N | ~290 µs |

rhapsody adds ~215 µs/task over dragon-native and degrades with batch size when the Batch work-queue (maxsize ~256) blocks the event-loop thread. **Parity means cutting ~215 µs → ~0** while keeping the queue drained.

## 2. Where the cost is (main / feature/flux, same submit path)

`submit_tasks()` = per-task loop on the **asyncio event-loop thread**; `build_task()` per task:
1. `task_opts = self.batch.options(...)` — fresh options object **every task**.
2. recompute mode/template config, stdio paths, coroutine check, dict lookups.
3. `task_opts.function(target, *args, **kwargs)` — dragon dispatch + blocking `work_q.put`.
4. `_task_registry[...]`, `_monitored_batches[...]` writes.
5. `_callback_func(task, "RUNNING")`.

Two cost components:
- **(a) per-task build** (steps 1–2): redundant whenever consecutive tasks share `(function, task_backend_specific_kwargs, stdio)`. Removable by **memoization**, which helps homogeneous *and* mixed-with-repeats batches, degrading to today's cost only for all-unique specs.
- **(b) per-task dispatch on the loop** (step 3): dragon floor (~74 µs) + amplification when `work_q.put` blocks the loop. Removed by getting submission **off the event-loop thread** without the re-entrancy that deadlocks 0.14.1.

## 3. Hard constraints
- **dragon 0.14.1.** `feature/v3_submit_chunking`'s design (chunk the puts across *multiple* `asyncio.to_thread` calls) **deadlocks on 0.14.1 — verified at 100 tasks**. Not an option as-is.
- **Additive, minimal diff vs feature/flux.** One file (`dragon.py`); no public API change; no new dependency; no dragon-version bump. Heterogeneous correctness preserved.

## 4. Approach (profile-first; parity-seeking; general over batch shape)

### Step 0 — Profile + establish the true ceiling (no code change; ~1–2 node-hr)
Two measurements, both no-rhapsody / no-record:
- **Raw dragon `Batch` per-task** (no_op via `batch.function()` in a tight loop + `batch.wait()`, no rhapsody Session). This is the real ceiling for the code path we optimize; `mp.Pool`'s ~13.5k/s is a *different*, lighter API and may not be reachable via `Batch`. Fix the target to this number.
- **Profile** a rhapsody `submit_tasks` of 40k `no_op` tasks on 4–8 nodes (`cProfile`/py-spy): split cost between (a) build and (b) dispatch/loop-block; measure `options()` alone. Gates Steps 2–3. Record both in the report.

### Step 1 — Per-spec memoization of the build — DEFERRED (not now)
Dropped from the initial cut per discussion. Revisit only if Step 0 shows the per-task build (`options()`/config, component (a)) makes the submit thread build-bound below the target; then reconsider as an additive, no-threading follow-up. Not implemented in the first pass.

### Step 2 — Coalesce per-task bookkeeping (if profile flags it)
Batch the `RUNNING` callback and registry writes (one update per N instead of per task). Additive, on-loop.

### Step 3 — Off-loop submit, 0.14.1-safe (PRIMARY lever; gated by a smoke test)
With memoization deferred this is the main change. Move the dispatch loop off the event-loop thread so `work_q.put` never blocks it — but **not** the chunking-branch design. Design to validate:
- a **single dedicated submit thread**, lifetime = the backend's: created lazily on the first `submit_tasks`, torn down on backend `close()`/shutdown — the same lifecycle as the existing `_batch_monitor_thread` daemon. One thread per backend, idle (blocked on its input queue) between submits; **not** per-submit, **not** per-task. `submit_tasks` hands it `(task)` items via a plain queue and `await`s a completion signal. No per-chunk re-entrancy — the property that broke 0.14.1 was repeated short-lived off-thread entry, not off-thread use per se.
- the per-task `build_task` work runs **on this thread** (not the loop), so it no longer blocks the loop; if the thread itself becomes build-bound (Step 0 tells us), that is when memoization (Step 1) comes back.
- **Smoke test first** (100 → 10k tasks, 1 node): if 0.14.1 Batch still refuses off-main-thread submission, abandon Step 3, fall back to on-loop, and report the achievable ceiling honestly.

### Step 4 — Stretch, only if Steps 1–3 plateau below ~13k (larger impact; discuss before doing)
Investigate a lower-overhead dragon submission primitive (e.g. bulk/one-shot enqueue if the 0.14.1 Batch or a lower API exposes it) to amortize per-task Python like the native batched `mp.Pool`. This is the one lever that could exceed per-task 13k but likely exceeds "minimal diff" — flagged, not committed.

## 5. Validation
- `tests/integration/test-hpc/dragon/test_throughput.py --min_tasks 10000 --max_tasks 40000`, **2N and 8N**, before/after; expect the 2N degradation (893→490) to flatten and the ceiling to rise toward native.
- A **heterogeneous** variant (mixed functions/kwargs across the call) to confirm the general path benefits, not just uniform batches.
- Correctness: all DONE, return values/stdout intact; existing dragon unit/integration tests pass unchanged.

## 6. Risk / impact
- Step 0–2: low risk, additive, dozens of lines, one file. Expected to recover component (a) for all batch shapes.
- Step 3: the real risk — threading × dragon 0.14.1 Batch. Gated behind a smoke test; single-owner-thread design chosen specifically to avoid the known deadlock. If it fails, we keep Steps 1–2 and report the honest ceiling.
- Step 4: beyond "minimal"; only on explicit go.

## 7. Decisions taken (this discussion)
- Target: **parity (~13k/s)** → Step 3 in scope.
- Scope: **heterogeneous must benefit** → memoization (Step 1), not a homogeneous-only fast path.
- Branch: **feature/flux**.
- dragon 0.14.1 is firm; old-API chunking branch excluded.

## 8. Still-open (cheap to resolve as we go)
- Single dedicated submit thread: lifetime = backend lifetime (lazily created on first `submit_tasks`, closed on backend shutdown — same as the existing `_batch_monitor_thread`). PENDING your OK on adding this one persistent thread. Separately: does 0.14.1 Batch actually permit off-main-thread submission at all (Step 3 smoke test answers that).
- Memoization deferred (see Step 1); revisit only if Step 0 shows the submit thread is build-bound.

---

## 9. Revised options (post-Step-0)

Since rhapsody already matches native `Batch`, the paths forward are NOT minimal rhapsody tweaks:

- **A. Accept it.** rhapsody-dragon is at the `Batch` ceiling (~900/s @2N, ~3.4k/s @64N — matching Aymen). If "native" means native `Batch`, there is no gap. Lowest effort; likely the correct answer.
- **B. Confirm the ceiling** with one more cheap run: raw `Batch` at 40k (expect ~490/s, matching rhapsody's 40k) and at 8–64 nodes (expect ~3.4k, matching Aymen). Nails "rhapsody == native Batch" across scale.
- **C. Chase `mp.Pool`-class throughput (13.5k+/s).** Requires rhapsody to add a *new dispatch mode* that bypasses `Batch` per-task (e.g. Pool/ProcessGroup or a chunked enqueue) for pure-function fan-out. Large, non-minimal; loses per-task result-tracking/cancellation that `Batch` provides; only worth it if the workload is massive homogeneous function fan-out. Would be a design discussion with the rhapsody/dragon teams, not a quick patch.
- **D. Ask dragon.** The `Batch` per-task cost (~1.2 ms/task @2N) is dragon-side; if that's higher than dragon intends, it's a dragon `Batch` issue, not rhapsody.

Recommendation: **A (+ optionally B to document it)**. Do not build the submit thread or memoization.

---

## 10. Option C in detail — a `Pool`-based function fast-lane

Context: Step 0's raw-`Batch` reuse-options run (single thread, `fence()`, no event loop) still only hit **832/s @2N**. So the ~1.2 ms/task is **intrinsic `Batch` per-task cost** (Function object + work-queue + results-DDict tracking), not event-loop/put blocking. Therefore no amount of chunking/threading of `Batch` submission beats it — **only a different dragon primitive can.** That primitive is dragon's `multiprocessing.Pool` (measured 13.5k/s per-task @2N, ~15×).

### Features the backend provides today via `Batch`, and their fate under a Pool fast-lane
| feature | under `mp.Pool` | recoverable? |
|---|---|---|
| return_value (function result) | native (`AsyncResult`) | yes — free, arguably cleaner |
| DONE / FAILED state | callback / error_callback | yes |
| RUNNING state (actually-started) | Pool signals only completion | approximate (mark RUNNING at submit); minor loss |
| per-task **mid-flight cancellation** (`cancel_task`) | Pool has only `terminate()` = kill all | **no** (would need ProcessGroup + custom control) |
| per-task **timeout → server-side kill** → CANCELED | only client-side `get(timeout)` wait | **partial** (client wait, not a true kill) |
| per-task **stdout/stderr capture** | functions return values, not files | N/A for functions (moot); recoverable via redirect if a fn prints |
| **placement / host-pinning**, cpu/gpu reqs | Pool uses its own worker spread | **limited**; fine-grained placement needs ProcessGroup (more work) |
| **executable** process / **MPI job** (process_templates, nranks) | not Pool's job | **keep on `Batch`** — never route these to the fast-lane |
| event-driven zero-CPU monitor | Pool callbacks | yes (different mechanism, equivalent) |

### Expected performance
- Per-task (`apply_async`, real futures): raw ~13.5k/s @2N measured → with rhapsody's per-task callback + state update layered on, realistically **~5–10k/s @2N** (prototype to confirm) — still **~6–15× `Batch`**. Should scale with workers at a higher base (tens of k/s at many nodes).
- Chunked (`map`, chunksize>1): up to ~819k/s, but results arrive **per chunk, not per task** → incompatible with rhapsody's per-`ComputeTask` future/state model. Not usable unless we relax per-task granularity. So the realistic target is the per-task-future number, not 819k.

### Mix and match — yes, and it's the right shape
A single `DragonExecutionBackend` holds **both** subsystems and **routes per task at submit**:
- **fast-lane (`Pool`)** iff the task is a pure **function** needing only return_value + DONE/FAILED (no mid-flight cancel, no server-side timeout-kill, no explicit placement);
- **`Batch`** for everything else (executables, MPI jobs, tasks needing cancel/timeout/placement) — unchanged.
Both paths feed the same state machine (`_callback_func(DONE/FAILED)`, set `return_value`). Opt-in via a backend flag or capability auto-detect; default can stay `Batch` for safety.

Costs/risks of the mix:
- Two dispatch + result subsystems, two teardown paths (must cleanly `close()` both).
- `Pool` workers and `Batch` workers **coexist on the same allocation** → possible oversubscription if both run heavy work at once; size/stagger to avoid contention. For the common case (function fan-out, Batch mostly idle) this is fine.
- Loss of cancel/timeout/placement **for fast-lane tasks only** — acceptable if the routing predicate is conservative (opt in only when those aren't needed).

### Bottom line on C
Feasible and the only path to `Pool`-class throughput, but it is a **new dispatch mode**, not a minimal diff: ~a few hundred lines, a routing predicate, dual result handling, dual teardown, and a prototype to pin the real (post-overhead) number. Worth it only for workloads dominated by large homogeneous **function** fan-out that don't need per-task cancel/timeout/placement. Recommend scoping it as its own opt-in feature PR (with the rhapsody/dragon teams), separate from any "minimal fix."

---

## 11. Option C ELIMINATED — cancellation is a hard requirement (2026-10-25)

Per-task **mid-flight** cancellation must be preserved (rhapsody `cancel_task` → `batch_task.cancel()`; ROSE kills running speculative branches this way). Verified against dragon 0.14.1:
- `mp.Pool` `AsyncResult` has **no `cancel()`**; `Pool.terminate()` kills all workers; no supported per-running-task kill (worker↔task mapping not exposed; killing a pool worker corrupts result bookkeeping).
- Per-task kill needs **per-task process identity** — `dragon.native.Process.terminate()/kill()` or `Batch` — which reintroduces per-task spawn/management, i.e. `Batch`-class cost. The Pool's ~15× speedup comes exactly from *not* having that.

⇒ **Cancellation and Pool-class throughput are mutually exclusive in one path.** Routing "non-cancellable" tasks to a fast lane doesn't help, because any task may be cancelled via `cancel_task(uid)` unless the user opts a task out of cancellability — which is the very loss that is ruled out.

**Remaining avenues:** A (accept — rhapsody already matches native `Batch`) and D (push dragon to lower `Batch`'s per-task cost, or provide a cancellable-but-lighter primitive). C is off the table.

---

## 12. Can we wrap function tasks and retrofit cancellation? (2026-10-25)

Two mechanisms:

- **Cooperative (soft) cancel** — wrap fn to poll a shared cancel flag. Works only for cooperating fns; **cannot** interrupt opaque/C-bound running tasks (numpy/BLAS, ctypes, tight native loops). Signals/thread-kill don't help (signal lands after the C call; Python threads aren't killable). ⇒ insufficient for the general requirement.

- **Hard cancel via kill-and-respawn (viable)** — a **custom cancellable worker pool**: persistent `dragon.native.Process` workers (which expose `.kill()`), **1 task per worker process**, a `uid → worker-PID` map; `cancel_task(uid)` SIGKILLs that worker (works on opaque code), marks CANCELED, respawns a replacement. Keeps reused-worker throughput (no per-task spawn); pays spawn cost **only on a (rare) cancel**. This preserves the hard requirement.

Costs/unknowns of the hard-cancel pool:
- it is **re-implementing a leaner cancellable `Batch`** in rhapsody (dispatch queue, result/error marshalling, PID tracking, kill+respawn, crash-vs-cancel disambiguation): few hundred LOC + careful tests.
- constraint: 1 task/process (concurrency = #workers = cores).
- **throughput win unproven**: raw reused-worker pool = 13.5k/s, but + tracking/cancel channel likely 5–10k/s; **must prototype** to confirm it beats `Batch`'s ~900/s enough to justify maintenance.
- our **raptor-standalone is a near-template** (persistent workers + slots); change = process-per-slot (today slots are threads, not individually killable) + kill/respawn-on-cancel.

Strategic note: this primitive *is* what Option D would ask dragon for. Choice = **own it in rhapsody** (control, but we maintain a mini-runtime overlapping dragon and track dragon releases) vs **push to dragon** (right layer, slower, not our hands). Recommend: prototype the throughput of a kill-respawn pool (1 interactive job, raptor-standalone adapted to process-per-slot) BEFORE committing — if it doesn't clear ~3–5× Batch, it isn't worth the maintenance and D is the answer.
