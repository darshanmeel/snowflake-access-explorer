User profile per run: type, disabled flag, defaults and last login.

```mermaid
flowchart LR
  A[ACCOUNT_USAGE.USERS] -->|AUTO| T[(TBL_ACCESS_USER)]
  B[SHOW USERS] -->|fallback| T
  T --> P[access.build: profile]
  P --> R[login_days / is_service / disabled checks]
```

DDL: `sql/1_setup.sql:44-54`. Grain: run x user.

| Column | Type | Meaning | Line |
|---|---|---|---|
| RUN_ID | VARCHAR(36) | run | 45 |
| USER_NAME | VARCHAR(255) | user (personal identifier) | 46 |
| TYPE | VARCHAR(50) | PERSON, SERVICE, LEGACY_SERVICE; empty = PERSON | 47 |
| DISABLED | BOOLEAN | disabled | 48 |
| DEFAULT_ROLE | VARCHAR(255) | default role | 49 |
| DEFAULT_SECONDARY_ROLES | VARCHAR(255) | e.g. `["ALL"]` | 50 |
| DEFAULT_WAREHOUSE | VARCHAR(255) | | 51 |
| DEFAULT_NAMESPACE | VARCHAR(500) | | 52 |
| LAST_SUCCESS_LOGIN | TIMESTAMP_LTZ | last login (personal activity data) | 53 |

- Written: `sql/1_setup.sql:302-305` (`OBJECT_CONSTRUCT(*)`: the secondary-roles column name varies, `:301`) or `:307-311` (SHOW).
- Read: `access.py:944` (`profile`); `login_days` `access.py:2018-2020`; service / disabled `access.py:2025-2029`; default role `access.py:1419,3254`.
- My access: from `DESC USER`; LAST_SUCCESS_LOGIN None + `LOGIN_UNKNOWN=True` (`access.py:524-529`).
- Which rules use which column (dormant, disabled, default role): inferred from CLAUDE.md rule list, not traced per rule here.
