Every grant to a role or database role: role -> object, role -> role (the role hierarchy) and future grants (`IS_FUTURE`).

```mermaid
flowchart LR
  A[ACCOUNT_USAGE.GRANTS_TO_ROLES] -->|AUTO| G[(TBL_ACCESS_GRANT)]
  B[SHOW ROLES + SHOW GRANTS TO ROLE] -->|fallback| G
  C[SHOW DATABASE ROLES + SHOW GRANTS TO DATABASE ROLE] -->|fallback| G
  D[SHOW FUTURE GRANTS IN DATABASE / SCHEMA] -->|always, IS_FUTURE| G
  G --> E[access.build: role_grants / privs]
  G --> TF[TF_ACCESS_OF / TF_WHO_CAN]
```

DDL: `sql/1_setup.sql:24-33`. Grain: run x grantee x privilege x granted_on x object x future (inferred, no constraint).

| Column | Type | Meaning | Line |
|---|---|---|---|
| RUN_ID | VARCHAR(36) | run (logical FK) | 25 |
| GRANTEE_ROLE | VARCHAR(255) | role; database role as `DB.ROLE` | 26 |
| PRIVILEGE | VARCHAR(255) | USAGE, SELECT, OWNERSHIP, ... | 27 |
| GRANTED_ON | VARCHAR(255) | TABLE, VIEW, ROLE, DATABASE_ROLE, SCHEMA, ACCOUNT, ... | 28 |
| OBJECT_NAME | VARCHAR(2000) | `DB.SCHEMA.OBJECT` unquoted; future: `DB.SCHEMA.<TABLE>` | 29 |
| IS_FUTURE | BOOLEAN | future grant | 30 |
| GRANT_OPTION | BOOLEAN | with grant option | 31 |
| GRANTED_BY | VARCHAR(255) | granting role; NULL on future grants (`sql/1_setup.sql:291`) | 32 |

- ACCOUNT_USAGE path: `sql/1_setup.sql:212-220` (`DELETED_ON IS NULL`, `GRANTED_TO IN ('ROLE','DATABASE_ROLE')`; DB role grantee qualified `DB.ROLE` at `:213-214`; OBJECT_NAME built at `:216-218`).
- SHOW path: roles `sql/1_setup.sql:226-231`, database roles `:237-253`, saved `:254`.
- Future grants: `sql/1_setup.sql:261-295` (STANDARD databases only `:269`; INFORMATION_SCHEMA skipped `:275`).
- Role link = USAGE on ROLE / DATABASE_ROLE, admin grantees dropped: `access.py:920-924`, `sql/1_setup.sql:597-601`.
- Other rows -> `privs` / `kinds`: `access.py:926-929`. Database roles collected: `access.py:930-933`.
- Built-in grants hidden unless `builtin=1`: `access.py:891-893,917-919`.
- Same shape from `live()`: `access.py:602-609,622-642,666-670`; from `mine()`: `access.py:483-496` (no GRANT_OPTION / GRANTED_BY keys).
- Per-object fallbacks of tags / policies list tables and views from this table: `sql/1_setup.sql:349-353`.
