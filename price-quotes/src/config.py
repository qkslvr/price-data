"""Static configuration: token addresses, fee tiers, size brackets, venue IDs.

All addresses are Base mainnet. Decimals matter for converting between raw
on-chain integer amounts ("wei") and human units.
"""
import os

from dotenv import load_dotenv

load_dotenv()

# --- Secrets / endpoints (from .env) ---------------------------------------
KALQIX_API_KEY = os.getenv("KALQIX_API_KEY", "")
KALQIX_API_SECRET = os.getenv("KALQIX_API_SECRET", "")
BASE_RPC_URL = os.getenv("BASE_RPC_URL", "https://base.gateway.tenderly.co")
UNISWAP_API_KEY = os.getenv("UNISWAP_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Rolling retention window: delete quote_runs (and their quotes, via cascade)
# older than this many days after each batch. 0 disables pruning.
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "30"))

# Uniswap Trading API — server-side smart-order-router (the same aggregated quote
# the Uniswap app uses: routes across v2/v3/v4, multi-hop, split routes).
UNISWAP_TRADING_API = "https://trade-api.gateway.uniswap.org/v1/quote"
BASE_CHAIN_ID = 8453

# PancakeSwap hub gateway — the aggregated quoter behind the PancakeSwap app
# (routes/splits across v2, v3, stableswap, and infinity pools). No key needed.
PANCAKESWAP_QUOTE_API = "https://hub-gateway.pancakeswap.com/v2/quote"
PANCAKE_PROTOCOLS = "v2,v3,stableswap,infinityCl,infinityBin"  # 'pro' is rejected on Base

# A dummy taker used for indicative RFQ quotes (Bebop) and as a generic spender.
DUMMY_TAKER = "0x1111111111111111111111111111111111111111"

USER_AGENT = "bestquotes/1.0 (+https://github.com/bestquotes)"

# --- Tokens (Base mainnet) -------------------------------------------------
TOKENS = {
    "WETH": {
        "address": "0x4200000000000000000000000000000000000006",
        "decimals": 18,
    },
    "USDC": {
        "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "decimals": 6,
    },
    "cbBTC": {
        "address": "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf",
        "decimals": 8,
    },
}

# --- On-chain quoter contracts ---------------------------------------------
UNISWAP_V3_QUOTER = "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"
PANCAKESWAP_V3_QUOTER = "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997"

# --- Trade size brackets ----------------------------------------------------
# Buy sizes are USDC notionals spent (USDC -> base).
BUY_SIZES_USDC = [10, 100, 1_000, 2_000]

# Sell sizes are base-token amounts sent (base -> USDC); per-pair.
SELL_SIZES = {
    "ETH_USDC": [0.01, 0.05, 0.1, 0.5, 1.0],
    "cbBTC_USDC": [0.001, 0.005, 0.01, 0.05, 0.1],
}

# --- Pairs ------------------------------------------------------------------
# Each pair binds a base/quote token plus the per-venue identifiers needed to
# query it. `fee_tiers` are the Uniswap/Pancake V3 pools to probe (bps).
PAIRS = {
    "ETH_USDC": {
        "base": "WETH",
        "quote": "USDC",
        "fee_tiers": [100, 500, 3000],
        "hyperliquid_coin": "@151",
        "binance_symbol": "ETHUSDC",
        "kalqix_market": "ETH_USDC",
    },
    "cbBTC_USDC": {
        "base": "cbBTC",
        "quote": "USDC",
        "fee_tiers": [500, 3000, 10000],
        "hyperliquid_coin": "@142",
        "binance_symbol": "BTCUSDC",
        "kalqix_market": "cbBTC_USDC",
    },
}


def to_raw(amount: float, token: str) -> int:
    """Human amount -> raw integer units for `token`."""
    return int(round(amount * 10 ** TOKENS[token]["decimals"]))


def from_raw(raw, token: str) -> float:
    """Raw integer units -> human amount for `token`."""
    return float(raw) / 10 ** TOKENS[token]["decimals"]
