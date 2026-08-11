# Running the use case

This assumes [SETUP.md](SETUP.md) is complete: all three roles installed,
the TLS cert generated on the bridge host and its `bridge_cert.pem`
distributed to the laptop and Perlmutter, `token_nersc` written on the
laptop, MATEY checked out with its wrapper on Perlmutter, and `amsc.py`'s
`IRI_DEFAULTS['nersc']` edited for your account and paths.

The bridge launches on the **bridge host**; the driver runs on the
**laptop**.

## 1. Launch the bridge (on the bridge host)

The bridge must load the `iri_connect` plugin so the driver can spawn a
child edge through NERSC IRI:

```sh
export AMSC_DIR="${AMSC_DIR:-$HOME/.amsc}"
. "$AMSC_DIR/ve/bin/activate"

radical-edge-bridge.py -p iri_connect,staging,sysinfo
```

Leave this running.  On startup it prints its URL form(s) — note the one
built from the host's **public** name (e.g. `https://bridge.example.org:8000`);
that's what the laptop and Perlmutter will use.  The bridge also serves an
Explorer UI at that root URL.

> The bridge binds all interfaces by default.  Make sure the bridge port
> (8000) is open to inbound connections from the laptop and from
> Perlmutter's login nodes — that's what the [FAQ](FAQ.md) "child edge
> never connects" item is usually about.

## 2. Run the driver (on the laptop)

Point the driver at the bridge's **public** URL and make sure the
distributed cert is in place:

```sh
export AMSC_DIR="${AMSC_DIR:-$HOME/.amsc}"
. "$AMSC_DIR/ve/bin/activate"

export RADICAL_BRIDGE_URL="https://bridge.example.org:8000"   # your bridge
# cert was distributed to ~/.radical/edge/bridge_cert.pem in SETUP

cd <this use-case directory>
python amsc.py iri:nersc
```

The driver resolves the bridge URL and cert via CLI > env
(`RADICAL_BRIDGE_URL` / `RADICAL_BRIDGE_CERT`) > the files under
`~/.radical/edge`.  Setting `RADICAL_BRIDGE_URL` is the simplest way to
aim it at the bridge host.

### Optional arguments

`amsc.py` accepts up to three positional arguments in any order:

```sh
python amsc.py iri:nersc                  # defaults from IRI_DEFAULTS['nersc']
python amsc.py iri:nersc horizontal 16    # slicing mode + node count
python amsc.py iri:nersc vertical 8
```

- **target** — `iri:nersc` for this use case.
- **slicing mode** — `horizontal` (every kind shares all nodes; per-node
  device counts) or `vertical` (disjoint node subsets by weight).  Default
  is the `horizontal` template.  Only MATEY is active, so horizontal simply
  gives MATEY `gpus_per_node` slots on every node.
- **n_nodes** — overrides the allocation size from `IRI_DEFAULTS['nersc']`.

## 3. Read the trace

The run emits a seven-step coloured trace:

```
step 1  connect bridge      <bridge url>
step 2  pick target         iri:nersc
step 3  configure           16 node x 4 gpu x 128 core, 30m walltime, queue=…
step 4  submit child edge   job=<id8>…  edge=nersc.0
step 5  await child edge    up after <N>s        (dots print during the queue wait)
step 6  run rhapsody        16 hosts  matey 192 (cap 64)  infer 0 (cap 0)  gkeyll 0 (cap 0)
step 7  teardown            cancelling 1 iri job(s)
```

Between steps 5 and 6 you also get:

- a **resource-slicing panel** — an ASCII view of how each node's GPUs
  (and cores) are carved up per task kind;
- **progress bars** — one per active kind, showing submitted / done /
  failed against the total.

A clean finish prints a final `done=… failed=…` tally and `Done.`.

## 4. Find the task output

Each MATEY task runs under `capture_stdio`, so Rhapsody's Dragon V3 backend
redirects its stdout/stderr to files on the **compute side**, named by the
task UID (`matey.0000`, `matey.0001`, …):

```
<edge session dir>/matey.NNNN.stdout
<edge session dir>/matey.NNNN.stderr
<edge session dir>/matey.NNNN.sh     # the generated wrapper script
```

The session directory is `<edge process cwd>/<rhapsody-session-id>`.  To
locate it on Perlmutter:

1. Find the rhapsody session id in the edge log — grep for
   `Registered session session.` in `~/.radical/edge/logs/<edge>.log`
   (e.g. `nersc.0.log`).
2. The files are under that session id beneath the edge's working
   directory.

See [FAQ.md](FAQ.md) for locating the edge log and reading task output.

## 5. Teardown

Teardown (step 7) is automatic and only touches what the driver itself
created — it cancels the IRI job it submitted and disconnects the IRI
endpoint it connected.  Anything that was already running before the driver
started is left alone.

If you interrupt the driver (Ctrl-C) before step 7, cancel the orphaned
IRI job manually (see [FAQ.md](FAQ.md)).
