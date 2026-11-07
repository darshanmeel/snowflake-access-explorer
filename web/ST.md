# React components in Streamlit (st_react.py)

The same React app as the local web version, packaged as one Streamlit component for app.py and Streamlit in
Snowflake (SiS). `app.py` only calls `st_react.app()`: the whole app (`web/src/App.tsx`) runs in the component, its API
calls come back as the component value and are answered in Python by `server.py`. There are no plain Streamlit pages.
The single components below (`graph`, `table`, ...) stay available for other Streamlit apps.

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
- `params(click)` maps the click to the same query keys the app uses: node actions `page` (page plus its params),
  `drill` (`schema`), `otype`, `full` and `expand`. A plain name opens the user, object or role page.
- Combined boxes (schema, database or type groups, folded role lanes) expand inside the component and send nothing.
- `theme=`: `"light"` or `"dark"`. When it is left out, the component follows Streamlit's theme.
- Data must be JSON, the same shapes as `web/API.md`. Build it with the same producer functions server.py uses, so
  both versions keep one logic.

## What works in SiS

| | Warehouse runtime (Streamlit 1.22 to 1.52) | Container runtime (1.50+) |
|---|---|---|
| `declare_component(path=web/dist-st)`, clicks back to Python | Preview, announced Aug 2025 but not confirmed in the docs. **Test first.** | expected to work |
| `ST_REACT=html` (`components.v1.html`, bundle inlined) | works for the single components, display only; not for `app()` | same |
| Fonts (bundled woff2) | yes with `path=`. Inlined: the font URLs do not resolve, so the system mono font is used | same |
| CSV button inside the component (blob URL) | unknown: blob URLs are not documented. Keep `st.download_button` | unknown |
| ELK layout | main thread, no worker, no eval in the bundle | same |

- **html switch:** env var `ST_REACT=html`, or set `st_react.MODE = "html"` before the first call. Every single
  component then returns `None`. `app()` can't run that way (its API calls never reach Python), so app.py then only
  says that it needs the component. The bundle
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
4. If it fails on the warehouse runtime, the app can't run there: use the container runtime or the local version.

## SiS packaging: files to upload

Upload to the stage or git path used by `CREATE STREAMLIT ... FROM`. Files are copied when the app is created, so
recreate or redeploy after each change. `MAIN_FILE` must be at the root.

```
app.py              MAIN_FILE
access.py
cache.py
server.py           (answers the app's API calls; FastAPI is imported only when it runs as the local server)
sf.py
st_react.py
ui.py               (theme tokens, help texts, type icons: sent in /api/meta)
environment.yml     warehouse runtime: channels [snowflake], streamlit and pandas pinned with "="
web/dist-st/index.html
web/dist-st/assets/*.js, *.css, *.woff2
```

- Do not upload `web/src`, `web/node_modules`, `web/dist`, `.env` or `settings.local.sql` (`sis/.env` is the app's `.env`).
- `st_react.py` finds the bundle at `<folder of st_react.py>/web/dist-st`, so keep that layout.
- Rebuild (`npm run build:st`) and upload `dist-st` again whenever a component changes. The asset names contain a
  hash, so remove the old `assets/` files first; otherwise `ST_REACT=html` would also inline the stale ones.
