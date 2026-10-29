"""Standalone, pilot-free Raptor master/worker high-throughput executor.

This package extracts the core of RADICAL-Pilot's Raptor (the master/worker
ZMQ request/result protocol) into a standalone form that runs *without* an
rp.Session, pilot, agent bootstrap, or MongoDB.  It reuses radical.utils ZMQ
comm primitives (Queue/Putter/Getter + PubSub) -- which are themselves
pilot-free -- and a worker dispatch loop modelled on
``radical.pilot.raptor.worker_default.DefaultWorker``.

Layout:
  - master.py : RaptorMaster -- creates the ZMQ bridges, submits tasks,
                collects results, drives worker lifecycle.
  - worker.py : worker entry point launched via srun on each node/rank.
  - rhapsody_backend.py : a rhapsody BaseBackend subclass driving a RaptorMaster.
"""

from .master import RaptorMaster

__all__ = ['RaptorMaster']
