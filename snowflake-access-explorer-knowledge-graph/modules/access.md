# access.py

All data, walks and rules of the app (4,871 lines). Both versions call it; it imports no Streamlit or FastAPI (CLAUDE.md "Code style").

```mermaid
flowchart LR
  subgraph Load
    F[fake 130-345] --> B
    SN[snapshot 401-416] --> B
    LV[live 560-836] --> B
    MI[mine 470-553] --> B
  end
  B[build 896-960<br/>module lookups] --> W[walks<br/>1335-1777]
  W --> P[page functions<br/>2563-3825]
  W --> R[rules 4427-4871]
  B --> WI[what_if 3943-4121]
  B --> DF[diff 4342-4424]
  P --> S[server.py handlers]
  R --> S
```

## Sections by area

| Area | Lines | What is there |
|---|---|---|
| Settings and constants | access.py:1-112 | `.env` load (access.py:19), `in_snowflake` / `INSIDE` (access.py:27-41), `ADMIN` (access.py:43), `BUILTIN` patterns (access.py:50-52), `MAX_HOPS`, `FUNC`/`TECH`/`BUILD`, `TABLES` (access.py:53-59), sensitive tags, dormancy, `MAX_PATHS` (access.py:62-72), `RULES` titles (access.py:78-107), `SEVERITY` (access.py:108) |
| Fake data | access.py:113-398 | `SCHEMAS`, `CHAIN`, `FIN_USERS` (access.py:115-127), `fake()` (access.py:130-345), `fake_use()` (access.py:348-371), `fake_previous()` for What changed (access.py:387-398) |
| Snapshot loader | access.py:401-416 | `snapshot(query, where)`: last OK run of `TBL_ACCESS_RUN`, then each `TBL_ACCESS_<t>` of that run; `OBJECT_USE` optional |
| SHOW helpers | access.py:419-469 | `ident`, `line`, `qualify`, `each` (SHOW_THREADS at once, access.py:437-451), `held_db_roles`, `info_schema` |
| My access | access.py:470-553 | `mine(query, db)`: the logged-in user's own access, read with their rights, writes nothing |
| Live (SOURCE=direct) | access.py:556-865 | `live(query)` (access.py:560-836): same dict as `snapshot()`, ACCOUNT_USAGE else SHOW; `use_sql` ACCESS_HISTORY (access.py:839-853); `only()` demo slice (access.py:856-865) |
| Lookups / build | access.py:868-1008 | `ROLE_ON` (access.py:879), `KEEP_BUILT` (access.py:883), `build()` (access.py:896-960), `cached()` (access.py:974-978), `kind_of`, `role_db`, `role_kind` (access.py:981-1006) |
| Names, classes, ladder | access.py:1009-1334 | `uid` / `UTAG` users vs roles (access.py:1009-1015), `priv_class`, `priv_cat`, `category`, `LEVELS` ladder (access.py:1030-1101), `access_objects`, `ladder*`, `reach_counts` (access.py:1105-1203), `who_has` (access.py:1240-1253), `split_name` (access.py:1315) |
| Full walks | access.py:1335-1450 | `down`, `up`, `bfs`, `ups`, `best_paths`, `starts`, `walk`, `depth`, `chains` |
| Fast walks (counted) | access.py:1451-1616 | `dag`, `loops`, `counts`, `shortest`, `listed`, `fast`, `capped_paths` |
| Counted walks to holders | access.py:1618-1721 | `holding`, `tally`, `via_role`, `via_link`, `paths_to`, `reach_without` |
| Walk up | access.py:1723-1779 | `users_on`, `up_walk` (access.py:1730-1762), `up_only_via` |
| Graph inputs | access.py:1781-2001 | `down_graph`, `object_graph`, `role_graph`; `access_of`, `admin_paths`, `account_privs`, `admin_holders`, `who_users`, `who_can` (access.py:1897-1991) |
| Users | access.py:2002-2072 | `login_days`, `is_service`, `is_disabled`, `is_dormant`, `status`, `split_users`, `used_roles` |
| Sensitive data | access.py:2074-2568 | tags (`tag_rules`..`sensitive_cols`, access.py:2076-2118), policies and masking (`clear_for`..`col_view`, access.py:2127-2310), `data_view` (access.py:2312-2331), `governance_kpis` (access.py:2372-2379), `catalog` (access.py:2441-2454), `sens_flow` (access.py:2466-2507), `review_grid` (access.py:2520-2566) |
| Page aggregations | access.py:2569-2816 | `grants`, `grant_rows`, `reach`, `held`, `loses`, `role_stats`, `grantees`, `valid_privs`, `admin_*`, `matrix`, `object_stats`, `has_lacks`, `privs_on` |
| Big accounts | access.py:2817-3085 | `finding_index`, `group_objects`, `MAX_OBJECTS` 12 (access.py:2889), `graph_input` (access.py:2892-2982), `too_big`, `summary` (access.py:3002-3057), `graph_info` |
| Removal and requests | access.py:3086-3496 | `revoke` / `fix_text` text only (access.py:3117-3148), `with_sql` (access.py:3151-3164), `losers`, `removal`, `ask_for`, `can` (access.py:3267-3300), `cut_points`, `nearest`, `suggest`, `approver` |
| Access graph (screen 4) | access.py:3497-3702 | `access_graph` (access.py:3552-3700) |
| What they see (screen 7) | access.py:3703-3727 | `seen` |
| Compare / review / search | access.py:3728-3848 | `compare` (access.py:3744-3798; `match` / `extras` pass through `with_sql`, access.py:3797-3798), `review` (access.py:3801-3834), `search` (access.py:3837-3846) |
| What if | access.py:3849-4123 | `WHAT_IF_OPS` (access.py:3851), `changes_of`, `without_cuts`, `what_if` (access.py:3943-4121) |
| Granted vs used | access.py:4124-4207 | `use_state`, `used_on`, `granted_used` (access.py:4162-4205) |
| What changed | access.py:4208-4454 | `state` / `restore` / `loaded` (access.py:4210-4237), `facts` (access.py:4242-4268), `diff` (access.py:4370-4452) |
| Rules | access.py:4455-4899 | `rule_rows`, `checks`, `find`, `rules_model` ... `rule23`, `findings` (access.py:4893-4899) |

