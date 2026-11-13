# JSON API: server.py

Contract between `server.py` (FastAPI, local version) and the React app in `web/`. The same JSON shapes feed the React
components inside Streamlit in Snowflake (`st_react.py`), so a component never knows which version it runs in.
TypeScript types: `web/src/api/types.ts` (keep both in step).

## Principles

- **Read-only.** Every endpoint is `GET`, except `POST /api/reload` and `POST /api/mine/load`. Nothing runs GRANT,
  REVOKE, CREATE, ALTER or DROP. The only write-like call is `CALL <ACCESS_SNAPSHOT>.SP_ACCESS_SNAPSHOT('AUTO')`
  (owner's rights), from `POST /api/reload` with `what=rebuild`. Fix texts (`iac`, `sql`) are text to copy, never run.
- **No logic in server.py.** Every number, path, rule and walk comes from `access.py` (the functions named per endpoint
  below). The server only picks, filters (the same filters for every page), renames to the JSON keys here, and adds
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
mirrors the page URL (`?page=user&name=...&depth=3&data=mine`), so links stay shareable; `data=mine` becomes `view=mine`.

## Data loading and caching

### Modes (meta.mode / meta.source)

Switches (`cache.config()`):

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
- Build key: `("shared", run["RUN_ID"], str(run["FINISHED_AT"]))`.
- A load error is kept for the request only (not cached): `503 shared_unreadable`, and the UI points to My access.

### My access: per browser session, 1 hour, memory only

- Cookie `ae_sid`: 32 random hex chars (`os.urandom(16).hex()`), set by `POST /api/mine/load`. `HttpOnly`,
  `SameSite=Strict`, `Path=/api`, `Max-Age=3600`. Not `Secure` locally (http://localhost).
- Server dict `MINE = {sid: {"data": dict, "key": ("mine", <random hex>), "user": str, "at": epoch}}`. `key` is
  random, so two sessions never share `a.build` lookups or rule findings.
- Every `view=mine` request: look up the cookie; missing, unknown or older than 3600 s -> `409 mine_not_loaded`
  (expired entries are dropped on the way). Found -> `a.build(data, key)` and answer from memory: no Snowflake call per
  click.
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
Answers even when the data is not loaded (`loaded: false`, no run). `cache_hours`: `CACHE_HOURS` when copies are
kept in `.cache/`, else 0 (the My access card says where your access is kept).

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
`names = [a.uid(u, True) for u in a.users] + a.roles + a.objects`. `answer`: one line per hit, for a person or role
"reads N · changes N · owns N" (`a.reach_counts`, reach only, the same numbers as the Access screen), for an object the
people with access.

```json
{"items": [{"id": "ENGINEER_01", "name": "ENGINEER_01", "kind": "user", "kind_label": "User · person",
            "type": null, "sensitive": false, "page": "user", "answer": "reads 6 · changes 5 · owns 2"},
           {"id": "SALES.CORE.TBL_CUSTOMER", "name": "SALES.CORE.TBL_CUSTOMER", "kind": "object", "kind_label": "Table",
            "type": "TABLE", "sensitive": true, "page": "object", "answer": "8 people have access"}], "total": 2}
```

### GET /api/list?what=users|roles|objects|types|databases[,...]&type=&q=&limit=&view=

Picker options. users: `a.users` (+ status); roles: `a.roles` (+ kind); objects: `a.objects` (filter by `type`,
+ type); types: `sorted(set(a.kinds.values()))`; databases: database names of `a.objects` (review page).
`what` takes a comma list (`users,roles` for a person-or-role picker). `q` filters and ranks the items as Find does
(`a.search`); `limit` caps the answer. The pickers search here as you type (50 at a time) instead of downloading
every name. Answer: `{"items": [{"id", "name", "kind", "type", "status"}], "total": n}` (`total` before `limit`).

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

### GET /api/who?view=&name=|preset=admin

Screen 2 (page key `object`): who has access to one object, or with `preset=admin` who holds an admin role.
`access.who_has` / `admin_access` / `same_paths` / `column_view`.

```
{ view, object: { id, preset, type, database, schema, name, sensitive, tags[], columns (sensitive count), masking[],
                  row_policies[], owners[], owner_note },
  people: [{ name, id, level: admin|own|change|read|use|names, privileges[], path, first, holder, ways, depth,
             admin[], status, service, days, login, mark, columns: [{ column, state, reason }] }],
  roles:  [{ name, kind, level, privileges[], path, first, holder, ways, depth, users }],
  groups: [{ level, privileges[], route[], names[] }],   // people with the same route ("12 people via PUBLIC")
  counts: { levels: {level: n}, people, roles, disabled, dormant },
  columns: [{ column, tags[], sensitive, policies[], clear[], masked[], unknown[] }],
  default_user, refs }
```
`app` is set for a Streamlit app (else null), from `a.app_exposure`: `{owner: [roles holding OWNERSHIP], sensitive: {object: [sensitive
columns]} (the owner reads them; `[]` = the whole object), holders: {role holding USAGE on the app: [users reaching it]},
exposed: {user: [sensitive objects they cannot read themselves]}}`. An app runs with its owner's rights, so whoever opens
it sees what the owner role reads; rule 29 is built from the same answer. The object page shows it as a banner.
A user holding an admin role is `admin` and shown by its shortest path to the admin role. 404 for an unknown name.

### GET /api/check?view=&name=|user=|role=&obj=&priv=SELECT|&do=read|change|own|any

The subject is a user (`name=`, or `user=` as on the Access screen) or a role (`role=`): users and roles are separate
namespaces, so `role=` always means the role. A `name=` that is no user but a role is that role (Home's typed
question). My access: always the signed-in user. For a role, every producer below runs with `is_user=False` /
`user=False`: its own grants plus the roles it inherits, routes start at the role (depth 1 itself), where to cut counts
the people holding it, nearest ways in grant a role to it (never one that holds it: a loop), `use_role` is the role.

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
  "subject": {"kind": "user" | "functional" | ..., "name": "ANALYST_01", "id": "ANALYST_01", "user": true, "people": null},  // people: users holding a role
  "status": "active", "dormant_days": null,         // status null for a role
  "admin_paths": [],
  "paths": [{"path": ["..."], "depth": 3, "holder": "T_SALES_CORE_READ", "how": "direct grant on T_SALES_CORE_READ"}],
  "owner": [], "choke": ["GRP_ANALYSTS"], "closest": null,
  "ask": [{"role": "F_ANALYST", "privileges": 14, "path": ["..."]}],   // only when no path; empty in mine
  "options": [{"iac": "...", "sql": "REVOKE ...;", "affects": 3, "users": ["..."], "edges": 1}],  // shared only
  "use_role": "F_ANALYST", "warehouse": "WH_ANALYST",
  "read": {"summary": "can read: all rows, EMAIL masked", "rows": {}, "columns": [], "role_only": "..."},  // or null
  "graph": { /* Graph */ },
  "usage": { /* as user */ }, "capped": [], "refs": {},
  // screens 3 and 12 (redesign)
  "verdict": "yes" | "partly" | "no",
  "held": [{"privilege": "SELECT", "held": true}],      // every privilege of the type; OWNERSHIP or an admin role: all
  "lanes": [{"path": ["..."], "privileges": ["SELECT"]}], "lanes_total": 2,   // a.lanes: one per distinct route (first 20)
  "cut": ["F_ENGINEER"],                                 // roles on every lane: a place to cut
  "cuts": [{"iac": "...", "sql": "...", "people": ["..."], "lost": 19, "edges": [{"grantee", "to", "priv", "user"}]}],  // a.cut_points, shared only
  "nearest": [{"path", "missing", "role", "to", "to_user", "cost", "people", "holders", "extra", "also", "rule1", "broad"}],  // a.nearest when No, shared only
  "ask_priv": "SELECT", "roles_count": 11, "approver": "HR data owner" | null,   // a.approver: OWNER / DATA_OWNER tag
  "layers": [{"step": "Grant" | "Rows" | "Columns", "ok": true, "result": "No rows", "reason": "..."}] | null  // Partly: rows none or columns masked
}
```
`do` picks the privilege when `priv` is not given: read = `a.basic_priv`, change = the first of `a.need_privs(type, "change")`,
own = OWNERSHIP, else every privilege (`*`).

### GET /api/request?view=&name=|user=|for_role=&obj=&need=read|change&role=&to=

For a person (`name=` / `user=`) or a role (`for_role=`; `role=` here is the role picked on Can they?): for a role the
grant is GRANT ROLE x TO ROLE <for_role>, `asked.to` is that role, and every suggestion says how many people holding it
get it too (`people`, `broad` when more than `BROAD_PEOPLE`).

Screen 15, Request access (page key `request`). Read-only: the page writes SQL / Terraform / ticket text (`codegen.ts`).
`a.need_privs`, `a.suggest` (functional roles reaching every needed privilege, fewest other privileges first; build and
admin-reaching roles never), `a.approver`, `a.object_stats` owners.

```
{ view, user, object, type, need, privileges[], level (the user's step today, or null), has (already holds them),
  subject: { kind, name, id, user, people },
  asked: { role, kind, to, rule1, people, broad } | null,  // the role picked on Can they? (role=, to=), checked against the roles
  suggestions: [{ role, path, holders, extra, also: [{ level, count, where }], unmasked[], people, broad }],
  approver, owners[], refs }
```
404 for an unknown user or object.

### GET /api/map?view=&table=|role=|user=&same=1&admin=1&builtin=

Screen 4, Access graph (page key `graph`; `show=trace` is its new tab, `sel=` the picked box, `risky=1` the highlight:
none of these reach the server). `a.access_graph(start, name, same, admin)`: columns by shortest step, every line's
`cls` the step it ends up granting (read / write / own / use; admin = bypass or account privilege), `count` the people
flowing through it; same-path people stacked (node mark `stack`), admin people and roles (`admin=0` hides them), PUBLIC's
built-ins as one fold box (`builtin=1` unfolds).

```
{ view, start: "object" | "role" | "user", name, id (start node), graph (Graph),
  detail: { <node id>: { level, people[30], people_count, leads[30], leads_count, risk, members (a stack) } },
  risky: { <edge id>: "admin" | "public" | "writes" }, risky_nodes: { <node id>: why }, why: { <why>: text },
  builtin, refs }
```
404 for an unknown table, role or user.

### GET /api/see?view=&user=|role=

Screen 7, What they see (page key `see`; `show=cards` the new tab, `part=sees|sens|usage` the old sub-tabs, `all=1` all
protected objects). `a.seen` (cards, sentence counts), `a.data_views` (old table), `sens_reach` (Sensitive data they can
see), `usage(u)` / `role_usage(r)`.

```
{ view, who: { kind, name, id, type, status, default_role, secondary_all, roles[] }, known,
  cards: [{ object, type, sensitive, rows: { state, reason, policy }, columns: [{ column, sensitive, state, reason, policy, fix }] }],
  counts: { objects, sensitive, columns, clear, masked, unknown, unprotected, rows } | null,
  can_read: DataView[] | null, sensitive: { known, roles[], rows[] } | null, usage: UsageCard | null, role_usage | null, refs }
```

### GET /api/compare?view=&a=&b=&scope=sensitive|all|db&db=

Screen 9, Compare two people or roles (page key `compare`; `show=diff` the new tab, `plan=match|extras` the change
text). `a.compare` (rows differences first, counts, `match` / `extras` as codegen changes; an admin side reaches every
object), `pair_rows` (the old Compare two roles table over the sensitive objects). A side is a user (also `X (user)`),
else a role. Default B: the person sharing most roles with A, not an admin.

```
{ view, a: { name, id, kind }, b, scope, db, dbs[], sensitive,
  rows: [{ object, type, database, schema, name, diff: "only_a"|"only_b"|"different"|"same",
           a: { level, privileges[], sees } | null, b, extra_a[], extra_b[] }],
  counts: { only_a, only_b, different, same }, match: Change[], extras: Change[],
  old: { rows: [{ object, a, b }], diff[] } | null, refs }
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

`catalog` (screen 8, `a.catalog()`, same tag / db filters), most exposed first:
`[{"object", "name", "ns", "type", "labels": ["PRIVACY_CATEGORY=IDENTIFIER"], "groups": ["pii"|"confidential"],
"status": "not"|"partly"|"protected"|"whole", "masked": [1, 3], "columns": [{"column", "masked", "policies"}],
"unmasked": 2, "row_policies": [], "readers": 6, "admin": 2}]`.

### GET /api/flow?view=

Screen 16, where sensitive data flows (shared only; `state` "mine" / "none" otherwise). Producer: `a.sens_flow()`.

```jsonc
{
  "state": "ok", "select": "risky",                       // default selection: the dormant or disabled
  "groups": [{"id": "risky", "label": "Dormant or disabled", "users": ["FIN_14"]}],   // active | risky | admin | service
  "roles": [{"id": "GRP_EMEA_ALL", "label": "GRP_EMEA_ALL", "users": ["..."], "kind": "group"}],  // "Admin roles" kind admin, "Other roles (N)" kind fold
  "objects": [{"id": "SALES.CORE.TBL_CUSTOMER", "label": "TBL_CUSTOMER", "ns": "SALES.CORE", "status": "partly",
               "unmasked": ["BIRTH_DATE", "PHONE"], "masked": ["EMAIL"], "row_policies": [], "users": ["..."]}],
  "links": [{"source": "risky", "target": "GRP_EMEA_ALL", "users": ["FIN_14"]}],     // group -> role, role -> object
  "refs": {}
}
```

### GET /api/rules?view=&grantee=&sev=&rule=

Rule checks; works in mine (the rules run on the slice that was loaded). Producers:
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
  // each finding also has "changes" (its fix as What if changes, [] when nothing to revoke) and "objects"
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

### GET /api/grid?scope=sensitive|db|all&db=&hideusage=1 | object=&columns=privileges

Screen 6 grid, shared only. Producer: `a.review_grid(scope, db, obj, hide_usage)`: people x objects (sensitive first,
most people first, up to `GRID_MAX` columns) or people x the privileges of one object. A user holding an admin role
has `admin` in every column.

```jsonc
{
  "scope": "sensitive" | "db" | "all" | "object", "db": "DW", "dbs": ["..."], "object": "",
  "columns": [{"id": "SALES.CORE.TBL_CUSTOMER", "name": "TBL_CUSTOMER", "ns": "SALES.CORE", "note": "EMAIL, PHONE", "sensitive": true}],
  "rows": [{"user": "FIN_14", "type": "PERSON", "status": "disabled", "days": 244, "last_login": "...", "admin": [],
            "roles": ["GRP_EMEA_ALL"], "suggest": "disabled",                 // roles: what a revoke takes away
            "cells": {"FINANCE.REPORT.TBL_REVENUE": {"level": "change", "privileges": ["INSERT", "SELECT"], "path": ["..."]}}}],
  "total": 5, "cap": 60, "sensitive": 5, "counts": {"people": 21, "admin": 2, "stale": 4, "service": 1},
  "refs": {}
}
```

Decisions (Keep / Revoke) stay in the browser (localStorage `ae-review`); Sign off downloads a CSV built in the
browser (reviewer, time, scope, one row per person with the decision and the access per column).

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

### GET /api/usage?view=&user=|role=&days=30|90|180

Granted vs used: `a.granted_used(name, user, days)` over `TBL_ACCESS_OBJECT_USE` (ACCESS_HISTORY per user, object,
week, READ / WRITE). 400 `bad_param` for another `days`. `available` false (with `reason` and `enable`, the grant
that makes ACCESS_HISTORY readable) when the snapshot has no usage.

```json
{"who": {"name": "ENGINEER_01", "kind": "user"}, "days": 90, "periods": [30, 90, 180], "available": true,
 "reason": null, "enable": "GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE <that role>; ...", "source": "demo values",
 "weeks": ["2026-08-10", "..."],
 "rows": [{"object": "HR.PEOPLE.TBL_EMPLOYEE", "type": "TABLE", "database": "HR", "schema": "PEOPLE", "sensitive": false,
           "level": "change", "used": null, "privileges": ["INSERT", "SELECT", "UPDATE"], "unused": ["INSERT", "SELECT", "UPDATE"],
           "weeks": [0, 0], "reads": 0, "writes": 0, "last": null, "people": ["ENGINEER_01"], "holder": "HR.SC_R_PEOPLE",
           "suggest": "drop", "text": "Remove all · not used in 90 days",
           "changes": [{"op": "revoke_priv", "role": "HR.SC_R_PEOPLE", "privilege": "SELECT", "object": "HR.PEOPLE.TBL_EMPLOYEE"}]}],
 "counts": {"objects": 4, "used": 3, "drop": 1, "trim": 2, "keep": 1, "write_unused": 1, "changes": 4},
 "changes": [], "people": ["ENGINEER_01"], "refs": {}}
```

`changes` are What if changes (`revoke_priv`, ownership never), for the change plan; nothing runs.

### GET /api/changes?view=&subject=

What changed: `a.diff(prev)` between the loaded snapshot and the previous one (`cache.prev(key)`: the copy kept in
`.cache/` when a newer run arrived; fake mode: `a.fake_previous()`). `available` false with `reason` inside Snowflake,
in My access, with `CACHE_HOURS=0` or before a second run. `subject` (user, role or object) keeps the events about it.

```json
{"available": true, "subject": null, "before": "2026-10-26 07:00", "now": "2026-11-02 07:00",
 "text": "Since the snapshot of 2026-10-26 07:00: 11 changes, 4 new high findings, 3 people gained sensitive access.",
 "counts": {"all": 11, "gain": 2, "lose": 2, "risk": 6, "sensitive": 7},
 "events": [{"id": "g1", "kind": "gain", "text": "T_SHARED_LOGGING_READ was granted INSERT on SHARED.LOGGING.TBL_LOGGING",
             "impact": "ANALYST_01, ANALYST_02 and 1 other can now change SHARED.LOGGING.TBL_LOGGING", "by": "F_DEPLOY",
             "sensitive": true, "findings": [{"num": "17", "severity": "High", "title": "Read-only role can write", "fixed": false}],
             "link": {"page": "object", "params": {"name": "SHARED.LOGGING.TBL_LOGGING", "show": "who"}},
             "subjects": ["T_SHARED_LOGGING_READ", "SHARED.LOGGING.TBL_LOGGING"], "people": ["ANALYST_01"], "objects": []}],
 "new": 6, "fixed": 2, "high": 4}
```

`kind`: `gain` | `lose` (grants), `user` (became dormant or disabled), `risk` (new finding), `fixed`. A `gain` /
`lose` event also has `edge` `{source, source_kind, target, target_kind, privilege, added}` (the grant drawn as two
boxes and a + or crossed-out link; `privilege` is `role` for a role grant). Without `subject` the answer has `severity`
`{"new": {"High": 4, ...}, "fixed": {...}}` for the strip of new against fixed findings (`null` with `subject`). Watched
questions are kept in the browser (localStorage `ae-watch`) and asked again through `/api/check` and `/api/who`.

### GET /api/activity?view=&name=|user=|role=&as=

Activity tab of an object (`name`), a person (`user`) or a role (`role`): use over the last `days` (60,
`ACTIVITY_DAYS`) from `TBL_ACCESS_ACTIVITY` (ACCESS_HISTORY, QUERY_HISTORY, SESSIONS: query metadata, never query
text). `what` follows the object type: `object` (table, view, ...), `app` (a Streamlit app: the queries it ran for its
viewers, matched on the table's `APP`), `scope` (a database or schema: every object in it), `warehouse` (see below),
`user`, `role`; `kind` is the object's type as the snapshot has it (`STREAMLIT`, `DATABASE`, `SCHEMA`, `WAREHOUSE`, ...,
null for a person or role). Producers: `a.activity(name, what, user)`, `a.activity_graph`, `a.activity_sensitive`,
`a.query_sql`, `a.app_use`, `a.warehouse_use`, `a.mark_sensitive`; the findings are the rule 24-28 rows of `a.rule_rows`
for the subject. `as` (object and app only) keeps one person's use: the object page's "Access for"; without it the tab
shows all users. `available` false (with `reason`) when the data has no
activity: no Enterprise edition, a snapshot made before the table existed, or My access (it reads no ACCESS_HISTORY).
`note` says when only part of it was read.

```json
{"view": "shared", "what": "object", "name": "SALES.CORE.TBL_CUSTOMER", "user": null, "days": 60,
 "kind": "TABLE", "available": true, "reason": null, "note": null, "first": "2026-09-04", "last": "2026-11-02",
 "work": {"start": 7, "end": 19},
 "daily": [38, 36, 51, "... 60 numbers, oldest first"],
 "by": {"user": [{"key": "SVC_DEPLOY", "read": 7, "write": 1500, "ddl": 0, "last": "2026-11-02 08:15", "daily": [25, 24, "..."]}],
        "role": [], "client": [], "type": [], "object": []},
 "rows": [{"user": "SVC_DEPLOY", "role": "F_DEPLOY", "client": "Python", "type": "MERGE", "object": "SALES.CORE.TBL_CUSTOMER",
           "action": "WRITE", "queries": 1500, "days": 60, "first_day": "2026-09-04", "last": "2026-11-02 08:15",
           "daily": [25, 24, "..."], "hours": [0, 0, "... 24 numbers"], "weekend": 0, "weekend_hours": [0, 0, "... 24 numbers"],
           "kind": "service", "interactive": false}],
 "total": 6,
 "ddl": [{"user": "ENGINEER_01", "role": "F_ENGINEER", "client": "Snowsight", "type": "ALTER_TABLE_ADD_COLUMN",
          "object": "SALES.CORE.TBL_CUSTOMER", "action": "DDL", "queries": 3, "days": 1, "last": "2026-10-21 11:15", "daily": [0, "..."]}],
 "findings": [{"num": "24", "title": "Person changed data or a table's definition", "severity": "Medium",
               "grantee": "ENGINEER_01", "detail": "INSERT 28, ALTER_TABLE_ADD_COLUMN 3 on SALES.CORE.TBL_CUSTOMER as F_ENGINEER, last 2026-10-30"}],
 "graph": {"title": "Who used it, through which grant", "header": "User, role used, then the grant path it has now", "lanes": [], "nodes": [], "edges": []},
 "gone": [],
 "sensitive": [{"object": "SALES.CORE.TBL_CUSTOMER", "sensitive": true, "columns": ["BIRTH_DATE", "EMAIL", "PHONE"], "whole": false,
                "masking": {"EMAIL": ["SHARED.GOVERNANCE.MP_EMAIL"]}, "row_policies": [],
                "people": [{"user": "ANALYST_01", "role": "GRP_ANALYSTS", "read": true, "clear": ["BIRTH_DATE", "PHONE"],
                            "masked": ["EMAIL"], "rows": "all"}]}],
 "mark": null,
 "objects": {"SALES.CORE.TBL_CUSTOMER": {"kind": "table", "sensitive": true}},
 "query_sql": "SELECT ... -- one row per query: id and time, no query text",
 "app": null, "refs": {}}
```

`by` has the five groupings (`user`, `role`, `client`, `type` = statement type, `object`), most queries first; `read`,
`write` and `ddl` are query counts per action (a MERGE that reads and changes a table counts in both) and `daily` is
one number per day, oldest first, ending at `last`. `rows` is one row per user, role, client, object, statement type
and action, the first 2000 (`MAX_ACTIVITY`); `total` counts all of them. `ddl` lists the DDL rows. In a row, `days` is
the number of active days and `first_day` the first of them; `hours` is the weekday queries per UTC hour (24 numbers),
`weekend` the queries on a Saturday or Sunday (by the UTC day) and `weekend_hours` those per UTC hour; `kind` is the
user's `person`, `service` or `system`; `interactive` is true for a client where people type queries (Snowsight,
SnowSQL, ...). The page counts off-hours from these: `work` is `WORK_HOURS` (default 7-19, local time, start inclusive,
end exclusive, Monday to Friday), and the UI shifts it from UTC with a business-time slider (UTC-12 to UTC+14). Nothing
off-hours is stored. `objects` has the type (`kind`, lower case, `gone` for an object no longer in the snapshot) and
`sensitive` of every object in `rows`. `query_sql` is SQL to copy and run in Snowflake for the query ids and times
behind the counts (no query text); the app never runs it. `graph` is a Graph
(see Shared shapes): user, role used, then the grant path that role has now, then the table (a person or role page:
role used first, top `MAX_OBJECTS` tables; null for an app or a database or schema); `gone` holds the rows whose role
reaches no grant on the table now (an admin role, or the grant was removed since). `sensitive` has one entry per used table that carries a sensitive tag or
a masking or row access policy; `people[].rows` is `all`, `filtered`, `none` or `unknown`, read from the policy text.
`mark` is `{sql, tf, ticket, tag, value}` for an object that is a table or view without a sensitive tag: text to tag
it, which the app never runs (else null). `findings` are the rule 24-28 findings for the subject (and for `as`).
`section_sql` is `{section key: sql}`, the query behind each section, shown by the `</>` mark in its card's corner (`a.activity_section_sql`; keys
`tiles`, `client`, `kinds`, `matrix`, `type_day`, `by_day`, `hours`, `off`, `touched`, `objects`, `who`, `ddl`); `hours` and `off`
have `WORK_START`, `WORK_END` and `TZ_HOURS` lines for business time. The app never runs them.
`app` is set only for a Streamlit app (else null), from `a.app_use`: `{can: {user: role holding USAGE}, opened:
{user: {queries, last}}, never: [users who can open it and did not], saw: {user: [sensitive objects they opened it for
but cannot read themselves]}}`. Opening an app without a table query leaves no row, so `opened` only has users whose
queries touched an object. A user in `opened` but not in `can` opened it without access now.
When `available` is false, only the head fields are returned (`view` to `note`).

