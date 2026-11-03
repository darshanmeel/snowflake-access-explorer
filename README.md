# Snowflake access explorer

See who can access what in Snowflake, and through which roles. It runs on your own machine, only reads from Snowflake, and never changes a grant.

**Full guide: [README.html](README.html)**, in this folder. It covers every screen with screenshots, how to read the graphs, all 23 rules, settings and limits. Open it in a browser: double-click it, or run `start README.html`. GitHub shows it as source code, so open your local copy.

## What it does
```mermaid
flowchart LR
  U(["You<br/>browser"]) -- "1 open localhost:8501" --> APP["Access explorer<br/>Streamlit on your machine"]
  APP -- "2 log in: SSO or key pair" --> SF[("Snowflake<br/>grants · users · tags · policies")]
  SF -. "3 read only" .-> APP
  APP -. "4 pages · graphs · rule checks · CSV" .-> U
```
Key: solid = calls · dashed = data moves · numbers = order.

- **Every path, at any depth.** It walks the whole role hierarchy, database roles (`DB.ROLE`) included, so access inherited ten roles deep shows up next to direct grants, each with its full chain (`ANALYST_01 > GRP_ANALYSTS > F_ANALYST > T_SALES_CORE_READ > TABLE`).
- **Who reads sensitive data.** It uses classification tags and masking or row access policies to show which columns each role sees in clear.
- **Rule checks.** 23 checks of the role model, such as a technical role granted to a person, an admin role held by a user, dormant users or PUBLIC grants. Each finding comes with the fix as infrastructure-as-code text and the matching SQL.
- **Read-only.** It only reads from Snowflake. It never runs GRANT, REVOKE, CREATE or ALTER, and it stores no data or passwords.
- **Works with what you have.** It shows the whole account if your role can read it, and only your own access if not (My access).

## Questions it answers
| Page | Question |
|---|---|
| User | What can this user reach, through every role? Graph, privileges with their paths, sensitive data, roles used. |
| Role | Who holds this role, what does it give, and who loses access if it is revoked? |
| Object | Who can touch this table or view, and how? Which columns are masked for whom? |
| Can they? | Can user X do SELECT, INSERT, CREATE TABLE, etc. on Y? Yes, with every path and how to remove it, or no, with the role to ask for. |
| Sensitive data | Which objects are sensitive, who reads them, and which columns are unmasked? Two roles compared. |
| Rule checks | Where does the role model break its own rules? Severity, findings and fixes. |
| Access review | One row per user and object in a database, with the path, exported as CSV with Reviewer and Keep/Revoke columns. |

Find (top bar) opens any user, role or object. Every view is a link (`?page=role&name=F_ANALYST`), so you can share it.

![User page: findings, profile, KPIs and the role graph](docs/img/user-graph.png)
![Can they?: yes, every path, and how to remove the access](docs/img/can-they.png)
![Rule checks: severity counts, rule map and rules by area](docs/img/rule-checks.png)

More screens, and how to read them: [README.html](README.html).

## Run it locally first
Start on your own machine. Try it with fake data first (no Snowflake, no login), then point it at your Snowflake. On Snowflake you choose one of two ways; both use the same code (`access.py`) and read the same sources:

