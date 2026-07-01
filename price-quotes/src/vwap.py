"""Shared VWAP fill simulation for orderbook venues.

A "level" is a dict with float-able `px` (quote per base) and `sz` (base size).
Bids are levels you can sell into; asks are levels you can buy from.

Levels are re-sorted by price before walking (bids high->low, asks low->high)
so a venue that returns its book in any order still fills best-price-first.
"""
from typing import List, Optional


def vwap_sell(levels: List[dict], qty: float) -> Optional[float]:
    """Walk bid levels to simulate a market sell of `qty` base. Returns $/base."""
    levels = sorted(levels, key=lambda l: float(l["px"]), reverse=True)
    rem, notional = qty, 0.0
    for level in levels:
        px, sz = float(level["px"]), float(level["sz"])
        fill = min(rem, sz)
        notional += fill * px
        rem -= fill
        if rem <= 1e-9:
            return notional / qty
    return None  # insufficient depth


def vwap_buy(levels: List[dict], usdc: float) -> Optional[float]:
    """Walk ask levels to simulate a market buy spending `usdc`. Returns $/base."""
    levels = sorted(levels, key=lambda l: float(l["px"]))
    rem, base_out = usdc, 0.0
    for level in levels:
        px, sz = float(level["px"]), float(level["sz"])
        cost = sz * px
        if rem >= cost:
            base_out += sz
            rem -= cost
        else:
            base_out += rem / px
            rem = 0
            break
    if rem > 1e-9:
        return None  # book exhausted before `usdc` fully spent
    return usdc / base_out if base_out > 0 else None


def base_out_for_buy(levels: List[dict], usdc: float) -> Optional[float]:
    """Base tokens received when spending `usdc` walking ask levels.

    Returns None if the book lacks depth to spend the full `usdc`.
    """
    levels = sorted(levels, key=lambda l: float(l["px"]))
    rem, base_out = usdc, 0.0
    for level in levels:
        px, sz = float(level["px"]), float(level["sz"])
        cost = sz * px
        if rem >= cost:
            base_out += sz
            rem -= cost
        else:
            base_out += rem / px
            rem = 0
            break
    if rem > 1e-9:
        return None  # insufficient depth
    return base_out
