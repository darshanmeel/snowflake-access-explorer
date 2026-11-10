"""The React app (web/dist-st, built by `npm run build:st`) as one Streamlit component, for app.py locally and in
Streamlit in Snowflake. app() runs every page: the app's API calls come back as the component value and answer()
answers them with server.py, as the local server would, so both versions show the same pages."""
import json
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

import streamlit as st
import streamlit.components.v1 as components

DIST = Path(__file__).parent / "web" / "dist-st"
_comp = components.declare_component("access_ui", path=str(DIST))
UP = "_ae_up"  # session key: the component has talked back once (app.py then drops its "blocked?" hint)


def _js(obj):
    # "</" would end an inline <script>; "<\/" reads the same in JSON and JS
    return json.dumps(obj, default=str).replace("</", "<\\/")


def answer(method, url, body, sid):
    """One API call of the React app, answered by server.py as the local server would: (status, body, sid)."""
    import server
    path, _, q = url.partition("?")
    name = path.removeprefix("/api/")
    p = dict(parse_qsl(q))
    try:
        if name == "meta":
            return 200, server.meta(p, sid), sid
        if name == "mine":
            return 200, server.mine_state(sid), sid
        if name == "reload":
            return 200, server.reload(body), sid
        if name == "mine/load":
            new = os.urandom(16).hex()
            out = server.clean(server.load_mine(new, p.get("fresh") == "1"))
            server.MINE.pop(sid, None)  # as the local server's mine_load: the previous data set is not kept
            return 200, out, new
        if name.endswith(".csv"):
            return 200, server.serve_csv(name[:-4], p, sid)[1], sid
        if name in server.ROUTES:
            return 200, server.serve(name, p, sid), sid
        return 404, {"detail": "not_found", "message": "No such endpoint."}, sid
    except server.ApiError as x:
        return x.status, {"detail": x.detail, "message": x.message}, sid
    except Exception as x:  # shown in the page like any API error
        return 500, {"detail": "error", "message": f"{type(x).__name__}: {x}"}, sid


def app(key="app"):
    """The whole React app (web/src/App.tsx) as one component: its API calls come back as the component value and are
    answered here with server.py, so both versions run the same pages. Returns once the page is drawn."""
    ss = st.session_state
    done = ss.setdefault("_ae_answers", {})
    now = st.query_params.to_dict()
    v = _comp(component="app", props={}, answers=done, query=urlencode(now), key=key, default=None)
    if not v:
        return
    ss[UP] = True
    reqs = v.get("requests") or []
    new = False
    for r in reqs:
        if r["id"] not in done:
            status, body, ss["_ae_sid"] = answer(r["method"], r["url"], r.get("body"), ss.get("_ae_sid"))
            done[r["id"]] = {"status": status, "body": json.loads(_js(body))}
            new = True
    open_ids = {r["id"] for r in reqs}
    for k in [k for k in done if k not in open_ids]:
        del done[k]  # answered and received: the frame no longer asks for it
    url = dict(parse_qsl((v.get("url") or "").lstrip("?")))
    if url and url != now:
        st.query_params.from_dict(url)
    if new:
        st.rerun()