| | B1. Direct query (default) | B2. With objects in Snowflake |
|---|---|---|
| Creates in Snowflake | Nothing: no tables, procedures or functions | Snapshot tables, `SP_ACCESS_SNAPSHOT`, `SP_ACCESS_FINDINGS`, table functions `TF_ACCESS_OF` / `TF_WHO_CAN` / `TF_CAN` (`sql/1_setup.sql`) |
| How the data is read | The app queries Snowflake directly with your role (`access.live()`) and keeps it in memory for 1 h | The procedure reads it with its owner's rights into `TBL_ACCESS_` tables; the app reads the last snapshot |
| Use it when | You can't (or don't want to) create objects, or you just want to try it | A team wants one shared, scheduled copy, viewers with low rights, and SQL in worksheets without the app |
| `.env` | `ACCESS_SNAPSHOT=` (empty) | `ACCESS_SNAPSHOT=<DB>.<SCHEMA>` |
```mermaid
flowchart LR
  I["1 Install once<br/>clone · venv · pip"] --> F{"Fake data<br/>or Snowflake?"}
  F -- "A fake data" --> FA["streamlit run app.py<br/>no .env, or FAKE=1"]
  F -- "B Snowflake" --> E["Fill in .env<br/>FAKE=0 · account · user · role · warehouse"]
  E --> W{"Create objects<br/>in Snowflake?"}
  W -- "B1 no: direct query" --> R["streamlit run app.py<br/>log in in the browser tab"]
  W -- "B2 yes: run sql/ once" --> S["run_sql.py 1_setup + 2_snapshot<br/>ACCESS_SNAPSHOT=DB.SCHEMA"]
  S --> R
  R --> M{"Your role can read<br/>the whole account?"}
  M -- "yes" --> A["Whole account"]
  M -- "no" --> O["My access<br/>your own roles"]
```
Key: box = step · diamond = a choice, or what you see depends on your role.

### 1. Install once (PowerShell; needs Python 3.10+ and git)
```
git clone https://github.com/darshanmeel/snowflake-access-explorer.git
cd snowflake-access-explorer
python -m venv .venv; .venv\Scripts\activate          # macOS/Linux: python3 -m venv .venv; source .venv/bin/activate
pip install -r requirements.txt
```
If `activate` says running scripts is disabled, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then activate again.
Next time: `cd snowflake-access-explorer; .venv\Scripts\activate`. Update: `git pull; pip install -r requirements.txt`.

### A. With fake data (no Snowflake)
```
streamlit run app.py          # no .env needed; opens http://localhost:8501
```
- Fake data is the default when there is no `.env`. If you already have a `.env`, set `FAKE=1` in it (or `$env:FAKE="1"` in the shell) to switch back to it.
- The fake account has users, functional, technical and group roles, admin holders, sensitive tags, masking policies and at least one finding for each of the 23 rules, so every page shows something.
- **Shared snapshot** in the sidebar shows the whole fake account. **My access** shows one demo user's slice (`ENGINEER_01`, or set `DEMO_USER=<name>`), which is what you'll see later on Snowflake with your own login. `DEMO_USER=HR_01` reads 15 objects of one schema through a database role, so its graph groups them into schema and type boxes you can click.
- Good first clicks: User `ENGINEER_01`, Role `F_ANALYST`, Object `SALES.CORE.TBL_CUSTOMER`, then **Rule checks**.

### B. With your Snowflake
Fill in `.env` (both ways), then run it directly (B1) or create the objects first (B2).

Copy the template once, then fill it in:
```
copy .env.example .env                                # macOS/Linux: cp .env.example .env
```

#### Fill in `.env`
```
FAKE=0
ACCESS_SNAPSHOT=
SNOWFLAKE_ACCOUNT=<org>-<account>
SNOWFLAKE_USER=<your Snowflake login name>
SNOWFLAKE_ROLE=<role>
SNOWFLAKE_WAREHOUSE=<WH>
```
- `<org>-<account>` is the start of your Snowflake URL: `https://<org>-<account>.snowflakecomputing.com`.
- Login is browser SSO by default: a tab opens. To use a key pair instead, add the two lines below (the second only if the key is encrypted):
  ```
  SNOWFLAKE_PRIVATE_KEY_FILE=C:\keys\rsa_key.p8
  SNOWFLAKE_PRIVATE_KEY_PWD=<passphrase>
  ```
- There are no passwords and nothing is stored in the repo; `.env` is git-ignored. Don't put a comment after a value on the same line. No `.env`, or a name missing or empty in it: the environment variable is used instead (e.g. `$env:SNOWFLAKE_USER="..."`). A variable set in the shell wins over `.env`.

