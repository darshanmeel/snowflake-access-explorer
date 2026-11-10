Data model: 10 Snowflake `TBL_ACCESS_` tables (9 snapshot + findings), one in-memory snapshot dict, and a local DuckDB copy; all metadata, never business data.

## Flow

```mermaid
flowchart LR
  AU[SNOWFLAKE.ACCOUNT_USAGE views] --> SP[SP_ACCESS_SNAPSHOT]
  SHOW[SHOW / INFORMATION_SCHEMA fallback] --> SP
  SP --> T[(TBL_ACCESS_* tables<br/>last OK run)]
  T --> SNAP[access.snapshot]
  AU --> LIVE[access.live SOURCE=direct]
  SHOW --> LIVE
  SHOW --> MINE[access.mine My access]
  SNAP --> D{{snapshot dict}}
  LIVE --> D
  MINE --> D
  FAKE[access.fake] --> D
  D --> B[access.build lookups]
  D --> PKL[.cache/key.pkl + .prev.pkl]
  D --> DUCK[(.cache/access.duckdb<br/>TBL_ACCESS_* + _PREV)]
  T --> TF[TF_ACCESS_OF / TF_WHO_CAN / TF_CAN]
  SNAP --> FIND[SP_ACCESS_FINDINGS] --> F[(TBL_ACCESS_FINDING)]
```

- SP writes: `sql/1_setup.sql:510-560`; snapshot read: `access.py:401-416`; live: `access.py:560-836`; mine: `access.py:470-553`.
- Cache / DuckDB: `cache.py:93-119`, `cache.py:188-245`. Findings: `sql/1_setup.sql:733-764`.

## ER diagram (logical; no PK/FK declared in DDL)

```mermaid
erDiagram
  TBL_ACCESS_RUN ||--o{ TBL_ACCESS_GRANT : RUN_ID
  TBL_ACCESS_RUN ||--o{ TBL_ACCESS_USER_ROLE : RUN_ID
  TBL_ACCESS_RUN ||--o{ TBL_ACCESS_USER : RUN_ID
  TBL_ACCESS_RUN ||--o{ TBL_ACCESS_USAGE : RUN_ID
  TBL_ACCESS_RUN ||--o{ TBL_ACCESS_TAG : RUN_ID
  TBL_ACCESS_RUN ||--o{ TBL_ACCESS_POLICY : RUN_ID
  TBL_ACCESS_RUN ||--o{ TBL_ACCESS_STREAM : RUN_ID
  TBL_ACCESS_RUN ||--o{ TBL_ACCESS_OBJECT_USE : RUN_ID
  TBL_ACCESS_RUN ||--o{ TBL_ACCESS_FINDING : RUN_ID
  TBL_ACCESS_USER ||--o{ TBL_ACCESS_USER_ROLE : USER_NAME
  TBL_ACCESS_USER ||--o{ TBL_ACCESS_USAGE : USER_NAME
  TBL_ACCESS_USER ||--o{ TBL_ACCESS_OBJECT_USE : USER_NAME
  TBL_ACCESS_USER_ROLE }o--o{ TBL_ACCESS_GRANT : "ROLE_NAME = GRANTEE_ROLE"
  TBL_ACCESS_GRANT }o--o{ TBL_ACCESS_GRANT : "OBJECT_NAME = GRANTEE_ROLE (role link)"
  TBL_ACCESS_TAG }o--o{ TBL_ACCESS_GRANT : OBJECT_NAME
  TBL_ACCESS_POLICY }o--o{ TBL_ACCESS_GRANT : OBJECT_NAME
  TBL_ACCESS_POLICY }o--o{ TBL_ACCESS_TAG : TAG_NAME
  TBL_ACCESS_STREAM }o--o{ TBL_ACCESS_GRANT : "STREAM_NAME = OBJECT_NAME"
  TBL_ACCESS_RUN { varchar RUN_ID PK }
  TBL_ACCESS_GRANT { varchar RUN_ID FK varchar GRANTEE_ROLE varchar PRIVILEGE varchar GRANTED_ON varchar OBJECT_NAME boolean IS_FUTURE }
  TBL_ACCESS_USER_ROLE { varchar RUN_ID FK varchar USER_NAME varchar ROLE_NAME }
  TBL_ACCESS_USER { varchar RUN_ID FK varchar USER_NAME }
```

