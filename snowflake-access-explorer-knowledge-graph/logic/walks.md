# Walks (paths, depth, counting)

How `access.py` finds every route from a user or role to a grant: counted exactly, shortest by BFS, listed lazily up to `MAX_PATHS`.

```mermaid
flowchart TD
  ST["starts(name,user)<br/>access.py:1411-1423"] --> FA["fast()<br/>1595-1600"]
  FA --> DAG["dag(): drop loop-closing links<br/>1453-1475"]
  FA --> CNT["counts(): paths per role<br/>1525-1546"]
  DAG --> SH["shortest(): BFS<br/>1549-1561"]
  DAG --> LI["listed(): up to MAX_PATHS<br/>1564-1592"]
  FA --> TA["tally() to grant holders<br/>1626-1639"]
  TA --> CAN["can()<br/>3245-3278"]
  TA --> REM["removal()<br/>3179-3204"]
  TA --> CUT["cut_points()<br/>3293-3314"]
  UW["up_walk(): walk up<br/>1727-1759"] --> WU["who_users()<br/>1955-1973"]
  UW --> HE["held()<br/>2631-2646"]
  UW --> R19["rule19 / admin_holders"]
  RW["reach_without()<br/>1698-1712"] --> LO["loses()<br/>2649-2651"]
  RW --> LS["losers()<br/>3165-3176"]
```

## Graph model
- Lookups filled by `build()`: `holds` (role -> child roles), `held_by` (child -> parents), `users_of`, `roles_of`, `granted` (role -> grants), `on` (object -> holders) (`access.py:935-943`).
- Walk down = parent -> roles it holds; walk up = holder -> grantees.

## Depth
- Depth = roles from the start to the grant holder, holder included; a user is not a role (`depth()`, `access.py:1432-1436`).
- Example (verified on fake data): `ANALYST_01 > GRP_ANALYSTS > F_ANALYST > T_SALES_CORE_READ` -> depth 3; a holder alone = 1.
- Same definition on every page (docstring `access.py:1434-1435`); `held()` rows: user direct = 1, role direct = 2 (`access.py:2638-2639`).

## Start paths
- Role: `[[role]]`; user: `[user, r]` per granted role, plus `[user, PUBLIC]` (every user holds PUBLIC) (`access.py:1411-1423`).
- `default_only`: one start, shortest path to `DEFAULT_ROLE` (only that role is in session) (`access.py:1418-1421`).

## Counting vs listing
- `counts()`: path count per role layer by layer, no enumeration (`access.py:1525-1546`).
- `tally()`: total paths to holders = sum(count(holder) x grant rows); `down[r]` = paths from r to a holder (`access.py:1629-1642`).
- `via_role` / `via_link`: paths through a role / a link, counted (`access.py:1645-1657`); a link used by every path = choke point.
- `listed()`: chains in `down()` order, pruned to roles that lead to a target, at most `cap` = `MAX_PATHS` (`access.py:1567-1595`). A chain only refuses roles already on it after the start's first element (`go(p, i)`, `r not in p[i:]`, `access.py:1588-1589`): for a user start `[user, role, ...]` `i = 1`, so a role named like the user is not taken for the user (`access.py:1592-1594`).
- `MAX_PATHS` default 200, "counts are always exact" (`access.py:72`); note text "first 200 of N" from `paths_note()` (`access.py:1613-1615`).
- `capped_paths()`: shortest first; the shortest path always kept when cut (`access.py:1606-1610`).
- Full listings `access_of()` / `who_can()` (via `walk`/`down`/`up`) remain as reference for TF_ACCESS_OF / TF_WHO_CAN parity (`access.py:1897-1899`, `1981-1985`) - inferred from commit 6330f29 message; code is verified.

