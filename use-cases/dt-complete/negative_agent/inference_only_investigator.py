"""
M3DC1 streaming digital twin.

This is a version of the M3DC1 streaming surrogate that uses the digital twin
framework.

Because we are using one active learner and only care about one physics
property, it's simplest to use just a single DT model investigator (no need for
a ScienceAgent. The point of a science agent is in the event you have various
surrogates with separate ALs)

One tricky part is that the simulation task itself is waiting for streaming data
(opposed to the pipeline waiting and then launching the sim.). This requires a
way to transfer data from the investigator to the simulation task as the
simulation task is running. This example uses REDIS from the Rhapsody Data
Backend.

"""

from digitaltwin import (
    ModelInvestigator,
    RuntimeAPI,
    TypedData,
)
from radical.asyncflow import WorkflowEngine
from .neg_dtypes import NEG_PREDICTION


class Neg_Inference_Only_Investigator(ModelInvestigator):
    def __init__(self, flow: WorkflowEngine):
        super().__init__(flow)

        @self.flow.function_task
        async def do_inference(in_data: TypedData):
            val = in_data.data

            return TypedData(NEG_PREDICTION, -1 * val)

        self.inference = do_inference

    async def main_loop(self, runtime: RuntimeAPI):
        # run the pipeline

        runtime.set_inference_task(self.inference)
        runtime.publish_new_model()
