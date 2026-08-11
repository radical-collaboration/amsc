# Setup (one-time)

One-time setup for the `hello-world` smoke test on Perlmutter via NERSC
IRI.  There are **three roles** to prepare.  They can be three separate
hosts, or you can co-locate the driver and the bridge if (and only if)
your driver host happens to be publicly reachable:

- the **driver** (your laptop / workstation) — runs `hello_world.py`.
  Outbound-only; it does **not** need a public IP.
- the **bridge host** — runs `radical-edge-bridge.py`.  Must be
  **publicly reachable** from both the laptop and the Perlmutter login
  node (it is the rendezvous point everything connects out to).
- the **target** (Perlmutter) — runs the compute-side edge + Rhapsody +
  Dragon, installed under `$AMSC_DIR/ve` so the IRI job can find it.

All three use the same `$AMSC_DIR` convention.

## Prerequisites

- A **NERSC account** with access to a Perlmutter GPU allocation
  (this example assumes project `m5290`; substitute your own).
- A **NERSC IRI Globus access token** (see *NERSC token* below).
- A **publicly reachable bridge host** with a stable hostname/DNS, on
  which you can open the bridge port (default 8000) to inbound
  connections from the laptop and from Perlmutter's login nodes.
- `python3.11` on the driver, the bridge host, and Perlmutter.

## `$AMSC_DIR`

Everything this test installs or reads lives under `$AMSC_DIR`
(default `$HOME/.amsc`): the virtualenv, the IRI token, and the
wrapper-script path the IRI job points at.

```sh
export AMSC_DIR="$HOME/.amsc"   # default — set only if relocating
```

If you relocate it on the **target**, update `HOME_DIR` in
`hello_world.py` accordingly (it builds the wrapper path as
`$HOME_DIR/.amsc/ve/bin/radical-edge-wrapper.sh`).

## Environment install

Run this on each role's host. What each one needs:

- **bridge host** — `radical.edge` (it runs the bridge).
- **driver (laptop)** — `radical.edge` + `rhapsody` + `dragon`.  The
  driver constructs a Dragon `Policy` locally (for per-node pinning) and
  cloudpickles it to the edge, so `dragon` must be **importable on the
  laptop**.
- **target (Perlmutter)** — the full stack (it executes the tasks).

The install below is the full stack; it's safe to run verbatim on all
three.

```sh
export AMSC_DIR="${AMSC_DIR:-$HOME/.amsc}"
mkdir -p "$AMSC_DIR"
cd       "$AMSC_DIR"

rm -rf ve/
python3.11 -m venv ./ve
. ve/bin/activate

pip install --upgrade pip pytest pytest-asyncio
pip install --upgrade dragonhpc scikit-learn mpi4py psij-python

git clone git@github.com:radical-cybertools/radical.edge      || true
git clone git@github.com:radical-cybertools/radical.asyncflow || true
git clone git@github.com:radical-cybertools/rhapsody          || true

cd radical.edge/     ; git checkout feature/amsc; git pull; pip install .; cd ..
cd rhapsody/         ; git checkout feature/edge; git pull; pip install .; cd ..
cd radical.asyncflow/; git checkout feature/edge; git pull; pip install .; cd ..

python3 -V
which radical-edge-bridge.py
```

> If `dragonhpc` will not install on your laptop, this smoke test cannot
> run from there as written — the per-node pinning needs a local Dragon
> `Policy`. Run the driver from a host where `dragon` imports cleanly, or
> drop the pinning (and the `one task per node` guarantee).

After this, the target has the wrapper the IRI job will launch:

```
${AMSC_DIR:-$HOME/.amsc}/ve/bin/radical-edge-wrapper.sh
```

## TLS certificate (generate on the bridge host)

The bridge serves over HTTPS. Because the laptop and the Perlmutter edge
reach it by its **public hostname**, the cert must be valid for that
hostname — a `CN=localhost` cert will fail hostname validation when a
client connects to `https://<bridge-host>:8000`. Generate a self-signed
pair on the **bridge host**, with its FQDN in both the CN and a SAN:

```sh
export BRIDGE_HOST="bridge.example.org"      # <- your bridge's public FQDN

mkdir -p "$HOME/.radical/edge"
openssl req -x509 -newkey rsa:4096 -nodes \
    -keyout "$HOME/.radical/edge/bridge_key.pem" \
    -out    "$HOME/.radical/edge/bridge_cert.pem" \
    -days 365 -subj "/CN=$BRIDGE_HOST" \
    -addext "subjectAltName=DNS:$BRIDGE_HOST"
chmod 600 "$HOME/.radical/edge/bridge_key.pem"
```

Then distribute the **cert** (never the key) to the other two roles:

```sh
scp "$HOME/.radical/edge/bridge_cert.pem" you@laptop:~/.radical/edge/bridge_cert.pem
scp "$HOME/.radical/edge/bridge_cert.pem" perlmutter.nersc.gov:~/.radical/edge/bridge_cert.pem
```

## NERSC token (driver/laptop only)

The IRI bearer token is read on the host that runs `hello_world.py` and
sent to the bridge once at connect time. The bridge holds it in process
memory only — it is never written to disk on the bridge side.

```sh
export AMSC_DIR="${AMSC_DIR:-$HOME/.amsc}"
mkdir -p "$AMSC_DIR"

# NERSC IRI Globus access token — paste the literal token string.
echo "$NERSC_GLOBUS_TOKEN" > "$AMSC_DIR/token_nersc"
chmod 600 "$AMSC_DIR/token_nersc"
```

Obtain the token per NERSC's IRI / Globus documentation. The token is
short-lived; if a run fails to connect, refresh it (see [FAQ.md](FAQ.md)).

## Point `hello_world.py` at your account

Edit the constants at the top of `hello_world.py`:

- `ACCOUNT` — your Perlmutter allocation / project.
- `LOGIN_HOST` — the login host for the forward SSH tunnel
  (`perlmutter.nersc.gov`).
- `HOME_DIR` — your `$HOME` on Perlmutter (used to build the wrapper path).
- `N_NODES` — allocation size (default 2).
- `QUEUE` / `WALLTIME_MIN` — queue and walltime.

Once all of the above is in place, continue to **[RUN.md](RUN.md)**.
