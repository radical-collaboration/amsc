"""Standalone (pilot-free) Raptor worker.

Launched once per srun rank.  Each rank is an independent worker process that:

  * reads the master's bridge addresses from the JSON info file,
  * connects a ``ru.zmq.Getter`` to the request queue (pull tasks) and a
    ``ru.zmq.Putter`` to the result queue (push results),
  * subscribes to the control pubsub for the ``terminate`` broadcast and
    publishes periodic ``worker_register`` / heartbeat messages,
  * runs up to ``nslots`` task subprocesses concurrently via a thread pool,
    with a bounded local prefetch queue providing backpressure (and thereby
    load balancing across workers).

Execution is modelled on raptor's ``_dispatch_proc`` (fork/exec of an
executable + arguments), minus the agent/registry machinery.

Usage:
    python -m raptor_standalone.worker --info <info_file> [--nslots N]
                                       [--prefetch P]
"""

import os
import sys
import time
import json
import queue
import socket
import argparse
import subprocess
import threading as mt

import radical.utils as ru

from .master import CTRL_TOPIC

_OUT_CAP = 16 * 1024   # cap captured stdout/stderr per task (bytes)


# ------------------------------------------------------------------------------
#
class StandaloneWorker(object):

    # --------------------------------------------------------------------------
    #
    def __init__(self, info, nslots, prefetch, workdir=None):
        '''
        Args:
            info (dict): bridge-address dict with keys ``req_addr_get``,
                ``res_addr_put``, ``ctrl_addr_pub``, ``ctrl_addr_sub`` (and
                optionally ``workdir``).  Built either from CLI address args
                or read from the master info file.
        '''

        self._info    = info

        self._node    = socket.gethostname()
        procid        = os.environ.get('SLURM_PROCID', '0')
        self._uid     = 'worker.%s.%s' % (self._node, procid)
        self._nslots  = nslots
        self._workdir = workdir or self._info.get('workdir', os.getcwd())
        self._term    = mt.Event()

        # bounded local queue: nslots * prefetch tasks may sit buffered.
        # when full, the Getter listener blocks in the cb -> stops pulling ->
        # the request bridge serves other (idle) workers instead.
        maxq          = max(1, self._nslots * max(1, prefetch))
        self._queue   = queue.Queue(maxsize=maxq)

        self._n_done  = 0
        self._stat_lock = mt.Lock()

        # connect comm endpoints
        self._res_put  = ru.zmq.Putter('raptor_res', self._info['res_addr_put'])
        self._ctrl_pub = ru.zmq.Publisher('raptor_ctrl',
                                           url=self._info['ctrl_addr_pub'])
        self._ctrl_sub = ru.zmq.Subscriber('raptor_ctrl',
                                            url=self._info['ctrl_addr_sub'],
                                            topic=CTRL_TOPIC, cb=self._ctrl_cb)
        time.sleep(0.5)

        # start executor threads
        self._threads = list()
        for i in range(self._nslots):
            t = mt.Thread(target=self._exec_loop, args=(i,))
            t.daemon = True
            t.start()
            self._threads.append(t)

        # start request getter (listener thread invokes _request_cb)
        self._req_get = ru.zmq.Getter('raptor_req', self._info['req_addr_get'],
                                       cb=self._request_cb)

        # heartbeat / (re-)register thread
        self._hb_thread = mt.Thread(target=self._hb_loop)
        self._hb_thread.daemon = True
        self._hb_thread.start()


    # --------------------------------------------------------------------------
    #
    def _hb_loop(self):
        msg = {'cmd': 'worker_register',
               'arg': {'uid'   : self._uid,
                       'node'  : self._node,
                       'nslots': self._nslots}}
        n = 0
        while not self._term.is_set():
            try:
                self._ctrl_pub.put(CTRL_TOPIC, msg)
            except Exception:
                pass
            # register aggressively for the first few seconds (slow joiner),
            # then fall back to a slow heartbeat.
            n += 1
            time.sleep(0.5 if n < 10 else 5.0)


    # --------------------------------------------------------------------------
    #
    def _ctrl_cb(self, topic, msg):
        if msg.get('cmd') == 'terminate':
            self._term.set()
        return True


    # --------------------------------------------------------------------------
    #
    def _request_cb(self, tasks):
        '''enqueue incoming tasks; block (backpressure) when local queue full.'''
        for task in ru.as_list(tasks):
            while not self._term.is_set():
                try:
                    self._queue.put(task, timeout=0.5)
                    break
                except queue.Full:
                    continue
        return True


    # --------------------------------------------------------------------------
    #
    def _exec_loop(self, slot):
        while not self._term.is_set():
            try:
                task = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._run_task(task, slot)
            except Exception as e:
                task['stdout']    = ''
                task['stderr']    = 'worker exec failed: %s' % e
                task['exit_code'] = 1
                task['exception'] = repr(e)
                task['worker']    = self._uid
                self._res_put.put(task)
            finally:
                with self._stat_lock:
                    self._n_done += 1


    # --------------------------------------------------------------------------
    #
    def _load_fn(self, blob):
        '''deserialize a cloudpickled callable once, cached per blob.'''
        cache = self.__dict__.setdefault('_fn_cache', {})
        fn = cache.get(blob)
        if fn is None:
            import cloudpickle
            with open(blob, 'rb') as f:
                fn = cloudpickle.load(f)
            cache[blob] = fn
        return fn

    def _run_func(self, task, slot):
        '''native function call in-slot (no fork/exec); GIL-releasing payloads
        (ctypes/numpy) run truly concurrent across slot threads.'''
        try:
            fn = self._load_fn(task['function_blob'])
            rv = fn(*task.get('args', ()), **(task.get('kwargs') or {}))
            task['return_value'] = rv if isinstance(
                rv, (int, float, str, bool, type(None))) else repr(rv)
            task['exit_code'] = 0
            task['stdout'] = ''
            task['stderr'] = ''
        except Exception as e:
            task['exit_code'] = 1
            task['exception'] = repr(e)
            task['stderr'] = 'function call failed: %r' % e
        task['worker'] = self._uid
        self._res_put.put(task)

    def _run_task(self, task, slot):
        '''fork/exec an executable task (raptor PROC mode), or an in-slot
        native function call when task['mode'] == "function".'''

        if task.get('mode') == 'function':
            return self._run_func(task, slot)

        uid  = task['uid']
        exe  = task['executable']
        args = [str(a) for a in task.get('arguments', [])]
        tout = task.get('timeout') or None

        env  = dict(os.environ)
        for k, v in task.get('environment', {}).items():
            env[str(k)] = str(v)
        env['RP_TASK_ID'] = uid
        env['RAPTOR_WORKER'] = self._uid
        env['RAPTOR_SLOT']   = str(slot)

        sbox = task.get('sandbox')
        if sbox:
            ru.rec_makedir(sbox)
        cwd = sbox or self._workdir

        out, err, ret = '', '', 1
        try:
            proc = subprocess.Popen([exe] + args, env=env, cwd=cwd,
                                    stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    close_fds=True)
            try:
                raw_out, raw_err = proc.communicate(timeout=tout)
                ret = proc.returncode
            except subprocess.TimeoutExpired:
                proc.kill()
                raw_out, raw_err = proc.communicate()
                ret = 1
                err = 'timeout (>%s)\n' % tout
            out += raw_out[:_OUT_CAP].decode(errors='replace')
            err += raw_err[:_OUT_CAP].decode(errors='replace')
        except Exception as e:
            err = 'exec failed: %s' % e
            ret = 1

        task['stdout']    = out
        task['stderr']    = err
        task['exit_code'] = ret
        task['worker']    = self._uid
        self._res_put.put(task)


    # --------------------------------------------------------------------------
    #
    def run(self):
        '''block until terminate; then drain in-flight tasks briefly and exit.'''
        while not self._term.is_set():
            time.sleep(0.5)

        # drain: let already-dequeued tasks finish for a short grace period
        t0 = time.time()
        while not self._queue.empty() and time.time() - t0 < 10:
            time.sleep(0.2)


