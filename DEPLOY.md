# Deploying the liquidity-edge dashboard (cloud)

Target architecture — the puller runs as a plain cron on your own server:

```
Your server (cron, every 5 min)         Vercel
  price-quotes/  ──writes──►  Neon  ◄──reads──  api/index.py (FastAPI)
                            Postgres                 +  index.html (dashboard)
```

- **DB:** Neon (managed serverless Postgres, free tier).
- **Puller:** `price-quotes/` runs from a cron on your server every 5 min, writes
  to Neon, and prunes anything older than **30 days** (`RETENTION_DAYS`).
- **API + UI:** one Vercel project. `index.html` is served by the CDN; every
  `/api/*` request is rewritten to the `api/index.py` serverless function.

---

## 1. Neon (database)

1. Create a project at <https://neon.tech>.
2. Copy **two** connection strings from the Neon dashboard:
   - **Pooled** (host contains `-pooler`) → for Vercel (the API).
   - **Direct** (no `-pooler`) → for the puller / running the schema.
   Both look like
   `postgresql://USER:PASSWORD@ep-xxxx[-pooler].REGION.aws.neon.tech/DB?sslmode=require`.
3. Apply the schema (uses the direct string):
   ```bash
   psql "postgresql://…neon.tech/DB?sslmode=require" -f price-quotes/db/schema.sql
   ```

## 2. Server cron (the 5-min puller)

Run this on whichever always-on box you control (e.g. the old data-pull box).
It needs outbound internet (for the venue APIs + Neon) — no SSH tunnel.

1. Get the code and install deps:
   ```bash
   git clone https://github.com/qkslvr/price-data.git
   cd price-data/price-quotes
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
   (If the box already has this repo, `git pull` to get the Neon-ready DB layer
   and the `--quiet` flag.)
2. Create `price-quotes/.env` (gitignored) — this is what the puller reads:
   ```env
   DATABASE_URL=postgresql://USER:PASSWORD@ep-xxxx.REGION.aws.neon.tech/DB?sslmode=require  # Neon DIRECT
   KALQIX_API_KEY=...
   KALQIX_API_SECRET=...
   BASE_RPC_URL=https://base.gateway.tenderly.co
   UNISWAP_API_KEY=...
   RETENTION_DAYS=30
   ```
3. Test one run:
   ```bash
   ./scripts/run_once.sh --quiet
   # -> 2026-07-02 09:11:34Z  114 quotes  run_id=7231
   ```
4. Install the cron (`crontab -e`), pointing at the absolute path on your box:
   ```cron
   */5 * * * * /home/USER/price-data/price-quotes/scripts/run_once.sh --quiet >> /home/USER/price-data/price-quotes/cron.log 2>&1
   ```
   `run_once.sh` resolves its own path, activates `.venv`, and runs
   `python -m src.main`. `--quiet` logs one line per run (no big tables), so
   `cron.log` stays tiny. Rotate/truncate it whenever you like.

## 3. Vercel (API + dashboard)

1. Import the GitHub repo at <https://vercel.com/new>. Framework preset:
   **Other**. Leave build/output settings empty — `vercel.json` handles routing.
   > Vercel may clone your code into a *new* repo at import (e.g. `<org>/price-data`
   > with an "Initial commit") and deploy from that copy — so your own pushes never
   > deploy. If so: **Settings → Git → disconnect that copy, connect
   > `qkslvr/price-data`** (grant the Vercel GitHub App access to your account),
   > then push a commit to trigger a deploy. (Redeploy fails — it targets the old
   > copy's commit.)
2. **Settings → Environment Variables:** add `DATABASE_URL` = Neon **pooled**
   (`-pooler`) connection string. Apply to Production (and Preview).
3. Deploy. Dashboard at `https://<project>.vercel.app/`; API at `/api/...`
   (same origin — no CORS needed).

## 4. (Optional) migrate existing history

To carry over data from an old Postgres into Neon (data-only):

```bash
pg_dump "postgresql://USER:PASS@OLD_HOST:PORT/OLD_DB" \
        --data-only --table=quote_runs --table=quotes \
  | psql "postgresql://…neon.tech/DB?sslmode=require"
```

After loading with preserved IDs, bump the sequence so the cron continues without
collisions: `SELECT setval('quote_runs_id_seq', (SELECT max(id) FROM quote_runs));`
The 30-day prune trims it to the retention window on the next run.

---

## Local development

No SSH tunnel — you connect straight to Neon.

```bash
cp .env.example .env          # put a Neon connection string in DATABASE_URL
./start.sh                    # dashboard + API at http://localhost:8000
```

`start.sh` creates a venv, installs `api/requirements.txt`, and runs
`uvicorn api.index:app`, which serves both `index.html` and `/api/*`.

## Knobs

- **Cadence:** the `*/5 * * * *` in your crontab (step 2.4).
- **Retention:** `RETENTION_DAYS` in `price-quotes/.env` (default `30`).
  Storage ≈ RETENTION_DAYS × ~25k rows/day at 5-min cadence.
