# Redesign notes

Notes for the redesign brief (`access-explorer-redesign.zip`: 17 screens, tokens, specs). What the repo has today, what
stays, what changes, and the order of the work.

## What the repo has

| Area | Where | Notes |
|---|---|---|
| Pages / routes | `web/src/App.tsx` | One query string: `?page=<key>&<params>`, `data=mine` for My access. Keys: user, role, object, check, sensitive, rules, review, whatif. Streamlit mirrors the same query into the browser bar (`st/main.tsx`), so path routes (`/access`) would not work inside Snowsight: new screens are new `page` keys. |
| API | `server.py` `ROUTES` | One function per page (`user_page`, `role_page`, ...), the same dict for FastAPI and the Streamlit bridge (`st_react.app`). `meta` carries pages, badges, rules, notes, tokens. |
| Data layer | `access.py` | `fake()` / `snapshot()` / `live()` give one dict; `build()` turns it into lookups: `users`, `roles`, `roles_of` (user -> roles), `holds` (role -> roles), `granted` (role -> privileges), `kinds` (object types), `profile`, tags and policies. |
| Path engine | `access.py` | `grants(name, user)`: one row per (privilege, object) with shortest path, `paths` (up to `MAX_PATHS`), `count` (all paths, counted without listing), `holders`, `depth`. `reach()` for roles, `ups(role)` for who reaches a role, `can(user, priv, obj)` for Can they? with choke points. |
| Rules | `access.py` `checks()` | 23 rules, `SEVERITY`, findings with `grantee`, `edges` (grantee -> to, privilege), `paths`, `iac` / `sql` fix text, `losers`. `server.finding()` shapes them; `RULE_INFO` has area, meaning and fix. |
| What if | `access.what_if` / `changes_of` | Cut sets (user, link, priv, drop, public), restores every lookup after; result has users who lose, keep, findings fixed / new, and IaC + REVOKE text. Never runs it. |
| Policies | `access.data_view(name, obj)` | Columns clear / masked and rows all / filtered / none, each with the reason ("MP_EMAIL shows the value to F_ENGINEER"). |
| Streamlit | `app.py` + `st_react.py` | The React app as one component, API calls answered by `server.py` in Python. The plain Streamlit pages are removed; `ui.py` keeps the tokens, help texts and type icons `server.py` sends. |
| URL params | `App.tsx` `read()` | `page`, `name`, `data=mine`, `builtin=1` (show Snowflake built-ins), page filters (`schema`, `otype`, `on`, `priv`, `rule`, ...). |
| Tests | `test_access.py`, `test_server.py`, `test_sql.py`, `web` vitest | `python test_access.py` (also with `ROLE_PREFIXES=ZF_,ZT_`), `python test_server.py`, `npm test` in `web/`. Demo: `python run.py --fake`. |

## Keep

- Every engine: walks, rules, What if, policy evaluation. The redesign is a UI layer plus a few derived fields.
- The `?page=` URL scheme (Streamlit needs it); old links keep working through `redirect()` in `App.tsx`.
- The graph component (`@xyflow/react` + `elkjs`) and the role-kind node styles from CLAUDE.md (functional blue, technical
  coffee, group dashed amber, database role dashed grey-blue, admin red). The ladder colours are for access levels, not kinds.
- Bundled IBM Plex Mono and the system sans: no font CDN (Streamlit in Snowflake blocks it). The brief's Inter and JetBrains Mono are not loaded.
- Load on click, My access, the Incomplete box, CSV downloads.
- No new dependencies.

## Change

- Tokens: the cool blue-grey palette and one-hue access ladder from `design/tokens.css`, in `theme.ts` and `ui.py` `TOKENS`.
- App shell: header (logo to Home, search, snapshot time and refresh, Demo data badge instead of the full banner), side nav
  in two groups, Answers and Admin, collapsing to a top menu below 1000px.
- Shared components: `AccessPill`, `PathChips`, `FindingChip`, `SensitiveCell`, `FilterChips`, `ListToolbar`, `CodeOutput`
  (SQL / Terraform / ticket text), `ExpandableRow`, `EmptyState`, `IdentityCard`.
- Derived fields in `access.py`: `level_of` (ladder), `category` (data / runnable / account / names / hold),
  `access_objects` (one row per object at its highest level, path summary), with tests.
- New screens as page keys: `home` (0), `access` (1, a person or a role), `object` (2), `check` (3 and 12), `request`
  (15), graph (4), see (7), compare (9). Next: the admin screens.

## Done

- **Screen 1, A person or role** (`access`): "Diagram & privileges" (the old User / Role paths page) is the default
  tab, "One row per object" next to it.
