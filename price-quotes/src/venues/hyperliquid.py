"""Hyperliquid spot orderbook (CLOB). POST /info, no auth.

levels[0] = bids, levels[1] = asks; each level is {px, sz, n}.
Prices exclude the ~0.025% taker fee.
"""
from typing import List

from ..config import PAIRS, BUY_SIZES_USDC, SELL_SIZES, USER_AGENT
from ..quote import Quote
from ..vwap import vwap_sell, vwap_buy

VENUE = "hyperliquid"
ENDPOINT = "https://api.hyperliquid.xyz/info"


async def _l2book(session, coin: str):
    body = {"type": "l2Book", "coin": coin, "nSigFigs": 5}
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    async with session.post(ENDPOINT, json=body, headers=headers, timeout=20) as r:
        r.raise_for_status()
        data = await r.json()
    levels = data["levels"]
    return levels[0], levels[1]  # bids, asks


async def fetch(session, pair: str) -> List[Quote]:
    cfg = PAIRS[pair]
    rows: List[Quote] = []
    try:
        bids, asks = await _l2book(session, cfg["hyperliquid_coin"])
    except Exception:
        return rows

    for size_base in SELL_SIZES[pair]:
        rate = vwap_sell(bids, size_base)
        rows.append(Quote(VENUE, pair, "SELL", rate if rate else 0.0,
                          size_base=size_base, depth_ok=rate is not None))

    for size_quote in BUY_SIZES_USDC:
        rate = vwap_buy(asks, size_quote)
        rows.append(Quote(VENUE, pair, "BUY", rate if rate else 0.0,
                          size_quote=size_quote, depth_ok=rate is not None))

    # Keep every bracket; insufficient-depth rows carry rate=0.0 and
    # depth_ok=False so consumers can filter on the flag (WHERE depth_ok).
    return rows
