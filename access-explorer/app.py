"""Snowflake access explorer. Run: streamlit run app.py
Data: FAKE=1 (default) fake data · DUCKDB=<file> fake data in DuckDB (make_demo_db.py), read with the snapshot SQL ·
FAKE=0 Snowflake via ../sf.py, as the logged-in user.
Page, entity and filters live in the URL (?page=role&name=...&depth=3), so chips and graph nodes are plain links."""
import csv
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
    "check": ("Can they?", "One user, one object, one privilege — every way it is granted.", ""),
    "rules": ("Rule checks", "Where the role model breaks its own rules",
              "Rules of the layered role model, sensitive data and dormant users. Rule 4 allows OWNER roles for "
              + ", ".join(f"<code>{e(b)}</code>" for b in a.BUILD) + "."),
}
THEME, VIEW_MODE, ROWS, SENS = "light", "shared", [], {}


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
    return a.only(shared(), DEMO_USER)


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
    st.query_params.from_dict(kept() | {"page": page_of(n), "name": n})
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


def chip(n, title=""):
    return ui.chip(n, a.kind_of(n), href(n), sensitive=n in SENS, disabled=a.is_disabled(n), title=title)


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


def login(u):
    """Last login as text: "2026-10-30 08:12 · 3 days ago", plus Dormant / Never."""
    p = a.profile.get(u) or {}
    d = a.login_days(u)
    if d is None:
        return "never logged in", "Never"
    text = f"{str(p.get('LAST_SUCCESS_LOGIN'))[:16]} · {plural(d, 'day')} ago"
    return text, "Dormant" if a.is_dormant(u) else ""


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


def table_card(key, title, sub, cols, rows, data, none, numeric=(), min_width=640, data_cols=None, fname=None, head=()):
    """Card with title, Export CSV and a table. data: plain rows for the CSV (columns data_cols or cols);
    none: sentence when empty."""
    with st.container(key="card_" + key):
        left, right = st.columns([4, 1], vertical_alignment="center")
        html(f'<div class="ae">{ui.title(title, sub)}</div>', left)
        if data:
            right.download_button("Export CSV", csv_text(data_cols or cols, data, head), fname or f"{key}.csv",
                                  "text/csv", key="csv_" + key, on_click="ignore")
        html(ui.table(cols, rows, numeric, min_width) if rows else f'<p class="ae ae-empty">{e(none)}</p>')


def marks(names):
    return {n: {f for f, on in (("disabled", a.is_disabled(n)), ("sensitive", n in SENS)) if on} for n in names
            if a.is_disabled(n) or n in SENS}


def graph_card(title, lanes, edges, notes=None, selected=None, sub=""):
    with st.container(key="card_graph"):
        left, right = st.columns([4, 1.2], vertical_alignment="center")
        html(f'<div class="ae">{ui.title(title, sub)}</div>', left)
        with right:
            fit = flag("Fit to width", "fit", toggle=True, help="Scale the whole graph into the card. Off: full size, "
                                                                "scroll sideways.")
        html(ui.legend(edges=True, marks=True))
        names = {n for _, ns in lanes for n in ns}
        html(ui.lane_graph(lanes, edges, a.kind_of, THEME, href, selected, expand=q("expand"),
                           query=dict(st.query_params), fit=fit, marks=marks(names), notes=notes))
        html(ui.how())


def usage_card(u, title):
    src = a.run["SOURCES"].get("usage")
    days = "7" if src == "INFORMATION_SCHEMA" else "30"
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


