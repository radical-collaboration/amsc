"""
Random value sensor stream
"""

from __future__ import annotations

import argparse
import asyncio
import random

from digitaltwin import ChannelPublisher

from neg_dtypes import *

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="RAND mock sensor.")
    parser.add_argument(
        "--sensor-rate",
        type=float,
        default=2.0,
        help="Mock sensor emission rate in observations/second (default: 2).",
    )
    parser.add_argument(
        "--sensor-seed",
        type=int,
        default=42,
        help="RNG seed for the rand sensor.",
    )

    args = parser.parse_args()

    random.seed(args.sensor_seed)

    async def main():
        publisher = await ChannelPublisher.open(RAND_SENSOR_CHANNEL)

        while True:
            val = random.random()
            await publisher.publish(val)

            await asyncio.sleep(1 / args.sensor_rate)

    if __name__ == "__main__":
        asyncio.run(main())
