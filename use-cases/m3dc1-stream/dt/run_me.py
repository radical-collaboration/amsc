"""
M3DC1 Digital Twin - a DT wrapper of the M3DC1 streaming surrogate example

Complete Digital Twin graph:

MOCK_SENSOR --> BUFFER_EVENT_TASK --> BARRIER --> M3DC1_Investigator --> OUTPUT TASK
                      |                 |||
                      +-------------> BARRIER --> DEAD SINK


"""

import argparse
import asyncio
from concurrent.futures import ProcessPoolExecutor
from digitaltwin import Barrier
from radical.asyncflow import WorkflowEngine
from rhapsody.backends import ConcurrentExecutionBackend

from digitaltwin.runtime import DTRuntime
from digitaltwin.streaming import connect_stream_client
from digitaltwin.components import NULL_DTYPE

from amsc_investigator import M3DC1_Investigator, OutputSink
from buffer import BufferEventEmit, DeadSink
from dtypes import *

from radical.asyncflow.logging import init_default_logger
import logging

logger = logging.getLogger(__name__)

# put it all together
# sensor channel --> model --> data_sink
#
# The sensor is external: run sensor.py in its own terminal.


async def main(candidates, args):
    max_iter = args.max_iter
    r2_threshold = args.r2_threshold
    max_len = args.buffer_maxlen
    window_size = args.buffer_size
    redis_endpoint = args.redis_endpoint

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

    # for buffer:
    buffer_event_task = BufferEventEmit(flow, window_size)
    barrier = Barrier("sensor_windowing_buffer")
    SENSOR_WINDOW = barrier.add_dtype(SYNC_SENSOR, hard=False)

    dead_sink = DeadSink(flow)

    barrier.add_dtype(BUFFER_EVENT, hard=True)

    # for investigator
    m3dc1 = M3DC1_Investigator(
        flow,
        candidates,
        max_iter,
        max_len,
        r2_threshold,
        redis_endpoint,
        "M3DC1",
    )
    output_sink = OutputSink(flow)

    # create graph
    runtime.add_input(M3DC1_SENSOR, M3DC1_MOCK_CHANNEL)
    runtime.add_barrier(barrier)
    runtime.add_data_split_task(
        buffer_event_task, M3DC1_SENSOR, [SYNC_SENSOR, BUFFER_EVENT]
    )
    runtime.add_task(dead_sink, BUFFER_EVENT, NULL_DTYPE)
    runtime.add_investigator(m3dc1, SENSOR_WINDOW, M3DC1_PREDICTION)
    runtime.add_task(output_sink, M3DC1_PREDICTION, NULL_DTYPE)

    runtime.print_graph()
    runtime.start()

    # let it run
    await asyncio.sleep(45)
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
        default=100,
        help="Maximum observations retained in the sensor buffer.",
    )
    parser.add_argument(
        "--buffer-size",
        type=int,
        default=100,
        help="Window size for sensor data",
    )
    parser.add_argument(
        "--redis-endpoint",
        type=str,
        default="localhost:6379",
        help="Redis endpoint used in M3D1C investigator.",
    )
    args = parser.parse_args()
    candidates = [x.strip() for x in args.candidates.split(",") if x.strip()]

    if len(candidates) < 2:
        parser.error("Need at least two candidates for ParallelActiveLearner.")

    asyncio.run(main(candidates, args))
