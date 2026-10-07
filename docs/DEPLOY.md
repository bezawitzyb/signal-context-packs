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
- `.github/workflows/keepalive.yml` is scheduled to call `/ping` every 10
  minutes so the free service does not sleep. GitHub treats schedules as
  best effort: in practice it ran every 4-8 hours (checked 2026-10-06), so
  the first visit after a quiet spell can take about a minute. Before a
  demo, open the site (or Actions -> keepalive -> Run workflow) 5 minutes
  early; the static mirror below is the backup. It reads the repository **variable**
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
| `GUEST_RUN_KEY` | optional: temporary run password for a tester (delete to revoke) |
| `DATABASE_URL` | Neon **main** branch, pooled connection string |

## Deploy discipline

- Every push to `main` rebuilds and restarts the service (interrupts a live
  run). Push at most twice a day, never during judging.
- `gitleaks` scans the full history before the first push and every commit.
- No payment method on Render, Neon or GitHub; the instance type stays Free.

## If a deploy fails

Render -> the service -> **Logs** -> copy the last 30 lines and ask
Claude Code to fix and push again.

## API and MCP (Step 3.7)

- Endpoints: `https://signal-l2w5.onrender.com/docs`. Reading packs is public
  (`GET /api/v1/packs` lists the featured packs; any pack is readable by its
  random id). Starting runs needs the run key in the `X-API-Key` header.
- MCP (streamable HTTP): `https://signal-l2w5.onrender.com/mcp`. Read tools
  (`list_packs`, `get_pack_view`, `get_insight`, `search_evidence`) work
  without a key; `create_context_pack` and `get_pack_status` need it.
- Connect Claude Code, read-only (no key):

  ```
  claude mcp add --transport http signal https://signal-l2w5.onrender.com/mcp
  ```

- With the run key (type it yourself in your own Terminal; never commit it):

  ```
  claude mcp add --transport http signal https://signal-l2w5.onrender.com/mcp --header "X-API-Key: <YOUR_KEY>"
  ```

- `/mcp` accepts only localhost and the address Render sets in
  `RENDER_EXTERNAL_HOSTNAME` (DNS-rebinding protection); nothing to configure.
- Featured packs live in `featured/` and load into the database at startup.
  Add one with `cli feature PACK_ID` (privacy check first; costs hidden).

## Saved research runs (Step 2.5, Neon dev branch)

Packs are built from these corpora without re-scraping (`--from-run`, Step 3.x).

| Run id | Brief | Mode | Relevant docs | Cost | Peak memory |
|--------|-------|------|---------------|------|-------------|
| `run_wOcIwOgGDnDUITS2` | Launching a snack brand in the Netherlands | standard, end to end (Apify capped at $1.50), Step 3.7 | 233 | $2.97 (incl. analysis) | 196 MB |
| `run_P81c2BlKyb86SxAj` | Launching a snack brand in the Netherlands | standard (web only) | 231 | $2.52 | 173 MB |
| `run_bz5PBTd-Pr6Xp3f2` | Gen Z and meal prep | standard (Apify capped at $0.20) | 76 | $1.87 | 185 MB |
| `run_hJI0ABjY0_rxZpFu` | Launching a snack brand in the Netherlands | quick (web only) | 52 | $1.13 | 169 MB |
| `run_3VCawdMzhwiERoqS` | Gen Z and meal prep | quick (web only) | 18 | $1.07 | 169 MB |
| `run_y17KKEL1oiOeO-_O` | Heat pumps for homeowners in Germany | quick | 28 | $1.11 | 176 MB |
| `run_gwXBU3TmSwTcXdUd` | snacks | quick (web only) | 13 | $1.23 | 169 MB |

Plan divergence across the four eval briefs: 3 of 73 source units shared (4%, target < 50%).
Memory test: both Standard runs peak below 400 MB, so Step 2.6 (Modal) is not needed.

## Featured packs (Step 3.7)

| Pack | Brief | Run | Labels |
|------|-------|-----|--------|
| `pk_wrvZBhDFsLR9` | Launching a snack brand in the Netherlands | `run_wOcIwOgGDnDUITS2` (fresh, 1,042 s) | strong 3, moderate 8, emerging 22, speculative 27 |
| `pk_CamfAsJ7Zbdr` | Gen Z and meal prep | `run_bz5PBTd-Pr6Xp3f2` (thin evidence) | emerging 23, speculative 24 |

## Guest access for a tester

1. In **your own** Terminal (never in a chat): `openssl rand -base64 18` -> copy the result.
2. Render -> Environment -> add `GUEST_RUN_KEY` with that value (at least 16 characters) -> Save.
   The service restarts (about a minute); this is not a deploy.
3. Send the key to the tester privately. Your own `RUN_KEY` keeps working unchanged.
4. Protect the budget during the test: ask for **Quick** runs only, and lower
   `DAILY_SPEND_CAP_USD` (e.g. `8`, about 2-3 Quick runs) for the day.
5. **Revoke:** Render -> Environment -> delete `GUEST_RUN_KEY` -> Save. New runs with that key are
   refused at once; a run already going finishes normally. Set the cap back to `25`.

`doctor` shows whether guest access is on locally; `demo-check` also checks that the guest key appears
in no file, commit, build or page.

## Static mirror (GitHub Pages, guide B15)

- `.github/workflows/mirror.yml` builds a read-only copy of the web app with the featured packs
  (`backend/scripts/build_mirror.py`) and publishes it to
  https://bezawitzyb.github.io/signal-context-packs/ on every push that changes `featured/` or the
  frontend. It needs no secrets.
- One-time setup: GitHub -> the repo -> **Settings -> Pages -> Build and deployment -> Source:
  GitHub Actions**. Then GitHub -> **Actions -> mirror -> Run workflow** once.
- Try it locally: `cd backend && uv run python -m scripts.build_mirror --base /` and open
  `mirror/index.html` through any static server.

## Before the demo: demo-check

`cd backend && uv run python -m ctxpack.cli demo-check` checks the live service (/ping, /health, new runs
accepted today, featured packs, MCP), the last keep-alive run, the static mirror, a tiny Anthropic call
(< $0.001) and Apify, today's local spend, and security (the real run key appears in no file, no commit,
no web build and not on the live site - compared inside the script, never printed - plus gitleaks).

## Cap test (Step 5.5)

1. Render -> the service -> **Environment** -> `DAILY_SPEND_CAP_USD` = `0.01` -> Save (Render restarts).
2. `https://signal-l2w5.onrender.com/health` shows `"accepting_runs": false`; starting a run in the web
   app is refused with a friendly message; featured packs still open.
3. Set `DAILY_SPEND_CAP_USD` back to `25` -> Save. `/health` shows `"accepting_runs": true` again.
