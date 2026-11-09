# The React app in Streamlit (st_react.py)

The same React app as the local web version, packaged as one Streamlit component for app.py and Streamlit in
Snowflake (SiS). `app.py` only calls `st_react.app()`: the whole app (`web/src/App.tsx`) runs in the component, its API
calls come back as the component value and are answered in Python by `server.py`. There are no plain Streamlit pages
and no other components.

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

## How the app talks to Python

- Every API call of the app becomes a request in the component value (all open requests each time, ids with a
  per-load prefix). `st_react.app()` answers them with `st_react.answer()` (the same `server.py` functions the local
  server calls), sends the answers back in the next render and reruns.
- The page's query string goes to the frame URL-encoded (`urlencode`) and comes back as the frame's own URL; Python
  compares the decoded parameters, so names with `&`, `+`, `#` or spaces survive a shared link.
- Until the component sends its first value, `app.py` shows a hint ("If this message stays, the React component did not
  load"), so a blocked component or a missing `web/dist-st` is not a blank page.

## What works in SiS

| | Warehouse runtime (Streamlit 1.22 to 1.52) |
|---|---|
| `declare_component(path=web/dist-st)`, values back to Python | Preview, announced Aug 2025 but not confirmed in the docs. **Test first.** |
| Fonts (bundled woff2) | yes with `path=` |
| CSV download inside the component (blob URL) | unknown: blob URLs are not documented |
| ELK layout | main thread, no worker, no eval in the bundle |

- `sql/4_streamlit.sql` creates a warehouse-runtime app only. If the component is blocked there, the app can't run in
  Snowflake: use the local version (or a shared server, README > On a shared server).
- Streamlit 1.56 warns that Components v1 will change. The warehouse runtime only goes up to 1.52, which is what
  `environment.yml` pins.

## Test before building on it

1. Deploy (`sql/4_streamlit.sql`) and open the app in Snowsight.
2. The hint must go away and Home must show data; click a few pages and a graph node.
3. Check the browser console for CSP errors (ELK, fonts, blob CSV).
4. If the hint stays, the component is blocked on the warehouse runtime: use the local version.

## SiS packaging: files to upload

`sql/4_streamlit.sql` uploads these to the stage used by `CREATE STREAMLIT ... FROM` (`test_sis_upload` checks the
list against what `app.py` imports). Files are copied when the app is created, so run it again after each change.
`MAIN_FILE` must be at the root.

```
app.py              MAIN_FILE
access.py
cache.py
server.py           (answers the app's API calls; FastAPI is imported only when it runs as the local server)
sf.py
st_react.py
ui.py               (theme tokens, help texts, type icons: sent in /api/meta)
environment.yml     warehouse runtime: channel snowflake, streamlit=1.52.* pinned, snowflake-snowpark-python
sis/.env            the app's .env (INSIDE=1, SOURCE=objects, ACCESS_SNAPSHOT)
web/dist-st/index.html
web/dist-st/assets/*.js, *.css, *.woff2
```

- Do not upload `web/src`, `web/node_modules`, `web/dist`, `.env`, `.streamlit/` or `settings.local.sql`.
- `st_react.py` finds the bundle at `<folder of st_react.py>/web/dist-st`, so keep that layout.
- The asset names contain a hash: the script removes the old `assets/` files before it uploads the new ones
  (`CLEAR_WEB_ASSETS`), and `4_streamlit_verify.sql` expects exactly 4.
