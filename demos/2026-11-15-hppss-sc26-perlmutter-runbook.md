# HPPSS @ SC26: Perlmutter build and run runbook

Build and standalone run of the HPPSS demo stack on Perlmutter: OpenFOAM,
Dragon, RHAPSODY, radex and the `radexWrite` function object from
[rhapsody-plugins-openfoam](https://github.com/CrayLabs/rhapsody-plugins-openfoam),
then the `pitzDaily-optimize` example on one CPU node. This is W1 of the
[demo plan](2026-11-15-hppss-sc26.md); W7 turns it into pinned installs.

- **Validated:** 2026-10-26, NERSC project amsc007.
- **Location:** everything lives under `$PSCRATCH/hppss` (sources, builds,
  venv, runs). Scratch is purged after about 8 weeks without access, which
  is enough for the demo but not a permanent install.
- **Effort:** about 15 minutes of login-node work plus a 1-hour OpenFOAM
  build job.

## 1. Versions

| Piece | Version | Note |
|---|---|---|
| Python | `cray-python/3.12.12` | radex's Python client needs 3.12; the default `python` module is 3.13; never 3.12.0 (breaks Dragon) |
| Dragon | `dragonhpc==0.15.0` (wheel) | the pin of RHAPSODY's `demo/hppss` branch, see below |
| RHAPSODY | `radical-cybertools/rhapsody` branch `demo/hppss` (`d80d415`) | `pip install '.[dragon]'`; `main` at validation plus the 0.15.0 pin (rhapsody#109) |
| radex | `radical-cybertools/radex` `c4b4d1f` | C++ library via CMake, Dragon backend only; Python client from `src/python` |
| OpenFOAM | ESI v2412, built from source | no NERSC module and no usable spack package; the plugin's example cases were made with v2412 |
| Plugin | `CrayLabs/rhapsody-plugins-openfoam` `306d3f4` | builds unchanged |
| Toolchain | PrgEnv-gnu, gcc 14.3.0, cmake 3.28.3, cray-mpich 9.1.0 | |

**Dragon version.** radex `main` calls `DDict::wait_for_keys()`, which the
`dragonhpc` 0.14.1 wheel headers lack (0.14.2 and 0.15.0 have it). RHAPSODY
`main` still pins `dragonhpc==0.14.1`; rhapsody#109 raises the pin to 0.15.0
after validating it on Perlmutter (unit, integration and GPU suites, plus
pitzDaily). The demo installs RHAPSODY from the `demo/hppss` branch, which
carries that pin, so `pip install '.[dragon]'` yields 0.15.0. The branch
stays fixed until someone moves it deliberately. W1 itself first ran on 0.14.2;
section 5 has both.

## 2. Environment file

One file sets up every shell, including inside allocations:
`$PSCRATCH/hppss/env.sh`.

```sh
module unload python conda 2>/dev/null
module load cray-python/3.12.12
export HPPSS=$PSCRATCH/hppss
source $HPPSS/ve/bin/activate
export PATH=$HPPSS/ve/bin:$PATH          # Dragon needs the venv bin on PATH
export SLURM_EXPORT_ENV=ALL
export PYTHONNOUSERSITE=1
export DRAGON_INCLUDE_DIR=$(dragon-config -o | sed 's/^-I *//')
export DRAGON_LIB_DIR=$(dragon-config -l | sed 's/^-L *//; s/ .*//')
export RADEX_INSTALL_DIR=$HPPSS/radex/install
export RADEX_DIR=$RADEX_INSTALL_DIR
module load PrgEnv-gnu cray-mpich
[ -f $HPPSS/openfoam/OpenFOAM-v2412/etc/bashrc ] && source $HPPSS/openfoam/OpenFOAM-v2412/etc/bashrc
```

## 3. Build

### 3.1 Python, Dragon, RHAPSODY (login node)

```sh
mkdir -p $PSCRATCH/hppss && cd $PSCRATCH/hppss
module unload python conda; module load cray-python/3.12.12
python3 -m venv ve && source ve/bin/activate
pip install -U pip
pip install dragonhpc==0.15.0 cython numpy scikit-optimize
dragon-config -o && dragon-config -l     # must print include and lib flags
# write env.sh (section 2), then:
source $PSCRATCH/hppss/env.sh

git clone -b demo/hppss https://github.com/radical-cybertools/rhapsody.git
git clone https://github.com/radical-cybertools/radex.git
git clone https://github.com/CrayLabs/rhapsody-plugins-openfoam.git

(cd rhapsody && pip install '.[dragon]')
pip show dragonhpc | grep Version        # must say 0.15.0 (a 0.14.1 means the wrong rhapsody branch)
python -c "from rhapsody.backends.data import DragonDataBackend"
```

Never `pip install -e`; radex's own docs install Dragon that way, use the
wheel instead.

### 3.2 radex (login node)

```sh
cd $HPPSS/radex
cmake -S . -B build -DCMAKE_INSTALL_PREFIX=$PWD/install -DCMAKE_CXX_COMPILER=g++ \
      -DBUILD_SMARTREDIS=OFF -DBUILD_TESTS=OFF -DBUILD_EXAMPLES=OFF -DENABLE_PYTHON=OFF
cmake --build build -j 16 && cmake --install build      # -> install/lib64/libradex.so
pip install ./src/python
python -c "from radex.clients.core import DragonClient"
```

`ENABLE_PYTHON=OFF` keeps CMake from running pip itself; the client is
installed explicitly instead. The library lands in `install/lib64`, not
`lib`; both radex's `setup.py` and the plugin's `Allwmake` find it there.

### 3.3 OpenFOAM v2412 (compute node, ~1 hour)

```sh
mkdir -p $HPPSS/openfoam && cd $HPPSS/openfoam
curl -fLO https://dl.openfoam.com/source/v2412/OpenFOAM-v2412.tgz
curl -fLO https://dl.openfoam.com/source/v2412/ThirdParty-v2412.tgz
tar xzf OpenFOAM-v2412.tgz && tar xzf ThirdParty-v2412.tgz
cat > OpenFOAM-v2412/etc/prefs.sh <<EOF
export WM_MPLIB=CRAY-MPICH
export WM_PROJECT_USER_DIR=$HPPSS/openfoam/user-v2412
EOF
```

`prefs.sh` selects Cray MPICH (serial runs are enough for the demo, but the
MPI layer still has to build) and moves the user directory, where the
plugin installs its libraries (`$FOAM_USER_LIBBIN`), from `$HOME/OpenFOAM`
to scratch.

Build job, `$HPPSS/openfoam/build-openfoam.sbatch`:

```sh
#!/bin/bash
#SBATCH -N 1 -C cpu -q regular -t 02:00:00 -A amsc007
#SBATCH -J of-v2412-build -o <HPPSS>/openfoam/build-%j.log
module load PrgEnv-gnu cray-mpich
source <HPPSS>/openfoam/OpenFOAM-v2412/etc/bashrc
export WM_NCOMPPROCS=128
cd $WM_PROJECT_DIR
/usr/bin/time -v ./Allwmake -j -s -l 2>&1 | tail -80
foamInstallationTest 2>&1 | tail -30
```

Replace `<HPPSS>` with the expanded `$PSCRATCH/hppss` path. The build took
61 minutes on 128 cores and ends with `foamInstallationTest` reporting
"Critical systems ok" (153 libraries, 285 applications). Expected noise in
the log: `make: ... install Error 1 (ignored)` from ThirdParty and boost
warnings.

### 3.4 Plugin and function objects (login node)

```sh
source $PSCRATCH/hppss/env.sh            # now also sources OpenFOAM
cd $HPPSS/rhapsody-plugins-openfoam
./Allwmake 2>&1 | tee allwmake.log
ls $FOAM_USER_LIBBIN                     # libradexBase/IO/Read/Write.so
python -c "import rhapsody_plugins.openfoam as rof; print(rof.CaseDefinition)"
```

Two messages are harmless:

- `Error: could not find libsmartredis under` — `SMARTREDIS_LIB_DIR` stays
  empty, so `-L$(SMARTREDIS_LIB_DIR) -lsmartredis` in `Make/options`
  becomes `-L -lsmartredis` and nothing links SmartRedis. radex built
  without SmartRedis replaces its Redis client with a stub.
- `wmkdepend: parse error while scanning 'radex/client_base.hpp'`.

Check: `ldd $FOAM_USER_LIBBIN/libradexWrite.so | grep 'not found'` prints
nothing.

## 4. Run

Run from a copy on scratch: cases resolve from `OPENFOAM_CASE_DIR` and
write `./run-<id>` directories into the working directory.

```sh
mkdir -p $HPPSS/runs
cp -r $HPPSS/rhapsody-plugins-openfoam/examples/{pitzDaily-optimize,openfoam-cases} $HPPSS/runs/
```

Smaller or matched runs use wrappers next to the example drivers instead of
edits, for example `driver-video.py`:

```python
import asyncio
import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location(
    "driver_staged", pathlib.Path(__file__).with_name("driver-staged.py"))
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)

if __name__ == "__main__":
    asyncio.run(driver.main(ensemble_size=4, max_iterations=4))
```

`$HPPSS/runs/run-w1.sh` runs each driver named in `DRIVERS` in its own
directory and collects per-case solver times:

```sh
#!/bin/bash
source $PSCRATCH/hppss/env.sh
export OPENFOAM_CASE_DIR=$PSCRATCH/hppss/runs/openfoam-cases
summarize() {  # per-case solver time = last ExecutionTime in the case's simpleFoam log
    for d in run-pD-*; do
        t=$(grep -h "^ExecutionTime" $(grep -l "^Case.*$d\$" rhapsody.session.*/task.*.stdout 2>/dev/null) 2>/dev/null | tail -1)
        echo "$d ${t:-NO-ExecutionTime}"
    done
}
for drv in ${DRIVERS:-staged video}; do
    w=$PSCRATCH/hppss/runs/$drv; rm -rf $w; cp -r $PSCRATCH/hppss/runs/pitzDaily-optimize $w; cd $w
    echo "=== $drv start $(date +%T) on $(hostname)"
    /usr/bin/time -v dragon driver-$drv.py > $drv.log 2>&1
    echo "=== $drv rc=$? end $(date +%T)"
    grep -E '^Iteration|WARNING|Traceback|Error' $drv.log | head -40
    grep -E 'Elapsed \(wall' $drv.log
    summarize > case-times.txt; cat case-times.txt
done
```

```sh
sbatch -N 1 -C cpu -q regular -t 01:30:00 -A amsc007 -J hppss-w1 \
       -o $PSCRATCH/hppss/runs/w1-%j.log $PSCRATCH/hppss/runs/run-w1.sh
```

Where things end up:

- Driver output: `runs/<driver>/<driver>.log`.
- Solver output: not in the case directory. RHAPSODY writes each task's
  stdout/stderr to `rhapsody.session.*/task.NNNNNN.{stdout,stderr}` in the
  working directory; the OpenFOAM header line `Case : .../run-pD-NNNN` maps
  a task to its case.
- Every solver log should contain `radexIO: connected to the radex store
  via dragon`, which confirms the C++ side reached the Dragon dictionary.

## 5. Measured results (2026-10-26)

One CPU node (128 cores), serial `simpleFoam` per case.

| Run | Cases | Wall time | Iterations | Best loss per iteration |
|---|---|---|---|---|
| `driver-staged.py` defaults (5 per batch, max 10) | 20 | 1:48 | 4, converged | 0.213, 0.0196, 0.00326, 9.39e-06 |
| Video size (4 per batch, 4 batches) | 16 | 1:40 | 4 (cap) | 0.213, 0.0196, 0.0196, 1.17e-04 |
| `driver-staged.py`, Dragon 0.15.0 (2026-10-28) | 20 | 2:01 | 4, converged | identical to the 0.14.2 run |
| Video size, Dragon 0.15.0 | 16 | 1:47 | 4 (cap) | identical to the 0.14.2 run |

- **Per case:** mean 9 s (`ClockTime`), typically 5-11 s; one case in the
  first batch takes 38-39 s. Cases converge in 240-350 solver steps.
- **Per batch** (slowest case): 38, 9, 9, 9 s (staged); 39, 10, 11, 9 s
  (video).
- **Wall time** also covers Dragon start-up, the radex store and the
  optimizer: the four staged batches account for 65 of the 108 s.
- **Best result:** `avgInlets` -1.90306 against the target -1.9.
- **Dragon 0.15.0** (Slurm 60474809 with RHAPSODY v0.6.0; 60476206 with
  `demo/hppss`, staged 2:07): results are identical, and solver time per
  case is unchanged (mean 9.2 s). The extra 7-13 s of wall time comes from
  slower Dragon start-up and teardown, which also shows in RHAPSODY's own
  test suites.

`driver-async.py` (no batches: a new case starts whenever one finishes;
2026-10-27, same node type), for comparison:

| Run | Cases | Wall time | Result |
|---|---|---|---|
| Matched to staged (5 in flight, target 1e-3), wrapper `driver-asyncmatched.py` | 30 | 1:23 | target reached after 26 cases (the 4 in flight then finish); best loss 2.44e-04 |
| Example defaults (32 in flight, target 1e-5, max 128 cases) | 128 | 3:02 | target never reached, runs to the case cap; best loss 2.42e-04, found by case 46 |

- **Matched async vs. staged:** async finished about 25 s sooner, but it
  also never hit a slow case (max 12 s, against the staged run's 38 s
  first-batch case), so the gap is not all down to removing the batch
  barrier. It ran more cases (30 vs. 20) and stopped at a looser best loss:
  the staged run happened to hit 9.4e-06 in its fourth batch. Each driver
  ran once, and the case order in the async driver is not deterministic, so
  treat these as single samples.
- **Per case:** mean 7.9 s (matched) and 9.3 s (defaults, 32 concurrent on
  one node), the same range as the staged runs.
- **Async defaults:** the 1e-5 target is out of reach here, so the default
  run measures throughput (128 cases in 3 minutes on one node), not
  convergence.

## 6. Troubleshooting

- **All cases print `WARNING: <id> failed`:** `gather_results` swallows
  every exception. Check that `libradexWrite.so` is in `$FOAM_USER_LIBBIN`
  and read one task's `stdout`/`stderr` in `rhapsody.session.*` first.
- **Dragon hangs instead of exiting:** see the Dragon-on-Perlmutter pitfalls
  (venv `bin/` on `PATH`, `SLURM_EXPORT_ENV=ALL`, never Python 3.12.0, never
  prepend `/usr/lib64` to `LD_LIBRARY_PATH`). Launch drivers with `dragon
  driver-*.py`, not `python`.
- **radex fails to compile with `no member named 'wait_for_keys'`:** the
  Dragon wheel is too old (needs >= 0.14.2); use the pinned `dragonhpc==0.15.0`.
