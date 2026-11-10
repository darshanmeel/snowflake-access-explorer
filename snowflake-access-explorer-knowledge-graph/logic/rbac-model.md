# RBAC model

How the app classifies roles (functional, technical, group, database, admin), which links it keeps, and what it hides or shows in red.

```mermaid
flowchart LR
  U((user)) --> G[group role<br/>GRP_*]
  U --> F[functional F_]
  G --> F
  F --> T[technical T_]
  T --> T2["T_.._READ<br/>(WRITE -> READ)"]
  T --> O[(object)]
  F -.-> DR[database role DB.ROLE]
  U -.red.-> A[admin role]
  PUB[PUBLIC] -.-> BI["Snowflake built-in<br/>(one fold box)"]
```

## Prefixes
- `FUNC, TECH` from `ROLE_PREFIXES` (default `F_,T_`) (`access.py:54-55`).
- `role_kind(name)`: admin -> database -> `FUNC` prefix = functional -> `TECH` prefix = technical -> object -> else group (PUBLIC included) (`access.py:994-1006`); `kind_of()` adds user (`access.py:981-986`).
- Tests rerun with `ROLE_PREFIXES=ZF_,ZT_` (CLAUDE.md; not re-verified here).

## Role links
- A GRANT row with `GRANTED_ON` in `ROLE_ON` = (`ROLE`, `DATABASE_ROLE`) and `PRIVILEGE = USAGE` is a role link (`access.py:879`, `920-924`).
- OWNERSHIP on a role is a privilege, not a link; the role stays a role, not an object (`access.py:920`, `928-929`).
- Links granted to admin roles are dropped ("every custom role is also granted to SYSADMIN") (`access.py:921-924`); same in `facts()` (`access.py:4262-4263`).

## Database roles
- Named `DB.ROLE`; added to `db_roles` when granted on (`GRANTED_ON = DATABASE_ROLE`) or when a grantee has a dot (`access.py:930-933`).
- `role_db()` reads the DB from `db_roles` membership, not name parsing of account roles (`access.py:989-991`).
- SQL uses `DATABASE ROLE db.r` (`role_sql`, `access.py:1106-1108`); `can()` sets `use_role=None` for a database role (USE ROLE can't take one) (`access.py:3299`).
- Fake data holds database roles, e.g. `DW.SC_C_CORE` (verified run).

## Default links / technical roles
- Schema roles `<TECH><DB>_<SCHEMA>_OWNER|READ|WRITE|EXECUTE`, DB `<TECH><DB>_OWNER`; default links OWNER -> DB OWNER, READ -> WRITE (CLAUDE.md; fake schemas `access.py:115-123`). The link logic itself is data, not code: unclear where fake() builds the default links (not opened: `access.py:130-347`).
- Rule 18 maps the capability suffix to standard privileges `CAP_PRIVS` (`access.py:73-77`).
- Never parse names for DB/schema: rule 3 uses grant data only (`access.py:4608-4609`).

## Admin roles and account privileges (red)
- `ADMIN = {ACCOUNTADMIN, SECURITYADMIN, SYSADMIN, USERADMIN, ORGADMIN}` (`access.py:43`).
- Admin kind has its own node style key in `ui.KINDS` / `SHAPE` (`ui.py:5-7`), colours from `ui.TOKENS` (`ui.py:16-19`); red per CLAUDE.md (inferred, exact hex not checked).
- Account privileges: `priv_class` returns `admin` for `ACCOUNT` grants (`access.py:1030-1036`); `ui.PCLASS["admin"] = "Account"` (`ui.py:22`).
- `admin_paths()`: per admin role at most `MAX_PATHS` paths, shortest first, via `shortest()` + `listed()` + `capped_paths()` (`access.py:1902-1908`), `account_privs()` (`access.py:1911-1916`), `admin_holders()` (`access.py:1919-1927`), `admin_ways()` (`access.py:1938-1945`).
  Example: `admin_holders()` -> `ADMIN_01 > SECURITYADMIN`, `F_SECURITY > SYSADMIN`, `OPS_01 > SYSADMIN`; `account_privs("F_SECURITY")` -> `MANAGE GRANTS`.

## Built-ins (hidden)
- `BUILTIN` fnmatch patterns `SNOWFLAKE.*,SYSTEM_COMPUTE_POOL_*,SYSTEM$*,SNOWFLAKE_LEARNING_*` (`access.py:47-52`).
- `builtin_grant(g)`: held by a built-in role, or PUBLIC's grant on a built-in (`access.py:891-893`); `build(builtin=False)` moves them to `hidden` (`access.py:916-919`).
- `builtin_info()`: label, grants, roles, objects for the fold box (`access.py:963-971`). Fake: 367 hidden grants, 353 objects (verified).
- Graph: one `BUILTIN_NODE` fold box under PUBLIC (`access.py:2959-2962`, `2968-2972`).
- Default PUBLIC account privileges `DEFAULT_PUBLIC` are not rule 9 (`access.py:44-46`, `4631`).
- `builtin=1` shows them: `session(view, sid, builtin)` -> `a.build(d, key, builtin)` (`server.py:175-191`).
- Test: `test_builtin` (`test_access.py:959`).
