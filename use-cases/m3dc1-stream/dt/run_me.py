"""
M3DC1 Digital Twin - a DT wrapper of the M3DC1 streaming surrogate example

Complete Digital Twin graph:

MOCK_SENSOR --> M3DC1_Investigator --> OUTPUT TASK


"""

import argparse
import asyncio
from concurrent.futures import ProcessPoolExecutor
from radical.asyncflow import WorkflowEngine
from rhapsody.backends import ConcurrentExecutionBackend

from digitaltwin.runtime import DTRuntime
from digitaltwin.streaming import connect_stream_client
from digitaltwin.components import NULL_DTYPE

from amsc_investigator import M3DC1_Investigator, OutputSink
from dtypes import *

from radical.asyncflow.logging import init_default_logger
from rhapsody.backends.data.redis import RedisDataBackend
import logging

logger = logging.getLogger(__name__)


async def main(candidates, args):
    max_iter = args.max_iter
    r2_threshold = args.r2_threshold
    max_len = args.buffer_maxlen
    window_size = args.window_size

    redis_backend = await RedisDataBackend()
    endpoint = redis_backend.endpoints[0]
    redis_endpoint = endpoint.serialize()

    init_default_logger(logging.WARNING)
    logging.getLogger("radical.asyncflow").setLevel(logging.WARNING)
    logging.getLogger("rhapsody").setLevel(logging.WARNING)

    # create engine
    exe = await ConcurrentExecutionBackend(ProcessPoolExecutor())
    flow = await WorkflowEngine.create(backend=exe)

    # create the twin's namespaced stream client
    pubsub_client = await connect_stream_client("M3DC1-Demo")

    runtime = DTRuntime(flow, pubsub_client)

    ###################
    # create tasks and investigators

    m3dc1 = M3DC1_Investigator(
        flow,
        candidates=candidates,
        max_iter=max_iter,
        buffer_max=max_len,
        window_size=window_size,
        r2_threshold=r2_threshold,
        redis_endpoint=redis_endpoint,
        redis_key="M3DC1",
    )
    output_sink = OutputSink(flow)

    # create graph
    runtime.add_input(M3DC1_SENSOR, M3DC1_MOCK_CHANNEL)
    runtime.add_investigator(m3dc1, M3DC1_SENSOR, M3DC1_PREDICTION)
    runtime.add_task(output_sink, M3DC1_PREDICTION, NULL_DTYPE)

    runtime.print_graph()
    runtime.start()

    # let it run
    await asyncio.sleep(45)
    print("SHUTDOWN")
    await runtime.stop()
    await flow.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="M3DC1 streaming surrogate — sensor input version."
    )
    parser.add_argument(
        "--candidates",
        default="rf,mlp",
        help="Comma-separated model families: rf, mlp, gbr, ridge.",
    )
    parser.add_argument("--max-iter", type=int, default=3)
    parser.add_argument("--r2-threshold", type=float, default=0.80)
    parser.add_argument(
        "--buffer-maxlen",
        type=int,
        default=1000,
        help="Maximum observations retained in the sensor buffer.",
    )
    parser.add_argument(
        "--window-size",
        type=int,
        default=10,
        help="Window size for sensor data",
    )
    args = parser.parse_args()
    candidates = [x.strip() for x in args.candidates.split(",") if x.strip()]

    if len(candidates) < 2:
        parser.error("Need at least two candidates for ParallelActiveLearner.")

    asyncio.run(main(candidates, args))
