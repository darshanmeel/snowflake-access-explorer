# JSON API: server.py

Contract between `server.py` (FastAPI, local version) and the React app in `web/`. The same JSON shapes feed the React
components inside Streamlit in Snowflake (`st_react.py`), so a component never knows which version it runs in.
TypeScript types: `web/src/api/types.ts` (keep both in step).

## Principles

- **Read-only.** Every endpoint is `GET`, except `POST /api/reload` and `POST /api/mine/load`. Nothing runs GRANT,
  REVOKE, CREATE, ALTER or DROP. The only write-like call is `CALL <ACCESS_SNAPSHOT>.SP_ACCESS_SNAPSHOT('AUTO')`
  (owner's rights), from `POST /api/reload` with `what=rebuild`. Fix texts (`iac`, `sql`) are text to copy, never run.
- **No logic in server.py.** Every number, path, rule and walk comes from `access.py` (the functions named per endpoint
  below). The server only picks, filters (the same filters app.py applies), renames to the JSON keys here, and adds
  `refs`. Page texts (headings, help) live in the React app.
- **Layout-free graphs.** Graphs are nodes, edges, lanes (depth) and groups. React Flow + ELK place them.
- **One lock.** `access.py` keeps its lookups in module globals. Every request runs
  `with LOCK: a.build(data, key); a.capped.clear(); payload = ...` and returns plain JSON. `build()` skips the work when
  the key is the same as the last build, so a run of clicks on one view costs nothing; switching between shared and mine
  rebuilds once.
- **Names are ids.** A node id is `a.uid(name, user)`: a user whose name is also a role's gets the suffix `" (user)"`.
  Every response that holds names carries `refs` (kind of every id it mentions, sensitive objects, disabled users), so
  chips and mini paths draw without extra calls.
- **Unknown kinds.** `access.py` is gaining database roles. The server maps `a.role_kind()` / `a.node_kind()` values
  to `NodeKind`: `"database"` -> `"database_role"`, `"database_role"` -> `"database_role"`, any other unknown value ->
  `"group"` with the raw value kept in `raw_kind`. Object types (`a.kinds`) pass through as strings; the UI falls back
  to a plain grey box for a type it does not know.
- **Errors:** `{"detail": "<code>", "message": "<plain words>"}` with HTTP 400 (bad param), 404 (name not in the data:
  `not_found`), 409 (`mine_not_loaded`; `mine_unavailable` inside Snowflake, where the app has its owner's rights and `meta.mine_available` is false), 503 (`shared_unreadable`, message = `a.line(error)`).

## Common query params

| Param | Values | Default | Meaning |
|---|---|---|---|
| `view` | `shared` \| `mine` | `shared` | Which data: the shared snapshot, or My access of this browser session |
| `builtin` | `1` | off | Keep Snowflake's built-in grants (see below); switching it rebuilds the lookups and rule checks |

**Snowflake built-in grants.** Grants Snowflake makes to every account through PUBLIC (fnmatch patterns `BUILTIN`,
default `SNOWFLAKE.*,SYSTEM_COMPUTE_POOL_*,SYSTEM$*,SNOWFLAKE_LEARNING_*`: the SNOWFLAKE.* database roles and their
functions / views, application role SNOWFLAKE.PUBLIC, system compute pools and warehouses, the learning role,
warehouse and database). `a.build(d, key, builtin=False)` leaves them out of every walk, count, table and rule
(kept in `a.hidden`); never rule 9 or 13 either way. Graphs (`a.graph_input`, the PUBLIC role graph) then show one
box `a.BUILTIN_NODE` = "Snowflake built-in (via PUBLIC)" under PUBLIC: kind `fold`, edge `PUBLIC -> box` class `use`
with the object count, note `("hidden", tooltip)`, info `{count: grants, noun: "built-in grants"}`. `builtin=1`
draws the real grants instead. `meta.builtin` tells what is hidden.

Every page endpoint accepts `view`. `review` is shared only (`400 shared_only` in mine). URL state of the React app
mirrors app.py (`?page=user&name=...&depth=3&data=mine`), so links stay shareable; `data=mine` becomes `view=mine`.

## Data loading and caching

### Modes (meta.mode / meta.source)

Same switches as app.py (`cache.config()`):

| `FAKE` | `SOURCE` | source | Shared data | My access |
|---|---|---|---|---|
| `1` | any | `fake` | `a.fake()` | `a.only(a.fake(), DEMO_USER)` |
| not `1` | `objects` (or `ACCESS_SNAPSHOT` set) | `objects` | `a.snapshot(query, WHERE)`, WHERE = `ACCESS_SNAPSHOT` or `SNOWFLAKE_DATABASE.SNOWFLAKE_SCHEMA` | `a.mine(query, WHERE.split(".")[0])` |
| not `1` | `direct` (default) | `direct` | `a.live(query)` | `a.mine(query, None)` |

The data is read once a day (`cache.get`: memory 24 h, and `.cache/` for `CACHE_HOURS`); `meta.fetched_at` is when.

`query(sql)` runs on a fresh connection from `sf.connect()` per load, closed afterwards (as `app.with_query`).

### Shared data: one copy, 1 hour

- In memory: `{"data": dict, "at": epoch}`. Loaded on the first request that needs it; reused while younger than
  3600 s (same as `@st.cache_data(ttl=3600)` on `app.shared`). Expired: the next request loads again.
- Build key: `("shared", run["RUN_ID"], str(run["FINISHED_AT"]))`, as app.py.
- A load error is kept for the request only (not cached): `503 shared_unreadable`, and the UI points to My access.

### My access: per browser session, 1 hour, memory only

- Cookie `ae_sid`: 32 random hex chars (`os.urandom(16).hex()`), set by `POST /api/mine/load`. `HttpOnly`,
  `SameSite=Strict`, `Path=/api`, `Max-Age=3600`. Not `Secure` locally (http://localhost).
- Server dict `MINE = {sid: {"data": dict, "key": ("mine", <random hex>), "user": str, "at": epoch}}`. `key` is the
  `stamp()` of app.py: random, so two sessions never share `a.build` lookups or rule findings.
- Every `view=mine` request: look up the cookie; missing, unknown or older than 3600 s -> `409 mine_not_loaded`
  (expired entries are dropped on the way). Found -> `a.build(data, key)` and answer from memory: no Snowflake call per
  click. Same as `app.mine_for(browser)` (ttl 3600) keyed by the XSRF cookie.
- `POST /api/mine/load` again replaces the entry (Reload my access). Nothing is written to disk, logs or the shared
  cache; no other browser sees it.

### Per-data-set memo

Rule rows, sensitive set and edge breaks use `a.cached(...)` exactly as app.main does
(`a.cached("sens", a.sensitive)`, `a.cached("rows", a.rule_rows)`, `a.cached("ro", a.readonly_writes)`), so they are
computed once per build key.

## Shared shapes

```jsonc
// refs: kinds and marks of every id in the response
"refs": {
  "kinds": {"ENGINEER_01": "user", "F_ENGINEER": "functional", "HR.SC_W_PEOPLE": "database_role",
            "SALES.CORE.TBL_CUSTOMER": "object"},
  "types": {"SALES.CORE.TBL_CUSTOMER": "TABLE"},            // a.kinds for objects
  "labels": {"SALES.FUTURE_TABLE": "All future tables in SALES.CORE"},  // a.future_label, only when set
  "sensitive": ["SALES.CORE.TBL_CUSTOMER"],                // in a.sensitive()
  "disabled": ["OLD_USER_01"]                               // a.is_disabled
}
// a path: node ids from start to end (user/role ... holder, then the object when there is one)
"path": ["ENGINEER_01", "F_ENGINEER", "T_SALES_CORE_READ", "SALES.CORE.TBL_CUSTOMER"]
// a rule hit on a node or edge
{"num": "17", "severity": "High", "title": "Read-only role can write"}
// a banner
{"tone": "info" | "warn" | "bad", "title": "Dormant user: no login for 120 days", "lines": ["..."],
 "links": [{"label": "Rule 16", "page": "rules", "params": {"rule": "16"}}]}
```

### Graph

```jsonc
{
  "title": "Role hierarchy, by depth",
  "header": "12 objects",               // graph_input()["header"] or a short count
  "level": "object" | "schema" | "database" | "type" | "summary",
  "note": "Summary: 14 roles between granted roles and grant holders are folded.",   // optional
  "full": false,                         // true: drawn in full although big; false + level "summary": ?full=1 draws all
  "selected": "F_ENGINEER",              // node to highlight (role page: the role), optional
  "lanes": [{"index": 0, "label": "User", "depth": null},
            {"index": 1, "label": "Depth 1", "depth": 1},
            {"index": 4, "label": "Objects", "depth": null}],
  "nodes": [{
    "id": "T_SALES_CORE_READ", "name": "T_SALES_CORE_READ",
    "label": "T_SALES_CORE_READ", "sub": null,          // object: own name + "▦ table · SALES.CORE" (app.node_label)
    "kind": "technical",                 // NodeKind, group kinds included
    "raw_kind": null,                    // access.py value when it was unknown
    "type": null,                        // object type for objects ("TABLE"), group: object type of a type-group
    "db": "SALES", "schema": "CORE",     // objects and groups (a.split_name), else null
    "lane": 2, "depth": 2,
    "badge": "D2 · also D3",             // a.notes() badge, "" when none
    "tip": "D2: ENGINEER_01 > F_ENGINEER > T_SALES_CORE_READ\nD3: ...",
    "marks": ["sensitive"],              // disabled | sensitive | bad
    "rules": [{"num": "3", "severity": "Low", "title": "READ held directly and through another role"}],
    "action": {"kind": "page", "page": "role", "params": {"name": "T_SALES_CORE_READ"}},
    "group": null,                       // GroupInfo for a combined box, see below
    "classes": ["read"]                  // roles: classes of their own grants (counts on a folded box); null otherwise
  }],
  "edges": [{
    "id": "F_ENGINEER>T_SALES_CORE_READ>inherit",
    "source": "F_ENGINEER", "target": "T_SALES_CORE_READ",
    "cls": "inherit",                    // inherit | inherit_db | read | write | own | use | manage | admin
    "privs": [],                         // privileges merged on this line (one line per class)
    "count": null,                       // objects behind an edge into a group
    "back": false,                       // source lane >= target lane: drawn as "also deeper" (dotted)
    "rules": [], "has": null, "lacks": null    // a.graph_info(): rule hits; Has / Lacks on arrows into one object
  }],
  "groups": {                            // expansion payload of every combined box, keyed by its node id
    "SALES.PIPELINE": {
      "kind": "schema_group", "label": "SALES.PIPELINE", "noun": "objects", "count": 8,
      "sensitive": 1, "findings": 3, "classes": ["read", "manage"],
      "nodes": [ /* GraphNode of each member, lane = the group's lane */ ],
      "edges": [ /* holder -> member edges that replace the edges into the group */ ],
      "truncated": 0,                    // members left out (over 1000): use the drill action
      "drill": {"kind": "drill", "schema": "SALES.PIPELINE"}   // or {"kind": "otype", "otype": "TABLE"}
    }
  },
  "legend": {"kinds": ["user", "functional", "technical", "database_role", "object", "schema_group"],
             "edges": ["inherit", "inherit_db", "read", "manage"], "marks": ["sensitive"], "rules": true}
}
```

- **NodeKind**: `user`, `functional`, `technical`, `group`, `database_role`, `admin`, `object`, and the combined boxes
  `schema_group`, `database_group`, `type_group` (graph_input's `kinds`: schema | database | type-group),
  `fold` (`a.summary()` "⋯ N roles ⋯" box), `lane_group` (many roles of one lane in one box, folded by the component).
- **Styles** (from `ui.TOKENS`, `meta.tokens`): user pill, functional blue, technical coffee, group dashed amber,
  database role tab-corner grey-blue box with its database under the name, object grey, admin red; account privileges
  red (edge `admin`). Edge `inherit_db`: a role link whose target is a database role (grey-blue, dotted double line).
- **Edges** come from graph_input / down_graph / role_graph / object_graph tuples: `(a, b)` -> `inherit` (or
  `inherit_db`); `(a, b, cls, privilege)` -> one edge per `(a, b, cls)` with `privs` merged; `(a, b, cls, privilege, n)`
  (into a group) -> `count` = max n.
- **Actions** (what a click does; the Streamlit wrapper turns the same action into a URL):
  `{"kind": "page", "page": "user"|"role"|"object"|"check", "params": {...}}`, `{"kind": "expand", "group": id}`
  (combined box: swap it for `groups[id].nodes` / `.edges`, click again to fold), `{"kind": "drill", "schema": "DB.SCH"}`,
  `{"kind": "otype", "otype": "TABLE"}`, `{"kind": "full"}` (fold box: reload with `full=1`).
  Rules as in `app.node_href`: schema/database/type-group boxes -> `expand` (with `drill` / `otype` in the group);
  fold -> `full`; on the user page an object -> Can they? for this user; else the node's own page.
- **Tab graphs** (Privileges tabs): at most 12 object boxes (`a.MAX_OBJECTS`), else objects combine into one
  `database_group` per database (`group.nodes` = its objects). Over `MAX_OBJECTS` rows only the shortest path of each
  row is drawn (as `app.tab_graph`).
- **Folding in the component** (`graphs.ts` `foldRoles`, every graph): 6+ database roles of one database in one lane
  become one box ("DW · 9 database roles", badge "3 read · 3 write · 3 manage" by the strongest class of each role's
  own grants), as do 6+ group roles; a lane still over 24 boxes folds the rest into one `lane_group`. Folded lines carry
  counts. Opening a box with over 24 members draws buckets instead (`buckets`): objects by schema, then type; roles by
  kind and database; then name ranges.

## Endpoints

### GET /api/meta?view=

Mode, run, warnings and constants for the frame (sidebar, nav, legends). Producer: `a.run`, `a.cached("rows",
a.rule_rows)`, `a.cached("sens", a.sensitive)`, `a.governance_kpis()`, constants of `access.py` and `ui.py`.
Answers even when the data is not loaded (`loaded: false`, no run).

```json
{
  "mode": "fake", "source": "fake", "where": "", "view": "shared", "loaded": true,
  "run": {"run_id": "fake", "finished_at": "2026-11-02 07:00", "when": "2026-11-02 07:00 UTC · 13 h ago", "old": false},
  "sources": {"all": "fake data"},
  "notes": [{"key": "usage", "title": "query history: last 7 days only", "meaning": "...", "raw": "..."}],
  "mine": {"loaded": false, "user": null, "loaded_at": null, "expires_at": null},
  "pages": [{"key": "user", "label": "User", "badge": null}, {"key": "rules", "label": "Rule checks", "badge": 41},
            {"key": "sensitive", "label": "Sensitive data", "badge": 6}, {"key": "review", "label": "Access review", "badge": null}],
  "default_user": "ENGINEER_01",
  "prefixes": {"func": "F_", "tech": "T_"}, "admin_roles": ["ACCOUNTADMIN", "..."], "build_roles": ["F_DEPLOY"],
  "limits": {"max_paths": 200, "max_objects": 12, "max_hops": 50, "dormant_days": 90, "max_depth_rule": 5},
  "read_privs": ["OWNERSHIP", "SELECT"], "sensitive_tags": "PRIVACY_CATEGORY=...",
  "rules": [{"num": "1", "title": "...", "why": "...", "severity": "Medium", "area": "Role model", "spot": "shortcut",
             "meaning": "...", "fix": "..."}],
  "governance": {"Row access policies used": "2 tables", "Masking": "5 columns", "Tags": "not used"},
  "tokens": {"light": {"...": "ui.TOKENS"}, "dark": {}}, "help": {"Depth": "ui.HELP"},
  "type_icon": {"TABLE": ["▦", "table"]}, "pclass": {"read": "Read"},
  "builtin": {"label": "Snowflake built-in (via PUBLIC)", "grants": 367, "objects": 353,
              "roles": ["SNOWFLAKE.CORTEX_USER", "SNOWFLAKE.PUBLIC", "SNOWFLAKE_LEARNING_ROLE", "..."]},
  "what_if_ops": ["revoke_role_from_user", "revoke_role_from_role", "revoke_priv", "drop_role", "empty_public"]
}
```

`builtin`: `a.builtin_info()`, the built-in grants left out (null with `builtin=1` or when there are none).

`notes` titles and meanings: `app.note_info(key, source, view)`; `old`: snapshot older than 24 h (`app.snap_time`).
`governance` is shared only (null in mine). `pages` leaves out `review` in mine; badges: rules = findings count,
sensitive = sensitive objects.

### POST /api/reload

Body `{"what": "load" | "page" | "rebuild"}`. `load`: read the shared data now (with `SOURCE=direct` on Snowflake every
shared request answers 409 `shared_not_loaded`, also in `meta.error`, until this click or a copy in memory or `.cache/`).
`page`: drop the shared cache, memory and `.cache/` file (Snowflake is read again on the next request; direct: at once).
`rebuild`: fake -> `{"ok": false, "message": "Demo: the CALL runs only on Snowflake (not FAKE=1)."}`; direct -> drop the
cache (everything read again); snapshot -> `CALL <WHERE>.SP_ACCESS_SNAPSHOT('AUTO')`, then drop the cache.
Answer: `{"ok": true, "result": <the procedure's JSON or null>, "message": "..."}`. Mirrors `app.refresh()`.

### POST /api/mine/load

Reads the logged-in user's own access (see sessions; `?fresh=1` reads Snowflake again, else the cached copy), sets `ae_sid`. Answer: `{"loaded": true, "user": "ENGINEER_01",
"loaded_at": "...", "expires_at": "...", "notes": [...]}`. Producer: `a.mine()` / `a.only()`.

### GET /api/mine

`{"loaded": bool, "user", "loaded_at", "expires_at"}` for the cookie, no Snowflake call.

### GET /api/find?q=&limit=20&view=

Global search over users (as `a.uid` ids), roles and objects. Producer: `a.search(q, names)` with
`names = [a.uid(u, True) for u in a.users] + a.roles + a.objects`.

```json
{"items": [{"id": "ENGINEER_01", "name": "ENGINEER_01", "kind": "user", "kind_label": "User · person",
            "type": null, "sensitive": false, "page": "user"},
           {"id": "SALES.CORE.TBL_CUSTOMER", "name": "SALES.CORE.TBL_CUSTOMER", "kind": "object", "kind_label": "Table",
            "type": "TABLE", "sensitive": true, "page": "object"}], "total": 2}
```

### GET /api/list?what=users|roles|objects|types|databases&type=&view=

Picker options. users: `a.users` (+ status); roles: `a.roles` (+ kind); objects: `a.objects` (filter by `type`,
+ type); types: `sorted(set(a.kinds.values()))`; databases: database names of `a.objects` (review page).
Answer: `{"items": [{"id", "name", "kind", "type", "status"}]}`.

### GET /api/user?view=&name=&roles=all|default&depth=&dataonly=1&schema=&otype=&on=&priv=

User page. In mine, `name` is ignored (always `a.users[0]`). `depth`: empty = no limit, else 1/3/5/10.
`dataonly=1` (default) hides USAGE on databases and schemas from every tab but Usage.

Producers: `a.grants(u, True, default_only, limit)` (rows), `a.reach(...)` (roles held, granted and database roles),
`a.admin_paths(...)`, `a.account_privs(...)`, `a.profile`, `a.status`, `a.login_days`, `a.is_dormant`,
`a.scopes`/`a.in_scope`, `a.priv_cat`, `a.paths_note`, `a.data_views(u, True)`, `a.sensitive_reach(u)`,
`a.used_roles(u)`, `a.used`, rule rows (`a.cached("rows", a.rule_rows)`) for the findings banner, and the graph from
`a.graph_input(...)` (+ `a.too_big` / `a.summary` unless `full=1`) or `a.down_graph(u, rows)` when `on` or `priv` is set.

```jsonc
{
  "view": "shared",
  "user": {"id": "ENGINEER_01", "name": "ENGINEER_01", "type": "PERSON", "status": "active", "disabled": false,
           "service": false, "default_role": "F_ENGINEER", "secondary_roles": "All", "default_warehouse": "WH_DEV",
           "last_login": "2026-10-30 08:12", "last_login_text": "2026-10-30 08:12 · 3 days ago", "login_mark": "",
           "login_days": 3},
  "filters": {"roles": "all", "depth": null, "dataonly": true, "schema": "", "otype": "", "on": "", "priv": "",
              "objects": ["SALES.CORE.TBL_CUSTOMER"], "privileges": ["SELECT", "USAGE"]},
  "banners": [{"tone": "info", "title": "3 grants hidden in this mode", "lines": ["..."]}],
  "findings": [{"num": "19", "severity": "Medium", "title": "EXECUTE TASK held by a person or consumer role",
                "grantee": "ENGINEER_01", "kind": "user", "details": ["EXECUTE TASK via ..."]}],
  "findings_total": 4,
  "kpis": {"privileges": 29, "objects": 21, "paths": 33, "multi": 3, "roles": 11, "roles_direct": 3, "deepest": 3,
           "sensitive": 2, "sensitive_known": true, "admin_roles": 0, "account_privs": 1},
  "account": {
    "admin": [{"role": "SYSADMIN", "path": ["ENGINEER_01", "F_PLATFORM", "SYSADMIN"]}],
    "privileges": [{"privilege": "EXECUTE TASK", "path": ["ENGINEER_01", "F_ENGINEER", "T_SALES_PIPELINE_EXECUTE"],
                    "via_public": false}],
    "public": ["VIEW LINEAGE"]           // "via PUBLIC: every user has these" (grouped in the Account tab)
  },
  "graph": { /* Graph */ },
  "tabs": [{"key": "account", "label": "Account", "count": 1}, {"key": "granted", "label": "Granted roles", "count": 9},
           {"key": "database_roles", "label": "Database roles", "count": 2}, {"key": "usage", "label": "Usage", "count": 6},
           {"key": "warehouses", "label": "Warehouses", "count": 1}, {"key": "execute", "label": "Execute", "count": 4},
           {"key": "read", "label": "Read", "count": 8}, {"key": "write", "label": "Write", "count": 3},
           {"key": "own", "label": "Own", "count": 2}, {"key": "manage", "label": "Manage", "count": 1},
           {"key": "all", "label": "All", "count": 29}],
  "privileges": [{
    "privilege": "SELECT", "cls": "read", "tab": "read", "type": "TABLE",
    "object": "SALES.CORE.TBL_CUSTOMER", "database": "SALES", "schema": "CORE", "name": "TBL_CUSTOMER",
    "future_label": null, "granted": "F_ANALYST", "holder": "T_SALES_CORE_READ", "depth": 2,
    "path": ["ENGINEER_01", "F_ANALYST", "T_SALES_CORE_READ", "SALES.CORE.TBL_CUSTOMER"],
    "count": 2, "paths_note": "", "sensitive": true,
    "hidden": false                      // true: database/schema USAGE that Data only hides outside the Usage tab
  }],
  "roles": [{"role": "F_ANALYST", "kind": "functional", "tab": "granted", "depth": 1, "direct": true,
             "path": ["ENGINEER_01", "F_ANALYST"], "count": 1, "admin": false}],
  "multi": {"rows": [{"privilege": "SELECT", "cls": "read", "object": "...", "depth": 2, "path": ["..."]}],
            "total": 7, "shown": 7},     // every path of rows with count > 1, first 300
  "can_read": [ /* DataView, shared only */ ],
  "sensitive": {"known": true, "roles": ["F_ANALYST"], "rows": [ /* SensitiveReach */ ]},
  "granted": [{"role": "F_ANALYST", "kind": "functional", "default": false, "used": {"queries": 41, "last_used": "..."},
               "used_text": "41 queries · 2026-10-31"}],
  "usage": {"days": 30, "source": "ACCOUNT_USAGE", "readable": true,
            "rows": [{"kind": "ROLE", "name": "F_ANALYST", "queries": 41, "last_used": "2026-10-31 09:00"}]},
  "capped": [],                          // a.capped after the page: walks cut at MAX_HOPS
  "refs": { /* Refs */ }
}
```

**Privilege tabs** (row `tab`): `account` if type is ACCOUNT; `warehouses` if type is WAREHOUSE; otherwise
`a.priv_cat(privilege, type)` -> `usage | read | write | execute | own | manage`; `hold` (USAGE on a role)
-> `database_roles` when the role is a database role, else `granted`. Granted roles and Database roles tabs list
`roles` rows (from `a.reach`) by their `tab`. The Account tab lists `account` (admin roles first, then account
privileges, `via PUBLIC` grouped) plus `privileges` rows with `tab: "account"`. A tab with count 0 is left out
(All stays). Each tab's diagram: `GET /api/graph?of=user-tab`.

### GET /api/role?view=&name=&depth=&users=0&sensitive=0&schema=&otype=&cut=&lacks=&full=

Role page. Producers: `a.role_stats(r, limit)`, `a.holds_of(r)`, `a.held(r, limit)`, `a.grants(r)` (effective),
`a.reach(r)` (roles held), `a.readonly_writes(r)`, `a.admin_paths(r)`, `a.account_privs(r)`, `a.has_lacks(r, o)`,
`a.valid_privs(t)`, `a.loses(...)` and `a.fix_text([a.role_edge(...)])` for `cut`, `a.data_views(r, False)`; graph from
`a.role_graph(r, up, ro)` merged with `a.graph_input(r, ...)` as `app.role_graph_card`.

```jsonc
{
  "role": {"id": "F_ANALYST", "name": "F_ANALYST", "kind": "functional", "owner": ["F_DEPLOY"], "admin": false},
  "filters": {"depth": null, "users": false, "sensitive": false, "schema": "", "otype": "", "cut": "", "lacks": "",
              "cuts": ["GRP_ANALYSTS", "ANALYST_01"], "gaps": ["DELETE", "INSERT"]},
  "kpis": {"privileges": 0, "future": 0, "effective": 14, "above": 2, "above_direct": 1, "users": 6,
           "users_direct": 2, "farthest": 3, "sensitive": 2, "holds_roles": ["T_SALES_CORE_READ"]},
  "scope_kpis": null,                    // with ?schema=: {direct, effective, objects, holders, sensitive}
  "banners": [], "findings": [], "findings_total": 0,
  "readonly_writes": [{"object": "...", "privileges": ["INSERT"], "holder": "...", "inherited": true, "how": "name",
                       "read_only": 9, "objects": 10}],
  "account": { /* as user */ },
  "graph": { /* Graph: lanes "Users", "Held by · D3", ..., "Depth 1 · Selected role", "Holds · D2", ...; selected = role */ },
  "held_by": {"rows": [{"grantee": "ANALYST_01", "id": "ANALYST_01", "kind": "user", "kind_label": "User · person",
                        "status": "active", "depth": 2, "direct": false, "only_via": ["GRP_ANALYSTS"],
                        "path": ["ANALYST_01", "GRP_ANALYSTS", "F_ANALYST"], "count": 1,
                        "loses_it": false, "loses": [["SELECT", "SALES.CORE.TBL_CUSTOMER"]]}],
              "revoke": null},           // with cut: {"grantee", "lost": 3, "users": 2, "iac": "...", "sql": "..."}
  "holds": {"types": [{"type": "TABLE", "privs": ["OWNERSHIP", "SELECT", "INSERT"],
                       "rows": [{"object": "...", "name": "...", "cells": {"SELECT": "direct" , "INSERT": "lacks",
                                 "OWNERSHIP": "lacks"}, "text": "SELECT but not INSERT"}]}],
            "other": [{"privilege": "CREATE TABLE", "cls": "manage", "type": "SCHEMA", "object": "...", "name": "..."}],
            "count": 3, "objects": 2},   // cell: direct | inherited | owner | lacks
  "tabs": [ /* as user */ ],
  "privileges": [ /* PrivRow, effective: path starts at the role, no "granted" */ ],
  "roles": [ /* ReachRow: roles it holds */ ],
  "can_read": [ /* DataView, shared only */ ],
  "capped": [], "refs": {}
}
```

Admin role: `admin: true`, no effective privileges or roles listed, a `bad` banner. An admin role nobody holds:
`404 not_found` with `message` pointing to People with admin roles.

### GET /api/object?view=&name=&type=&priv=&active=0&users=0

Object page. Producers: `a.object_stats(o, t, priv)`, `a.admin_holders()` + `a.from_user`, `a.matrix(o, t, priv=)`,
`a.grantees(o, t)`, `a.object_graph(o, t, shown, users)`, `a.tags_of(o)`, `a.policies_of(o)`, `a.tag_rules()`,
`a.tag_hit`, `a.sensitive_cols(o)`, `a.split_users(a.readers(o), a.admin_users())`, `a.policy_text(p)`,
`a.data_view(...)` (matrix cells and What each role sees), `a.valid_privs(t)`.

```jsonc
{
  "object": {"id": "SALES.CORE.TBL_CUSTOMER", "type": "TABLE", "database": "SALES", "schema": "CORE",
             "name": "TBL_CUSTOMER", "sensitive": true, "privileges": ["OWNERSHIP", "SELECT", "INSERT"]},
  "filters": {"type": "TABLE", "priv": "", "active": false, "users": false},
  "kpis": {"people": 9, "disabled": 1, "service": 1, "admin": 2, "read": 7, "write": 2, "own": 1,
           "roles": 6, "direct": 3, "owners": ["T_SALES_CORE_OWNER"], "deployers": ["DEPLOY_SVC"],
           "owner_note": "", "longest": 4},
  "admin_paths": [["ADMIN_01", "ACCOUNTADMIN"]],
  "sensitivity": {"object_tags": [{"label": "SENSITIVITY=PII", "origin": "inherited from schema SALES.CORE",
                                   "sensitive": true}],
                  "row_policies": [{"name": "...", "args": "REGION", "text": "...", "from_text": true}],
                  "columns": [{"column": "EMAIL", "tags": [{"label": "...", "sensitive": true}], "semantic": "EMAIL",
                               "masking": ["MP_EMAIL"], "clear_for": [{"role": "F_HR", "how": "session"}],
                               "clear_known": true, "unmasked_everyone": false}],
                  "policy_text": {"MP_EMAIL": "CASE WHEN ..."},
                  "readers": {"people": 9, "admin": 2, "service": 1}} ,   // null when no tag or policy
  "matrix": {"privs": ["OWNERSHIP", "SELECT"], "sensitive_cols": ["EMAIL"], "row_policy": true,
             "rows": [{"user": "ANALYST_01", "type": "PERSON", "status": "active", "admin": [], "real": true,
                       "cells": {"SELECT": {"has": true, "owner": false, "depth": 3, "count": 1, "title": "SELECT via ..."}},
                       "seen": {"EMAIL": {"state": "masked", "reason": "..."}}, "rows_state": {"state": "all", "reason": "..."},
                       "via": [{"classes": ["read"], "roles": ["GRP_ANALYSTS"], "holders": ["T_SALES_CORE_READ"]}],
                       "depth": 3, "paths": 1, "path": ["..."], "admin_paths": []}]},
  "graph": { /* Graph: lanes Users, Depth n ... Depth 1 · Grant holders, Object */ },
  "sees": {"cols": ["EMAIL"], "row_policy": true,
           "rows": [{"role": "F_HR", "rows": {"state": "all", "reason": "..."}, "columns": [{"column": "EMAIL", "state": "clear", "reason": "..."}]}]},
  "tabs": [{"key": "read", "label": "Read", "count": 7}, {"key": "write", "label": "Write", "count": 2},
           {"key": "own", "label": "Own", "count": 1}, {"key": "all", "label": "All", "count": 10}],
  "grantees": [{"grantee": "ANALYST_01", "id": "ANALYST_01", "kind": "user", "kind_label": "User · person",
                "status": "active", "privileges": [{"privilege": "SELECT", "cls": "read", "tab": "read"}],
                "tabs": ["read"], "depth": 3, "path": ["ANALYST_01", "GRP_ANALYSTS", "F_ANALYST", "T_SALES_CORE_READ",
                "SALES.CORE.TBL_CUSTOMER"], "count": 1}],
  "capped": [], "refs": {}
}
```

Grantees are merged per (grantee, kind, path) as `app.object_page`; their `tabs` (categories of their privileges, same
mapping as the user page) drive the category tabs. `active` drops disabled users; `users` keeps only chains that end
at a user (graph and grantees). `sees` and `sensitivity` are shared only (null in mine).

### GET /api/check?view=&name=&obj=&priv=SELECT

Can they? Producers: `a.can(u, priv, obj)`, `a.admin_paths(u, True)`, `a.login_days`, `a.is_dormant`,
`a.data_view(u, obj, True)` and `a.data_view(use_role, obj, False)` (read line), `a.priv_class`, the usage card
(`a.used`), and the graph from `a.down_graph(u, [dict(privilege, type, object, paths)], user=True)`.
`obj` default: `on`, else the first table or view the user reaches (as app.check_page).

```jsonc
{
  "user": "ANALYST_01", "object": "SALES.CORE.TBL_CUSTOMER", "type": "TABLE", "priv": "SELECT",
  "privileges": ["OWNERSHIP", "SELECT"],          // a.valid_privs(type), for the picker
  "answer": {"yes": true, "how": "paths" | "owner" | "admin" | "none", "title": "Yes, through 2 paths",
             "text": "ANALYST_01 can SELECT SALES.CORE.TBL_CUSTOMER.", "tone": null | "warn" | "low",
             "stats": [["Paths", 2], ["Shortest depth", 3]]},
  "status": "active", "dormant_days": null,
  "admin_paths": [],
  "paths": [{"path": ["..."], "depth": 3, "holder": "T_SALES_CORE_READ", "how": "direct grant on T_SALES_CORE_READ"}],
  "owner": [], "choke": ["GRP_ANALYSTS"], "closest": null,
  "ask": [{"role": "F_ANALYST", "privileges": 14, "path": ["..."]}],   // only when no path; empty in mine
  "options": [{"iac": "...", "sql": "REVOKE ...;", "affects": 3, "users": ["..."], "edges": 1}],  // shared only
  "use_role": "F_ANALYST", "warehouse": "WH_ANALYST",
  "read": {"summary": "can read: all rows, EMAIL masked", "rows": {}, "columns": [], "role_only": "..."},  // or null
  "graph": { /* Graph */ },
  "usage": { /* as user */ }, "capped": [], "refs": {}
}
```

### GET /api/sensitive?view=&tag=&db=&people=0&a=&b=

Sensitive data. Producers: `a.governance_kpis()`, `a.cached("sens", a.sensitive)`, `a.sensitive_rank()`,
`a.who_can(o)` + `a.from_user`, `a.split_users`, `a.admin_users()`, `a.admin_paths(u, True)`, `a.reads([role])`,
`a.data_view(role, o, False)` (mask text), `a.tag_label`, `a.run["SOURCES"]["tags"]`.

```jsonc
{
  "state": "ok" | "mine" | "unavailable" | "no_tags" | "none_sensitive",   // why there is nothing (app.no_tags)
  "governance": {"Row access policies used": "2 tables"},
  "filters": {"tag": "", "db": "", "people": false, "tags": ["SENSITIVITY=PII"], "dbs": ["HR", "SALES"]},
  "kpis": {"objects": 6, "columns": 9, "whole": 1, "people": 12, "admin": 2, "disabled": 1, "service": 1,
           "unmasked": 3, "stale": ["OLD_USER_01"]},
  "objects": [{"object": "...", "database": "SALES", "schema": "CORE", "name": "TBL_CUSTOMER", "type": "TABLE",
               "tags": [{"label": "SENSITIVITY=PII", "origins": ["on column EMAIL"]}], "cols": ["EMAIL"],
               "masked": [1, 2], "row_policies": ["..."], "people": ["..."], "disabled": [], "service": [], "admin": [],
               "roles": ["..."]}],
  "readers": [{"user": "ANALYST_01", "type": "PERSON", "status": "active", "last_login_text": "...", "objects": ["..."],
               "roles": ["GRP_ANALYSTS"], "path": ["..."], "via_admin": false, "admin_paths": []}],
  "compare": {"a": "F_ANALYST", "b": "F_HR", "roles": ["..."],
              "rows": [{"object": "...", "a": "EMAIL masked · all rows", "b": null}], "diff": ["..."]},
  "refs": {}
}
```

### GET /api/rules?view=&grantee=&sev=&rule=

Rule checks; works in mine (the rules run on the slice that was loaded, as app.py). Producers:
`a.cached("rows", a.rule_rows)`, `a.RULES`, `a.SEVERITY`, `a.admin_people()`, `a.row_terms` + `a.policies_of` (rows
unknown note); rule texts per number are in `meta.rules`.

```jsonc
{
  "scope": "account" | "mine",
  "filters": {"grantee": "", "sev": "", "rule": ""},
  "counts": {"High": 12, "Medium": 20, "Low": 9, "Passing": 2},
  "per_rule": {"1": 2, "2": 1},
  "findings": [{"num": "10", "title": "...", "severity": "Medium", "why": "...",
                "grantees": [{"id": "FIN_01", "kind": "user"}],   // same fix merged into one row
                "detail": "...", "more": 13, "paths": [["..."]], "edge_cls": "write",
                "iac": "...", "sql": "...", "affects": 14, "impact": "14 users lose access", "same_fix": ""}],
  "total": 41,
  "rows_unknown": ["HR.PEOPLE.TBL_EMPLOYEE"],
  "admins": [{"user": "ADMIN_01", "service": false, "roles": ["ACCOUNTADMIN"], "account": ["MANAGE GRANTS"],
              "paths": [["ADMIN_01", "ACCOUNTADMIN"]], "status": "active", "last_login": "..."}],
  "refs": {}
}
```

`GET /api/rules.csv` (same params): the findings CSV of app.rules_page (header lines Rule checks, Run, Generated).

### GET /api/review?db=*|DB&schema=&object=&active=0&hideusage=1

Access review, shared only. Producer: `a.review(None if db == "*" else db)`, sorted and filtered as
`app.review_page`. `hideusage` affects the screen rows only.

```jsonc
{
  "filters": {"db": "SALES", "dbs": ["FINANCE", "SALES"], "schema": "", "schemas": ["CORE"], "object": "",
              "objects": ["TBL_CUSTOMER"], "active": false, "hideusage": true},
  "kpis": {"objects": 14, "users": 22, "not_active": 3, "rows": 60, "admin_rows": 2, "hidden_usage": 9, "sensitive": 2},
  "rows": [{"database": "SALES", "schema": "CORE", "object": "TBL_CUSTOMER", "type": "TABLE", "future_label": null,
            "user": "ANALYST_01", "user_type": "PERSON", "status": "active", "last_login": "...",
            "privileges": ["SELECT"], "classes": ["read"], "sensitive": ["SENSITIVITY=PII"], "granted": ["GRP_ANALYSTS"],
            "path": ["ANALYST_01", "GRP_ANALYSTS", "F_ANALYST", "T_SALES_CORE_READ", "SALES.CORE.TBL_CUSTOMER"],
            "admin": false, "hidden": false}],
  "refs": {}
}
```

### GET /api/review.csv?db=&schema=&object=&active=0

`text/csv`, `Content-Disposition: attachment; filename=access_review_<DB|ALL>_<yyyy-mm-dd>.csv`. Every row (USAGE
included), columns Database, Schema, Object, Type, User, User type, Status, Last login, Privileges, Classes,
Sensitive, Granted roles, Path, Reviewer, Keep/Revoke, with the header lines of `app.review_page` (Access review, Run,
Filter, Generated). Other tables export CSV in the browser from the JSON rows.

### GET /api/whatif?view=&changes=&builtin=

What if grants went: `a.what_if(changes, cap=a.MAX_PATHS)`. Read-only: the loaded lookups are rebuilt in memory
without the changes, diffed, and put back; nothing runs in Snowflake, `iac` / `sql` are text to apply through
infrastructure as code. The rules recheck only the users and roles a change can touch (`a.SCOPED`, `a.GROW`).
`changes`: URL-encoded JSON list, one or more of

| op | fields | SQL text |
|---|---|---|
| `revoke_role_from_user` | `role`, `user` | `REVOKE ROLE R FROM USER U;` |
| `revoke_role_from_role` | `role`, `grantee` | `REVOKE ROLE R FROM ROLE G;` (DATABASE ROLE for a database role) |
| `revoke_priv` | `role`, `privilege`, `object` | `REVOKE P ON <type> O FROM ROLE R;` (OWNERSHIP: a transfer) |
| `drop_role` | `role` | `DROP ROLE R;` (not PUBLIC, not an admin role) |
| `empty_public` | | every grant to PUBLIC revoked (PUBLIC itself stays: every user holds it) |

400 `bad_param` (not a JSON list of objects), 400 `bad_change` (unknown op, a grant that is not there, PUBLIC or an
admin role dropped; the message names it).

```json
{
  "changes": [{"change": {"op": "revoke_role_from_role", "role": "T_SALES_CORE_READ", "grantee": "F_ANALYST"},
               "label": "Revoke role T_SALES_CORE_READ from role F_ANALYST",
               "iac": "Remove in the infrastructure-as-code repo: role T_SALES_CORE_READ granted to role F_ANALYST",
               "sql": "REVOKE ROLE T_SALES_CORE_READ FROM ROLE F_ANALYST;"}],
  "summary": "2 users lose access to 3 objects; 3 keep access through another path (most via T_SALES_MART_READ); 0 findings fixed, 0 new, 2 changed",
  "counts": {"users": 2, "objects": 3, "kept": 3, "unreached": 0, "ownerless": 0, "orphans": 0, "unreached_roles": 0,
             "fixed": 0, "new": 0, "changed": 2},
  "users": [{"user": "ANALYST_01", "status": "active", "lost": 3, "objects": 3, "kept": 1,
             "lost_rows": [{"object": "SALES.CORE.TBL_CUSTOMER", "type": "TABLE", "privileges": ["SELECT"],
                            "classes": ["read"], "path": ["ANALYST_01", "GRP_ANALYSTS", "F_ANALYST", "T_SALES_CORE_READ",
                                                          "SALES.CORE.TBL_CUSTOMER"]}],
             "kept_rows": [{"object": "SALES", "type": "DATABASE", "privileges": ["USAGE"], "classes": ["read"],
                            "path": ["ANALYST_01", "...", "T_SALES_CORE_READ", "SALES"],
                            "via": ["ANALYST_01", "GRP_ANALYSTS", "F_ANALYST", "T_SALES_MART_READ", "SALES"],
                            "through": "T_SALES_MART_READ"}],
             "kept_roles": []},
            {"user": "ENGINEER_01", "status": "active", "lost": 0, "objects": 0, "kept": 0, "lost_rows": [], "kept_rows": [],
             "kept_roles": [{"role": "T_SALES_CORE_READ", "path": ["ENGINEER_01", "F_ENGINEER", "T_SALES_CORE_READ"],
                             "via": ["ENGINEER_01", "F_ENGINEER", "T_SALES_CORE_READ"], "through": "F_ENGINEER"}]}],
  "objects": [{"object": "SALES.MART.VW_CUSTOMER", "type": "VIEW", "sensitive": true, "unreached": false, "ownerless": true}],
  "roles": [{"role": "T_SALES_CORE_WRITE", "kind": "technical", "orphan": true, "unreached": true}],
  "findings": [{"num": "4", "title": "OWNER role held by a consumer", "severity": "High", "grantee": "F_ENGINEER",
                "kind": "functional", "detail": "T_SALES_MART_OWNER", "path": ["F_ENGINEER", "T_SALES_MART_OWNER"],
                "status": "fixed", "changed": false}],
  "iac": "Remove in the infrastructure-as-code repo: ...", "sql": "REVOKE ROLE T_SALES_CORE_READ FROM ROLE F_ANALYST;",
  "refs": {"kinds": {}, "types": {}, "labels": {}, "sensitive": [], "disabled": []}
}
```

(`objects`, `roles` and `findings` above are from other changes, to show their shape.)

- `users`: everyone who reaches something under a change, most objects lost first. `lost` / `kept`: privileges
  (exact); `lost_rows` / `kept_rows`: one row per object, the first `max_paths` objects; `path` = the shortest path
  before, `via` = the path left, `through` = its first role the old path did not use; `kept_roles`: the roles right
  under a cut the user still reaches. `objects`: objects nobody reaches any more (`unreached`) or left without an
  OWNERSHIP grant (`ownerless`). `roles`: roles left without users or parent roles (`orphan`), or that no user reaches
  any more (`unreached`). `findings`: rule findings that go (`fixed`) or come (`new`); `changed`: the rule still
  fires on that grantee with another detail (counted once per rule and grantee in `counts.changed`).
- Entry points (UI): a "What if revoked?" button on role pages, grant / path rows, findings and Can they?, each
  adding one change to the list.

`GET /api/whatif.csv` (same params): `text/csv`, `what_if_<yyyy-mm-dd>.csv`, every row (no cap), columns Section
(change | user | object | role | finding), Name, Privilege, Type, Object, Cls, Status (lost | kept | kept role |
unreached | ownerless | orphan | fixed | new), Path, Detail, with the header lines What if (summary), Run, Generated,
Infrastructure as code, SQL (never run by this app).

### GET /api/graph?view=&of=user|role|object|check|user-tab|role-tab&...&full=0

Graph alone (the page answers already hold their main graph; this one serves tab diagrams and `full=1` / filter
changes without the rest of the page). Params: those of the page named by `of`, plus `tab` for `*-tab`.
Answer: `Graph`. Producers: as the pages; tab graphs `a.down_graph(start, rows_of_tab, walked)` with
`walked = [x["path"] for x in reach rows of the tab]` for the Granted roles / Database roles tabs.

## Doubts

1. **Tab mapping** (account / warehouses / granted / database_roles on top of `a.priv_cat`) and the RULE_INFO / note
   texts live in app.py today, and app.py can't be imported (it runs `main()`). Copying them into server.py duplicates
   logic; better: `access.py` gets `priv_tab(pv, kind)` and the rule area/meaning/fix and note texts (or a small shared
   `texts.py`), used by both. Until then server.py copies them, marked `# keep in step with app.py`.
2. **Fold children.** `a.summary()` returns fold boxes but not which roles each hides; `groups[fold].nodes` needs
   them. Without an access.py change the server derives them from the full graph (roles below the granted role that
   are not holders); the cleaner fix is `summary()` returning `members`.
3. **Payload builders for Streamlit.** For SiS to send the same JSON to the React components, the builders must be
   importable without FastAPI: server.py keeps them as plain functions and imports FastAPI only in its app factory /
   `__main__`, so `st_react.py` can `import server` (or the builders move to a module both import).
4. **Database role kind.** CLAUDE.md says kind `"database"`, the run brief says `"database_role"`; the API always says
   `database_role` and maps both. Group-node kinds are renamed (`database_group`, ...) so they never clash.
5. **Shared/mine thrash.** One process, one set of module globals: alternating requests from a shared and a mine tab
   rebuild each time (`build` is keyed). Fine for one local user; a second worker process would avoid it.
6. **Local My access identity** is the `.env` connection user (same as the shared reads when not using a snapshot);
   true per-viewer identity only exists in SiS.