## Shortest (BFS)
- `bfs(path)`: shortest path to every role held (`access.py:1371-1382`); `shortest()` same over `dag` links with hop cap (`access.py:1549-1564`); starts are sorted by length and a longer start (a default role's route) joins the BFS only at its own hop, so a shorter route found meanwhile wins (`access.py:1552-1556`); `paths_from()` BFS without hop cap (`access.py:3916-3926`).
- `first_short()`: first of the shortest paths in `down()` order (`access.py:1660-1681`).

## Cycle guard
- `down()` / `up()` skip roles already on the path (`access.py:1352`, `1362`).
- `dag()`: DFS, drops back edges (links closing a loop) (`access.py:1453-1475`).
- `loops()`: Tarjan SCC, lists role loops so the app can warn (`access.py:1478-1518`); `paths_to()` lists over every link when loops exist (`access.py:1690-1691`). Fake data: no loops (verified).
- `MAX_HOPS` (50) caps any walk; capped starts recorded in `capped` (`access.py:53`, `1335-1342`, `1543-1544`).

## Users vs roles namespaces
- A user named like a role gets graph id `name + " (user)"` (`UTAG`, `uid()`, `access.py:1009-1014`); `node_kind` / `node_name` resolve it (`access.py:1017-1026`).
- `down(..., user=True)` lets a role with the user's name appear on the path (`access.py:1352`); `up()` ends a path with `uid(u, True)` (`access.py:1368`).

## Walk up
- `up_walk(srcs, hops, user_hops)`: rows `{(name, is_user): (count, shortest up path)}`, `paths(key)` lazily (`access.py:1730-1762`). PUBLIC is held by every user (`users_on`, `access.py:1725-1727`).
- `up_only_via()`: every up path passes through a role (reach without it) (`access.py:1765-1778`).
- `up_rows(r)`: cached `up_walk([r])["rows"]` (`access.py:1948-1950`); `ups(role)`: reach only (roles, users) (`access.py:1390-1403`).
- `who_users(obj)`: `{(user, privilege): path, firsts, count}` counted, not listed (`access.py:1961-1979`). Example: `('ENGINEER_01','SELECT')` on SALES.CORE.TBL_CUSTOMER -> count 3, shortest `ENGINEER_01 > F_ANALYST > T_SALES_CORE_READ`, firsts `F_ANALYST, F_ENGINEER`.
- `held(role)`: grantees with depth, count, `only_via` (`access.py:2637-2652`).

## Page walks
- `can(user, priv, obj)`: paths (<= MAX_PATHS), exact `count`, `shortest`, `choke` (roles on every path), `owner` paths, `options` = `removal()`, `ask` / `closest` when no path (`access.py:3267-3300`).
  Example: `can("ANALYST_01","SELECT","SALES.CORE.TBL_CUSTOMER")` -> count 1, shortest 3, choke `[GRP_ANALYSTS, F_ANALYST, T_SALES_CORE_READ]`.
- `removal()`: one option per choke grant edge, fewest users losing it first (`access.py:3201-3226`). Example first option: `REVOKE ROLE GRP_ANALYSTS FROM USER ANALYST_01;` affects 1.
- `cut_points()`: per link on every path: `people` who lose it, `lost` other privileges (`access.py:3315-3336`). Example: revoking `GRP_ANALYSTS` from ANALYST_01 -> people `[ANALYST_01]`, lost 9.
- `loses(user, grantee, role)`: `(privilege, object)` lost when role is revoked from grantee (`access.py:2655-2657`). Example `loses("ANALYST_01","GRP_ANALYSTS","F_ANALYST")` starts `('SELECT','SALES.CORE.<TABLE>'), ('SELECT','SALES.CORE.TBL_CUSTOMER'), ...`.
- `lose(e)` / `losing(e)`: users who lose access when one edge goes, cached per edge (`access.py:3167-3184`); `losers()` for several edges (`access.py:3187-3198`).
- Tests: `test_counted` (`test_access.py:869`), `test_perf` (`test_access.py:1115`).