#### B1. Run with direct query (nothing created)
```
streamlit run app.py          # ACCESS_SNAPSHOT empty; opens http://localhost:8501; a second tab asks for your Snowflake login
```
Stop it with Ctrl+C. The browser tab opens on the machine running Streamlit, so run the app on your own machine.

Start small: open `http://localhost:8501/?data=mine` and click **Load my access**. It needs only a warehouse and shows your own roles. Then try the whole account (the table below) if your role can read it.

#### What you see depends on your role
| Your role has | Open | You see |
|---|---|---|
| Only a warehouse | `http://localhost:8501/?data=mine`, then **Load my access** | Your own roles and everything they reach (User, Role, Object, Can they?, Rule checks on your own roles) |
| `MANAGE GRANTS` | `http://localhost:8501` | The whole account, read with `SHOW` (slow: one query per role) |
| `IMPORTED PRIVILEGES` on DB `SNOWFLAKE` | `http://localhost:8501` | The whole account, including tags, policies and query history (fast) |

- The app reads everything when it starts and keeps it in memory for 1 h. **Read Snowflake again** in the sidebar reads it again.
- If something can't be read, the app still loads. The sidebar shows **Incomplete** with what is missing and why.
- My access reads with your own rights and saves nothing. It has no sensitivity (tags need the governance views), Rule checks run on your own roles only, and Access review is not available in it (it is about everyone).
- One login per new connection. To reuse a login for about 4 h, an admin runs `ALTER ACCOUNT SET ALLOW_ID_TOKEN = TRUE;` once (on Linux also `pip install "snowflake-connector-python[secure-local-storage]"`).

#### B2. Run with objects in Snowflake (snapshot tables, procedures, functions)
A developer whose role can create tables and procedures runs this once, from the same folder and `.env`:
```
copy settings.sql settings.local.sql      # fill in DB, SCHEMA, WH, DEV_ROLE, APP_ROLE (git-ignored)
python run_sql.py sql/1_setup.sql;     python run_sql.py sql/1_setup_verify.sql      # tables, procedures, functions
python run_sql.py sql/2_snapshot.sql;  python run_sql.py sql/2_snapshot_verify.sql   # CALL SP_ACCESS_SNAPSHOT('AUTO')
```
Then set `ACCESS_SNAPSHOT=<DB>.<SCHEMA>` in `.env` (and `SNOWFLAKE_ROLE=<APP_ROLE>` for viewers) and run `streamlit run app.py`.
- `DEV_ROLE` needs `IMPORTED PRIVILEGES` on DB `SNOWFLAKE` (or `MANAGE GRANTS`) to see the whole account; viewers only need `APP_ROLE`.
- Fresh data: **Rebuild snapshot in Snowflake** in the sidebar, rerun `sql/2_snapshot.sql`, or schedule it with a task ([README.html, Run modes and setup](README.html#run)).
- Without the app, in a worksheet: `SELECT * FROM TABLE(TF_ACCESS_OF('<USER>', NULL));`, `TF_WHO_CAN`, `TF_CAN`, `CALL SP_ACCESS_FINDINGS('{}')`.
- SnowSQL instead of `run_sql.py`: `!source` the same `sql/` files in order. Remove everything: `python run_sql.py sql/3_cleanup.sql`.
- Switch back to direct query any time: empty `ACCESS_SNAPSHOT=`.

### Back to fake data
`FAKE=1` in `.env`, or `$env:FAKE="1"; streamlit run app.py` for one run.

## Also in this repo
- **`sf.py` runs plain SQL from your machine.** It uses the same `.env` and logins. Run `python sf.py "select current_user(), current_role()"` or `python sf.py -f query.sql`, or from Python: `from sf import run; cols, rows = run("select 1")`.
- **Tests:** `python test_access.py` and `python test_sql.py`. They include a check that every page renders.
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
