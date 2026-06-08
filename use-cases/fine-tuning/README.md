# AmSC fine-tuning use case — MATEY on Perlmutter via RADICAL Edge

This use case runs an HPC workload on NERSC **Perlmutter** compute nodes,
driven from your own laptop / workstation, without you ever logging in to
Perlmutter to start the run.  The compute-side service is spawned **on
demand** through NERSC's IRI interface, and the individual tasks are
executed by **Rhapsody** on **Dragon**.

The three components — the **driver** on your laptop, the **bridge**, and
the compute-side **edge** — talk to each other through the bridge, which is
the rendezvous point.  Because your laptop almost certainly has no public
IP, the bridge runs on a **separate, publicly reachable host** that both
the laptop and Perlmutter can connect *out* to.  All connections are
outbound toward the bridge, which keeps everything firewall-friendly.

The worked example here is **MATEY** (a surrogate-model inference run).
The point of this document, though, is the **infrastructure pattern**, not
MATEY itself: once you can drive MATEY this way, you can swap in your own
executable and run *your* workload across Perlmutter the same way.  The
MATEY-specific bits are isolated to a handful of config fields and a
wrapper script.

## What you will run

```
  Laptop / workstation  (outbound only — no public IP needed)
    └── amsc.py                    the driver: drives the whole run over
          │                        HTTPS, then tears down what it created
          │   HTTPS  (outbound)
          ▼
  Public bridge host  (reachable from BOTH the laptop and Perlmutter)
     ╔══════════╗
     ║  Bridge  ║   radical-edge-bridge.py — reverse proxy / rendezvous
     ╚══════════╝
          ▲   outbound WebSocket  (compute → login → bridge, via SSH tunnel)
          │
          │   ── and ── IRI submit (NERSC Globus token) → SLURM job
          ▼
     Perlmutter compute nodes
       └── child edge        radical-edge-wrapper.sh, launched under Dragon
             └── Rhapsody V3 backend
                   └── MATEY tasks   one task per GPU slot, pinned per node
```

The bridge host is the only component that must be publicly reachable: the
laptop connects out to it over HTTPS, and the Perlmutter edge connects out
to it over a WebSocket (tunnelled compute → login → bridge).  The IRI job
submission also targets the bridge URL so the spawned edge knows where to
phone home.

The driver (`amsc.py`) does seven visible steps:

```
  step 1  connect bridge
  step 2  pick target          iri:nersc
  step 3  configure            nodes × gpus × cores, walltime, queue
  step 4  submit child edge    IRI job submitted to Perlmutter
  step 5  await child edge     wait for it to queue, start, connect back
  step 6  run rhapsody         submit + run the MATEY tasks
  step 7  teardown             cancel the IRI job we created
```

A successful run prints a per-node resource-slicing panel, live progress
bars (submitted / done / failed), and a final done/failed tally.

## Documents

- **[SETUP.md](SETUP.md)** — one-time setup: accounts, the client and
  target environments, TLS cert, NERSC token, and the MATEY checkout.
- **[RUN.md](RUN.md)** — each run: launch the bridge, run the driver,
  read the trace, and find the task output.
- **[FAQ.md](FAQ.md)** — common snags and how to diagnose them.

## Files in this directory

| File | Purpose |
|---|---|
| `README.md` | This file — overview, architecture, and index. |
| `SETUP.md` | One-time setup: roles, environments, TLS cert, NERSC token, MATEY. |
| `RUN.md` | Each run: launch the bridge, run the driver, read the trace, find output. |
| `FAQ.md` | Common snags and how to diagnose them. |
| `amsc.py` | The driver. A snapshot of `radical.edge/examples/amsc.py`. |
| `matey_wrapper.sh` | Per-task wrapper: loads the MATEY env, then execs the task. Goes on the **target** at `$MATEY_DIR/matey_wrapper.sh`. |

## Reusing this for your own workload

Three things are MATEY-specific; everything else is reusable infrastructure:

1. The `app` paths in `amsc.py`'s `IRI_DEFAULTS['nersc']` block
   (`matey_dir`, `matey_model_dir`, `matey_xgc_dir`).
2. `matey_wrapper.sh` (the env-setup + exec shim).
3. The task command line built in `submit_rhapsody_workload`
   (the `basic_inference.py` argv).

Point those at your own executable and data, and the bridge / edge / IRI /
Rhapsody / Dragon machinery carries it unchanged.
