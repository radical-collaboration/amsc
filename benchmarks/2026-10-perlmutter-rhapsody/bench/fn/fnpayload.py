"""Function-task payload, the function-mode analogue of the C `taskrun`.

`taskfn(dur, ncores, uid, recdir)` busy-occupies `ncores` physical cores for
`dur` seconds and writes a host/affinity/timestamp record, exactly like the
executable payload. Multi-core occupancy is real: the busy loop lives in C
(libspin.so) and is called via ctypes, which releases the GIL, so `ncores`
Python threads each run on their own core.

Importable on every node (workers import it); keep it dependency-free.
"""
from __future__ import annotations

import ctypes
import json
import os
import socket
import threading
import time

_SO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libspin.so")
_lib = ctypes.CDLL(_SO)
_lib.spin.argtypes = [ctypes.c_double]
_lib.spin.restype = ctypes.c_double


def taskfn(dur: float, ncores: int, uid: str, recdir: str) -> str:
    t_start = time.time()
    if dur > 0:
        ths = [threading.Thread(target=_lib.spin, args=(float(dur),))
               for _ in range(max(1, int(ncores)))]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
    t_end = time.time()
    try:
        aff = sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        aff = []
    rec = {"uid": uid, "host": socket.gethostname(), "pid": os.getpid(),
           "ncores": int(ncores), "dur": float(dur),
           "t_start": t_start, "t_end": t_end, "cpus": len(aff)}
    try:
        os.makedirs(recdir, exist_ok=True)
        with open(os.path.join(recdir, uid + ".json"), "w") as f:
            json.dump(rec, f)
    except OSError:
        pass
    return uid


def noop(uid):
    """Dispatch-only payload: no filesystem record, no syscalls -- isolates
    pure dispatch rate from per-task record I/O."""
    return uid
