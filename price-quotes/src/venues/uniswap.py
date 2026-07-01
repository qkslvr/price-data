"""Uniswap and PancakeSwap quotes via their hosted aggregated-router APIs.

Both venues now use the same server-side smart-order-router that powers their
respective web apps, so each quote is a fully *aggregated* price — routed and
split across pool types and multiple hops — rather than a single-pool probe.

Uniswap
-------
Trading API (`/v1/quote`, POST, key-gated): routes across v2/v3/v4. The routed
output amount is at `quote.output.amount` (raw units of tokenOut).

PancakeSwap
-----------
Hub gateway (`/v2/quote`, GET, no key): routes across v2/v3/stableswap/infinity.
The routed output amount is at `data.outputAmount` (raw units of outputToken).
"""
import asyncio
from typing import List, Optional

from ..config import (PAIRS, BUY_SIZES_USDC, SELL_SIZES, TOKENS,
                      UNISWAP_TRADING_API, UNISWAP_API_KEY, BASE_CHAIN_ID,
                      DUMMY_TAKER, USER_AGENT, PANCAKESWAP_QUOTE_API,
                      PANCAKE_PROTOCOLS, to_raw, from_raw)
from ..quote import Quote


# ---------------------------------------------------------------------------
# Shared: assemble Quote rows from a per-size "routed output amount" coroutine
# ---------------------------------------------------------------------------
async def _fetch_pair(pair: str, venue: str, get_out) -> List[Quote]:
    """`get_out(token_in, token_out, amount_in_raw) -> Optional[int]`."""
    cfg = PAIRS[pair]
    base, quote = cfg["base"], cfg["quote"]
    rows: List[Quote] = []

    # One failing size (e.g. a transient router 404) must not drop the others,
    # so each bracket swallows its own errors and yields None.
    async def sell(size_base: float):
        try:
            raw_out = await get_out(base, quote, to_raw(size_base, base))
        except Exception as e:
            print(f"  ! {venue}/{pair} SELL {size_base} failed: {e}")
            return None
        if not raw_out:
            return None
        usdc_out = from_raw(raw_out, quote)
        return Quote(venue, pair, "SELL", usdc_out / size_base,
                     size_base=size_base, raw_out=raw_out)

    async def buy(size_quote: float):
        try:
            raw_out = await get_out(quote, base, to_raw(size_quote, quote))
        except Exception as e:
            print(f"  ! {venue}/{pair} BUY ${size_quote} failed: {e}")
            return None
        if not raw_out:
            return None
        base_out = from_raw(raw_out, base)
        return Quote(venue, pair, "BUY", size_quote / base_out,
                     size_quote=size_quote, raw_out=raw_out)

    tasks = [sell(s) for s in SELL_SIZES[pair]] + [buy(s) for s in BUY_SIZES_USDC]
    for q in await asyncio.gather(*tasks):
        if q:
            rows.append(q)
    return rows


# ---------------------------------------------------------------------------
# Uniswap — Trading API (aggregated router)
# ---------------------------------------------------------------------------

# Default key rate limit is 3 req/s; space request *starts* ~0.4s apart (≈2.5
# req/s, a safety margin under the cap) process-wide — both pairs and all size
# brackets share this limiter. Bursts over the cap come back as 403, not 429.
_MIN_INTERVAL = 0.4
_rate_lock = asyncio.Lock()
_last_start = 0.0


async def _throttle() -> None:
    global _last_start
    async with _rate_lock:
        loop = asyncio.get_event_loop()
        wait = _last_start + _MIN_INTERVAL - loop.time()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_start = loop.time()


async def _uniswap_out(session, token_in: str, token_out: str,
                       amount_in: int) -> Optional[int]:
    """POST one EXACT_INPUT quote; return routed output amount (raw units)."""
    body = {
        "tokenIn": TOKENS[token_in]["address"],
        "tokenOut": TOKENS[token_out]["address"],
        "tokenInChainId": BASE_CHAIN_ID,
        "tokenOutChainId": BASE_CHAIN_ID,
        "type": "EXACT_INPUT",
        "amount": str(amount_in),
        "swapper": DUMMY_TAKER,
        "slippageTolerance": 0.5,
    }
    headers = {
        "x-api-key": UNISWAP_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    for attempt in range(4):
        await _throttle()
        async with session.post(UNISWAP_TRADING_API, json=body,
                                headers=headers, timeout=20) as r:
            # The gateway returns 429 or 403 when the rate cap is tripped.
            if r.status in (429, 403):
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            # 404 == no route found for this size; not an error, just no quote.
            if r.status == 404:
                return None
            r.raise_for_status()
            res = await r.json()
        out = (res.get("quote") or {}).get("output") or {}
        amount = out.get("amount")
        return int(amount) if amount is not None else None
    return None


async def fetch_uniswap(session, pair: str) -> List[Quote]:
    return await _fetch_pair(
        pair, "uniswap",
        lambda ti, to, amt: _uniswap_out(session, ti, to, amt))


# ---------------------------------------------------------------------------
# PancakeSwap — hub gateway (aggregated router)
# ---------------------------------------------------------------------------
async def _pancake_out(session, token_in: str, token_out: str,
                       amount_in: int) -> Optional[int]:
    """GET one exactIn quote; return routed output amount (raw units)."""
    params = {
        "chainId": BASE_CHAIN_ID,
        "inputToken": TOKENS[token_in]["address"],
        "outputToken": TOKENS[token_out]["address"],
        "amount": str(amount_in),
        "tradeType": "exactIn",
        "maxSplits": 10,
        "protocol": PANCAKE_PROTOCOLS,
    }
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    for attempt in range(4):
        async with session.get(PANCAKESWAP_QUOTE_API, params=params,
                               headers=headers, timeout=20) as r:
            if r.status in (429, 403) or r.status >= 500:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            r.raise_for_status()
            res = await r.json()
        if res.get("code") != 0:
            return None
        amount = (res.get("data") or {}).get("outputAmount")
        return int(amount) if amount is not None else None
    return None


async def fetch_pancakeswap(session, pair: str) -> List[Quote]:
    return await _fetch_pair(
        pair, "pancakeswap",
        lambda ti, to, amt: _pancake_out(session, ti, to, amt))
