# Snowflake access explorer

See who can access what in Snowflake, and through which roles. It runs on your own machine, only reads from Snowflake, and never changes a grant.

**Full guide: [README.html](README.html)**, in this folder. It covers every screen with screenshots, how to read the graphs, all 23 rules, settings and limits. Open it in a browser: double-click it, or run `start README.html`. GitHub shows it as source code, so open your local copy.

## What it does
```mermaid
flowchart LR
  U(["You<br/>browser"]) -- "1 open localhost:8000" --> APP["Access explorer<br/>React + FastAPI on your machine"]
  APP -- "2 log in: SSO or key pair" --> SF[("Snowflake<br/>grants · users · tags · policies")]
  SF -. "3 read only" .-> APP
  APP -. "4 pages · graphs · rule checks · CSV" .-> U
```
Key: solid = calls · dashed = data moves · numbers = order.

- **Every path, at any depth.** It walks the whole role hierarchy, database roles (`DB.ROLE`) included, so access inherited ten roles deep shows up next to direct grants, each with its full chain (`ANALYST_01 > GRP_ANALYSTS > F_ANALYST > T_SALES_CORE_READ > TABLE`).
- **Who reads sensitive data.** It uses classification tags and masking or row access policies to show which columns each role sees in clear.
- **Rule checks.** 23 checks of the role model, such as a technical role granted to a person, an admin role held by a user, dormant users or PUBLIC grants. Each finding comes with the fix as infrastructure-as-code text and the matching SQL.
- **What if.** Pick grants to take away (a role from a user or role, a privilege, a whole role, or everything on PUBLIC) and see who loses what, who keeps it another way, which objects and roles are left behind, and which findings go away or appear. It is a simulation: it prints the REVOKE text for your infrastructure as code and never runs it.
- **Readable graphs.** One lane per depth from the user, many database roles of one database folded into one box, huge boxes grouped by schema and type, hover explains each line in words, and each box shows its worst rule finding ("High · 3", click opens them). Snowflake's own built-in grants that every user gets through PUBLIC are one folded box, not findings.
- **Read-only.** It only reads from Snowflake. It never runs GRANT, REVOKE, CREATE or ALTER and writes nothing to Snowflake. Locally it keeps a copy of what it read in `.cache/` (git-ignored) for a day; no passwords.
- **Works with what you have.** It shows the whole account if your role can read it, and only your own access if not (My access).

## Questions it answers
| Page | Question |
|---|---|
| User | What can this user reach, through every role? Graph, privileges with their paths, sensitive data, roles used. |
| Role | Who holds this role, what does it give, and who loses access if it is revoked? |
| Object | Who can touch this table or view, and how? Which columns are masked for whom? |
| Can they? | Can user X do SELECT, INSERT, CREATE TABLE, etc. on Y, or leave Privilege on **Any** to see every access X has on Y? Yes, with every path and how to remove it, or no, with the role to ask for. |
| Sensitive data | Which objects are sensitive, who reads them, and which columns are unmasked? Two roles compared. |
| Rule checks | Where does the role model break its own rules? Severity, findings and fixes. |
| Access review | One row per user and object in a database, with the path, exported as CSV with Reviewer and Keep/Revoke columns. |
| What if | If we revoke this, who loses what, and what is left behind? Start here or from "What if revoked?" on role pages, paths, findings and Can they?. |

Find (top bar) opens any user, role or object. Every view is a link (`?page=role&name=F_ANALYST`), so you can share it.

![User page: findings, profile, KPIs and the role graph](docs/img/user-graph.png)
![Can they?: yes, every path, and how to remove the access](docs/img/can-they.png)
![Rule checks: severity counts, rule map and rules by area](docs/img/rule-checks.png)

More screens, and how to read them: [README.html](README.html).

