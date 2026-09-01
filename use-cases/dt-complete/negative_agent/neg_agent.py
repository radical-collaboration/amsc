"""
This agent is a demo of the "SciAgents" abstraction.

This NEGATIVE_Agent calls the "Neg_Inference_Only_Investigator" which is an
investigator that only does inference. Since there is only one investigator, the
NEGATIVE_Agent is a very light wrapper that merely passes through all requests to the
investigator.

---
More about SciAgents:

A SciAgent is used to group together multiple investigators that operate on the
same input / output DataTypes under one roof. It also has a "model selector"
task that runs in-stream, deciding what investigator and model to run for
inference.

The purpose of the Science Agent is to contain one physics property. The
investigator then provides the implementation.
This implementation can have an Active Learner, and publishes one surrogate.


The alternative is to have only an investigator, and put all the various
surrogates inside one active learning loop. This is absolutely acceptable (see
the m3dc1 investigator), though the SciAgent format is more generalizable and scalable.
It separates the concerns from training a specific surrogate architecture from
the decision making of what surrogate to train/run when.
"""

import asyncio

from radical.asyncflow import WorkflowEngine
from digitaltwin.components import ModelInvestigator, TypedData, SciAgent
from digitaltwin.runtime import RuntimeAPI

from .inference_only_investigator import Neg_Inference_Only_Investigator

from dtypes import *

import logging

logger = logging.getLogger(__name__)


class NEGATIVE_Agent(SciAgent):
    def __init__(self, flow: WorkflowEngine):
        super().__init__(flow)
        self.flow = flow

        # no learning. Simple investigator
        self.investigator = Neg_Inference_Only_Investigator(flow)

        @self.flow.function_task
        async def model_select(
            in_data: TypedData, i_id=self.investigator.get_id(), model_kwargs={}
        ):
            return i_id  # default to latest model

        self.model_selector = model_select

    async def main_loop(self, runtime: RuntimeAPI):
        # Start up the investigator
        runtime.start_investigator(self.investigator)

        runtime.set_model_selection_task(self.model_selector)

        # set the investigator for primary inference
        runtime.update_model_selector(i_id=self.investigator.get_id())
