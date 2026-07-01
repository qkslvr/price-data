"""FastAPI read-only API for the liquidity-edge dashboard.

Deployed on Vercel as a Python serverless function (all `/api/*` routes are
rewritten to this file by vercel.json). Also runnable locally with
`uvicorn api.index:app --port 8000`, in which case it additionally serves the
static dashboard at `/` so you can develop against Neon without any tunnel.
"""
import json
import os
import ssl as ssl_module
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import asyncpg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

load_dotenv()  # no-op on Vercel (env vars come from the dashboard)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://bestquotes:bestquotes@localhost:5432/bestquotes",
)


def prepare_dsn(url: str) -> tuple[str, ssl_module.SSLContext | None]:
    """Return an asyncpg-safe DSN plus an SSL context.

    Managed Postgres (Neon) connection strings carry libpq params such as
    `sslmode` and `channel_binding` that asyncpg's DSN parser doesn't all
    accept, so we strip them and translate `sslmode` into an explicit SSL
    context. Local (localhost) connections use no TLS.
    """
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    sslmode = (q.pop("sslmode", ["require"]) or ["require"])[0]
    q.pop("channel_binding", None)
    dsn = urlunparse(parsed._replace(query=urlencode({k: v[0] for k, v in q.items()})))

    if parsed.hostname in ("localhost", "127.0.0.1") or sslmode in (
        "disable",
        "allow",
        "prefer",
    ):
        return dsn, None

    ctx = ssl_module.create_default_context()
    if sslmode == "require":  # encrypt but don't verify the server cert/host
        ctx.check_hostname = False
        ctx.verify_mode = ssl_module.CERT_NONE
    return dsn, ctx


pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global pool
    if pool is None:
        dsn, ssl_ctx = prepare_dsn(DATABASE_URL)
        try:
            p = await asyncpg.create_pool(
                dsn,
                ssl=ssl_ctx,
                min_size=0,
                max_size=3,
                # Neon's pooled endpoint is PgBouncer (transaction mode), which
                # is incompatible with asyncpg's prepared-statement cache.
                statement_cache_size=0,
            )
            # min_size=0 defers the first connect, so validate it here to turn
            # a DB outage into a clean 503 rather than a 500 at query time.
            async with p.acquire() as conn:
                await conn.execute("SELECT 1")
            pool = p
        except Exception as e:
            raise HTTPException(
                status_code=503,
                detail=f"Database unreachable ({e})",
            )
    return pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    if pool:
        await pool.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/tables")
async def list_tables() -> list[str]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public'
        ORDER BY tablename
        """
    )
    return [r["tablename"] for r in rows]


@app.get("/api/tables/{table}")
async def get_table(
    table: str,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    pool = await get_pool()
    # Validate table name exists to prevent SQL injection
    exists = await pool.fetchval(
        "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
        table,
    )
    if not exists:
        raise HTTPException(status_code=404, detail=f"Table '{table}' not found")

    rows = await pool.fetch(
        f'SELECT * FROM "{table}" LIMIT $1 OFFSET $2', limit, offset
    )
    total = await pool.fetchval(f'SELECT COUNT(*) FROM "{table}"')

    columns = list(rows[0].keys()) if rows else []
    data = [dict(r) for r in rows]

    # Serialize non-JSON-safe types to strings
    for row in data:
        for k, v in row.items():
            if not isinstance(v, (str, int, float, bool, type(None))):
                row[k] = str(v)

    return {"table": table, "total": total, "columns": columns, "rows": data}


@app.get("/api/pairs")
async def list_pairs() -> list[str]:
    pool = await get_pool()
    rows = await pool.fetch("SELECT DISTINCT pair FROM quotes ORDER BY pair")
    return [r["pair"] for r in rows]


@app.get("/api/liquidity/{pair}")
async def get_liquidity(pair: str) -> dict[str, Any]:
    pool = await get_pool()
    # latest run that actually has fillable quotes (depth_ok AND rate > 0)
    run_id = await pool.fetchval(
        "SELECT MAX(run_id) FROM quotes WHERE pair = $1 AND depth_ok AND rate > 0",
        pair,
    )
    if run_id is None:
        raise HTTPException(status_code=404, detail=f"No data for pair '{pair}'")

    rows = await pool.fetch(
        """
        SELECT venue, direction,
               CAST(size_base AS float)  AS size_base,
               CAST(size_quote AS float) AS size_quote,
               CAST(rate AS float)       AS rate,
               CAST(raw_out AS float)    AS raw_out,
               depth_ok,
               fetched_at
        FROM quotes
        WHERE pair = $1 AND run_id = $2
          AND depth_ok AND rate > 0
        ORDER BY direction, venue, COALESCE(size_base::float, size_quote::float)
        """,
        pair,
        run_id,
    )

    # full venue list across all runs (a venue may be absent from the latest run)
    all_venues = [
        r["venue"]
        for r in await pool.fetch(
            "SELECT DISTINCT venue FROM quotes "
            "WHERE pair = $1 AND depth_ok AND rate > 0 ORDER BY venue",
            pair,
        )
    ]

    result: dict[str, Any] = {"BUY": {}, "SELL": {}}
    fetched_at = None

    for r in rows:
        d = r["direction"]
        v = r["venue"]
        size = r["size_base"] if d == "SELL" else r["size_quote"]
        if fetched_at is None and r["fetched_at"]:
            fetched_at = r["fetched_at"].isoformat()
        if v not in result[d]:
            result[d][v] = []
        result[d][v].append(
            {
                "size": round(float(size), 4) if size is not None else 0,
                "rate": round(float(r["rate"]), 4) if r["rate"] is not None else None,
                "raw_out": float(r["raw_out"]) if r["raw_out"] is not None else None,
                "depth_ok": r["depth_ok"],
            }
        )

    return {
        "pair": pair,
        "run_id": run_id,
        "fetched_at": fetched_at,
        "data": result,
        "all_venues": all_venues,
    }


@app.get("/api/timeseries/{pair}")
async def timeseries(pair: str, direction: str, size: float) -> dict[str, Any]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT run_id,
               extract(epoch FROM fetched_at) * 1000 AS t_ms,
               venue,
               CAST(rate AS float) AS rate
        FROM quotes
        WHERE pair = $1
          AND direction = $2
          AND round(COALESCE(size_base, size_quote), 6) = round($3::numeric, 6)
          AND depth_ok AND rate > 0
        ORDER BY run_id
        """,
        pair,
        direction,
        size,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No time-series for that selection")

    run_order: list[int] = []
    run_t: dict[int, float] = {}
    by_venue: dict[str, dict[int, float]] = {}

    for r in rows:
        rid = r["run_id"]
        if rid not in run_t:
            run_t[rid] = float(r["t_ms"])
            run_order.append(rid)
        by_venue.setdefault(r["venue"], {})[rid] = r["rate"]

    venues = sorted(by_venue)
    t = [run_t[rid] for rid in run_order]
    rates = {v: [by_venue[v].get(rid) for rid in run_order] for v in venues}

    return {
        "pair": pair,
        "direction": direction,
        "size": size,
        "venues": venues,
        "t": t,
        "rates": rates,
        "runs": len(run_order),
    }


