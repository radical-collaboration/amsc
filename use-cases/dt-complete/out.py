
from digitaltwin.components import UtilityTask, TypedData

# this is needed to
class OutputSink(UtilityTask):
    def __init__(self, flow):
        super().__init__(flow)

    async def main_loop(self, runtime, in_data: TypedData):
        if in_data.data is None:
            return  # don't print out None... that means there wasn't a model ready yet
        print("Received: ", in_data.data)
