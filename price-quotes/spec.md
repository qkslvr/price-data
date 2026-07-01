# BestQuotes — Multi-Venue Price Aggregator

Real-time swap quote aggregator for ETH/USDC and cbBTC/USDC across 7 venues, with VWAP-weighted effective rates and persistent quote storage.

---

## Pairs & Sizes

| Pair | Chain | Base Token | Quote Token |
|---|---|---|---|
| ETH/USDC | Base | WETH `0x4200...0006` | USDC `0x8335...2913` |
| cbBTC/USDC | Base | cbBTC `0xcbB7...3Bf` | USDC `0x8335...2913` |

**Buy sizes (USDC in):** $10, $100, $1,000, $2,000  
**Sell sizes (base token in):**
- ETH: 0.01, 0.05, 0.1, 0.5, 1.0 ETH
- cbBTC: 0.001, 0.005, 0.01, 0.05, 0.1 BTC

**Output:** Effective rate ($/token) = VWAP-weighted fill price for each size bracket.

---

## Venues

### 1. KyberSwap — REST API (Base chain)
- **Type:** DEX aggregator
- **Endpoint:** `GET https://aggregator-api.kyberswap.com/base/api/v1/routes`
- **Params:** `tokenIn`, `tokenOut`, `amountIn` (wei), `saveGas=0`, `gasInclude=1`
- **Auth:** None (requires `User-Agent` header)
- **Returns:** `data.routeSummary.amountOut` (raw units)
- **Note:** Best aggregator on Base; consistently finds optimal routes

### 2. Bebop — REST API (Base chain)
- **Type:** RFQ / DEX aggregator
- **Endpoint:** `GET https://api.bebop.xyz/router/base/v1/quote`
- **Params:** `buy_tokens`, `sell_tokens`, `sell_amounts` (wei), `taker_address`
- **Auth:** None (requires `User-Agent` header; API key available for better rates)
- **Returns:** `routes[].quote.buyTokens.{address}.amount`
- **Note:** Use a dummy taker address (`0x1111...1111`) for indicative quotes

### 3. Uniswap V3 — On-chain Quoter (Base chain)
- **Type:** AMM on-chain simulation
- **Contract:** `QuoterV2` at `0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a`
- **Method:** `quoteExactInputSingle` — selector `0xc6a5026a`
- **Fee tiers tried:**
  - ETH/USDC: 100, 500, 3000 bps
  - cbBTC/USDC: 500, 3000, 10000 bps
- **RPC:** `https://base.gateway.tenderly.co` (public, no key needed)
- **Note:** Take best output across all fee tiers

### 4. PancakeSwap V3 — On-chain Quoter (Base chain)
- **Type:** AMM on-chain simulation
- **Contract:** `QuoterV2` at `0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997`
- **Method:** Same ABI as Uniswap V3 (`0xc6a5026a`)
- **Fee tiers:** Same as Uniswap above
- **RPC:** `https://base.gateway.tenderly.co`
- **Note:** Degrades significantly on large cbBTC sizes (thin liquidity)

### 5. Hyperliquid — Spot Orderbook
- **Type:** CLOB (Central Limit Order Book)
- **Endpoint:** `POST https://api.hyperliquid.xyz/info`
- **Auth:** None
- **Market IDs (spot):**
  - ETH/USDC → coin `@151`
  - BTC/USDC  → coin `@142`
- **Request body:** `{"type": "l2Book", "coin": "@151", "nSigFigs": 5}`
- **Returns:** `levels[0]` = bids, `levels[1]` = asks (each: `{px, sz, n}`)
- **VWAP calc:** Walk bid/ask levels to compute weighted fill price for each size
- **Note:** Prices exclude Hyperliquid taker fee (~0.025%). Tight spreads on ETH.

### 6. Binance — Spot Orderbook
- **Type:** CEX CLOB
- **Endpoint:** `GET https://api.binance.com/api/v3/depth`
- **Params:** `symbol=ETHUSDC` or `BTCUSDC`, `limit=100`
- **Auth:** None
- **Returns:** `bids` and `asks` arrays of `[price, qty]` strings
- **VWAP calc:** Same walk-the-book approach as Hyperliquid
- **Note:** Uses BTCUSDC (not BTCBUSD). No cbBTC-specific market; BTC price used as reference.

### 7. KalqiX — CLOB with REST API
- **Type:** CLOB DEX
- **Base URL:** `https://api.kalqix.com/v1`
- **Auth:** HMAC-SHA256
  ```
  X-API-Key:    <api_key>
  X-Timestamp:  <unix_ms>
  X-Signature:  HMAC-SHA256(secret, timestamp + "GET" + path)
  ```
- **Markets:** `ETH_USDC`, `cbBTC_USDC`
- **Endpoints used:**
  - Mid price: `GET /markets/{market}/price`
  - Side price: `GET /markets/{market}/market-price?side=SELL|BUY`
  - Orderbook:  `GET /markets/{market}/order-book` (requires auth)
