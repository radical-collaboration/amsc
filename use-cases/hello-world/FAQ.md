# FAQ / troubleshooting

Common snags running the `hello-world` smoke test, and how to diagnose
them.

## `ModuleNotFoundError: dragon` when the driver runs

The driver constructs a Dragon `Policy` locally (for per-node pinning) and
cloudpickles it to the edge, so `dragon` must be importable on the host
running `hello_world.py`. Install `dragonhpc` there (see
[SETUP.md](SETUP.md) → *Environment install*), or run the driver from a
host where Dragon imports cleanly. If Dragon genuinely can't run on your
client, drop the pinning (and the one-task-per-node guarantee).

## The bridge won't start — "TLS cert not found"

The bridge needs a cert + key on the **bridge host**, valid for its public
FQDN:

```sh
export BRIDGE_HOST="bridge.example.org"
openssl req -x509 -newkey rsa:4096 -nodes \
    -keyout "$HOME/.radical/edge/bridge_key.pem" \
    -out    "$HOME/.radical/edge/bridge_cert.pem" \
    -days 365 -subj "/CN=$BRIDGE_HOST" \
    -addext "subjectAltName=DNS:$BRIDGE_HOST"
chmod 600 "$HOME/.radical/edge/bridge_key.pem"
```

The key must be mode `0600` or the bridge refuses to start.

## TLS handshake fails — hostname mismatch

The laptop and Perlmutter reach the bridge by its **public hostname**, so a
`CN=localhost` cert will not validate. Regenerate the cert with the
bridge's FQDN in the CN **and** a `subjectAltName` DNS entry (as above),
redistribute it, and make sure `RADICAL_BRIDGE_URL` uses that same FQDN —
not an IP, not `localhost`.

## The child edge starts but can't connect — cert validation

The compute-side edge validates the bridge's cert against its own
`~/.radical/edge/bridge_cert.pem` on Perlmutter (or `$RADICAL_BRIDGE_CERT`
if set there). Copy the **cert** (not the key) from the bridge host to the
target:

```sh
scp "$HOME/.radical/edge/bridge_cert.pem" \
    perlmutter.nersc.gov:~/.radical/edge/bridge_cert.pem
```

## "token file missing" or IRI connect is rejected (401/403)

The driver reads `$AMSC_DIR/token_nersc` and sends it to the bridge at
connect time. If it's missing, empty, or expired:

```sh
echo "$NERSC_GLOBUS_TOKEN" > "${AMSC_DIR:-$HOME/.amsc}/token_nersc"
chmod 600 "${AMSC_DIR:-$HOME/.amsc}/token_nersc"
```

NERSC Globus access tokens are short-lived — a token that worked yesterday
can fail today. Refresh it and re-run.

## "waiting for the edge" never finishes

This polls the bridge until the child edge connects back. A long wait is
usually the **SLURM queue** — the IRI job is submitted but not yet running.
The driver prints dots during the wait.

If it never connects:

- Check the job actually queued — the driver prints the IRI `job_id` at
  submit time; query it via the IRI endpoint or `squeue` on Perlmutter.
- Check the bridge host is reachable from Perlmutter's **login node** and
  the bridge port (8000) is open inbound there. The NERSC path tunnels
  compute → login → bridge, so the login node is what opens the connection
  to the bridge. From a Perlmutter login node:
  `curl -sk https://<bridge-host>:8000/ >/dev/null && echo reachable`.
- Read the edge log on Perlmutter (below).

## A task shows `state=FAILED`

Read the task's captured stderr on the compute side:

```
<edge cwd>/<rhapsody-session-id>/hello.NN.stderr
```

Find `<rhapsody-session-id>` by grepping the edge log for
`Registered session`. Also check the edge log itself for backend errors.

## Tasks land on the same node instead of one-per-node

Each task is pinned to a host via `Policy(placement=HOST_NAME, …)` built
from `queue_info.nodelist()`. If placement looks wrong, confirm the
hostnames the driver used match what Dragon reports for the allocation — a
mismatch silently disables HOST_NAME placement. Also ensure the `rhapsody`
install on the **target** is on a branch that includes the V3 monitor-loop
fix (the `feature/edge` branch used in [SETUP.md](SETUP.md) does).

## Where is the edge log?

On Perlmutter, per-edge logs are under:

```
~/.radical/edge/logs/<edge-name>.log      # e.g. amsc-nersc-a1b2c3.log
```

It captures both radical.edge and rhapsody output (including Dragon V3
backend lines).

## I Ctrl-C'd the driver — is the IRI job still running?

Possibly. Automatic teardown only runs if the driver reaches its `finally`
block. If you interrupted earlier, cancel the orphaned job manually: note
the `job_id` printed at submit time and cancel it via the IRI endpoint, or
`scancel` it on Perlmutter (`squeue -u $USER`).
