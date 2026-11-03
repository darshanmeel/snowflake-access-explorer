"""Snowflake access explorer. Run: streamlit run app.py
Data: FAKE=1 (default) fake data · DUCKDB=<file> fake data in DuckDB (make_demo_db.py), read with the snapshot SQL ·
FAKE=0 Snowflake via ../sf.py, as the logged-in user.
Page, entity and filters live in the URL (?page=role&name=...&depth=3), so chips and graph nodes are plain links."""
import csv
import importlib
import io
import json
import os
import pathlib
import sys
import threading
from datetime import datetime, timezone
from html import escape as e
from urllib.parse import urlencode

import streamlit as st

import access as a
import ui

DUCK = os.environ.get("DUCKDB")
MODE = "duckdb" if DUCK else "fake" if os.environ.get("FAKE", "1") != "0" else "snowflake"
WHERE = os.environ["ACCESS_SNAPSHOT"] if MODE == "snowflake" else "main"  # DB.SCHEMA of the tables
DEMO_USER = os.environ.get("DEMO_USER", "ENGINEER_01")  # "My access" without Snowflake, and the default user
# nav order; a page shows in the nav once it has a function in VIEW (sensitive and review come next)
PAGES = {"user": "User", "role": "Role", "object": "Object", "sensitive": "Sensitive data", "check": "Can they?",
         "rules": "Rule checks", "review": "Access review"}
VIEWS = {"shared": "Shared snapshot", "mine": "My access (live, only me)"}
DEPTHS = {"": "No limit (every level)", "1": "Up to depth 1", "3": "Up to depth 3", "5": "Up to depth 5",
          "10": "Up to depth 10"}
ROLES = {"all": "All granted roles", "default": "Default role only"}
KIND = {"functional": "Functional role", "technical": "Technical role", "group": "Group role", "admin": "Admin role",
        "object": "Object"}
SEVS = ["High", "Medium", "Low"]
HEAD = {
    "user": ("User access", "What can this user reach — through every role, at any depth?",
             "Walks the full role hierarchy from the user down to every grant, so access inherited ten roles deep "
             "shows up next to direct grants, along with the path that gives it."),
    "role": ("Role", "Who holds this role, and what does it hold?",
             "Upward, every role and user that inherits it, however many levels away. Downward, the roles it holds "
             "and every privilege it carries to objects."),
    "object": ("Object", "Who can touch this object, and how?",
               "Starts at the object and walks up from every role that holds a grant on it to the users at the end "
               "of each chain."),
    "sensitive": ("Sensitive data", "Which objects hold sensitive data, and who can read them?",
                  "Objects carrying a sensitive tag (on a column, the table, its schema or database), the people and "
                  "roles that can read them, and whether the columns are masked. Masking comes from the policy text, "
                  "not evaluated by Snowflake."),
    "check": ("Can they?", "One user, one object, one privilege — every way it is granted.", ""),
    "rules": ("Rule checks", "Where the role model breaks its own rules",
              "Rules of the layered role model, sensitive data and dormant users. Rule 4 allows OWNER roles for "
              + ", ".join(f"<code>{e(b)}</code>" for b in a.BUILD) + "."),
    "review": ("Access review", "Who can reach what in one database, for sign-off",
               "One row per user and object with every privilege, the granted roles and the shortest path, plus one "
               "row per admin user. Export the CSV and fill in Reviewer and Keep/Revoke."),
}
THEME, VIEW_MODE, ROWS, SENS, BREAKS = "light", "shared", [], {}, {}


# ---------- data ----------

def connect():  # one connection per load: a cached one expires when idle
    if DUCK:
        import duckdb
        return duckdb.connect(DUCK, read_only=True)
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from sf import connect as sf
    return sf()


def with_query(fn):
    """fn(query) with query(sql) -> list of dicts, on a fresh connection."""
    conn = connect()

    def query(sql):
        cur = conn.cursor()
        cur.execute(sql)
        cols = [c[0] for c in cur.description or []]
        return [dict(zip(cols, r)) for r in cur.fetchall()] if cols else []

    try:
        return fn(query)
    finally:
        conn.close()


@st.cache_data(ttl=3600, show_spinner=False)
def shared():  # the same for every viewer
    return a.fake() if MODE == "fake" else with_query(lambda q: a.snapshot(q, WHERE))


def mine():  # per viewer only, never in the shared cache
    if MODE == "snowflake":
        return with_query(lambda q: a.mine(q, WHERE.split(".")[0]))
    d = shared()
    with lock():  # only() rebuilds the shared lookups; called before main takes the lock, so no deadlock
        return a.only(d, DEMO_USER)


# Links reload the page, which starts a new Streamlit session. Keyed by the browser's XSRF cookie, the viewer's
# own access survives that in server memory for an hour; it is never written anywhere and no other browser sees it.
@st.cache_data(ttl=3600, show_spinner=False)
def mine_for(browser):
    return mine()


def refresh():
    """CALL the snapshot procedure: owner's rights, whoever clicks, so the shared tables always hold the full picture."""
    if MODE != "snowflake":
        st.sidebar.info("Demo: the CALL runs only on Snowflake (FAKE=0).")
        return
    with st.spinner("Running SP_ACCESS_SNAPSHOT ..."):
        res = with_query(lambda q: q(f"CALL {WHERE}.SP_ACCESS_SNAPSHOT('AUTO')"))
    st.sidebar.json(json.loads(list(res[0].values())[0]))
    shared.clear()


def load_mine(who):  # a click callback: runs before the page, so the button label is already right
    if who:
        mine_for.clear(who)
    st.session_state.mine = mine_for(who) if who else mine()


def load(view, box):
    """The data for the view, or None (with the reason shown). box: the sidebar snapshot card."""
    if view == "shared":
        if box.button("Reload page data", width="stretch",
                      help="Reads the snapshot tables again. Does not read the grants from Snowflake again."):
            shared.clear()
        if box.button("Rebuild snapshot in Snowflake (slow, admin)", key="refresh", width="stretch",
                      help="CALL SP_ACCESS_SNAPSHOT with the owner's rights. Takes minutes on the SHOW fallback."):
            refresh()
        try:
            return shared()
        except Exception as x:
            html(ui.banner("bad", "Shared snapshot not readable", [e(a.line(x))]))
            html(ui.banner("info", f"Use {VIEWS['mine']} in the sidebar: it reads only your own roles, with your own "
                                   "rights, and saves nothing."))
            return None
    who = st.context.cookies.get("_streamlit_xsrf")
    box.button("Reload my access" if "mine" in st.session_state else "Load my access", width="stretch",
               on_click=load_mine, args=(who,))
    if "mine" not in st.session_state and who and q("data") == "mine":  # came back through a link
        st.session_state.mine = mine_for(who)
    if "mine" not in st.session_state:
        html(ui.banner("info", "Load my access <span style='font-weight:400'>reads your own roles and grants with your "
                               "own rights. Nothing is saved, and other users see nothing of it.</span>"))
        return None
    st.query_params["data"] = "mine"
    return st.session_state.mine


# ---------- URL state ----------

def q(key, default=""):
    return st.query_params.get(key, default)


def put(key, value, default):
    """Write a filter to the URL; a value equal to default stays out (default None: always written)."""
    if q(key) != ("" if default is not None and value == default else str(value)):
        st.query_params.pop("expand", None)  # the expanded lane belongs to the old view
    if default is not None and value == default:
        st.query_params.pop(key, None)
    else:
        st.query_params[key] = str(value)


def init(key, param, default, options, strict=False):
    """Widget state from the URL on a fresh session, or when the old value is no longer an option.
    strict: a name in the URL that is not an option gives None (shown as "not in this snapshot"), never another one."""
    if st.session_state.get(key) not in options:
        v = q(param, default)
        st.session_state[key] = v if v in options else None if strict and q(param) else default


def select(label, options, param, default=None, fmt=str, key=None, strict=False, **kw):
    key = key or "f_" + param
    init(key, param, default if default in options else options[0], options, strict)
    v = st.selectbox(label, options, key=key, format_func=fmt, placeholder="Pick one", **kw)
    if v is not None:
        put(param, v, default)
    return v


def radio(label, options, param, default, fmt=str, **kw):
    key = "f_" + param
    init(key, param, default if default in options else options[0], options)
    v = st.radio(label, options, key=key, format_func=fmt, horizontal=True, **kw)
    put(param, v, default)
    return v


def flag(label, param, default=False, toggle=False, **kw):
    """Checkbox or toggle kept in the URL as 1/0 when it differs from default."""
    key = "f_" + param
    if key not in st.session_state:
        st.session_state[key] = {"1": True, "0": False}.get(q(param), default)
    v = (st.toggle if toggle else st.checkbox)(label, key=key, **kw)
    put(param, "1" if v else "0", "1" if default else "0")
    return v


def depth_select(label):
    d = select(label, list(DEPTHS), "depth", "", DEPTHS.get, help=ui.HELP["Depth"])
    return int(d) if d else None


def gone(param):
    """A name in the URL that is not in the data: say so, show nothing else."""
    html(ui.banner("warn", f"{e(q(param))} is not in this snapshot",
                   ["No grants to or from it. Pick another name above."]))


def kept():
    """URL params that survive navigation."""
    return {k: q(k) for k in ("theme", "data") if q(k)}


def here(**params):
    """This view with params changed (None or "" drops one); the expanded graph lane and the full chain are reset."""
    qs = {k: v for k, v in st.query_params.items() if k not in ("expand", "unfold", "full")} | params
    return "?" + urlencode({k: v for k, v in qs.items() if v not in (None, "")})


def scope_crumb(name, scope):
    """"U › DB.SCHEMA" with a link back to the whole view; a bad ?schema= is said, then ignored."""
    if q("schema") and not scope:
        html(ui.banner("info", f"{e(q('schema'))} is not reached by {e(name)}", ["Showing all of its access."]))
    if scope:
        html(f'<div class="ae ae-crumb"><a href="{e(here(schema=None))}" target="_self">{e(name)}</a> › '
             f'<b class="ae-mono">{e(scope)}</b> <span class="ae-small">· graph, tiles and tables show only '
             f'this {"schema" if "." in scope else "database"}</span></div>')


def node_href(start, kinds, check=False):
    """Graph links: a schema or database node opens the drill-down (?schema=); check: an object node opens Can they?
    for start."""
    def go(n):
        k = kinds.get(n)
        if k in ("schema", "database"):
            return here(schema=n)
        if k == "fold":
            return here(full="1")
        if k:
            return here()
        if check and n in a.kinds and a.role_kind(n) == "object":
            return link(page="check", name=start, obj=n)
        return node_link(n)
    return go


def link(**params):
    return "?" + urlencode(kept() | {k: v for k, v in params.items() if v not in (None, "")})


def shared_link(**params):
    """A link into the shared snapshot (no data=mine), e.g. from My access to an answer it can't give."""
    return "?" + urlencode({k: v for k, v in (kept() | params).items() if k != "data" and v not in (None, "")})


def page_of(name):
    k = a.kind_of(name)
    return "user" if k == "user" else "object" if k == "object" else "role"


def href(name):
    return link(page=page_of(name), name=name)


def href_k(name, kind):
    return link(page="user" if kind == "user" else "object" if kind == "object" else "role", name=name)


def node_link(n):
    """Link of a graph node id (a.uid): a role named like a user opens the role."""
    return href_k(a.node_name(n), a.node_kind(n))


def find():
    """Global search: go to the page of the picked entity, with that page's own filters reset."""
    n = st.session_state.find
    if not n:
        return
    for k in [k for k in st.session_state if k.startswith(("f_", "pick_")) and k != "f_data"]:
        del st.session_state[k]
    with lock():  # a callback runs before main takes the lock; node_kind reads the shared lookups
        k, name = a.node_kind(n), a.node_name(n)
    st.query_params.from_dict(kept() | {"page": "user" if k == "user" else "object" if k == "object" else "role",
                                        "name": name})
    st.session_state.find = None


def theme():
    t = q("theme") or st.context.theme.type or "light"
    return t if t in ui.TOKENS else "light"


def flip():
    st.query_params["theme"] = "light" if theme() == "dark" else "dark"


# ---------- drawing helpers ----------

def html(s, where=st):
    where.markdown(s, unsafe_allow_html=True)


def empty(text):
    html(f'<p class="ae ae-empty">{e(text)}</p>')


def chip(n, title="", short=False, kind=None):
    """short: an object as its own name only (DB and schema sit in their own columns); the full name in the title.
    kind: when known (a role named like a user stays a role), else kind_of."""
    k = a.kinds.get(n, "")
    kind = kind or a.kind_of(n)
    lab = a.future_label(n, k)
    if lab:
        title = title or "applies to objects created later"
    elif short and kind == "object":
        lab, title = a.split_name(n)[2], title or n
    return ui.chip(n, kind, href_k(n, kind), sensitive=n in SENS, disabled=kind == "user" and a.is_disabled(n),
                   title=title, label=lab)


def rchip(n, title=""):
    """A chip for a name known to be a role (or object)."""
    return chip(n, title, kind=a.role_kind(n))


def mpath(p, cls="", first=None):
    """A path as a mini chain graph (ui.mini_path): start, roles, maybe an object; long ones collapse. first: the kind
    of p[0] when known (a role named like a user stays a role); later names are roles or the object. p[0] may be a
    graph node id (a.uid): a user named like a role, as up() paths start."""
    nodes = []
    for i, n in enumerate(p):
        name = a.node_name(n) if i == 0 else n
        k = (a.node_kind(n) if name != n or not first else first) if i == 0 else a.role_kind(n)
        lab = a.future_label(n, a.kinds.get(n, "")) or (a.split_name(n)[2] if k == "object" else None)
        nodes.append((n, k, href_k(name, k), lab if lab != n else None))
    return ui.mini_path(nodes, cls)


def mpaths(ps, cls="", first=None, top=3):
    """Several paths stacked: the first top, then "+N more paths" (the CSV has all)."""
    more = f'<span class="ae-small">+{len(ps) - top} more paths</span>' if len(ps) > top else ""
    return '<div class="ae-mps">' + "".join(mpath(p, cls, first) for p in ps[:top]) + more + '</div>'


def edge_cls(f):
    """Privilege class of a finding's edge, for the last arrow of its path ("" for a role link)."""
    g = f.get("edge")
    return a.priv_class(g[2], a.kinds.get(g[1], "")) if g and g[2] else ""


def strong(n, caption="", bad=False, kind=None):
    cap = f'<br><span class="ae-small{" ae-ink-bad" if bad else ""}">{e(caption)}</span>' if caption else ""
    return (f'<a class="ae-strong" style="color:var(--ink);text-decoration:none" href="{e(href_k(n, kind) if kind else href(n))}" '
            f'target="_self">{e(n)}</a>{cap}')


def kind_label(n, k=None):
    k = k or a.kind_of(n)
    if k == "user":
        p = a.profile.get(n) or {}
        s = a.status(n) if n in a.profile else ""
        return "User · " + str(p.get("TYPE") or "person").lower() + (f" · {s}" if s and s != "active" else "")
    return KIND[k]