def findings_banner(name):
    xs = [x for x in ROWS if x["grantee"] == name]
    if xs and VIEW_MODE == "shared":
        lines = [f'{ui.dot(x["severity"])}&nbsp;<b>Rule {e(x["num"])}</b>&nbsp;{e(x["title"])}: '
                 f'<span class="ae-mono" style="font-size:12.5px">{e(x["detail"])}</span>' for x in xs[:6]]
        lines.append(f'<a href="{e(link(page="rules", grantee=name))}" target="_self">Show on Rule checks</a>')
        html(ui.banner("warn", f"{plural(len(xs), 'rule finding')} for {e(name)}", lines))


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
    findings_banner(u)

    text, mark = login(u)
    sec = str(p.get("DEFAULT_SECONDARY_ROLES") or "")
    html(ui.profile([
        ("Type", e(str(p.get("TYPE") or "—").capitalize())),
        ("Status", '<span class="ae-ink-bad">Disabled</span>' if a.is_disabled(u)
         else '<span class="ae-ink-ok">Enabled</span>'),
        ("Default role", chip(p["DEFAULT_ROLE"]) if p.get("DEFAULT_ROLE") else "—"),
        ("Secondary roles", f'<span class="ae-tip" title="{e(ui.HELP["Secondary roles"])}">'
                            f'{"All" if "ALL" in sec.upper() else "None"}</span>'),
        ("Default warehouse", ui.mono(p.get("DEFAULT_WAREHOUSE") or "—")),
        ("Last login", e(text) + (" " + tag(mark, "warn", ui.HELP["Dormant"]) if mark else ""))]))
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
               help="Sensitive"),
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
    src = a.run["SOURCES"].get("usage")
    days = "7" if src == "INFORMATION_SCHEMA" else "30"
    use, dr = a.used_roles(u), (a.profile.get(u) or {}).get("DEFAULT_ROLE")
    rs = sorted(a.roles_of.get(u, []))
    cell = (lambda r: "not readable") if src == "UNAVAILABLE" else (
        lambda r: f"{use[r]['queries']} queries · {str(use[r]['last_used'])[:10]}" if r in use else "not used")
    table_card("granted", "Granted roles", f"granted to {u} directly · use from the query history",
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
        if a.run["SOURCES"].get("tags") == "UNAVAILABLE":
            html(ui.banner("info", "Sensitivity needs the governance views of the shared snapshot; ask an admin."))
        return
    rs = a.sensitive_reach(u)
    got = [x for x in rs if x["path"]]
    if not got:
        return
    roles = list(dict.fromkeys(x["role"] for x in rs))
    objs = list(dict.fromkeys(x["object"] for x in got))
    cell = {(x["object"], x["role"]): x for x in got}
    per = [f"through {chip(r)}: {plural(sum(1 for o in objs if (o, r) in cell), 'sensitive object')}" for r in roles
           if any((o, r) in cell for o in objs)]
    diff = [f'{chip(o)}: through {", ".join(chip(r) for r in roles if (o, r) in cell)}; not through '
            f'{", ".join(chip(r) for r in roles if (o, r) not in cell)}' for o in objs
            if any((o, r) not in cell for r in roles)]
    if diff:
        html(ui.banner("info", "Granted roles differ in sensitive reach", diff[:8]))
    tick = f'<span class="ae-yes">{ui.icon("ok", 14, 2.6)}</span>'
    rows = [[chip(o) + (f'<br><span class="ae-small">{e(", ".join(a.sensitive_cols(o)) or "whole object")}</span>')]
            + [f'{tick} <span class="ae-small">{e(masks(cell[(o, r)]))}</span>' if (o, r) in cell
               else '<span class="ae-muted">–</span>' for r in roles] for o in objs]
    data = [[o, ", ".join(a.sensitive_cols(o))] + [masks(cell[(o, r)]) if (o, r) in cell else "" for r in roles]
            for o in objs]
    table_card("sensitive", "Sensitive data, by granted role", " · ".join(per) + " · masking from policy text, "
               "not evaluated", ["Sensitive object"] + roles, rows, data, "", min_width=520,
               data_cols=["Object", "Sensitive columns"] + roles)
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
        return gone("name")
    s, hold, full = a.role_stats(r, limit), a.holds_of(r), a.held(r, limit)
    up = [x for x in full if x["kind"] == "user"] if only_users else full
    k = s["kind"]
    prefix = {"functional": a.FUNC, "technical": a.TECH}.get(k)
    owner = [g for g, pv, t in a.on.get(r, []) if pv == "OWNERSHIP" and t == "ROLE"]
    html(ui.grid([
        ui.kpi("Kind", ui.chip(KIND.get(k, "Group role") + (f" ({prefix} prefix)" if prefix else ""), k,
                               title=ui.tip(ui.LABELS[k])),
               f"owned by {e(', '.join(owner))}" if owner else "", help=ui.LABELS[k]),
        ui.kpi("Direct grants", s["privileges"], f"incl. {plural(s['future'], 'future grant')}" if s["future"]
               else "privileges on the role itself", "accent"),
        ui.kpi("Effective privileges", s["effective"], f"inherited from {plural(len(s['holds_roles']), 'role')} "
                                                        "it holds" if s["holds_roles"] else "no roles held"),
        ui.kpi("Roles above it", s["above"], f"{s['above_direct']} grant it directly"),
        ui.kpi("Users who get it", s["users"], f"{s['users_direct']} granted directly" if s["users_direct"]
               else "none granted directly"),
        ui.kpi("Farthest holder", s["farthest"], "depth from the holder down to this role", help="Depth"),
        ui.kpi("Sensitive objects reached", s["sensitive"], "readable through it", "bad" if s["sensitive"] else None,
               help="Sensitive")], 150))
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
    findings_banner(r)
    if s["holds_roles"]:
        html(ui.card("Holds roles", f"direct grants: {s['privileges']} · it gets everything these roles hold",
                     '<div class="ae-path">' + " ".join(chip(x) for x in s["holds_roles"]) + '</div>'))

    lanes, edges, notes, far = a.role_graph(r, up)
    graph_card("Held by (up) and holds (down)", lanes, edges, notes, far)

    left, right = st.columns(2)
    with left:
        table_card("holds", "Holds (down)", f"direct grants: {len(hold)}",
                   ["Privilege", "Type", "Database", "Schema", "Object"],
                   [[pv_cell(h), f'<span class="ae-small">{e(h["type"])}</span>', ui.mono(h["database"]),
                     ui.mono(h["schema"]), obj_cell(h["object"], h["type"], h["name"])] for h in hold],
                   [[h["privilege"], h["cls"], h["type"], h["database"], h["schema"], h["name"]] for h in hold],
                   f"{r} holds no privileges of its own" + (": see Effective privileges." if s["holds_roles"] else "."),
                   min_width=460, data_cols=["Privilege", "Class", "Type", "Database", "Schema", "Object"])
    with right:
        table_card("held", "Held by (up)", f"{len(up)} grantees · shortest path shown, read left to right",
                   ["Grantee", "Depth", "Only via", "Path", "Paths"],
                   [[strong(x["grantee"], kind_label(x["grantee"]) + (" · granted directly" if x["direct"] else "")),
                     ui.depth(x["depth"]), " ".join(chip(n) for n in x["only_via"]) or
                     '<span class="ae-muted">–</span>', chain(x["path"], True), str(x["count"])] for x in up],
                   [[x["grantee"], x["kind"], a.status(x["grantee"]) if x["kind"] == "user" else "", x["depth"],
                     x["direct"], " ".join(x["only_via"]), arrow(x["path"]), x["count"]] for x in up],
                   f"No {'user' if only_users else 'role or user'} holds {r} at this depth.", {"Paths"},
                   min_width=560, data_cols=["Grantee", "Kind", "Status", "Depth", "Direct", "Only via", "Path",
                                             "Paths"])
    st.caption("Only via: roles every path passes through. Revoking one of them removes this role from the grantee.")
    eff = [x for x in a.grants(r) if not only_sens or x["object"] in SENS]
    eff.sort(key=lambda x: (type_rank(x["type"]), x["object"], x["privilege"]))
    table_card("effective", "Effective privileges (inherited)", f"{len(eff)} privileges · own grants and every "
               "role it holds" + (" · sensitive only" if only_sens else ""),
               ["Privilege", "Type", "Database", "Schema", "Object", "Depth", "Path"],
               [[pv_cell(x), f'<span class="ae-small">{e(x["type"])}</span>', ui.mono(x["database"]),
                 ui.mono(x["schema"]), obj_cell(x["object"], x["type"], x["name"]), ui.depth(x["depth"]),
                 chain(x["path"][:-1], True)] for x in eff],
               [[x["privilege"], x["cls"], x["type"], x["database"], x["schema"], x["name"], x["depth"],
                 arrow(x["path"])] for x in eff],
               f"{r} reaches no {'sensitive ' if only_sens else ''}privileges.", min_width=900,
               data_cols=["Privilege", "Class", "Type", "Database", "Schema", "Object", "Depth", "Path"])


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
    extra = ([] if active else [f"+{len(s['disabled'])} disabled"] * bool(s["disabled"])) \
        + [f"+{len(s['service'])} service"] * bool(s["service"]) + [f"+{len(s['admin'])} via admin"] * bool(s["admin"])
    html(ui.grid([
        ui.kpi(f"People who can {pv}" if pv else "People with access", len(s["people"]),
               " · ".join(extra) or "no others", "accent",
               help="Enabled persons. Disabled and service users and admin-role holders are counted apart."),
        ui.kpi("Roles with access", s["roles"], f"{s['direct']} hold grants directly"),
        ui.kpi("Owner", " ".join(chip(x) for x in s["owners"]) or "—",
               "deployed by " + e(", ".join(s["deployers"])) if s["deployers"] else e(s["owner_note"]),
               help="Own"),
        ui.kpi("Longest chain", s["longest"], "roles from the farthest grantee to the grant holder", help="Depth")],
        200))
    sensitivity_card(o)
    matrix_card(o, t, pv, active)

    g = [x for x in a.grantees(o, t) if not pv or x["privilege"] == pv]
    users = sorted({x["grantee"] for x in g if x["kind"] == "user" and a.from_user(x["path"])
                    and not (active and a.is_disabled(x["grantee"]))})
    shown = [x for x in g if x["kind"] != "user" or x["grantee"] in users]
    if only_users:
        shown = [x for x in shown if x["grantee"] in users]
    with st.expander("Paths into the object (graph)", expanded=False):
        g = a.object_graph(o, t, shown, users)
        if g:
            graph_card("Paths into the object", *g)
        else:
            empty(f"Nobody holds {pv or 'a privilege'} on {o} at any depth.")
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


def sensitivity_card(o):
    tg, ps = a.tags_of(o), a.policies_of(o)
    if not tg and not ps["columns"] and not ps["rows"]:
        return
    rules = a.tag_rules()
    chips = " ".join(ui.chip(f"{t.split('.')[-1]}={v}", "object", sensitive=a.tag_hit(rules, t, v),
                             title=f"{t} · {origin}") + f'<span class="ae-small"> {e(origin)}'
                     f'</span>' for c, t, v, origin in tg if not c)
    cols = sorted({c for c, *_ in tg if c} | set(ps["columns"]))

    def clear(p):
        c = p["clear"]
        if c is None:
            return '<span class="ae-muted">cannot derive from the policy text</span>'
        roles = " ".join(chip(r, "in session (hierarchy-aware)" if h == "session" else "primary role only")
                         for r, h in c[0].items()) or '<span class="ae-muted">no role</span>'
        return roles + " " + tag("heuristic", "low", "From the policy text, not evaluated by Snowflake"
                                 + ("" if c[1] else "; the policy also checks the user or account"))

    rows = []
    for c in cols:
        ct = [(t, v) for cc, t, v, _ in tg if cc == c]
        mp = ps["columns"].get(c, [])
        rows.append([ui.mono(c), " ".join(ui.chip(f"{t.split('.')[-1]}={v}", "object", sensitive=a.tag_hit(rules, t, v),
                                                  title=t) for t, v in ct if not t.upper().endswith("SEMANTIC_CATEGORY")),
                     e(", ".join(v for t, v in ct if t.upper().endswith("SEMANTIC_CATEGORY"))),
                     " ".join(ui.mono(p["name"]) for p in mp) or tag("no masking policy", "warn") * (c in a.sensitive_cols(o)),
                     clear(mp[0]) if mp else ""])
    body = (f'<div class="ae-path">{chips}</div>' if chips else "")
    body += "".join(f'<p>Row access policy {ui.mono(p["name"])} on {e(p["args"] or "rows")}: clear for {clear(p)}</p>'
                    for p in ps["rows"])
    if rows:
        body += ui.table(["Column", "Tags", "Semantic category", "Masking policy", "Clear for"], rows, min_width=640)
    html(ui.card("Sensitivity", "tags with where they come from · masking from policy text, not evaluated", body))
    bodies = {p["name"]: p["body"] for ps_ in ps["columns"].values() for p in ps_} | {p["name"]: p["body"]
                                                                                     for p in ps["rows"]}
    if bodies:
        with st.expander("Policy text"):
            for n, b in bodies.items():
                st.code(f"-- {n}\n{b or '(not readable)'}", language="sql")


def matrix_card(o, t, pv, active):
    m = [x for x in a.matrix(o, t, priv=pv or None) if not (active and x["status"] == "disabled")]
    cols = a.valid_privs(t)
    db, sc, nm = a.split_name(o, t)
    adm = f'<span class="ae-yes bad">{ui.icon("ok", 14, 2.6)}</span>'
    rows, data = [], []
    for x in m:
        u = x["user"]
        real = any(v["has"] or v["owner"] for v in x["privs"].values())
        ds = [v["depth"] for v in x["privs"].values() if v["has"]]
        n = max(v["count"] for v in x["privs"].values())
        best = min((v["path"] for v in x["privs"].values() if v["has"]), key=len, default=None)
        if real:
            cell = strong(u, kind_label(u) + (" · also admin" if x["admin"] else ""))
        else:  # only through an admin role: depth and paths of the admin role itself
            ap = a.admin_paths(u, True)
            ds, n, best = [min(a.depth(p, True) for p in ap)], len(ap), min(ap, key=len)
            cell = strong(u, f'admin role · {", ".join(x["admin"])} inherits all', bad=True)

        def tick(c):
            v = x["privs"][c]
            if v["has"]:
                return (f'<a class="ae-yes" href="{e(link(page="check", name=u, obj=o, priv=c))}" target="_self" '
                        f'title="{e(v["title"])}">{ui.icon("ok", 14, 2.6)}</a>')
            if v["owner"]:
                return f'<span class="ae-small ae-tip" title="implied by OWNERSHIP">owner</span>'
            return adm if not real else '<span class="ae-muted">–</span>'

        via = " · ".join(f'{ui.PCLASS[c]} via {", ".join(chip(r) for r in rs)}' for c, rs in x["via"].items())
        rows.append([cell] + [tick(c) for c in cols] + [via or '<span class="ae-muted">admin role</span>',
                                                         ui.depth(min(ds)) if ds else "—", str(n)])
        privs = ["ALL (admin)"] if not real else [c for c in cols if x["privs"][c]["has"]] + \
            [f"{c} (owner)" for c in cols if x["privs"][c]["owner"]]
        data.append([u, (a.profile.get(u) or {}).get("TYPE") or "PERSON", x["status"], db, sc, nm, ", ".join(privs),
                     arrow(best) if best else "", "", ""])
    when = str(a.run.get("FINISHED_AT"))[:16]
    table_card("matrix", "Effective access by user", "what each person ends up with, after every role is unfolded"
               + (f" · only users with {pv} (or OWNERSHIP)" if pv else "") + (" · disabled excluded" if active else ""),
               ["User"] + cols + ["Via", "Nearest grant", "Paths"], rows, data, f"No user reaches {o} at any depth.",
               {"Paths"}, min_width=900,
               data_cols=["User", "Type", "Status", "Database", "Schema", "Object", "Privileges", "Path", "Reviewer",
                          "Keep/Revoke"],
               fname=f"{o}_{pv or 'ALL'}_{datetime.now():%Y-%m-%d}.csv",
               head=[["Object", o, t], ["Filter", pv or "any privilege", "disabled excluded" if active else ""],
                     ["Run", a.run.get("RUN_ID"), when]])
    st.caption("Click a tick to see every path on Can they?. owner: implied by OWNERSHIP.")


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
        c = st.columns([0.5, 2, 3, 0.2], vertical_alignment="center")
        html('<div class="ae"><span class="ae-h2" style="font-size:26px;white-space:nowrap">Can</span></div>', c[0])
        with c[1]:
            u = select("User", a.users, "name", DEMO_USER if DEMO_USER in a.users else None, key="pick_user",
                       strict=True, label_visibility="collapsed")
        with c[2]:
            o = select("Object", a.objects, "obj", tables[0] if tables else None, key="pick_obj", strict=True,
                       label_visibility="collapsed")
        html('<div class="ae"><span class="ae-h2" style="font-size:26px">?</span></div>', c[3])
        if o is not None:
            pv = radio("Privilege", a.valid_privs(a.kinds[o]), "priv", "SELECT", label_visibility="collapsed")
        st.caption("Uses all granted roles (secondary roles ALL). The role hierarchy is walked without a depth limit.")
    if u is None:
        return gone("name")
    if o is None:
        return gone("obj")
    r = a.can(u, pv, o)
    ps = r["paths"]
    admin = a.admin_paths(u, True)
    off = r["status"] == "disabled"
    note = " The user is disabled: cannot log in." if off else ""
    if admin:
        html(ui.banner("bad", f"{e(u)} holds an admin role, which inherits every role below it",
                       [chain(x) for x in admin] + ['<span style="font-size:12.5px">The admin route is not drawn '
                                                    'below, to keep it readable.</span>']))
    yes = bool(ps or r["owner"] or admin)
    tone = "warn" if yes and off else None
    if yes and o in SENS and pv in a.READ_PRIVS:
        pol = a.policies_of(o)
        bits = [f"{c} {unless(pol['columns'][c][0]) if a.masked(u, o, c) != 'clear' else 'clear'}"
                if c in pol["columns"] else f"{c} clear (no masking policy)" for c in a.sensitive_cols(o)]
        bits += [f"rows {'clear' if a.masked(u, o) == 'clear' else unless(p)}" for p in pol["rows"][:1]]
        html(ui.banner("info", f"Sensitive object: {e(pv)} yes; " + e("; ".join(bits) or "the whole object is "
                                                                       "sensitive") + " (from policy text)"))
    if not ps and r["owner"]:
        html(ui.answer(True, "Yes, but the user is disabled" if off else "Yes, via ownership",
                       f"{e(u)} reaches OWNERSHIP of {e(o)}, which implies {e(pv)}.{note}",
                       [("Paths", len(r["owner"])), ("Shortest depth", len(r["owner"][0]) - 2)], tone))
        run_with(r)
        return usage_card(u, "Roles and warehouses this user ran queries with ({days} days)")
    if not ps and admin:
        html(ui.answer(True, "Yes, but the user is disabled" if off else
                       f"Yes, through admin role {', '.join(dict.fromkeys(x[-1] for x in admin))}",
                       f"{e(u)} can {e(pv)} {e(o)}: the admin role inherits every role, not through a granted "
                       f"role path.{note}", [("Paths", 0), ("Via admin", len(admin))], tone))
        return usage_card(u, "Roles and warehouses this user ran queries with ({days} days)")
    if not ps:
        html(ui.answer(False, "No, not through any role",
                       f"No role granted to {e(u)}, at any depth, holds {e(pv)} on {e(o)}.{note}",
                       [("Paths", 0), ("Shortest depth", "—")], "low"))
        if r["ask"]:
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
    html(ui.answer(True, "Yes, but the user is disabled" if off else f"Yes, through {plural(len(ps), 'path')}",
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
        sql = f"USE ROLE {r['use_role']};" + (f" USE WAREHOUSE {r['warehouse']};" if r["warehouse"] else "")
        html(ui.banner("info", f"Run with: {ui.mono(sql)}",
                       ["Not needed with secondary roles ALL: every granted role is active in the session."]))


def removal_html(u, r):
    opts = r["options"]
    if not opts:
        return ('<p class="ae-muted">No single grant sits on every path: each path has to be cut on its own.</p>'
                if r["paths"] else "")
    out = ['<p class="ae-muted">Grants every path passes through, fewest affected users first. Remove in the '
           'infrastructure-as-code repo (manual changes are undone by reconciliation); the SQL is the equivalent.</p>']
    for x in opts:
        others = x["affects"] - (u in x["users"])
        warn = f" · removes access for {plural(others, 'other user')}" if x["edge"]["priv"] and others else ""
        out.append(f'<div class="ae-block" style="background:var(--panel)"><div class="ae-block-head">'
                   f'<span>{e(x["iac"])}</span><span class="ae-small">affects {plural(x["affects"], "user")}{e(warn)}'
                   f'</span></div><code class="ae-mono" style="font-size:12.5px">{e(x["sql"])}</code></div>')
    return "".join(out)


def rules_page(rows):
    sev = q("sev") if q("sev") in SEVS else ""
    gs = {x["grantee"] for x in rows}
    who = q("grantee") if q("grantee") in gs else ""
    if q("grantee") and not who:
        html(ui.banner("info", f"No rule findings for {e(q('grantee'))}."))
    base = [x for x in rows if (not sev or x["severity"] == sev) and (not who or x["grantee"] == who)]
    nums = sorted({x["num"] for x in base}, key=int)
    sel = q("rule") if q("rule") in nums else ""
    keep = dict(sev=sev, grantee=who)
    html('<div class="ae ae-legend">' + "".join(
        f'<a class="ae-chip k-object" style="{"outline:1.5px solid var(--accent)" if s == sev else ""}" '
        f'href="{e(link(page="rules", grantee=who, sev=s))}" target="_self">{ui.dot(s, True) if s else "All severities"}'
        f'</a>' for s in [""] + SEVS) + '</div>')
    if who:
        html(ui.banner("info", f"Findings for {chip(who)} · <a href=\"{e(link(page='rules', sev=sev))}\" "
                               "target=\"_self\">show everyone</a>"))
    cards = [ui.rule_card("All rules", "", len(base), "Findings across every rule", link(page="rules", **keep),
                          not sel)]
    for n in nums:
        xs = [x for x in base if x["num"] == n]
        cards.append(ui.rule_card(f"Rule {n}", xs[0]["severity"], len(xs), xs[0]["title"],
                                  link(page="rules", rule=n, **keep), sel == n))
    html(ui.grid(cards, 160))
    shown = [x for x in base if not sel or x["num"] == sel]
    if sel:
        html(ui.banner("info", f"Why rule {e(sel)} matters: <span style='font-weight:400'>{e(a.RULES[sel][1])}</span>"))

    def fix(x):
        if not x["iac"]:
            return '<span class="ae-muted">–</span>'
        same = f'<br>{tag("same fix as " + x["same_fix"], "low")}' if x["same_fix"] else ""
        sql = f'<br><code class="ae-mono" style="font-size:12px">{e(x["sql"])}</code>' if x["sql"] else ""
        return f'<span style="font-size:12.5px">{e(x["iac"])}</span>{sql}{same}'

    table_card("findings", "Findings", f"{len(shown)} across {plural(len({x['num'] for x in shown}), 'rule')}"
               + (f" · {sev} only" if sev else ""),
               ["Rule", "Grantee", "Detail", "Fix", "Affects", "Path"],
               [[f'<div class="ae-path" style="flex-wrap:nowrap">{ui.dot(x["severity"], True)}</div>'
                 f'<span class="ae-tip" title="{e(x["why"])}">{e(x["num"])} · {e(x["title"])}</span>',
                 chip(x["grantee"]), ui.mono(x["detail"]), fix(x),
                 f'<span title="users who lose the revoked grant">{plural(x["affects"], "user")}</span>'
                 if x["sql"] else "",
                 "".join(chain(p, True) for p in x["paths"])] for x in shown],
               [[x["num"], x["title"], x["severity"], x["grantee"], x["detail"], x["iac"], x["sql"], x["affects"],
                 x["same_fix"], " | ".join(arrow(p) for p in x["paths"])] for x in shown],
               "No rule findings in this data.", {"Affects"}, min_width=1100,
               data_cols=["Rule", "Title", "Severity", "Grantee", "Detail", "Fix", "SQL", "Affects users", "Same fix",
                          "Paths"])
    people = a.admin_people()
    table_card("admins", "People with admin roles", "persons only (service users left out) · with the chain",
               ["User", "Admin roles", "Chain", "Status", "Last login"],
               [[strong(x["user"]), " ".join(chip(r) for r in x["roles"]),
                 "".join(chain(p) for p in x["paths"]), tag(x["status"], "bad" if x["status"] != "active" else "low"),
                 e(login(x["user"])[0])] for x in people],
               [[x["user"], ", ".join(x["roles"]), " | ".join(arrow(p) for p in x["paths"]), x["status"],
                 x["last_login"] or ""] for x in people],
               "No person holds an admin role.", min_width=760)


# ---------- frame ----------

def topbar(page, names):
    c = st.columns([3, 3, 0.4, 0.4], vertical_alignment="center")
    html(ui.crumb(PAGES[page]), c[0])
    c[1].selectbox("Find", names, index=None, key="find", on_change=find, label_visibility="collapsed",
                   placeholder="Find a user, role or object", format_func=lambda n: f"{n}  ·  {kind_label(n)}")
    with c[2].popover("", icon=":material/link:", help="Copy a link to this view"):
        qs = {k: v for k, v in st.query_params.items() if k != "theme"}
        st.code(str(st.context.url or "").split("?")[0] + "?" + urlencode(qs), language=None)
    c[3].button("", key="theme", on_click=flip, help="Switch light / dark",
                icon=":material/light_mode:" if THEME == "dark" else ":material/dark_mode:")


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


VIEW = {"user": user_page, "role": role_page, "object": object_page, "check": check_page, "rules": None}


def main():
    global THEME, VIEW_MODE, ROWS, SENS
    st.set_page_config("Snowflake access explorer", layout="wide", initial_sidebar_state="auto")
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
    page = q("page") if q("page") in VIEW and not (view == "mine" and q("page") == "rules") else "user"
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
        if d is not None:
            a.build(d)
        SENS = a.sensitive() if d is not None else {}
        rows = ROWS = a.rule_rows() if d is not None and a.roles else []
        badge = {"rules": len(rows), "sensitive": len(SENS)}
        html(ui.nav([(PAGES[k], link(page=k), badge.get(k) or None) for k in PAGES
                     if k in VIEW and not (k == "rules" and view == "mine")], PAGES[page]), nav)
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
            topbar(page, names)
        if d is None:
            body.empty()
            return
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


main()