- **Screen 2, Who has access to an object** (`object`, endpoint `/api/who`): "Diagram, paths & users" (the old Object
  page: graph, admin banner, Who has access by path / by user or role, Users × privileges, What each role sees,
  Sensitivity) is the default tab. Above the tabs: breadcrumb, name, tags (type, sensitive columns, masking and row
  policies, owner) and the "Access for [person]" strip (`as=`, defaults to the signed-in / demo user). Tab "Who has
  access" (`show=who`): stacked bar per level and "N disabled still hold access", People / Roles (`by=roles`), rows
  grouped by level (Admin, Owns, Can change, Read only, Can use, Can see names) with status, last login, PathChips,
  privileges and path count, disabled / dormant rows tinted; side panel "How X gets in" (`sel=`) with All paths (Can
  they?) and What if revoked?, and Sensitive columns (who sees each one unmasked). "Group people with the same path"
  (`same=1`, on by default for warehouses) shows "23 people via PUBLIC (everyone)". `preset=admin` is the Admin
  holders preset: its default tab is the Rule checks Admin holders table, which links here. Redirects:
  `rules&tab=admins` and `admins` -> `object&preset=admin`, `who` -> `object`. Home search already lands objects here.
  `access.py`: `obj_level`, `who_entry`, `who_has`, `admin_access`, `same_paths`, `column_view`.

