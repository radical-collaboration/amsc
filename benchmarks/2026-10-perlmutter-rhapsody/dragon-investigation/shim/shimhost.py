"""Surgical host-child entrypoint (NOT a source edit to rhapsody or dragon).

Run ONLY as the rhapsody backend-host child, via a RemoteBackendProxy
launch_prefix override:

    dragon <ports> <hostlist> python <this file> [ignored args...]

Unlike a global sitecustomize, this runs in exactly one process -- the host
child -- so dragon's own backend / global-services / transport processes keep
the mp-monkeypatch they rely on.  Here we trigger the patch, then restore the
genuine multiprocessing.connection.Client/Listener (dragon 0.14.1 leaves its
fallback _original_Client = None), and hand off to the real, unmodified host
module as if it were run with `python -m rhapsody.backends.multiproc.host`."""
import runpy
import socket
import sys

sys.stderr.write("[rhap-shimhost] running on host=%s\n" % socket.gethostname())
sys.stderr.flush()

try:
    import dragon  # noqa: F401  triggers patch_multiprocessing() once
    import multiprocessing.connection as _mc
    from dragon.mpbridge.monkeypatching import original_multiprocessing as _om

    _mc.Client = _om.connection_Client
    _mc.Listener = _om.connection_Listener
    sys.stderr.write(
        "[rhap-shimhost] Client restored -> %s.%s\n"
        % (_mc.Client.__module__, getattr(_mc.Client, "__qualname__", _mc.Client))
    )
    sys.stderr.flush()
except Exception as _e:
    sys.stderr.write("[rhap-shimhost] restore failed: %r\n" % (_e,))
    sys.stderr.flush()

runpy.run_module("rhapsody.backends.multiproc.host", run_name="__main__")