- **Orderbook format:** `{"BUY": [{price, quantity, price_formatted, quantity_formatted}], "SELL": [...]}`
- **VWAP calc:** Walk `BUY` levels for sells, `SELL` levels for buys
- **Note:** Ask side is thin — BUY quotes deteriorate sharply for larger sizes

---

## VWAP Fill Calculation

```python
def vwap_sell(levels, qty):
    """Walk bid levels to simulate a market sell. Returns $/base."""
    rem, notional = qty, 0.0
    for level in levels:
        px, sz = float(level['px']), float(level['sz'])
        fill = min(rem, sz)
        notional += fill * px
        rem -= fill
        if rem <= 1e-9:
            return notional / qty
    return None  # insufficient depth

def vwap_buy(levels, usdc):
    """Walk ask levels to simulate a market buy. Returns $/base."""
    rem, base_out = usdc, 0.0
    for level in levels:
        px, sz = float(level['px']), float(level['sz'])
        cost = sz * px
        if rem >= cost:
            base_out += sz; rem -= cost
        else:
            base_out += rem / px; rem = 0; break
    return usdc / base_out if base_out > 0 else None
```

---

## Database Schema

Store every quote run with venue, pair, direction, size, and effective rate.

```sql
CREATE TABLE quote_runs (
    id          SERIAL PRIMARY KEY,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE quotes (
    id          SERIAL PRIMARY KEY,
    run_id      INT REFERENCES quote_runs(id) ON DELETE CASCADE,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    venue       TEXT NOT NULL,          -- 'kyberswap' | 'bebop' | 'uniswap' | 'pancakeswap' | 'hyperliquid' | 'binance' | 'kalqix'
    pair        TEXT NOT NULL,          -- 'ETH_USDC' | 'cbBTC_USDC'
    direction   TEXT NOT NULL,          -- 'SELL' | 'BUY'
    size_base   NUMERIC,                -- base token amount (ETH or BTC), NULL if buying
    size_quote  NUMERIC,                -- USDC amount, NULL if selling
    rate        NUMERIC NOT NULL,       -- effective $/token (VWAP fill price)
    raw_out     NUMERIC,                -- raw output amount (optional)
    depth_ok    BOOLEAN DEFAULT TRUE    -- FALSE if insufficient book depth
);

CREATE INDEX ON quotes (fetched_at DESC);
CREATE INDEX ON quotes (venue, pair, direction);
```

**Suggested DB:** PostgreSQL (TimescaleDB extension optional for time-series hypertable on `fetched_at`)

---

## Project Structure

```
bestQuotes/
├── SPEC.md                  # this file
├── .env                     # secrets (never commit)
├── requirements.txt
├── db/
│   └── schema.sql           # CREATE TABLE statements above
├── src/
│   ├── config.py            # token addresses, fee tiers, size brackets
│   ├── venues/
│   │   ├── kyberswap.py
│   │   ├── bebop.py
│   │   ├── uniswap.py       # on-chain quoter (also used for PancakeSwap)
│   │   ├── hyperliquid.py
│   │   ├── binance.py
│   │   └── kalqix.py
│   ├── vwap.py              # shared fill simulation logic
│   ├── aggregator.py        # runs all venues in parallel, returns unified rows
│   ├── db.py                # psycopg2/asyncpg insert helpers
│   └── main.py              # entry point: fetch → compute → store → print
└── scripts/
    └── run_once.sh          # cron-friendly wrapper
```

---

## .env

```env
# KalqiX
KALQIX_API_KEY=c35a50a2cd35aec15fcf1a6973050695
KALQIX_API_SECRET=a59e6c67bb843449429a6c665b2743647b99cf80b6155f6148ae266749a72a7c

# Base RPC
BASE_RPC_URL=https://base.gateway.tenderly.co

# Postgres
DATABASE_URL=postgresql://user:pass@localhost:5432/bestquotes
```

---

## requirements.txt

```
aiohttp>=3.9
asyncpg>=0.29
python-dotenv>=1.0
web3>=6.0          # optional, for on-chain calls via library instead of raw RPC
```

---

## Key Addresses (Base Mainnet)

| Token | Address |
|---|---|
| WETH | `0x4200000000000000000000000000000000000006` |
| USDC | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` |
| cbBTC | `0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf` |
| Uniswap V3 QuoterV2 | `0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a` |
| PancakeSwap V3 QuoterV2 | `0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997` |

---

## Venues Not Included (and Why)

| Venue | Status |
|---|---|
| **Odos.xyz** | Rate limited without API key; get one at odos.xyz/api |
| **Aerodrome** | Slipstream CL quoter ABI incompatible with standard V3 encoding; skip or use subgraph |
| **KalqiX orderbook (unauth)** | Returns 401; use API key path above |

---

## Suggested Run Schedule

- **Every 60 seconds** for live monitoring
- **Every 5 minutes** for historical trend storage
- One `quote_runs` row per batch; all venue/pair/size quotes link to it via `run_id`