- **Screens 3 and 12, Can they?** (`check`): the question as a sentence (Can [user] [privilege] [object]?), the
  verdict Yes / Partly / No with the privilege row (held / not held, struck through), then tabs. "Answer & diagram"
  (the old page: banner, combined diagram, paths, ownership, where to cut, ways to remove, closest, roles to ask for,
  what they see) is the default tab. "Routes & where to cut" (`show=routes`): one lane per distinct route, roles on
  every route marked as a place to cut; Where to cut with side effects (people who lose it, other privileges the user
  loses), Simulate (What if) and the revoke as SQL / Terraform / ticket; What they see with the USE ROLE snippet.
  "Nearest ways in" (`show=nearest`, No): reverse BFS from the object up the role graph, missing link dashed red,
  ranked by grants needed, then people who would also get it, then what else the role brings; too broad and rule 1
  warnings; Request (to screen 15) and What it brings (the role's access screen). "Rows & columns" (`show=layers`):
  1 Grant, 2 Rows, 3 Columns with result and reason (`data_view`); Partly when rows are none or columns masked.
  `do=read|change|own` picks the privilege; redirect `check&who=&what=` -> `name` / `obj`. The subject is a person
  (`name=`, `user=` redirects to it) or a role (`role=`; Request access: `for_role=`), picked from one list as on the
  Access screen; for a role the walks start at the role, cuts count the people holding it, nearest ways in grant a
  role to it (GRANT ROLE x TO ROLE y on Request access) with the too broad and rule 1 warnings.
  `access.py`: `lanes`, `cut_points`, `reverse`, `brings`, `nearest`, `basic_priv`, `need_privs`, `approver`
  (`OWNER_TAGS`, the fake data has an OWNER tag on HR.PEOPLE), `suggest`.
- **Screen 15, Request access** (`request`, endpoint `/api/request`, new): object, Read it / Change it, suggested
  roles (smallest existing functional role first, holders, what else it brings, sensitive columns it shows), the
  role picked on Can they?, how long, approver (owner tag, else a blank field), reason; SQL / Terraform / ticket via
  `CodeOutput`; a commented skeleton for a new role when none fits (`newRoleOf`). Text only.
- **Screen 4, Access graph** (`graph`, endpoint `/api/map`): start from a Table / Role / Person (`table=` / `role=` /
  `user=`). "Role hierarchy, by depth" (the diagram of the person, role or object page) is the default tab; "Trace
  graph" (`show=trace`) is the new one: the existing React Flow + ELK graph, columns by shortest step, line colour by
  what the line ends up granting (read / write / own / use, admin bypass and account privileges red dotted), width by
  people flowing, same-path people stacked (`same=0` ungroups), admin people and roles (`admin=0`), PUBLIC built-ins
  folded (`builtin=1` unfolds), risky paths in red (`risky=1`: to an admin role or account privilege, via PUBLIC, read
  role that writes). A click (`sel=`) fades everything not through the box; the side panel lists people through it and
  what it leads to, with Open its page, What if removed?, Make it the start. `Graph.tsx` got `focus`, `hi` and `flow`.
  `access.py`: `access_graph`, `flow`, `steps`, `grants_out`, `step_of`, `top`.
- **Screen 7, What they see** (`see`, endpoint `/api/see`): "What they see · tables" (the old User / Role tabs What they
  see, Sensitive data they can see, Role usage, `part=`) is the default tab; "Column by column" (`show=cards`): the
  sentence, Only sensitive / All protected objects (`all=1`), one card per object with the rows chip and each column
  visible / masked with the reason from `data_view`, "Add masking →" (rule 6) when a sensitive column has no policy;
  role usage bars on the side. `access.py`: `seen`.
- **Screen 9, Compare** (`compare`, endpoint `/api/compare`, `a=`, `b=`, `scope=sensitive|all|db`, `db=`): counts only
  A / only B / both but different / same; "What each sees" (the old Sensitive data Compare two roles table, now for
  people too) is the default tab; "Differences" (`show=diff`): differences first, the same ones folded, Make B match A /
  Remove A's extras (`plan=`) as SQL / Terraform / ticket text, Simulate on What if. `access.py`: `compare`, `sees_text`.
- The Access screen has Show as graph, What they see and Compare with… next to Can they?. Redirects: `user|role&part=
  sees|sens|usage` -> `see`, `sensitive&a=&b=` (or `tab=compare`) -> `compare`, `see&name=` -> `user=`.
- What if simulates removals only, so a nearest way in (a grant) opens the role's access screen ("What it brings")
  instead of What if.
- **Screen 5, Risks & fixes** (`rules`): "Rule checks" (the old page: findings with severity tabs, Admin holders, Rules
  table) stays the default tab. "Risks & change plan" (`show=fixes`): severity tiles as filters (`sev=`), Admin holders
  tile to `object&preset=admin`, group by rule / person / object (`by=`); rule rows sorted by people affected with a bar;
  expanded: why it matters, findings with chain chips and **Add fix to plan** (a finding's `changes`, from
  `access.fix_changes(edges)`; findings without a grant to revoke show their fix text), See on the graph, Rule settings,
  Mute with a reason. Right panel **Change plan**: items, impact tiles (people lose, keep another way, findings fixed,
  new findings) and who loses what from `/api/whatif` (`access.what_if`, simulation only), SQL / Terraform / ticket via
  `CodeOutput`, Open full what-if. `access.py`: `fix_changes`, `finding_objects` (findings carry `changes`, `objects`).
- **Change plan store** (`web/src/pages/changeplan.ts`): module state + localStorage `ae-plan`, per viewer, every access
  in try/catch; the same plan on Risks & fixes and What if. Rules On/Off (`ae-rules-off`) and muted findings
  (`ae-muted`, with the reason) live there too, labelled "saved in this browser": they only hide findings on Risks &
  fixes and never change `access.py` results.
- **Screen 11, What if** (`whatif`): "Changes & impact tables" (the old page with its Users / Objects / Roles / Findings /
  Text to apply tabs, `changes=` in the URL) stays the default tab, with "Add to the change plan". "Change plan"
  (`show=plan`): one-line form [Revoke role | Drop role | Revoke privilege | Empty PUBLIC] [role] from [user or role]
  [Add to plan], plan chips, the sentence and seven impact tiles, Group by People / Objects / Roles / Findings (`by=`),
  people rows expand to Loses / Keeps through another path, CodeOutput and the CSV.
- **Screen 10, Rules** (`rules&show=list`): rules by area with severity counts; each rule #, name, severity, findings
  link (to Risks & fixes on that rule) and On/Off; expand What it checks / How to fix (`RULE_INFO`, all 23 filled).
- Redirects: `rulelist` -> `rules&show=list`, `risks` -> `rules&show=fixes`, `plan` -> `whatif&show=plan`.
- **Screen 6, Review & sign-off** (`review`, endpoint `/api/grid`): "Access review" (the old page: Sensitive objects /
  All tables, CSV) stays the default tab. "Review grid & sign-off" (`show=grid`): the sentence (people, admins,
  dormant or disabled), links to the catalog, Compare and Data flow; scope chips Sensitive data / Database X /
  Everything (`scope=`, `db=`), People only (`people=0` off), Only dormant / disabled (`stale=1`), Hide USAGE
  (`hideusage=0` off); people x objects grid, cell = ladder colour + word, hover = path and privileges; dormant /
  disabled / never logged in rows tinted with "Suggested: revoke"; Keep / Revoke per row (localStorage `ae-review`,
  per scope); footer decided count, revokes -> "Test revokes in the change plan" (the shared `ae-plan`, revoke each
  granted role on the paths from that user, then What if on the plan), Sign off downloads a CSV with the reviewer
  typed, the decisions and a UTC timestamp, in the browser. `object=&columns=privileges` is the Object Users x
  privileges grid (people x privileges of one object). `access.py`: `review_grid`, `grid_cell`, `GRID_MAX`.
- **Screen 8, Sensitive objects catalog** (`sensitive&show=catalog`): the old Sensitive objects / Who can read them /
  Compare two roles tabs stay, Sensitive objects the default; tab "Catalog": sentence, filters All / Not protected
  (a sensitive column without masking) / PII / identifiers / Confidential (`PII_TAGS`, `CONFIDENTIAL_TAGS`), rows
  object, tags, status Not protected / Partly / Protected / Whole object with "1 of 3 columns masked" or the row
  policy, column chips red (no masking) / green (masked), people who can read (+ admins), Who -> (screen 2). Most
  exposed first. `access.py`: `catalog`, `protection`.
- **Screen 16, Sensitive data flow** (`flow`, endpoint `/api/flow`, new, Admin group, hidden in My access): People
  (Active / Dormant or disabled / Admins / Service) -> the role they were granted -> sensitive object, own SVG and
  buttons (no new dependency); box height and line width = people; object subtitle red when columns are unmasked;
  a click follows a box (`sel=`, `sel=none` everyone): the people through it and only their own links, with the
  headline sentence and a panel (people, Who has access / Open the role, Review these people). Default selection:
  Dormant or disabled. Over 12 roles the smallest fold into "Other roles (N)". Linked from Home's data protection,
  the catalog, the Sensitive data page and the review grid. `access.py`: `sens_flow`, `flow_group`, `ADMIN_BOX`.
- Redirects: `catalog` -> `sensitive&show=catalog`, `dataflow` and `sensitive&show=flow` -> `flow`, `signoff` ->
  `review&show=grid`.

- **Screen 13, Granted vs used** (`usage`, endpoint `/api/usage`, Admin group): optional read of
  `ACCOUNT_USAGE.ACCESS_HISTORY`, aggregated per user, object, week and READ / WRITE over 180 days (`access.use_sql`,
  the same text in `SP_ACCESS_SNAPSHOT`), into the new table `TBL_ACCESS_OBJECT_USE` (`TBL_ACCESS_USAGE` already holds
  role / warehouse usage). A may-fail step: without Enterprise or `IMPORTED PRIVILEGES` the table stays empty and the
  note says UNAVAILABLE; `live()` reads it the same way; `fake()` has deterministic demo rows (`fake_use`) with unused
  grants. Screen: period 30 / 90 / 180 days (`days=`), one row per table or view reached: granted level, used level or
  Not used (capped at the granted level), weekly bars, last used, suggestion Keep / Remove INSERT never used / Remove
  all; "Trim to what is used: N grants" adds `revoke_priv` changes at the holding roles to the change plan store
  (ownership is never revoked); tab "Trim to what is used" (`show=trim`) with the revokes as SQL / Terraform / ticket
  text. EmptyState with the reason and the grant that enables it when there is no data. Linked from the Access screen
  (Granted vs used). `access.py`: `use_state`, `used_on`, `granted_used`, `weeks_of`.
- **Screen 14, What changed + watched questions** (`changes`, endpoint `/api/changes`, Admin group, hidden in My
  access): the current snapshot against the previous one, which `cache.py` keeps as `<name>.prev.pkl` in `.cache/`
  when a new run arrives (only locally, `CACHE_HOURS` > 0). Inside Snowflake, with no previous copy or with memory-only
  caching, an EmptyState says why. Fake mode compares with `fake_previous()`. `access.diff(prev)`: grants gained / lost
  with who gains or loses what (`loaded(prev)` rebuilds the previous lookups and restores them), people turned dormant
  or disabled, new and fixed findings (matched on rule, grantee, kind), `GRANTED_BY`. Filters All / Gained / Lost /
  New findings / Sensitive only; feed with + / − / ! / ✓ icons, sentence, impact, by, finding chips and a link.
  "Watched questions" (`show=watch`): Can [person] read [object]? / Who can read [object]? / Who holds admin roles?,
  saved in localStorage `ae-watch`, asked again through `/api/check` and `/api/who`, tagged New / Changed / No change
  against the answer on the previous run; Notify is text only, nothing is sent. A "History" tab (`show=history`) on
  the Access and Object screens shows the feed for that subject.
- Redirects: `history`, `diff` -> `changes`; `unused`, `used`, `access|user|role&show=usage` -> `usage`;
  `usage&name=` -> `user=`.

- **Phase 5, cleanup and consistency**: every row of `specs/old-to-new-map.md` has a destination, checked one by one in
  `web/src/pages/oldmap.test.ts`. Old pages stay as the default tabs; old sub-tabs are linkable with `part=` (User,
  Role, Object, Sensitive data, Rule checks, Access review, What if tables). New redirects: `me` -> My access on the
  Access screen (`mine()`), `object&by=path` -> `graph&table=`, `rules&tab=rules` -> `rules&show=list`, `review&scope=`
  -> the grid, `whatif&by=` -> the change plan, `see&only=sensitive|all`, `access&filter=` -> the One row per object tab
  with that chip. Switching to My access leaves the shared-only pages (Review, Data flow, What changed). Home: the
  shortcuts cover graph, compare, request, flow, usage and changes (only pages in the nav), and the search lists matching
  screens. `test_every_page` (test_server.py): every page key has a label, a group and an endpoint that answers, shared
  and (unless shared-only) mine; `test_pages` also opens React-only keys in the plain fallback, which show the User page.
  Below 1000px the menu row is only as tall as the menu. Removed: the unused `DEPTHS` export and an unused import.
  README: screens list, screenshots from `docs/img/redesign`, Data sources with ACCESS_HISTORY, the fallback note.
  Screenshots of every page, local and Streamlit, at 1500 and 780 px: no console errors, no page-wide horizontal scroll
  (wide tables, the flow diagram and graphs scroll inside their card).

- **Review fixes**: service users are never dormant or "suggested: revoke" on the new screens (`a.stale`: disabled, or
  a person dormant or never logged in, the same test as rules 8 and 16) in Sensitive data flow, the review grid and the
  Who has access counts. Access graph: no What if / Open its page on the drawn boxes (`ACCOUNT`, every object) and no
  What if on admin roles or PUBLIC. Risks: a click on the active severity tile shows every severity (`sev=all`). The
  Object screen's default person and Compare's default side exist (no 500 without users). What changed subjects are node
  ids (`a.uid` for users), so a user and a role with the same name keep their own History. test_perf takes the best of
  up to 3 runs. The plain Streamlit fallback says when a screen is in the React version only, instead of silently showing
  the User page. Home: each search hit has a one-line answer (`a.reach_counts`), warehouses are their own group, the
  shortcuts are filled with the first hit (or the default user), Tagged objects opens the catalog and Tables with row
  policies opens their list (`a.row_tables`). Access: recently viewed chips by the picker, Group by Schema / Type and a
  Name sort; the Access and Object screens add to Recently viewed. Object, Users x privileges links the review grid with
  privilege columns. Catalog, Granted vs used and the review grid use the list toolbar (search + CSV).

- **Plain Streamlit fallback removed** (not needed): `app.py` only runs the React app (`st_react.app`); the native pages
  (`ST_REACT=native`, and `ST_REACT=html`, which showed them too) are gone, and `ui.py` keeps only what `server.py`
  sends (tokens, help, type icons, privilege classes and order). `ST_REACT=html` now only says that the app needs the
  component. `test_pages` runs app.py for every page key, shared and mine, and checks that it hands the page to the
  component; the SVG lane graph tests went with `ui.lane_graph`, the graph inputs are still checked (`test_graph_inputs`).

## Not done, and why

- Rules On/Off and Mute are per browser (localStorage), not shared: a shared setting would need a store the app writes to.
- No Streamlit fallback without the React component: if an account blocks it, use the container runtime or the local version.
- The old pages stay the default tab of each new screen (the user's choice), so the brief's "Replaces" column is met one
  tab away.
- Nearest ways in has no grant simulation: What if simulates removals only; the row shows who holds the role today and
  what else it brings, and What it brings opens the role.
- CLAUDE.md's `.cache/` rule does not mention `<key>.prev.pkl` yet (README does); an agent may not edit CLAUDE.md.
- The company-term pre-commit hook could not run: `~/.company-terms.txt` is missing on this machine.

## Phases

1. Foundations: tokens, shell, shared components, redirect table. Old pages stay reachable under "Detail".
2. Answer screens: Home, A person or role, then object, Can they?, graph, what they see, compare.
3. Admin screens: Risks & fixes with change plan, What if, Review, Sensitive catalog, Rules, data flow (done).
4. New data: Granted vs used (ACCESS_HISTORY) and What changed (previous snapshot in `.cache/`) (done).
5. Cleanup and consistency (done). The old pages were kept, not removed: the user wants their diagrams and tables, so
   they are the default tabs of the new screens and stay under Detail (User paths, Role paths).

## What is left

- README.html (the full guide) still describes the earlier pages; regenerate its generated parts with
  `python docs/make_readme.py` and rewrite its screen sections at the end of the redesign.
- Rules On/Off, Mute, review decisions and watched questions are per browser.
