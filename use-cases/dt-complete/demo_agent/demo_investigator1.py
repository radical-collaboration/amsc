"""
The Demo Investigator is a simple investigator that triggers an active learning
workflow per input on callback. It batches the input when the active learning
workflow is running, so there is at most one workflow running at once.

This is a simple example of how to interact with ROSE's AL inside the digital
twin framework. This example shows how to have an active learner where the workflow is launched
from the data stream.

Though Demo Investigator 1 & 2 are identical, this is to demonstrate that I can
have different "implementations" of a physics property. I can have each
investigator focus on a single surrogate, have a single active learner loop, or
other custom logic / lifecycle management. The DEMO_AGENT selects the
investigator / surrogate to run.

Note: Compare this to the M3DC1 investigator which instructs the simulation itself to wait for
data. Therefore, the M3DC1 investigator requires a side-channel as the
simulation is fetching the data. The approach here does not require REDIS or
some side-channel method for sending data as the workflow is built already
knowing the input data.

"""

DO_PRINT = False

import asyncio
import random
from typing import Any
import cloudpickle
from digitaltwin import (
    ModelInvestigator,
    RuntimeAPI,
    TypedData,
)
from radical.asyncflow import WorkflowEngine

from rose.al.active_learner import Learner
from .demo_dtypes import DEMO_PREDICTION


class Demo_Investigator_1(ModelInvestigator):
    def __init__(self, flow: WorkflowEngine):
        super().__init__(flow)

        # Learners
        self.acl = Learner(flow)

        self.data_update = asyncio.Event()
        self.dataset: list[Any] = []
        self.new_values: list[Any] = []

        # Learning tasks..............
        @self.acl.simulation_task(as_executable=False)
        async def simulation(*args):
            import time

            time.sleep(1)
            return time.time()

        self.simulation = simulation

        @self.acl.training_task(as_executable=False)
        async def training(*args):
            return random.random()

        self.training = training

        @self.flow.function_task
        async def do_inference(in_data: TypedData, model=None):
            # gamma = in_data.data[0].data
            # neg = in_data.data[1].data

            # out = [gamma, neg]
            # if gamma is None:
            #     out[0] = None

            return TypedData(DEMO_PREDICTION, in_data.data)

        self.inference = do_inference

    async def input_callback(self, in_data: TypedData):
        # only trigger update for ~10% of inputs
        if random.random() > 0.1:
            return
        self.new_values.append(in_data)
        self.data_update.set()

    async def main_loop(self, runtime: RuntimeAPI):
        # run the pipeline
        runtime.subscribe_to_topic(runtime.ON_INPUT, self.input_callback)
        runtime.set_inference_task(self.inference)
        runtime.publish_new_model()
        counter = 0
        while True:
            await self.data_update.wait()

            self.dataset += self.new_values
            self.new_values = []

            # Start the active learning workflow on the dataset.
            if DO_PRINT:
                print("[Demo Agent / Investigator 1]: Start AL Workflow")
            model = await self.training(self.simulation(self.dataset))

            # publish model and accuracy metrics.
            acc = random.random()
            if DO_PRINT:
                print(
                    f"[Demo Agent / Investigator 1]: Publish model {counter}. Acc: {acc}"
                )
            runtime.publish_new_model({"model": counter}, {"acc": acc})
            self.data_update.clear()
            counter += 1
