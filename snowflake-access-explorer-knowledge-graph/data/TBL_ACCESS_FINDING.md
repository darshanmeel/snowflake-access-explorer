Rule findings of the last run only, written by `SP_ACCESS_FINDINGS` (access.py's rule checks run inside Snowflake) for worksheet use.

```mermaid
flowchart LR
  T[(TBL_ACCESS_* last OK run)] --> S[access.snapshot] --> B[access.build] --> R[access.rule_rows]
  R -->|DELETE all + append| F[(TBL_ACCESS_FINDING)]
```

DDL: `sql/1_setup.sql:109-119`. Grain: one row per finding of the last run (`DELETE FROM` the whole table before the append, `sql/1_setup.sql:752`).

| Column | Type | Meaning | Line |
|---|---|---|---|
| RUN_ID | VARCHAR(36) | snapshot run checked | 110 |
| RULE_NUM | VARCHAR(10) | rule 1..23 | 111 |
| TITLE | VARCHAR(500) | | 112 |
| SEVERITY | VARCHAR(20) | High, Medium, Low | 113 |
| GRANTEE | VARCHAR(2000) | user, role or object (may be a user name) | 114 |
| KIND | VARCHAR(20) | user, admin, functional, technical, group, object | 115 |
| DETAIL | VARCHAR | | 116 |
| PATH | VARCHAR | `A > B > C` | 117 |
| CREATED_AT | TIMESTAMP_LTZ | default CURRENT_TIMESTAMP() | 118 |

- Procedure: `sql/1_setup.sql:703-765`; code from stage `STG_ACCESS_CODE` (`:696-701,709`).
- Flow: settings -> `access.snapshot` -> `build` -> `rule_rows` (`sql/1_setup.sql:733-745`); write in a transaction (`:750-760`).
- Not cleaned by SP_ACCESS_SNAPSHOT (`DATA` excludes it, `sql/1_setup.sql:147`); `SP_ACCESS_FINDINGS` empties it itself on every call, so only the last run's findings stay (`sql/1_setup.sql:752`; README.md:231).
- Readers: SELECT granted to APP_ROLE `sql/1_setup.sql:805`; no reader in `access.py` / `server.py` (grep); not in the DuckDB copy (`cache.py:146-163`).
- Test: `test_sql.py:229-231` runs the DDL and procedure body on DuckDB.
