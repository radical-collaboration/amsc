"""pitzDaily Bayesian optimization driven through ORBIT.

Same optimization as ``driver-staged.py`` in the rhapsody-plugins-openfoam
example, but the solver tasks and the radex store run on a remote ORBIT
endpoint:

* ``OrbitExecutionBackend`` runs the ``simpleFoam`` tasks in the endpoint's
  Dragon runtime.
* ``OrbitDataBackend`` starts the radex DDict in that same runtime; only its
  lifecycle crosses ORBIT, the data stays on the endpoint.
* Results are read from radex by one function task per batch on the endpoint,
  which returns ``(final_step, avg_inlets)`` per case; the loss and the
  optimizer stay here.

Case preparation (``foamDictionary``) runs locally, so this process needs the
OpenFOAM environment and a filesystem shared with the endpoint.
"""

import argparse
import asyncio
import os
import sys
import time

import skopt

import rhapsody_plugins.openfoam as rof
from rhapsody.api.task import BaseTask, ComputeTask
from rhapsody.backends.data.orbit import OrbitDataBackend
from rhapsody.backends.execution.orbit import OrbitExecutionBackend

from pitzdaily_case import KEpsilonParameters, pitzDailyCase, pitzDailyResults

TARGET_AVGINLETS = -1.9
MAX_SOLVER_ITER = 2000

default_params = KEpsilonParameters(14.855, 0.09, 1.44, 1.92)


def initialize_optimizer():
    lower_bound = KEpsilonParameters(default_params.epsilon * 0.2, 0.05, 1.0, 1.5)
    upper_bound = KEpsilonParameters(default_params.epsilon * 4, 0.15, 1.5, 3.0)
    bounds = list(zip(lower_bound.as_optimizer_list(), upper_bound.as_optimizer_list()))
    return skopt.Optimizer(dimensions=bounds, random_state=1, base_estimator="gp")


def gather_on_endpoint(descriptor, identifiers):
    """Runs on the endpoint (defined in __main__, so cloudpickle ships it by value): read final step and avgInlets per case from radex."""
    from radex.clients.core import DragonClient
    from radex.handles.handles import IncomingHandle
    from rhapsody_plugins.openfoam.utils import OFKey

    client = DragonClient(descriptor, timeout=30)
    out = {}
    for ident in identifiers:
        try:
            final_step = client.get_scalar(IncomingHandle(OFKey(ident, "final_step")))
            avg = client.get_scalar(
                IncomingHandle(OFKey(ident, "avgInlets", time=final_step, rank=0)))
            out[ident] = (int(final_step), float(avg))
        except Exception as e:
            out[ident] = (None, repr(e))
    return out


def results_from(entry, target):
    final_step, avg = entry
    if final_step is None:
        return pitzDailyResults(final_step=None, avg_inlets=None, loss=None, converged=False)
    return pitzDailyResults(final_step=final_step, avg_inlets=avg,
                            loss=(avg - target) ** 2,
                            converged=final_step < MAX_SOLVER_ITER)


