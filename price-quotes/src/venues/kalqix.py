"""KalqiX CLOB DEX. REST with HMAC-SHA256 auth.

Signature: HMAC-SHA256(secret, timestamp + "GET" + path), hex.
Orderbook: {"BUY": [{price, quantity, ...}], "SELL": [...]}.
Walk BUY levels for sells (bids), SELL levels for buys (asks).
"""
import hashlib
import hmac
import time
from typing import List

from ..config import (PAIRS, BUY_SIZES_USDC, SELL_SIZES, USER_AGENT,
                      KALQIX_API_KEY, KALQIX_API_SECRET)
from ..quote import Quote
from ..vwap import vwap_sell, vwap_buy

VENUE = "kalqix"
BASE_URL = "https://api.kalqix.com/v1"


def _headers(path: str) -> dict:
    ts = str(int(time.time() * 1000))
    msg = (ts + "GET" + path).encode()
    sig = hmac.new(KALQIX_API_SECRET.encode(), msg, hashlib.sha256).hexdigest()
    return {
        "X-API-Key": KALQIX_API_KEY,
        "X-Timestamp": ts,
        "X-Signature": sig,
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }


def _num(value):
    # Accept plain numbers or formatted strings ("1,540.50").
    return float(str(value).replace(",", ""))


def _norm(levels):
    # Prefer the human-scaled *_formatted fields; raw price/quantity are
    # fixed-point integers (off by the token decimal factor).
    out = []
    for lvl in levels:
        px = lvl.get("price_formatted", lvl.get("price"))
        sz = lvl.get("quantity_formatted", lvl.get("quantity"))
        out.append({"px": _num(px), "sz": _num(sz)})
    return out


async def _order_book(session, market: str):
    path = f"/markets/{market}/order-book"
    async with session.get(BASE_URL + path, headers=_headers(path), timeout=20) as r:
        r.raise_for_status()
        data = await r.json()
    book = data.get("data", data)
    return _norm(book.get("BUY", [])), _norm(book.get("SELL", []))


async def fetch(session, pair: str) -> List[Quote]:
    cfg = PAIRS[pair]
    rows: List[Quote] = []
    if not KALQIX_API_KEY or not KALQIX_API_SECRET:
        return rows
    try:
        bids, asks = await _order_book(session, cfg["kalqix_market"])
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
