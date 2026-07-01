# Deploying the liquidity-edge dashboard (cloud)

Target architecture — nothing depends on the old private box:

```
GitHub Actions (cron, every 5 min)      Vercel
  price-quotes/  ──writes──►  Neon  ◄──reads──  api/index.py (FastAPI)
                            Postgres                 +  index.html (dashboard)
```

- **DB:** Neon (managed serverless Postgres, free tier).
- **Puller:** `price-quotes/` runs on GitHub Actions every 5 min, writes to Neon,
  and prunes anything older than **30 days** (`RETENTION_DAYS`).
- **API + UI:** one Vercel project. `index.html` is served by the CDN; every
  `/api/*` request is rewritten to the `api/index.py` serverless function.

---

## 1. Neon (database)

1. Create a project at <https://neon.tech> and a database named `bestquotes`.
2. Copy **two** connection strings from the Neon dashboard:
   - **Pooled** (host contains `-pooler`) → for Vercel (the API).
   - **Direct** (no `-pooler`) → for the puller / running the schema.
   Both look like
   `postgresql://USER:PASSWORD@ep-xxxx[-pooler].REGION.aws.neon.tech/bestquotes?sslmode=require`.
3. Apply the schema (uses the direct string):
   ```bash
   psql "postgresql://…neon.tech/bestquotes?sslmode=require" -f price-quotes/db/schema.sql
   ```

## 2. GitHub (the 5-min puller)

1. Create a repo and push this folder to it.
   > **Make the repo PUBLIC.** GitHub Actions minutes are unlimited on public
   > repos. On a private repo the 5-min cron (~8,640 runs/month, billed ≥1 min
   > each) blows past the 2,000 free minutes and costs ~$50/month. No secrets
   > are committed — they live in Actions secrets below and `.env` is gitignored.
   > (If you must keep it private, raise the cron interval or expect the cost.)
2. In the repo: **Settings → Secrets and variables → Actions → New repository
   secret**, add:
   | Secret | Value |
   |---|---|
   | `DATABASE_URL` | Neon **direct** connection string |
   | `KALQIX_API_KEY` | from `price-quotes/.env` |
   | `KALQIX_API_SECRET` | from `price-quotes/.env` |
   | `BASE_RPC_URL` | from `price-quotes/.env` |
   | `UNISWAP_API_KEY` | from `price-quotes/.env` |
3. **Settings → Actions → General:** ensure Actions are enabled.
4. Open the **Actions** tab → **pull-quotes** → **Run workflow** to fire the
   first run manually. After that it runs every 5 min on its own.
   > GitHub's scheduler is best-effort: runs may drift a few minutes or, under
   > load, skip. Fine for this dashboard; the schema tolerates gaps.

## 3. Vercel (API + dashboard)

1. Import the same GitHub repo at <https://vercel.com/new>. Framework preset:
   **Other**. Leave build/output settings empty — `vercel.json` handles routing.
2. **Settings → Environment Variables:** add `DATABASE_URL` = Neon **pooled**
   connection string (the `-pooler` one). Apply to Production (and Preview).
3. Deploy. Your dashboard is at `https://<project>.vercel.app/`, and the API at
   `https://<project>.vercel.app/api/...` (same origin — no CORS needed).

## 4. (Optional) migrate existing history

To carry over the data currently on the old box, run once with the SSH tunnel up
(`./start.sh` from the old setup opened `localhost:5433`):

```bash
pg_dump "postgresql://bestquotes:PASS@localhost:5433/bestquotes" \
        --data-only --table=quote_runs --table=quotes \
  | psql "postgresql://…neon.tech/bestquotes?sslmode=require"
```

The 30-day prune will then trim it to the retention window on the next run.

---

## Local development

No SSH tunnel anymore — you connect straight to Neon.

```bash
cp .env.example .env          # put a Neon connection string in DATABASE_URL
./start.sh                    # dashboard + API at http://localhost:8000
```

`start.sh` creates a venv, installs `api/requirements.txt`, and runs
`uvicorn api.index:app`, which serves both `index.html` and `/api/*`.

## Knobs

- **Cadence:** edit `.github/workflows/pull-quotes.yml` (`cron: "*/5 * * * *"`).
- **Retention:** edit `RETENTION_DAYS` in the same workflow (default `30`).
  Storage ≈ RETENTION_DAYS × ~25k rows/day at 5-min cadence.