async def main(args):
    t0 = time.time()
    # WORKAROUND (ORBIT: task notifications are broadcast to every client of
    # the plugin and matched by uid only; uids come from a per-process
    # counter): give each client its own uid range so they cannot collide.
    BaseTask._uid_counter = args.uid_offset
    exec_be = OrbitExecutionBackend(broker_url=args.broker_url,
                                    endpoint_name=args.endpoint,
                                    backends=["dragon"],
                                    participant_name="client.%s" % args.prefix,
                                    init_timeout=300)
    await exec_be
    store = OrbitDataBackend(exec_be, "dragon", name="radex_%s" % args.prefix,
                             managers_per_node=1, n_nodes=1,
                             total_mem=512 * 1024 * 1024, working_set_size=4)
    await store
    descriptor = store.endpoints[0].serialize()
    print("[%6.1fs] client %s: endpoint %s ready, radex store up, target %.3g"
          % (time.time() - t0, args.prefix, args.endpoint, args.target), flush=True)

    registry = rof.OFExecutableRegistry()
    optimizer = initialize_optimizer()
    next_index, iteration = 0, 0
    best, best_loss, n_done = None, 1e10, 0
    history = []

    async with rof.OFSession(backends=[exec_be]) as session:
        while iteration < args.max_iterations and best_loss > args.convergence:
            t_it = time.time()
            params = optimizer.ask(n_points=args.ensemble_size)
            cases = [pitzDailyCase(registry, KEpsilonParameters(*p),
                                   "%s-%04d" % (args.prefix, next_index + k),
                                   descriptor, args.target)
                     for k, p in enumerate(params)]
            next_index += args.ensemble_size

            solve = [t for c in cases for t in c.stages["solve"].to_tasks()]
            await session.submit_tasks(solve)
            await asyncio.wait_for(session.wait_tasks(solve), timeout=args.task_timeout)

            gather = ComputeTask(function=gather_on_endpoint,
                                 args=(descriptor, [c.identifier for c in cases]))
            await session.submit_tasks([gather])
            await asyncio.wait_for(session.wait_tasks([gather]), timeout=300)
            found = gather.get("return_value") or {}
            if gather.state != "DONE":
                print("  gather task %s: %s %s" % (gather.uid, gather.state,
                      (gather.get("exception") or gather.get("stderr") or "")[:300]), flush=True)
            else:
                errs = [v[1] for v in found.values() if v and v[0] is None]
                if errs or len(found) < len(cases):
                    print("  gather: %d/%d missing, first error: %s"
                          % (len(cases) - (len(found) - len(errs)), len(cases),
                             (errs[0] if errs else "no entry")[:300]), flush=True)

            for case in cases:
                case.results = results_from(found.get(case.identifier, (None, "missing")),
                                            args.target)
                n_done += 1
                if case.results.converged:
                    optimizer.tell(case.parameters.as_optimizer_list(), case.results.loss)
                    if case.results.loss < best_loss:
                        best, best_loss = case, case.results.loss
            iteration += 1
            ok = sum(1 for c in cases if c.results.avg_inlets is not None)
            history.append((iteration, time.time() - t0, best_loss))
            print("[%6.1fs] client %s | iteration %2d | cases %3d (%d/%d with results) "
                  "| batch %5.1fs | best loss %.3g"
                  % (time.time() - t0, args.prefix, iteration, n_done, ok, len(cases),
                     time.time() - t_it, best_loss), flush=True)

        if args.foreign_prefix:
            # isolation check: the other client's first case must not be in our store
            probe = ComputeTask(function=gather_on_endpoint,
                                args=(descriptor, ["%s-0000" % args.foreign_prefix]))
            await session.submit_tasks([probe])
            await asyncio.wait_for(session.wait_tasks([probe]), timeout=300)
            seen = (probe.get("return_value") or {}).get("%s-0000" % args.foreign_prefix)
            if probe.state != "DONE" or seen is None:
                verdict = "UNKNOWN (probe %s: %s)" % (probe.state, str(probe.get("exception"))[:200])
            elif seen[0] is None:
                verdict = "no (isolated): %s" % seen[1][:120]
            else:
                verdict = "YES (leak)"
            print("ISOLATION client %s: %s-0000 in own store: %s"
                  % (args.prefix, args.foreign_prefix, verdict), flush=True)

    await store.shutdown()
    if best is not None:
        print("RESULT client %s: %d iterations, %d cases, best %s; %s, wall %.1fs"
              % (args.prefix, iteration, n_done, best.parameters.pretty_print(),
                 best.results.pretty_print(), time.time() - t0), flush=True)
    if args.plot and history:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(5, 3))
        ax.semilogy([h[0] for h in history], [h[2] for h in history], "o-")
        ax.set_xlabel("iteration")
        ax.set_ylabel("best loss")
        fig.tight_layout()
        fig.savefig("loss-%s.png" % args.prefix, dpi=150)
    return best is not None and best.results.avg_inlets is not None


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--broker-url", required=True)
    p.add_argument("--endpoint", required=True)
    p.add_argument("--prefix", default="pD", help="case/run-dir prefix, unique per client")
    p.add_argument("--ensemble-size", type=int, default=5)
    p.add_argument("--max-iterations", type=int, default=10)
    p.add_argument("--convergence", type=float, default=1e-3)
    p.add_argument("--task-timeout", type=float, default=900)
    p.add_argument("--target", type=float, default=TARGET_AVGINLETS,
                   help="target avgInlets (default %(default)s)")
    p.add_argument("--foreign-prefix", default=None,
                   help="another client's prefix: check its cases are not in our store")
    p.add_argument("--uid-offset", type=int, default=0,
                   help="start of this client's task-uid range (workaround, see main())")
    p.add_argument("--plot", action="store_true")
    return p.parse_args()


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main(parse_args())) else 1)
