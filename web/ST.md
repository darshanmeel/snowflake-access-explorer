# React components in Streamlit (st_react.py)

The same React components as the local web version, packaged as one Streamlit component for app.py and
Streamlit in Snowflake (SiS). Not wired into app.py yet; this is the plan for that step.

## Build

```
cd web
npm run build:st        # -> web/dist-st/index.html + assets/ (one JS, one CSS, two fonts)
```

- Entry: `web/st/index.html` -> `web/src/st/main.tsx`. Protocol: `web/src/st/protocol.ts`, the Streamlit v1
  component messages written by hand (`componentReady`, `render`, `setComponentValue`, `setFrameHeight`), so there is no
  `streamlit-component-lib` dependency.
- Relative paths, no CDN, no worker (ELK from `elk.bundled.js`), no `eval`, no `data:` assets.
- `web/dist-st/` is committed: SiS cannot run npm.

## Python API

```python
import st_react

click = st_react.graph(graph_json, key="g")                  # Graph JSON, as server.py sends it
click = st_react.privilege_tabs(rows, key="p", roles=reach, account=acct, refs=refs)
click = st_react.table(df, key="t", link="Role", numeric={"Paths"}, wrap={"Path": "truncate"})
click = st_react.chips([{"id": "F_SALES", "kind": "functional"}], key="c")
if click:
    st.query_params.update(st_react.params(click))
    st.rerun()
```

- A click returns `{"id", "name", "kind", "action", "row"?}`, once. The component keeps its value across reruns, so
  `st_react` drops a nonce it has already returned (in `st.session_state["_st_react_seen"]`). Without that,
  `st.rerun()` would loop.
- `params(click)` maps the click to the same query keys app.py uses: node actions `page` (page plus its params),
  `drill` (`schema`), `otype`, `full` and `expand`. A plain name opens the user, object or role page.
- Combined boxes (schema, database or type groups, folded role lanes) expand inside the component and send nothing.
- `theme=`: `"light"` or `"dark"`. When it is left out, the component follows Streamlit's theme. Pass app.py's
  `THEME`, so the `?theme=` toggle is honoured.
- Data must be JSON, the same shapes as `web/API.md`. Build it with the same producer functions server.py uses, so
  both versions keep one logic.

## Which ui.py call each one replaces (combine step)

| app.py today | Replace with | Keep native |
|---|---|---|
| `graph_card()` -> `ui.legend()` + `ui.lane_graph()` + `ui.how()`, and the Fit / All rule hits toggles | `st_react.graph()` (legend, fit, zoom and expand are built in) | the card title |
| `priv_tabs()` (`st.tabs` per category + tables) | `st_react.privilege_tabs()` (Account ... All, with a diagram per tab) | |
| `table_card()` -> `ui.table()`, the 7 calls | `st_react.table()` | `st.download_button` "Export CSV" (see blob below) |
| chip lists built from `ui.chip()` (granted roles, holders, PUBLIC) | `st_react.chips()` | |
| `ui.mini_path()` in table cells | the Path column of `table()` / `privilege_tabs()` (`PathText`) | |
| `ui.banner`, `ui.kpi`, `ui.card`, `ui.answer`, `ui.header`, `ui.nav`, rule rows / map | unchanged | yes |

Links in `ui.lane_graph` are `<a href="?page=...">`. In SiS they reload the app inside Snowsight's iframe, and query keys
get a `streamlit-` prefix, so clicks coming back as values are the more reliable route there.

## What works in SiS

| | Warehouse runtime (Streamlit 1.22 to 1.52) | Container runtime (1.50+) |
|---|---|---|
| `declare_component(path=web/dist-st)`, clicks back to Python | Preview, announced Aug 2025 but not confirmed in the docs. **Test first.** | expected to work |
| Fallback `ST_REACT=html` (`components.v1.html`, bundle inlined) | works, display only | works, display only |
| Fonts (bundled woff2) | yes with `path=`. Inlined: the font URLs do not resolve, so the system mono font is used | same |
| CSV button inside the component (blob URL) | unknown: blob URLs are not documented. Keep `st.download_button` | unknown |
| ELK layout | main thread, no worker, no eval in the bundle | same |

- **Fallback switch:** env var `ST_REACT=html`, or set `st_react.MODE = "html"` before the first call. Every function
  then returns `None`, so navigation needs native widgets (selectbox, `st.dataframe(on_select=...)`). The bundle
  (about 1.8 MB) is sent again on every rerun, which is well under the 32 MB message limit.
- Streamlit 1.56 warns that `st.components.v1.html` will be replaced by `st.iframe`. The warehouse runtime only goes up
  to 1.52, so keep `components.v1.html` for now.
- If `path=` fails but the container runtime is available, Components v2 is the next option
  (`st.components.v2.component` with the JS and CSS inline). It needs an ES-module build that exports a default
  function; not built yet.

## Test before building on it

1. Deploy a small app that calls `st_react.graph()` on both runtimes.
2. Check that the component loads, that a node click reaches Python (`st.write(click)`), and that combined boxes expand.
3. Check the browser console for CSP errors (ELK, fonts, blob CSV).
4. If it fails on the warehouse runtime, set `ST_REACT=html` and check that the diagrams still draw.

## SiS packaging: files to upload

Upload to the stage or git path used by `CREATE STREAMLIT ... FROM`. Files are copied when the app is created, so
recreate or redeploy after each change. `MAIN_FILE` must be at the root.

```
app.py              MAIN_FILE
access.py
ui.py               (still used for banners, KPIs and nav)
st_react.py
sf.py               (only if app.py imports it on SiS)
environment.yml     warehouse runtime: channels [snowflake], streamlit and pandas pinned with "="
web/dist-st/index.html
web/dist-st/assets/*.js, *.css, *.woff2
```

- Do not upload `web/src`, `web/node_modules`, `web/dist`, `server.py`, `.env` or `settings.local.sql`.
- `st_react.py` finds the bundle at `<folder of st_react.py>/web/dist-st`, so keep that layout.
- Rebuild (`npm run build:st`) and upload `dist-st` again whenever a component changes. The asset names contain a
  hash, so remove the old `assets/` files first; otherwise the html fallback would also inline the stale ones.
