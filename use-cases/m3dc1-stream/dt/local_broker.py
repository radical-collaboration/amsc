"""Standalone stream broker for the two-terminal demos.

Addresses come from configuration (`DT_STREAM_PUB_ADDR` /
`DT_STREAM_SUB_ADDR`, loopback defaults) -- the same resolution the
demos use, so both terminals agree without any literal in the code.
"""

from digitaltwin.config import stream_addresses
from digitaltwin.streaming import ZMQ_Broker

if __name__ == "__main__":
    broker = ZMQ_Broker(*stream_addresses())

    publish_addr, subscribe_addr = broker.bind()
    print(
        f"stream broker: publish to {publish_addr}, subscribe on {subscribe_addr}",
        flush=True,
    )

    broker.run()