def arrow(p):
    """A path as text; a user named like a role (a.uid, as up() paths start) by its own name."""
    return " > ".join([a.node_name(p[0])] + list(p[1:])) if p else ""


def plural(n, word):
    return f"{n} {word}{'s' * (n != 1)}"


def ago(d):
    return "today" if d == 0 else "1 day ago" if d == 1 else f"{d} days ago"


def login(u):
    """Last login as text: "2026-10-30 08:12 · 3 days ago", plus Dormant / Never; "—" when not readable (My access)."""
    p = a.profile.get(u) or {}
    d = a.login_days(u)
    if a.login_unknown(u):
        return "—", ""
    if d is None:
        return "never logged in", "Never"
    return f"{str(p.get('LAST_SUCCESS_LOGIN'))[:16]} · {ago(d)}", "Dormant" if a.is_dormant(u) else ""


def login_html(u):
    """Last login on two lines: the time, then "3 days ago" muted."""
    text = login(u)[0]
    t, _, rel = text.partition(" · ")
    return e(t) + (f'<br><span class="ae-small">{e(rel)}</span>' if rel else "")


def tag(text, tone="low", title=""):
    t = f' title="{e(title)}"' if title else ""
    return f'<span class="ae-sev ae-tone-{tone}"{t}>{e(text)}</span>' if text else ""


def wbr(text):
    """Escaped text that may break after "_" and ".", never inside a name part (long role and object names)."""
    return e(text).replace("_", "_<wbr>").replace(".", ".<wbr>")


def obj_cell(o, k, name, where=False):
    """An object's own name as a link (lock when sensitive); where: its DB.SCHEMA muted in front."""
    if k.startswith("FUTURE"):
        what = k.split(" ", 1)[1].lower() + "s"
        return (f'<span class="ae-tip" title="applies to {e(what)} created later">All future {e(what)} in '
                f'{e(o.rsplit(".", 1)[0])}</span>')
    head = o[:-len(name)] if where and o != name and o.endswith(name) else ""  # "SALES.CORE." in front of a table
    pre = f'<span class="ae-small">{e(head)}</span>' if head else ""
    return (pre + f'<a class="ae-mono" style="color:var(--ink);text-decoration:none" href="{e(href_k(o, "object"))}" '
            f'target="_self">{e(name)}</a>' + (f'<span class="ae-sens" title="sensitive data">{ui.icon("lock", 11, 2.4)}'
                                               f'</span>' if o in SENS else ""))


def type_rank(k):
    """Tables and views first, then warehouses, then the rest, database/schema USAGE last."""
    return 0 if a.is_data(k) else 1 if k == "WAREHOUSE" else 3 if k in ("DATABASE", "SCHEMA") else 2


def csv_text(cols, rows, head=()):
    f = io.StringIO()
    w = csv.writer(f)
    w.writerows(list(head) + ([[]] if head else []))
    w.writerow(cols)
    w.writerows(rows)
    return f.getvalue()


NARROW = {"Depth", "Paths", "People", "Masked", "Nearest grant", "Roles with read", "Objects", "Status",
          "Type", "Privilege"}  # short columns kept on one line


def table_card(key, title, sub, cols, rows, data, none, numeric=(), min_width=640, data_cols=None, fname=None, head=(),
               subs=None, nowrap=()):
    """Card with title, Export CSV and a table. data: plain rows for the CSV (columns data_cols or cols);
    none: sentence when empty; subs: a full-width line under each row (ui.table)."""
    with st.container(key="card_" + key):
        left, right = st.columns([4, 1], vertical_alignment="center")
        html(f'<div class="ae">{ui.title(title, sub)}</div>', left)
        if data:
            right.download_button("Export CSV", csv_text(data_cols or cols, data, head), fname or f"{key}.csv",
                                  "text/csv", key="csv_" + key, on_click="ignore")
        html(ui.table(cols, rows, numeric, min_width, nowrap=NARROW | set(nowrap), subs=subs) if rows else
             f'<p class="ae ae-empty">{e(none)}</p>')


def marks(names, bad=()):
    """Graph node markers: disabled user, sensitive object, bad (e.g. the role a read-only role writes through)."""
    out = {n: {f for f, on in (("disabled", a.node_kind(n) == "user" and a.is_disabled(a.node_name(n))),
                               ("sensitive", n in SENS), ("bad", n in bad)) if on} for n in names}
    return {n: f for n, f in out.items() if f}


def edge_tip(x, y, cls, privs, back):
    """Hover text of a graph edge x -> y in plain words, plus the rules it breaks."""
    if cls == "inherit":
        s = (f"Role {y} is granted to user {a.node_name(x)}" if a.node_kind(x) == "user" else
             f"Role {y} is granted to role {x}: {x} inherits all its privileges")
        s += f"\n{y} is drawn once, at its shortest depth" if back else ""
    else:
        s = f"{x} has {', '.join(privs)} on {a.kinds.get(y, 'object').lower()} {y} ({ui.PCLASS.get(cls, cls).lower()})"
    return "\n".join([s] + ui.rule_lines(BREAKS.get((x, y, cls), [])))


def node_label(n):
    """Graph box text of an object: (own name, "≋ stream · SALES.PIPELINE"); a future grant ("future tables",
    "SALES.CORE"); None for every other name."""
    k = a.kinds.get(n, "")
    if k.startswith("FUTURE"):
        return f"future {k.split(' ', 1)[1].lower()}s", n.rsplit(".", 1)[0]
    if a.role_kind(n) != "object":
        return None
    db, sc, nm = a.split_name(n, k)
    g, lab = ui.TYPE_ICON.get(k, ("·", k.lower()))
    return nm, f"{g} {lab}" + (f" · {db}.{sc}" if sc else f" · {db}" if db and db != nm else "")


def node_tip(n):
    """Kind and rule findings of a graph node id, under its name in the hover text."""
    name, kind = a.node_name(n), a.node_kind(n)
    k = (a.kinds.get(n, "Object").capitalize() if kind == "object" else kind_label(name) if kind == "user" else KIND[kind])
    fs = [f'Rule {x["num"]} ({x["severity"]}): {x["title"]}' for x in ROWS if x["grantee"] == name
          and (x["kind"] == "user") == (kind == "user")]
    return "\n".join([k] + fs[:5] + ([f"+{len(fs) - 5} more findings"] if len(fs) > 5 else []))


def breaks(rows, ro):
    """{(x, y, cls): [(num, severity, title)]} for the graph edges a rule finding's fix points at."""
    out = {}
    for x in rows:
        for g in x["edges"]:
            cls = "inherit" if g["priv"] is None else a.priv_class(g["priv"], g["kind"] or "")
            out.setdefault((a.uid(g["grantee"], g["user"]), g["to"], cls), {})[(x["num"], x["severity"], x["title"])] = 1
    for x in ro:  # rule 17: the write arrow out of a read-only role
        for pv in x["privileges"]:
            k = (x["holder"], x["object"], a.priv_class(pv, a.kinds.get(x["object"], "")))
            out.setdefault(k, {})[("17", a.SEVERITY["17"], a.RULES["17"][0])] = 1
    return {k: list(v) for k, v in out.items()}


def merge(x, rs):
    x["rules"] = sorted(set(x.get("rules", [])) | set(rs), key=lambda t: int(t[0]))


def hits(lanes, edges, info=None, every=False):
    """Graph info: graph_input's (else a.graph_info's: rule hits, Has / Lacks) plus the BREAKS rule hits on the drawn
    edges. every=False keeps only High rule hits, so they stand out. My access holds only your own roles: no rule hits
    there."""
    out = {k: dict(v) for k, v in (a.graph_info(lanes, edges) if info is None else info).items()}
    if VIEW_MODE != "shared":
        for v in out.values():
            v.pop("rules", None)
            v.pop("findings", None)
        return out
    for g in edges:
        k = (g[0], g[1], g[2] if len(g) > 2 else "inherit")
        if BREAKS.get(k):
            merge(out.setdefault(k, {}), BREAKS[k])
    if not every:
        for v in out.values():
            if "rules" in v:
                v["rules"] = [r for r in v["rules"] if r[1] == "High"]
    return out


def summarize(g):
    """A big graph as a.summary(), unless ?full=1; a note above the graph links to the other view."""
    if not g or not a.too_big(g):
        return g, ""
    if q("full") == "1":
        return g, f'Full chain of a big graph. <a href="{e(here())}" target="_self">Show summary</a>'
    g = a.summary(g)
    return g, (f'Summary: {plural(g["folded"], "role")} between granted roles and grant holders '
               f'{"is" if g["folded"] == 1 else "are"} folded. <a href="{e(here(full="1"))}" target="_self">'
               f'Show full chain</a>')


def graph_card(title, lanes, edges, notes=None, selected=None, sub="", bad=(), info=None, kinds=None, href_of=None,
               note=""):
    """Graphs over 3 lanes (often wider than the card at full size) start fitted, so the answer on the right is in
    view. info: graph_input's (else a.graph_info's; BREAKS are added here); kinds: {group node: schema | database |
    type-group}; href_of: node links (default: the node's own page). Node names are graph node ids (a.uid)."""
    kinds = kinds or {}
    with st.container(key="card_graph"):
        left, right = st.columns([4, 1.2], vertical_alignment="center")
        html(f'<div class="ae">{ui.title(title, sub)}</div>', left)
        with right:
            fit = flag("Fit to width", "fit", len(lanes) > 3, toggle=True,
                       help="Scale the whole graph into the card (scrolls below a readable size). Off: full size, "
                            "scroll sideways.")
            every = VIEW_MODE == "shared" and flag("All rule hits", "allhits", toggle=True,
                                                   help="Off: only High rule hits are marked on the graph. On: "
                                                        "Medium and Low too.")
        info = hits(lanes, edges, info, every)
        names = {n for _, ns in lanes for n in ns}
        kind = {n: kinds.get(n) or a.node_kind(n) for n in names}
        mk = marks(names, bad)
        extra = ({c for e_ in edges for c in e_[2:3]} | ({"group"} if kinds else set())
                 | ({"rule"} if any(v.get("rules") for v in info.values()) else set()))
        html(ui.legend(edges=True, marks={f for v in mk.values() for f in v}, extra=extra,
                       kinds={"object" if k in ui.GROUPS else k for k in kind.values()}))
        if note:
            html(f'<div class="ae ae-graph-note">{note}</div>')
        html(ui.lane_graph(lanes, edges, lambda n: kind.get(n) or a.node_kind(n), THEME, href_of or node_link, selected,
                           expand=q("expand"), query=dict(st.query_params), fit=fit, marks=mk,
                           notes=notes, edge_tip=edge_tip, node_tip={n: node_tip(n) for n in names if n not in kinds},
                           label=lambda n: None if n in kinds else node_label(n), info=info))
        html(ui.how())


def usage_days():
    return "7" if a.run["SOURCES"].get("usage") == "INFORMATION_SCHEMA" else "30"


def usage_card(u, title):
    src, days = a.run["SOURCES"].get("usage"), usage_days()
    use = a.used.get(u, [])
    rows = [[e(x["KIND"].capitalize()), ui.mono(x["NAME"]), e(str(x["QUERIES"])), ui.mono(str(x["LAST_USED"])[:16])]
            for x in use]
    data = [[x["KIND"], x["NAME"], x["QUERIES"], x["LAST_USED"]] for x in use]
    none = "Query history not readable." if src == "UNAVAILABLE" else f"No queries by {u} in the last {days} days."
    table_card("usage", title.format(days=days), f"last {days} days", ["Kind", "Name", "Queries", "Last used"], rows,
               data, none, {"Queries"})


def admin_lines(paths, first="user"):
    """Admin paths, one mini chain each (at most 6, the rest counted)."""
    return [mpath(p, "", first) for p in paths[:6]] + [f'<span class="ae-small">+{len(paths) - 6} more paths</span>'] * (
        len(paths) > 6)


def findings_banner(name, user, skip=()):
    """Rule findings of a user or role and, for a user, of the roles granted to it directly: one line per rule and
    grantee, "● Rule 19 EXECUTE TASK ... · [GRANTEE] · detail" (details of several findings joined)."""
    if VIEW_MODE != "shared":
        return
    via = set(a.roles_of.get(name, [])) if user else set()
    xs = [x for x in ROWS if x["num"] not in skip and ((x["grantee"] == name and (x["kind"] == "user") == user)
                                                      or (x["grantee"] in via and x["kind"] != "user"))]
    per = {}
    for x in xs:
        per.setdefault((x["num"], x["grantee"], x["kind"]), []).append(x)
    lines = [f'{ui.dot(v[0]["severity"])}&nbsp;<b>Rule {e(n)}</b>&nbsp;{e(v[0]["title"])}&nbsp;·&nbsp;{chip(g, kind=k)}'
             f'&nbsp;<span class="ae-mono" style="font-size:12.5px">{e("; ".join(dict.fromkeys(x["detail"] for x in v)))}'
             f'</span>' for (n, g, k), v in list(per.items())[:6]]
    if lines:
        lines += [f'<span class="ae-small">+{len(per) - 6} more</span>'] * (len(per) > 6)
        lines.append(f'<a href="{e(link(page="rules", grantee=name))}" target="_self">Show on Rule checks</a>')
        html(ui.banner("warn", f"{plural(len(xs), 'rule finding')} for {e(name)}"
                       + (" and the roles granted to it" if any(x["grantee"] != name for x in xs) else ""), lines))


# ---------- pages ----------

