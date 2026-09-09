from digitaltwin.components import UtilityTask, TypedData

GREEN = "\033[92m"
RESET = "\033[0m"


# this is needed to
class OutputSink(UtilityTask):
    def __init__(self, flow):
        super().__init__(flow)

    async def main_loop(self, runtime, in_data: TypedData):

        prediction = in_data.data[0].data
        neg_val = in_data.data[1].data

        if prediction is not None:
            prediction = prediction[0]
            print(f"{GREEN}[OUT]: Gamma: {prediction}. NEGATIVE: {neg_val}{RESET}")
        else:
            print(f"{GREEN}[OUT]: Gamma model not ready. NEGATIVE: {neg_val}{RESET}")
