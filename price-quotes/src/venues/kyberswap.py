"""KyberSwap aggregator (Base). REST, no auth (User-Agent required)."""
import asyncio
from typing import List

from ..config import PAIRS, BUY_SIZES_USDC, SELL_SIZES, TOKENS, USER_AGENT, to_raw, from_raw
from ..quote import Quote

VENUE = "kyberswap"
ENDPOINT = "https://aggregator-api.kyberswap.com/base/api/v1/routes"


async def _route(session, token_in: str, token_out: str, amount_in_raw: int):
    params = {
        "tokenIn": TOKENS[token_in]["address"],
        "tokenOut": TOKENS[token_out]["address"],
        "amountIn": str(amount_in_raw),
        "saveGas": "0",
        "gasInclude": "1",
    }
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    async with session.get(ENDPOINT, params=params, headers=headers, timeout=20) as r:
        r.raise_for_status()
        data = await r.json()
    return int(data["data"]["routeSummary"]["amountOut"])


async def fetch(session, pair: str) -> List[Quote]:
    cfg = PAIRS[pair]
    base, quote = cfg["base"], cfg["quote"]
    rows: List[Quote] = []

    async def sell(size_base: float):
        try:
            raw_out = await _route(session, base, quote, to_raw(size_base, base))
            usdc_out = from_raw(raw_out, quote)
            return Quote(VENUE, pair, "SELL", usdc_out / size_base,
                         size_base=size_base, raw_out=raw_out)
        except Exception:
            return None

    async def buy(size_quote: float):
        try:
            raw_out = await _route(session, quote, base, to_raw(size_quote, quote))
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
