"""The React app (web/dist-st, built by `npm run build:st`) as one Streamlit component, for app.py locally and in
Streamlit in Snowflake. app() runs every page: the app's API calls come back as the component value and answer()
answers them with server.py, as the local server would, so both versions show the same pages."""
import json
import os
import threading
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
        if name == "progress":
            return 200, server.progress(p.get("view")), sid
        if name == "reload":
            return 200, server.reload(body), sid
        if name == "mine/load":
            new = os.urandom(16).hex()
            out = server.clean(server.load_mine(new, p.get("fresh") == "1"))
            server.MINE.pop(sid, None)  # as the local server's mine_load: the previous data set is not kept
            return 200, out, new
        if name.endswith(".csv") and name[:-4] in server.CSV:
            return 200, server.serve_csv(name[:-4], p, sid)[1], sid
        if name in server.ROUTES:
            return 200, server.serve(name, p, sid), sid
        return 404, {"detail": "not_found", "message": "No such endpoint."}, sid
    except server.ApiError as x:
        return x.status, {"detail": x.detail, "message": x.message}, sid
    except Exception as x:  # shown in the page like any API error
        return 500, {"detail": "error", "message": f"{type(x).__name__}: {x}"}, sid


def shown(box, r, sid):
    """answer() in a thread while this script thread writes the lines of a load it starts (server.progress) into box,
    about once a second: Python is busy during the load, so the frame cannot ask for them as the local version does.
    The thread is kept in the session: a rerun meanwhile waits for it instead of reading Snowflake a second time.
    to verify: inside Snowflake, the app's session (sf.connect) is used from this thread as from each()'s threads."""
    import server
    runs = st.session_state.setdefault("_ae_running", {})
    if r["id"] not in runs:
        out = []
        t = threading.Thread(target=lambda: out.append(answer(r["method"], r["url"], r.get("body"), sid)), daemon=True)
        t.start()
        runs[r["id"]] = t, out
    t, out = runs[r["id"]]
    drawn = None  # the last line drawn
    while t.is_alive():
        t.join(1)
        lines = server.progress()["lines"]
        if lines and lines[-1] != drawn:
            drawn = lines[-1]
            box.code("Reading Snowflake: what the app is doing\n" + "\n".join(
                f"{x['t']:7.1f} s  {x['text']}" for x in lines[-40:]), language=None)
    if drawn:
        box.empty()
    runs.pop(r["id"], None)
    return out[0] if out else (500, {"detail": "error", "message": "The request stopped without an answer."}, sid)


def app(key="app"):
    """The whole React app (web/src/App.tsx) as one component: its API calls come back as the component value and are
    answered here with server.py, so both versions run the same pages. Returns once the page is drawn."""
    ss = st.session_state
    done = ss.setdefault("_ae_answers", {})
    now = st.query_params.to_dict()
    box = st.empty()  # a load's progress lines (shown()), above the app
    v = _comp(component="app", props={}, answers=done, query=urlencode(now), key=key, default=None)
    if not v:
        return
    ss[UP] = True
    reqs = v.get("requests") or []
    new = False
    for r in reqs:
        if r["id"] not in done:
            status, body, ss["_ae_sid"] = shown(box, r, ss.get("_ae_sid"))
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
