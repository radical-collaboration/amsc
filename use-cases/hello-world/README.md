# hello-world — AmSC edge infrastructure smoke test

This is a minimal end-to-end test of the AmSC edge infrastructure on NERSC
**Perlmutter**.  It spawns a compute-side edge on demand through NERSC's
IRI interface, runs `hostname` as an executable task **pinned to each of 2
nodes** (one task per node) through **Rhapsody** on **Dragon**, then tears
the edge down.

There is no application workload — the point is to verify the plumbing
(connectivity, IRI submission, edge bring-up, task placement, task
execution) before anyone wires in a real workload.  Once `hello-world`
runs cleanly, you know the infrastructure is sound; swapping in your own
executable is then a config change, not a debugging session.

If you want the fully worked application example, see the sibling
[`fine-tuning`](../fine-tuning/) use case — same infrastructure, real
MATEY workload.

## What you will run

```
  Laptop / workstation  (outbound only — no public IP needed)
    └── hello_world.py             the driver: spawns the edge, runs the
          │                        smoke test, tears down
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
     Perlmutter compute nodes  (2 nodes)
       └── child edge        radical-edge-wrapper.sh, launched under Dragon
             └── Rhapsody V3 backend
                   └── hostname task   one per node, pinned via Policy
```

The bridge host is the only component that must be publicly reachable: the
laptop connects out to it over HTTPS, and the Perlmutter edge connects out
to it over a WebSocket (tunnelled compute → login → bridge).

## What success looks like

```
  submitting IRI job (nersc → perlmutter, edge name: amsc-nersc-a1b2c3)…
  IRI job_id: <id>

— Waiting for first edge to come up (any of: amsc-nersc-a1b2c3) —
— First edge up: amsc-nersc-a1b2c3 —
allocation (2 nodes): ['nidXXXXXX', 'nidYYYYYY']
submitting 2 hostname task(s), one per node ...

results:
  hello.00   pinned ->     nidXXXXXX   state=DONE
  hello.01   pinned ->     nidYYYYYY   state=DONE

executable stdout/stderr are captured on the COMPUTE side ...
tearing down ...
```

`state=DONE` for every task means the full chain works.  The captured
`hostname` output lives on the compute side (see [RUN.md](RUN.md) →
*Where the output is*); staging it back to the client is left for later.

## Documents

- **[SETUP.md](SETUP.md)** — one-time setup: roles, environments, TLS
  cert, NERSC token.
- **[RUN.md](RUN.md)** — launch the bridge, run the driver, read the
  result, find the captured output.
- **[FAQ.md](FAQ.md)** — common snags and how to diagnose them.

## Files in this directory

| File | Purpose |
|---|---|
| `README.md` | This file — overview, architecture, and index. |
| `SETUP.md` | One-time setup: roles, environments, TLS cert, NERSC token. |
| `RUN.md` | Launch the bridge, run the driver, read the result. |
| `FAQ.md` | Common snags and how to diagnose them. |
| `hello_world.py` | The minimal smoke-test driver. |
| [`../service_utils.py`](../service_utils.py) | Shared service machinery (target discovery, IRI/PsiJ launch, teardown) used by all use-case drivers; holds the `IRI_DEFAULTS` account settings. |
