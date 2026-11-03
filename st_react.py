"""React components (web/dist-st, built by `npm run build:st`) inside Streamlit and Streamlit in Snowflake.

Each function draws one component and returns the click as a dict, or None:
  {"id": <node id or name>, "name": <user/role/object name>, "kind": <NodeKind or None>, "action": <NodeAction or None>, "row": <table row, tables only>}
params(click) turns it into query params; the caller does st.query_params.update(...) and st.rerun().

MODE (env ST_REACT, default "component"):
  component  bidirectional v1 component from web/dist-st (declare_component(path=...)); clicks come back.
  html       fallback when SiS blocks path= components: the bundle inlined into st.components.v1.html,
             display only (always returns None), navigation stays in native Streamlit widgets.
"""
import json
import os
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

DIST = Path(__file__).parent / "web" / "dist-st"
MODE = os.environ.get("ST_REACT", "component")
_comp = components.declare_component("access_ui", path=str(DIST)) if MODE == "component" else None


def _js(obj):
    # "</" would end the inline <script>; "<\/" reads the same in JSON and JS
    return json.dumps(obj, default=str).replace("</", "<\\/")


def _inline(args, height):
    js = "".join(p.read_text(encoding="utf-8") for p in sorted((DIST / "assets").glob("*.js")))
    css = "".join(p.read_text(encoding="utf-8") for p in sorted((DIST / "assets").glob("*.css")))
    js = js.replace("</script", "<\\/script")
    page = (f"<!doctype html><html><head><meta charset='utf-8'><style>body{{margin:0}}{css}</style></head><body>"
            f"<div id='root'></div><script>window.__AE_ARGS__={_js(args)}</script>"
            f"<script type='module'>{js}</script></body></html>")
    components.html(page, height=height, scrolling=True)


def _show(component, props, key, theme=None, height=600):
    args = {"component": component, "props": json.loads(_js(props)), "theme": theme}
    if _comp is None:
        _inline(args, height)
        return None
    v = _comp(**args, key=key, default=None)
    # the value stays set across reruns: report each click once (by its nonce)
    seen = st.session_state.setdefault("_st_react_seen", {})
    if not v or seen.get(key) == v.get("nonce"):
        return None
    seen[key] = v.get("nonce")
    return v


def graph(data, key, theme=None, legend=True, max_height=640):
    """data: Graph JSON (web/src/api/types.ts). Combined boxes expand inside the component; other clicks return."""
    return _show("graph", {"graph": data, "legend": legend, "maxHeight": max_height}, key, theme, max_height + 80)


def privilege_tabs(rows, key, roles=None, account=None, refs=None, tabs=None, graphs=None, theme=None, csv_name=None):
    """rows: PrivRow list; roles: ReachRow list; account / refs / tabs / graphs as in web/API.md."""
    props = {"rows": rows, "roles": roles or [], "account": account, "refs": refs, "tabs": tabs, "graphs": graphs,
             "csvName": csv_name}
    return _show("privileges", {k: v for k, v in props.items() if v is not None}, key, theme, 900)


def table(df, key, link=None, numeric=(), wrap=None, csv="table.csv", refs=None, theme=None, max_height=520):
    """df: pandas DataFrame or list of dicts. link: column whose value is a user/role/object name; a click on such a
    row returns {"id": value, "row": {...}}. numeric: right-aligned columns; wrap: {column: "wrap"|"truncate"|"nowrap"}."""
    rows = json.loads(df.to_json(orient="records", date_format="iso")) if hasattr(df, "to_json") else list(df)
    names = list(df.columns) if hasattr(df, "columns") else list(rows[0]) if rows else []
    cols = [{"key": c, "label": c, "num": c in numeric, "wrap": (wrap or {}).get(c)} for c in names]
    props = {"columns": cols, "rows": rows, "link": link, "csv": csv, "refs": refs, "maxHeight": max_height}
    return _show("table", props, key, theme, max_height + 60)


def chips(items, key, max_shown=12, theme=None):
    """items: [{"id", "label"?, "kind"?, "title"?, "tone"?}]; a click returns that chip's id and kind."""
    return _show("chips", {"items": items, "max": max_shown}, key, theme, 120)


def params(click):
    """Query params for a click (same pages and keys as app.py's links)."""
    act = click.get("action") or {}
    k = act.get("kind")
    if k == "page":
        return {"page": act["page"], **act.get("params", {})}
    if k == "drill":
        return {"schema": act["schema"]}
    if k == "otype":
        return {"otype": act["otype"]}
    if k == "full":
        return {"full": "1"}
    if k == "expand":
        return {"expand": act["group"]}
    kind = click.get("kind")
    return {"page": "user" if kind == "user" else "object" if kind == "object" else "role", "name": click.get("name") or click["id"]}
