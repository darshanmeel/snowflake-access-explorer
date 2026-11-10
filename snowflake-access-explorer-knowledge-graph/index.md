# Snowflake access explorer: knowledge graph index

Read-only app that explains who has what in Snowflake and through which path; this graph maps its code, data, flows, rules and processes (built 2026-11-10, commit ab685a6).

## Big picture

```mermaid
flowchart LR
  SF[Snowflake: TBL_ACCESS_ tables or ACCOUNT_USAGE / SHOW] --> ACC[access.py: snapshot, live, walks, 23 rules]
  CACHE[cache.py: memory, .cache pkl, DuckDB copy] <--> ACC
  ACC --> SRV[server.py: pages + JSON API]
  SRV --> WEB[web/: React app]
  SRV --> ST[app.py + st_react.py: Streamlit in Snowflake]
  SQL[sql/: setup, snapshot, streamlit deploy] --> SF
```

- Boxes: Snowflake side (`sql/1_setup.sql`), data and rules (`access.py:401` snapshot, `access.py:560` live, `access.py:4475` checks), cache (`cache.py`), server (`server.py:2231` make_app), two front ends (`web/src/App.tsx:249` VIEWS, `app.py:18` st_react.app).
- Hard rule: the app never runs GRANT / REVOKE / DDL (`CLAUDE.md`, see `documents/claude-md.md`).

## Entry points

- `run.py`: starts the local web app or Streamlit (`processes/run-local.md`).
- `server.py:2231` `make_app()`: FastAPI app, 30 endpoints (`modules/server.md`).
- `app.py:18`: Streamlit in Snowflake page, runs the same React app (`flows/streamlit-in-snowflake.md`).
- `sql/1_setup.sql`: tables, `SP_ACCESS_SNAPSHOT`, table functions (`data/model.md`, `modules/sql.md`).
- `web/src/App.tsx`: React router and page map (`modules/web.md`).

## Where to look for what

| Question | Go to |
|---|---|
| How does a request / snapshot / My access / what-changed run, step by step? | `flows/` (snapshot-objects, direct-live, web-request, streamlit-in-snowflake, my-access, startup, what-changed) |
| What does rule N check? How are paths counted, depth, what-if, graph roll-up, caching? | `logic/` (rules, walks, rbac-model, what-if, graph-input, diff, caching) |
| What does file / module X do, what calls what? | `modules/` (access, server, cache, sf, app-and-st_react, ui, run-scripts, web, sql, tests) |
| Which tables, columns, joins, dict keys, DuckDB copy? | `data/` (model.md, one page per `TBL_ACCESS_*`, snapshot-dict, duckdb-copy, model.json) |
| How to set up, run, deploy, build the web bundles, test? | `processes/` |
| What do README / CLAUDE.md / review notes / env templates say? | `documents/` (start at `documents/README.md`) |
| Machine-readable graph (nodes, edges with path:line) | `graph/nodes.jsonl`, `graph/edges.jsonl`; per-part sources in `graph/parts/` |

## Known gaps

- `unclear` / `inferred` marks are kept on the nodes, edges and pages; each page ends with its own unclear list.
- TypeScript line ranges are approximate (tag `range-heuristic`); vitest cases are not extracted.
