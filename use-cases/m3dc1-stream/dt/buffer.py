"""
Buffer: generic data buffer. Batches inputs and only emits when done.

The digital twin framework provides a stream-processing dataflow paradigm. It already
comes with a Windowing feature via its BARRIER. However, it leaves the logic up to the user of
how their windows should be defined.

So, you need a split task that generates an event of when to trigger the barrier.

Dataflow Digital Twin graph:

SENSOR --> BUFFER_EVENT_EMIT --> BARRIER --> SINK
                |                   |
                +--------------> BARRIER --> goes nowhere

From this, the BUFFER_EVENT_EMIT is a SPLIT task. It takes in one stream and
generates two.

The BARRIER is provided by the DT framework. This file simply implements the
buffer event split task, and a null sink.

The null sink is needed to drain the queues.

"""

import time

from digitaltwin import SplitTask, TypedData, UtilityTask
from dtypes import BUFFER_EVENT, SYNC_SENSOR


class BufferEventEmit(SplitTask):
    def __init__(self, flow, buffer_length):
        super().__init__(flow)
        self.buffer_length = buffer_length
        self.counter = 0

    async def main_loop(self, runtime, in_data: TypedData):
        self.counter += 1
        out_data = TypedData(
            SYNC_SENSOR,
        )
        if self.counter >= self.buffer_length:
            # emit event
            return in_data, TypedData(BUFFER_EVENT, time.time())

        return in_data, None


# this is needed to
class DeadSink(UtilityTask):
    def __init__(self, flow):
        super().__init__(flow)

    async def main_loop(self, runtime, in_data):
        pass  # do nothing.