## Load and build

```mermaid
sequenceDiagram
  participant S as server.read_shared
  participant A as access
  S->>A: fake() | live(query) | snapshot(query, where)
  A-->>S: dict of TABLES + run
  S->>A: build(d, key, builtin)
  A->>A: fill roles, users, objects, lookups (keep KEEP_BUILT older sets)
```

- `snapshot()` reads only `WHERE STATUS = 'OK'` latest run, so a half run is never shown (access.py:403-406).
- `live()` must stay in step with `SP_ACCESS_SNAPSHOT` (docstring access.py:561-563; CLAUDE.md "Direct mode").
- `build()` skips work when `key` matches the last build; keeps older sets in `built` up to `KEEP_BUILT` (access.py:896-905).
- Example: the server calls `a.build(d, key, builtin)` under its lock (server.py:191).

## Rules -> functions

| Rules | Function | Lines |
|---|---|---|
| 1, 2, 3, 4, 13, 14 | `rules_model` | access.py:4595-4645 |
| 5, 9, 12 | `rules_admin` | access.py:4648-4670 |
| 6, 7, 10, 11, 15 | `rules_sensitive` | access.py:4673-4728 |
| 8, 16 | `rules_users` | access.py:4731-4743 |
| 17 | `rule17` (+ `readonly_writes` access.py:4552-4583) | access.py:4746-4762 |
| 18 | `rule18` (+ `unusual` access.py:4765-4791) | access.py:4794-4807 |
| 19 | `rule19` | access.py:4810-4824 |
| 20, 21 | `rules_operate` | access.py:4832-4843 |
| 22 | `rule22` | access.py:4846-4863 |
| 23 | `rule23` | access.py:4866-4890 |

- `findings()` concatenates all and sorts by rule number (access.py:4893-4899); `checks()` gives `(num, title, grantee, detail, path)` rows (access.py:4503-4505).
- `SCOPED` rules check only names passed in `only` (what_if rechecks only what a change touches) (access.py:4586-4587).

## Key functions