## Quick start
Needs Python 3.10+ and git. No Node or npm: the web app comes built.
```
git clone https://github.com/darshanmeel/snowflake-access-explorer.git
cd snowflake-access-explorer
python -m venv .venv; .venv\Scripts\activate          # macOS/Linux: python3 -m venv .venv; source .venv/bin/activate
pip install -r requirements-web.txt
python run.py --fake                                  # try it on fake data: open http://localhost:8000
```
For your own account: `copy .env.example .env` (macOS/Linux: `cp`), fill in account, user, role and warehouse (step 3 below), then `python run.py`. A browser tab opens for the Snowflake login. The details follow.

## Run it
The **local web app (React)** is the recommended and default version: it runs on your machine and reads Snowflake with your own login. The Streamlit version runs the very same React app inside Streamlit, so both look and work the same. Data comes from Snowflake by default; fake data only with `--fake`. Both use the same code (`access.py`).

| | `SOURCE=direct` (default) | `SOURCE=objects` |
|---|---|---|
| Creates in Snowflake | Nothing: no tables, procedures or functions | Snapshot tables, `SP_ACCESS_SNAPSHOT`, `SP_ACCESS_FINDINGS`, table functions `TF_ACCESS_OF` / `TF_WHO_CAN` / `TF_CAN` (`sql/1_setup.sql`) |
| How the data is read | The app queries Snowflake with your role (`access.live()`) | The procedure reads it with its owner's rights into `TBL_ACCESS_` tables; the app reads the last snapshot |
| Use it when | You can't (or don't want to) create objects, or you just want to try it | A team wants one shared, scheduled copy, viewers with low rights, and SQL in worksheets without the app |
| Settings | nothing more | `ACCESS_SNAPSHOT=<DB>.<SCHEMA>`, or `SNOWFLAKE_DATABASE` and `SNOWFLAKE_SCHEMA` |

With `SOURCE=direct` the shared data is read only when you click **Load shared data** (a copy from the last 24 h opens at
once), so **My access** works without waiting for it. Without ACCOUNT_USAGE it reads with one `SHOW` per role, sent 16 at a
time (`SHOW_THREADS`); `IMPORTED PRIVILEGES` on database `SNOWFLAKE` makes it one fast query. The sidebar's
**Incomplete** box says what could not be read and which grant fixes it.

Data does not need to be real time. Once read, it is kept for 24 h in memory and in `.cache/` (one file per account and source, and one per user for My access). The sidebar shows **Data from &lt;time&gt;**; **Read Snowflake again** reads it again. For `objects`, schedule `SP_ACCESS_SNAPSHOT` as a daily task (README.html, Run modes and setup).

### 1. Install once (PowerShell; needs Python 3.10+ and git, no Node or npm)
```
git clone https://github.com/darshanmeel/snowflake-access-explorer.git
cd snowflake-access-explorer
python -m venv .venv; .venv\Scripts\activate          # macOS/Linux: python3 -m venv .venv; source .venv/bin/activate
pip install -r requirements-web.txt
```
If `activate` says running scripts is disabled, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then activate again.
The web app comes built (`web/dist`, and `web/dist-st` for Streamlit), so running it needs only Python. Update: `git pull; pip install -r requirements-web.txt`.
Developers who change `web/src` rebuild both bundles with Node 20+ (`cd web; npm ci; npm run build; npm run build:st`) and commit them.

### 2. Start it
```
python run.py                    # local web app on your Snowflake data: http://localhost:8000
python run.py --fake             # fake data, no Snowflake, no .env
python run.py streamlit          # the Streamlit version: http://localhost:8501
python run.py --direct | --objects   # SOURCE for this run
python run.py --port 9000        # another port
```
Both apps can run side by side to compare them: `APP=web|streamlit` picks the default, `WEB_PORT` (8000) and `STREAMLIT_PORT` (8501) the ports. Stop with Ctrl+C.

The fake account has users, functional, technical and group roles, admin holders, sensitive tags, masking policies and at least one finding for each of the 23 rules. **My access** shows one demo user's slice (`ENGINEER_01`, or `DEMO_USER=<name>`).