def user_page():
    if not a.users:
        return empty("No users in this data.")
    mine = VIEW_MODE == "mine"
    with st.container(key="card_filter"):
        top = st.columns(4)
        with top[0]:
            if mine:
                u = a.users[0]
                html(f'<div class="ae"><span class="ae-small">You</span><br><span class="ae-strong">{e(u)}</span></div>')
            else:
                u = select("User", a.users, "name", DEMO_USER if DEMO_USER in a.users else None, key="pick_user",
                           strict=True)
        with top[3]:
            limit = depth_select("Walk role hierarchy")
        low = st.columns([1.4, 1], vertical_alignment="center")
        with low[0]:
            mode = radio("Roles", list(ROLES), "roles", "all", ROLES.get, label_visibility="collapsed",
                         help="All granted roles: as with secondary roles ALL. Live session roles of other users "
                              "can't be read: this shows the defaults and the roles used in queries.")
        with low[1]:
            data_only = flag("Data only", "dataonly", True, toggle=True,
                             help="Hide USAGE on databases and schemas (needed to reach a table, rarely the question).")
        if u is None:
            return gone("name")
        only_default = mode == "default"
        every = a.grants(u, True, only_default, limit)
        scope = q("schema") if q("schema") in a.scopes(every) else ""
        rows = [r for r in every if a.in_scope(r, scope) and not (data_only and r["privilege"] == "USAGE"
                                                                and r["type"] in ("DATABASE", "SCHEMA"))]
        rows.sort(key=lambda r: (type_rank(r["type"]), r["object"], r["privilege"]))
        with top[1]:
            o = select("Only on object", [""] + sorted({r["object"] for r in rows}), "on", "",
                       lambda x: x or "Any object")
        rows = [r for r in rows if not o or r["object"] == o]
        with top[2]:
            pv = select("Only privilege", [""] + sorted({r["privilege"] for r in rows}), "priv", "",
                        lambda x: x or "Any privilege")
        rows = [r for r in rows if not pv or r["privilege"] == pv]
    scope_crumb(u, scope)
    p = a.profile.get(u) or {}
    reach = a.reach(u, True, only_default, limit)
    if scope:  # roles on a path into the scope
        on_path = {n for r in rows for x in r["paths"] for n in x[1:-1]}
        reach = [x for x in reach if x["role"] in on_path]
    admin = a.admin_paths(u, True, only_default, limit)
    acct = a.account_privs(u, True, only_default, limit)
    if only_default:
        hidden = len(a.grants(u, True, False, limit)) - len(every)
        if hidden:
            html(ui.banner("info", f"{plural(hidden, 'grant')} hidden in this mode",
                           ["Default role only leaves out roles granted next to the default role (direct grants "
                            "included). Switch to All granted roles to see them."]))
    if a.is_disabled(u):
        html(ui.banner("warn", "Disabled user: access below is dormant; revoke or drop",
                       ["The user can't log in, but every grant comes back if it is enabled again."]))
    elif a.is_dormant(u) and not a.is_service(u):
        d = a.login_days(u)
        html(ui.banner("warn", "Dormant user: " + ("never logged in" if d is None else f"no login for {d} days"),
                       [f'Unused access is risk: revoke the roles or disable the user. See '
                        f'<a href="{e(link(page="rules", rule="16"))}" target="_self">Rule 16</a> and '
                        f'<a href="{e(link(page="rules", rule="7"))}" target="_self">Rule 7</a>.']))
    findings_banner(u, True)

    mark = login(u)[1]
    sec = str(p.get("DEFAULT_SECONDARY_ROLES") or "")
    html(ui.profile([
        ("Type", e(str(p.get("TYPE") or "—").capitalize())),
        ("Status", '<span class="ae-ink-bad">Disabled</span>' if a.is_disabled(u)
         else '<span class="ae-ink-ok">Enabled</span>'),
        ("Default role", rchip(p["DEFAULT_ROLE"]) if p.get("DEFAULT_ROLE") else "—"),
        ("Secondary roles", f'<span class="ae-tip" title="{e(ui.HELP["Secondary roles"])}">'
                            f'{"All" if "ALL" in sec.upper() else "None"}</span>'),
        ("Default warehouse", ui.mono(p.get("DEFAULT_WAREHOUSE") or "—")),
        ("Last login", login_html(u) + (" " + tag(mark, "warn", ui.HELP["Dormant"]) if mark else ""))]))
    twice = sum(r["count"] > 1 for r in rows)
    n_admin = len({x[-1] for x in admin})
    sens = sorted({r["object"] for r in rows if r["object"] in SENS and r["privilege"] in a.READ_PRIVS})
    html(ui.grid([
        ui.kpi("Distinct privileges", len(rows), f"on {plural(len({r['object'] for r in rows}), 'object')}", "accent"),
        ui.kpi("Grant paths", sum(r["count"] for r in rows),
               f"{plural(twice, 'privilege')} reached more than once" if twice else "each through one path",
               help="Paths"),
        ui.kpi("Roles reachable", len(reach), f"{sum(x['direct'] for x in reach)} granted directly"),
        ui.kpi("Deepest grant", max((r["depth"] for r in rows), default=0), "roles from the user to the grant",
               help="Depth"),
        ui.kpi("Sensitive objects", len(sens), "readable" if sens else "none readable", "bad" if sens else None,
               help="Sensitive") if SENS or not mine else ui.kpi(
            "Sensitive objects", "—", f'needs governance views: <a href="{e(shared_link(page="user", name=u))}" '
                                      'target="_self">see it in the shared snapshot</a>', help="Sensitive"),
        ui.kpi("Admin roles", n_admin, f"{plural(len(acct), 'account-level privilege')}" if acct else
               "no account-level privileges", "bad" if n_admin or acct else "ok", help="Admin")]))
    lines = admin_lines(admin) + [f'<span class="ae-mono">{e(x)}:</span>&nbsp;{mpath(y, "", "user")}' for x, y in acct]
    if lines:
        html(ui.banner("bad", "Reaches an admin role, which inherits every role below it" if admin
                       else "Holds account-level privileges", lines))

    if o or pv:  # one object or privilege: the graph of just those rows
        g = a.down_graph(u, rows, user=True)
        g = g and dict(lanes=g[0], edges=g[1], notes=g[2], header=f"{len(rows)} privileges shown")
    else:
        g = a.graph_input(u, scope or None, default_only=only_default, limit=limit, user=True)
    g, note = summarize(g) if not (o or pv) else (g, "")
    if g:
        kinds = g.get("kinds", {})
        graph_card("Role hierarchy, by depth", g["lanes"], g["edges"], g["notes"],
                   sub=e(g["header"]) + (" · click a schema or database box to open it"
                                         if {"schema", "database"} & set(kinds.values()) else "")
                   + " · click an object: can this user use it?", info=g.get("info"), kinds=kinds,
                   href_of=node_href(u, kinds, check=True), note=note)
    else:
        html(ui.card("Role hierarchy, by depth", "", f'<p class="ae-empty">{e(u)} reaches no roles at this depth.</p>'))

    table_card("privileges", "Privileges", f"{len(rows)} privileges · {sum(r['count'] for r in rows)} paths · "
                                           "shortest path shown" + (" · data only" if data_only else "")
               + (f" · in {e(scope)}" if scope else ""),
               ["Privilege", "Type", "Object", "Use role", "Depth", "Path", "Paths"],
               [[ui.pclass(r["cls"], r["privilege"]), ui.type_tag(r["type"]),
                 obj_cell(r["object"], r["type"], r["name"], True), rchip(r["granted"]),
                 ui.depth(r["depth"]), f'<div class="ae-wide">{mpath(r["path"], r["cls"], "user")}</div>',
                 f'<span class="ae-tip" title="{e(a.paths_note(r))}">{r["count"]}</span>' if a.paths_note(r)
                 else str(r["count"])] for r in rows],
               [[r["privilege"], r["cls"], r["type"], r["database"], r["schema"], r["name"], r["granted"], r["depth"],
                 arrow(r["path"]), r["count"]] for r in rows],
               f"{u} holds no privileges{' on ' + o if o else ''} at this depth.", {"Paths"}, min_width=820,
               data_cols=["Privilege", "Class", "Type", "Database", "Schema", "Object", "Use role", "Depth", "Path",
                          "Paths"],
               fname=f"{u}_privileges.csv", head=[["User", u, a.status(u)]])
    multi = [(r, x) for r in rows if r["count"] > 1 for x in r["paths"]]
    if multi:
        cut = 300  # on screen; the CSV has every listed path
        table_card("multi", "Every path of the privileges reached more than once",
                   f"{plural(twice, 'privilege')} · {len(multi)} paths listed (up to {a.MAX_PATHS} per privilege)"
                   + (f" · first {cut} shown, the CSV has all" if len(multi) > cut else ""),
                   ["Privilege", "Object", "Depth", "Path"],
                   [[ui.pclass(r["cls"], r["privilege"]), ui.mono(r["object"]), ui.depth(a.depth(x[:-1], True)), mpath(x, r["cls"], "user")]
                    for r, x in multi[:cut]],
                   [[r["privilege"], r["object"], a.depth(x[:-1], True), arrow(x)] for r, x in multi], "",
                   min_width=560, fname=f"{u}_every_path.csv")
    objs = {r["object"] for r in rows}
    data_card(u, True, objs if scope or o or pv else None)
    sensitive_card(u, objs if scope else None)
    granted_card(u)


ROWS_WORD = {"all": "all rows", "filtered": "filtered rows", "none": "no rows", "unknown": "rows unknown"}


def state_tag(x, word=None):
    """A clear / masked / unknown (column) or all / filtered / none / unknown (rows) badge from data_view(), the reason
    in the tooltip, plus the policy text when the state can't be derived from it."""
    tip = x["reason"] + (f"\nPolicy text: {x['body']}" if x.get("body") and x["state"] == "unknown" else "")
    return tag(word or x["state"], "warn" if x["state"] in ("clear", "all", "unknown") else "low", tip)


def data_card(name, user, objs=None):
    """Can read the data? Per governed table or view name reads: the privilege, then what the row access policy and
    the masking policies leave visible (from the policy text, not evaluated). objs: only these objects."""
    if VIEW_MODE != "shared":
        return
    vs = [v for v in a.data_views(name, user) if objs is None or v["object"] in objs]
    if not vs:
        return
    rows = [[chip(v["object"]), tag("yes", "low", "reaches SELECT or OWNERSHIP"),
             state_tag(v["rows"], ROWS_WORD[v["rows"]["state"]]) if v["rows"]["policy"]
             else '<span class="ae-small">all rows · no row policy</span>',
             " ".join(f'<span class="ae-mono" style="font-size:12px">{e(c["column"])}</span>&nbsp;{state_tag(c)}'
                      for c in v["columns"]) or '<span class="ae-muted">–</span>'] for v in vs]
    data = [[v["object"], "yes", ROWS_WORD[v["rows"]["state"]], "; ".join(f'{c["column"]} {c["state"]}'
                                                                         for c in v["columns"]), v["summary"]] for v in vs]
    table_card("canread", "Can read the data?", "privilege + row access policy + masking, for "
               + ("any role granted to the user (secondary roles ALL)" if user else "this role as the role in use")
               + " · from the policy text, not evaluated · hover a badge for why",
               ["Object", "Privilege", "Rows", "Columns"], rows, data, "", min_width=560,
               data_cols=["Object", "Privilege", "Rows", "Columns", "Summary"], fname=f"{name}_can_read.csv")


def read_line(u, o, role=None):
    """Can they? / User: one line "Can read the data?" for u on o, with the row and column reasons under it; role:
    the role to USE, compared when it alone would see less or more."""
    v = a.data_view(u, o, True)
    if not v["can_read"]:
        return
    lines = ([f'Rows: {state_tag(v["rows"], ROWS_WORD[v["rows"]["state"]])} '
              f'<span class="ae-small">{e(v["rows"]["reason"])}</span>'] if v["rows"]["policy"] else [])
    lines += [f'{ui.mono(c["column"])}: {state_tag(c)} <span class="ae-small">{e(c["reason"])}</span>'
              for c in v["columns"]]
    if role:
        w = a.data_view(role, o, False)
        if w["summary"] != v["summary"]:
            lines.append(f'With only {chip(role)} in use (no secondary roles): {e(w["summary"])}')
    html(ui.banner("info", "Can read the data? Privilege yes · " + e(v["summary"].replace("can read: ", ""))
                   + ' <span class="ae-small" style="font-weight:400">(from the policy text, not evaluated)</span>',
                   lines))


def granted_card(u):
    """Roles granted to the user directly, with use in the query history (F5)."""
    src, days = a.run["SOURCES"].get("usage"), usage_days()
    use, dr = a.used_roles(u), (a.profile.get(u) or {}).get("DEFAULT_ROLE")
    rs = sorted(a.roles_of.get(u, []))
    cell = (lambda r: "not readable") if src == "UNAVAILABLE" else (
        lambda r: f"{use[r]['queries']} queries · {str(use[r]['last_used'])[:10]}" if r in use else "not used")
    table_card("granted", "Granted roles", f"granted to {e(u)} directly · use from the query history",
               ["Role", "Kind", "Default", f"Used ({days} d)"],
               [[rchip(r), e(KIND.get(a.role_kind(r), "Group role")), "default role" if r == dr else "",
                 e(cell(r))] for r in rs],
               [[r, a.role_kind(r), r == dr, cell(r)] for r in rs], f"No roles granted to {u}.", min_width=560)
    usage_card(u, "Roles and warehouses used")


def masks(row):
    """Short text of a sensitive_reach row as its granted role sees it: "EMAIL masked · PHONE clear · no rows"."""
    return mask_text(row["role"], row["object"])


def sensitive_card(u, objs=None):
    """Sensitive data per granted role: one column per depth-1 role, a tick plus clear/masked. objs: only these."""
    if not SENS:
        no_tags()
        return
    rs = [x for x in a.sensitive_reach(u) if objs is None or x["object"] in objs]
    got = [x for x in rs if x["path"]]
    if not got:
        return
    objs = list(dict.fromkeys(x["object"] for x in got))
    cell = {(x["object"], x["role"]): x for x in got}
    # only roles that reach sensitive data: PUBLIC (expected to reach nothing) would add an all-dash column
    roles = [r for r in dict.fromkeys(x["role"] for x in rs) if any((o, r) in cell for o in objs)]
    per = [f"through {rchip(r)}: {plural(sum(1 for o in objs if (o, r) in cell), 'sensitive object')}" for r in roles]
    diff = [f'{chip(o, short=True)}: through {", ".join(rchip(r) for r in roles if (o, r) in cell)}; not through '
            f'{", ".join(rchip(r) for r in roles if (o, r) not in cell)}' for o in objs
            if any((o, r) not in cell for r in roles)]
    if len(roles) > 1 and diff:
        html(ui.banner("info", "Granted roles differ in sensitive reach", diff[:8]))
    tick = f'<span class="ae-yes">{ui.icon("ok", 14, 2.6)}</span>'
    rows = [[ui.mono(a.split_name(o)[0]), ui.mono(a.split_name(o)[1]), chip(o, short=True) + (
        f'<br><span class="ae-small">{e(", ".join(a.sensitive_cols(o)) or "whole object")}</span>')]
            + [f'{tick} <span class="ae-small">{e(masks(cell[(o, r)]))}</span>' if (o, r) in cell
               else '<span class="ae-muted">–</span>' for r in roles] for o in objs]
    data = [[*a.split_name(o), ", ".join(a.sensitive_cols(o))] + [masks(cell[(o, r)]) if (o, r) in cell else "" for r in roles]
            for o in objs]
    table_card("sensitive", "Sensitive data, by granted role", " · ".join(per) + " · masking from policy text, "
               "not evaluated", ["Database", "Schema", "Sensitive object"] + roles, rows, data, "", min_width=620,
               data_cols=["Database", "Schema", "Object", "Sensitive columns"] + roles)
    table_card("senspaths", "Paths to sensitive data", "shortest path per sensitive object and granted role",
               ["Object", "Granted role", "Path"],
               [[chip(x["object"], short=True), rchip(x["role"]), mpath(x["path"], "read", "user")] for x in got],
               [[x["object"], x["role"], arrow(x["path"])] for x in got], "", min_width=560)


