Run the app locally with `run.py`: web (FastAPI + React, port 8000, default) or Streamlit (port 8501), on fake data, direct reads or the snapshot tables.

```mermaid
flowchart TD
  R[python run.py args] --> E[import access: loads .env]
  E --> F{--fake?}
  F -->|yes| F1[env FAKE=1]
  R --> S{--direct / --objects?}
  S --> S1[env SOURCE=direct|objects]
  R --> A{app arg or APP}
  A -->|web| W[WEB_PORT = --port or WEB_PORT or 8000] --> W1[python server.py] --> W2[uvicorn on HOST:WEB_PORT]
  A -->|streamlit| T[port = --port or STREAMLIT_PORT or 8501] --> T1[python -m streamlit run app.py --server.port ... --server.headless true]
```

## run.py
- Usage text: run.py:1-10.
- Imports `access` first so `.env` values (WEB_PORT, ...) apply — run.py:16.
- Args: `app` = `web|streamlit`, default `APP` env or `web` — run.py:19; `--fake` — run.py:20; `--port` — run.py:21; `--direct` / `--objects` set `SOURCE` — run.py:22-23.
- `--fake` sets `FAKE=1` in the child env — run.py:27-28; source flag sets `SOURCE` — run.py:29-30.
- Streamlit: `streamlit run app.py`, port `--port` or `STREAMLIT_PORT` (8501), headless, usage stats off — run.py:31-34.
- Web: sets `WEB_PORT` (8000) and runs `server.py` — run.py:35-37; server listens on `HOST` (default 127.0.0.1) — server.py:2344.
- Child runs in the repo folder; exit code passed through — run.py:38.

## Modes (README "Run each mode")
| Mode | Command | Open | Evidence |
|---|---|---|---|
| Fake, web | `python run.py --fake` | :8000 | README.md:88 |
| Fake, Streamlit | `python run.py streamlit --fake` (needs requirements.txt) | :8501 | README.md:89 |
| Direct (default), web | `python run.py` = `--direct` | :8000 | README.md:90 |
| Direct, Streamlit | `python run.py streamlit --direct` | :8501 | README.md:91 |
| Objects, web | `python run.py --objects` (needs `ACCESS_SNAPSHOT` and objects setup) | :8000 | README.md:92 |
| Objects, Streamlit | `python run.py streamlit --objects` | :8501 | README.md:93 |
| Side by side | two terminals | :8000 + :8501 | README.md:94 |
| Other port | `python run.py --port 9000` | :9000 | README.md:95 |
| DuckDB copy off / on for fake | `DUCKDB=0` / `DUCKDB=1` | `.cache\access.duckdb` | README.md:96 |
| Memory only | `CACHE_HOURS=0` | | README.md:97 |
| Shared server | `HOST=0.0.0.0` + key pair | `http://<server>:8000` | README.md:98 |

## Source selection
- `cache.config()`: `SOURCE` or `objects` when `ACCESS_SNAPSHOT` set, else `direct` — cache.py:27-32; anything else is an error — cache.py:34; objects without a location errors — cache.py:39.
- Direct vs objects comparison — README.md:108-113.
- `FAKE=1` forces not-inside — access.py:30; `INSIDE=0|1` explicit — access.py:32-33.

## Data freshness
- Kept 24 h in memory and in `.cache/`; previous run kept as `<name>.prev.pkl` for What changed — README.md:120; `TTL = 24 * 3600` — cache.py:22; `CACHE_HOURS` — cache.py:21.
- Direct mode reads on "Load shared data"; `SHOW_THREADS` (16) when ACCOUNT_USAGE is not readable — README.md:115-118.

## Gates on a local run
- My access off on non-loopback `HOST`, key-pair login, or inside Snowflake; `MY_ACCESS=1|0` decides — server.py:126-140.
- Local API answers only its host names (`allowed_hosts()`) — server.py:2214-2218, README.md:218.
- First run without `.env`: error telling you to copy `.env.example` — sf.py:23-25, README.md:215.

## Dev mode (inferred)
- `npm run dev` serves the page from Vite and proxies `/api` to `server.py` on `ACCESS_API_PORT` (default 8000) — web/vite.config.ts:41-42, web/package.json:7. Not described in README (inferred: developer-only).