For a warehouse (`kind` `WAREHOUSE`) there are no ACCESS_HISTORY rows: the answer is `{view, what: "warehouse", kind, name,
user: null, available, reason, warehouse: {used: [{user, queries, last}], unused: [users who can use or operate it and
did not]}, source}`. It comes from the query-history read (`USAGE` rows; `source` is its state, `demo values` for fake
data); `available` is false when that source is `UNAVAILABLE`, with `reason`.

### GET /api/sql?view=&page=&<the page's own parameters>

The SQL behind a page ("SQL behind this page": the top-bar **SQL** button, or a right-click on the page). `page` is a
page key (`home`, `access`, `object`, `usage`, `sensitive`, `flow`, `review`, `rules`, `whatif`, ...; default `home`);
the other parameters are the page's own (`user=`, `role=`, `name=`, `show=activity`). Producer: `a.page_sql`, which fills
the `SET` lines of the `access_queries/` files, or of a query of its own, for what the page shows. The app never runs
the queries; the viewer copies one into a worksheet and needs IMPORTED PRIVILEGES on database `SNOWFLAKE` (or the
database roles `SNOWFLAKE.SECURITY_VIEWER` and `SNOWFLAKE.GOVERNANCE_VIEWER`); ACCESS_HISTORY needs Enterprise edition.

