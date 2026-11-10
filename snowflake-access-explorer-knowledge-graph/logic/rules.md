# Rules (23 checks)

The 23 rule checks in `access.findings()` that flag risky grants; each row: what it means, severity, where it lives, one real finding from `a.fake()`.

```mermaid
flowchart LR
  B["build(d)<br/>access.py:896-960"] --> F["findings(only)<br/>access.py:4893-4899"]
  F --> M["rules_model 1-4,13,14<br/>4567-4617"]
  F --> A["rules_admin 5,9,12<br/>4620-4642"]
  F --> S["rules_sensitive 6,7,10,11,15<br/>4645-4700"]
  F --> U["rules_users 8,16<br/>4703-4715"]
  F --> R17["rule17<br/>4718-4734"]
  F --> R18["rule18<br/>4766-4779"]
  F --> R19["rule19<br/>4782-4796"]
  F --> O["rules_operate 20,21<br/>4804-4815"]
  F --> R22["rule22<br/>4818-4835"]
  F --> R23["rule23<br/>4838-4862"]
  F --> C["checks()<br/>4475-4477"]
  F --> RR["rule_rows() page rows<br/>4451-4472"]
```

## How a finding is made
- Titles and "why" text: `RULES` dict, `access.py:78-107`. Severity: `SEVERITY`, `access.py:108-111` ("edit freely").
- `find(num, grantee, detail, path, edges, edge, user, **kw)` builds one finding dict; `edges` = grant edges the fix removes, `edge` = graph edge it is drawn on (`access.py:4508-4517`).
- `findings(only)` concatenates all rule groups, sorted by rule number (`access.py:4893-4899`).
- `checks()` = `(num, title, grantee, detail, path)` tuples (`access.py:4503-4505`); the CLAUDE.md verify command uses it.
- `rule_rows()` adds severity, IaC/SQL fix text (`fix_text`, `access.py:3141-3148`), users who lose access (`lose`, `access.py:3167-3184`) and `same_fix` (`access.py:4479-4500`).
- `SCOPED` rules (3,5,7,10,11,14,17,23) can be rechecked for a subset of names (What if); `GROW` (14,17,23) can be started by a removed grant (`access.py:4586-4592`).
- Hidden built-ins never produce rule 9 / 13 findings (`access.py:4627`, `access.py:4659-4662`).

## Rule table
Examples: output of `.venv\Scripts\python -c "import access as a; a.build(a.fake()); a.checks()"`, first finding per rule (count = findings for that rule on fake data). Fake names only.