### 3. Fill in `.env` for Snowflake
```
copy .env.example .env                                # macOS/Linux: cp .env.example .env
```
```
SNOWFLAKE_ACCOUNT=<org>-<account>
SNOWFLAKE_USER=<your Snowflake login name>
SNOWFLAKE_ROLE=<role>
SNOWFLAKE_WAREHOUSE=<WH>
```
- `<org>-<account>` is the start of your Snowflake URL: `https://<org>-<account>.snowflakecomputing.com`.
- Login is browser SSO by default: a tab opens. For a key pair add `SNOWFLAKE_PRIVATE_KEY_FILE=C:\keys\rsa_key.p8` (and `SNOWFLAKE_PRIVATE_KEY_PWD=<passphrase>` if encrypted).
- No passwords in the repo; `.env` is git-ignored. No comment after a value on the same line. A name missing or empty in `.env` comes from the environment variable; a variable set in the shell wins.
- One login per new connection. To reuse a login for about 4 h, an admin runs `ALTER ACCOUNT SET ALLOW_ID_TOKEN = TRUE;` once.

### Settings
| Name | Default | Meaning |
|---|---|---|
| `FAKE` | unset | `1` = fake data (also `python run.py --fake`); anything else = Snowflake |
| `SOURCE` | `direct` (`objects` if `ACCESS_SNAPSHOT` is set) | `direct` or `objects`, see above |
| `ACCESS_SNAPSHOT` | `SNOWFLAKE_DATABASE.SNOWFLAKE_SCHEMA` | `<DB>.<SCHEMA>` of the `TBL_ACCESS_` tables; `SOURCE=objects` without any of these is an error |
| `CACHE_HOURS` | `24` | Hours the local copy in `.cache/` is used; `0` = memory only |
| `BUILTIN` | `SNOWFLAKE.*,SYSTEM_COMPUTE_POOL_*,SYSTEM$*,SNOWFLAKE_LEARNING_*` | Names of Snowflake's built-in roles and objects, folded under PUBLIC and left out of rule checks (`?builtin=1` shows them) |
| `APP`, `WEB_PORT`, `STREAMLIT_PORT` | `web`, `8000`, `8501` | What `run.py` starts, and where |
| `SHOW_THREADS` | `16` | SHOW statements sent at once when ACCOUNT_USAGE is not readable (`1` = one after another) |
| `HOST` | `127.0.0.1` | Address the local web app listens on; `0.0.0.0` on a shared server ([Deploy](#deploy)) |

More settings (`ROLE_PREFIXES`, `DORMANT_DAYS`, ...): README.html.

### What you see depends on your role
| Your role has | You see |
|---|---|
| Only a warehouse | **My access** (top bar): your own roles and everything they reach (User, Role, Object, Can they?, Rule checks on your own roles) |
| `MANAGE GRANTS` | The whole account, read with `SHOW` (slow: one query per role) |
| `IMPORTED PRIVILEGES` on DB `SNOWFLAKE` | The whole account, including tags, policies and query history (fast) |

- If something can't be read, the app still loads and shows **Incomplete** with what is missing and why.
- My access reads with your own rights and writes nothing to Snowflake. It has no sensitivity (tags need the governance views), Rule checks run on your own roles only, and Access review is not available in it.

### Objects in Snowflake (`SOURCE=objects`)
A developer whose role can create tables and procedures runs this once, from the same folder and `.env`:
```
copy settings.sql settings.local.sql      # fill in DB, SCHEMA, WH, DEV_ROLE, APP_ROLE (git-ignored)
python run_sql.py sql/1_setup.sql;     python run_sql.py sql/1_setup_verify.sql      # tables, procedures, functions
python run_sql.py sql/2_snapshot.sql;  python run_sql.py sql/2_snapshot_verify.sql   # CALL SP_ACCESS_SNAPSHOT('AUTO')
```
Then set `ACCESS_SNAPSHOT=<DB>.<SCHEMA>` in `.env` (and `SNOWFLAKE_ROLE=<APP_ROLE>` for viewers) and run `python run.py --objects`.
- `DEV_ROLE` needs `IMPORTED PRIVILEGES` on DB `SNOWFLAKE` (or `MANAGE GRANTS`) to see the whole account; viewers only need `APP_ROLE`.
- Fresh data: schedule `CALL SP_ACCESS_SNAPSHOT('AUTO')` as a **daily task**, or rerun `sql/2_snapshot.sql` (README.html, Run modes and setup). **Rebuild snapshot** in the app runs the procedure too.
- Without the app, in a worksheet: `SELECT * FROM TABLE(TF_ACCESS_OF('<USER>', NULL));`, `TF_WHO_CAN`, `TF_CAN`, `CALL SP_ACCESS_FINDINGS('{}')`.
- SnowSQL instead of `run_sql.py`: `!source` the same `sql/` files in order. Remove everything: `python run_sql.py sql/3_cleanup.sql`.

## Deploy
Four ways to run it. All of them only read; none of them changes grants.

| Where | Who uses it | Login to Snowflake | Data |
|---|---|---|---|
| [Your own machine](#on-your-own-machine) | you | your own (browser SSO or key pair) | what your role can read |
| [A shared server](#on-a-shared-server-local-web-app-or-streamlit) | a team, in the browser | one service user (key pair) | what that user's role can read |
| [Streamlit in Snowflake](#streamlit-in-snowflake-sis) | anyone with the app role, in Snowsight | none extra: Snowflake's own login | what the owner role can read |
| [Streamlit elsewhere](#streamlit-anywhere-else) | a team, in the browser | one service user (key pair) | what that user's role can read |

### On your own machine
The [Quick start](#quick-start) and steps 1 to 3 above: `python run.py` (React, http://localhost:8000) or `python run.py streamlit`
(http://localhost:8501). It listens on your machine only (`127.0.0.1`). Nothing to install in Snowflake with `SOURCE=direct`.

### On a shared server (local web app or Streamlit)
A VM or container your team can reach, with Python 3.10+:
```
git clone https://github.com/darshanmeel/snowflake-access-explorer.git
cd snowflake-access-explorer
python3 -m venv .venv; source .venv/bin/activate; pip install -r requirements-web.txt
HOST=0.0.0.0 python run.py                                                   # React on port 8000
python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true   # or Streamlit
```
- Browser SSO can't work on a server (the login tab would open there): create a service user with a **key pair** and set
  `SNOWFLAKE_PRIVATE_KEY_FILE` (and `SNOWFLAKE_PRIVATE_KEY_PWD`) in `.env`. Everyone then sees what that user's role sees.
- Prefer `SOURCE=objects` with the daily snapshot task: the service role then needs only `SELECT` on the `TBL_ACCESS_` tables.
- The app has no login of its own and shows who can reach what: put it behind your company sign-in (VPN, a reverse proxy
  with SSO) and never on the open internet.
- Keep it running with your usual tool (systemd, Docker, a Windows service). Update: `git pull; pip install -r requirements-web.txt`, then restart.

### Streamlit in Snowflake (SiS)
The app runs inside Snowflake and opens in Snowsight; nobody installs anything. It runs the same React app as one Streamlit
component (`web/dist-st/`, committed); its data calls are answered in Python by the same code as the local server.
It uses the app's own Snowflake session, keeps data in memory only (24 h) and writes nothing.

1. Do the [Objects in Snowflake](#objects-in-snowflake-sourceobjects) setup first (`1_setup.sql`, `2_snapshot.sql`, the daily task):
   inside Snowflake the app reads the `TBL_ACCESS_` tables.
2. Settings for the app go in `sis/.env` (required, git-ignored), uploaded as the app's `.env`:
   `copy sis.env.example sis\.env` (macOS/Linux: `cp sis.env.example sis/.env`) and fill in:
   ```
   SOURCE=objects
   ACCESS_SNAPSHOT=<DB>.<SCHEMA>
   ```
   Inside Snowflake the app reads the snapshot tables: direct reads need `SHOW`, which is restricted there. Never put
   `SNOWFLAKE_ACCOUNT` or a key in this file: without it the app knows it runs inside Snowflake and uses the app's session.
3. Upload the files and create the app, from the repo folder with the same `.env` and `settings.local.sql` as step 1:
   ```
   python run_sql.py sql/4_streamlit.sql;  python run_sql.py sql/4_streamlit_verify.sql
   ```
   It creates the stage `STG_ACCESS_APP`, uploads the Python files, `environment.yml` (packages: `streamlit`,
   `snowflake-snowpark-python`) and `web/dist-st`, creates the Streamlit app `ST_ACCESS_EXPLORER` (warehouse `WH`) and grants
   `USAGE` on it to `APP_ROLE`. SnowSQL: `!source sql/4_streamlit.sql`.
4. Open it in Snowsight: **Projects > Streamlit > ST_ACCESS_EXPLORER**. To update after `git pull`, run step 3 again.

- The app runs with its **owner's rights** (`DEV_ROLE`): every viewer sees what that role reads, not their own access.
  So **My access** (each person's own view) is hidden there; it is a feature of the local version.
- If the page stays blank (the React component blocked in your account), add `ST_REACT=html` to `sis/.env` and run step 3
  again: the app then shows its plain Streamlit pages (same data, simpler look).
- Remove it: `python run_sql.py sql/3_cleanup.sql` (drops the app and its stage too).

### Streamlit anywhere else
Any host that runs Python (a VM, Docker, Kubernetes, a Streamlit hosting service):
```
pip install -r requirements.txt
python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true
```
- Settings as environment variables or a `.env` next to `app.py`, with a **key pair** login as on a shared server.
  Hosting services that offer "secrets" usually turn them into environment variables; the key itself must be a file the app
  can read (`SNOWFLAKE_PRIVATE_KEY_FILE`).
- The same warnings as for a shared server: one service user's view, no login of its own, so keep it private, never public.
- Fake data to try a host first: `FAKE=1`.

### Container Services (optional)
Only to give everyone the local web app without each person installing it: run `server.py` as a Snowpark Container Services
service (any container image with Python and `requirements-web.txt`, `HOST=0.0.0.0`). Not needed to use the app.
Snowflake sets `SNOWFLAKE_ACCOUNT` in the container, so the app logs in like on a shared server: give the service
`SNOWFLAKE_USER` and a key pair (`SNOWFLAKE_PRIVATE_KEY_FILE`, mounted as a secret). Browser SSO can't work there.

## Also in this repo
- **`sf.py` runs plain SQL from your machine.** It uses the same `.env` and logins. Run `python sf.py "select current_user(), current_role()"` or `python sf.py -f query.sql`, or from Python: `from sf import run; cols, rows = run("select 1")`.
- **Tests:** `python test_access.py`, `python test_sql.py` and `python test_server.py` (all set `FAKE=1` themselves). They include a check that every page renders.
- **Commit guardrail:** `.githooks/pre-commit` blocks a commit if a staged file matches a term in `~/.company-terms.txt`. Turn it on once with `git config core.hooksPath .githooks`, after creating that file (one regex per line). Without the file, the hook blocks every commit.
- **Roles and grants** are managed as infrastructure as code. This app only reads them and never changes them.

## Where to find more
[README.html](README.html) covers:
- every screen, one by one, with screenshots;
- how to read the graphs;
- the 23 rules;
- run modes and the one-time setup for snapshot tables;
- the role model;
- SQL functions for worksheets;
- data sources;
- all settings, and the limits.

## License

Dual-licensed under either of [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE), at your option.
Unless you say otherwise, any contribution you submit is licensed the same way, with no extra terms. Bundled third-party code keeps its own licenses: [THIRD_PARTY.md](THIRD_PARTY.md).
