#!/usr/bin/env python3
"""Executable shim that lets Flux run a Python function task.

Flux only launches executables, so rhapsody's flux backend (patched clone)
submits a jobspec whose executable is `python flux_fn_wrapper.py <blob>`, where
<blob> is a cloudpickle of (function, args, kwargs). This process deserializes
and calls it. This is the function->executable bridge Flux inherently needs.
"""
import sys
import cloudpickle

with open(sys.argv[1], "rb") as f:
    fn, args, kwargs = cloudpickle.load(f)
rv = fn(*args, **kwargs)
if len(sys.argv) > 2:  # optional return-value capture (general case)
    with open(sys.argv[2], "wb") as f:
        cloudpickle.dump(rv, f)
