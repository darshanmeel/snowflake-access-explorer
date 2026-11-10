# Graph input (rollup and summary)

`graph_input()` turns a user's or role's grants into lanes and edges for the React graph, rolling objects up over `MAX_OBJECTS`; `summary()` folds big role graphs.

```mermaid
flowchart TD
  IG["server.input_graph<br/>server.py:618-636"] --> GI["a.graph_input<br/>access.py:2886-2976"]
  GI --> LV{"objects > MAX_OBJECTS (12)?"}
  LV -- no --> OBJ[level object]
  LV -- yes --> SC["level schema<br/>(database if schemas > 12)"]
  IG --> TB{"too_big(g)?<br/>access.py:2982-2993"}
  TB -- "yes, not full" --> SU["a.summary(g)<br/>access.py:2996-3051"]
  TB -- "no / full=1" --> RAW[graph as is]
```

## graph_input (`access.py:2886-2976`)
- Rows = `grants(start)` minus USAGE on DATABASE/SCHEMA (unless `cat`) (`access.py:2901-2904`).
- Level: `object` if <= `max_objects` or `otype`; with `schema` a database -> its schemas, a schema -> object types; else `schema` if schemas <= max, else `database` (`access.py:2909-2916`).
- `MAX_OBJECTS = 12`, matches `graphs.ts` `MAX_BOXES` (`access.py:2883`, `web/src/components/graphs.ts:4`).
- Object level paths per object; grouped levels list paths once per holder (`access.py:2927-2930`); roles leading to no object still shown (`access.py:2931-2932`).
- Lanes: start, one lane per shortest depth (`by_depth`, `Depth {}`), then objects/groups (`access.py:2934-2942`).
- Group edges carry object count `(holder, group, cls, privilege, n)` (`access.py:2952`).
- Built-in fold box under PUBLIC (`access.py:2953-2956`, `2968-2972`).
- Returns lanes, edges, notes, info, kinds, header, level, shown, total, groups, types (`access.py:2973-2976`).
- Example (fake, verified): `graph_input("ANALYST_01", user=True)` -> header `6 objects`, level `object`, lanes User 1, Depth 1-3 (2 each), Objects 7 (incl. built-in box), `too_big` False.

## summary (`access.py:2979-3051`)
- `SUMMARY_ROLES, SUMMARY_LANES = 30, 6` (`access.py:2979`).
- `too_big(g)`: role boxes > 30 or role lanes > 6, a run of 3+ single-role lanes counted as one (`access.py:2982-2993`).
- Layout: start -> granted roles -> one `⋯ N roles ⋯` fold box per granted role -> grant holders -> objects/groups (`access.py:2996-3000`, `3048-3049`).
- Ranked by objects reached; fold boxes only for the first 12 granted roles (`access.py:3022-3024`, `3033`).
- Holders picked round-robin so every object/group keeps a line (`access.py:3029-3031`).
- Returns `kinds[fold] = "fold"`, `folded` = hidden role count (`access.py:3050-3051`).
- Server: `full=1` skips the summary with note "Full chain of a big graph." (`server.py:627-635`).
- No fake user triggers the summary (checked all users: `too_big` False) - example only via `test_summary` (`test_access.py:1343`), not opened.
- Tests: `test_graph_inputs` (`test_access.py:1324`), `test_summary` (`test_access.py:1343`).