# ------------------------------------------------------------------------------
#
def main():
    p = argparse.ArgumentParser()
    # Address args are the preferred bootstrap: the master bakes the ZMQ
    # bridge addresses straight into the srun argv, so no shared-FS round-trip
    # is needed at worker startup.
    p.add_argument('--req-addr',      default=None, help='request queue get addr')
    p.add_argument('--res-addr',      default=None, help='result queue put addr')
    p.add_argument('--ctrl-pub-addr', default=None, help='control pubsub pub addr')
    p.add_argument('--ctrl-sub-addr', default=None, help='control pubsub sub addr')
    # Fallback: read the same addresses from the master info JSON file.
    p.add_argument('--info',     default=None, help='master info JSON file (fallback)')
    p.add_argument('--nslots',   type=int, default=0,
                   help='concurrent task slots (default: cpus on node)')
    p.add_argument('--prefetch', type=int, default=2,
                   help='local prefetch depth multiplier (default 2)')
    p.add_argument('--workdir',  default=None)
    args = p.parse_args()

    addr_args = (args.req_addr, args.res_addr,
                 args.ctrl_pub_addr, args.ctrl_sub_addr)

    if all(addr_args):
        # preferred: addresses passed directly on the command line
        info = {'req_addr_get' : args.req_addr,
                'res_addr_put' : args.res_addr,
                'ctrl_addr_pub': args.ctrl_pub_addr,
                'ctrl_addr_sub': args.ctrl_sub_addr,
                'workdir'      : args.workdir}
        src = 'argv'
    elif args.info:
        # fallback: read the master info file from the shared filesystem
        with open(args.info) as fin:
            info = json.load(fin)
        src = 'info-file'
    else:
        p.error('provide --req-addr/--res-addr/--ctrl-pub-addr/--ctrl-sub-addr '
                'or --info')

    nslots = args.nslots
    if nslots <= 0:
        nslots = int(os.environ.get('SLURM_CPUS_ON_NODE') or os.cpu_count() or 1)

    w = StandaloneWorker(info, nslots, args.prefetch, args.workdir)
    sys.stderr.write('worker %s bootstrap via %s\n' % (w._uid, src))
    sys.stderr.write('worker %s up: %d slots on %s\n'
                     % (w._uid, nslots, w._node))
    sys.stderr.flush()
    w.run()
    sys.stderr.write('worker %s exiting (%d tasks done)\n'
                     % (w._uid, w._n_done))
    sys.stderr.flush()


if __name__ == '__main__':
    main()