def role_page():
    if not a.roles:
        return empty("No roles in this data.")
    with st.container(key="card_filter"):
        c = st.columns([3, 2, 1, 1], vertical_alignment="bottom")
        with c[0]:
            r = select("Role", a.roles, "name", key="pick_role", strict=True)
        with c[1]:
            limit = depth_select("Walk upward")
        with c[2]:
            only_users = flag("Users only", "users")
        with c[3]:
            only_sens = flag("Only sensitive", "sensitive", help="Effective privileges: only sensitive objects.")
    if r is None:
        if q("name") in a.ADMIN:  # admin-to-admin grants are hidden, so an admin role nobody else holds is not listed
            return html(ui.banner("info", f"No user or role holds {e(q('name'))} in this snapshot",
                                  [f'See <a href="{e(link(page="rules"))}#admins" target="_self">People with admin '
                                   'roles</a> on Rule checks for who holds the other admin roles.']))
        return gone("name")
    s, hold, full = a.role_stats(r, limit), a.holds_of(r), a.held(r, limit)
    up = [x for x in full if x["kind"] == "user"] if only_users else full
    admin_role = r in a.ADMIN
    every = [] if admin_role else a.grants(r)
    scope = q("schema") if q("schema") in a.scopes(every) else ""
    if scope:
        hold = [h for h in hold if a.in_scope(h, scope)]
    k = s["kind"]
    prefix = {"functional": a.FUNC, "technical": a.TECH}.get(k)
    owner = [g for g, pv, t in a.on.get(r, []) if pv == "OWNERSHIP" and t == "ROLE"]
    eff_cap = ("inherits every role below it" if admin_role else
               f"inherited from {plural(len(s['holds_roles']), 'role')} it holds" if s["holds_roles"] else "no roles held")
    scope_crumb(r, scope)
    if scope:
        sc = [x for x in every if a.in_scope(x, scope)]
        html(ui.grid([
            ui.kpi("Direct grants", len(hold), f"in {e(scope)}", "accent"),
            ui.kpi("Effective privileges", len(sc), f"on {plural(len({x['object'] for x in sc}), 'object')}"),
            ui.kpi("Grant holders", len({x['holder'] for x in sc}), "roles holding the grants"),
            ui.kpi("Sensitive objects", len({x["object"] for x in sc if x["object"] in SENS}), "in this scope",
                   help="Sensitive")], 160))
    html("" if scope else ui.grid([
        ui.kpi("Kind", ui.chip(KIND.get(k, "Group role"), k, title=ui.tip(ui.LABELS[k]) + (
            f" Name starts with {prefix}." if prefix else "")),
               f"owned by {e(', '.join(owner))}" if owner else "", help=ui.LABELS[k]),
        ui.kpi("Direct grants", s["privileges"], f"incl. {plural(s['future'], 'future grant')}" if s["future"]
               else "privileges on the role itself", "accent"),
        ui.kpi("Effective privileges", "all" if admin_role else s["effective"], eff_cap, "bad" if admin_role else None),
        ui.kpi("Roles above it", s["above"], f"{s['above_direct']} grant it directly"),
        ui.kpi("Users who get it", s["users"], f"{s['users_direct']} granted directly" if s["users_direct"]
               else "none granted directly"),
        ui.kpi("Farthest holder", s["farthest"], "roles from the farthest holder to this one", help="Depth"),
        ui.kpi("Sensitive objects reached", s["sensitive"], "readable through it", "bad" if s["sensitive"] else None,
               help="Sensitive")], 140))
    if admin_role:
        html(ui.banner("bad", "Admin role: inherits every role below it (hierarchy hidden)",
                       ["Its effective privileges are those of every custom role, so they are not listed here. See "
                        f'<a href="{e(link(page="rules"))}#admins" target="_self">People with admin roles</a>.']))
    ro = a.readonly_writes(r)
    if ro:
        html(ui.banner("bad", "Read-only role can write", [
            f'{" ".join(ui.pclass(a.priv_class(pv, a.kinds.get(x["object"], "")), pv) for pv in x["privileges"])}'
            f'&nbsp;on {chip(x["object"])}&nbsp;'
            + (f'via {rchip(x["holder"])} (inherited)' if x["inherited"] else "granted directly")
            + f'&nbsp;<span class="ae-small">heuristic: {e(x["how"])}'
            + (f' · mostly read: {x["read_only"]} of {x["objects"]} objects read-only' if x["how"] != "name" else "")
            + '</span>' for x in ro]))
    admin, acct = a.admin_paths(r), a.account_privs(r)
    lines = admin_lines(admin, a.role_kind(r)) + [f'<span class="ae-mono">{e(pv)}:</span>&nbsp;'
                                                   f'{mpath(x, "", a.role_kind(r))}' for pv, x in acct]
    if lines:
        html(ui.banner("bad", "Holds an admin role, which inherits every role below it" if admin
                       else "Holds account-level privileges", lines))
    findings_banner(r, False, skip={"17"} if ro else ())
    if s["holds_roles"]:
        html(ui.card("Holds roles", f"direct grants: {s['privileges']} · it gets everything these roles hold",
                     '<div class="ae-path">' + " ".join(rchip(x) for x in s["holds_roles"]) + '</div>'))

    role_graph_card(r, up, ro, scope)
    held_card(r, up, only_users)
    holds_card(r, hold, s)
    eff = [x for x in every if a.in_scope(x, scope) and (not only_sens or x["object"] in SENS)]
    eff.sort(key=lambda x: (type_rank(x["type"]), x["object"], x["privilege"]))
    table_card("effective", "Effective privileges (inherited)", f"{len(eff)} privileges · own grants and every "
               "role it holds" + (" · sensitive only" if only_sens else ""),
               ["Privilege", "Type", "Object", "Depth", "Path"],
               [[ui.pclass(x["cls"], x["privilege"]), ui.type_tag(x["type"]),
                 obj_cell(x["object"], x["type"], x["name"], True), ui.depth(x["depth"]),
                 f'<div class="ae-wide">{mpath(x["path"], x["cls"], a.role_kind(r))}</div>'] for x in eff],
               [[x["privilege"], x["cls"], x["type"], x["database"], x["schema"], x["name"], x["depth"],
                 arrow(x["path"])] for x in eff],
               f"{r} is an admin role: it inherits every role below it (hierarchy hidden)." if admin_role else
               f"{r} reaches no {'sensitive ' if only_sens else ''}privileges.", min_width=720,
               data_cols=["Privilege", "Class", "Type", "Database", "Schema", "Object", "Depth", "Path"])
    data_card(r, False, {x["object"] for x in eff} if scope else None)


def role_graph_card(r, up, ro, scope):
    """Role page graph: who holds r (up, role_graph lanes), r, then everything r reaches (graph_input: grouped by
    schema / database on big accounts, only scope's objects in a drill-down)."""
    lanes, edges, notes, sel = a.role_graph(r, up, ro)
    above = {n for _, ns in lanes[:sel] for n in ns}
    lanes = [(lab.replace("Depth ", "Held by · D"), ns) for lab, ns in lanes[:sel]] + [lanes[sel]]
    edges = [x for x in edges if len(x) == 2 and x[0] in above]
    g, note = summarize(None if r in a.ADMIN else a.graph_input(r, scope or None, user=False))
    info, kinds, sub = a.graph_info(lanes, edges), {}, "read left to right: holders, the role, what it reaches"
    if g:
        for k, v in info.items():  # the holders' rule hits next to graph_input's (the role's own side)
            merge(g["info"].setdefault(k, {}), v.get("rules", []))
        lanes += [(lab.replace("Depth ", "Holds · D"), ns) for lab, ns in g["lanes"][1:]]
        edges += g["edges"]
        notes = notes | g["notes"]
        info, kinds = g["info"], g["kinds"]
        sub = g["header"] + (" · click a schema or database box to open it"
                             if {"schema", "database"} & set(kinds.values()) else "")
    graph_card("Held by (up) and holds (down)", lanes, edges, notes, sel, sub=e(sub), bad={x["holder"] for x in ro},
               info=info, kinds=kinds, href_of=node_href(r, kinds), note=note)


def holds_card(r, hold, s):
    """Holds (down) as a has / lacks grid: one table per object type, one column per privilege of the type,
    ✓ granted to r, dashed ✓ inherited from a role r holds, owner = implied by OWNERSHIP, – lacks. Filter: lacks X."""
    objs = {}
    for h in hold:
        if not h["type"].startswith("FUTURE") and h["type"] != "ACCOUNT":
            objs.setdefault(h["object"], h)
    other = [h for h in hold if h["object"] not in objs]
    direct = {(h["object"], h["privilege"]) for h in hold}
    hl = {o: a.has_lacks(r, o) for o in objs}
    gaps = sorted({p for x in hl.values() for p in x["lacks"]})
    with st.container(key="card_holds"):
        left, right = st.columns([3, 2], vertical_alignment="bottom")
        html(f'<div class="ae">{ui.title("Holds (down)", f"direct grants: {len(hold)} on {plural(len(objs), "object")}"
                                         " · what it has and lacks of each type's privileges")}</div>', left)
        with right:
            lack = select("Show", [""] + gaps, "lacks", "", lambda x: f"Only objects that lack {x}" if x else
                          "Every object", help="Objects missing this privilege (OWNERSHIP never counts as missing).")
        shown = [o for o in objs if not lack or lack in hl[o]["lacks"]]
        if not objs and not other:
            html(f'<p class="ae ae-empty">{e(r)} holds no privileges of its own'
                 + (": see Effective privileges.</p>" if s["holds_roles"] else ".</p>"))

        def cell(o, p):
            x = hl[o]
            if (o, p) in direct:
                return f'<span class="ae-hl y" title="{e(p)}: granted to {e(r)}">✓</span>'
            if p in x["has"]:
                return f'<span class="ae-hl i" title="{e(p)}: inherited from a role {e(r)} holds">✓</span>'
            if p in x["implied"]:
                return f'<span class="ae-hl o" title="{e(p)}: implied by OWNERSHIP">owner</span>'
            why = "not the owner (normal)" if p == "OWNERSHIP" else f"lacks {p}"
            return f'<span class="ae-hl n" title="{e(why)}">–</span>'

        for t in sorted({objs[o]["type"] for o in shown}, key=lambda t: (type_rank(t), t)):
            cols = a.valid_privs(t)
            os_ = [o for o in shown if objs[o]["type"] == t]
            html(f'<p class="ae ae-rgroup">{ui.type_tag(t)} · {plural(len(os_), "object")}</p>')
            html(ui.table(["Object"] + cols + ["Has / lacks"],
                          [[obj_cell(o, t, objs[o]["name"])] + [cell(o, p) for p in cols]
                           + [f'<span class="ae-small">{e(hl[o]["text"])}</span>'] for o in os_],
                          min_width=260 + 70 * len(cols), nowrap=set(cols) | {"Object"}))
        if objs and not shown:
            html(f'<p class="ae ae-empty">Every object has {e(lack)}.</p>')
        if other:
            html(f'<p class="ae ae-rgroup">Other direct grants</p>')
            html(ui.table(["Privilege", "Type", "Object"], [[ui.pclass(h["cls"], h["privilege"]), ui.type_tag(h["type"]),
                                                             obj_cell(h["object"], h["type"], h["name"])]
                                                            for h in other], min_width=420))
        if hold:
            st.download_button("Export CSV", csv_text(["Object", "Type", "Has", "Lacks", "Implied by OWNERSHIP"], [
                [o, objs[o]["type"], ", ".join(hl[o]["has"]), ", ".join(hl[o]["lacks"]), ", ".join(hl[o]["implied"])]
                for o in objs] + [[h["object"], h["type"], h["privilege"], "", ""] for h in other]),
                f"{r}_holds.csv", "text/csv", key="csv_holds", on_click="ignore")


def held_card(r, up, only_users):
    """Held by (up), full width, with "If revoked from": who loses r, and which privileges, net of other paths."""
    # graph node ids (a.uid): user X and role X holding r are two picks, matched against held()'s paths
    direct = sorted(set(a.held_by.get(r, [])) | {a.uid(u, True) for u in a.users_of.get(r, [])})
    with st.container(key="card_held"):
        left, right = st.columns([3, 2], vertical_alignment="bottom")
        n_users = sum(x["kind"] == "user" for x in up)
        sub = f"{len(up)} grantees · {plural(n_users, 'user')} · shortest path shown, read left to right"
        html(f'<div class="ae">{ui.title("Held by (up)", sub)}</div>', left)
        with right:
            cut = select("If revoked from", [""] + direct, "cut", "", lambda x: x or "Pick a direct grantee",
                         help=f"Who loses {r}, and which privileges, net of their other paths.")
        loses, lost = {}, set()
        if cut:
            for x in up:
                if all((cut, r) in zip(p, p[1:]) for p in x["paths"]):
                    lost.add((x["grantee"], x["kind"]))
                    if x["kind"] == "user":
                        loses[x["grantee"]] = a.loses(x["grantee"], a.node_name(cut), r)
            iac, sql = a.fix_text([a.role_edge(a.node_name(cut), r, a.node_kind(cut) == "user")])
            html(ui.banner("warn", f"Revoking {e(r)} from {e(a.node_name(cut))}: {plural(len(lost), 'grantee')} lose{'s' * (len(lost) == 1)} it, "
                                   f"{plural(len(loses), 'user')} among them", [e(iac), ui.mono(sql)]))
        cols = ["Grantee", "Depth", "Only via", "Path", "Paths"] + (["Loses"] if cut else [])
        rows = []
        for x in up:
            g = x["grantee"]
            cap = kind_label(g, x["kind"]) + (" · granted directly" if x["direct"] else "")
            row = [strong(g, cap, kind=x["kind"]) + (" " + tag("loses it", "bad") if (g, x["kind"]) in lost else ""), ui.depth(x["depth"]),
                   " ".join(rchip(n) for n in x["only_via"]) or '<span class="ae-muted">–</span>',
                   mpath(x["path"], first=x["kind"]), str(x["count"])]
            if cut:
                ls = loses.get(g, [])
                row.append(f'<span class="ae-tip" title="{e(chr(10).join(f"{pv} on {o}" for pv, o in ls))}">'
                           f'{plural(len(ls), "privilege")}</span>' if ls else '<span class="ae-muted">–</span>')
            rows.append(row)
        who = "user" if only_users else "role or user"
        html(ui.table(cols, rows, {"Paths"}, 760, nowrap={"Depth", "Paths", "Loses"}) if rows else
             f'<p class="ae ae-empty">No {who} holds {e(r)} at this depth.</p>')
        if rows:
            data = [[x["grantee"], x["kind"], a.status(x["grantee"]) if x["kind"] == "user" else "", x["depth"],
                     x["direct"], " ".join(x["only_via"]), arrow(x["path"]), x["count"],
                     ", ".join(f"{pv} on {o}" for pv, o in loses.get(x["grantee"], []))] for x in up]
            st.download_button("Export CSV", csv_text(["Grantee", "Kind", "Status", "Depth", "Direct", "Only via",
                                                       "Path", "Paths", "Loses"], data), f"{r}_held_by.csv",
                               "text/csv", key="csv_held", on_click="ignore")
    st.caption("Only via: roles every path passes through. Revoking one of them removes this role from the grantee.")


