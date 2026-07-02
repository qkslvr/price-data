"""Entry point: fetch -> compute -> store -> print.

Usage:
    python -m src.main                 # one batch, all pairs, store to DB
    python -m src.main --pair ETH_USDC # restrict to one pair
    python -m src.main --no-db         # skip DB write
    python -m src.main --loop 60       # repeat every 60 seconds
"""
import argparse
import asyncio
from datetime import datetime, timezone
from typing import List

from .aggregator import fetch_all
from .config import PAIRS, RETENTION_DAYS
from .db import prune, store
from .quote import Quote


def _fmt_size(q: Quote) -> str:
    if q.direction == "SELL":
        return f"{q.size_base:g} base"
    return f"${q.size_quote:g}"


def print_table(rows: List[Quote]):
    if not rows:
        print("(no quotes)")
        return

    # Group by pair + direction, sort by size then rate.
    rows = sorted(
        rows,
        key=lambda q: (
            q.pair,
            q.direction,
            q.size_base if q.size_base is not None else q.size_quote,
            -q.rate,
        ),
    )
    header = f"{'venue':<13} {'pair':<11} {'dir':<5} {'size':>12} {'rate $/tok':>14} {'depth':>6}"
    print(header)
    print("-" * len(header))
    for q in rows:
        flag = "" if q.depth_ok else "thin"
        print(
            f"{q.venue:<13} {q.pair:<11} {q.direction:<5} "
            f"{_fmt_size(q):>12} {q.rate:>14,.2f} {flag:>6}"
        )


def print_best(rows: List[Quote]):
    """Print the best venue per (pair, direction, size) bracket."""
    best = {}
    for q in rows:
        size = q.size_base if q.size_base is not None else q.size_quote
        key = (q.pair, q.direction, size)
        # Best SELL = highest $/token received; best BUY = lowest $/token paid.
        cur = best.get(key)
        if cur is None:
            best[key] = q
        elif q.direction == "SELL" and q.rate > cur.rate:
            best[key] = q
        elif q.direction == "BUY" and q.rate < cur.rate:
            best[key] = q

    print("\nBest venue per bracket:")
    header = f"{'pair':<11} {'dir':<5} {'size':>12} {'best venue':<13} {'rate $/tok':>14}"
    print(header)
    print("-" * len(header))
    for key in sorted(best, key=lambda k: (k[0], k[1], k[2])):
        q = best[key]
        print(
            f"{q.pair:<11} {q.direction:<5} {_fmt_size(q):>12} "
            f"{q.venue:<13} {q.rate:>14,.2f}"
        )


async def run_once(pairs, use_db: bool, quiet: bool = False):
    if not quiet:
        print(f"Fetching quotes for: {', '.join(pairs)} ...")
    rows = await fetch_all(pairs)
    if not quiet:
        print(f"Collected {len(rows)} quotes.\n")
        print_table(rows)
        print_best(rows)

    run_id = removed = None
    if use_db:
        run_id = await store(rows)
        if run_id is not None:
            removed = await prune(RETENTION_DAYS)
            if not quiet:
                print(f"\nStored as run_id={run_id}")
                if removed:
                    print(f"Pruned {removed} run(s) older than {RETENTION_DAYS}d")

    if quiet:
        # One compact line per run — keeps cron logs tiny.
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        pruned = f", pruned {removed}" if removed else ""
        print(f"{ts}  {len(rows)} quotes  run_id={run_id}{pruned}", flush=True)


async def main_async(args):
    pairs = [args.pair] if args.pair else list(PAIRS.keys())
    if args.loop:
        while True:
            await run_once(pairs, not args.no_db, args.quiet)
            if not args.quiet:
                print(f"\n--- sleeping {args.loop}s ---\n")
            await asyncio.sleep(args.loop)
    else:
        await run_once(pairs, not args.no_db, args.quiet)


def main():
    parser = argparse.ArgumentParser(description="BestQuotes multi-venue aggregator")
    parser.add_argument("--pair", choices=list(PAIRS.keys()), help="restrict to one pair")
    parser.add_argument("--no-db", action="store_true", help="do not write to Postgres")
    parser.add_argument("--loop", type=int, metavar="SECONDS",
                        help="repeat every N seconds")
    parser.add_argument("--quiet", action="store_true",
                        help="cron mode: one summary line per run, no tables")
    args = parser.parse_args()

    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
