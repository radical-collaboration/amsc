"""
Complete Digital Twin - a DT wrapper of the M3DC1 streaming surrogate example

Complete Digital Twin graph:

M3DC1 Mock sensor --> M3DC1 Investigator --
                                           \\ 
                                             --(JOIN)--> DEMO Agent --> OUT  
RAND_VAL sensor  ---> NEGATIVE_Agent ------//


"""

import argparse
import asyncio
from concurrent.futures import ProcessPoolExecutor
from radical.asyncflow import WorkflowEngine
from rhapsody.backends import ConcurrentExecutionBackend
from radical.asyncflow.logging import init_default_logger
from rhapsody.backends.data.redis import RedisDataBackend

# Digital Twin imports
from digitaltwin.runtime import DTRuntime
from digitaltwin.streaming import connect_stream_client
from digitaltwin.components import NULL_DTYPE

# User code imports
from m3dc1.m3dc1_investigator import M3DC1_Investigator
from negative_agent.neg_agent import NEGATIVE_Agent
from demo_agent.demo_agent import DEMO_Agent

from out import OutputSink
from dtypes import *

import logging

logger = logging.getLogger(__name__)


async def main(m3dc1_candidates, other_args):

    # Start engine
    redis_backend = await RedisDataBackend()
    endpoint = redis_backend.endpoints[0]
    redis_endpoint = endpoint.serialize()

    init_default_logger(logging.WARNING)
    logging.getLogger("radical.asyncflow").setLevel(logging.WARNING)
    logging.getLogger("rhapsody").setLevel(logging.WARNING)

    # create engine
    exe = await ConcurrentExecutionBackend(ProcessPoolExecutor())
    flow = await WorkflowEngine.create(backend=exe)

    # Connect to the namespaced stream client
    # create the twin's namespaced stream client
    pubsub_client = await connect_stream_client("Complete-DT")
    runtime = DTRuntime(flow, pubsub_client)

    ############################
    # Create the tasks and investigators

    m3dc1 = M3DC1_Investigator(
        flow,
        candidates=m3dc1_candidates,
        max_iter=other_args.m3dc1_max_iter,
        buffer_max=other_args.m3dc1_buffer_maxlen,
        window_size=other_args.m3dc1_window_size,
        r2_threshold=other_args.m3dc1_r2_threshold,
        redis_endpoint=redis_endpoint,
        redis_key="M3DC1",
    )

    neg_agent = NEGATIVE_Agent(flow)

    demo_agent = DEMO_Agent(flow)

    output_sink = OutputSink(flow)

    ##########################
    # Create Digital Twin description graph

    # sensors
    runtime.add_input(M3DC1_SENSOR, M3DC1_MOCK_CHANNEL)
    runtime.add_input(RAND_SENSOR, RAND_SENSOR_CHANNEL)

    # investigator and agents
    runtime.add_investigator(m3dc1, M3DC1_SENSOR, M3DC1_PREDICTION)
    runtime.add_agent(neg_agent, RAND_SENSOR, NEG_PREDICTION)

    # JOIN
    runtime.add_data_join(JOIN_NEG_M3DC1)

    runtime.add_agent(demo_agent, JOIN_NEG_M3DC1, DEMO_PREDICTION)

    # output
    runtime.add_task(output_sink, DEMO_PREDICTION, NULL_DTYPE)

    runtime.print_graph()
    runtime.start()

    # let it run
    await asyncio.sleep(45)
    print("SHUTDOWN")
    await runtime.stop()
    await flow.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Complete Digital Twin Run")
    parser.add_argument(
        "--m3dc1-candidates",
        default="rf,mlp",
        help="Comma-separated model families: rf, mlp, gbr, ridge.",
    )
    parser.add_argument("--m3dc1-max-iter", type=int, default=3)
    parser.add_argument("--m3dc1-r2-threshold", type=float, default=0.80)
    parser.add_argument(
        "--m3dc1-buffer-maxlen",
        type=int,
        default=1000,
        help="Maximum observations retained in the sensor buffer.",
    )
    parser.add_argument(
        "--m3dc1-window-size",
        type=int,
        default=10,
        help="Window size for sensor data",
    )
    args = parser.parse_args()
    m3dc1_candidates = [
        x.strip() for x in args.m3dc1_candidates.split(",") if x.strip()
    ]

    if len(m3dc1_candidates) < 2:
        parser.error("Need at least two candidates for ParallelActiveLearner.")

    asyncio.run(main(m3dc1_candidates, args))
