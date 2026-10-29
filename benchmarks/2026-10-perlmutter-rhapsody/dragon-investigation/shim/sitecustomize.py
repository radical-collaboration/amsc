"""Deployment shim (NOT a source edit to rhapsody or dragon).

Placed on PYTHONPATH; auto-imported at interpreter startup.  Only acts when
running under the dragon launcher (DRAGON_PATCH_MP set).  Dragon 0.14.1 patches
``multiprocessing.connection.Client`` to ``DragonContext.Client`` but never
populates the ``_original_Client`` global it falls back to (``_apply_patches``
is dead code), so any AF_UNIX Client() raises ``TypeError: 'NoneType' object is
not callable``.  We trigger the patch, then restore the real Client/Listener
(kept in ``original_multiprocessing``) so rhapsody's
``multiproc.host`` top-level ``from multiprocessing.connection import Client``
binds the genuine implementation.  The dragon runtime / Batch API are
unaffected (only the mp-monkeypatch of the connection API is reverted)."""
import os
import sys

if os.environ.get("DRAGON_PATCH_MP"):
    try:
        import dragon  # noqa: F401  triggers patch_multiprocessing() once
        import multiprocessing.connection as _mc
        from dragon.mpbridge.monkeypatching import original_multiprocessing as _om

        _mc.Client = _om.connection_Client
        _mc.Listener = _om.connection_Listener
        sys.stderr.write(
            "[rhap-shim] restored multiprocessing.connection.Client -> %s.%s\n"
            % (_mc.Client.__module__, getattr(_mc.Client, "__qualname__", _mc.Client))
        )
        sys.stderr.flush()
    except Exception as _e:  # never break the interpreter
        sys.stderr.write("[rhap-shim] shim failed (continuing): %r\n" % (_e,))
        sys.stderr.flush()
