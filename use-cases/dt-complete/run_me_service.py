"""
Complete Digital Twin - a DT wrapper of the M3DC1 streaming surrogate example

A Digital Twin as a Service implementation. 

Not fully ready to run yet. The DTaaS is missing some features still: 
- data join (missing .add_data_join() API in client)
- input channels (missing .add_channel() API in client)

Complete Digital Twin graph:

M3DC1 Mock sensor --> M3DC1 Investigator --
                                           \\ 
                                             --(JOIN)--> DEMO Agent --> OUT  
RAND_VAL sensor  ---> NEGATIVE_Agent ------//


"""

import argparse
import asyncio
import os
import time

from radical.orbit import EndpointRuntime
from digitaltwin.service import register_user_modules

# Digital Twin imports
from digitaltwin.components import NULL_DTYPE, TypedData

# User code imports
from m3dc1.m3dc1_investigator import M3DC1_Investigator
from negative_agent.neg_agent import NEGATIVE_Agent
from demo_agent.demo_agent import DEMO_Agent

from out import OutputSink
from dtypes import *

import logging

#############################################
# register user modules that twin will run
import demo_agent.demo_agent
import demo_agent.demo_dtypes
import demo_agent.demo_investigator1
import demo_agent.demo_investigator2
import m3dc1.m3dc1_dtypes
import m3dc1.m3dc1_investigator
import negative_agent.inference_only_investigator
import negative_agent.neg_agent
import negative_agent.neg_dtypes
import dtypes
import out

register_user_modules(
    [
        demo_agent.demo_agent,
        demo_agent.demo_dtypes,
        demo_agent.demo_investigator1,
        demo_agent.demo_investigator2,
        m3dc1.m3dc1_dtypes,
        m3dc1.m3dc1_investigator,
        negative_agent.inference_only_investigator,
        negative_agent.neg_agent,
        negative_agent.neg_dtypes,
        dtypes,
        out,
    ]
)
############################################


logger = logging.getLogger(__name__)

DT_HOST = os.environ.get("DT_SERVICE_HOST", "broker")
TASK_ENDPOINT = os.environ.get("DT_INFERENCE_ENDPOINT") or None

ENGINES = {
    "engines": {
        "inference": {"endpoint_name": "hpc", "backends": ["dragon"]},
        # "learning": {"endpoint_name": "hpc", "backends": ["dragon"]},
    }
}


def main(m3dc1_candidates, other_args):

    logging.basicConfig(level=logging.INFO)
    logging.getLogger("radical.orbit").setLevel(logging.WARNING)

    runtime = EndpointRuntime()
    runtime.start(wait=True)

    # Start redis -- needed by M3DC1. This later would be moved to more of an
    # as-a-service approach.

    try:
        dt = runtime.get_plugin(DT_HOST, "dt", config=ENGINES)
        print(f"[ORBIT Client]: session: {dt.sid}  (reattach with this sid)")

        twin = dt.create_twin()
        print(f"twin: {twin}")

        ############################
        # Package the tasks and investigators

        m3dc1 = dt.package(
            M3DC1_Investigator,
            candidates=m3dc1_candidates,
            max_iter=other_args.m3dc1_max_iter,
            buffer_max=other_args.m3dc1_buffer_maxlen,
            window_size=other_args.m3dc1_window_size,
            r2_threshold=other_args.m3dc1_r2_threshold,
        )

        neg_agent = dt.package(NEGATIVE_Agent)

        demo_agent = dt.package(DEMO_Agent)

        output_sink = dt.package(OutputSink)

        ##########################
        # Create Digital Twin description graph

        # sensors
        dt.add_input(twin, M3DC1_SENSOR, M3DC1_MOCK_CHANNEL)
        dt.add_input(twin, RAND_SENSOR, RAND_SENSOR_CHANNEL)

        # investigator and agents
        dt.add_investigator(twin, m3dc1, M3DC1_SENSOR, M3DC1_PREDICTION)
        dt.add_agent(twin, neg_agent, RAND_SENSOR, NEG_PREDICTION)

        # JOIN
        dt.add_data_join(twin, JOIN_NEG_M3DC1)

        dt.add_agent(twin, demo_agent, JOIN_NEG_M3DC1, DEMO_PREDICTION)

        # output
        dt.add_task(twin, output_sink, DEMO_PREDICTION, NULL_DTYPE)

        # dt.print_graph()

        dt.start(twin)

        # Client-side feedback while the twin runs: the demo is stream
        # driven, so all component output lands on the service.  Poll the
        # twin and probe inference so the client terminal shows lifecycle
        # and predictions too -- and a stuck twin is visible immediately.
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "m3dc1"))
        from m3dc1_mock_sensor import MockM3DC1Sensor

        probe = MockM3DC1Sensor()  # samples only, no pacing
        deadline = time.time() + 240
        while time.time() < deadline:
            time.sleep(10)

            info = dt.twin(twin)
            print(
                f"[ORBIT Client]: state={info['state']}"
                f" calls={info.get('calls') or {}}"
                f" metrics={list((info.get('metrics') or {}).keys())}"
            )

            obs = probe._sample()
            answer = dt.get_inference(
                twin, TypedData(M3DC1_SENSOR, obs), M3DC1_PREDICTION,
                timeout=30,
            )
            print(
                f"[ORBIT Client]: inference"
                f" gamma_true={obs['output_gamma']:.4f}"
                f" -> prediction={answer.data}"
            )

        print("SHUTDOWN")
        dt.twin_close(twin)

    finally:
        runtime.stop()


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

    main(m3dc1_candidates, args)
