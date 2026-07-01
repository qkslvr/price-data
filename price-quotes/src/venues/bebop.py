"""Bebop RFQ / aggregator (Base). REST, no auth (User-Agent required)."""
import asyncio
from typing import List, Optional

from ..config import (PAIRS, BUY_SIZES_USDC, SELL_SIZES, TOKENS, USER_AGENT,
                      DUMMY_TAKER, to_raw, from_raw)
from ..quote import Quote

VENUE = "bebop"
ENDPOINT = "https://api.bebop.xyz/router/base/v1/quote"


async def _quote(session, sell_token: str, buy_token: str, sell_amount_raw: int) -> Optional[int]:
    params = {
        "sell_tokens": TOKENS[sell_token]["address"],
        "buy_tokens": TOKENS[buy_token]["address"],
        "sell_amounts": str(sell_amount_raw),
        "taker_address": DUMMY_TAKER,
    }
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    async with session.get(ENDPOINT, params=params, headers=headers, timeout=20) as r:
        r.raise_for_status()
        data = await r.json()

    # Response may be {"routes": [{"quote": {...}}]} or a bare quote object.
    quote = None
    if isinstance(data.get("routes"), list) and data["routes"]:
        quote = data["routes"][0].get("quote")
    quote = quote or data
    buy_tokens = quote.get("buyTokens") or {}
    want = TOKENS[buy_token]["address"].lower()
    for addr, info in buy_tokens.items():
        if addr.lower() == want:
            return int(info["amount"])
    return None


async def fetch(session, pair: str) -> List[Quote]:
    cfg = PAIRS[pair]
    base, quote = cfg["base"], cfg["quote"]
    rows: List[Quote] = []

    async def sell(size_base: float):
        try:
            raw_out = await _quote(session, base, quote, to_raw(size_base, base))
            if raw_out is None:
                return None
            usdc_out = from_raw(raw_out, quote)
            return Quote(VENUE, pair, "SELL", usdc_out / size_base,
                         size_base=size_base, raw_out=raw_out)
        except Exception:
            return None

    async def buy(size_quote: float):
        try:
            raw_out = await _quote(session, quote, base, to_raw(size_quote, quote))
            if raw_out is None:
                return None
            base_out = from_raw(raw_out, base)
            return Quote(VENUE, pair, "BUY", size_quote / base_out,
                         size_quote=size_quote, raw_out=raw_out)
        except Exception:
            return None

    tasks = [sell(s) for s in SELL_SIZES[pair]] + [buy(s) for s in BUY_SIZES_USDC]
    for q in await asyncio.gather(*tasks):
        if q:
            rows.append(q)
    return rows
