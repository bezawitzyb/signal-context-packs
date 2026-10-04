# SIGNAL - Context Packs

Audience research packs for people and AI agents: SIGNAL reads public
discussion about a brief, clusters what people actually say, and returns a
structured, evidence-linked **context pack** (JSON, Markdown, spreadsheet,
agent skill, MCP).

> Work in progress - the live app currently shows a placeholder.

- **Live app:** https://signal-l2w5.onrender.com
- **Pack format:** [docs/SCHEMA.md](docs/SCHEMA.md)
- **Health check:** `GET /health` (status, version, database reachable)

## Run locally

```sh
./start.sh            # http://localhost:7860
```

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). Settings come
from a local `.env` (copy `.env.example`); it is never committed.