def object_page():
    types = sorted(set(a.kinds.values()))
    if not types:
        return empty("No objects in this data.")
    with st.container(key="card_filter"):
        c = st.columns([2, 3, 2], vertical_alignment="bottom")
        with c[0]:
            t = select("Type", types, "type", a.kinds.get(q("name"), "TABLE"),
                       lambda k: f"{ui.TYPE_ICON.get(k, ('·',))[0]}  {k.capitalize()}")
        with c[1]:
            o = select("Object", [x for x in a.objects if a.kinds[x] == t], "name", key="pick_obj",
                       strict=True)
        with c[2]:
            pv = select("Privilege", [""] + a.valid_privs(t), "priv", "", lambda x: x or "Any privilege")
        c2 = st.columns(2)
        with c2[0]:
            active = flag("Exclude disabled users", "active")
        with c2[1]:
            only_users = flag("Graph: users only", "users", help="Graph and All grantees: only chains that end at a user.")
    if o is None:
        return gone("name")
    s = a.object_stats(o, t, pv or None)
    adm = [p for x, p in a.admin_holders() if a.from_user(p)]
    if adm:
        html(ui.banner("bad", "Also reachable through admin roles, which inherit every role below them",
                       admin_lines(adm) + ['<span style="font-size:12.5px">Not drawn in the hierarchy below, to '
                                                 'keep it readable.</span>']))
    m = [x for x in a.matrix(o, t, priv=pv or None) if not (active and x["status"] == "disabled")]
    real = [x for x in m if not x["admin"] or x["via"]]
    n_cls = {c: sum(c in x["via"] for x in real) for c in ("read", "write", "own")}
    extra = ([] if active else [f"+{len(s['disabled'])} disabled"] * bool(s["disabled"])) \
        + [f"+{len(s['service'])} service"] * bool(s["service"]) + [f"+{len(s['admin'])} via admin"] * bool(s["admin"])
    split = " · ".join(f"{n} can {w}" for w, n in (("read", n_cls["read"]), ("write", n_cls["write"]),
                                                   ("own", n_cls["own"])) if n)
    html(ui.grid([
        ui.kpi(f"People who can {pv}" if pv else "People with access", len(s["people"]),
               e(" · ".join(extra) or "no others") + (f"<br>{e(split)} (users, admins left out)" if split else ""),
               "accent", help="Enabled persons. Disabled and service users and admin-role holders are counted apart."),
        ui.kpi("Roles with access", s["roles"], f"{s['direct']} hold grants directly"),
        ui.kpi("Owner", " ".join(rchip(x) for x in s["owners"]) or "—",
               "deployed by " + e(", ".join(s["deployers"])) if s["deployers"] else e(s["owner_note"]),
               help="Own"),
        ui.kpi("Longest chain", s["longest"], "roles from the farthest grantee to the grant holder", help="Depth")],
        200))
    sensitivity_card(o)
    matrix_card(o, t, pv, active, m)

    g = [x for x in a.grantees(o, t) if not pv or x["privilege"] == pv]
    users = sorted({x["grantee"] for x in g if x["kind"] == "user" and a.from_user(x["path"])
                    and not (active and a.is_disabled(x["grantee"]))})
    shown = [x for x in g if x["kind"] != "user" or x["grantee"] in users]
    if only_users:
        shown = [x for x in shown if x["grantee"] in users]
    g = a.object_graph(o, t, shown, users)
    if g:
        graph_card("Paths into the object", *g)
    else:
        html(ui.card("Paths into the object", "", f'<p class="ae-empty">Nobody holds {e(pv or "a privilege")} on '
                                                  f'{e(o)} at any depth.</p>'))
    sees_card(o)
    merged = {}
    for x in shown:
        merged.setdefault((x["grantee"], x["kind"], tuple(x["path"])), []).append(x)
    table_card("grantees", "All grantees", "roles and users · path read toward the object",
               ["Grantee", "Privilege", "Depth", "Path", "Paths"],
               [[strong(k[0], kind_label(k[0], k[1]), kind=k[1]),
                 " ".join(ui.pclass(y["cls"], y["privilege"]) for y in v), ui.depth(v[0]["depth"]), mpath(list(k[2]), v[0]["cls"], k[1]),
                 str(max(y["count"] for y in v))] for k, v in merged.items()],
               [[k[0], k[1], a.status(k[0]) if k[1] == "user" else "", *a.split_name(o, t)[:2],
                 a.split_name(o, t)[2], ", ".join(y["privilege"] for y in v), v[0]["depth"], arrow(k[2]),
                 max(y["count"] for y in v)] for k, v in merged.items()],
               f"Nobody holds {pv or 'a privilege'} on {o} at any depth.", {"Paths"}, min_width=640,
               data_cols=["Grantee", "Kind", "Status", "Database", "Schema", "Object", "Privilege", "Depth",
                          "Path", "Paths"])


def sees_card(o):
    """What each role sees of a governed table or view: rows and every tagged or masked column, with the role as the
    role in use (from the policy text, not evaluated; the reason in each badge's tooltip)."""
    ps = a.policies_of(o)
    if VIEW_MODE != "shared" or not a.is_data(a.kinds.get(o, "")) or not (ps["rows"] or ps["columns"] or
                                                                        a.sensitive_cols(o)):
        return
    rs = sorted({x for x, pv, p in a.who_can(o) if pv in a.READ_PRIVS and not a.from_user(p)})
    vs = [a.data_view(r, o, False) for r in rs]
    cols = [c["column"] for c in vs[0]["columns"]] if vs else []
    rows = [[chip(v["name"]), state_tag(v["rows"], ROWS_WORD[v["rows"]["state"]]) if ps["rows"]
             else '<span class="ae-small">all rows · no row policy</span>']
            + [state_tag(c) for c in v["columns"]] for v in vs]
    data = [[v["name"], ROWS_WORD[v["rows"]["state"]]] + [c["state"] for c in v["columns"]] for v in vs]
    table_card("sees", "What each role sees", f"{plural(len(rs), 'role')} that can read {e(o)}, each as the role in "
               "use · rows from the row access policy, columns from masking · from the policy text, not evaluated · "
               "hover a badge for why", ["Role", "Rows"] + cols, rows, data, "No role can read it.",
               min_width=360 + 90 * len(cols), fname=f"{o}_what_roles_see.csv")


POLICY_TEXT = "From the policy text, not evaluated by Snowflake"


def sensitivity_card(o):
    tg, ps = a.tags_of(o), a.policies_of(o)
    if not tg and not ps["columns"] and not ps["rows"]:
        return
    rules = a.tag_rules()
    chips = " ".join(ui.chip(a.tag_label(t, v), "object", sensitive=a.tag_hit(rules, t, v),
                             title=f"{t} · {origin}") + f'<span class="ae-small"> {e(origin)}'
                     f'</span>' for c, t, v, origin in tg if not c)
    cols = sorted({c for c, *_ in tg if c} | set(ps["columns"]))
    sp = a.split_users(a.readers(o), a.admin_users())
    everyone = (f'<span class="ae-ink-warn">everyone who can read</span> <span class="ae-small">'
                f'({len(sp["people"])} {"person" if len(sp["people"]) == 1 else "people"}' + (f' +{len(sp["admin"])} via admin' if sp["admin"] else "")
                + (f' +{len(sp["service"])} service' if sp["service"] else "") + ')</span>')

    def note(c):
        return tag("from policy text", "low", POLICY_TEXT + ("" if c[1] else "; the policy also checks the user or "
                                                                             "account"))

    def clear(p):
        c = p["clear"]
        if c is None:
            return '<span class="ae-muted">cannot derive from the policy text</span>'
        roles = " ".join(chip(r, "in session (hierarchy-aware)" if h == "session" else "primary role only")
                         for r, h in c[0].items()) or '<span class="ae-muted">no role</span>'
        return roles + " " + note(c)

    def rows_text(p):
        return (f'Row access policy {ui.mono(p["name"])} on {e(p["args"] or "rows")}: '
                f'{e(a.policy_text(p).split(": ", 1)[-1])} ' + (note(p["clear"]) if p["clear"] else ""))

    rows = []
    for c in cols:
        ct = [(t, v) for cc, t, v, _ in tg if cc == c]
        mp = ps["columns"].get(c, [])
        sensitive = c in a.sensitive_cols(o)
        rows.append([ui.mono(c), " ".join(ui.chip(a.tag_label(t, v), "object", sensitive=a.tag_hit(rules, t, v),
                                                  title=t) for t, v in ct if not t.upper().endswith("SEMANTIC_CATEGORY")),
                     e(", ".join(v for t, v in ct if t.upper().endswith("SEMANTIC_CATEGORY"))),
                     " ".join(ui.mono(p["name"]) for p in mp) or tag("no masking policy", "warn") * sensitive,
                     clear(mp[0]) if mp else everyone if sensitive else ""])
    body = (f'<div class="ae-path">{chips}</div>' if chips else "")
    body += "".join(f'<p>{rows_text(p)}</p>' for p in ps["rows"])
    if rows:
        body += ui.table(["Column", "Tags", "Semantic category", "Masking policy", "Clear for"], rows, min_width=640)
    html(ui.card("Sensitivity", "tags with where they come from · masking from policy text, not evaluated", body))
    bodies = {p["name"]: p["body"] for ps_ in ps["columns"].values() for p in ps_} | {p["name"]: p["body"]
                                                                                     for p in ps["rows"]}
    if bodies:
        with st.expander("Policy text", expanded=True):
            for n, b in bodies.items():
                st.code(f"-- {n}\n{b or '(not readable)'}", language="sql")


def via_html(x, plain=False):
    """"Read + write via GRP_EMEA_ALL → T_FINANCE_REPORT_WRITE, T_FINANCE_REPORT_READ": classes that share their granted
    roles merged, then the grant holders. plain: text for the CSV."""
    groups = {}
    for c, rs in x["via"].items():
        g = groups.setdefault(tuple(rs), ([], []))
        g[0].append(ui.PCLASS.get(c, c))
        g[1].extend(h for h in x["holders"][c] if h not in rs and h not in g[1])
    out = []
    for rs, (cs, hs) in groups.items():
        lab = " + ".join(cs).capitalize()
        if plain:
            out.append(f"{lab} via {', '.join(rs)}" + (f" > ... > {', '.join(hs)}" if hs else ""))
        else:
            held = f"grant held by {', '.join(hs)}" if hs else "granted role holds the grant itself"
            out.append(f'<span class="ae-small ae-tip" title="{e(held)}">{e(lab)} via</span> '
                       + " ".join(rchip(r) for r in rs))
    return " · ".join(out) if plain else "<br>".join(out)


def matrix_card(o, t, pv, active, m):
    cols = list(m[0]["privs"]) if m else []
    db, sc, nm = a.split_name(o, t)
    scols = a.sensitive_cols(o) if a.is_data(t) else []
    rpol = a.policies_of(o)["rows"] if a.is_data(t) else []
    adm = f'<span class="ae-yes bad">{ui.icon("ok", 14, 2.6)}</span>'
    rows, data = [], []
    for x in m:
        u = x["user"]
        real = any(v["has"] or v["owner"] for v in x["privs"].values())
        ds = [v["depth"] for v in x["privs"].values() if v["has"]]
        n = max(v["count"] for v in x["privs"].values())
        best = min((v["path"] for v in x["privs"].values() if v["has"]), key=len, default=None)
        st_ = x["status"]
        stag = " " + tag(st_, "warn") if st_ != "active" else ""
        if real:
            cell = strong(u, kind_label(u).split(" · ")[0] + (" · also admin" if x["admin"] else "")) + stag
        else:  # only through an admin role: no granted role path, so no depth
            ap = a.admin_paths(u, True)
            n, best = len(ap), None
            cell = strong(u, f'admin role · {", ".join(x["admin"])} inherits all', bad=True) + stag
        reads = real and any(x["privs"].get(c, {}).get("has") or x["privs"].get(c, {}).get("owner")
                             for c in a.READ_PRIVS if c in x["privs"])

        def tick(c):
            v = x["privs"][c]
            if v["has"]:
                return (f'<a class="ae-yes" href="{e(link(page="check", name=u, obj=o, priv=c))}" target="_self" '
                        f'title="{e(v["title"])}">{ui.icon("ok", 14, 2.6)}</a>')
            if v["owner"]:
                return '<span class="ae-small ae-tip" title="implied by OWNERSHIP">owner</span>'
            return adm if not real else '<span class="ae-muted">–</span>'

        dv = a.data_view(u, o, True) if reads and (scols or rpol) else None
        col_of = {c["column"]: c for c in dv["columns"]} if dv else {}

        def seen(col):
            if not dv:
                return '<span class="ae-muted">–</span>'
            return state_tag(col_of[col]) if col in col_of else tag("clear", "warn", "no masking policy")

        def rowcell():
            return state_tag(dv["rows"], ROWS_WORD[dv["rows"]["state"]]) if dv else '<span class="ae-muted">–</span>'

        sens = [seen(c) for c in scols] + ([rowcell()] if rpol else [])
        rows.append([cell] + [tick(c) for c in cols] + sens
                    + [via_html(x) if x["via"] else '<span class="ae-muted">admin role</span>',
                       ui.depth(min(ds)) if ds else tag("admin", "bad", "Only through an admin role: no granted role "
                                                                        "path, so no depth"), str(n)])
        privs = ["ALL (admin)"] if not real else [c for c in cols if x["privs"][c]["has"]] + \
            [f"{c} (owner)" for c in cols if x["privs"][c]["owner"]]
        path = arrow(best) if best else " | ".join(arrow(p) for p in a.admin_paths(u, True))
        plain = ([col_of[c]["state"] if c in col_of else "clear" if dv else "" for c in scols]
                 + ([ROWS_WORD[dv["rows"]["state"]] if dv else ""] if rpol else []))
        data.append([u, (a.profile.get(u) or {}).get("TYPE") or "PERSON", st_, db, sc, nm, ", ".join(privs)] + plain
                    + [via_html(x, True), min(ds) if ds else "", path, "", ""])
    when = str(a.run.get("FINISHED_AT"))[:16]
    extra = scols + (["Rows"] if rpol else [])
    tips = {c: f"Is {c} clear or masked for this user? " + POLICY_TEXT for c in scols} | {
        "Rows": "Does the row access policy show this user all rows? " + POLICY_TEXT}
    with st.container(key="card_matrix"):
        left, right = st.columns([4, 1], vertical_alignment="center")
        sub = ("what each person ends up with, after every role is unfolded" + (
            f" · only users with {e(pv)} (or OWNERSHIP)" if pv else "") + (" · disabled excluded" if active else "")
               + (" · column and row cells from the policy text" if extra else ""))
        html(f'<div class="ae">{ui.title("Effective access by user", sub)}</div>', left)
        if data:
            right.download_button("Export CSV", csv_text(
                ["User", "Type", "Status", "Database", "Schema", "Object", "Privileges"] + extra
                + ["Via", "Depth", "Path", "Reviewer", "Keep/Revoke"], data,
                [["Object", o, t], ["Filter", pv or "any privilege", "disabled excluded" if active else ""],
                 ["Run", a.run.get("RUN_ID"), when]]), f"{o}_{pv or 'ALL'}_{datetime.now():%Y-%m-%d}.csv",
                "text/csv", key="csv_matrix", on_click="ignore")
        html(ui.table(["User"] + cols + extra + ["Via", "Depth", "Paths"], rows, {"Paths"}, 760, tips=tips,
                      nowrap={"Depth", "Paths"} | set(cols)) if rows else
             f'<p class="ae ae-empty">No user reaches {e(o)} at any depth.</p>')
    st.caption("Click a tick to see every path on Can they?. owner: implied by OWNERSHIP. Hover a tick for the path.")