```json
{"page": "access",
 "queries": [{"title": "Everything ANALYST_01 can reach, through which roles", "sql": "-- ...
SET USER_NAME = 'ANALYST_01';
..."},
             {"title": "Every role ANALYST_01 holds", "sql": "..."}]}
```

`queries` are most useful first, each `{title, sql}`: a person has `2_user_access.sql` and `1_user_roles.sql`; a role
`3_role_access.sql` and `4_role_holders.sql`; an object `5_object_users.sql` and its tags and policies. With
`show=activity`: one query per Activity section plus "Every query, one by one"; for a warehouse, queries per user and
role from QUERY_HISTORY and who can use it. `usage` adds the objects used per week; `sensitive`, `flow` and `review` the
sensitive tags; `rules`, `whatif`, `review` and `home` grants to PUBLIC, admin roles held by users and dormant or
disabled users with roles.

### GET /api/graph?view=&of=user|role|object|check|user-tab|role-tab&...&full=0

Graph alone (the page answers already hold their main graph; this one serves tab diagrams and `full=1` / filter
changes without the rest of the page). Params: those of the page named by `of`, plus `tab` for `*-tab`.
Answer: `Graph`. Producers: as the pages; tab graphs `a.down_graph(start, rows_of_tab, walked)` with
`walked = [x["path"] for x in reach rows of the tab]` for the Granted roles / Database roles tabs.

## Doubts

1. **Tab mapping** (account / warehouses / granted / database_roles on top of `a.priv_cat`) and the RULE_INFO / note
   texts live in server.py (app.py, now only the Streamlit wrapper, no longer has its own copy).
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