| # | Name (`RULES`) | Plain words | Sev. | Code | Input -> output example (fake data) |
|---|---|---|---|---|---|
| 1 | Technical role granted to a user or group role | A `T_` role sits directly on a user, or a group role holds a `T_` role | Medium | `access.py:4598-4603` | user ANALYST_02 holds T_SALES_MART_READ -> `ANALYST_02 > T_SALES_MART_READ` (2) |
| 2 | Direct privilege on a functional role | An `F_` role holds a privilege itself instead of via a `T_` role | Medium | `access.py:4604-4607` | F_SECURITY -> `MANAGE GRANTS on ACCOUNT` (2) |
| 3 | READ held directly and through another role | A consumer holds a `..._READ` role directly and also through another held role | Low | `access.py:4608-4618` | ANALYST_02 -> T_SALES_MART_READ, path `ANALYST_02 > GRP_ANALYSTS > F_ANALYST > T_SALES_MART_READ` (3) |
| 4 | OWNER role held by a consumer | A `..._OWNER` technical role held by a user or a non-build, non-technical role | High | `access.py:4619-4625` | F_ENGINEER holds T_SALES_MART_OWNER (1) |
| 5 | Admin role held by a person | A non-service user reaches an admin role (not via another admin role); paths from `admin_paths()`, capped per admin role (`MAX_PATHS` each, shortest first, `access.py:1902-1908`), so 200 paths to SYSADMIN never hide ACCOUNTADMIN | High | `access.py:4652-4657` | ADMIN_01 -> SYSADMIN via `ADMIN_01 > F_SECURITY > SYSADMIN` (3) |
| 6 | Sensitive column without a masking policy | A tagged-sensitive column has no masking policy | Medium | `access.py:4676-4685` | SALES.CORE.TBL_CUSTOMER -> `column BIRTH_DATE: PRIVACY_CATEGORY=QUASI_IDENTIFIER` (3) |
| 7 | Dormant or disabled person can read sensitive data | Inactive non-service user still reads a sensitive object | High | `access.py:4686-4695` | ANALYST_02 -> `last login 109 days ago; reads 3 sensitive: ...` (4) |
| 8 | Disabled user still holds roles | Disabled user with role grants | Low | `access.py:4734-4737` | FIN_14 -> `holds GRP_EMEA_ALL` (1) |
| 9 | Privilege granted to PUBLIC | PUBLIC holds a privilege or role (default account privileges and built-ins excluded) | High | `access.py:4658-4663` | PUBLIC -> `USAGE on WAREHOUSE WH_SALES_XS` (1) |
| 10 | Person can write to a sensitive object | Non-service user reaches write/own on a sensitive object | Medium | `access.py:4696-4709` | ANALYST_01 -> `INSERT on SHARED.LOGGING.TBL_LOGGING` via `GRP_ANALYSTS > T_SHARED_LOGGING_READ` (17) |
| 11 | Sensitive object reachable through a group role | A group role reaches sensitive objects | Low | `access.py:4710-4718` | GRP_ANALYSTS -> `reads 3 sensitive: ...; 2 users` (2) |
| 12 | Admin role is a user's default role | `DEFAULT_ROLE` in `ADMIN` | High | `access.py:4664-4669` | OPS_01 -> `default role SYSADMIN` (1) |
| 13 | Orphan role: no users and no parent roles | Functional/group role nobody holds (technical roles exempt by design) | Low | `access.py:4626-4632` | F_LEGACY_REPORTING -> `holds 1 role: T_SALES_MART_READ; 0 privileges of its own` (1) |
| 14 | Chain deeper than `MAX_DEPTH_RULE` (5) roles | Shortest chain from a user-held role to its deepest grant is > 5 | Low | `access.py:4633-4644`, `access.py:66` | GRP_EMEA_ALL -> `10 roles deep to SELECT on FINANCE.REPORT.TBL_REVENUE; held by 14 users` (1) |
| 15 | Future grant in a schema that holds sensitive data | Read future grant on tables/views in a schema with sensitive objects (not build/admin) | Medium | `access.py:4719-4727` | T_SALES_CORE_READ -> `SELECT on future tables in SALES.CORE` (1) |
| 16 | Dormant user (no login for `DORMANT_DAYS`=90) still holds roles | Not disabled (that is rule 8), not service | Medium | `access.py:4738-4742`, `access.py:65` | ANALYST_02 -> `last login 109 days ago; holds GRP_ANALYSTS, T_SALES_MART_READ` (3) |
| 17 | Read-only role can write | Name (`READ_ROLE_PATTERNS`) or behaviour (>= 80% read-only over >= 5 objects) says read-only, but it writes/owns | High | `access.py:4746-4762`, `readonly_writes` `access.py:4552-4583`, `access.py:67-71` | F_FINANCE_REPORTING -> `DELETE, INSERT, TRUNCATE, UPDATE on FINANCE.REPORT.TBL_REVENUE via T_FINANCE_REPORT_WRITE (inherited); heuristic: name` (4) |
| 18 | Unusual privilege set | Role suffix `_READ/_WRITE/_EXECUTE/_OWNER` -> `CAP_PRIVS`; extra or missing privileges | Low | `access.py:4794-4807`, `unusual` `access.py:4765-4791`, `CAP_PRIVS` `access.py:73-77` | T_SALES_PIPELINE_EXECUTE -> `EXECUTE role holds OPERATE on task ...TSK_LOAD_CUSTOMER; standard EXECUTE: USAGE; extra OPERATE` (3) |
| 19 | EXECUTE TASK held by a person or consumer role | Account `EXECUTE TASK` reaches a non-service user or F/group role (not build) | Medium | `access.py:4810-4824` | ENGINEER_01 -> `EXECUTE TASK on ACCOUNT via F_ENGINEER > T_SALES_PIPELINE_EXECUTE` (2) |
| 20 | OPERATE on a task outside owner/build roles | Task OPERATE held by a role that is not build/admin/owner side | High | `access.py:4832-4843`, `owner_side` `access.py:4827-4829` | T_SALES_PIPELINE_EXECUTE -> `OPERATE on task ...; runs as its owner T_SALES_PIPELINE_OWNER; 1 user reaches it` (1) |
| 21 | Warehouse MODIFY or OPERATE outside owner/build roles | Same for warehouses | Medium | `access.py:4832-4843` | T_SALES_CORE_EXECUTE -> `OPERATE on warehouse WH_SALES_XS; owner T_WAREHOUSE_OWNER` (1) |
| 22 | Stream on sensitive table readable without the table | Consumer reads a stream whose source is sensitive but cannot read the source | High | `access.py:4846-4863` | F_SUPPORT -> `reads stream SALES.PIPELINE.STR_CUSTOMER on sensitive SALES.CORE.TBL_CUSTOMER, but cannot read ...` (1) |
| 23 | CREATE privilege on a schema held by a read-only role | Read-only role (rule 17 heuristics) reaches `CREATE ...` on a schema | High | `access.py:4866-4890` | F_FINANCE_REPORTING -> `CREATE VIEW on schema FINANCE.REPORT via T_FINANCE_REPORT_READ (inherited); heuristic: name` (4) |

## Notes per rule
- 3: no name parsing; only consumer -> technical `_READ` reached through another held role; technical-to-technical links not checked (`access.py:4608-4611`).
- 4: build roles (`BUILD_ROLES`, default `F_DEPLOY`, fnmatch) may hold OWNER roles (`access.py:56-57`, `is_build` `access.py:4520-4521`).
- 5: reach first via `ups()` (no paths) to skip non-admin users (`access.py:4651`).
- 6/7/10/11/15/22: "sensitive" = tags matching `SENSITIVE_TAGS` (`access.py:61-63`), filled in `build()` (`access.py:956-960`); `SENS_RULES` = {6,7,10,11,15,22} (`access.py:4363`).
- 12, 13, 14, 6, 18: custom `fix=` text (ALTER USER / DROP ROLE / masking policy / "shorten the chain") instead of REVOKE (`access.py:4632`, `4616`, `4639-4641`, `4656-4657`, `4774-4775`).
- 17: an inherited write on a name-only match that is not mostly read gets a review hint, no SQL (`access.py:4756-4759`).
- 18: standard list sorted with name as tie-breaker so findings are stable across processes (`access.py:4798`).
- Fake data keeps >= 1 finding per rule (CLAUDE.md "Keep FAKE=1 ... at least one finding per rule"; verified: all 23 present above).
- Tests: `test_rules` (`test_access.py:262`).
