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