def check_page():
    if not (a.users and a.objects):
        return empty("No users or objects in this data.")
    mine = VIEW_MODE == "mine"
    tables = [x for x in a.objects if a.is_data(a.kinds[x])]
    with st.container(key="card_can"):
        c = st.columns([0.5, 2, 3], vertical_alignment="center")
        html('<div class="ae"><span class="ae-h2" style="font-size:26px;white-space:nowrap">Can</span></div>', c[0])
        with c[1]:
            u = select("User", a.users, "name", DEMO_USER if DEMO_USER in a.users else None, key="pick_user",
                       strict=True, label_visibility="collapsed")
        # default object: ?on= from the User page, else the first table or view the user reaches
        first = q("on") if q("on") in a.kinds else next((r["object"] for r in a.grants(u, True) if a.is_data(r["type"])),
                                                         tables[0] if tables else None) if u else None
        with c[2]:
            o = select("Object", a.objects, "obj", first, key="pick_obj", strict=True, label_visibility="collapsed")
        if o is not None:
            pv = radio("Privilege", a.valid_privs(a.kinds[o]), "priv", "SELECT", label_visibility="collapsed")
        st.caption("Can this user use this privilege on this object? Uses all granted roles (secondary roles ALL); the "
                   "role hierarchy is walked without a depth limit.")
    if u is None:
        return gone("name")
    if o is None:
        return gone("obj")
    r = a.can(u, pv, o)
    ps = r["paths"]
    admin = a.admin_paths(u, True)
    off = r["status"] == "disabled"
    sleep = not off and a.is_dormant(u) and not a.is_service(u)
    d = a.login_days(u)
    note = (" The user is disabled: cannot log in." if off else
            (" The user never logged in (dormant)." if d is None else f" The user has not logged in for {d} days "
                                                                       "(dormant).") if sleep else "")
    yes_text = "Yes, but the user is disabled" if off else "Yes, but the user is dormant" if sleep else ""
    if admin:
        html(ui.banner("bad", f"{e(u)} holds an admin role, which inherits every role below it",
                       admin_lines(admin) + ['<span style="font-size:12.5px">The admin route is not drawn '
                                                    'below, to keep it readable.</span>']))
    yes = bool(ps or r["owner"] or admin)
    if mine and a.is_data(a.kinds[o]):
        html(ui.banner("info", "Masking needs governance views", [
            f'My access reads only your own grants. <a href="{e(shared_link(page="check", name=u, obj=o, priv=pv))}" '
            'target="_self">See whether the columns are masked for you in the shared snapshot</a>.']))
    tone = "warn" if yes and (off or sleep) else None
    data = not mine and pv in a.READ_PRIVS and a.is_data(a.kinds[o])  # "Can read the data?" under a yes
    if not ps and r["owner"]:
        html(ui.answer(True, yes_text or "Yes, via ownership",
                       f"{e(u)} reaches OWNERSHIP of {e(o)}, which implies {e(pv)}.{note}",
                       [("Paths", len(r["owner"])), ("Shortest depth", len(r["owner"][0]) - 2)], tone))
        if data:
            read_line(u, o, r["use_role"])
        run_with(r)
        return usage_card(u, "Roles and warehouses this user ran queries with ({days} days)")
    if not ps and admin:
        html(ui.answer(True, yes_text or f"Yes, through admin role {', '.join(dict.fromkeys(x[-1] for x in admin))}",
                       f"{e(u)} can {e(pv)} {e(o)}: the admin role inherits every role, not through a granted "
                       f"role path.{note}", [("Paths", 0), ("Via admin", len(admin))], tone))
        return usage_card(u, "Roles and warehouses this user ran queries with ({days} days)")
    if not ps:
        html(ui.answer(False, "No, not through any role",
                       f"No role granted to {e(u)}, at any depth, holds {e(pv)} on {e(o)}.{note}",
                       [("Paths", 0), ("Shortest depth", "—")], "low"))
        if mine:  # My access holds only your own roles: it can't know which role to ask for
            body = (f'<p class="ae-muted">My access sees only your own roles. <a href="'
                    f'{e(shared_link(page="check", name=u, obj=o, priv=pv))}" target="_self">Open this check in the '
                    'shared snapshot</a> to see which role to ask for.</p>')
        elif r["ask"]:
            body = (f'<p>To get {e(pv)}, ask for one of: '
                    + " ".join(rchip(x["role"], f"{x['privileges']} privileges in all") for x in r["ask"][:5])
                    + '</p><p class="ae-muted">Fewest privileges first. How the first one would reach it:</p>'
                    + mpath(r["ask"][0]["path"], a.priv_class(pv, a.kinds[o]), "role"))
        elif r["closest"]:
            body = (f'<p class="ae-muted">No functional role reaches {e(pv)}. It sits with this chain:</p>'
                    + mpath(r["closest"], a.priv_class(pv, a.kinds[o])))
        else:
            body = f'<p class="ae-muted">No role holds {e(pv)} on {e(o)}.</p>'
        html(ui.card("What to ask for", "", body))
        return usage_card(u, "Roles and warehouses this user ran queries with ({days} days)")

    ends = {x["holder"] for x in ps}
    html(ui.answer(True, yes_text or f"Yes, through {plural(len(ps), 'path')}",
                   f"{e(u)} can {e(pv)} {e(o)}." + (f" Every path ends at {e(ps[0]['holder'])}." if len(ends) == 1
                                                     else "") + (" Also through an admin role." if admin else "")
                   + note, [("Paths", len(ps)), ("Shortest depth", r["shortest"])], tone))
    if data:
        read_line(u, o, r["use_role"])
    run_with(r)
    blocks = "".join(ui.block(f"Path {i}", ui.depth(x["depth"]), mpath(x["path"], a.priv_class(pv, a.kinds[o]), "user"),
                              f"{e(pv)}: {e(x['how'])}") for i, x in enumerate(ps, 1))
    if mine:
        html(ui.card("Every path", "", blocks))
    else:
        html('<div class="ae ae-two">' + ui.card("Every path", "", blocks)
             + ui.card("To remove this access", "", removal_html(u, r)) + '</div>')
    graph_card("Paths combined", *a.down_graph(u, [dict(privilege=pv, type=a.kinds[o], object=o,
                                                         paths=[x["path"] for x in ps])], user=True))
    usage_card(u, "Roles and warehouses this user ran queries with ({days} days)")


def run_with(r):
    if r["use_role"]:
        sql = f"USE ROLE {a.sql_name(r['use_role'])};" + (f" USE WAREHOUSE {a.sql_name(r['warehouse'])};"
                                                           if r["warehouse"] else "")
        html(ui.banner("info", f"Run with: {ui.mono(sql)}",
                       ["Not needed with secondary roles ALL: every granted role is active in the session."]))


def removal_html(u, r):
    opts = r["options"]
    if not opts:
        return ('<p class="ae-muted">No single grant sits on every path: each path has to be cut on its own.</p>'
                if r["paths"] else "")
    out = ['<p class="ae-muted">Fewest users losing it first. Remove in the infrastructure-as-code repo (manual changes '
           'are undone by reconciliation); the SQL is the equivalent.</p>']
    for x in opts:
        others = x["affects"] - (u in x["users"])
        both = f" · all {len(x['edges'])} needed" if len(x["edges"]) > 1 else ""
        warn = f" · {plural(others, 'other user')} lose it too" if others else ""
        out.append(f'<div class="ae-block" style="background:var(--panel)"><div class="ae-block-head">'
                   f'<span>{e(x["iac"]).replace("; ", "<br>")}</span><span class="ae-small" style="white-space:nowrap">'
                   f'{plural(x["affects"], "user")} lose{"s" * (x["affects"] == 1)} it{e(both)}{e(warn)}</span></div>'
                   f'<span class="ae-mono" style="font-size:12.5px">{e(x["sql"])}</span></div>')
    return "".join(out)


def no_tags(page=False):
    """Why there is no sensitivity data. page: the Sensitive data page also says so when the account has no tags."""
    if VIEW_MODE == "mine":
        u = a.users[0] if a.users else ""
        html(ui.banner("info", "Sensitivity needs governance views",
                       ["Tags and policies come from the governance views of the shared snapshot. My access reads only "
                        f'your own grants. <a href="{e(shared_link(page="user", name=u))}" target="_self">See it for you '
                        'in the shared snapshot</a>.']))
    elif a.run["SOURCES"].get("tags") == "UNAVAILABLE":
        html(ui.banner("info", "Sensitivity needs governance views; ask an admin",
                       ["The snapshot could not read tags (ACCOUNT_USAGE TAG_REFERENCES or INFORMATION_SCHEMA)."]))
    elif page and not a.tags:
        empty("No tags in this account. Tags need Enterprise edition; on Standard the tag view is empty.")
    elif page:
        empty(f"No table or view carries a sensitive tag ({a.SENSITIVE_TAGS}).")


def mask_text(name, o):
    """What role name sees of sensitive object o as the role in use: "EMAIL masked · PHONE clear · no rows"."""
    v = a.data_view(name, o, False)
    m = [f'{c["column"]} {c["state"]}' for c in v["columns"] if c["sensitive"]]
    m += [ROWS_WORD[v["rows"]["state"]]] * bool(v["rows"]["policy"])
    return " · ".join(m) or "whole object, clear"


def governance_line():
    """Are row access policies, masking and tags used at all in this account (counts or "not used")."""
    if VIEW_MODE != "shared":
        return
    k = a.governance_kpis()["text"]
    html(ui.profile([(lab, e(v) if v != "not used" else '<span class="ae-muted">not used</span>') for lab, v in k.items()]))


def sensitive_page():
    governance_line()
    if not SENS:
        return no_tags(True)
    rank = a.sensitive_rank()
    labels = sorted({a.tag_label(t, v) for r in rank for _, t, v, _ in r["tags"]})
    with st.container(key="card_filter"):
        c = st.columns([2, 2, 1.4], vertical_alignment="bottom")
        with c[0]:
            tg = select("Tag", [""] + labels, "tag", "", lambda x: x or "Any sensitive tag")
        with c[1]:
            db = select("Database", [""] + sorted({r["database"] for r in rank}), "db", "", lambda x: x or "Any database")
        with c[2]:
            people = flag("Enabled people only", "people", help="Leave out disabled and service users.")
    rank = [r for r in rank if (not db or r["database"] == db)
            and (not tg or tg in {a.tag_label(t, v) for _, t, v, _ in r["tags"]})]
    who = {}  # user -> objects, granted roles, shortest path
    for r in rank:
        for x, pv, p in a.who_can(r["object"]):
            if pv in a.READ_PRIVS and a.from_user(p):
                w = who.setdefault(x, dict(objs=set(), roles=set(), path=None))
                w["objs"].add(r["object"])
                w["roles"].add(p[1])
                if w["path"] is None or len(p) < len(w["path"]) - 1:
                    w["path"] = p + [r["object"]]
    stale = sorted(u for u in who if not a.is_service(u) and a.status(u) != "active")
    if people:
        who = {u: w for u, w in who.items() if not a.is_disabled(u) and not a.is_service(u)}

    def every(k):
        return set().union(*(r[k] for r in rank))

    ppl, adm = every("people"), every("admin") - set(who)
    cols = sum(len(r["cols"]) for r in rank)
    open_ = sum(n - k for k, n in (r["masked"] for r in rank))
    extra = [f"+{len(adm)} via admin"] * bool(adm) + ([] if people else
                                                      [f"+{len(every('disabled'))} disabled"] * bool(every("disabled"))
                                                      + [f"+{len(every('service'))} service"] * bool(every("service")))
    html(ui.grid([
        ui.kpi("Sensitive objects", len(rank), f"{plural(cols, 'column')} · {sum(not r['cols'] for r in rank)} whole",
               "accent", help="Sensitive"),
        ui.kpi("People who can read them", len(ppl), " · ".join(extra) or "no others",
               help="Enabled persons. Disabled and service users and admin-role holders are counted apart."),
        ui.kpi("Unmasked sensitive columns", open_, "no masking policy" if open_ else "every column masked",
               "bad" if open_ else "ok", help="Masked"),
        ui.kpi("Dormant or disabled with access", len(stale), e(", ".join(stale[:4]) + (" …" if len(stale) > 4 else "")
                                                                 or "none"), "bad" if stale else "ok", help="Dormant")],
        190))

    def tags_html(r):
        seen = {}
        for c, t, v, origin in r["tags"]:
            seen.setdefault(a.tag_label(t, v), []).append(origin + (f" {c}" if c else ""))
        return '<div class="ae-path">' + " ".join(ui.chip(k, "object", title="; ".join(dict.fromkeys(v)))
                                                  for k, v in seen.items()) + '</div>'

    def masked_cell(r):
        k, n = r["masked"]
        return "—" if not n else f"{k} of {n} masked" + ("<br>" + tag(f"{n - k} unmasked", "warn") if k < n else "")

    table_card("sensobj", "Sensitive objects, most reached first",
               f"{plural(len(rank), 'object')}" + (f" · tag {e(tg)}" if tg else "") + (f" · {e(db)}" if db else ""),
               ["Database", "Schema", "Object", "Tags", "Sensitive columns", "Masked", "Row policy", "People",
                "Roles"],
               [[ui.mono(r["database"]), ui.mono(r["schema"]), chip(r["object"], short=True), tags_html(r),
                 e(", ".join(r["cols"]) or "whole object"), masked_cell(r),
                 " ".join(f'<span class="ae-mono ae-tip" title="{e(p)}">{e(p.split(".")[-1])}</span>'
                          for p in r["row_policies"]) or '<span class="ae-muted">–</span>',
                 f'<span class="ae-tip" title="{e(", ".join(r["people"]))}">{len(r["people"])}</span>',
                 f'<span class="ae-tip" title="{e(", ".join(r["roles"]))}">{len(r["roles"])}</span>'] for r in rank],
               [[r["database"], r["schema"], r["name"], r["kind"], "; ".join(a.tag_label(t, v) + f" ({o})"
                                                                            for _, t, v, o in r["tags"]),
                 ", ".join(r["cols"]), f"{r['masked'][0]} of {r['masked'][1]} masked", ", ".join(r["row_policies"]),
                 len(r["people"]), ", ".join(r["people"]), len(r["disabled"]), len(r["service"]), ", ".join(r["admin"]),
                 ", ".join(r["roles"])] for r in rank],
               "No sensitive object matches these filters.", {"People", "Roles"}, min_width=760,
               data_cols=["Database", "Schema", "Object", "Type", "Tags", "Sensitive columns", "Masked", "Row policy",
                          "People", "People names", "Disabled", "Service", "Via admin", "Roles with read"],
               fname=f"sensitive_objects_{datetime.now():%Y-%m-%d}.csv")
    us = sorted(who, key=lambda u: (-len(who[u]["objs"]), u))
    admins = a.admin_users()
    ad = sorted(u for u in admins if u not in who and not (people and (a.is_disabled(u) or a.is_service(u))))
    sp = a.split_users(us)
    sub = " · ".join(x for x in [f'{len(sp["people"])} {"person" if len(sp["people"]) == 1 else "people"}', f"{len(sp['disabled'])} disabled" * bool(
        sp["disabled"]), f"{len(sp['service'])} service" * bool(sp["service"]), f"{len(ad)} via admin" * bool(ad)] if x)
    rows = [[strong(u, str((a.profile.get(u) or {}).get("TYPE") or "person").lower()),
             tag(a.status(u), "low" if a.status(u) == "active" else "warn") + "<br>" + login_html(u),
             f'<span class="ae-tip" title="{e(", ".join(sorted(who[u]["objs"])))}">{len(who[u]["objs"])}</span>',
             " ".join(rchip(r) for r in sorted(who[u]["roles"])), mpath(who[u]["path"], "read", "user")] for u in us]
    rows += [[strong(u, "admin role", bad=True), tag("via admin role", "bad") + "<br>" + login_html(u),
              f'<span class="ae-tip" title="every object">{len(rank)}</span>', " ".join(rchip(r) for r in admins[u]),
              mpaths(a.admin_paths(u, True), first="user")] for u in ad]
    data = [[u, (a.profile.get(u) or {}).get("TYPE") or "PERSON", a.status(u),
             (a.profile.get(u) or {}).get("LAST_SUCCESS_LOGIN") or "", len(who[u]["objs"]),
             ", ".join(sorted(who[u]["objs"])), ", ".join(sorted(who[u]["roles"])), arrow(who[u]["path"])] for u in us]
    data += [[u, (a.profile.get(u) or {}).get("TYPE") or "PERSON", "via admin role",
              (a.profile.get(u) or {}).get("LAST_SUCCESS_LOGIN") or "", len(rank), "every object (admin role)",
              ", ".join(admins[u]), " | ".join(arrow(p) for p in a.admin_paths(u, True))] for u in ad]
    table_card("sensusers", "Who can read sensitive data", sub + " · through any granted role, admin holders last"
               + (" · enabled people only" if people else ""),
               ["User", "Status", "Objects", "Through granted roles", "Shortest path"], rows, data,
               "Nobody reads these objects.", {"Objects"}, min_width=640,
               data_cols=["User", "Type", "Status", "Last login", "Objects", "Object names", "Granted roles",
                          "Shortest path"], fname=f"sensitive_readers_{datetime.now():%Y-%m-%d}.csv")
    compare_card(rank)


