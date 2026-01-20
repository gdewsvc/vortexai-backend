# VortexAI — Deployment Guide (Production)

This repo is a **production-ready starter** for:
- Buyer intake
- Seller intake
- Deal ingest
- Deal scoring (OpenAI optional)
- Buyer matching
- Email notifications (SMTP)

## 0) What you need
- **Supabase Postgres** (or any Postgres)
- **Railway / Render / Fly.io / Docker host**
- (Optional) **OpenAI API key** for scoring
- (Optional) SMTP credentials for sending email

> NOTE: The included `scrapers.py` is a safe starter (RSS/CSV/official APIs). Many marketplaces prohibit scraping.

---

## 1) Create Supabase project
1. Create project
2. Get **Database URL** from Project Settings → Database
   - Use the **session/transaction** connection string in production where available.

## 2) Create tables
- Open Supabase SQL Editor
- Paste and run `schema.sql`

## 3) Set environment variables
These are required:
- `DATABASE_URL` (Postgres connection string)
- `ADMIN_EMAIL` (where admin deal alerts go)

Optional:
- `OPENAI_API_KEY`
- `OPENAI_MODEL` (default: `gpt-4o-mini`)
- `MATCH_THRESHOLD` (default: `0.65`)
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`

Example:
```
DATABASE_URL=postgresql+asyncpg://postgres:PASS@HOST:5432/postgres
ADMIN_EMAIL=you@example.com
OPENAI_API_KEY=sk-...
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASS=app-password
SMTP_FROM="VortexAI <you@gmail.com>"
```

## 4) Deploy
### Option A — Railway
1. Create new project → Deploy from GitHub
2. Add env vars
3. Deploy

### Option B — Docker
```
docker build -t vortexai .
docker run -p 8000:8000 \
  -e DATABASE_URL="..." \
  -e ADMIN_EMAIL="..." \
  vortexai
```

## 5) Test with cURL
Run:
```
bash CURL_TESTS.sh
```

You should get:
- Buyer + Seller created
- Deal ingested
- Matches generated
- Admin notification queued (or sent if SMTP configured)

---

## 6) Run the safe scraper runner (optional)
```
python scrapers.py
```
It will read sources from:
- `DEAL_SOURCES_JSON` (env) OR
- the `deal_sources` table

And POST deals into:
- `DEAL_INGEST_WEBHOOK_URL` (env) or `http://localhost:8000/webhooks/deal-ingest`

---

## Common issues
- **`DATABASE_URL` must be asyncpg format** for this starter:
  - `postgresql+asyncpg://...`
- If you get SSL errors on hosted Postgres, add `?ssl=true` or `?sslmode=require` depending on provider.
- If SMTP isn’t configured, the app will **queue notifications** in DB and log them.
