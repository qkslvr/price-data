"""Run every venue across every pair in parallel and return unified Quote rows."""
import asyncio
from typing import List

import aiohttp

from .config import PAIRS
from .quote import Quote
from .venues import kyberswap, bebop, hyperliquid, binance, kalqix
from .venues import uniswap, paraswap

# Each entry: (label, coroutine factory taking (session, pair)).
VENUE_FETCHERS = [
    ("kyberswap", kyberswap.fetch),
    ("paraswap", paraswap.fetch),
    ("bebop", bebop.fetch),
    ("uniswap", uniswap.fetch_uniswap),
    ("pancakeswap", uniswap.fetch_pancakeswap),
    ("hyperliquid", hyperliquid.fetch),
    ("binance", binance.fetch),
    ("kalqix", kalqix.fetch),
]


async def fetch_all(pairs=None) -> List[Quote]:
    pairs = pairs or list(PAIRS.keys())
    rows: List[Quote] = []

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        tasks = []
        meta = []
        for pair in pairs:
            for label, fn in VENUE_FETCHERS:
                tasks.append(fn(session, pair))
                meta.append((label, pair))

        results = await asyncio.gather(*tasks, return_exceptions=True)

    for (label, pair), res in zip(meta, results):
        if isinstance(res, Exception):
            print(f"  ! {label}/{pair} failed: {res}")
            continue
        rows.extend(res)
    return rows