def compare_card(rank):
    """Two roles side by side: which sensitive objects each reads, clear or masked."""
    funcs = [r for r in a.roles if a.kind_of(r) == "functional"] or a.roles
    hits = {r: sum(o in SENS for o in a.reads([r])) for r in funcs}
    top = sorted(funcs, key=lambda r: (-hits[r], r))
    with st.container(key="card_compare"):
        html(f'<div class="ae">{ui.title("Role comparison", "pick two roles: what each can read of the sensitive data")}'
             '</div>')
        c = st.columns(2)
        with c[0]:
            x = select("Role A", a.roles, "a", top[0], key="pick_a")
        with c[1]:
            y = select("Role B", a.roles, "b", top[1] if len(top) > 1 else top[0], key="pick_b")
        got = {r: a.reads([r]) for r in (x, y)}
        tick = f'<span class="ae-yes">{ui.icon("ok", 14, 2.6)}</span>'
        rows = [[ui.mono(r["database"]), ui.mono(r["schema"]), chip(r["object"], short=True)
                 + f'<br><span class="ae-small">{e(", ".join(r["cols"]) or "whole object")}</span>']
                + [f'{tick} <span class="ae-small">{e(mask_text(n, r["object"]))}</span>' if r["object"] in got[n]
                   else '<span class="ae-muted">–</span>' for n in (x, y)] for r in rank]
        diff = [f'{chip(r["object"])}: through {chip(n)} yes; through {chip(m)} no' for r in rank
                for n, m in ((x, y), (y, x)) if r["object"] in got[n] and r["object"] not in got[m]]
        diff += [f'{chip(r["object"])}: {chip(x)} sees {e(mask_text(x, r["object"]))}; {chip(y)} sees '
                 f'{e(mask_text(y, r["object"]))}' for r in rank if r["object"] in got[x] and r["object"] in got[y]
                 and mask_text(x, r["object"]) != mask_text(y, r["object"])]
        if x == y:
            html(ui.banner("info", "Pick two different roles."))
        elif diff:
            html(ui.banner("info", "The two roles differ", diff[:10]))
        html(ui.table(["Database", "Schema", "Sensitive object", x, y], rows, min_width=640) if rows else
             '<p class="ae ae-empty">No sensitive object matches the filters.</p>')
        st.caption("Clear or masked: from the masking policy text, with the role as the role in use; not evaluated.")


def review_page():
    dbs = sorted({a.split_name(o)[0] for o in a.objects} - {""})
    if not dbs:
        return empty("No databases in this data.")
    with st.container(key="card_filter"):
        c = st.columns([2, 2, 2], vertical_alignment="bottom")
        with c[0]:
            db = select("Database", ["*"] + dbs, "db", dbs[0], lambda x: "All databases" if x == "*" else x,
                        key="pick_db", strict=True)
        every = a.review(None if db == "*" else db) if db else []
        with c[1]:
            sc = select("Schema", [""] + sorted({x["schema"] for x in every} - {""}), "schema", "",
                        lambda x: x or "Any schema")
        with c[2]:
            ob = select("Object", [""] + sorted({x["object"] for x in every if x["type"] and (not sc or x["schema"] == sc)}),
                        "object", "", lambda x: x or "Any object")
        c2 = st.columns(2)
        with c2[0]:
            active = flag("Exclude disabled users", "active")
        with c2[1]:
            noise = flag("Hide USAGE on database and schema", "hideusage", True,
                         help="On screen only: the CSV keeps every row.")
    if db is None:
        return gone("db")
    rs = [x for x in every if not (active and x["status"] == "disabled")
          and (not sc or x["schema"] == sc or not x["type"]) and (not ob or x["object"] == ob or not x["type"])]
    rs.sort(key=lambda x: (not x["type"], type_rank(x["type"] or ""), x["database"], x["schema"], x["object"],
                           x["user"]))
    real = [x for x in rs if x["type"]]
    shown = [x for x in rs if not (noise and x["type"] in ("DATABASE", "SCHEMA"))]
    where = "every database" if db == "*" else db
    html(ui.grid([
        ui.kpi("Objects", len({(x["database"], x["schema"], x["object"]) for x in real}),
               f"in {e(where)} that a user reaches", "accent"),
        ui.kpi("Users", len({x["user"] for x in real}), f"{len({x['user'] for x in real if x['status'] != 'active'})} "
               "not active"),
        ui.kpi("Rows to review", len(rs), f"{len(rs) - len(real)} admin rows · {len(rs) - len(shown)} hidden USAGE"),
        ui.kpi("Sensitive objects", len({x["object"] for x in real if x["sensitive"]}), "tagged", help="Sensitive")],
        180))
    when = str(a.run.get("FINISHED_AT"))[:16]
    cols = ["Database", "Schema", "Object", "Type", "User", "User type", "Status", "Last login", "Privileges", "Classes",
            "Sensitive", "Granted roles", "Path", "Reviewer", "Keep/Revoke"]
    keys = ["database", "schema", "object", "type", "user", "user_type", "status", "last_login", "privileges", "classes",
            "sensitive", "granted", "path", "reviewer", "decision"]
    head = (["Database"] if db == "*" else []) + ["Schema", "Object", "User", "Status", "Privileges", "Sensitive",
                                                  "Granted roles"]
    rows = [([ui.mono(x["database"])] if db == "*" else []) + [
        ui.mono(x["schema"]), (e(a.future_label(f'{x["database"]}.{x["schema"]}.{x["object"]}', x["type"]) or "")
                               or ui.mono(x["object"])) + f'<br><span class="ae-small">{e(x["type"] or "")}</span>',
        strong(x["user"], x["user_type"].lower()), tag(x["status"], "low" if x["status"] == "active" else "warn"),
        '<div style="min-width:110px">' + " ".join(ui.pclass(c) for c in x["classes"].split(", ") if c)
        + f'<br><span class="ae-small">{e(x["privileges"].replace(", ", " · "))}</span></div>',
        " ".join(tag(t.split("=", 1)[-1], "bad", t) for t in x["sensitive"].split(", ") if t)
        or '<span class="ae-muted">–</span>',
        " ".join(rchip(r) for r in x["granted"].split(", ") if r)] for x in shown]
    # the path on its own full-width line: as a column it pushed the table past the card's right edge
    subs = [f'<div class="ae-sub-path"><span class="ae-small">Path</span>'
            f'{mpath(x["path"].split(" > "), x["classes"].split(", ")[0], "user")}</div>' if x["path"] else ""
            for x in shown]
    filt = [f"schema {sc}"] * bool(sc) + [f"object {ob}"] * bool(ob) + ["disabled excluded"] * active
    table_card("review", f"Access review: {where}", f"{plural(len(shown), 'row')} shown of {len(rs)} · one per user and "
               "object · the CSV has every row and blank Reviewer and Keep/Revoke columns"
               + (" · " + e(", ".join(filt)) if filt else ""), head, rows,
               [[x[k] if x[k] is not None else "" for k in keys] for x in rs],
               f"No user reaches an object in {where}.", min_width=760, data_cols=cols, subs=subs,
               fname=f"access_review_{'ALL' if db == '*' else db}_{datetime.now():%Y-%m-%d}.csv",
               head=[["Access review", where], ["Run", a.run.get("RUN_ID"), when],
                     ["Filter", ", ".join(filt) or "all users"], ["Generated", f"{datetime.now():%Y-%m-%d %H:%M}"]])


# rule number -> (spot on the rule map, area, plain meaning, how to fix)
RULE_INFO = {
    "1": ("shortcut", "Role model", "A user or group role holds a technical role directly, skipping the functional "
          "role.", "Grant the matching functional role instead and remove the direct grant."),
    "2": ("func-object", "Role model", "A functional role holds a privilege on an object itself.",
          "Move the privilege to the technical role of that schema."),
    "3": ("loop", "Role model", "A role holds a READ role directly and also through another role it holds.",
          "Remove the direct grant; the other path keeps the access."),
    "4": ("func-tech", "Role model", "A role other than the build identity holds an OWNER role.",
          "Remove the OWNER role; grant READ or WRITE instead."),
    "13": ("func", "Role model", "A functional or group role has no users and no parent roles other than admin roles.",
           "Drop the role in the infrastructure-as-code repo, or grant it where it is needed."),
    "14": ("func", "Role model", f"A user reaches a grant through more than {a.MAX_DEPTH_RULE} roles.",
           "Flatten the chain: grant the functional role closer to the user."),
    "5": ("admin", "Admin and account", "A person holds an admin role, directly or through other roles.",
          "Remove it; do admin work through a break-glass account."),
    "12": ("admin", "Admin and account", "An admin role is the user's default role, so every session starts with it.",
           "Set a non-admin default role."),
    "9": ("public", "Admin and account", "A privilege is granted to PUBLIC, the role every user has.",
          "Grant it to the roles that need it and remove it from PUBLIC."),
    "6": ("object", "Sensitive data", "A column tagged as sensitive has no masking policy.",
          "Attach a masking policy to the column or to its tag."),
    "7": ("user", "Sensitive data", f"A disabled person, or one with no login for {a.DORMANT_DAYS} days, can still "
          "read sensitive data.", "Remove the person's roles, or drop the user."),
    "10": ("object", "Sensitive data", "A person can insert, update, delete or own a sensitive object.",
           "Leave writes to the build or a service user; give people READ."),
    "11": ("group", "Sensitive data", "Users reach a sensitive object through a group role from the identity provider.",
           "Review the group's members, or grant a reviewed functional role instead."),
    "15": ("object", "Sensitive data", "A future grant opens tables created later in a schema that holds sensitive "
           "data.", "Grant per table after classification, or confirm the future grant."),
    "17": ("write", "Read-only and write", "A role that is read-only by name or by use can write or own objects, "
           "directly or through roles it inherits.", "Remove the write grant, or the write role it inherits."),
    "18": ("tech", "Role model", "A technical role holds more or fewer privileges on an object than its capability "
           "(READ, WRITE, EXECUTE, OWNER) stands for.", "Grant the standard set to the role, or move the odd "
           "privilege to a role whose name says it."),
    "19": ("user", "Admin and account", "EXECUTE TASK, an account-level privilege, reaches a person or a consumer "
           "role.", "Keep EXECUTE TASK on the build or a service user's role."),
    "20": ("ops", "Tasks, warehouses and objects", "A role that neither owns the task nor builds can OPERATE it "
           "(start, suspend, resume).", "Remove OPERATE, or run the task from the owner or build role."),
    "21": ("ops", "Tasks, warehouses and objects", "A role that neither owns the warehouse nor builds can MODIFY or "
           "OPERATE it.", "Leave USAGE; move MODIFY and OPERATE to the owner or build role."),
    "22": ("ops", "Sensitive data", "A consumer role reads a stream on a sensitive table it cannot read itself.",
           "Remove the stream grant, or grant the table read through a reviewed role."),
    "23": ("write", "Read-only and write", "A read-only role can CREATE objects in a schema.",
           "Remove the CREATE privilege; leave object creation to the build role."),
    "8": ("user", "Users and hygiene", "A disabled user still has roles granted.", "Revoke the roles or drop the user."),
    "16": ("user", "Users and hygiene", f"A person with no login for {a.DORMANT_DAYS} days (or never) still holds "
           "roles.", "Revoke the roles or disable the user."),
}
AREAS = ["Role model", "Admin and account", "Sensitive data", "Read-only and write", "Tasks, warehouses and objects",
         "Users and hygiene"]


