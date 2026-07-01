CREATE TABLE IF NOT EXISTS quote_runs (
    id          SERIAL PRIMARY KEY,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS quotes (
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

CREATE INDEX IF NOT EXISTS quotes_fetched_at_idx ON quotes (fetched_at DESC);
CREATE INDEX IF NOT EXISTS quotes_venue_pair_dir_idx ON quotes (venue, pair, direction);
CREATE INDEX IF NOT EXISTS quotes_pair_run_idx ON quotes (pair, run_id);
-- Speeds up the retention prune (DELETE FROM quote_runs WHERE fetched_at < …).
CREATE INDEX IF NOT EXISTS quote_runs_fetched_at_idx ON quote_runs (fetched_at);
