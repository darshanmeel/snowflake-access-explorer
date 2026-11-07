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
| Streamlit | `app.py` + `st_react.py` | Default: the React app as one component, API calls answered by `server.py` in Python. `ST_REACT=native` keeps the plain Streamlit pages (`app.py` + `ui.py`) as a fallback. |
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
- New screens as page keys: `home` (0) and `access` (1, a person or a role). Next: Can they? (3 and 12),
  graph (4), what they see (7), compare (9), then the admin screens.

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

## Not done, and why

- Granted vs used (13) needs `ACCESS_HISTORY`, What changed (14) needs dated snapshots kept. Both add new reads and stored
  data next to the `TBL_ACCESS_` tables, which CLAUDE.md limits; they need a decision first.
- Rules On/Off (10) would need a settings store; the app writes nothing today.
- The plain Streamlit fallback (`ST_REACT=native`) keeps its current pages; the default Streamlit mode runs the React app and gets every new screen.

## Phases

1. Foundations: tokens, shell, shared components, redirect table. Old pages stay reachable under "Detail".
2. Answer screens: Home, A person or role, then object, Can they?, graph, what they see, compare.
3. Admin screens: Risks & fixes with change plan, What if, Review, Sensitive catalog, Rules, data flow.
4. New data: needs the decision above.
5. Cleanup: remove the old pages once every tab has a destination and a redirect.
