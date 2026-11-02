# Access explorer: standards

Read-only Streamlit app that explains Snowflake access: who has what, and through which path.

## Hard rules
- Read-only. The app never runs GRANT, REVOKE, CREATE, ALTER or DROP. RBAC changes go through
  infrastructure as code; manual grants get removed by reconciliation.
- The app writes nothing itself. Shared view: reads the `TBL_ACCESS_` tables and may CALL `SP_ACCESS_SNAPSHOT`
  (owner's rights). My-access view: read-only queries as the logged-in user, kept in server memory only (per browser, 1 h; links reload the page).
- The app reads only the `TBL_ACCESS_` snapshot tables in the shared view. `SP_ACCESS_SNAPSHOT` (sql/1_setup.sql) fills them from
  ACCOUNT_USAGE, or SHOW when ACCOUNT_USAGE is not readable, and writes nothing else.
- No credentials, account names or company names in code or the repo. Real values live in git-ignored
  `settings.local.sql` and `local.ps1` (env vars). Connection via `../sf.py` (`connect()`).
- The procedure uses only the read sources in README > "Source per dataset". No queries on business data.
- Don't commit or push unless asked. Commits pass `../.githooks/pre-commit` (company-term check, `git config core.hooksPath .githooks`); never bypass it with `--no-verify`.

## RBAC model
- Account roles only; database roles are not used.
- Chain: user / service user / group role -> functional role (`FUNC`) -> technical role (`TECH`) -> objects.
  Prefixes `F_` / `T_` by default, `ROLE_PREFIXES` env var for another naming. Use `a.FUNC` / `a.TECH`, never literals.
- Technical roles: `<TECH><DB>_OWNER`, and `<TECH><DB>_<SCHEMA>_OWNER|READ|WRITE|EXECUTE` per schema.
- Default links: schema OWNER -> DB OWNER, READ -> WRITE. Cross-schema and cross-database links exist.
- Never parse role names to get the DB or schema (names contain underscores). Use grant data.
- Admin roles `ACCOUNTADMIN`, `SECURITYADMIN`, `SYSADMIN`: hide the "every role -> SYSADMIN"
  hierarchy. Show any user or role that holds an admin role in red, with its path.
  Show account-level privileges (MANAGE GRANTS, CREATE DATABASE, ...) in red too.

## Code style
- Simple and minimal: plain functions, no classes or frameworks, standard library + streamlit + pandas
  + snowflake-connector-python only.
- App: `access.py` (fake data, snapshot loader, graph walks, rule checks; no Streamlit import, testable, `test_access.py`),
  `ui.py` (theme tokens, CSS, HTML components, SVG lane graph; no data logic) and `app.py` (pages, URL state).
- Snowflake side: names in `settings.local.sql` (template `settings.sql`), `sql/<n>_<step>.sql` with `-- name:` statements
  (`(may fail)`, `(expect N)`) plus `_verify.sql`, run by `run_sql.py` or SnowSQL. Use `&NAME`, never hard-code names.
- Load the snapshot once and cache it (`st.cache_data`, ttl 1h). Do the walks in Python, not SQL.
- Every walk returns full paths and lists all paths, not just the shortest. Guard against cycles.
- Graphs: `ui.lane_graph` (own SVG, one lane per depth, nodes are links). Node styles from `ui.TOKENS`:
  user = pill, functional = blue, technical = coffee, group role = dashed amber, object = grey,
  admin role / account privilege = red. Put the legend next to each graph.
- Keep `FAKE=1` mode on the fake data in `access.py`, so it runs without Snowflake. Fake data keeps at least
  one finding per rule.
- Short names, comments only for the non-obvious "why", no extra error handling or logging.

## Verify before saying done
- `.venv\Scripts\python -c "import access as a; a.build(a.fake()); print(sorted({c[0] for c in a.checks()}))"` lists all 5 rules.
- Spot-check paths: a user via a group role, a role reached through 2 paths, an admin holder.
- DuckDB demo + `take_screens.py`: 0 exceptions on every screen.
