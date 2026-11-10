# Graph input (rollup and summary)

`graph_input()` turns a user's or role's grants into lanes and edges for the React graph, rolling objects up over `MAX_OBJECTS`; `summary()` folds big role graphs.

```mermaid
flowchart TD
  IG["server.input_graph<br/>server.py:622-640"] --> GI["a.graph_input<br/>access.py:2892-2982"]
  GI --> LV{"objects > MAX_OBJECTS (12)?"}
  LV -- no --> OBJ[level object]
  LV -- yes --> SC["level schema<br/>(database if schemas > 12)"]
  IG --> TB{"too_big(g)?<br/>access.py:2988-2999"}
  TB -- "yes, not full" --> SU["a.summary(g)<br/>access.py:3002-3057"]
  TB -- "no / full=1" --> RAW[graph as is]
```

## graph_input (`access.py:2892-2982`)
- Rows = `grants(start)` minus USAGE on DATABASE/SCHEMA (unless `cat`) (`access.py:2907-2910`).
- Level: `object` if <= `max_objects` or `otype`; with `schema` a database -> its schemas, a schema -> object types; else `schema` if schemas <= max, else `database` (`access.py:2915-2922`).
- `MAX_OBJECTS = 12`, matches `graphs.ts` `MAX_BOXES` (`access.py:2889`, `web/src/components/graphs.ts:4`).
- Object level paths per object; grouped levels list paths once per holder (`access.py:2933-2936`); roles leading to no object still shown (`access.py:2937-2938`).
- Lanes: start, one lane per shortest depth (`by_depth`, `Depth {}`), then objects/groups (`access.py:2940-2948`).
- Group edges carry object count `(holder, group, cls, privilege, n)` (`access.py:2958`).
- Built-in fold box under PUBLIC (`access.py:2959-2962`, `2968-2972`).
- Returns lanes, edges, notes, info, kinds, header, level, shown, total, groups, types (`access.py:2979-2982`).
- Example (fake, verified): `graph_input("ANALYST_01", user=True)` -> header `6 objects`, level `object`, lanes User 1, Depth 1-3 (2 each), Objects 7 (incl. built-in box), `too_big` False.

## summary (`access.py:2985-3057`)
- `SUMMARY_ROLES, SUMMARY_LANES = 30, 6` (`access.py:2985`).
- `too_big(g)`: role boxes > 30 or role lanes > 6, a run of 3+ single-role lanes counted as one (`access.py:2988-2999`).
- Layout: start -> granted roles -> one `⋯ N roles ⋯` fold box per granted role -> grant holders -> objects/groups (`access.py:3002-3006`, `3048-3049`).
- Ranked by objects reached; fold boxes only for the first 12 granted roles (`access.py:3028-3030`, `3033`).
- Holders picked round-robin so every object/group keeps a line (`access.py:3035-3037`).
- Returns `kinds[fold] = "fold"`, `folded` = hidden role count (`access.py:3056-3057`).
- Server: `full=1` skips the summary with note "Full chain of a big graph." (`server.py:631-639`).
- No fake user triggers the summary (checked all users: `too_big` False) - example only via `test_summary` (`test_access.py:1370`), not opened.
- Tests: `test_graph_inputs` (`test_access.py:1351`), `test_summary` (`test_access.py:1370`).
