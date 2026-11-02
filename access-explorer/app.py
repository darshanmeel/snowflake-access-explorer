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


def find():
    """Global search: go to the page of the picked entity, with that page's own filters reset."""
    n = st.session_state.find
    if not n:
        return
    for k in [k for k in st.session_state if k.startswith(("f_", "pick_")) and k != "f_data"]:
        del st.session_state[k]
    with lock():  # a callback runs before main takes the lock; page_of reads the shared lookups
        page = page_of(n)
    st.query_params.from_dict(kept() | {"page": page, "name": n})
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


def chip(n, title="", short=False):
    """short: an object as its own name only (DB and schema sit in their own columns); the full name in the title."""
    k = a.kinds.get(n, "")
    lab = a.future_label(n, k)
    if lab:
        title = title or "applies to objects created later"
    elif short and a.kind_of(n) == "object":
        lab, title = a.split_name(n)[2], title or n
    return ui.chip(n, a.kind_of(n), href(n), sensitive=n in SENS, disabled=a.is_disabled(n), title=title, label=lab)


def chain(p, cut=False):
    """Chips joined by chevrons; cut: over 5 chips, "first, …N roles…, last 2" (full path on hover)."""
    parts = [chip(x) for x in p]
    if cut and len(p) > 5:
        parts = parts[:1] + [f'<span class="ae-small ae-tip" title="{e(arrow(p))}">…{len(p) - 3} roles…</span>'] \
            + parts[-2:]
    return '<div class="ae-path">' + ui.icon("chev", 12, 2.5).join(parts) + '</div>'


def strong(n, caption="", bad=False):
    cap = f'<br><span class="ae-small{" ae-ink-bad" if bad else ""}">{e(caption)}</span>' if caption else ""
    return (f'<a class="ae-strong" style="color:var(--ink);text-decoration:none" href="{e(href(n))}" '
            f'target="_self">{e(n)}</a>{cap}')


def kind_label(n):
    k = a.kind_of(n)
    if k == "user":
        p = a.profile.get(n) or {}
        s = a.status(n) if n in a.profile else ""
        return "User · " + str(p.get("TYPE") or "person").lower() + (f" · {s}" if s and s != "active" else "")
    return KIND[k]


def arrow(p):
    return " > ".join(p)


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


def pv_cell(r):
    return ui.pclass(r["cls"], r["privilege"])


def obj_cell(o, k, name):
    if k.startswith("FUTURE"):
        what = k.split(" ", 1)[1].lower() + "s"
        return (f'<span class="ae-tip" title="applies to {e(what)} created later">All future {e(what)} in '
                f'{e(o.rsplit(".", 1)[0])}</span>')
    return (f'<a class="ae-mono" style="color:var(--ink);text-decoration:none" href="{e(href(o))}" '
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
               subs=None):
    """Card with title, Export CSV and a table. data: plain rows for the CSV (columns data_cols or cols);
    none: sentence when empty; subs: a full-width line under each row (ui.table)."""
    with st.container(key="card_" + key):
        left, right = st.columns([4, 1], vertical_alignment="center")
        html(f'<div class="ae">{ui.title(title, sub)}</div>', left)
        if data:
            right.download_button("Export CSV", csv_text(data_cols or cols, data, head), fname or f"{key}.csv",
                                  "text/csv", key="csv_" + key, on_click="ignore")
        html(ui.table(cols, rows, numeric, min_width, nowrap=NARROW, subs=subs) if rows else
             f'<p class="ae ae-empty">{e(none)}</p>')


def marks(names, bad=()):
    """Graph node markers: disabled user, sensitive object, bad (e.g. the role a read-only role writes through)."""
    out = {n: {f for f, on in (("disabled", a.is_disabled(n)), ("sensitive", n in SENS), ("bad", n in bad)) if on}
           for n in names}
    return {n: f for n, f in out.items() if f}


def edge_tip(x, y, cls, privs, back):
    """Hover text of a graph edge x -> y in plain words, plus the rules it breaks."""
    if cls == "inherit":
        s = (f"Role {y} is granted to user {x}" if a.kind_of(x) == "user" else
             f"Role {y} is granted to role {x}: {x} inherits all its privileges")
        s += f"\n{y} is drawn once, at its shortest depth" if back else ""
    else:
        s = f"{x} has {', '.join(privs)} on {a.kinds.get(y, 'object').lower()} {y} ({ui.PCLASS[cls].lower()})"
    return "\n".join([s] + BREAKS.get((x, y, cls), []))


