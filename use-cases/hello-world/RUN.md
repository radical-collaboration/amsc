# Running the smoke test

This assumes [SETUP.md](SETUP.md) is complete: all three roles installed,
the TLS cert generated on the bridge host and its `bridge_cert.pem`
distributed to the laptop and Perlmutter, `token_nersc` written on the
laptop, and the constants at the top of `hello_world.py` edited for your
account.

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

Leave this running. On startup it prints its URL form(s) — note the one
built from the host's **public** name (e.g.
`https://bridge.example.org:8000`); that's what the laptop and Perlmutter
will use.

> The bridge binds all interfaces by default. Make sure the bridge port
> (8000) is open to inbound connections from the laptop and from
> Perlmutter's login nodes.

## 2. Run the driver (on the laptop)

Point the driver at the bridge's **public** URL and make sure the
distributed cert is in place:

```sh
export AMSC_DIR="${AMSC_DIR:-$HOME/.amsc}"
. "$AMSC_DIR/ve/bin/activate"

export RADICAL_BRIDGE_URL="https://bridge.example.org:8000"   # your bridge

cd <this use-case directory>
python hello_world.py
```

The driver resolves the bridge URL and cert via env
(`RADICAL_BRIDGE_URL` / `RADICAL_BRIDGE_CERT`) > the files under
`~/.radical/edge`.

## 3. Read the result

```
submitting IRI job (nersc -> perlmutter, edge hello.0) ...
  job_id: <id>
waiting for the edge (queue + boot) ......        (dots during the queue wait)
edge hello.0 is up
allocation (2 nodes): ['nidXXXXXX', 'nidYYYYYY']
submitting 2 hostname task(s), one per node ...

results:
  hello.00   pinned ->     nidXXXXXX   state=DONE
  hello.01   pinned ->     nidYYYYYY   state=DONE

executable stdout/stderr are captured on the COMPUTE side ...
tearing down ...
```

`state=DONE` for every task means the full chain works: the laptop reached
the bridge, the bridge spawned the edge via IRI, the edge came up and
connected back, Rhapsody/Dragon placed one task on each node, and the
tasks ran to completion.

If any task shows `state=FAILED`, see [FAQ.md](FAQ.md).

## 4. Where the output is

`hostname` writes to stdout, which Rhapsody's Dragon V3 backend captures to
files on the **compute side** (executable stdout does **not** cross the
edge result channel — only state / return value do). The files are named
by task UID:

```
<edge cwd>/<rhapsody-session-id>/hello.NN.stdout
<edge cwd>/<rhapsody-session-id>/hello.NN.stderr
<edge cwd>/<rhapsody-session-id>/hello.NN.sh     # the generated wrapper
```

To locate `<rhapsody-session-id>` on Perlmutter, grep the edge log:

```sh
grep "Registered session" ~/.radical/edge/logs/hello.0.log
```

The files are under that session id beneath the edge's working directory.
Staging this output back to the client automatically is not wired up yet —
for now, read it on the compute side.

## 5. Teardown

Teardown is automatic (the `finally` block): it cancels the IRI job the
driver submitted and disconnects the IRI endpoint it connected. If you
Ctrl-C before teardown runs, cancel the orphaned job manually — note the
`job_id` printed at submit time and cancel it via the IRI endpoint or
`scancel` on Perlmutter (see [FAQ.md](FAQ.md)).
