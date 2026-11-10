Optional: run the local web app (`server.py`) as a Snowpark Container Services service so a team can use it without installing; documented in prose only, no deploy script in the repo.

```mermaid
flowchart LR
  IMG[container image: Python + requirements-web.txt] --> SVC[SPCS service running server.py]
  ENV[HOST=0.0.0.0, SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER] --> SVC
  SEC[key pair mounted as secret: SNOWFLAKE_PRIVATE_KEY_FILE] --> SVC
  SVC --> SF[(Snowflake, service user's role)]
  SVC -.My access off: key pair.-> X[no per-viewer view]
```

## What the source says
- Optional, only to give everyone the local web app; any image with Python and `requirements-web.txt`, `HOST=0.0.0.0` — README.md:321-323, CLAUDE.md:42.
- Login like a shared server: `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, key pair `SNOWFLAKE_PRIVATE_KEY_FILE` mounted as a secret; SSO can't work; My access off — README.md:324-325, server.py:139-140.
- Inside detection is by active Snowpark session or `INSIDE=1`, not by a missing `SNOWFLAKE_ACCOUNT` — access.py:27-38 (fix of docs/review-2026-11-09.md:320-327).
- Host allow-list: with `HOST=0.0.0.0` the server also answers machine names/IPs; add others to `ALLOWED_HOSTS` — README.md:260-261, server.py:2214-2218.

## Not defined
- No Dockerfile, service spec, compute pool or SQL for SPCS in the repo (tracked files checked); steps are unclear beyond README.md:321-325.
- SiS container runtime (not SPCS): `sql/4_streamlit.sql` creates only a warehouse-runtime app (no RUNTIME_NAME / COMPUTE_POOL) — sql/4_streamlit.sql:61-67; review finding on this — docs/review-2026-11-09.md:320-327. web/ST.md now says to use the local version if the component is blocked — web/ST.md:50.