def node_label(n):
    """Graph box text for a future grant: ("future tables", "SALES.CORE"); None for every other name."""
    k = a.kinds.get(n, "")
    return (f"future {k.split(' ', 1)[1].lower()}s", n.rsplit(".", 1)[0]) if k.startswith("FUTURE") else None


def node_tip(n):
    """Kind and rule findings of a graph node, under its name in the hover text."""
    k = (a.kinds.get(n, "Object").capitalize() if a.kind_of(n) == "object" else kind_label(n))
    fs = [f'Rule {x["num"]} ({x["severity"]}): {x["title"]}' for x in ROWS if x["grantee"] == n]
    return "\n".join([k] + fs[:5] + ([f"+{len(fs) - 5} more findings"] if len(fs) > 5 else []))


def breaks(rows, ro):
    """{(x, y, cls): ["Rule N (severity): title"]} for the graph edges a rule finding points at."""
    out = {}
    for x in rows:
        for g in x["edges"]:
            cls = "inherit" if g["priv"] is None else a.priv_class(g["priv"], g["kind"] or "")
            out.setdefault((g["grantee"], g["to"], cls), {})[f'Rule {x["num"]} ({x["severity"]}): {x["title"]}'] = 1
    for x in ro:  # rule 17: the write arrow out of a read-only role
        for pv in x["privileges"]:
            k = (x["holder"], x["object"], a.priv_class(pv, a.kinds.get(x["object"], "")))
            out.setdefault(k, {})[f'Rule 17 ({a.SEVERITY["17"]}): {a.RULES["17"][0]}'] = 1
    return {k: list(v) for k, v in out.items()}


def graph_card(title, lanes, edges, notes=None, selected=None, sub="", bad=()):
    """Graphs over 4 lanes (wider than the card at full size) start fitted, so the answer on the right is in view."""
    with st.container(key="card_graph"):
        left, right = st.columns([4, 1.2], vertical_alignment="center")
        html(f'<div class="ae">{ui.title(title, sub)}</div>', left)
        with right:
            fit = flag("Fit to width", "fit", len(lanes) > 4, toggle=True,
                       help="Scale the whole graph into the card (scrolls below a readable size). Off: full size, "
                            "scroll sideways.")
        names = {n for _, ns in lanes for n in ns}
        html(ui.legend(edges=True, marks=True, extra={c for e_ in edges for c in e_[2:3]}))
        html(ui.lane_graph(lanes, edges, a.kind_of, THEME, href, selected, expand=q("expand"),
                           query=dict(st.query_params), fit=fit, marks=marks(names, bad), notes=notes,
                           edge_tip=edge_tip, node_tip={n: node_tip(n) for n in names}, label=node_label))
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


def admin_lines(paths, user=False):
    """Admin paths grouped per start: "ADMIN_01: SECURITYADMIN; F_SECURITY > SYSADMIN" (chips)."""
    per = a.group((p[0], p) for p in paths)
    return [strong(u) + ":&nbsp;" + "; ".join(chain(p[1:]) for p in ps) if user else
            "; ".join(chain(p) for p in ps) for u, ps in per.items()]


