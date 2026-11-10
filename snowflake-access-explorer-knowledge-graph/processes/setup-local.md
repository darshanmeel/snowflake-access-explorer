Set up a local machine once: Python venv, pip requirements, `.env` from `.env.example`, and (objects mode / Snowflake deploy only) `settings.local.sql` from `settings.sql`.

```mermaid
flowchart LR
  A[git clone] --> B[python -m venv .venv]
  B --> C{which version?}
  C -->|web, default| D[pip install -r requirements-web.txt]
  C -->|Streamlit local| E[pip install -r requirements.txt]
  C -->|tests| F[pip install -r requirements-dev.txt]
  D --> G[copy .env.example .env]
  E --> G
  G --> H{SOURCE=objects or SiS deploy?}
  H -->|yes| I[copy settings.sql settings.local.sql]
  H -->|no| J[python run.py]
  I --> J
```

## Steps
- Needs Python 3.10+ and git, no Node or npm (web app comes built) — README.md:72, README.md:122.
- Create and activate venv: `python -m venv .venv; .venv\Scripts\activate` — README.md:126. Execution-policy hint if `activate` is blocked — README.md:129.
- Install the web version: `pip install -r requirements-web.txt` — README.md:127.
- Update later: `git pull; pip install -r requirements-web.txt` — README.md:130.
- Try without Snowflake: `python run.py --fake` — README.md:78.

## Requirements files
| File | For | Contents (pinning) |
|---|---|---|
| `requirements-web.txt` | local web version, also shared server — requirements-web.txt:1 | snowflake-connector-python `>=3.12,<6`, fastapi `==0.135.3`, uvicorn `==0.46.0`, duckdb `>=1.0` (optional SQL copy) — requirements-web.txt:2-5 |
| `requirements.txt` | Streamlit version (`run.py streamlit`) — requirements.txt:1 | streamlit `>=1.50,<2`, snowflake-connector-python — requirements.txt:2-3 |
| `requirements-dev.txt` | tests — requirements-dev.txt:1 | `-r requirements.txt`, `-r requirements-web.txt`, httpx `==0.28.1` — requirements-dev.txt:2-4 |
| `environment.yml` | Streamlit in Snowflake only, uploaded by sql/4_streamlit.sql — environment.yml:1 | channel `snowflake`, `streamlit=1.52.*` pinned, `snowflake-snowpark-python` — environment.yml:4-9 |

- duckdb is only in requirements-web.txt; without it the app runs and notes why there is no SQL copy — CLAUDE.md:14-15.

## `.env` (from `.env.example`, git-ignored)
- Copy: `copy .env.example .env` — README.md:147. `.env` is git-ignored — .gitignore:3.
- Rules: `NAME=value`, no comment after a value; empty/missing name falls back to env var; a shell variable wins — .env.example:1; loader uses `os.environ.setdefault` — access.py:17-24.
- Names only (values never stored here):
  - Source/data: `FAKE`, `SOURCE`, `ACCESS_SNAPSHOT`, `CACHE_HOURS` — .env.example:4-10.
  - Runner: `APP`, `WEB_PORT`, `STREAMLIT_PORT` — .env.example:12-14.
  - Shared server: `HOST` (comment), `ALLOWED_HOSTS`, `MY_ACCESS` — .env.example:15-18.
  - Login: `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_ROLE`, `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA` — .env.example:21-27; read by sf.connect() — sf.py:27-34.
  - Secret refs: `SNOWFLAKE_PRIVATE_KEY_FILE`, `SNOWFLAKE_PRIVATE_KEY_PWD` (key pair; else browser SSO) — .env.example:28-29, sf.py:35-40.
  - Optional: `ROLE_PREFIXES` (and others listed in README.html > Settings) — .env.example:31-32.
- Missing `SNOWFLAKE_ACCOUNT` outside Snowflake raises "copy .env.example to .env" — sf.py:23-25.
- Settings table with defaults — README.md:160-174.

## `settings.local.sql` (from `settings.sql`, git-ignored)
- Needed only for `run_sql.py` / SnowSQL (objects setup, SiS deploy) — settings.sql:1-2, README.md:223.
- Names: `DB`, `SCHEMA`, `WH`, `DEV_ROLE`, `APP_ROLE`, `HERE` (SnowSQL only; run_sql.py fills it) — settings.sql:5-14, run_sql.py:19.
- git-ignored — .gitignore:4.
- run_sql.py falls back to settings.sql if no local file, then stops if any `<placeholder>` is left — run_sql.py:17, run_sql.py:22-27.

## Local-only files
- `.cache/` (git-ignored) holds the pickled data and `access.duckdb` — .gitignore:7, CLAUDE.md:9-15.
- `.streamlit/config.toml`: local runs only, not uploaded to SiS — .streamlit/config.toml:1-10, sql/4_streamlit.sql:44.
- `local.ps1` is git-ignored — .gitignore:5; its purpose is unclear (no tracked file describes it).
