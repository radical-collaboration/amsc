# Setup (one-time)

This is the one-time setup for the fine-tuning use case on Perlmutter via
NERSC IRI.  There are **three roles** to prepare.  They can be three
separate hosts, or you can co-locate the driver and the bridge if (and
only if) your driver host happens to be publicly reachable:

- the **driver** (your laptop / workstation) — runs the `amsc.py` driver.
  Outbound-only; it does **not** need a public IP.
- the **bridge host** — runs `radical-edge-bridge.py`.  Must be
  **publicly reachable** from both the laptop and the Perlmutter login
  node (that's the rendezvous point everything connects out to).
- the **target** (Perlmutter) — runs the compute-side edge + Rhapsody +
  Dragon, installed under `$AMSC_DIR/ve` so the IRI job can find it.

All three use the same `$AMSC_DIR` convention.

## Prerequisites

- A **NERSC account** with access to a Perlmutter GPU allocation
  (this example assumes project `amsc007`; substitute your own).
- A **NERSC IRI Globus access token** (see *NERSC token* below).
- A **publicly reachable bridge host** with a stable hostname/DNS, on
  which you can open the bridge port (default 8000) to inbound
  connections from the laptop and from Perlmutter's login nodes.
- `python3.11` or `python3.12`  on the driver, the bridge host, and Perlmutter.

## `$AMSC_DIR`

Everything this use case installs or reads lives under `$AMSC_DIR`
(default `$HOME/.amsc`): the virtualenv, the IRI token, and the
wrapper-script path the IRI job points at.

```sh
export AMSC_DIR="$HOME/.amsc"   # default — set only if relocating
```

The snippets below use `${AMSC_DIR:-$HOME/.amsc}` so they paste-and-run
whether or not the variable is set.  If you relocate it on the **target**,
set `IRI_DEFAULTS['nersc']['amsc_dir']` in `amsc.py` to match.

## Environment install

Run this on each role's host.  What each one needs:

- **bridge host** — `radical.edge` (it runs the bridge).
- **driver (laptop)** — `radical.edge` + `rhapsody` (the driver imports
  both; the edge backend it talks to is client-side).
- **target (Perlmutter)** — the full stack (it executes the tasks).

The install below is the full stack; it's safe to run verbatim on all
three (the extra packages on the bridge/laptop are harmless).

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

> On the driver and bridge hosts, `dragonhpc` / `mpi4py` are not strictly
> required (the Dragon imports in `amsc.py` are lazy and only fire on the
> target). Installing the full list anyway keeps the environments
> identical and avoids surprises.

After this, the target has the wrapper the IRI job will launch:

```
${AMSC_DIR:-$HOME/.amsc}/ve/bin/radical-edge-wrapper.sh
```

## TLS certificate (generate on the bridge host)

The bridge serves over HTTPS.  Because the laptop and the Perlmutter edge
now reach it by its **public hostname**, the cert must be valid for that
hostname — a `CN=localhost` cert will fail hostname validation when a
client connects to `https://<bridge-host>:8000`.  Generate a self-signed
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

Then distribute the **cert** (never the key) to the other two roles so
they can validate the bridge they connect to:

```sh
# to the laptop and to Perlmutter
scp "$HOME/.radical/edge/bridge_cert.pem" you@laptop:~/.radical/edge/bridge_cert.pem
scp "$HOME/.radical/edge/bridge_cert.pem" perlmutter.nersc.gov:~/.radical/edge/bridge_cert.pem
```

The child edge on Perlmutter resolves the cert from its own
`~/.radical/edge/bridge_cert.pem` (or `$RADICAL_BRIDGE_CERT`); the driver
on the laptop does the same.  See [FAQ.md](FAQ.md) if you hit a cert error.

## NERSC token (driver/laptop only)

The IRI bearer token is read on the host that runs `amsc.py` and sent to
the bridge once at connect time.  The bridge holds it in process memory
only — it is never written to disk on the bridge side.

```sh
export AMSC_DIR="${AMSC_DIR:-$HOME/.amsc}"
mkdir -p "$AMSC_DIR"

# NERSC IRI Globus access token — paste the literal token string.
echo "$NERSC_GLOBUS_TOKEN" > "$AMSC_DIR/token_nersc"
chmod 600 "$AMSC_DIR/token_nersc"
```

Obtain the token per NERSC's IRI / Globus documentation.  The token is
short-lived; if a run fails to connect, refresh it (see [FAQ.md](FAQ.md)).