def findings_banner(name, skip=()):
    """Rule findings of name and, for a user, of the roles granted to it directly ("via GRP_ANALYSTS")."""
    if VIEW_MODE != "shared":
        return
    via = set(a.roles_of.get(name, [])) if a.kind_of(name) == "user" else set()
    xs = [x for x in ROWS if (x["grantee"] == name or x["grantee"] in via) and x["num"] not in skip]
    if xs:
        lines = [f'{ui.dot(x["severity"])}&nbsp;<b>Rule {e(x["num"])}</b>&nbsp;{e(x["title"])}'
                 + (f'&nbsp;via {chip(x["grantee"])}' if x["grantee"] != name else "") + ': '
                 f'<span class="ae-mono" style="font-size:12.5px">{e(x["detail"])}</span>' for x in xs[:6]]
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
        rows = [r for r in every if not data_only or not (r["privilege"] == "USAGE" and r["type"] in ("DATABASE", "SCHEMA"))]
        rows.sort(key=lambda r: (type_rank(r["type"]), r["object"], r["privilege"]))
        with top[1]:
            o = select("Only on object", [""] + sorted({r["object"] for r in rows}), "on", "",
                       lambda x: x or "Any object")
        rows = [r for r in rows if not o or r["object"] == o]
        with top[2]:
            pv = select("Only privilege", [""] + sorted({r["privilege"] for r in rows}), "priv", "",
                        lambda x: x or "Any privilege")
        rows = [r for r in rows if not pv or r["privilege"] == pv]
    p = a.profile.get(u) or {}
    reach = a.reach(u, True, only_default, limit)
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
    findings_banner(u)

    mark = login(u)[1]
    sec = str(p.get("DEFAULT_SECONDARY_ROLES") or "")
    html(ui.profile([
        ("Type", e(str(p.get("TYPE") or "—").capitalize())),
        ("Status", '<span class="ae-ink-bad">Disabled</span>' if a.is_disabled(u)
         else '<span class="ae-ink-ok">Enabled</span>'),
        ("Default role", chip(p["DEFAULT_ROLE"]) if p.get("DEFAULT_ROLE") else "—"),
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
    lines = admin_lines(admin) + [f'<span class="ae-mono">{e(x)}:</span>&nbsp;{chain(y)}' for x, y in acct]
    if lines:
        html(ui.banner("bad", "Reaches an admin role, which inherits every role below it" if admin
                       else "Holds account-level privileges", lines))

    walked = [] if o or pv else a.walk(u, True, only_default, limit)
    g = a.down_graph(u, rows, walked)
    if g:
        graph_card("Role hierarchy, by depth", *g)
    else:
        html(ui.card("Role hierarchy, by depth", "", f'<p class="ae-empty">{e(u)} reaches no roles at this depth.</p>'))

    table_card("privileges", "Privileges", f"{len(rows)} privileges · {sum(r['count'] for r in rows)} paths · "
                                           "shortest path shown" + (" · data only" if data_only else ""),
               ["Privilege", "Type", "Database", "Schema", "Object", "Use role", "Depth", "Path", "Paths"],
               [[pv_cell(r), f'<span class="ae-small">{e(r["type"])}</span>', ui.mono(r["database"]),
                 ui.mono(r["schema"]), obj_cell(r["object"], r["type"], r["name"]), chip(r["granted"]),
                 ui.depth(r["depth"]), chain(r["path"][:-1], True), str(r["count"])] for r in rows],
               [[r["privilege"], r["cls"], r["type"], r["database"], r["schema"], r["name"], r["granted"], r["depth"],
                 arrow(r["path"]), r["count"]] for r in rows],
               f"{u} holds no privileges{' on ' + o if o else ''} at this depth.", {"Paths"}, min_width=1040,
               data_cols=["Privilege", "Class", "Type", "Database", "Schema", "Object", "Use role", "Depth", "Path",
                          "Paths"],
               fname=f"{u}_privileges.csv", head=[["User", u, a.status(u)]])
    multi = [(r, x) for r in rows if r["count"] > 1 for x in r["paths"]]
    if multi:
        with st.expander(f"Every path of the {plural(twice, 'privilege')} reached more than once"):
            html(ui.table(["Privilege", "Object", "Depth", "Path"],
                          [[pv_cell(r), ui.mono(r["object"]), ui.depth(a.depth(x[:-1], True)), chain(x[:-1])]
                           for r, x in multi], min_width=760))
    sensitive_card(u)
    granted_card(u)


def granted_card(u):
    """Roles granted to the user directly, with use in the query history (F5)."""
    src, days = a.run["SOURCES"].get("usage"), usage_days()
    use, dr = a.used_roles(u), (a.profile.get(u) or {}).get("DEFAULT_ROLE")
    rs = sorted(a.roles_of.get(u, []))
    cell = (lambda r: "not readable") if src == "UNAVAILABLE" else (
        lambda r: f"{use[r]['queries']} queries · {str(use[r]['last_used'])[:10]}" if r in use else "not used")
    table_card("granted", "Granted roles", f"granted to {e(u)} directly · use from the query history",
               ["Role", "Kind", "Default", f"Used ({days} d)"],
               [[chip(r), e(KIND.get(a.kind_of(r), "Group role")), "default role" if r == dr else "",
                 e(cell(r))] for r in rs],
               [[r, a.kind_of(r), r == dr, cell(r)] for r in rs], f"No roles granted to {u}.", min_width=560)
    usage_card(u, "Roles and warehouses used")


def masks(row):
    """Short text of a sensitive_reach row: "EMAIL masked · PHONE clear · rows ?"."""
    m = [f"{c} {v}" for c, v in row["masked"].items()]
    if row["rows"] and a.policies_of(row["object"])["rows"]:
        m.append(f"rows {row['rows']}")
    return " · ".join(m) or "whole object, clear"


def sensitive_card(u):
    """Sensitive data per granted role: one column per depth-1 role, a tick plus clear/masked."""
    if not SENS:
        no_tags()
        return
    rs = a.sensitive_reach(u)
    got = [x for x in rs if x["path"]]
    if not got:
        return
    objs = list(dict.fromkeys(x["object"] for x in got))
    cell = {(x["object"], x["role"]): x for x in got}
    # only roles that reach sensitive data: PUBLIC (expected to reach nothing) would add an all-dash column
    roles = [r for r in dict.fromkeys(x["role"] for x in rs) if any((o, r) in cell for o in objs)]
    per = [f"through {chip(r)}: {plural(sum(1 for o in objs if (o, r) in cell), 'sensitive object')}" for r in roles]
    diff = [f'{chip(o, short=True)}: through {", ".join(chip(r) for r in roles if (o, r) in cell)}; not through '
            f'{", ".join(chip(r) for r in roles if (o, r) not in cell)}' for o in objs
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
    with st.expander("Paths to sensitive data"):
        html(ui.table(["Object", "Granted role", "Path"], [[chip(x["object"]), chip(x["role"]), chain(x["path"])]
                                                            for x in got], min_width=760))


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
    k = s["kind"]
    prefix = {"functional": a.FUNC, "technical": a.TECH}.get(k)
    owner = [g for g, pv, t in a.on.get(r, []) if pv == "OWNERSHIP" and t == "ROLE"]
    admin_role = r in a.ADMIN
    eff_cap = ("inherits every role below it" if admin_role else
               f"inherited from {plural(len(s['holds_roles']), 'role')} it holds" if s["holds_roles"] else "no roles held")
    html(ui.grid([
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
            + (f'via {chip(x["holder"])} (inherited)' if x["inherited"] else "granted directly")
            + f'&nbsp;<span class="ae-small">heuristic: {e(x["how"])}'
            + (f' · mostly read: {x["read_only"]} of {x["objects"]} objects read-only' if x["how"] != "name" else "")
            + '</span>' for x in ro]))
    admin, acct = a.admin_paths(r), a.account_privs(r)
    lines = [chain(x) for x in admin] + [f'<span class="ae-mono">{e(pv)}:</span>&nbsp;{chain(x)}' for pv, x in acct]
    if lines:
        html(ui.banner("bad", "Holds an admin role, which inherits every role below it" if admin
                       else "Holds account-level privileges", lines))
    findings_banner(r, skip={"17"} if ro else ())
    if s["holds_roles"]:
        html(ui.card("Holds roles", f"direct grants: {s['privileges']} · it gets everything these roles hold",
                     '<div class="ae-path">' + " ".join(chip(x) for x in s["holds_roles"]) + '</div>'))

    lanes, edges, notes, sel = a.role_graph(r, up, ro)
    graph_card("Held by (up) and holds (down)", lanes, edges, notes, sel, bad={x["holder"] for x in ro})
    held_card(r, up, only_users)
    table_card("holds", "Holds (down)", f"direct grants: {len(hold)}",
               ["Privilege", "Type", "Database", "Schema", "Object"],
               [[pv_cell(h), f'<span class="ae-small">{e(h["type"])}</span>', ui.mono(h["database"]),
                 ui.mono(h["schema"]), obj_cell(h["object"], h["type"], h["name"])] for h in hold],
               [[h["privilege"], h["cls"], h["type"], h["database"], h["schema"], h["name"]] for h in hold],
               f"{r} holds no privileges of its own" + (": see Effective privileges." if s["holds_roles"] else "."),
               min_width=560, data_cols=["Privilege", "Class", "Type", "Database", "Schema", "Object"])
    eff = [] if admin_role else [x for x in a.grants(r) if not only_sens or x["object"] in SENS]
    eff.sort(key=lambda x: (type_rank(x["type"]), x["object"], x["privilege"]))
    table_card("effective", "Effective privileges (inherited)", f"{len(eff)} privileges · own grants and every "
               "role it holds" + (" · sensitive only" if only_sens else ""),
               ["Privilege", "Type", "Database", "Schema", "Object", "Depth", "Path"],
               [[pv_cell(x), f'<span class="ae-small">{e(x["type"])}</span>', ui.mono(x["database"]),
                 ui.mono(x["schema"]), obj_cell(x["object"], x["type"], x["name"]), ui.depth(x["depth"]),
                 chain(x["path"][:-1], True)] for x in eff],
               [[x["privilege"], x["cls"], x["type"], x["database"], x["schema"], x["name"], x["depth"],
                 arrow(x["path"])] for x in eff],
               f"{r} is an admin role: it inherits every role below it (hierarchy hidden)." if admin_role else
               f"{r} reaches no {'sensitive ' if only_sens else ''}privileges.", min_width=900,
               data_cols=["Privilege", "Class", "Type", "Database", "Schema", "Object", "Depth", "Path"])


def held_card(r, up, only_users):
    """Held by (up), full width, with "If revoked from": who loses r, and which privileges, net of other paths."""
    direct = sorted(set(a.held_by.get(r, [])) | set(a.users_of.get(r, [])))
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
                    lost.add(x["grantee"])
                    if x["kind"] == "user":
                        loses[x["grantee"]] = a.loses(x["grantee"], cut, r)
            iac, sql = a.fix_text([a.role_edge(cut, r, a.kind_of(cut) == "user")])
            html(ui.banner("warn", f"Revoking {e(r)} from {e(cut)}: {plural(len(lost), 'grantee')} lose it, "
                                   f"{plural(len(loses), 'user')} among them", [e(iac), ui.mono(sql)]))
        cols = ["Grantee", "Depth", "Only via", "Path", "Paths"] + (["Loses"] if cut else [])
        rows = []
        for x in up:
            g = x["grantee"]
            cap = kind_label(g) + (" · granted directly" if x["direct"] else "")
            row = [strong(g, cap) + (" " + tag("loses it", "bad") if g in lost else ""), ui.depth(x["depth"]),
                   " ".join(chip(n) for n in x["only_via"]) or '<span class="ae-muted">–</span>',
                   chain(x["path"], True), str(x["count"])]
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
            t = select("Type", types, "type", a.kinds.get(q("name"), "TABLE"))
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
                       admin_lines(adm, True) + ['<span style="font-size:12.5px">Not drawn in the hierarchy below, to '
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
        ui.kpi("Owner", " ".join(chip(x) for x in s["owners"]) or "—",
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
    with st.expander("All grantees (roles and users)", expanded=False):
        merged = {}
        for x in shown:
            merged.setdefault((x["grantee"], tuple(x["path"])), []).append(x)
        table_card("grantees", "All grantees", "roles and users · path read toward the object",
                   ["Grantee", "Privilege", "Depth", "Path", "Paths"],
                   [[strong(k[0], kind_label(k[0])), " ".join(pv_cell(y) for y in v), ui.depth(v[0]["depth"]),
                     chain(list(k[1]), True), str(max(y["count"] for y in v))] for k, v in merged.items()],
                   [[k[0], v[0]["kind"], a.status(k[0]) if v[0]["kind"] == "user" else "", *a.split_name(o, t)[:2],
                     a.split_name(o, t)[2], ", ".join(y["privilege"] for y in v), v[0]["depth"], arrow(k[1]),
                     max(y["count"] for y in v)] for k, v in merged.items()],
                   f"Nobody holds {pv or 'a privilege'} on {o} at any depth.", {"Paths"}, min_width=760,
                   data_cols=["Grantee", "Kind", "Status", "Database", "Schema", "Object", "Privilege", "Depth",
                              "Path", "Paths"])


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
        c = p["clear"]
        if c is None:
            return f'Row access policy {ui.mono(p["name"])}: who sees which rows cannot be derived from the policy text.'
        who = " ".join(chip(r) + f'<span class="ae-small"> ({"any role in session" if h == "session" else "only as primary role"})</span>'
                       for r, h in c[0].items()) or '<span class="ae-muted">no role</span>'
        return (f'Row access policy {ui.mono(p["name"])} on {e(p["args"] or "rows")}: sees all rows: {who}; everyone '
                f'else: rows filtered by the policy {note(c)}')

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
        with st.expander("Policy text"):
            for n, b in bodies.items():
                st.code(f"-- {n}\n{b or '(not readable)'}", language="sql")


def via_html(x, plain=False):
    """"Read + write via GRP_EMEA_ALL → T_FINANCE_REPORT_WRITE, T_FINANCE_REPORT_READ": classes that share their granted
    roles merged, then the grant holders. plain: text for the CSV."""
    groups = {}
    for c, rs in x["via"].items():
        g = groups.setdefault(tuple(rs), ([], []))
        g[0].append(ui.PCLASS[c])
        g[1].extend(h for h in x["holders"][c] if h not in rs and h not in g[1])
    out = []
    for rs, (cs, hs) in groups.items():
        lab = " + ".join(cs).capitalize()
        if plain:
            out.append(f"{lab} via {', '.join(rs)}" + (f" > ... > {', '.join(hs)}" if hs else ""))
        else:
            held = f"grant held by {', '.join(hs)}" if hs else "granted role holds the grant itself"
            out.append(f'<span class="ae-small ae-tip" title="{e(held)}">{e(lab)} via</span> '
                       + " ".join(chip(r) for r in rs))
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

        def seen(col):
            if not reads:
                return '<span class="ae-muted">–</span>'
            v = a.masked(u, o, col)
            return tag(v, "warn" if v == "clear" else "low", POLICY_TEXT)

        def rowcell():
            if not reads:
                return '<span class="ae-muted">–</span>'
            v = a.masked(u, o)
            return tag("all rows" if v == "clear" else "filtered" if v == "masked" else "?", "warn" if v == "clear"
                       else "low", POLICY_TEXT)

        sens = [seen(c) for c in scols] + ([rowcell()] if rpol else [])
        rows.append([cell] + [tick(c) for c in cols] + sens
                    + [via_html(x) if x["via"] else '<span class="ae-muted">admin role</span>',
                       ui.depth(min(ds)) if ds else tag("admin", "bad", "Only through an admin role: no granted role "
                                                                        "path, so no depth"), str(n)])
        privs = ["ALL (admin)"] if not real else [c for c in cols if x["privs"][c]["has"]] + \
            [f"{c} (owner)" for c in cols if x["privs"][c]["owner"]]
        path = arrow(best) if best else " | ".join(arrow(p) for p in a.admin_paths(u, True))
        plain = ([a.masked(u, o, c) if reads else "" for c in scols]
                 + ([("all rows" if a.masked(u, o) == "clear" else "filtered") if reads else ""] if rpol else []))
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
        html(ui.table(["User"] + cols + extra + ["Via", "Nearest grant", "Paths"], rows, {"Paths"}, 760, tips=tips,
                      nowrap={"Nearest grant", "Paths"} | set(cols)) if rows else
             f'<p class="ae ae-empty">No user reaches {e(o)} at any depth.</p>')
    st.caption("Click a tick to see every path on Can they?. owner: implied by OWNERSHIP. Hover a tick for the path.")


def unless(p):
    c = p["clear"]
    if c is None:
        return "masked or clear: cannot derive from the policy text"
    rs = [f"{r} is {'in session' if h == 'session' else 'the primary role'}" for r, h in c[0].items()]
    return "masked unless " + " or ".join(rs) if rs else "masked for every role"


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
                       [chain(x) for x in admin] + ['<span style="font-size:12.5px">The admin route is not drawn '
                                                    'below, to keep it readable.</span>']))
    yes = bool(ps or r["owner"] or admin)
    if mine and a.is_data(a.kinds[o]):
        html(ui.banner("info", "Masking needs governance views", [
            f'My access reads only your own grants. <a href="{e(shared_link(page="check", name=u, obj=o, priv=pv))}" '
            'target="_self">See whether the columns are masked for you in the shared snapshot</a>.']))
    tone = "warn" if yes and (off or sleep) else None
    if yes and o in SENS and pv in a.READ_PRIVS:
        pol = a.policies_of(o)
        bits = [f"{c} {unless(pol['columns'][c][0]) if a.masked(u, o, c) != 'clear' else 'clear'}"
                if c in pol["columns"] else f"{c} clear (no masking policy)" for c in a.sensitive_cols(o)]
        bits += [f"rows {'clear' if a.masked(u, o) == 'clear' else unless(p)}" for p in pol["rows"][:1]]
        html(ui.banner("info", f"Sensitive object: {e(pv)} yes; " + e("; ".join(bits) or "the whole object is "
                                                                       "sensitive") + " (from policy text)"))
    if not ps and r["owner"]:
        html(ui.answer(True, yes_text or "Yes, via ownership",
                       f"{e(u)} reaches OWNERSHIP of {e(o)}, which implies {e(pv)}.{note}",
                       [("Paths", len(r["owner"])), ("Shortest depth", len(r["owner"][0]) - 2)], tone))
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
                    + " ".join(chip(x["role"], f"{x['privileges']} privileges in all") for x in r["ask"][:5])
                    + '</p><p class="ae-muted">Fewest privileges first. How the first one would reach it:</p>'
                    + chain(r["ask"][0]["path"]))
        elif r["closest"]:
            body = (f'<p class="ae-muted">No functional role reaches {e(pv)}. It sits with this chain:</p>'
                    + chain(r["closest"]))
        else:
            body = f'<p class="ae-muted">No role holds {e(pv)} on {e(o)}.</p>'
        html(ui.card("What to ask for", "", body))
        return usage_card(u, "Roles and warehouses this user ran queries with ({days} days)")

    ends = {x["holder"] for x in ps}
    html(ui.answer(True, yes_text or f"Yes, through {plural(len(ps), 'path')}",
                   f"{e(u)} can {e(pv)} {e(o)}." + (f" Every path ends at {e(ps[0]['holder'])}." if len(ends) == 1
                                                     else "") + (" Also through an admin role." if admin else "")
                   + note, [("Paths", len(ps)), ("Shortest depth", r["shortest"])], tone))
    run_with(r)
    blocks = "".join(ui.block(f"Path {i}", ui.depth(x["depth"]), chain(x["path"]), f"{e(pv)}: {e(x['how'])}")
                     for i, x in enumerate(ps, 1))
    if mine:
        html(ui.card("Every path", "", blocks))
    else:
        html('<div class="ae ae-two">' + ui.card("Every path", "", blocks)
             + ui.card("To remove this access", "", removal_html(u, r)) + '</div>')
    graph_card("Paths combined", *a.down_graph(u, [dict(privilege=pv, type=a.kinds[o], object=o,
                                                         paths=[x["path"] for x in ps])]))
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
    """What name (user or role) sees of sensitive object o: "EMAIL masked · PHONE clear · rows clear"."""
    m = [f"{c} {a.masked(name, o, c)}" for c in a.sensitive_cols(o)]
    m += ["rows " + a.masked(name, o)] * bool(a.policies_of(o)["rows"])
    return " · ".join(m) or "whole object, clear"


def sensitive_page():
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
             " ".join(chip(r) for r in sorted(who[u]["roles"])), chain(who[u]["path"], True)] for u in us]
    rows += [[strong(u, "admin role", bad=True), tag("via admin role", "bad") + "<br>" + login_html(u),
              f'<span class="ae-tip" title="every object">{len(rank)}</span>', " ".join(chip(r) for r in admins[u]),
              " ".join(chain(p) for p in a.admin_paths(u, True))] for u in ad]
    data = [[u, (a.profile.get(u) or {}).get("TYPE") or "PERSON", a.status(u),
             (a.profile.get(u) or {}).get("LAST_SUCCESS_LOGIN") or "", len(who[u]["objs"]),
             ", ".join(sorted(who[u]["objs"])), ", ".join(sorted(who[u]["roles"])), arrow(who[u]["path"])] for u in us]
    data += [[u, (a.profile.get(u) or {}).get("TYPE") or "PERSON", "via admin role",
              (a.profile.get(u) or {}).get("LAST_SUCCESS_LOGIN") or "", len(rank), "every object (admin role)",
              ", ".join(admins[u]), " | ".join(arrow(p) for p in a.admin_paths(u, True))] for u in ad]
    table_card("sensusers", "Who can read sensitive data", sub + " · through any granted role, admin holders last"
               + (" · enabled people only" if people else ""),
               ["User", "Status", "Objects", "Through granted roles", "Shortest path"], rows, data,
               "Nobody reads these objects.", {"Objects"}, min_width=900,
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
                                                  "Granted roles", "Path"]
    rows = [([ui.mono(x["database"])] if db == "*" else []) + [
        ui.mono(x["schema"]), (e(a.future_label(f'{x["database"]}.{x["schema"]}.{x["object"]}', x["type"]) or "")
                               or ui.mono(x["object"])) + f'<br><span class="ae-small">{e(x["type"] or "")}</span>',
        strong(x["user"], x["user_type"].lower()), tag(x["status"], "low" if x["status"] == "active" else "warn"),
        " ".join(ui.pclass(c) for c in x["classes"].split(", ") if c) + f'<br><span class="ae-small">'
        f'{e(x["privileges"])}</span>', e(x["sensitive"]), " ".join(chip(r) for r in x["granted"].split(", ") if r),
        chain(x["path"].split(" > "), True) if x["path"] else ""] for x in shown]
    filt = [f"schema {sc}"] * bool(sc) + [f"object {ob}"] * bool(ob) + ["disabled excluded"] * active
    table_card("review", f"Access review: {where}", f"{plural(len(shown), 'row')} shown of {len(rs)} · one per user and "
               "object · the CSV has every row and blank Reviewer and Keep/Revoke columns"
               + (" · " + e(", ".join(filt)) if filt else ""), head, rows,
               [[x[k] if x[k] is not None else "" for k in keys] for x in rs],
               f"No user reaches an object in {where}.", min_width=1100, data_cols=cols,
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
    "8": ("user", "Users and hygiene", "A disabled user still has roles granted.", "Revoke the roles or drop the user."),
    "16": ("user", "Users and hygiene", f"A person with no login for {a.DORMANT_DAYS} days (or never) still holds "
           "roles.", "Revoke the roles or disable the user."),
}
AREAS = ["Role model", "Admin and account", "Sensitive data", "Read-only and write", "Users and hygiene"]


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
        example = (f'{chip(ex["grantee"])}&nbsp;<span class="ae-mono" style="font-size:12.5px">{e(ex["detail"])}</span>'
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
            return chip(xs[0]["grantee"])
        return (f'<details><summary class="ae-tip">{plural(len(xs), "grantee")}</summary><div class="ae-path">'
                + " ".join(chip(x["grantee"]) for x in xs) + '</div></details>')

    what = ([f"rule {sel}"] if sel else []) + ([sev] if sev else []) + ([who] if who else [])
    gs = list(groups.values())
    now = datetime.now()
    table_card("findings", "Findings", f"{len(shown)} across {plural(len({x['num'] for x in shown}), 'rule')} · "
               f"{len(gs)} rows (same fix merged)" + (" · " + e(", ".join(what)) if what else "")
               + (f' · <a href="{e(link(page="rules"))}" target="_self">clear filters</a>' if what else ""),
               ["Rule", "Grantee", "Detail", "Affects"],
               [[f'<div style="min-width:170px">{ui.dot(xs[0]["severity"], True)}<br>'
                 f'<span class="ae-tip" title="{e(xs[0]["why"])}">{e(xs[0]["num"])} · {e(xs[0]["title"])}</span></div>',
                 who_cell(xs), ui.mono(xs[0]["detail"]) + (f'<br><span class="ae-small">and {len(xs) - 1} more like '
                                                            'it</span>' if len(xs) > 1 else ""),
                 f'<span class="ae-tip" title="users who lose access when the fix is applied, net of their other '
                 f'paths">{e(xs[0]["impact"])}</span>'] for xs in gs],
               [[x["num"], x["title"], x["severity"], x["grantee"], x["detail"], x["iac"], x["sql"],
                 "" if x["affects"] is None else x["affects"], x["same_fix"], " | ".join(arrow(p) for p in x["paths"])]
                for x in shown],
               "No findings for this selection." if what else "No rule findings in this data.", {"Affects"},
               min_width=760, data_cols=["Rule", "Title", "Severity", "Grantee", "Detail", "Fix", "SQL",
                                         "Affects users", "Same fix", "Paths"],
               fname=f"findings_{sev or 'all'}_{now:%Y-%m-%d}.csv",
               head=[["Rule checks", ", ".join(what) or "all"], ["Run", a.run.get("RUN_ID"),
                                                                 str(a.run.get("FINISHED_AT"))[:16]],
                     ["Generated", f"{now:%Y-%m-%d %H:%M}"]],
               subs=[f'<div class="ae-subline"><span class="ae-small">Path</span> '
                     + "".join(chain(p, True) for p in xs[0]["paths"]) + '</div>' + fix(xs[0]) for xs in gs])


def admins_card():
    """Users holding an admin role or an account-level privilege, service users included."""
    people, now = a.admin_people(), datetime.now()
    html('<div id="admins"></div>')
    table_card("admins", "People with admin roles", "admin roles and account-level privileges · service users "
               "included · with the chain",
               ["User", "Admin roles", "Account privileges", "Chain", "Status", "Last login"],
               [[strong(x["user"], "service" if x["service"] else "person"), " ".join(chip(r) for r in x["roles"])
                 or '<span class="ae-muted">–</span>',
                 " ".join(ui.pclass("admin", pv) for pv in dict.fromkeys(pv for pv, _ in x["account"]))
                 or '<span class="ae-muted">–</span>',
                 "".join(chain(p) for p in x["paths"] + [p for _, p in x["account"]]),
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
                   format_func=lambda n: f"{n}  ·  {kind_label(n)}" + ("  ·  sensitive" if n in SENS else ""))
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
        names = a.users + [r for r in a.roles if r not in a.profile] + a.objects if d is not None else []
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
