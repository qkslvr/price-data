# BestQuotes — Multi-Venue Price Aggregator

Real-time swap quote aggregator for **ETH/USDC** and **cbBTC/USDC** across 7 venues,
with VWAP-weighted effective rates and persistent quote storage. See [spec.md](spec.md).

## Venues

| Venue | Type | Auth |
|---|---|---|
| KyberSwap | DEX aggregator (REST) | none |
| Bebop | RFQ / aggregator (REST) | none |
| Uniswap V3 | on-chain QuoterV2 (eth_call) | none |
| PancakeSwap V3 | on-chain QuoterV2 (eth_call) | none |
| Hyperliquid | spot CLOB | none |
| Binance | spot CLOB | none |
| KalqiX | CLOB DEX (REST) | HMAC-SHA256 |

DEX/RFQ venues return `amountOut` for a given `amountIn` (effective rate computed
directly). Orderbook venues (Hyperliquid, Binance, KalqiX) are walked level-by-level
via the shared VWAP fill simulation in [`src/vwap.py`](src/vwap.py).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt          # asyncpg only needed for DB writes
cp .env.example .env                      # fill in secrets
```

## Run

```bash
python -m src.main                  # one batch, all pairs, store to Postgres
python -m src.main --pair ETH_USDC  # single pair
python -m src.main --no-db          # skip DB write (print only)
python -m src.main --loop 60        # repeat every 60s (live monitoring)
./scripts/run_once.sh --no-db       # cron-friendly wrapper
```

Output: a full quote table plus the best venue per (pair, direction, size) bracket.

## Database

```bash
psql "$DATABASE_URL" -f db/schema.sql
```

Each batch inserts one `quote_runs` row; all venue/pair/size quotes link to it via
`run_id`. Schema in [`db/schema.sql`](db/schema.sql). If `asyncpg` isn't installed or
`DATABASE_URL` is unset, DB writes are skipped (printing still works).

## Layout

```
src/
├── config.py        # token addresses, fee tiers, size brackets, pair definitions
├── vwap.py          # shared orderbook fill simulation
├── quote.py         # unified Quote row
├── venues/          # one module per venue
├── aggregator.py    # runs all venues × pairs in parallel
├── db.py            # asyncpg persistence
└── main.py          # entry point: fetch → compute → store → print
```
