# AmSC use-case questionnaire — MATEY / fusion fine-tuning

Draft answers. Items marked **[input/confirmation Mat needed]** are either
science-side detail we don't own or statements we could not verify.

## General

### Application overview: scientific goals, computational methods, infrastructure

**Scientific goal.** Train and improve MATEY, a surrogate model for fusion
plasma dynamics, on XGC gyrokinetic simulation data. Long-term direction:
a continuously learning model that serves inference for the fusion
digital-twin effort. **[input/confirmation Mat needed:** precise science
goals and the foundation-model ambition — how far beyond a per-capability
surrogate does this aim?**]**

**Computational methods.**

- XGC simulation for training-data generation.
- MATEY training / fine-tuning (`Fusion_Seed` configuration).
- Surrogate inference at scale.
- Active-learning / model-selection loops (ROSE) — demonstrated on the
  M3DC1 recipe, planned here.

**Infrastructure and scale.**

- Training: Frontier (OLCF), data on the Orion file system; a full
  training run is ~4 nodes for a few hours, all 8 GPUs per node, with GPU
  and CPU work concurrent on the same node.
- Demonstrated inference run: Perlmutter (NERSC, project amsc007),
  16 nodes × 4 GPUs = 192 concurrent tasks, one per GPU slot.
- Runs are driven from a laptop through the ORBIT broker/endpoint
  pattern; the compute-side service is spawned on demand (IRI/SFAPI/Slurm)
  inside a normal batch allocation, tasks executed by RHAPSODY on Dragon.

### How do you measure scientific and computational performance?

**Scientific:** validation accuracy against held-out XGC data; runs are
tracked in the shared AmSC MLflow server. **[input/confirmation Mat
needed:** which physics metrics matter — field-level errors, rollout
stability, conservation properties?**]**

**Computational:** time-to-solution and task throughput per GPU-hour, GPU
utilization (tasks pinned per device), and end-to-end latency of the
on-demand path (job submit → allocation start → endpoint connect → first
task running). The driver emits a per-run trace and per-node resource
panel that make these observable.

### Define "AI advantage" for this application

Proposed definition: the point where the surrogate answers the science
question at sufficient accuracy, and the total cost — data generation +
training + inference — is far below direct XGC simulation for the same
campaign. Once validated, a query costs GPU-seconds of inference instead
of a leadership-scale simulation, enabling campaigns (wide parameter
scans, always-on twin serving) not reachable by direct simulation.
Claimed per capability, not globally — like quantum advantage is claimed
per problem class. **[input/confirmation Mat needed:** agree on the
accuracy threshold and the reference campaign for the cost comparison.**]**

## Runtime specific

### How do AI and HPC couple?

Three modes, in increasing tightness:

1. **Data coupling (demonstrated):** XGC output staged to the parallel
   file system; training and inference read from there — AI runs where
   the simulation data lives.
2. **Concurrent in-allocation (infrastructure demonstrated):** RHAPSODY
   on Dragon runs simulation, training, and inference tasks concurrently
   in one allocation, GPU and CPU side by side, pinned per device. The
   shipped MATEY demo exercised inference only; coupled
   sim + train + infer configurations have not run yet.
3. **Loop coupling (planned):** ROSE closes the
   simulate → train → evaluate → select loop as a service. Demonstrated
   on M3DC1 (20-candidate race, best val_r2 = 0.90), not yet on MATEY.

### Temporal and spatial distribution of tasks

**Spatial:** a wide ensemble of independent tasks, one per GPU slot,
pinned per node. Training uses fewer nodes but all GPUs plus concurrent
CPU work. Placement is data-driven (train at OLCF, near Orion). The
control plane is decoupled: driver on a laptop, public broker as
rendezvous, endpoint inside the allocation.

**Temporal:** phased, not steady-state — on-demand spawn, a
high-throughput bag-of-tasks phase, teardown. Training runs last hours.
In the digital-twin framing, learner loops are episodic (run until an
objective is met); the inference loop runs indefinitely.

### How is concurrent execution managed?

All in user space, no facility-deployed services:

- **RHAPSODY on Dragon** — heterogeneous concurrent tasks in one
  allocation, per-device pinning; nodes shared between services and
  tasks (horizontal slicing) or partitioned per service (vertical), one
  config switch.
- **ORBIT** — connects allocations to the control plane; outbound-only
  connections, allocations spawned and torn down by the driver.
- **AsyncFlow** — task dependencies and campaigns.
- **ROSE** — model-level learning loops.
- **MLflow** — experiment tracking.

### Performance and scale barriers, challenges, limits

- **Allocation latency:** queue wait plus the IRI spawn path dominates
  short campaigns; two IRI issues are open, a direct-SFAPI path is
  validated as an alternative.
- **Connectivity:** compute nodes are outbound-only; the endpoint reaches
  the broker via a tunnel (compute → login → broker), which each new
  facility needs set up. The broker must be publicly reachable — being
  addressed by embedding it in the client.
- **Data/IO:** training data on shared file systems; staging bandwidth
  bounds training throughput. Open question: does training-data order
  matter for heterogeneous data? **[input/confirmation Mat needed]**
- **Task granularity:** many small per-GPU tasks stress launch paths —
  the reason for Dragon rather than repeated scheduler launches.
- **Model scale:** the XGC graph is very large; growing MATEY will hit
  single-allocation memory limits and need model parallelism.
  **[input/confirmation Mat needed:** current model size and memory
  footprint.**]**
- **Policy:** users cannot deploy persistent services at facilities, so
  service lifetime is bounded by allocation lifetime.

## Extra credit: 10× / 100× more resources?

The workload is throughput-oriented and absorbs more resources
near-linearly until data and coordination bind.

- **10×:** larger training runs, wider inference ensembles, several model
  architectures raced concurrently (the M3DC1 pattern applied to MATEY),
  and coupled sim + train + infer runs instead of sequential phases.
- **100×:** always-on digital-twin operation — a continuous inference
  loop plus persistent learner loops across allocations and facilities.
  The bottleneck then shifts from AI compute to (a) training-data
  generation — XGC itself, (b) cross-facility data movement, and (c)
  control-plane scalability, which the user-space ORBIT/RHAPSODY stack
  is built to keep off the facility-ops critical path.

**[input/confirmation Mat needed:** the science-side answer — what would
you *do* with 100×: bigger model, more physics regimes, higher-fidelity
training data?**]**
