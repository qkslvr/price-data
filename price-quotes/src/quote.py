"""Unified quote-row shape returned by every venue fetcher."""
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class Quote:
    venue: str
    pair: str
    direction: str               # 'SELL' | 'BUY'
    rate: float                  # effective $/token (VWAP fill price)
    size_base: Optional[float] = None    # base sent when selling
    size_quote: Optional[float] = None   # USDC sent when buying
    raw_out: Optional[float] = None      # raw output amount (optional)
    depth_ok: bool = True

    def as_dict(self) -> dict:
        return asdict(self)