def rules_page(rows):
    gs = {x["grantee"] for x in rows}
    who = q("grantee") if q("grantee") in gs else ""
    if q("grantee") and not who:
        html(ui.banner("info", f"No rule findings for {e(q('grantee'))}."))
    mine = [x for x in rows if not who or x["grantee"] == who]
    count = {n: sum(x["num"] == n for x in mine) for n in a.RULES}
    sev = q("sev") if q("sev") in SEVS + ["Passing"] else ""
    sel = q("rule") if q("rule") in a.RULES else ""

    def lvl(n):
        return a.SEVERITY.get(n, "Low")

    def go(**kw):
        return link(page="rules", grantee=who, **kw)

    if who:
        html(ui.banner("info", f"Findings for {chip(who)} · <a href=\"{e(link(page='rules', sev=sev))}\" "
                               "target=\"_self\">show everyone</a>"))
    passing = [n for n in a.RULES if not count[n]]
    html(ui.strip([(ui.dot(s, True), sum(count[n] for n in a.RULES if lvl(n) == s), go(sev="" if sev == s else s),
                    sev == s) for s in SEVS]
                  + [(f'<span class="ae-sevdot">{ui.icon("ok", 13, 2.6)}Passing</span>', len(passing),
                      go(sev="" if sev == "Passing" else "Passing"), sev == "Passing")]))
    st.caption("Findings per severity, and the number of rules with no findings. Click one to filter.")

    items = [(n, RULE_INFO[n][0], lvl(n), count[n], go(rule="" if sel == n else n),
              f"Rule {n} ({lvl(n)}): {a.RULES[n][0]} · {plural(count[n], 'finding')}") for n in a.RULES]
    html(ui.card("Rule map", "where each rule sits in the role model", ui.rule_map(items, THEME, sel)
                 + ui.how(ui.MAP_HOW)))

    order = {s: i for i, s in enumerate(SEVS)}
    keep = [n for n in a.RULES if not sev or (sev == "Passing" and not count[n]) or lvl(n) == sev]
    top = max(count.values(), default=0)

    def row(n):
        ex = next((x for x in mine if x["num"] == n), None)
        example = (f'{chip(ex["grantee"], kind=ex["kind"])}&nbsp;<span class="ae-mono" style="font-size:12.5px">{e(ex["detail"])}</span>'
                   if ex else '<span class="ae-muted">No finding in this snapshot.</span>')
        body = (f'<p><b>What it means:</b> {e(RULE_INFO[n][2])}</p><p><b>Why it matters:</b> {e(a.RULES[n][1])}</p>'
                f'<p><b>How to fix:</b> {e(RULE_INFO[n][3])} Change it in the infrastructure-as-code repo.</p>'
                f'<p><b>Example:</b> {example}</p>'
                + (f'<p><a href="{e(go(rule=n))}" target="_self">Show the {plural(count[n], "finding")}</a></p>'
                   if count[n] else ""))
        return ui.rule_row(n, lvl(n), a.RULES[n][0], count[n], top, RULE_INFO[n][2], body, sel == n, sel == n)

    out = []
    for area in AREAS:
        ns = sorted((n for n in keep if RULE_INFO[n][1] == area and count[n]), key=lambda n: (order[lvl(n)], -count[n]))
        if ns:
            out.append(f'<p class="ae ae-rgroup">{e(area)}</p>' + "".join(row(n) for n in ns))
    off = [n for n in keep if not count[n]]
    if off:
        out.append(f'<details class="ae"{" open" if sev == "Passing" or sel in off else ""}><summary class="ae-rgroup" '
                   f'style="cursor:pointer">Passing ({len(off)})</summary>' + "".join(row(n) for n in off)
                   + '</details>')
    html(ui.card("Rules", f"{len(a.RULES)} rules · grouped by area · most severe first · open a row for what it "
                          "means and how to fix", f'<div>{"".join(out)}</div>' if out else '<p class="ae-empty">No rule matches.</p>'))

    shown = [x for x in mine if (not sev or x["severity"] == sev) and (not sel or x["num"] == sel)]
    unknown = sorted(o for o in SENS if any(a.row_terms(p) is None for p in a.policies_of(o)["rows"]))
    if unknown and not who:
        html(ui.banner("info", f"Not a finding: {plural(len(unknown), 'sensitive table')} with a row access policy "
                               "whose rows can't be derived from the policy text",
                       [" ".join(chip(o) for o in unknown) + '&nbsp;<span class="ae-small">readable, rows unknown: the '
                        'policy looks rows up (e.g. in a mapping table). Check the policy, not the grants.</span>']))
    admins_card()

    groups = {}  # the same fix for several grantees of one rule (rule 10 for 14 FIN users): one row
    for x in shown:
        groups.setdefault((x["num"], x["sql"]) if x["sql"] else id(x), []).append(x)

    def fix(x):
        if not x["iac"]:
            return ""
        same = f' {tag("same fix as " + x["same_fix"], "low")}' if x["same_fix"] else ""
        sql = f'<br><span class="ae-mono" style="font-size:12px">{e(x["sql"])}</span>' if x["sql"] else ""
        return (f'<div class="ae-fix"><span class="ae-small">Fix</span> <span style="font-size:12.5px">{e(x["iac"])}'
                f'</span>{same}{sql}</div>')

    def who_cell(xs):
        if len(xs) == 1:
            return chip(xs[0]["grantee"], kind=xs[0]["kind"])
        return (f'<details><summary class="ae-tip">{plural(len(xs), "grantee")}</summary><div class="ae-path">'
                + " ".join(chip(x["grantee"], kind=x["kind"]) for x in xs) + '</div></details>')

    what = ([f"rule {sel}"] if sel else []) + ([sev] if sev else []) + ([who] if who else [])
    gs = list(groups.values())
    now = datetime.now()
    table_card("findings", "Findings", f"{len(shown)} across {plural(len({x['num'] for x in shown}), 'rule')} · "
               f"{len(gs)} rows (same fix merged)" + (" · " + e(", ".join(what)) if what else "")
               + (f' · <a href="{e(link(page="rules"))}" target="_self">clear filters</a>' if what else ""),
               ["Rule", "Grantee", "Detail", "Path", "Affects"],
               [[f'{ui.dot(xs[0]["severity"], True)}<br><span class="ae-tip ae-rt" title="{e(xs[0]["why"])}">'
                 f'{e(xs[0]["num"])} · {e(xs[0]["title"])}</span>',
                 who_cell(xs), f'<span class="ae-det">{wbr(xs[0]["detail"])}</span>'
                 + (f'<br><span class="ae-small">and {len(xs) - 1} more like it</span>' if len(xs) > 1 else ""),
                 mpaths(xs[0]["paths"], edge_cls(xs[0]), top=2,
                        first=xs[0]["kind"] if all(p[0] == xs[0]["grantee"] for p in xs[0]["paths"]) else None),
                 f'<span class="ae-tip" title="users who lose access when the fix is applied, net of their other '
                 f'paths">{e(xs[0]["impact"])}</span>'] for xs in gs],
               [[x["num"], x["title"], x["severity"], x["grantee"], x["detail"], x["iac"], x["sql"],
                 "" if x["affects"] is None else x["affects"], x["same_fix"], " | ".join(arrow(p) for p in x["paths"])]
                for x in shown],
               "No findings for this selection." if what else "No rule findings in this data.", (),
               min_width=720, data_cols=["Rule", "Title", "Severity", "Grantee", "Detail", "Fix", "SQL",
                                         "Affects users", "Same fix", "Paths"],
               fname=f"findings_{sev or 'all'}_{now:%Y-%m-%d}.csv",
               head=[["Rule checks", ", ".join(what) or "all"], ["Run", a.run.get("RUN_ID"),
                                                                 str(a.run.get("FINISHED_AT"))[:16]],
                     ["Generated", f"{now:%Y-%m-%d %H:%M}"]],
               subs=[fix(xs[0]) for xs in gs], nowrap={"Grantee", "Affects"})


def admins_card():
    """Users holding an admin role or an account-level privilege, service users included."""
    people, now = a.admin_people(), datetime.now()
    html('<div id="admins"></div>')
    table_card("admins", "People with admin roles", "admin roles and account-level privileges · service users "
               "included · with the chain",
               ["User", "Admin roles", "Account privileges", "Chain", "Status", "Last login"],
               [[strong(x["user"], "service" if x["service"] else "person"), " ".join(rchip(r) for r in x["roles"])
                 or '<span class="ae-muted">–</span>',
                 " ".join(ui.pclass("admin", pv) for pv in dict.fromkeys(pv for pv, _ in x["account"]))
                 or '<span class="ae-muted">–</span>',
                 mpaths(x["paths"] + [p for _, p in x["account"]], first="user", top=4),
                 tag(x["status"], "bad" if x["status"] != "active" else "low")
                 + (" " + tag("service", "low") if x["service"] else ""), login_html(x["user"])] for x in people],
               [[x["user"], "SERVICE" if x["service"] else "PERSON", ", ".join(x["roles"]),
                 ", ".join(dict.fromkeys(pv for pv, _ in x["account"])),
                 " | ".join(arrow(p) for p in x["paths"] + [p for _, p in x["account"]]), x["status"],
                 x["last_login"] or ""] for x in people],
               "No user holds an admin role or an account-level privilege.", min_width=860,
               data_cols=["User", "Type", "Admin roles", "Account privileges", "Chain", "Status", "Last login"],
               fname=f"admins_{now:%Y-%m-%d}.csv",
               head=[["People with admin roles"], ["Run", a.run.get("RUN_ID"), str(a.run.get("FINISHED_AT"))[:16]],
                     ["Generated", f"{now:%Y-%m-%d %H:%M}"]])


# ---------- frame ----------

def topbar(page, names):
    """Returns the link popover's slot: main fills it after the page ran, so the link has the page's last filters."""
    c = st.columns([3, 3, 0.4, 0.4], vertical_alignment="center")
    html(ui.crumb(PAGES[page]), c[0])
    c[1].selectbox("Find", names, index=None, key="find", on_change=find, label_visibility="collapsed",
                   placeholder="Find a user, role or object",
                   format_func=lambda n: f"{a.node_name(n)}  ·  {kind_label(a.node_name(n), a.node_kind(n))}"
                   + ("  ·  sensitive" if n in SENS else ""))
    slot = c[2].popover("", icon=":material/link:", help="Copy a link to this view").empty()
    c[3].button("", key="theme", on_click=flip, help="Switch light / dark",
                icon=":material/light_mode:" if THEME == "dark" else ":material/dark_mode:")
    return slot


def share(slot):
    qs = {k: v for k, v in st.query_params.items() if k != "theme"}
    slot.code(str(st.context.url or "").split("?")[0] + "?" + urlencode(qs), language=None)


def snap_time():
    """ "2026-11-02 07:00 UTC · 13 h ago" and whether it is older than 24 h."""
    v = a.run.get("FINISHED_AT")
    if isinstance(v, datetime) and v.tzinfo:
        v = v.astimezone(timezone.utc)
    t = a.when(v)
    if t is None:
        return str(v), False
    h = max(0, (datetime.now(timezone.utc).replace(tzinfo=None) - t).total_seconds() / 3600)
    return f"{t:%Y-%m-%d %H:%M} UTC · " + (f"{h:.0f} h ago" if h < 48 else f"{h / 24:.0f} days ago"), h > 24


@st.cache_resource
def lock():
    """access.py keeps its lookups in module globals, shared by every session (thread): build + render under one lock."""
    return threading.Lock()


VIEW = {"user": user_page, "role": role_page, "object": object_page, "sensitive": sensitive_page, "check": check_page,
        "rules": None, "review": review_page}
SHARED_ONLY = {"rules", "review"}  # pages about everyone: not in My access


def fresh():
    """Dev: Streamlit drops a changed module only while a browser tab watches it, so an edit made with no tab open kept
    the old ui/access until a restart. Reload a module whose file is newer than the copy in memory (never in a deployed
    app, whose files don't change), under the lock so no other session renders half-reloaded lookups."""
    with lock():
        for m in (a, ui):
            if os.path.getmtime(m.__file__) > m.LOADED:
                importlib.reload(m)


def main():
    global THEME, VIEW_MODE, ROWS, SENS, BREAKS
    st.set_page_config("Snowflake access explorer", layout="wide", initial_sidebar_state="auto")
    fresh()
    THEME = theme()
    html(ui.css(THEME))
    sb = st.sidebar
    html(ui.brand(), sb)
    html('<p class="ae ae-label" style="margin-top:14px">Data</p>', sb)
    init("f_data", "data", "shared", list(VIEWS))
    with sb:
        view = st.radio("Data", list(VIEWS), key="f_data", format_func=VIEWS.get, label_visibility="collapsed")
    VIEW_MODE = view
    if view == "shared":
        st.query_params.pop("data", None)
    page = q("page") if q("page") in VIEW and not (view == "mine" and q("page") in SHARED_ONLY) else "user"
    st.query_params["page"] = page
    nav = sb.container()
    card = sb.container(key="card_snap")
    snap, notes = card.empty(), card.container()
    with sb.expander("Glossary"):
        html(ui.glossary())
    top = st.container()
    head = HEAD[page]
    if view == "mine" and page == "user":
        head = ("My access", "What can I reach?", "Your own roles, read live with your own rights. Nothing is saved.")
    html(ui.header(*head))
    body = st.empty()
    html(ui.skeleton(), body)
    d = load(view, card)
    with lock():
        if d is not None:  # the shared snapshot is built once per run; My access every time (it is per viewer)
            a.build(d, ("shared", d["run"].get("RUN_ID"), str(d["run"].get("FINISHED_AT"))) if view == "shared" else None)
        SENS = a.cached("sens", a.sensitive) if d is not None else {}
        rows = ROWS = a.cached("rows", a.rule_rows) if d is not None and a.roles else []
        BREAKS = a.cached("breaks", lambda: breaks(rows, a.cached("ro", a.readonly_writes))) if rows else {}
        badge = {"rules": len(rows), "sensitive": len(SENS)}
        html(ui.nav([(PAGES[k], link(page=k), badge.get(k) or None) for k in PAGES
                     if k in VIEW and not (k in SHARED_ONLY and view == "mine")], PAGES[page]), nav)
        if d is not None:
            src = a.run["SOURCES"] or {"all": "fake data"}
            when, old = snap_time() if view == "shared" else ("live", False)
            html(ui.snapshot_card("live" if view == "mine" else WHERE if MODE == "snowflake" else MODE, when,
                                  list(src.items())), snap)
            if old:
                html(ui.banner("warn", "Snapshot older than 24 h"), notes)
            for k, v in a.run["NOTES"].items():
                html(ui.banner("warn", f"Incomplete: {e(k.replace('_', ' '))}"), notes)
                with notes.expander("Details"):
                    st.caption(str(v))
        # graph node ids (a.uid), so a role named like a user is listed too
        names = [a.uid(u, True) for u in a.users] + a.roles + a.objects if d is not None else []
        with top:
            slot = topbar(page, names)
        if d is None:
            body.empty()
            return share(slot)
        a.capped.clear()
        with body.container():
            if view == "mine":
                html(ui.banner("info", "Only your own roles: <span style='font-weight:400'>Object shows what your "
                                       "roles reach, not everyone.</span>"))
            cap = st.empty()
            if not a.roles:
                empty("No grants in this data.")
            elif page == "rules":
                rules_page(rows)
            else:
                VIEW[page]()
            if a.capped:
                html(ui.banner("warn", f"Stopped at {a.MAX_HOPS} role hops", [
                    f"The walk from {e(', '.join(sorted(a.capped)))} hit the safety cap (MAX_HOPS). Paths deeper than "
                    "that are not shown."]), cap)
        share(slot)


main()