@app.get("/api/winshare/{direction}")
async def winshare(
    direction: str,
    fees: str,
    since_ms: float | None = None,
) -> dict[str, Any]:
    """Best-venue share per (pair, size) for a direction, over a time window,
    with per-venue taker fees applied to the effective rate.

    `fees` is a JSON object {venue: bps}; only venues present in it are
    considered (this also enforces the venue allowlist server-side)."""
    pool = await get_pool()
    if direction not in ("SELL", "BUY"):
        raise HTTPException(status_code=400, detail="direction must be SELL or BUY")
    try:
        fee_map = {str(k): float(v) for k, v in json.loads(fees).items()}
    except Exception:
        raise HTTPException(status_code=400, detail="fees must be JSON {venue: bps}")

    # SELL best = max effective rate; BUY best = min. ORDER BY eff*sign ASC picks best.
    sign = -1 if direction == "SELL" else 1

    rows = await pool.fetch(
        """
        WITH fee(venue, bps) AS (
            SELECT key, value::float FROM jsonb_each_text($1::jsonb)
        ),
        adj AS (
            SELECT q.pair,
                   round(COALESCE(q.size_base, q.size_quote), 6) AS size,
                   q.run_id, q.venue,
                   CASE WHEN $2 = 'SELL'
                        THEN q.rate * (1 - fee.bps / 10000.0)
                        ELSE q.rate * (1 + fee.bps / 10000.0) END AS eff
            FROM quotes q
            JOIN fee ON fee.venue = q.venue
            WHERE q.direction = $2 AND q.depth_ok AND q.rate > 0
              AND ($3::float IS NULL OR extract(epoch FROM q.fetched_at) * 1000 >= $3)
        ),
        ranked AS (
            SELECT pair, size, run_id, venue,
                   ROW_NUMBER() OVER (PARTITION BY pair, size, run_id
                                      ORDER BY eff * $4 ASC) AS rn
            FROM adj
        ),
        wins AS (
            SELECT pair, size, venue, COUNT(*) AS w
            FROM ranked WHERE rn = 1 GROUP BY pair, size, venue
        ),
        totals AS (
            SELECT pair, size, COUNT(DISTINCT run_id) AS tot
            FROM adj GROUP BY pair, size
        )
        SELECT w.pair, CAST(w.size AS float) AS size, w.venue, w.w, t.tot
        FROM wins w JOIN totals t USING (pair, size)
        ORDER BY w.pair, size
        """,
        json.dumps(fee_map),
        direction,
        since_ms,
        sign,
    )

    out: dict[str, Any] = {}
    for r in rows:
        sz = float(r["size"])
        out.setdefault(r["pair"], {}).setdefault(sz, {})
        out[r["pair"]][sz][r["venue"]] = {
            "wins": r["w"],
            "tot": r["tot"],
            "pct": round(r["w"] / r["tot"] * 100, 1) if r["tot"] else 0.0,
        }
    return {"direction": direction, "data": out}


# --- Local dev only: serve the static dashboard from the repo root ----------
# On Vercel the static files are served by the CDN and only `/api/*` reaches
# this function, so this mount is never hit there (and is skipped if the repo
# root isn't bundled with the function).
_ROOT = Path(__file__).resolve().parent.parent
if (_ROOT / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(_ROOT), html=True), name="static")