- Role link: `GRANTED_ON IN ('ROLE','DATABASE_ROLE') AND PRIVILEGE='USAGE'`, grantee not an admin role: `sql/1_setup.sql:597-601`, `access.py:920-924`.
- Tag inheritance: a tag row counts for an object when its `OBJECT_NAME` equals the object (own or column tag), or equals the object's `DB.SCHEMA` (SCHEMA row) or `DB` (DATABASE row) from `split_name(obj)`: exact matches, not a prefix match (`access.py:2090-2106`).
- Tag-based policy (`OBJECT_NAME` empty) joins by `TAG_NAME`: `access.py:2160-2163`.
- Stream → sensitive source (rule 22): `access.py:4846-4858`.
- Full list with evidence: `data/model.json` → `relationships`.

## Versioning

- Every data row carries `RUN_ID`; after an OK run all other runs' rows are deleted, except those of a run still RUNNING and started within the last day (an older one is taken as dead): `sql/1_setup.sql:554-559`.
- FAILED run deletes its own rows: `sql/1_setup.sql:547-549`. A second CALL within 1 h of a RUNNING one is SKIPPED (insert first, then look: the run's RUNNING row goes in, then the earliest RUNNING run of the last hour (ORDER BY STARTED_AT, RUN_ID) goes on and any other deletes its own row and returns SKIPPED, so two CALLs a moment apart can no longer both start): `sql/1_setup.sql:515-523`.
- `TBL_ACCESS_RUN` keeps every run (`sql/1_setup.sql:13`). `TBL_ACCESS_FINDING` keeps only the last run: each `SP_ACCESS_FINDINGS` call deletes every row, then appends, in one transaction (`sql/1_setup.sql:750-752`).
- Readers take the newest OK run: `access.py:403-404` (ORDER BY FINISHED_AT), `sql/1_setup.sql:586` (MAX_BY).

## Views and derived sets

| View | Built from | Rows |
|---|---|---|
| `TF_ACCESS_OF(NAME, MAX_DEPTH)` (`sql/1_setup.sql:577-636`) | RUN, USER_ROLE, USER, GRANT (last OK run) | one per path × privilege a user/role reaches |
| `TF_WHO_CAN(OBJECT_NAME, PRIVILEGE, MAX_DEPTH)` (`sql/1_setup.sql:638-679`) | RUN, USER_ROLE, USER, GRANT | one per role or user × path to the object |
| `TF_CAN(USER_NAME, PRIVILEGE, OBJECT_NAME)` (`sql/1_setup.sql:681-693`) | `TF_ACCESS_OF` | one per path; no rows = no access |
| snapshot dict (`access.py:401-416`) | TBL_ACCESS_* of last OK run, or live / mine / fake | one list of row dicts per table + `run` |
| DuckDB `TBL_ACCESS_*` (`cache.py:220-234`) | snapshot dict of one read | same as the Snowflake table |
| DuckDB `TBL_ACCESS_*_PREV` (`cache.py:222-224`) | DuckDB tables of the read before | same as the Snowflake table |
| `.cache/<key>.prev.pkl` (`cache.py:72-90`) | replaced `.pkl` of another run | whole dict (What changed, `server.py:1655`) |

## Pages

- Tables: [TBL_ACCESS_RUN](TBL_ACCESS_RUN.md) · [GRANT](TBL_ACCESS_GRANT.md) · [USER_ROLE](TBL_ACCESS_USER_ROLE.md) · [USER](TBL_ACCESS_USER.md) · [USAGE](TBL_ACCESS_USAGE.md) · [TAG](TBL_ACCESS_TAG.md) · [POLICY](TBL_ACCESS_POLICY.md) · [STREAM](TBL_ACCESS_STREAM.md) · [OBJECT_USE](TBL_ACCESS_OBJECT_USE.md) · [FINDING](TBL_ACCESS_FINDING.md)
- [snapshot-dict.md](snapshot-dict.md) · [duckdb-copy.md](duckdb-copy.md)

## Unclear

- No PK, UNIQUE or FK constraints in any DDL (`sql/1_setup.sql:13-119`): every key is logical.
- Source column semantics marked "to verify" in setup: tags `sql/1_setup.sql:380-381`, policies `:421-422`, DESCRIBE body `:447`, SHOW STREAMS columns `:466`.
- `TBL_ACCESS_FINDING`: no reader in the app (grep of `access.py`, `server.py`); not in the DuckDB copy (`cache.py:146-163`).
