# FAQ / troubleshooting

Common snags running the fine-tuning use case, and how to diagnose them.

## The bridge won't start — "TLS cert not found"

The bridge needs a cert + key on the **bridge host**. Generate a
self-signed pair valid for the bridge's public FQDN (see
[SETUP.md](SETUP.md) → *TLS certificate*):

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

If the laptop or the edge connects but the TLS handshake fails with a
certificate / hostname error, the cert's name doesn't match the URL being
used. The laptop and Perlmutter reach the bridge by its **public
hostname**, so a `CN=localhost` cert (the old single-host default) will
not validate. Regenerate the cert with the bridge's FQDN in the CN **and**
a `subjectAltName` DNS entry (as above), redistribute it, and make sure
`RADICAL_BRIDGE_URL` uses that same FQDN — not an IP, not `localhost`.

## The child edge starts but can't connect — cert validation

The compute-side edge validates the bridge's cert against its own
`~/.radical/edge/bridge_cert.pem` on Perlmutter (or `$RADICAL_BRIDGE_CERT`
if set there). Copy the **cert** (not the key) from the bridge host to the
target so it validates:

```sh
scp "$HOME/.radical/edge/bridge_cert.pem" \
    perlmutter.nersc.gov:~/.radical/edge/bridge_cert.pem
```

## "token file missing" or the IRI connect is rejected (401/403)

The driver reads `$AMSC_DIR/token_nersc` and sends it to the bridge at
connect time. If it's missing, empty, or expired:

```sh
echo "$NERSC_GLOBUS_TOKEN" > "${AMSC_DIR:-$HOME/.amsc}/token_nersc"
chmod 600 "${AMSC_DIR:-$HOME/.amsc}/token_nersc"
```

NERSC Globus access tokens are short-lived — a run that worked yesterday
can fail today purely because the token expired. Refresh it and re-run.

## Step 5 hangs — "await child edge" never completes

This step polls the bridge until the child edge connects back. A long wait
is usually just the **SLURM queue** — the IRI job is submitted but not yet
running. The driver prints dots during the wait; give it time (the default
timeout is 30 minutes).

If it never connects:

- Check the job actually queued: the driver prints the IRI `job_id` at
  step 4. Query its state through the IRI endpoint or `squeue` on
  Perlmutter.
- Check the bridge host is reachable from Perlmutter's **login node** and
  that the bridge port (8000) is open inbound there. The NERSC path
  tunnels compute → login → bridge (`tunnel='forward'` in
  `IRI_DEFAULTS['nersc']`), so the login node is what actually opens the
  connection to the bridge. From a Perlmutter login node:
  `curl -sk https://<bridge-host>:8000/ >/dev/null && echo reachable`.
- Check the compute→login SSH the forward tunnel relies on is permitted
  (it is on Perlmutter by default).
- Read the edge log on Perlmutter (below).

## Tasks oversubscribe a node (more than `gpus_per_node` per node)

Each task is pinned to a `(host, gpu)` via Dragon's
`Policy(placement=HOST_NAME, gpu_affinity=[…])`. On multi-node
allocations this depends on a Rhapsody fix that guards the V3 monitor
loop's result lookup; without it the loop can wedge and placement can
appear wrong. Ensure the `rhapsody` install on the **target** is on a
branch that includes that fix (the `feature/edge` branch used in
[SETUP.md](SETUP.md) does).

If you still see uneven per-node counts, confirm the hostnames the driver
uses (`queue_info.nodelist()`) match what Dragon reports for the same
allocation — a mismatch silently disables HOST_NAME placement.

## Where is the edge log?

On Perlmutter, per-edge logs are under:

```
~/.radical/edge/logs/<edge-name>.log      # e.g. nersc.0.log
```

The edge name is shown at step 4 (`edge=nersc.0`). The log captures both
radical.edge and rhapsody output (including Dragon V3 backend lines), and
survives Dragon's stdio capture.

## Where is per-task stdout/stderr?

Under the rhapsody session directory on the compute side, named by task
UID:

```
<edge cwd>/<rhapsody-session-id>/task.NNNN.stdout
<edge cwd>/<rhapsody-session-id>/task.NNNN.stderr
```

Find `<rhapsody-session-id>` by grepping the edge log for
`Registered session session.`. See [RUN.md](RUN.md) → *Find the task
output*.

> [NOTE]
> By default `stderr` and `stdout` are only generated when `capture_stdio=True` is passed to the `ComputeTask`.



## I Ctrl-C'd the driver — is the IRI job still running?

Possibly. Automatic teardown (step 7) only runs if the driver reaches it.
If you interrupted earlier, cancel the orphaned job manually: note the
`job_id` from step 4 and cancel it via the IRI endpoint, or `scancel` it on
Perlmutter once you identify it (`squeue -u $USER`).

## Nothing matches my target — "no IRI_DEFAULTS entry for …"

`amsc.py iri:<name>` requires a matching `IRI_DEFAULTS['<name>']` block.
This use case ships `nersc`. To target a different endpoint, add an entry
(account, login_host, home_dir, tunnel mode, app paths) modelled on the
`nersc` one.
