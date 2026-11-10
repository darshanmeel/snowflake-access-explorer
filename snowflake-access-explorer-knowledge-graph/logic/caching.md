# Caching

Data is read once and kept: `cache.get` (memory 24 h + `.cache/*.pkl` for `CACHE_HOURS`), `.prev.pkl` for What changed, and `access.build` keeps `KEEP_BUILT` built data sets.

```mermaid
flowchart TD
  LS["server.load_shared<br/>server.py:91-100"] --> G["cache.get(KEY, read_shared)<br/>cache.py:93-119"]
  G -->|"MEM < 24 h"| M[memory]
  G -->|".pkl < CACHE_HOURS"| P[".cache/&lt;key&gt;.pkl"]
  G -->|else| R["fn(): fake / live / snapshot<br/>server.py:87-88"]
  R --> KP["keep_prev(): old file -> .prev.pkl<br/>cache.py:72-81"]
  R --> SQ["sql_copy -> access.duckdb<br/>cache.py:188"]
  G --> B["a.build(d, key, builtin)<br/>server.py:190-191"]
  B --> KB["built{} up to KEEP_BUILT=3<br/>access.py:883-909"]
```

## Cache key (`cache.name`, `cache.py:43-48`)
- `SNOWFLAKE_ACCOUNT` (or `local`) + what (source / `mine`) + snapshot location + user + role; another location, user or role never shares a copy.
- Shared key: `KEY = cache.name(SOURCE, where=WHERE)` (`server.py:23`); My access: `cache.name("mine", user or sid, WHERE)` (`server.py:157`).
- `config()` picks mode/source/where: `FAKE=1`, `SOURCE=direct|objects`, `ACCESS_SNAPSHOT` (`cache.py:27-40`).

## Lifetimes
- `HOURS = CACHE_HOURS` (default 24) for the file; `TTL = 24*3600` for memory (`cache.py:21-22`).
- `local()`: file only when `CACHE_HOURS > 0` and not inside Snowflake (`cache.py:51-53`).
- `get()`: memory checked first without the lock, so a page whose data is in memory never waits for another key's read (`cache.py:95-97`); then under one `RLock` memory again (another thread may have read it), file, `fn()`, stores both (`cache.py:24`, `98-119`); fake mode passes `disk=False` (`server.py:98`).
- `ready()`: answers without reading the source (`cache.py:122-129`); used to require a click before a direct read (`server.py:94-95`).
- `drop()`: under `LOCK`, out of memory, file set aside as `.old.pkl` (`cache.py:132-140`); the lock stops a read still running from storing its older data after the drop (`cache.py:135`); called on refresh (`server.py:2149`, `2149`) and fresh My access (`server.py:158-159`).

## Previous snapshot (`.prev.pkl`)
- `keep_prev(f, new)`: the replaced file (or `.old.pkl`) becomes `<key>.prev.pkl` unless it is the same run (`run_of`: RUN_ID, FINISHED_AT) (`cache.py:67-81`).
- `prev(key)`: returns it with its mtime, or None (`cache.py:84-90`); used by What changed (`server.py:1655`).

## Built data sets (`access.py`)
- `memo`: results per data set, cleared by `build()`; `cached(name, fn)` (`access.py:880`, `974-978`).
- `build(d, key, builtin)`: same `(key, builtin)` as loaded -> no work; the loaded one is saved to `built`, at most `KEEP_BUILT` (3) kept (oldest dropped); a key in `built` is restored instead of rebuilt (`access.py:883-909`).
- Shared build key: `("shared", RUN_ID, FINISHED_AT)` (`server.py:184`); My access gets a random key per load (`server.py:168-170`).
- Test: `test_built` (`test_access.py:922`), `test_cache` (`test_access.py:1385`).

## SQL copy (DuckDB)
- `DUCKDB` env (`0` off, `1` also fake) (`cache.py:144`); `sql_copy(key, d, at)` writes TBL_ACCESS_ tables after each read (`cache.py:110-111`, `183`). Details not opened beyond signatures (`cache.py:144-248`): see CLAUDE.md.
