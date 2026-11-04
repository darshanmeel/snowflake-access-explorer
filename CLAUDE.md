# Access explorer: standards

Read-only Streamlit app that explains Snowflake access: who has what, and through which path.

## Hard rules
- Read-only. The app never runs GRANT, REVOKE, CREATE, ALTER or DROP. RBAC changes go through
  infrastructure as code; manual grants get removed by reconciliation.
- The app writes nothing to Snowflake. Shared view: reads the `TBL_ACCESS_` tables and may CALL `SP_ACCESS_SNAPSHOT`
  (owner's rights). My-access view: read-only queries as the logged-in user. Locally the only thing written is
  `.cache/` (git-ignored, `cache.py`: one file per account + source, one per user for My access, `CACHE_HOURS`=24, 0 = memory
  only); in memory 24 h per process. Inside Snowflake (SiS) memory only, no disk. Data needs no real time: the UI shows
  "Data from <time>" and a refresh (Read Snowflake again) that reads again.
- The app reads only the `TBL_ACCESS_` snapshot tables in the shared view. `SP_ACCESS_SNAPSHOT` (sql/1_setup.sql) fills them from
  ACCOUNT_USAGE, or SHOW when ACCOUNT_USAGE is not readable, and writes nothing else.
- `SOURCE=direct|objects` (default direct; `objects` if only `ACCESS_SNAPSHOT` is set; objects location = `ACCESS_SNAPSHOT` or
  `SNOWFLAKE_DATABASE.SNOWFLAKE_SCHEMA`, else an error; `cache.config()`). Fake data only with `FAKE=1` (`run.py --fake`);
  tests set it themselves.
- Direct mode (`SOURCE=direct`, for accounts where procedures can't be created): `access.live()` reads the same
  sources with the user's role into memory, same dict as `snapshot()`. Keep it in step with `SP_ACCESS_SNAPSHOT`; `test_live` checks it.
- No credentials, account names or company names in code or the repo. Real values live in git-ignored
  `settings.local.sql` and `.env` (env vars, template `.env.example`). Connection via `sf.py` (`connect()`), all files at the repo root.
- The procedure uses only the read sources in README > "Data sources". No queries on business data.
- Don't commit or push unless asked. Commits pass `.githooks/pre-commit` (company-term check, `git config core.hooksPath .githooks`); never bypass it with `--no-verify`.

## Two versions, one logic
- **Local (recommended, default):** `server.py` (FastAPI, JSON API over `access.py`) + `web/` (React). Runs on your machine.
  `python run.py` (web), `run.py streamlit`, `--fake`, `--direct` / `--objects`, `--port N`; env `APP`, `WEB_PORT` (8000),
  `STREAMLIT_PORT` (8501) so both run side by side.
- **Streamlit in Snowflake:** `app.py` runs the same React app (`web/src/App.tsx`) as one Streamlit component
  (`st_react.app`): its API calls come back to Python and are answered by `server.py` functions, so both versions show
  identical pages. `ST_REACT=native` (or `html`) runs the plain Streamlit pages in `app.py` + `ui.py` as a fallback.
- Built bundles `web/dist` and `web/dist-st` are committed: users only run Python, never npm. After any change in
  `web/src`, rebuild both (`npm run build`, `npm run build:st`) and commit them.
  Must keep running as a Streamlit app inside Snowflake: `sql/4_streamlit.sql` deploys it (stage + `CREATE STREAMLIT`,
  settings from the required `sis/.env`, `SOURCE=objects`); there (`a.INSIDE`: no `SNOWFLAKE_ACCOUNT`) `sf.connect()`
  uses the app's session, never closed, and My access is hidden (owner's rights, not the viewer's). Container Services: optional, only to give everyone the local version.
- `access.py` is the only place for data, walks and rules; both versions call it, neither has its own logic.
- **If you change one version, change the other in the same task:** a page, tab, column, graph style or rule shown
  locally must show in Streamlit too (and the reverse). Shared React components change once in `web/src/components/`;
  rebuild both bundles. `test_server.py` and `test_pages` both cover every page.

## RBAC model
- Account roles, plus database roles: a database role (named `DB.ROLE`, kind "database") is a role that is held, not
  an object. USAGE on `GRANTED_ON = 'DATABASE_ROLE'` is a role link like `'ROLE'`; its own grants come from
  `SHOW GRANTS TO DATABASE ROLE` (or ACCOUNT_USAGE `GRANTED_TO = 'DATABASE_ROLE'`, grantee qualified with its database).
- Chain: user / service user / group role -> functional role (`FUNC`) -> technical role (`TECH`) -> objects.
  Prefixes `F_` / `T_` by default, `ROLE_PREFIXES` env var for another naming. Use `a.FUNC` / `a.TECH`, never literals.
- Technical roles: `<TECH><DB>_OWNER`, and `<TECH><DB>_<SCHEMA>_OWNER|READ|WRITE|EXECUTE` per schema.
- Default links: schema OWNER -> DB OWNER, READ -> WRITE. Cross-schema and cross-database links exist.
- Never parse role names to get the DB or schema (names contain underscores). Use grant data.
- Snowflake built-ins (`BUILTIN` patterns: SNOWFLAKE.*, system compute pools, ...) reached via PUBLIC are hidden from walks,
  counts and rules (`a.hidden`), drawn as one fold box under PUBLIC; `builtin=1` shows them. Never rule 9 / 13 findings.
- What if (`a.what_if`): simulation only, restores every lookup afterwards; prints REVOKE / IaC text, never runs it.
- Admin roles `ACCOUNTADMIN`, `SECURITYADMIN`, `SYSADMIN`, `USERADMIN`, `ORGADMIN`: hide the "every role -> SYSADMIN"
  hierarchy. Show any user or role that holds an admin role in red, with its path.
  Show account-level privileges (MANAGE GRANTS, CREATE DATABASE, ...) in red too.

## Code style
- Simple and minimal: plain functions, no classes. Python: standard library + streamlit + pandas
  + snowflake-connector-python, plus fastapi + uvicorn for the local web version only.
  Web: React + TypeScript + Vite, @xyflow/react + elkjs for graphs; nothing else without asking.
- App: `access.py` (fake data, snapshot loader, graph walks, rule checks; no Streamlit import, testable, `test_access.py`),
  `ui.py` (theme tokens, CSS, HTML components, SVG lane graph; no data logic) and `app.py` (pages, URL state).
- Snowflake side: names in `settings.local.sql` (template `settings.sql`), `sql/<n>_<step>.sql` with `-- name:` statements
  (`(may fail)`, `(expect N)`) plus `_verify.sql`, run by `run_sql.py` or SnowSQL. Use `&NAME`, never hard-code names.
- Load the snapshot once and cache it (`st.cache_data`, ttl 1h). The app does its walks in Python, not SQL. For use
  without the app, `sql/1_setup.sql` also creates the table functions `TF_ACCESS_OF` / `TF_WHO_CAN` / `TF_CAN` and the
  procedure `SP_ACCESS_FINDINGS` (runs `access.py`); `test_sql.py` keeps them equal to `access.py`.
- Walks give full paths: exact path counts without listing (count over the role graph), the shortest by BFS, every chain
  listed lazily up to `MAX_PATHS` ("first 200 of N"). Guard against cycles. Users and roles are separate namespaces.
- Depth = roles from the start to the grant holder, holder included, the same on every page; graph lanes by shortest depth.
- Big accounts: `graph_input()` rolls objects up to schema / database nodes over `MAX_OBJECTS` (12, a lane's boxes); tables list every object.
  Over 30 role boxes or 6 role lanes, `summary()` draws granted roles -> one fold box each -> grant holders -> groups (`?full=1`: all).
- Graphs: `ui.lane_graph` (own SVG, one lane per depth, nodes are links). Node styles from `ui.TOKENS`:
  user = pill, functional = blue, technical = coffee, group role = dashed amber, database role = dashed grey-blue, object = grey,
  admin role / account privilege = red. Put the legend next to each graph.
- Keep `FAKE=1` mode on the fake data in `access.py`, so it runs without Snowflake. Fake data keeps at least
  one finding per rule.
- UI: sections are tabs, never stacked one under the other; a long page is split into tabs.
- Short names, comments only for the non-obvious "why", no extra error handling or logging.

## Verify before saying done
- `.venv\Scripts\python -c "import access as a; a.build(a.fake()); print(sorted({c[0] for c in a.checks()}, key=int))"` lists all 23 rules (each has a finding on the fake data):
  1 technical role on user/group · 2 direct privilege on functional · 3 READ direct + inherited · 4 OWNER on consumer ·
  5 admin role on person · 6 sensitive column unmasked · 7 dormant/disabled reads sensitive · 8 disabled holds roles ·
  9 PUBLIC grant · 10 person writes sensitive · 11 sensitive via group role · 12 admin default role · 13 orphan role ·
  14 deep chain · 15 future grant on sensitive schema · 16 dormant holds roles · 17 read-only role writes ·
  18 unusual privilege set · 19 EXECUTE TASK on person/consumer · 20 task OPERATE outside owner/build ·
  21 warehouse MODIFY/OPERATE outside owner/build · 22 stream on sensitive table without table read ·
  23 schema CREATE on read-only role.
- `python test_access.py` and `python test_sql.py` green (test_access reruns itself with `ROLE_PREFIXES=ZF_,ZT_`).
- Spot-check paths: a user via a group role, a role reached through 2 paths, an admin holder.
- `test_pages` (in test_access.py): every page renders without an exception.
