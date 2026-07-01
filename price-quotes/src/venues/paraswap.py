"""ParaSwap aggregator (Base). REST, no auth (User-Agent required).

The `/prices` endpoint returns a `priceRoute` whose `destAmount` is the routed
output amount (raw units of destToken) for an exact-input swap. Like KyberSwap,
ParaSwap routes/splits across many DEX pools, so each quote is aggregated.
"""
import asyncio
from typing import List

from ..config import PAIRS, BUY_SIZES_USDC, SELL_SIZES, TOKENS, USER_AGENT, BASE_CHAIN_ID, to_raw, from_raw
from ..quote import Quote

VENUE = "paraswap"
ENDPOINT = "https://api.paraswap.io/prices"


async def _price(session, token_in: str, token_out: str, amount_in_raw: int) -> int:
    """GET one exact-input (side=SELL) quote; return destAmount (raw units)."""
    params = {
        "srcToken": TOKENS[token_in]["address"],
        "destToken": TOKENS[token_out]["address"],
        "srcDecimals": TOKENS[token_in]["decimals"],
        "destDecimals": TOKENS[token_out]["decimals"],
        "amount": str(amount_in_raw),
        "side": "SELL",
        "network": BASE_CHAIN_ID,
    }
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    async with session.get(ENDPOINT, params=params, headers=headers, timeout=20) as r:
        r.raise_for_status()
        data = await r.json()
    return int(data["priceRoute"]["destAmount"])


async def fetch(session, pair: str) -> List[Quote]:
    cfg = PAIRS[pair]
    base, quote = cfg["base"], cfg["quote"]
    rows: List[Quote] = []

    async def sell(size_base: float):
        try:
            raw_out = await _price(session, base, quote, to_raw(size_base, base))
            usdc_out = from_raw(raw_out, quote)
            return Quote(VENUE, pair, "SELL", usdc_out / size_base,
                         size_base=size_base, raw_out=raw_out)
        except Exception:
            return None

    async def buy(size_quote: float):
        try:
            raw_out = await _price(session, quote, base, to_raw(size_quote, quote))
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