| Name | Does | path:line |
|---|---|---|
| `in_snowflake` | Active Snowpark session or `INSIDE=1` | access.py:27-38 |
| `fake` | Demo data set (at least one finding per rule) | access.py:130-345 |
| `fake_previous` | Earlier demo snapshot for What changed | access.py:387-398 |
| `snapshot` | Last OK run of the `TBL_ACCESS_` tables | access.py:401-416 |
| `mine` | Logged-in user's own access, live | access.py:470-553 |
| `live` | Whole account read now (SOURCE=direct) | access.py:560-836 |
| `use_sql` | ACCESS_HISTORY usage SQL (metadata only) | access.py:839-853 |
| `only` | One user's slice (demo My access) | access.py:856-865 |
| `build` | Fill module lookups; memo by key | access.py:896-960 |
| `cached` | `fn()` once per data set | access.py:974-978 |
| `kind_of` / `role_kind` | user / admin / database / functional / technical / group / object | access.py:981-1006 |
| `who_has` | Screen 2 entries per user / role | access.py:1240-1253 |
| `down` / `up` / `bfs` | Full path walks down / up, shortest by BFS | access.py:1345-1382 |
| `dag` / `loops` | Role links minus loop back edges; role loops | access.py:1453-1518 |
| `counts` / `shortest` / `listed` / `fast` | Exact path counts, shortest paths, capped listing | access.py:1525-1603 |
| `up_walk` | Counted walk up to holders | access.py:1730-1762 |
| `access_of` / `who_can` | Reference listings (TF parity) | access.py:1897-1899, access.py:1987-1991 |
| `who_users` | Users of an object, counted | access.py:1961-1979 |
| `admin_holders` | Users / roles holding an admin role | access.py:1919-1927 |
| `status` / `is_dormant` | disabled / never / dormant / active | access.py:2037-2051 |
| `sensitive` / `masked` / `data_view` | Sensitive tags, masking, what a role sees | access.py:2109-2112, access.py:2167-2173, access.py:2312-2331 |
| `catalog` / `sens_flow` / `review_grid` | Screens 8, 16, 6 | access.py:2441-2454, access.py:2466-2507, access.py:2520-2566 |
| `grants` / `reach` / `held` / `grantees` / `matrix` | Page rows (cached per walk) | access.py:2571-2765 |
| `has_lacks` | Privileges held vs missing on one object | access.py:2790-2803 |
| `graph_input` / `summary` | Big-account roll-up and fold | access.py:2892-2982, access.py:3002-3057 |
| `revoke` / `fix_text` | IaC + SQL text for a grant edge (never run) | access.py:3117-3148 |
| `with_sql` | A Compare / Request change dict (op grant / revoke, role or privilege + objectType + object, to, toUser) plus its `sql` (revoke via `revoke()`, grant written here with a `-- undo:` line for a role) and `roleDb` / `toDb` from `role_kind()`: the server is the only SQL writer, the web pages never write SQL or guess a role's kind from a dot (never run) | access.py:3151-3164 |
| `can` | Can they? (count, shortest, choke, options) | access.py:3267-3300 |
| `cut_points` / `removal` / `nearest` / `suggest` / `ask_for` | Where to cut, ways to remove, ways in, request roles | access.py:3201-3494 |
| `access_graph` | Screen 4 graph | access.py:3552-3700 |
| `seen` / `compare` / `review` / `search` | Screens 7, 9, review export, search ranking | access.py:3705-3846 |
| `what_if` | Simulated revokes; restores lookups | access.py:3943-4121 |
| `granted_used` | Screen 13; also `sql`: the trim of unused grants joined from `changes_of(changes)`, as What if writes it (access.py:4205) | access.py:4162-4205 |
| `facts` / `diff` | Screen 14 | access.py:4242-4268, access.py:4370-4452 |
| `rule_rows` / `checks` / `findings` | Rule output for pages and tests | access.py:4479-4505, access.py:4893-4899 |

- Graph fragment: `function:access.py:<name>` nodes, `implements` edges to `business_rule:rule_N` (graph/parts/modules.*.jsonl).
- unclear: `fake()` has no docstring; its content was not inspected line by line here.
