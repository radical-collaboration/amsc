# DT paper: outline and experiment list

Discussion draft, 2026-10-02. Scope as agreed on 2026-09-24: DT framework
and DTaaS form one paper; ORBIT is the hosting means. Seed: top half of
"Paper ideas - DT".

## Open

- Venue and deadline
- Timeline
- Ben's role and author list
- Overleaf
- Which paper reports the two shared numbers, inference latency and
  stream hop: this one or the ORBIT paper

## Claim

- Abstractions that decouple DT application logic from task
  orchestration, plus a central broker, make DTs easier to run.
- Scope of the claim: DTs with an online/offline (in-situ/ex-situ)
  architecture, on HPC, fed by external data streams.
- "Easier" means:
  - **portable:** same DT on 1 or N sites
  - **modular:** parts contributed separately and swapped at runtime
  - **extensible:** new features need no rewrite
  - **persistent:** survives client and endpoint loss

## Motivation

- DT definition follows the National Academies report (NASEM 2024),
  including bidirectional interaction.
- Today DTs are one-offs: each is a hand-wired pipeline, and a new
  sensor or model means re-plumbing it.
- Surrogate frameworks train on static data and terminate. A DT needs
  inference that never pauses while models keep learning from streams.
- Facilities allow no persistent user services, so service lifetime is
  bounded by the allocation.
- Fusion driver: NSTX-U processing between shots, target 5–10 min.
- Prior work, the N=1 case: xGFabric/RBF, one stream and one surrogate
  family. This paper covers N streams, M capabilities and S models.

## Contributions

- **C1 DT abstractions** (architecture, independent of implementation):
  - typed streams (DATA_TYPE), external input channels
  - science agent: one capability, holds investigators and a model
    selector
  - model investigator: one model; in-situ inference plus ex-situ
    learning
  - utility tasks
  - stream operators: hard/soft barrier (windowing, replay), join,
    split
- **C2 DTaaS**: the abstractions run as a service.
  - DT control plane is a broker plugin
  - sessions persist without the client; clients reattach
  - compute runs through RHAPSODY endpoints, learning through ROSE
  - authenticated data plane
- **C3 Evaluation** on DOE HPC (Perlmutter), with fusion and agriculture
  DTs.

## Paper structure

1. Introduction
2. Background and requirements (NASEM, NSTX-U, xGFabric)
3. Architecture: C1
4. Implementation: C2
5. Evaluation
6. Related work
7. Limits and future work

## Experiments

Tasks are no-ops unless noted, so the runs isolate DT overhead. Upper
bounds come from the tools underneath: ZMQ, asyncio, AsyncFlow, ROSE,
ORBIT.

- **E1 Overhead.** Do the abstractions cost performance?
  - Baseline: xGFabric-style hand-wired workflow on one endpoint.
  - Metrics:
    - in-situ inference throughput and latency
    - ex-situ learner throughput
  - Have (single host only):
    - service inference 20 ms vs 11 ms in-process
    - stream hop 0.98 ms on ZMQ vs 2.09 ms on ORBIT
  - Missing: the baseline comparison; runs on Perlmutter.
- **E2 Scaling.** How do inputs per second and DT size scale?
  - Axes: number of streams (via join) × number of agents, side by side
    or chained.
  - Same metrics as E1, plus model-publish throughput.
  - Also: DTs and sessions per broker until the broker saturates.
  - Have: placeholder plots only.
- **E3 Portability.** Same DT on 1 to N sites, run as a service.
  - Baseline: xGFabric.
  - Metrics:
    - throughput as sites are added
    - code changes needed per site
  - Needs Ben's multi-endpoint branch merged.
- **E4 Hot-swap.** Update components while the DT runs.
  - Baseline: TBD; Flink, which stops, checkpoints and restarts.
  - Metrics:
    - turnaround per update
    - throughput dip at a given update rate
    - model-update propagation latency (stream → learner → published
      model → inference)
- **E5 Persistence.**
  - Repeated client loss: time to reattach; DT state intact.
  - Endpoint loss: detection, then recovery.
  - Long run: 30 days of uptime (STELLAR-AI milestone T3).
  - Out of scope: broker loss.
- **E6 Use cases.** Show extensibility qualitatively.
  - xGFabric WindField: three investigators (PCR, PINN, FNO) and
    resource-aware model selection.
  - M3D-C1 DT on Perlmutter (dt-complete).
  - Heat-flux surrogate on NSTX-U geometry.
  - Needs a GPU surrogate run; on CPU the xGFabric surrogates took 54 s
    per inference.

## Limits

- Central broker is assumed up; no recovery after broker restart.
- Control path only: bulk data moves out of band.
- Scheduling ignores data location and size.
- Aimed at loosely coupled capabilities.
- Model selection is naive (shortest runtime); cross-model selector is
  v2.
- Single trust domain; per-tenant auth is v2.
- NSTX-U may not treat several models for the same physics as a real
  option.

## Related work (to build)

- Streaming and dataflow: Flink, Spark
- Distributed AI: Ray, Dask
- HPC task services: Globus Compute, Parsl, TaskVine/Work Queue,
  Makeflow
- DT systems: xGFabric/RBF, ExaDigiT, GrowFlow, NASEM report
- Middleware building blocks: ROSE, RHAPSODY, AsyncFlow, Turilli et al.
  2019
- Edge pub/sub: MQTT, CSPOT, AWS Greengrass

## Discussion points

- Terminology: physics property / operator vs science agent vs
  capability; project name "Doppelganger"?
- Explain why DTs run two engines (one for inference, one for learning).
- Use case: wait for the NSTX-U world model (T1, Nov 2026), or go with
  the M3D-C1 mock, heat and CUPS?
- E4 baseline: Flink, or a hand-wired restart?
