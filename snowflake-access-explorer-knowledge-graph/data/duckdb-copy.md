DuckDB copy: after each read from Snowflake, `cache.sql_copy` writes the snapshot dict to `.cache/access.duckdb` as the `TBL_ACCESS_` tables (plus `_PREV` of the read before), for the user to query with SQL; the app never reads it.

```mermaid
flowchart LR
  G[cache.get: fresh read] -->|sql_wanted| C[cache.sql_copy]
  D{{snapshot dict}} --> C
  C --> J[.cache/sql-PID.ndjson temp]
  J -->|read_json bulk INSERT| S[(schema per cache key<br/>TBL_ACCESS_RUN .. OBJECT_USE)]
  S -->|other run id: RENAME| P[(TBL_ACCESS_*_PREV)]
  C --> K[(main.COPIES)]
```

## Layout

- File: `.cache/access.duckdb` (`cache.py:167-168`); git-ignored `.cache/` (`.gitignore:7`).
- One schema per cache key: `schema(key)` = key with non-word chars -> `_`, lower case (`cache.py:171-173`); key from `cache.name` (`cache.py:43-48`).
- Tables: the 9 `TBL_ACCESS_` data + run tables, columns from `COLUMNS` (`cache.py:146-163`); `TBL_ACCESS_FINDING` is not copied.
- `COPIES` in main: SCHEMA_NAME, CACHE_KEY, RUN_ID, READ_AT, PREV_RUN_ID (`cache.py:215-216`), one row per schema (delete + insert `cache.py:235-237`).

## Type mapping (Snowflake -> DuckDB)

| Snowflake (`sql/1_setup.sql`) | DuckDB (`cache.py:146-163`) |
|---|---|
| VARCHAR(n) | VARCHAR |
| TIMESTAMP_LTZ | TIMESTAMPTZ |
| VARIANT (RUN.SOURCES / ROW_COUNTS / NOTES) | JSON |
| NUMBER (QUERIES) | BIGINT |
| BOOLEAN, DATE | BOOLEAN, DATE |

- Values loaded as VARCHAR then `TRY_CAST` to the column type (`cache.py:232-234`): bad values become NULL.

## Write steps (`cache.py:188-245`)

1. Skip with a note when duckdb is not installed (`cache.py:193-197`).
2. Run id: snapshot RUN_ID; for `""`, `direct`, `live`, `fake` -> `<rid or read>-YYYYmmddHHMMSS` per read (`cache.py:198-201`).
3. `TBL_ACCESS_RUN` row is synthesized: STARTED_AT NULL, STATUS OK, ROW_COUNTS from the dict lists (`cache.py:203-207`).
4. One transaction (`cache.py:214,233`); if `COPIES` has another run id for this schema -> drop old `_PREV`, rename current to `_PREV` (`cache.py:218-224`).
5. Recreate each table and bulk load from a JSON lines temp file, RUN_ID set to the run id (`cache.py:225-234`).
6. Record in `COPIES`; PREV_RUN_ID = the replaced run (`cache.py:235-237`). Failure -> note in `SQL[key]` (`cache.py:242-243`); temp file removed (`cache.py:244-245`).

## When it is written

- `sql_wanted`: never inside Snowflake or with `DUCKDB=0`; fake data only with `DUCKDB=1`; Snowflake reads when a local copy may be kept (`CACHE_HOURS > 0`) (`cache.py:176-181`).
- Called from `cache.get` only on a fresh read, before the `.pkl` write (`cache.py:108-111`).
- UI info: `sql_info` (`cache.py:248-256`), sent by `server.py:2082,2108`.
- Example queries (EXCEPT against `_PREV`): `README.md:190-205`.

## Unclear

- `COPIES` grows one row per cache key and is never pruned (inferred from `cache.py:235-237`; no delete of other schemas found).
