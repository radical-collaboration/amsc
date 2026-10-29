"""Standalone (pilot-free) Raptor master.

The master owns three ZMQ bridges created with radical.utils (all pilot-free):

  * ``req``  -- a ``ru.zmq.Queue``   carrying task requests  master -> workers
  * ``res``  -- a ``ru.zmq.Queue``   carrying task results   workers -> master
  * ``ctrl`` -- a ``ru.zmq.PubSub``  carrying control msgs (worker register,
                heartbeat, terminate) both directions, broadcast.

Workers (launched independently via srun) read the bridge addresses from a
JSON "info file" on the shared filesystem, connect, and start pulling tasks.
The request queue is a PUSH/REP bridge: many worker REQ sockets pull from it,
so tasks are naturally load-balanced (round-robin) across all workers with no
central scheduler.
"""

import os
import json
import time
import threading as mt

import radical.utils as ru

TERM_TOPIC = 'raptor'
CTRL_TOPIC = 'raptor'


# ------------------------------------------------------------------------------
#
class RaptorMaster(object):

    # --------------------------------------------------------------------------
    #
    def __init__(self, workdir, bulk_size=1, result_cb=None, uid=None):
        '''
        Args:
            workdir (str): shared-FS directory; the info file is written here
                           and worker uids/logs are rooted here.
            bulk_size (int): max number of tasks handed to a worker per pull.
                             Small = finer load balancing, large = less comm.
            result_cb (callable): optional ``cb(task_dict, state_str)`` invoked
                             for every completed task from the collector thread.
            uid (str): master id (default auto-generated).
        '''

        self._uid       = uid or ru.generate_id('raptor.master')
        self._workdir   = os.path.abspath(workdir)
        self._bulk_size = bulk_size
        self._user_cb   = result_cb

        ru.rec_makedir(self._workdir)

        self._lock      = mt.Lock()
        self._pending   = dict()          # uid: task   (submitted, not done)
        self._done      = dict()          # uid: task   (completed)
        self._workers   = dict()          # uid: {last_hb, node, nslots}
        self._n_submit  = 0
        self._n_collect = 0
        self._term      = mt.Event()

        # ----------------------------------------------------------------------
        # request queue: master puts tasks, workers get them
        self._req_q = ru.zmq.Queue('raptor_req', cfg={'channel'  : 'raptor_req',
                                                      'uid'      : self._uid + '.req',
                                                      'type'     : 'queue',
                                                      'path'     : self._workdir,
                                                      'stall_hwm': 0,
                                                      'bulk_size': self._bulk_size})
        self._req_q.start()

        # result queue: workers put results, master gets them
        self._res_q = ru.zmq.Queue('raptor_res', cfg={'channel'  : 'raptor_res',
                                                      'uid'      : self._uid + '.res',
                                                      'type'     : 'queue',
                                                      'path'     : self._workdir,
                                                      'stall_hwm': 0,
                                                      'bulk_size': self._bulk_size})
        self._res_q.start()

        # control pubsub: register / heartbeat / terminate (broadcast)
        self._ctrl_q = ru.zmq.PubSub('raptor_ctrl', cfg={'channel': 'raptor_ctrl',
                                                         'uid'    : self._uid + '.ctrl',
                                                         'type'   : 'pubsub',
                                                         'path'   : self._workdir})
        self._ctrl_q.start()

        # give the bridges a moment to bind
        time.sleep(1)

        # master endpoints
        self._req_put = ru.zmq.Putter('raptor_req', str(self._req_q.addr_put))
        self._res_get = ru.zmq.Getter('raptor_res', str(self._res_q.addr_get),
                                       cb=self._result_cb)
        self._ctrl_pub = ru.zmq.Publisher('raptor_ctrl',
                                           url=str(self._ctrl_q.addr_pub))
        self._ctrl_sub = ru.zmq.Subscriber('raptor_ctrl',
                                            url=str(self._ctrl_q.addr_sub),
                                            topic=CTRL_TOPIC, cb=self._ctrl_cb)
        time.sleep(0.5)

        # write the info file workers use to connect
        self._info = {'uid'         : self._uid,
                      'req_addr_get': str(self._req_q.addr_get),
                      'res_addr_put': str(self._res_q.addr_put),
                      'ctrl_addr_pub': str(self._ctrl_q.addr_pub),
                      'ctrl_addr_sub': str(self._ctrl_q.addr_sub),
                      'bulk_size'   : self._bulk_size,
                      'workdir'     : self._workdir}

        self._info_file = os.path.join(self._workdir, 'raptor.master.json')
        with open(self._info_file, 'w') as fout:
            json.dump(self._info, fout, indent=2)


    # --------------------------------------------------------------------------
    #
    @property
    def info_file(self):
        return self._info_file

    @property
    def uid(self):
        return self._uid

    @property
    def addresses(self):
        '''the four ZMQ bridge addresses workers need to connect.'''
        return {'req_addr_get' : self._info['req_addr_get'],
                'res_addr_put' : self._info['res_addr_put'],
                'ctrl_addr_pub': self._info['ctrl_addr_pub'],
                'ctrl_addr_sub': self._info['ctrl_addr_sub']}

    def worker_cli_args(self):
        '''
        Return the ``--req-addr/--res-addr/--ctrl-pub-addr/--ctrl-sub-addr``
        argv fragment so the master can bake its bridge addresses straight
        into the worker launch command -- no shared-FS info file needed.
        '''
        a = self.addresses
        return ['--req-addr',      a['req_addr_get'],
                '--res-addr',      a['res_addr_put'],
                '--ctrl-pub-addr', a['ctrl_addr_pub'],
                '--ctrl-sub-addr', a['ctrl_addr_sub']]

    @property
    def workers(self):
        with self._lock:
            return dict(self._workers)


    # --------------------------------------------------------------------------
    #
    def _ctrl_cb(self, topic, msg):
        '''receive worker register / heartbeat messages.'''

        cmd = msg.get('cmd')
        arg = msg.get('arg', {})

        if cmd in ('worker_register', 'worker_heartbeat'):
            uid = arg.get('uid')
            if not uid:
                return True
            with self._lock:
                w = self._workers.setdefault(uid, {'uid': uid})
                w['last_hb'] = time.time()
                w['node']    = arg.get('node')
                w['nslots']  = arg.get('nslots')
        return True


    # --------------------------------------------------------------------------
    #
    def _result_cb(self, tasks):
        '''receive completed tasks from workers (runs in Getter listener thread).'''

        tasks = ru.as_list(tasks)
        for task in tasks:
            uid = task['uid']
            ec  = task.get('exit_code')
            if ec is None:
                ec = -1
            state = 'DONE' if int(ec) == 0 else 'FAILED'
            task['state'] = state

            with self._lock:
                self._pending.pop(uid, None)
                self._done[uid] = task
                self._n_collect += 1

            if self._user_cb:
                try:
                    self._user_cb(task, state)
                except Exception:
                    pass
        return True


    # --------------------------------------------------------------------------
    #
    def wait_workers(self, count, timeout=120):
        '''block until at least ``count`` workers have registered.'''

        t0 = time.time()
        while True:
            with self._lock:
                n = len(self._workers)
            if n >= count:
                return n
            if time.time() - t0 > timeout:
                raise RuntimeError('only %d/%d workers registered after %ds'
                                   % (n, count, timeout))
            time.sleep(0.2)


    # --------------------------------------------------------------------------
    #
    def submit(self, tasks):
        '''
        Submit a batch of task dicts.  Each task needs at least ``uid`` and
        ``executable``; optional: ``arguments`` (list), ``environment`` (dict),
        ``cores`` (int, default 1), ``timeout`` (float|None), ``sandbox`` (str).
        '''

        tasks = ru.as_list(tasks)
        norm  = list()
        for task in tasks:
            if 'uid' not in task:
                task['uid'] = ru.generate_id('task.%(counter)06d', ru.ID_CUSTOM)
            task.setdefault('arguments',   [])
            task.setdefault('environment', {})
            task.setdefault('cores',       1)
            task.setdefault('timeout',     None)
            with self._lock:
                self._pending[task['uid']] = task
                self._n_submit += 1
            norm.append(task)

        # push in bulks so a single zmq message is not unbounded
        BULK = 1024
        for i in range(0, len(norm), BULK):
            self._req_put.put(norm[i:i + BULK])

        return [t['uid'] for t in norm]


    # --------------------------------------------------------------------------
    #
    def wait(self, count=None, timeout=None):
        '''
        Wait until ``count`` tasks have completed (default: all submitted).
        Returns the number collected.
        '''

        t0 = time.time()
        while True:
            with self._lock:
                n_done   = self._n_collect
                n_submit = self._n_submit
                n_pend   = len(self._pending)
            target = count if count is not None else n_submit
            if n_pend == 0 and n_done >= target:
                return n_done
            if timeout is not None and time.time() - t0 > timeout:
                raise RuntimeError('timeout: %d/%d done, %d pending'
                                   % (n_done, target, n_pend))
            time.sleep(0.05)


    # --------------------------------------------------------------------------
    #
    @property
    def stats(self):
        with self._lock:
            return {'submitted': self._n_submit,
                    'collected': self._n_collect,
                    'pending'  : len(self._pending),
                    'workers'  : len(self._workers)}


    # --------------------------------------------------------------------------
    #
    def terminate(self):
        '''broadcast terminate to all workers and tear down the bridges.'''

        self._term.set()
        try:
            self._ctrl_pub.put(TERM_TOPIC, {'cmd': 'terminate',
                                            'arg': {'master': self._uid}})
        except Exception:
            pass

        # give workers a moment to receive the broadcast and exit
        time.sleep(2)

        for q in (self._req_q, self._res_q, self._ctrl_q):
            try:
                q.stop()
            except Exception:
                pass


# ------------------------------------------------------------------------------
