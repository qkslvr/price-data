"""Binance spot orderbook (CEX CLOB). GET /api/v3/depth, no auth.

bids/asks are arrays of [price, qty] strings. cbBTC has no native market, so
BTCUSDC is used as the BTC price reference.
"""
from typing import List

from ..config import PAIRS, BUY_SIZES_USDC, SELL_SIZES, USER_AGENT
from ..quote import Quote
from ..vwap import vwap_sell, vwap_buy

VENUE = "binance"
ENDPOINT = "https://api.binance.com/api/v3/depth"


def _norm(levels):
    return [{"px": p, "sz": q} for p, q in levels]


async def _depth(session, symbol: str):
    params = {"symbol": symbol, "limit": 100}
    headers = {"User-Agent": USER_AGENT}
    async with session.get(ENDPOINT, params=params, headers=headers, timeout=20) as r:
        r.raise_for_status()
        data = await r.json()
    return _norm(data["bids"]), _norm(data["asks"])


async def fetch(session, pair: str) -> List[Quote]:
    cfg = PAIRS[pair]
    rows: List[Quote] = []
    try:
        bids, asks = await _depth(session, cfg["binance_symbol"])
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

    return rows
