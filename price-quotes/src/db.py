"""Persistence helpers (asyncpg). A run groups all quotes from one batch."""
import ssl as ssl_module
from typing import List, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from .config import DATABASE_URL

from .quote import Quote

try:
    import asyncpg
except ImportError:  # allow running without DB deps installed
    asyncpg = None


def _prepare_dsn(url: str):
    """Return an asyncpg-safe DSN plus an SSL context.

    Managed Postgres (Neon) URLs carry libpq params such as `sslmode` and
    `channel_binding` that asyncpg's DSN parser doesn't all accept, so strip
    them and translate `sslmode` into an explicit SSL context. Localhost uses
    no TLS.
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


async def _connect():
    """Open a single asyncpg connection to DATABASE_URL, or None if unavailable."""
    if asyncpg is None:
        print("  ! asyncpg not installed; skipping DB write")
        return None
    if not DATABASE_URL:
        print("  ! DATABASE_URL not set; skipping DB write")
        return None
    dsn, ssl_ctx = _prepare_dsn(DATABASE_URL)
    # statement_cache_size=0 keeps us compatible with PgBouncer-pooled endpoints.
    return await asyncpg.connect(dsn, ssl=ssl_ctx, statement_cache_size=0)


async def store(rows: List[Quote]) -> Optional[int]:
    """Insert a quote_runs row and all quotes under it. Returns the run id.

    Returns None (no-op) if asyncpg is unavailable or DATABASE_URL is unset.
    """
    conn = await _connect()
    if conn is None:
        return None
    try:
        run_id = await conn.fetchval(
            "INSERT INTO quote_runs DEFAULT VALUES RETURNING id"
        )
        await conn.executemany(
            """
            INSERT INTO quotes
                (run_id, venue, pair, direction, size_base, size_quote,
                 rate, raw_out, depth_ok)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            [
                (
                    run_id, q.venue, q.pair, q.direction,
                    q.size_base, q.size_quote, q.rate,
                    q.raw_out, q.depth_ok,
                )
                for q in rows
            ],
        )
        return run_id
    finally:
        await conn.close()


async def prune(days: int) -> Optional[int]:
    """Delete quote_runs (and their quotes, via ON DELETE CASCADE) older than
    `days`. Returns the number of runs removed, or None if it was a no-op."""
    if not days or days <= 0:
        return None
    conn = await _connect()
    if conn is None:
        return None
    try:
        result = await conn.execute(
            "DELETE FROM quote_runs "
            "WHERE fetched_at < now() - ($1::int * interval '1 day')",
            days,
        )
        # asyncpg returns a status string like "DELETE 42".
        return int(result.split()[-1]) if result.startswith("DELETE") else 0
    finally:
        await conn.close()
