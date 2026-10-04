# Deploying SIGNAL - Context Packs

**Public URL:** https://signal-l2w5.onrender.com

## How it runs

- One **Render Free** web service, built from the `Dockerfile` in this
  public repo, region **Frankfurt**, auto-deployed on every push to `main`.
- One uvicorn worker on Render's `$PORT` (7860 when `PORT` is not set).
- Data lives in **Neon Postgres** (main branch online, dev branch locally),
  so a redeploy or restart loses nothing.
- Health check path: `/ping` (never touches the database or a paid API).
  `/health` reports the version and whether the database answers.
- `.github/workflows/keepalive.yml` calls `/ping` every 10 minutes so the
  free service does not sleep. It reads the repository **variable**
  `RENDER_URL` (GitHub -> Settings -> Secrets and variables -> Actions ->
  Variables).

## Environment variables (Render -> service -> Environment)

Set by the owner only, never in this repo, GitHub Actions or `render.yaml`:

| Name | What |
|------|------|
| `ANTHROPIC_API_KEY` | Anthropic Console API key |
| `APIFY_API_TOKEN` | Apify API token |
| `AUTHOR_HASH_SALT` | long random sentence (same as local) |
| `RUN_KEY` | run password (never shown anywhere) |
| `DATABASE_URL` | Neon **main** branch, pooled connection string |

## Deploy discipline

- Every push to `main` rebuilds and restarts the service (interrupts a live
  run). Push at most twice a day, never during judging.
- `gitleaks` scans the full history before the first push and every commit.
- No payment method on Render, Neon or GitHub; the instance type stays Free.

## If a deploy fails

Render -> the service -> **Logs** -> copy the last 30 lines and ask
Claude Code to fix and push again.

## Saved research runs (Step 2.5, Neon dev branch)

Packs are built from these corpora without re-scraping (`--from-run`, Step 3.x).

| Run id | Brief | Mode | Relevant docs | Cost | Peak memory |
|--------|-------|------|---------------|------|-------------|
| `run_P81c2BlKyb86SxAj` | Launching a snack brand in the Netherlands | standard (web only) | 231 | $2.52 | 173 MB |
| `run_bz5PBTd-Pr6Xp3f2` | Gen Z and meal prep | standard (Apify capped at $0.20) | 76 | $1.87 | 185 MB |
| `run_hJI0ABjY0_rxZpFu` | Launching a snack brand in the Netherlands | quick (web only) | 52 | $1.13 | 169 MB |
| `run_3VCawdMzhwiERoqS` | Gen Z and meal prep | quick (web only) | 18 | $1.07 | 169 MB |
| `run_y17KKEL1oiOeO-_O` | Heat pumps for homeowners in Germany | quick | 28 | $1.11 | 176 MB |
| `run_gwXBU3TmSwTcXdUd` | snacks | quick (web only) | 13 | $1.23 | 169 MB |

Plan divergence across the four eval briefs: 3 of 73 source units shared (4%, target < 50%).
Memory test: both Standard runs peak below 400 MB, so Step 2.6 (Modal) is not needed.
