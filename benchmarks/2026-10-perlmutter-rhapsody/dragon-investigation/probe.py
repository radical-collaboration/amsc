#!/usr/bin/env python3
"""Probe the dragon mp-monkeypatch state in THIS process.

Prints whether DRAGON_PATCH_MP is in env, whether multiprocessing.connection.Client
is the real one or dragon's patched one, and whether dragon.workflows.batch.Batch
is importable.  No dragon runtime is started.
"""
import os, sys

print(f"[probe pid={os.getpid()}] argv={sys.argv[1:]}")
print(f"  DRAGON_PATCH_MP env = {os.environ.get('DRAGON_PATCH_MP', '<unset>')!r}")

# Import rhapsody exactly as `-m rhapsody.backends.multiproc.host` would:
# importing the package triggers backends/__init__ -> import dragon (if it patches).
import importlib
host_mod_pre = None
import multiprocessing.connection as mpc
print(f"  Client BEFORE rhapsody import: {mpc.Client.__module__}.{getattr(mpc.Client,'__qualname__',mpc.Client)}")

try:
    import rhapsody  # noqa
    print("  imported rhapsody OK")
except Exception as e:
    print(f"  import rhapsody FAILED: {e!r}")

import multiprocessing.connection as mpc2
cl = mpc2.Client
origin = "REAL (multiprocessing)" if cl.__module__.startswith("multiprocessing") else f"PATCHED ({cl.__module__})"
print(f"  Client AFTER rhapsody import:  {cl.__module__}.{getattr(cl,'__qualname__',cl)}  -> {origin}")

# Also show what host.py's own top-level import would bind:
from multiprocessing.connection import Client as HostClient
print(f"  host-style `from ... import Client`: {HostClient.__module__}.{getattr(HostClient,'__qualname__',HostClient)}")

# Can we still get the dragon Batch API?
try:
    from dragon.workflows.batch import Batch  # noqa
    print("  dragon.workflows.batch.Batch import OK")
except Exception as e:
    print(f"  dragon Batch import FAILED: {e!r}")

# Is the real original reachable?
try:
    from dragon.mpbridge.monkeypatching import original_multiprocessing as om
    print(f"  original_multiprocessing.connection_Client = {om.connection_Client.__module__}.{om.connection_Client.__qualname__}")
except Exception as e:
    print(f"  original_multiprocessing unavailable: {e!r}")

try:
    import dragon.mpbridge.context as _ctx
    print(f"  dragon.mpbridge.context._original_Client = {_ctx._original_Client!r}")
except Exception as e:
    print(f"  context._original_Client check failed: {e!r}")
print(f"  get_start_method() = {__import__('multiprocessing').get_start_method()!r}")
