"""JSON API of the access explorer (contract: web/API.md). Run: python server.py -> http://localhost:8000
Data: Snowflake via sf.py (SOURCE=direct, or objects = the TBL_ACCESS_ tables), FAKE=1 fake data. Kept once a day (cache.py).
No logic of its own: every number, path and rule comes from access.py; this file picks, filters, renames to JSON.
FastAPI is imported only in make_app(), so st_react.py can `import server` and call serve() for the same JSON."""
import csv
import io
import json
import os
import pathlib
import re
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal

import access as a
import cache
import ui

MODE, SOURCE, WHERE = cache.config()  # FAKE=1 fake data; else SOURCE=direct|objects (README > Settings)
DIRECT = SOURCE == "direct"  # no tables: read the grants straight from Snowflake (a.live)
KEY = cache.name(SOURCE, where=WHERE)  # another snapshot location, user or role: another copy
DEMO_USER = os.environ.get("DEMO_USER", "ENGINEER_01")
TTL = cache.TTL  # shared data and My access stay in memory this long (seconds)
DIST = pathlib.Path(__file__).with_name("web") / "dist"

PAGES = {"home": "Home", "access": "A person or role", "object": "Who has access to an object", "check": "Can they?",
         "graph": "Access graph", "see": "What they see", "compare": "Compare", "request": "Request access",
         "rules": "Risks & fixes", "whatif": "What if", "review": "Review & sign-off", "sensitive": "Sensitive data",
         "flow": "Sensitive data flow", "usage": "Granted vs used", "changes": "What changed",
         "user": "User paths", "role": "Role paths"}
GROUP = {"home": "answers", "access": "answers", "object": "answers", "check": "answers", "graph": "answers", "see": "answers",
         "compare": "answers", "request": "answers", "rules": "admin", "whatif": "admin", "review": "admin",
         "sensitive": "admin", "flow": "admin", "usage": "admin", "changes": "admin",
         "user": "detail", "role": "detail"}  # side nav groups
SHARED_ONLY = {"review", "flow", "changes"}
KIND = {"functional": "Functional role", "technical": "Technical role", "group": "Group role",
        "database": "Database role", "admin": "Admin role", "object": "Object"}
KNOWN = {"user", "functional", "technical", "group", "admin", "object"}
SEVS = ["High", "Medium", "Low"]
TABS = [("account", "Account"), ("granted", "Granted roles"), ("database_roles", "Database roles"), ("usage", "Usage"),
        ("warehouses", "Warehouses"), ("execute", "Execute"), ("read", "Read"), ("write", "Write"), ("own", "Own"),
        ("manage", "Manage")]
GKIND = {"schema": "schema_group", "database": "database_group", "type-group": "type_group", "fold": "fold",
         "lane_group": "lane_group"}
ROWS_WORD = {"all": "all rows", "filtered": "filtered rows", "none": "no rows", "unknown": "rows unknown"}
MAX_MEMBERS = 1000  # members of a combined box sent for expansion (the graph groups them by schema, then type); the
# rest through the drill action
MAX_BOX = a.MAX_OBJECTS  # a tab diagram draws one box each up to this many objects / roles per lane

LOCK = threading.RLock()  # access.py keeps its lookups in module globals: build + answer under one lock
LOAD = threading.Lock()  # one Snowflake read at a time
MINE = {}
S = dict(sens={}, rows=[], breaks={}, view="shared", known=None)  # per request, set under LOCK


class ApiError(Exception):
    def __init__(self, status, detail, message=""):
        super().__init__(message or detail)
        self.status, self.detail, self.message = status, detail, message or detail


# ---------- data ----------

def connect():  # one connection per load; st_react.py may replace this
    from sf import connect as sf
    return sf()


def with_query(fn):
    """fn(query) with query(sql) -> list of dicts, on a fresh connection."""
    import sf
    conn = connect()

    def query(sql):
        cols, got = sf.rows(conn, sql)
        return [dict(zip(cols, r)) for r in got]

    try:
        return fn(query)
    finally:
        if sf.owned():  # inside Snowflake it is the app's session: keep it open
            conn.close()


def read_shared():
    return (a.fake() if MODE == "fake" else with_query(a.live) if DIRECT else with_query(lambda q: a.snapshot(q, WHERE)))


def load_shared(ask=False):
    """ask: a page wants it. Read directly from Snowflake (SOURCE=direct) only on a click (reload what=load): it can
    take minutes, and someone may want only My access; a copy in memory or .cache/ is used at once."""
    if ask and MODE == "snowflake" and DIRECT and not cache.ready(KEY):
        raise ApiError(409, "shared_not_loaded", "The shared data is read from Snowflake on request: Load shared data.")
    with LOAD:
        try:
            return cache.get(KEY, read_shared, disk=MODE == "snowflake")[0]
        except Exception as x:
            raise ApiError(503, "shared_unreadable", a.line(x))


def fetched():
    """When the shared data was read from its source (memory or the local file)."""
    return datetime.fromtimestamp(cache.MEM[KEY][1]).strftime("%Y-%m-%d %H:%M") if KEY in cache.MEM else None


def mine_entry(sid):
    m = MINE.get(sid) if sid else None
    if m and time.time() - m["at"] >= TTL:
        MINE.pop(sid, None)
        m = None
    return m


def mine_state(sid):
    m = mine_entry(sid)
    when = lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")
    return dict(loaded=bool(m), user=m["user"] if m else None, loaded_at=when(m["at"]) if m else None,
                expires_at=when(m["at"] + TTL) if m else None)


LOOPBACK = ("127.0.0.1", "localhost", "::1")


def mine_off():
    """Why My access is off here, else None. It reads with the server's own login, so it is the viewer's access only
    on their own machine with their own SSO login: not inside Snowflake (the owner's rights), not on a server others
    reach (HOST not loopback), not with a key pair (a service user). MY_ACCESS=1 / 0 decides outside Snowflake."""
    if a.INSIDE:
        return ("My access is not available inside Snowflake: the app runs with its owner's rights, not yours. "
                "Use the local version for your own access.")
    v = os.environ.get("MY_ACCESS")
    if v in ("0", "1"):
        return None if v == "1" else "My access is turned off here (MY_ACCESS=0)."
    if os.environ.get("HOST", "127.0.0.1") not in LOOPBACK:
        return ("My access is off on a shared server: it would read with the server's login, not yours. "
                "Run the local version on your own machine for your own access.")
    if MODE == "snowflake" and os.environ.get("SNOWFLAKE_PRIVATE_KEY_FILE"):
        return ("My access is off with a key-pair login: that is a service user, not you. Log in with SSO (no "
                "SNOWFLAKE_PRIVATE_KEY_FILE), or set MY_ACCESS=1 when the key pair is your own user.")
    return None


def load_mine(sid, fresh=False):
    """The logged-in user's own access: read with their rights, kept in server memory under sid and, like the shared
    data, in .cache/ for CACHE_HOURS (fresh: read again)."""
    why = mine_off()
    if why:
        raise ApiError(409, "mine_unavailable", why)
    for k in list(MINE):
        mine_entry(k)  # drops the expired ones
    at, ck = time.time(), None  # ck: the cache key (local copy, SQL copy)
    if MODE == "snowflake":
        ck = cache.name("mine", os.environ.get("SNOWFLAKE_USER") or sid, WHERE)
        if fresh:
            cache.drop(ck)
        try:
            d, at = cache.get(ck, lambda: with_query(lambda q: a.mine(q, WHERE.split(".")[0] or None)))
        except Exception as x:  # a cancelled SSO, no warehouse, the network: the real message, as for the shared data
            raise ApiError(503, "mine_unreadable", a.line(x))
    else:
        d0 = load_shared()
        with LOCK:
            d = a.only(d0, DEMO_USER)
    key = ("mine", os.urandom(16).hex())  # random: two sessions never share lookups or rule findings
    with LOCK:
        a.build(d, key)
        user = a.users[0] if a.users else ""
    MINE[sid] = dict(data=d, key=key, user=user, at=at, cache_key=ck)
    return mine_state(sid) | dict(notes=notes_of(d["run"], "mine"))


@contextmanager
def session(view, sid, builtin=False):
    """The lookups of the view's data built, under the lock; S holds sensitive objects, rule rows and graph rule hits.
    builtin: with Snowflake's built-in grants (a.BUILTIN); switching it rebuilds, rule checks included."""
    if view not in ("shared", "mine"):
        raise ApiError(400, "bad_param", "view must be shared or mine")
    if view == "shared":
        d = load_shared(ask=True)
        key = ("shared", d["run"].get("RUN_ID"), str(d["run"].get("FINISHED_AT")))
    else:
        m = mine_entry(sid)
        if not m:
            raise ApiError(409, "mine_not_loaded", "Load My access first.")
        d, key = m["data"], m["key"]
    with LOCK:
        a.build(d, key, builtin)
        a.capped.clear()
        S["view"], S["known"] = view, None
        S["sens"] = a.cached("sens", a.sensitive)
        rows = S["rows"] = a.cached("rows", a.rule_rows) if a.roles else []
        S["breaks"] = a.cached("breaks", lambda: breaks(rows, a.cached("ro", a.readonly_writes))) if rows else {}
        yield d


# ---------- small helpers ----------

def clean(x):
    """Plain JSON values: tuples and sets become lists, dates and decimals text and numbers."""
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (set, frozenset)):
        return [clean(v) for v in sorted(x, key=str)]
    if x is None or isinstance(x, (str, int, float, bool)):
        return x
    if isinstance(x, Decimal):
        return float(x)
    return str(x)


def plural(n, word):
    return f"{n} {word}{'s' * (n != 1)}"


def norm(k):
    """access.py kind -> NodeKind: "database" and "database_role" are database roles, an unknown value a group."""
    return "database_role" if k in ("database", "database_role") else k if k in KNOWN else "group"


def nk(n):
    return norm(a.node_kind(n))


def raw_of(n):
    k = a.node_kind(n)
    return None if k in KNOWN or k in ("database", "database_role") else k


def page_of(k):
    return "user" if k == "user" else "object" if k == "object" else "role"


def kind_label(n, k=None):
    k = k or a.kind_of(n)
    if k == "user":
        p = a.profile.get(n) or {}
        return str(p.get("TYPE") or "person").lower()  # the status has its own column
    return KIND.get(k, "Group role")


def ago(d):
    return "today" if d == 0 else "1 day ago" if d == 1 else f"{d} days ago"


def login(u):
    """(last login as text, "Dormant" | "Never" | "")."""
    p = a.profile.get(u) or {}
    d = a.login_days(u)
    if a.login_unknown(u):
        return "—", ""
    if d is None:
        return "never logged in", "Never"
    return f"{str(p.get('LAST_SUCCESS_LOGIN'))[:16]} · {ago(d)}", "Dormant" if a.is_dormant(u) else ""


def type_rank(k):
    return 0 if a.is_data(k) else 1 if k == "WAREHOUSE" else 3 if k in ("DATABASE", "SCHEMA") else 2


def arrow(p):
    return " > ".join([a.node_name(p[0])] + list(p[1:])) if p else ""


def flag(p, key, default=False):
    return {"1": True, "0": False}.get(p.get(key, ""), default)


def depth_of(p):
    v = p.get("depth", "")
    return int(v) if v.isdigit() else None


def csv_text(cols, rows, head=()):
    f = io.StringIO()
    w = csv.writer(f)
    w.writerows(list(head) + ([[]] if head else []))
    w.writerow(cols)
    w.writerows(rows)
    return f.getvalue()


def link(label, page, **params):
    return dict(label=label, page=page, params={k: v for k, v in params.items() if v})


def banner(tone, title, lines=(), links=()):
    return dict(tone=tone, title=title, lines=list(lines), links=list(links))


def need(cond, message):
    if not cond:
        raise ApiError(404, "not_found", message)


# ---------- rule texts and notes ----------

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


IP = "IMPORTED PRIVILEGES on database SNOWFLAKE"


def note_info(k, source, view):
    """A NOTES key in plain words: (title, what it means for the app, how to fix it or None)."""
    mine = view == "mine"
    if k == "usage":
        return (("Query history: 7 days only", "Roles and warehouses used before that look unused.",
                 f"{IP} gives 30 days.") if source == "INFORMATION_SCHEMA" else
                ("No query history", "No 'last used' for roles and warehouses. Grants and paths are complete.",
                 f"{IP}." if not mine else "None needed: grants and paths are complete."))
    return {
        "applicable_roles": ("Role list fallback unread", "Only a fallback: role links come from SHOW GRANTS.", None),
        "grants": ("Some roles unreadable", "Their privileges are missing; their role links are shown.",
                   "Ask the owner of those roles, or use the shared snapshot.") if mine else
                  ("Grants read with SHOW", "Slow (one query per role). Roles named in the error are missing.",
                   f"{IP}: one fast, complete read."),
        "user_roles": ("Your direct roles guessed", "What you reach is right; a path may start at another role.", None)
                      if mine else ("User roles read with SHOW", "Complete, but slow.", f"{IP}."),
        "users": ("User details unread", "Default role, disabled state and last login unknown: dormant checks can't judge.",
                  f"{IP}."),
        "tags": ("No sensitive tags", "My access can't read tags: no sensitive marks or rules here.",
                 "Use the shared snapshot.") if mine else
                ("Tags partly read", "Sensitive marks may be incomplete.", f"{IP}."),
        "policies": ("Policies partly read", "'Masked' / 'unmasked' on sensitive columns may be wrong.", f"{IP}."),
        "future_grants": ("Future grants unread", "No future grants: rule 15 can't run.", "Run the local version, "
                          "or SOURCE=objects (the procedure reads them).") if source == "UNAVAILABLE" else
                         ("Future grants partly read", "Future grants of the databases in the error are missing.",
                          "MANAGE GRANTS, or ownership of those schemas."),
        "streams": ("Streams unread", "The stream rule (22) can't run.", f"{IP}."),
        "object_use": ("No object usage", "Granted vs used has nothing to compare: ACCESS_HISTORY is not readable "
                       "(Enterprise edition or higher).", f"{IP}, on Enterprise edition."),
        "database_roles": ("Database roles partly read", "What the database roles in the error give is missing.",
                           "USAGE on those databases."),
        "error": ("Snapshot run failed", "The last SP_ACCESS_SNAPSHOT run failed.", "Run sql/2_snapshot.sql and read its error."),
    }.get(k, (k.replace("_", " ").capitalize(), "Read with a fallback, or partly.", None))


def loop_notes():
    """A side note per role loop (a.loops): path counts through it are approximate."""
    return [dict(key="role_loop", title="Role loop", raw=", ".join(x),
                 meaning=f"Roles {', '.join(x[:5])}{' ...' if len(x) > 5 else ''} hold each other: path counts through "
                 "them are approximate, and a page that lists every path can show more than it counts.",
                 fix="Snowflake refuses such grants: read the snapshot again once the change that made it is done.")
            for x in a.loops()]


def snap_time(run):
    """("2026-11-02 07:00 UTC · 13 h ago", older than 24 h)."""
    v = run.get("FINISHED_AT")
    if isinstance(v, datetime) and v.tzinfo:
        v = v.astimezone(timezone.utc)
    try:
        t = a.when(v)
    except Exception:
        t = None
    if t is None:
        return str(v), False
    h = max(0, (datetime.now(timezone.utc).replace(tzinfo=None) - t).total_seconds() / 3600)
    return f"{t:%Y-%m-%d %H:%M} UTC · " + (f"{h:.0f} h ago" if h < 48 else f"{h / 24:.0f} days ago"), h > 24


def notes_of(run, view):
    src = run.get("SOURCES") or {}
    return [dict(key=k, title=t, meaning=m, fix=f, raw=str(v))
            for k, v in (run.get("NOTES") or {}).items() for t, m, f in [note_info(k, src.get(k), view)]]


# ---------- rule hits on graph edges ----------

def breaks(rows, ro):
    """{(x, y, cls): [(num, severity, title)]} for the graph edges a rule finding's fix points at."""
    out = {}
    for x in rows:
        for g in x["edges"]:
            cls = "inherit" if g["priv"] is None else a.priv_class(g["priv"], g["kind"] or "")
            out.setdefault((a.uid(g["grantee"], g["user"]), g["to"], cls), {})[(x["num"], x["severity"], x["title"])] = 1
    for x in ro:
        for pv in x["privileges"]:
            k = (x["holder"], x["object"], a.priv_class(pv, a.kinds.get(x["object"], "")))
            out.setdefault(k, {})[("17", a.SEVERITY["17"], a.RULES["17"][0])] = 1
    return {k: list(v) for k, v in out.items()}


def hits(lanes, edges, info=None):
    """a.graph_info (or the given info) plus the break rule hits of the drawn edges."""
    out = {k: dict(v) for k, v in (a.graph_info(lanes, edges) if info is None else info).items()}
    for g in edges:
        k = (g[0], g[1], g[2] if len(g) > 2 else "inherit")
        if S["breaks"].get(k):
            x = out.setdefault(k, {})
            x["rules"] = sorted(set(x.get("rules", [])) | set(S["breaks"][k]), key=lambda t: int(t[0]))
    return out


# ---------- graphs ----------

def node_label(n):
    """(own name, "▦ table · SALES.CORE") for an object, a future grant; None for every other name."""
    k = a.kinds.get(n, "")
    if k.startswith("FUTURE"):
        return f"future {k.split(' ', 1)[1].lower()}s", n.rsplit(".", 1)[0]
    if a.role_kind(n) != "object":
        return None
    db, sc, nm = a.split_name(n, k)
    g, lab = ui.TYPE_ICON.get(k, ("·", k.lower()))
    return nm, f"{g} {lab}" + (f" · {db}.{sc}" if sc else f" · {db}" if db and db != nm else "")


def rule_dicts(rs):
    return [dict(num=r[0], severity=r[1], title=r[2]) for r in rs]


def lane_depth(label):
    m = re.search(r"(?:Depth |\bD)(\d+)", label)
    return int(m.group(1)) if m else None


def build_graph(title, lanes, edges, notes=None, info=None, kinds=None, selected=None, header="", level="object",
                note=None, full=False, bad=(), start=None, check=False, types=None, gx=None):
    """Graph JSON from access.py's (lanes, edges, notes): nodes with kinds, marks, rule hits and click actions, merged
    edges, and the expansion payload of every combined box (gx: {box: dict(members, edges, drill, ...)})."""
    notes, kinds, types, gx = notes or {}, kinds or {}, types or {}, gx or {}
    info = hits(lanes, edges, info)
    lane_of = {n: i for i, (_, ns) in enumerate(lanes) for n in ns}

    def action(n, gk):
        if gk in ("schema", "database", "type-group", "lane_group"):
            return dict(kind="expand", group=n)
        if gk == "fold":
            return dict(kind="full")
        k = nk(n)
        if check and k == "object" and start:
            return dict(kind="page", page="check", params=dict(name=start, obj=n))
        return dict(kind="page", page=page_of(k), params=dict(name=a.node_name(n)))

    def node(n, i, kd):
        gk = kd.get(n)
        kind = GKIND[gk] if gk else nk(n)
        name = n if gk else a.node_name(n)
        gi = info.get(n, {})
        label, sub, typ, db, sc = name, None, None, None, None
        if gk:
            cnt = (gx.get(n) or {}).get("count") or gi.get("count")
            sub = f"{cnt} {(gx.get(n) or {}).get('noun') or gi.get('noun') or 'objects'}" if cnt else None
            scope = n.split(" · ")[0]
            if gk == "type-group":
                typ = types.get(n) or (n.split(" · ", 1)[1] if " · " in n else None)
                db, _, sc = scope.partition(".")
            elif gk in ("schema", "database"):
                db, _, sc = n.split(" · ")[0].partition(".")  # a tab box id is "DB · 19 objects": the count is the sub
            label = n.strip("⋯ ").join(["⋯ ", " ⋯"]) if gk == "fold" else n.split(" · ")[0] if gk == "database" else n
        elif kind == "object":
            nl = node_label(n)
            if nl:
                label, sub = nl
            typ = a.kinds.get(n)
            db, sc, _ = a.split_name(n)
            db, sc = db or None, sc or None
        elif kind == "database_role":
            db, _, r = name.partition(".")
            label, sub = (r, db) if r else (name, None)
        badge, tip = notes.get(n, ("", ""))
        rules = rule_dicts(gi.get("rules", []))
        lines = [kind_label(name) if kind == "user" else KIND.get(a.role_kind(n), "Group role") if not gk else
                 f"{len(gx.get(n, {}).get('members', []))} combined"] + ([tip] if tip else []) + [
            f"Rule {x['num']} ({x['severity']}): {x['title']}" for x in rules[:5]]
        marks = [m for m, on in (("disabled", kind == "user" and a.is_disabled(name)), ("sensitive", n in S["sens"]),
                                 ("bad", n in bad)) if on]
        classes = None if gk or kind in ("user", "object") else [  # what the role's own grants allow (folded box counts)
            c for c in a.CLS_ORDER if c in {a.priv_class(pv, k) for pv, k, _ in a.granted.get(name, [])}]
        return dict(id=n, name=name, label=label, sub=sub, kind=kind, raw_kind=None if gk else raw_of(n), type=typ,
                    db=db, schema=sc, lane=i, depth=lane_depth(lanes[i][0]) if i < len(lanes) else None, badge=badge,
                    tip="\n".join(lines), marks=marks, rules=rules, action=action(n, gk), group=n if gx.get(n) else None,
                    classes=classes)

    def edge_list(es, lanes_of, inf):
        out = {}
        for e in es:
            x, y = e[0], e[1]
            cls = e[2] if len(e) > 2 else ("inherit_db" if a.role_kind(y) == "database" else "inherit")
            ik = (x, y, e[2] if len(e) > 2 else "inherit")
            g = out.setdefault((x, y, cls), dict(
                id=f"{x}>{y}>{cls}", source=x, target=y, cls=cls, privs=[], count=None,
                back=x in lanes_of and y in lanes_of and lanes_of[x] >= lanes_of[y],
                rules=rule_dicts(inf.get(ik, {}).get("rules", [])), has=inf.get(ik, {}).get("has"),
                lacks=inf.get(ik, {}).get("lacks")))
            if len(e) > 3 and e[3] and e[3] not in g["privs"]:
                g["privs"].append(e[3])
            if len(e) > 4:
                g["count"] = max(g["count"] or 0, e[4])
        for g in out.values():
            g["privs"] = ui.psort(g["privs"])
        return list(out.values())

    nodes = [node(n, i, kinds) for i, (_, ns) in enumerate(lanes) for n in ns]
    eds = edge_list(edges, lane_of, info)
    groups = {}
    for gid, x in gx.items():
        mem = x["members"]
        gl = lane_of.get(gid, len(lanes) - 1)
        shown = mem[:MAX_MEMBERS]
        keep = set(shown)
        es = [e for e in x["edges"] if e[1] in keep or e[0] in keep]
        lo = dict(lane_of) | {n: gl for n in shown}
        sens = sum(n in S["sens"] for n in mem)
        gi = info.get(gid, {})
        classes = x.get("classes") or [c for c in a.CLS_ORDER if c in {e[2] for e in es if len(e) > 2}]
        groups[gid] = dict(
            kind=GKIND[kinds[gid]], label=gid, noun=x.get("noun") or gi.get("noun") or "objects",
            count=x.get("count") or gi.get("count") or len(mem), sensitive=x.get("sensitive", gi.get("sensitive", sens)),
            findings=x.get("findings", gi.get("findings", 0)), classes=classes,
            nodes=[node(n, gl, {}) for n in shown], edges=edge_list(es, lo, hits([("", shown)], es)),
            truncated=max(0, len(mem) - MAX_MEMBERS), drill=x.get("drill"))
    allnodes = nodes + [n for g in groups.values() for n in g["nodes"]]
    return dict(
        title=title, header=header, level=level, note=note, full=full, selected=selected,
        lanes=[dict(index=i, label=lab, depth=lane_depth(lab)) for i, (lab, _) in enumerate(lanes)],
        nodes=nodes, edges=eds, groups=groups,
        legend=dict(kinds=list(dict.fromkeys(n["kind"] for n in nodes)),
                    edges=list(dict.fromkeys(e["cls"] for e in eds)),
                    marks=sorted({m for n in nodes for m in n["marks"]}),
                    rules=any(n["rules"] for n in allnodes) or any(e["rules"] for e in eds)))


def member_groups(rows, level, schema):
    """Members and holder edges of every combined box of graph_input (same keys as there)."""
    out = {}
    for r in rows:
        k = (f"{schema} · {r['type']}" if level == "type" else a.group_key(r, level)
             if (r["schema"] if level == "schema" else level == "database" and r["database"]) else None)
        if k is None:
            continue
        g = out.setdefault(k, dict(members=[], edges=[], drill=dict(kind="otype", otype=r["type"]) if level == "type"
                                   else dict(kind="drill", schema=k)))
        g["members"].append(r["object"])
        g["edges"] += [(h, r["object"], r["cls"], r["privilege"]) for h in r["holders"]]
    for g in out.values():
        g["members"] = sorted(dict.fromkeys(g["members"]))
        g["edges"] = list(dict.fromkeys(g["edges"]))
    return out


def fold_groups(orig, g):
    """Roles hidden by every fold box of a summary graph, with their links, taken from the full graph."""
    kids = {}
    for e in orig["edges"]:
        if len(e) == 2:
            kids.setdefault(e[0], []).append(e[1])
    shown = {n for _, ns in g["lanes"] for n in ns}
    out = {}
    for e in g["edges"]:
        if len(e) == 2 and g["kinds"].get(e[1]) == "fold":
            seen, todo = set(), list(kids.get(e[0], []))
            while todo:
                x = todo.pop()
                if x not in seen and x != e[0]:
                    seen.add(x)
                    todo += kids.get(x, [])
            mem = sorted(x for x in seen if x not in shown)
            ok = set(mem) | {e[0]}
            out[e[1]] = dict(members=mem, edges=[x for x in orig["edges"] if len(x) == 2 and x[0] in ok
                                                 and (x[1] in mem or x[1] in shown)],
                             noun="roles", drill=dict(kind="full"))
    return out


def input_graph(start, user, rows, schema=None, otype=None, default_only=False, limit=None, full=False):
    """graph_input() of a user or role (a summary when big, unless full) with its expansion payloads, or None."""
    g = a.graph_input(start, schema, default_only=default_only, limit=limit, user=user, otype=otype)
    if not g:
        return None
    use = [r for r in rows if not (r["privilege"] == "USAGE" and r["type"] in ("DATABASE", "SCHEMA"))
           and a.in_scope(r, schema) and otype in (None, r["type"])]
    gx = member_groups(use, g["level"], schema) if g["kinds"] else {}
    note, level, drawn = None, g["level"], False
    if a.too_big(g):
        if full:
            note, drawn = "Full chain of a big graph.", True
        else:
            orig, g = g, a.summary(g)
            gx = {k: v for k, v in gx.items() if k in g["kinds"]} | fold_groups(orig, g)
            level = "summary"
            note = (f"Summary: {plural(g['folded'], 'role')} between granted roles and grant holders "
                    f"{'is' if g['folded'] == 1 else 'are'} folded.")
    return dict(g=g, gx=gx, note=note, level=level, full=drawn)


def combine_tab(lanes, edges, notes, kinds):
    """Tab diagram with many boxes: objects over MAX_BOX become one box per database (the graph component folds crowded
    role lanes: database roles per database, group roles, then the rest). Returns lanes, edges, notes, kinds, gx."""
    gx, to = {}, {}  # to: member -> its box
    lanes = [(lab, list(ns)) for lab, ns in lanes]
    for i, (lab, ns) in enumerate(lanes):
        if lab in ("Object", "Objects") and len(ns) > MAX_BOX:
            by = {}
            for o in ns:
                by.setdefault(a.split_name(o)[0] or o, []).append(o)  # account-level objects stay single
            ids = []
            for k, os_ in by.items():
                if len(os_) == 1:
                    ids.append(os_[0])
                    continue
                gid = f"{k} · {len(os_)} objects"
                gx[gid] = dict(members=os_, count=len(os_), noun="objects", drill=dict(kind="drill", schema=k))
                kinds[gid] = "database"
                to.update({o: gid for o in os_})
                ids.append(gid)
            lanes[i] = (lab, ids)
    if not gx:
        return lanes, edges, notes, kinds, gx
    new, per = [], {}
    for e in edges:
        x, y = to.get(e[0], e[0]), to.get(e[1], e[1])
        if x == y:
            continue
        if len(e) == 2:
            new.append((x, y))
        else:  # one line per (holder, box, class, privilege), counting its objects
            per.setdefault((x, y, e[2], e[3]), set()).add(e[1])
    new = list(dict.fromkeys(new)) + [(x, y, c, pv, len(o) if y in gx else 1) for (x, y, c, pv), o in per.items()]
    for gid, g in gx.items():  # what an expansion draws: the original links, outside ends mapped to their box
        mem = set(g["members"])
        g["edges"] = [(e[0] if e[0] in mem else to.get(e[0], e[0]), e[1] if e[1] in mem else to.get(e[1], e[1]), *e[2:])
                      for e in edges if e[0] in mem or e[1] in mem]
    notes = {n: v for n, v in notes.items() if n not in to}
    return lanes, new, notes, kinds, gx


def tab_graph(start, user, rows, walked=(), what="privileges", full_title="Graph"):
    """A Privileges tab's own diagram: start, the roles on the way, the objects of just these rows (walked: role paths).
    Over MAX_OBJECTS rows only the shortest path of each row is drawn."""
    big = len(rows) > a.MAX_OBJECTS
    g = a.down_graph(start, [r | dict(paths=r["paths"][:1]) for r in rows] if big else rows, walked, user)
    if not g:
        return None
    lanes, edges, notes = [x for x in g[0] if x[1]], g[1], g[2]
    kinds = {}
    lanes, edges, notes, kinds, gx = combine_tab(lanes, edges, notes, kinds)
    n = len(rows) or len(walked)
    return build_graph(full_title, lanes, edges, notes, kinds=kinds, header=f"{n} {what}" + (" · shortest path each" if big else ""),
                       level="database" if any(k == "database" for k in kinds.values()) else "object",
                       start=start, check=user, gx=gx)


# ---------- privilege rows, tabs, account ----------

def tab_of(pv, kind, obj=""):
    k = (kind or "").replace("FUTURE ", "")
    if k == "ACCOUNT":
        return "account"
    if k == "WAREHOUSE":
        return "warehouses"
    c = a.priv_cat(pv, kind)
    if c == "hold":
        return "database_roles" if a.role_kind(obj) == "database" else "granted"
    return c


def priv_row(r, user_page=False, hidden=False):
    row = dict(privilege=r["privilege"], cls=r["cls"], tab=tab_of(r["privilege"], r["type"], r["object"]),
               type=r["type"], object=r["object"], database=r["database"], schema=r["schema"], name=r["name"],
               future_label=a.future_label(r["object"], r["type"]), holder=r["holder"], depth=r["depth"],
               path=r["path"], count=r["count"], paths_note=a.paths_note(r), sensitive=r["object"] in S["sens"],
               hidden=hidden)
    if user_page:
        row["granted"] = r["granted"]
    return row


def reach_row(x):
    return dict(role=x["role"], kind=norm(x["kind"]), tab="database_roles" if x["kind"] == "database" else "granted",
                depth=x["depth"], direct=x["direct"], path=x["path"], count=x["count"], admin=x["role"] in a.ADMIN)


def account(admin, acct):
    """Account tab: admin roles first, then account-level privileges, "via PUBLIC" grouped."""
    return dict(admin=[dict(role=p[-1], path=p) for p in admin],
                privileges=sorted((dict(privilege=pv, path=p, via_public=p[-1] == "PUBLIC") for pv, p in acct),
                                  key=lambda x: (x["via_public"], x["privilege"])),
                public=sorted({pv for pv, p in acct if p[-1] == "PUBLIC"}))


def tab_rows(rows, hidden, reach, t):
    """(privilege rows, role paths) drawn by tab t of the Privileges tabs."""
    if t in ("granted", "database_roles"):
        return [], [x["path"] for x in reach if ("database_roles" if x["kind"] == "database" else "granted") == t]
    if t == "all":
        return rows, []
    return [r for r in rows + hidden if tab_of(r["privilege"], r["type"], r["object"]) == t], []


def tab_list(rows, hidden, reach, acct):
    n = {k: 0 for k, _ in TABS}
    for r in rows + hidden:
        n[tab_of(r["privilege"], r["type"], r["object"])] += 1
    for x in reach:
        n["granted" if x["kind"] != "database" else "database_roles"] += 1
    n["account"] = max(n["account"], len(acct["admin"]) + len(acct["privileges"]))
    return [dict(key=k, label=lab, count=n[k]) for k, lab in TABS if n[k]] + [dict(key="all", label="All", count=len(rows))]


def impact(x):
    """The finding's impact as a tag: who loses access when it is fixed, or how many read in clear."""
    n, who = x["affects"], x["losers"]
    if n is None or x["impact"] == "—":
        return None
    if x["edges"] and not n:
        return dict(text="Safe to fix: everyone keeps access another way", tone="ok")
    if who:
        names = ", ".join(who[:3]) + (f" +{len(who) - 3}" if len(who) > 3 else "")
        return dict(text=f"{plural(n, 'user')} lose{'s' * (n == 1)} access: {names}", tone="warn")
    return dict(text=x["impact"], tone="bad" if x["num"] == "6" else "warn")


def finding(x):
    """One finding, the same shape on every page (web/API.md Finding)."""
    user = x["kind"] == "user"
    return dict(num=x["num"], title=x["title"], severity=x["severity"], area=RULE_INFO.get(x["num"], ("", "Other"))[1],
                grantee=a.uid(x["grantee"], user), kind=norm(x["kind"]), what=x["detail"], impact=impact(x),
                people=sorted({x["grantee"]} if user else set()) or x["losers"][:50], paths=x["paths"][:5],
                iac=x["iac"], sql=x["sql"], same_fix=x["same_fix"], changes=a.fix_changes(x["edges"]),
                objects=a.finding_objects(x))


def findings_of(name, user, skip=()):
    """Rule findings of a user or role (for a user also of the roles granted to it directly)."""
    via = set(a.roles_of.get(name, [])) if user else set()
    xs = [x for x in S["rows"] if x["num"] not in skip and ((x["grantee"] == name and (x["kind"] == "user") == user)
                                                           or (x["grantee"] in via and x["kind"] != "user"))]
    return [finding(x) for x in xs], len(xs)


def usage(u):
    """Role usage card: every role granted to u straight, held against used in the query history (unused first, with
    what removing it takes away), and the warehouses."""
    src = a.run["SOURCES"].get("usage")
    days = 7 if src == "INFORMATION_SCHEMA" else 30
    rows = a.used.get(u, [])
    by = {}
    for x in rows:
        if x["KIND"] in ("ROLE", "SECONDARY ROLE"):
            y = by.setdefault(x["NAME"], dict(queries=0, last_used="", secondary=True))
            y["queries"] += x["QUERIES"]
            y["last_used"] = max(y["last_used"], str(x["LAST_USED"])[:16])
            y["secondary"] &= x["KIND"] == "SECONDARY ROLE"
    dr = (a.profile.get(u) or {}).get("DEFAULT_ROLE")
    roles = []
    for r in sorted(a.roles_of.get(u, [])):
        x = by.get(r)
        status = "unused" if not x else "secondary" if x["secondary"] else "used"
        takes = len({o for _, o in a.loses(u, u, r)}) if status == "unused" else None
        roles.append(dict(role=r, kind=norm(a.role_kind(r)), default=r == dr, status=status,
                          queries=x["queries"] if x else 0, last_used=x["last_used"] if x else None, takes=takes))
    roles.sort(key=lambda r: (r["status"] != "unused", -r["queries"], r["role"]))
    return dict(days=days, source=f"Query history, last {days} days, from {'INFORMATION_SCHEMA' if days == 7 else 'ACCOUNT_USAGE'}",
                readable=src != "UNAVAILABLE", roles=roles,
                warehouses=[dict(name=x["NAME"], queries=x["QUERIES"], last_used=str(x["LAST_USED"])[:16])
                            for x in rows if x["KIND"] == "WAREHOUSE"])


def role_usage(r):
    """Role page: how many users holding r used it (as primary or secondary role) in the query history."""
    holders = sorted(a.ups(r)[1])
    used = {u for u in holders if any(x["NAME"] == r and x["KIND"] in ("ROLE", "SECONDARY ROLE") for x in a.used.get(u, []))}
    return dict(holders=len(holders), used=len(used), unused=[u for u in holders if u not in used][:200])


def scope_of(p, rows):
    sc = p.get("schema", "")
    return sc if sc in a.scopes(rows) else ""


# ---------- user ----------

def user_ctx(p, view):
    """Everything the User page and its tab diagrams share: the user, filters and the filtered privilege rows."""
    need(a.users, "No users in this data.")
    mine = view == "mine"
    u = a.users[0] if mine else p.get("name") or (DEMO_USER if DEMO_USER in a.users else a.users[0])
    need(u in a.users, f"{u} is not in this snapshot")
    limit, default_only, data_only = depth_of(p), p.get("roles") == "default", flag(p, "dataonly", True)
    every = a.grants(u, True, default_only, limit)
    scope, otype = scope_of(p, every), p.get("otype") or None
    ok = lambda r: a.in_scope(r, scope) and otype in (None, r["type"])
    rows = [r for r in every if ok(r) and not (data_only and r["privilege"] == "USAGE" and r["type"] in ("DATABASE", "SCHEMA"))]
    rows.sort(key=lambda r: (type_rank(r["type"]), r["object"], r["privilege"]))
    on, pv = p.get("on", ""), p.get("priv", "")
    objs, privs = sorted({r["object"] for r in rows}), sorted({r["privilege"] for r in rows})
    rows = [r for r in rows if (not on or r["object"] == on) and (not pv or r["privilege"] == pv)]
    hidden = [r for r in every if data_only and r["privilege"] == "USAGE" and r["type"] in ("DATABASE", "SCHEMA") and ok(r)
              and (not on or r["object"] == on) and (not pv or r["privilege"] == pv)]
    reach = a.reach(u, True, default_only, limit)
    if scope:
        path = {n for r in rows for x in r["paths"] for n in x[1:-1]}
        reach = [x for x in reach if x["role"] in path]
    return dict(u=u, mine=mine, limit=limit, default_only=default_only, data_only=data_only, every=every, scope=scope,
                otype=otype, rows=rows, hidden=hidden, reach=reach, on=on, pv=pv, objs=objs, privs=privs)


def user_page(p, view):
    c = user_ctx(p, view)
    u, rows, reach, scope = c["u"], c["rows"], c["reach"], c["scope"]
    pr = a.profile.get(u) or {}
    admin, acct = (a.admin_paths(u, True, c["default_only"], c["limit"]),
                   a.account_privs(u, True, c["default_only"], c["limit"]))
    banners = []
    if p.get("schema") and not scope:
        banners.append(banner("info", f"{p['schema']} is not reached by {u}", ["Showing all of its access."]))
    if c["default_only"]:
        n = len(a.grants(u, True, False, c["limit"])) - len(c["every"])
        if n:
            banners.append(banner("info", f"{plural(n, 'grant')} hidden in this mode", [
                "Default role only leaves out roles granted next to the default role (direct grants included). "
                "Switch to All granted roles to see them."]))
    if a.is_disabled(u):
        banners.append(banner("warn", "Disabled user: access below is dormant; revoke or drop",
                              ["The user can't log in, but every grant comes back if it is enabled again."]))
    elif a.is_dormant(u) and not a.is_service(u):
        d = a.login_days(u)
        banners.append(banner("warn", "Dormant user: " + ("never logged in" if d is None else f"no login for {d} days"),
                              ["Unused access is risk: revoke the roles or disable the user."],
                              [link("Rule 16", "rules", rule="16"), link("Rule 7", "rules", rule="7")]))
    findings, total = findings_of(u, True)
    text, mark = login(u)
    sec = str(pr.get("DEFAULT_SECONDARY_ROLES") or "")
    twice = sum(r["count"] > 1 for r in rows)
    sens = sorted({r["object"] for r in rows if r["object"] in S["sens"] and r["privilege"] in a.READ_PRIVS})
    acc = account(admin, acct)
    # graph: one object or privilege = just those rows, else graph_input (grouped on big accounts)
    if c["on"] or c["pv"]:
        g = a.down_graph(u, rows, user=True)
        graph = g and build_graph("Role hierarchy, by depth", g[0], g[1], g[2], header=f"{len(rows)} privileges shown",
                                  start=u, check=True)
    else:
        ig = input_graph(u, True, c["every"], scope or None, c["otype"], c["default_only"], c["limit"], flag(p, "full"))
        graph = ig and build_graph("Role hierarchy, by depth", ig["g"]["lanes"], ig["g"]["edges"], ig["g"]["notes"],
                                   ig["g"]["info"], ig["g"]["kinds"], header=ig["g"]["header"], level=ig["level"],
                                   note=ig["note"], full=ig["full"], start=u, check=True, types=ig["g"].get("types"),
                                   gx=ig["gx"])
    multi = [(r, x) for r in rows if r["count"] > 1 for x in r["paths"]]
    use, dr = a.used_roles(u), pr.get("DEFAULT_ROLE")
    src = a.run["SOURCES"].get("usage")
    shared = c["mine"] is False
    objs = {r["object"] for r in rows}
    return dict(
        view=view,
        user=dict(id=a.uid(u, True), name=u, type=str(pr.get("TYPE") or "PERSON"), status=a.status(u),
                  disabled=a.is_disabled(u), service=a.is_service(u), default_role=dr or None,
                  secondary_roles="All" if "ALL" in sec.upper() else "None", default_warehouse=pr.get("DEFAULT_WAREHOUSE") or None,
                  last_login=str(pr.get("LAST_SUCCESS_LOGIN"))[:16] if pr.get("LAST_SUCCESS_LOGIN") else None,
                  last_login_text=text, login_mark=mark, login_days=a.login_days(u)),
        filters=dict(roles="default" if c["default_only"] else "all", depth=c["limit"], dataonly=c["data_only"],
                     schema=scope, otype=c["otype"] or "", on=c["on"], priv=c["pv"], objects=c["objs"], privileges=c["privs"]),
        banners=banners, findings=findings, findings_total=total,
        kpis=dict(privileges=len(rows), objects=len(objs), paths=sum(r["count"] for r in rows), multi=twice,
                  roles=len(reach), roles_direct=sum(x["direct"] for x in reach),
                  deepest=max((r["depth"] for r in rows), default=0), sensitive=len(sens) if (S["sens"] or shared) else None,
                  sensitive_known=bool(S["sens"]) or shared, admin_roles=len({x[-1] for x in admin}),
                  account_privs=len(acct)),
        account=acc, graph=graph, tabs=tab_list(rows, c["hidden"], reach, acc),
        privileges=[priv_row(r, True) for r in rows] + [priv_row(r, True, True) for r in c["hidden"]],
        roles=[reach_row(x) for x in reach],
        multi=dict(rows=[dict(privilege=r["privilege"], cls=r["cls"], object=r["object"], depth=a.depth(x[:-1], True),
                              path=x) for r, x in multi[:300]], total=len(multi), shown=min(300, len(multi))),
        can_read=[v for v in a.data_views(u, True) if not (scope or c["on"] or c["pv"]) or v["object"] in objs] if shared else None,
        sensitive=sens_reach(u, objs if scope else None),
        granted=[dict(role=r, kind=norm(a.role_kind(r)), default=r == dr, used=use.get(r) and dict(
            queries=use[r]["queries"], last_used=str(use[r]["last_used"])[:16]),
            used_text="not readable" if src == "UNAVAILABLE" else f"{use[r]['queries']} queries · {str(use[r]['last_used'])[:10]}"
            if r in use else "not used") for r in sorted(a.roles_of.get(u, []))],
        usage=usage(u), capped=sorted(a.capped))


def sens_reach(u, objs=None):
    """Sensitive data a user can see, per granted role (the User page tab and What they see); None without tags."""
    if not S["sens"]:
        return None
    rs = [x for x in a.sensitive_reach(u) if objs is None or x["object"] in objs]
    return dict(known=True, roles=[r for r in dict.fromkeys(x["role"] for x in rs) if any(y["role"] == r and y["path"] for y in rs)],
                rows=[dict(object=x["object"], cols=x["cols"], role=x["role"], path=x["path"],
                           text=mask_text(x["role"], x["object"])) for x in rs if x["path"]])


# ---------- access (screen 1: a person or a role, one row per object on the ladder) ----------

SHORT = {"1": "technical role held directly", "2": "privilege on a functional role", "3": "read held twice",
         "4": "owner role on a consumer", "5": "admin role on a person", "6": "sensitive column unmasked",
         "7": "dormant reads sensitive", "8": "disabled holds roles", "9": "granted to everyone",
         "10": "person writes sensitive", "11": "sensitive via group role", "12": "admin as default role",
         "13": "orphan role", "14": "deep chain", "15": "future grant on sensitive", "16": "dormant holds roles",
         "17": "read role can write", "18": "unusual privilege set", "19": "EXECUTE TASK on a person",
         "20": "task OPERATE outside owner", "21": "warehouse MODIFY / OPERATE", "22": "stream without table read",
         "23": "CREATE on a read-only role"}
SEV_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def row_findings(subject, user, objs, rows):
    """Findings that sit on each access row: the finding is about the subject or a role on the row's paths, and one of
    its grants (edges) is a privilege the row has on the object, or a role link on those paths (data and runnable rows
    only: a link explains a privilege, not a power). One list per entry of objs."""
    xs = {}  # grantee -> its findings (a finding's chip depends only on its rule number)
    for x in S["rows"]:
        if x["kind"] != "user" or (user and x["grantee"] == subject):
            xs.setdefault(x["grantee"], []).append(x)
    lists = {}  # rows of one holder and object share their path list: each list once
    for r in rows:
        lists.setdefault(r["object"], {})[id(r["paths"])] = r["paths"]
    by = {o: {n for ps in ls.values() for q in ps for n in q[:-1]} for o, ls in lists.items()}
    out = []
    for o in objs:
        on = by.get(o["object"], set())
        hit = {}
        for x in (x for g in on & xs.keys() for x in xs[g]):
            if x["num"] in hit:
                continue
            if any(e["grantee"] in on and ((e["to"] == o["object"] and e["priv"] in (None, *o["privileges"]))
                                           or (e["to"] in on and not e["priv"] and o["category"] in ("data", "runnable")))
                   for e in x["edges"]):
                hit[x["num"]] = dict(num=x["num"], severity=x["severity"], label=SHORT.get(x["num"], x["title"]))
        out.append(sorted(hit.values(), key=lambda f: (SEV_RANK.get(f["severity"], 9), int(f["num"]))))
    return out


def access_page(p, view):
    """A person (user=) or a role (role=), or My access: one row per object at its highest level, things they can run,
    powers over the account, where the access is (per schema) and why they have it (roles)."""
    mine = view == "mine"
    role = p.get("role", "") if not mine else ""
    if role:
        need(role in a.roles, f"{role} is not in this snapshot")
        name, user = role, False
    else:
        need(a.users, "No users in this data.")
        name = a.users[0] if mine else p.get("user") or (DEMO_USER if DEMO_USER in a.users else a.users[0])
        need(name in a.users, f"{name} is not in this snapshot")
        user = True
    rows = [] if not user and role in a.ADMIN else a.grants(name, user)
    objs = a.access_objects(rows, user)
    views = {v["object"]: v for v in a.data_views(name, user)} if not mine or S["sens"] else {}
    chips = row_findings(name, user, objs, rows)
    first = {}
    for r in rows:
        first.setdefault(r["object"], r["paths"])
    for o, f in zip(objs, chips):
        v = views.get(o["object"])
        o["sensitive"] = o["object"] in S["sens"]
        o["columns"] = [dict(column=c["column"], state=c["state"], reason=c["reason"]) for c in v["columns"] if c["sensitive"]] if v else []
        o["findings"] = f
        o["label"] = a.future_label(o["object"], o["type"])
        o["paths"] = first.get(o["object"], [])[:5]
    rank = lambda o: (min((SEV_RANK.get(f["severity"], 9) for f in o["findings"]), default=9), not o["sensitive"],
                      -a.LEVELS.index(o["level"]) if o["level"] else 0, o["object"])
    objs.sort(key=rank)
    counts = a.ladder_counts(objs)
    data = [o for o in objs if o["category"] == "data"]
    counts["sensitive"] = sum(o["sensitive"] and o["level"] != "names" and (not o["columns"] or any(c["state"] != "masked" for c in o["columns"]))
                              for o in data)  # sensitive and seen in clear (or unknown)
    counts["schemas"] = len({(o["database"], o["schema"] or o["object"]) for o in data})
    heat = {}
    for o in data:
        k = f'{o["database"]}.{o["schema"]}' if o["schema"] else o["object"]
        h = heat.setdefault(k, dict(schema=k, read=0, change=0, own=0, sensitive=0))
        i = a.LEVELS.index(o["level"]) if o["level"] else 0
        h["read"] += i >= 1
        h["change"] += i >= 2
        h["own"] += i >= 3
        h["sensitive"] += o["sensitive"]
    pr = (a.profile.get(name) or {}) if user else {}
    if user:
        dr, sec = pr.get("DEFAULT_ROLE"), "ALL" in str(pr.get("DEFAULT_SECONDARY_ROLES") or "").upper()
        text, mark = login(name)
        top = sorted(a.roles_of.get(name, []), key=lambda r: (r != dr, r))
        why = [dict(role=r, kind=norm(a.role_kind(r)), note="default" if r == dr else "secondary" if sec else "",
                    kids=sorted(a.holds.get(r, []))) for r in top]
        if "PUBLIC" not in top:
            why.append(dict(role="PUBLIC", kind="group", note="everyone", kids=sorted(a.holds.get("PUBLIC", []))))
        who = dict(kind="user", name=name, id=a.uid(name, True), type=str(pr.get("TYPE") or "PERSON"), status=a.status(name),
                   disabled=a.is_disabled(name), last_login=text, login_mark=mark, default_role=dr or None, secondary_all=sec,
                   held_by=None)
    else:
        rs, us = a.ups(name)
        why = [dict(role=x, kind=nk(x), note="holds it", kids=[]) for x in sorted(set(a.held_by.get(name, [])))]
        why.append(dict(role=name, kind=nk(name), note="this role", kids=sorted(a.holds.get(name, []))))
        who = dict(kind=nk(name), name=name, id=name, type=KIND.get(norm(a.role_kind(name)), "Role"), status=None,
                   disabled=False, last_login=None, login_mark="", default_role=None, secondary_all=False,
                   held_by=dict(users=len(us), roles=len(rs) - 1))
    findings, total = findings_of(name, user)
    return dict(view=view, who=who, counts=counts, objects=objs, heat=sorted(heat.values(), key=lambda h: h["schema"]),
                why=why, findings=findings, findings_total=total,
                deepest=max((o["depth"] for o in objs), default=0), roles=len(a.reach(name, user)))


def home_page(p, view):
    """Home: the default (or own) user's ladder counts, account risks by severity, data protection tiles."""
    me = a.users[0] if view == "mine" else (DEMO_USER if DEMO_USER in a.users else a.users[0] if a.users else None)
    mine = None
    if me:
        objs = a.access_objects(a.grants(me, True), True)
        mine = dict(user=me, counts=a.ladder_counts(objs))
    sev = {v: sum(x["severity"] == v for x in S["rows"]) for v in ("Critical", "High", "Medium", "Low")}
    g = a.governance_kpis()
    unmasked = sorted({x["grantee"].split(".")[-1] + "." + x["detail"].split(" ")[1].rstrip(":") for x in S["rows"] if x["num"] == "6"})[:8]
    dormant = sorted({x["grantee"] for x in S["rows"] if x["num"] == "7"})
    counts = dict(users=len(a.users), roles=len(a.roles), objects=len(a.objects), sensitive=len(S["sens"]))
    per_rule = {}
    for x in S["rows"]:
        per_rule[x["num"]] = per_rule.get(x["num"], 0) + 1
    return dict(view=view, me=mine, risks=sev if view == "shared" else None, counts=counts,
                per_rule=per_rule if view == "shared" else None,
                protection=dict(unmasked=sum(x["num"] == "6" for x in S["rows"]), unmasked_names=unmasked,
                                dormant=len(dormant), dormant_names=dormant[:8], tagged=g["tagged_objects"],
                                masked=g["masked_columns"], row_tables=g["row_tables"],
                                row_list=[dict(object=o, policies=v) for o, v in a.row_tables().items()])
                if view == "shared" else None)


def mask_text(name, o, user=False):
    """What role name (or a user, with any role they hold) sees of sensitive object o: "EMAIL masked · PHONE clear ·
    no rows"."""
    v = a.data_view(name, o, user)
    m = [f'{c["column"]} {c["state"]}' for c in v["columns"] if c["sensitive"]]
    m += [ROWS_WORD[v["rows"]["state"]]] * bool(v["rows"]["policy"])
    return " · ".join(m) or "whole object, clear"


# ---------- role ----------

def role_ctx(p, view):
    need(a.roles, "No roles in this data.")
    name = p.get("name") or a.roles[0]
    if name not in a.roles:
        if name in a.ADMIN:
            raise ApiError(404, "not_found", f"No user or role holds {name} in this snapshot. See People with admin "
                                             "roles on Rule checks for who holds the other admin roles.")
        raise ApiError(404, "not_found", f"{name} is not in this snapshot")
    r = name
    limit = depth_of(p)
    admin_role = r in a.ADMIN
    every = [] if admin_role else a.grants(r)
    scope = scope_of(p, every)
    only_sens = flag(p, "sensitive")
    eff = [x for x in every if a.in_scope(x, scope) and (not only_sens or x["object"] in S["sens"])
           and p.get("otype", "") in ("", x["type"])]
    eff.sort(key=lambda x: (type_rank(x["type"]), x["object"], x["privilege"]))
    held = [] if admin_role else a.reach(r)
    if scope or only_sens:
        path = {n for x in eff for q in x["paths"] for n in q[1:-1]}
        held = [x for x in held if x["role"] in path]
    return dict(r=r, limit=limit, admin_role=admin_role, every=every, scope=scope, only_sens=only_sens, eff=eff,
                held=held, only_users=flag(p, "users"))


def role_page(p, view):
    c = role_ctx(p, view)
    r, limit, scope, every, admin_role = c["r"], c["limit"], c["scope"], c["every"], c["admin_role"]
    s, hold, full = a.role_stats(r, limit), a.holds_of(r), a.held(r, limit)
    up = [x for x in full if x["kind"] == "user"] if c["only_users"] else full
    if scope:
        hold = [h for h in hold if a.in_scope(h, scope)]
    owner = [g for g, pv, t in a.on.get(r, []) if pv == "OWNERSHIP" and t == "ROLE"]
    ro = a.readonly_writes(r)
    admin, acct = a.admin_paths(r), a.account_privs(r)
    findings, total = findings_of(r, False, {"17"} if ro else ())
    banners = []
    if p.get("schema") and not scope:
        banners.append(banner("info", f"{p['schema']} is not reached by {r}", ["Showing all of its access."]))
    if admin_role:
        banners.append(banner("bad", "Admin role: inherits every role below it (hierarchy hidden)", [
            "Its effective privileges are those of every custom role, so they are not listed here."],
            [link("People with admin roles", "rules")]))
    sc = [x for x in every if a.in_scope(x, scope)]
    # graph: who holds r (up), r, then everything r reaches
    lanes, edges, notes, sel = a.role_graph(r, up, ro)
    above = {n for _, ns in lanes[:sel] for n in ns}
    lanes = [(lab.replace("Depth ", "Held by · D"), ns) for lab, ns in lanes[:sel]] + [lanes[sel]]
    edges = [x for x in edges if len(x) == 2 and x[0] in above]
    ig = None if admin_role else input_graph(r, False, every, scope or None, p.get("otype") or None, full=flag(p, "full"))
    info, kinds, gx, types, header, level, note = a.graph_info(lanes, edges), {}, {}, {}, "", "object", None
    if ig:
        g = ig["g"]
        for k, v in info.items():
            x = g["info"].setdefault(k, {})
            x["rules"] = sorted(set(x.get("rules", [])) | set(v.get("rules", [])), key=lambda t: int(t[0]))
        lanes += [(lab.replace("Depth ", "Holds · D"), ns) for lab, ns in g["lanes"][1:]]
        edges += g["edges"]
        notes = notes | g["notes"]
        info, kinds, gx, types, header, level, note = g["info"], g["kinds"], ig["gx"], g.get("types"), g["header"], ig["level"], ig["note"]
    graph = build_graph("Held by (up) and holds (down)", lanes, edges, notes, info, kinds, selected=r, header=header,
                        level=level, note=note, full=bool(ig and ig["full"]), bad={x["holder"] for x in ro}, types=types, gx=gx)
    # held by, with "if revoked from"
    direct = sorted(set(a.held_by.get(r, [])) | {a.uid(u, True) for u in a.users_of.get(r, [])})
    cut = p.get("cut", "")
    cut = cut if cut in direct else ""
    loses, lost, revoke = {}, set(), None
    if cut:
        for x in up:
            if all((cut, r) in zip(q, q[1:]) for q in x["paths"]):
                lost.add((x["grantee"], x["kind"]))
                if x["kind"] == "user":
                    loses[x["grantee"]] = a.loses(x["grantee"], a.node_name(cut), r)
        iac, sql = a.fix_text([a.role_edge(a.node_name(cut), r, a.node_kind(cut) == "user")])
        revoke = dict(grantee=a.node_name(cut), lost=len(lost), users=len(loses), iac=iac, sql=sql)
    held_rows = [dict(grantee=x["grantee"], id=a.uid(x["grantee"], x["kind"] == "user"), kind=norm(x["kind"]),
                      kind_label=kind_label(x["grantee"], x["kind"]) + (" · granted directly" if x["direct"] else ""),
                      status=a.status(x["grantee"]) if x["kind"] == "user" else None, depth=x["depth"],
                      direct=x["direct"], only_via=x["only_via"], path=x["path"], count=x["count"],
                      # no grantee picked: a direct holder loses the role when its own grant is its only path
                      loses_it=(x["grantee"], x["kind"]) in lost if cut else x["direct"] and x["count"] == 1,
                      loses=loses.get(x["grantee"], [])) for x in up]
    # holds as a has / lacks grid
    objs = {}
    for h in hold:
        if not h["type"].startswith("FUTURE") and h["type"] != "ACCOUNT":
            objs.setdefault(h["object"], h)
    other = [h for h in hold if h["object"] not in objs]
    direct_pv = {(h["object"], h["privilege"]) for h in hold}
    hl = {o: a.has_lacks(r, o) for o in objs}
    gaps = sorted({pv for x in hl.values() for pv in x["lacks"]})
    lack = p.get("lacks", "")
    lack = lack if lack in gaps else ""
    shown = [o for o in objs if not lack or lack in hl[o]["lacks"]]

    def cell(o, pv):
        x = hl[o]
        return ("direct" if (o, pv) in direct_pv else "inherited" if pv in x["has"] else "owner" if pv in x["implied"]
                else "lacks")

    types_ = []
    for t in sorted({objs[o]["type"] for o in shown}, key=lambda t: (type_rank(t), t)):
        cols = a.valid_privs(t)
        types_.append(dict(type=t, privs=cols, rows=[dict(object=o, name=objs[o]["name"], cells={pv: cell(o, pv) for pv in cols},
                                                          text=hl[o]["text"]) for o in shown if objs[o]["type"] == t]))
    acc = account(admin, acct)
    ro_rows = [dict(object=x["object"], privileges=x["privileges"], holder=x["holder"], inherited=x["inherited"],
                    how=x["how"], read_only=x["read_only"], objects=x["objects"]) for x in ro]
    eff = c["eff"]
    return dict(
        view=view, role=dict(id=r, name=r, kind=nk(r), owner=owner, admin=admin_role),
        filters=dict(depth=limit, users=c["only_users"], sensitive=c["only_sens"], schema=scope,
                     otype=p.get("otype", ""), cut=cut, lacks=lack, cuts=direct, gaps=gaps),
        kpis=dict(privileges=s["privileges"], future=s["future"], effective=s["effective"], above=s["above"],
                  above_direct=s["above_direct"], users=s["users"], users_direct=s["users_direct"],
                  farthest=s["farthest"], sensitive=s["sensitive"], holds_roles=s["holds_roles"]),
        scope_kpis=dict(direct=len(hold), effective=len(sc), objects=len({x["object"] for x in sc}),
                        holders=len({x["holder"] for x in sc}), sensitive=len({x["object"] for x in sc if x["object"] in S["sens"]}))
        if scope else None,
        banners=banners, findings=findings, findings_total=total, usage=role_usage(r), readonly_writes=ro_rows, account=acc, graph=graph,
        held_by=dict(rows=held_rows, revoke=revoke),
        holds=dict(types=types_, other=[dict(privilege=h["privilege"], cls=h["cls"], type=h["type"], object=h["object"],
                                             name=h["name"]) for h in other], count=len(hold), objects=len(objs)),
        tabs=tab_list(eff, [], c["held"], acc), privileges=[priv_row(x) for x in eff],
        roles=[reach_row(x) for x in c["held"]],
        can_read=[v for v in a.data_views(r, False) if not scope or v["object"] in {x["object"] for x in eff}]
        if S["view"] == "shared" else None,
        capped=sorted(a.capped))


# ---------- object ----------

def via_groups(x):
    """Classes that share their granted roles merged, then the grant holders."""
    groups = {}
    for cl, rs in x["via"].items():
        g = groups.setdefault(tuple(rs), ([], []))
        g[0].append(cl)
        g[1].extend(h for h in x["holders"][cl] if h not in rs and h not in g[1])
    return [dict(classes=cs, roles=list(rs), holders=hs) for rs, (cs, hs) in groups.items()]


def sensitivity(o):
    tg, ps = a.tags_of(o), a.policies_of(o)
    if not tg and not ps["columns"] and not ps["rows"]:
        return None
    rules = a.tag_rules()
    sp = a.split_users(a.readers(o), a.admin_users())
    cols = sorted({c for c, *_ in tg if c} | set(ps["columns"]))
    rows = []
    for c in cols:
        ct = [(t, v) for cc, t, v, _ in tg if cc == c]
        mp = ps["columns"].get(c, [])
        sens = c in a.sensitive_cols(o)
        clr = mp[0]["clear"] if mp else None
        rows.append(dict(
            column=c, tags=[dict(label=a.tag_label(t, v), sensitive=a.tag_hit(rules, t, v)) for t, v in ct
                            if not t.upper().endswith("SEMANTIC_CATEGORY")],
            semantic=", ".join(v for t, v in ct if t.upper().endswith("SEMANTIC_CATEGORY")),
            masking=[x["name"] for x in mp], clear_for=[dict(role=r, how=h) for r, h in (clr[0].items() if clr else [])],
            clear_known=bool(mp) and clr is not None, unmasked_everyone=sens and not mp))
    bodies = {x["name"]: x["body"] for ps_ in ps["columns"].values() for x in ps_} | {x["name"]: x["body"] for x in ps["rows"]}
    return dict(
        object_tags=[dict(label=a.tag_label(t, v), origin=origin, sensitive=a.tag_hit(rules, t, v))
                     for c, t, v, origin in tg if not c],
        row_policies=[dict(name=x["name"], args=x["args"] or "", text=a.policy_text(x).split(": ", 1)[-1],
                           from_text=bool(x["clear"])) for x in ps["rows"]],
        columns=rows, policy_text={k: v or "" for k, v in bodies.items()},
        readers=dict(people=len(sp["people"]), admin=len(sp["admin"]), service=len(sp["service"])))


def grantee_tab(pv, t):
    return tab_of(pv, t)


def object_page(p, view):
    types = sorted(set(a.kinds.values()))
    need(types, "No objects in this data.")
    name = p.get("name") or next((x for x in a.objects if a.kinds[x] == (p.get("type") or "TABLE")), a.objects[0])
    need(name in a.kinds, f"{name} is not in this snapshot")
    o, t = name, p.get("type") or a.kinds[name]
    if a.kinds.get(o) != t:
        t = a.kinds[o]
    pv, active, only_users = p.get("priv", ""), flag(p, "active"), flag(p, "users")
    s = a.object_stats(o, t, pv or None)
    adm = [q for x, q in a.admin_holders() if a.from_user(q)]
    m = [x for x in a.matrix(o, t, priv=pv or None) if not (active and x["status"] == "disabled")]
    real = [x for x in m if not x["admin"] or x["via"]]
    n_cls = {c: sum(c in x["via"] for x in real) for c in ("read", "write", "own")}
    data = a.is_data(t)
    scols = a.sensitive_cols(o) if data else []
    rpol = a.policies_of(o)["rows"] if data else []
    rows = []
    for x in m:
        u = x["user"]
        isreal = any(v["has"] or v["owner"] for v in x["privs"].values())
        ds = [v["depth"] for v in x["privs"].values() if v["has"]]
        n = max((v["count"] for v in x["privs"].values()), default=0)
        best = min((v["path"] for v in x["privs"].values() if v["has"]), key=len, default=None)
        aps = a.admin_paths(u, True)
        if not isreal:
            n, best = len(aps), None
        reads = isreal and any(x["privs"].get(c, {}).get("has") or x["privs"].get(c, {}).get("owner")
                               for c in a.READ_PRIVS if c in x["privs"])
        dv = a.data_view(u, o, True) if reads and (scols or rpol) else None
        col_of = {c["column"]: c for c in dv["columns"]} if dv else {}
        rows.append(dict(
            user=u, type=str((a.profile.get(u) or {}).get("TYPE") or "PERSON"), status=x["status"], admin=x["admin"],
            real=isreal, cells={c: {k: v[k] for k in ("has", "owner", "depth", "count", "title")}
                                for c, v in x["privs"].items()},
            seen={c: col_of.get(c) or dict(state="clear", reason="no masking policy") for c in scols} if dv else {},
            rows_state=dv["rows"] if dv and rpol else None, via=via_groups(x), depth=min(ds) if ds else None, paths=n,
            path=best, admin_paths=aps if x["admin"] else []))
    g = [x for x in a.grantees(o, t) if not pv or x["privilege"] == pv]
    users = sorted({x["grantee"] for x in g if x["kind"] == "user" and a.from_user(x["path"])
                    and not (active and a.is_disabled(x["grantee"]))})
    shown = [x for x in g if x["kind"] != "user" or x["grantee"] in users]
    if only_users:
        shown = [x for x in shown if x["grantee"] in users]
    og = a.object_graph(o, t, shown, users)
    graph = og and build_graph("Paths into the object", og[0], og[1], og[2])
    merged = {}
    for x in shown:
        merged.setdefault((x["grantee"], x["kind"], tuple(x["path"])), []).append(x)
    grantees = [dict(grantee=k[0], id=a.uid(k[0], k[1] == "user"), kind=norm(k[1]), kind_label=kind_label(k[0], k[1]),
                     status=a.status(k[0]) if k[1] == "user" else None,
                     privileges=[dict(privilege=y["privilege"], cls=y["cls"], tab=grantee_tab(y["privilege"], t)) for y in v],
                     tabs=sorted({grantee_tab(y["privilege"], t) for y in v}), depth=v[0]["depth"], path=list(k[2]),
                     count=max(y["count"] for y in v)) for k, v in merged.items()]
    tabs = {}
    for x in grantees:
        for k in x["tabs"]:
            tabs[k] = tabs.get(k, 0) + 1
    sees = None
    shared = view == "shared"
    ps = a.policies_of(o)
    if shared and data and (ps["rows"] or ps["columns"] or a.sensitive_cols(o)):
        rs = sorted({x for r, q_pv, _ in a.on.get(o, []) if q_pv in a.READ_PRIVS for x in a.ups(r)[0]})
        vs = [a.data_view(r, o, False) for r in rs]
        sees = dict(cols=[c["column"] for c in vs[0]["columns"]] if vs else [], row_policy=bool(ps["rows"]),
                    rows=[dict(role=v["name"], rows=v["rows"], columns=v["columns"]) for v in vs])
    db, sc, nm = a.split_name(o, t)
    return dict(
        view=view, object=dict(id=o, type=t, database=db, schema=sc, name=nm, sensitive=o in S["sens"],
                               privileges=a.valid_privs(t)),
        filters=dict(type=t, priv=pv, active=active, users=only_users),
        kpis=dict(people=len(s["people"]), disabled=len(s["disabled"]), service=len(s["service"]), admin=len(s["admin"]),
                  read=n_cls["read"], write=n_cls["write"], own=n_cls["own"], roles=s["roles"], direct=s["direct"],
                  owners=s["owners"], deployers=s["deployers"], owner_note=s["owner_note"], longest=s["longest"]),
        admin_paths=adm, sensitivity=sensitivity(o) if shared else None,
        matrix=dict(privs=list(m[0]["privs"]) if m else [], sensitive_cols=scols, row_policy=bool(rpol), rows=rows),
        graph=graph, sees=sees,
        tabs=[dict(key=k, label=lab, count=tabs[k]) for k, lab in TABS if k in tabs] + [dict(key="all", label="All", count=len(grantees))],
        grantees=grantees, capped=sorted(a.capped))


def who_page(p, view):
    """Screen 2: who has access to one object (name=), or the Admin holders preset (preset=admin): people and roles at
    their highest step, people with the same route grouped, the object's tags and policies, and who sees each sensitive
    column unmasked."""
    if p.get("preset") == "admin":
        w, o, t, cols, seen = a.admin_access(), None, None, [], {}
        head = dict(id=None, preset="admin", type="Admin roles", database=None, schema=None, name="Admin roles",
                    sensitive=False, tags=[], columns=0, masking=[], row_policies=[], owners=[], owner_note="")
    else:
        need(a.objects, "No objects in this data.")
        o = p.get("name") or next((x for x in a.objects if a.kinds[x] == "TABLE"), a.objects[0])
        need(o in a.kinds, f"{o} is not in this snapshot")
        t = a.kinds[o]
        w = a.who_has(o, t)
        data = a.is_data(t)
        cols, seen = a.column_view(o, [x["name"] for x in w["people"] if x["level"] in ("read", "change", "own", "admin")]) \
            if data else ([], {})
        ps, s = a.policies_of(o), a.object_stats(o, t)
        db, sc, nm = a.split_name(o, t)
        head = dict(id=o, preset=None, type=t, database=db, schema=sc, name=a.future_label(o, t) or nm,
                    sensitive=o in S["sens"], tags=[a.tag_label(tg, v) for c, tg, v, _ in a.tags_of(o) if not c],
                    columns=len(a.sensitive_cols(o)) if data else 0,
                    masking=sorted({x["name"] for xs in ps["columns"].values() for x in xs}),
                    row_policies=[x["name"] for x in ps["rows"]], owners=s["owners"], owner_note=s["owner_note"])
    for x in w["people"]:
        x["id"] = a.uid(x["name"], True)
        x["login"], x["mark"] = login(x["name"])
        x["columns"] = seen.get(x["name"], [])
    for x in w["roles"]:
        x["kind"] = nk(x["name"])
    levels = {lv: sum(x["level"] == lv for x in w["people"]) for lv in a.OBJ_LEVELS[::-1]}
    return dict(view=view, object=head, people=w["people"], roles=w["roles"], groups=a.same_paths(w["people"]),
                counts=dict(levels=levels, people=len(w["people"]), roles=len(w["roles"]),
                            disabled=sum(x["status"] == "disabled" for x in w["people"]),
                            dormant=sum(x["status"] in ("dormant", "never") and not a.is_service(x["name"])
                                        for x in w["people"])),
                columns=cols, default_user=(DEMO_USER if DEMO_USER in a.users else a.users[0] if a.users else None)
                if view == "shared" else (a.users[0] if a.users else None))


# ---------- can they ----------

ALL = "*"  # Can they?: every privilege on the object


def asker(p, view, key="role"):
    """Can they? / Request access subject: (name, user). A role from key= (role= on Can they?, for_role= on Request,
    where role= is the role to ask for), else a user from user= or name= (old links); a name that is no user but a
    role is that role (Home's typed question). My access: always the signed-in user."""
    mine = view == "mine"
    if not mine and p.get(key):
        need(p[key] in a.roles, f"{p[key]} is not in this snapshot")
        return p[key], False
    need(a.users, "No users in this data.")
    u = p.get("user") or p.get("name") or (a.users[0] if mine or DEMO_USER not in a.users else DEMO_USER)
    if not mine and u not in a.users and u in a.roles:
        return u, False
    need(u in a.users, f"{u} is not in this snapshot")
    return u, True


def subject_of(u, user):
    """Who the question is about: kind (user or role kind), name, id (a.uid), user, people (users holding a role),
    database (of a database role, else None)."""
    return dict(kind="user" if user else nk(u), name=u, id=a.uid(u, user), user=user,
                people=None if user else len(a.ups(u)[1]), database=None if user else a.role_db(u))


def check_page(p, view):
    need(a.objects, "No objects in this data.")
    mine = view == "mine"
    u, user = asker(p, view)
    tables = [x for x in a.objects if a.is_data(a.kinds[x])]
    mine_rows = a.grants(u, user)  # once: a big account takes a second per walk
    o = p.get("obj") or (p.get("on") if p.get("on") in a.kinds else next(
        (r["object"] for r in mine_rows if a.is_data(r["type"])), tables[0] if tables else a.objects[0]))
    need(o in a.kinds, f"{o} is not in this snapshot")
    opts = a.valid_privs(a.kinds[o])
    do = {"read": a.basic_priv(a.kinds[o]), "change": a.need_privs(a.kinds[o], "change")[0], "own": "OWNERSHIP"}
    pv = p.get("priv") if p.get("priv") in opts else do.get(p.get("do"), ALL)
    if pv == ALL:  # every privilege the user holds on o, each with its own paths
        held = list(dict.fromkeys(x["privilege"] for x in mine_rows if x["object"] == o))
        rs = {x: a.can(u, x, o, is_user=user) for x in held}
        r = (dict(next(iter(rs.values())), choke=[]) if rs else a.can(u, opts[0], o, is_user=user)) | dict(ask=[], options=[], closest=None)
        r["paths"] = [q | dict(privilege=x) for x, v in rs.items() for q in v["paths"]]
        r["owner"] = list({tuple(q): q for v in rs.values() for q in v["owner"]}.values())
        r["choke"] = [c for c in (next(iter(rs.values()))["choke"] if rs else []) if all(c in v["choke"] for v in rs.values())]
        r["shortest"] = min((q["depth"] for q in r["paths"]), default=None)
        r["count"] = sum(v["count"] for v in rs.values())
        r["owner_count"] = max((v["owner_count"] for v in rs.values()), default=0)
    else:
        held, r = [pv], a.can(u, pv, o, is_user=user)
        r["paths"] = [q | dict(privilege=pv) for q in r["paths"]]
    ps, admin = r["paths"], a.admin_paths(u, user) or ([[u]] if not user and u in a.ADMIN else [])
    what = (", ".join(held) if held else "anything") if pv == ALL else pv
    off = r["status"] == "disabled"
    sleep = user and not off and a.is_dormant(u) and not a.is_service(u)
    d = a.login_days(u) if user else None
    note = (" The user is disabled: cannot log in." if off else
            (" The user never logged in (dormant)." if d is None else f" The user has not logged in for {d} days "
                                                                       "(dormant).") if sleep else "")
    yes_text = "Yes, but the user is disabled" if off else "Yes, but the user is dormant" if sleep else ""
    tone = "warn" if (ps or r["owner"] or admin) and (off or sleep) else None
    if not ps and r["owner"]:
        ans = dict(yes=True, how="owner", title=yes_text or "Yes, via ownership",
                   text=f"{u} reaches OWNERSHIP of {o}, which implies {pv}.{note}", tone=tone,
                   stats=[["Paths", r["owner_count"]], ["Shortest depth", a.depth(r["owner"][0][:-1], user)]])
    elif not ps and admin:
        ans = dict(yes=True, how="admin", title=yes_text or f"Yes, through admin role {', '.join(dict.fromkeys(x[-1] for x in admin))}",
                   text=f"{u} can {pv} {o}: the admin role inherits every role, not through a granted role path.{note}"
                   if user or admin[0] != [u] else f"{u} is an admin role: it inherits every role, no granted path needed.",
                   tone=tone, stats=[["Paths", 0], ["Via admin", len(admin)]])
    elif not ps:
        ans = dict(yes=False, how="none", title="No, not through any role",
                   text=f"No role {'granted to' if user else 'held by'} {u}, at any depth, "
                   f"{'' if user else f'and not {u} itself, '}holds {'any privilege' if pv == ALL else pv} on {o}.{note}", tone="low",
                   stats=[["Paths", 0], ["Shortest depth", "—"]])
    else:
        ends = {x["holder"] for x in ps}
        ans = dict(yes=True, how="paths", title=yes_text or (f"Yes: {plural(len(held), 'privilege')} through {plural(r['count'], 'path')}"
                                                             if pv == ALL else f"Yes, through {plural(r['count'], 'path')}"),
                   text=(f"{u} has {what} on {o}." if pv == ALL else f"{u} can {pv} {o}.") + (f" Every path ends at {ps[0]['holder']}." if len(ends) == 1 else "")
                   + (" Also through an admin role." if admin else "") + note, tone=tone,
                   stats=([["Privileges", len(held)]] if pv == ALL else []) + [["Paths", r["count"]], ["Shortest depth", r["shortest"]]])
    read = None
    if not mine and any(x in a.READ_PRIVS for x in held) and a.is_data(a.kinds[o]) and (ps or r["owner"]):
        v = a.data_view(u, o, user)
        if v["can_read"]:
            w = a.data_view(r["use_role"], o, False) if r["use_role"] and user else None
            read = dict(summary=v["summary"], rows=v["rows"] if v["rows"]["policy"] else None, columns=v["columns"],
                        role_only=w["summary"] if w and w["summary"] != v["summary"] else None)
    g = ps and a.down_graph(u, [dict(privilege=x, type=a.kinds[o], object=o, paths=[q["path"] for q in ps if q["privilege"] == x])
                                for x in held if any(q["privilege"] == x for q in ps)], user=user)
    k = a.kinds[o]
    got = {x["privilege"] for x in mine_rows if x["object"] == o}
    has = set(opts) if admin or "OWNERSHIP" in got else got
    ls, cut = a.lanes(ps)
    cut = [x for x in cut if x in r["choke"]]  # lanes list at most MAX_PATHS paths; choke is counted over all
    ask = pv if pv != ALL else a.basic_priv(k)
    near = [] if mine or ps or r["owner"] or admin else a.nearest(u, ask, o, is_user=user)
    layers = None
    if read:  # Partly: the grant is there, but a row policy returns nothing or columns are masked
        v = a.data_view(u, o, user)
        rows, cols = v["rows"], [x for x in v["columns"] if x["state"] != "clear"]
        h = next((x for x in ps if x["privilege"] in a.READ_PRIVS), None)
        layers = [dict(step="Grant", ok=True, result="Allowed",
                       reason=f"{h['privilege']} via {h['holder']}" if h else "through ownership"),
                  dict(step="Rows", ok=rows["state"] == "all", result=ROWS_WORD[rows["state"]].capitalize(),
                       reason=rows["reason"]),
                  dict(step="Columns", ok=not cols and rows["state"] != "none",
                       result="Not reached" if rows["state"] == "none" else f"{len(cols)} masked" if cols else "All clear",
                       reason="No column shows when no rows return" if rows["state"] == "none" else
                       "; ".join(f"{x['column']}: {x['reason']}" for x in cols) or "no masking applies")]
    partly = bool(layers) and (layers[1]["result"] == "No rows" or not layers[2]["ok"])
    verdict = "partly" if ans["yes"] and partly else "yes" if ans["yes"] else "no"
    return dict(
        verdict=verdict, layers=layers, roles_count=len(set(a.best_paths(u, user)) - (set() if user else {u})), ask_priv=ask,
        held=[dict(privilege=x, held=x in has) for x in opts], lanes=ls[:20], lanes_total=len(ls), cut=cut,
        cuts=[] if mine or not ps else [dict(iac=x["iac"], sql=x["sql"], people=x["people"], lost=x["lost"],
                                             edges=[dict(grantee=e["grantee"], to=e["to"], priv=e["priv"], user=e["user"])
                                                    for e in x["edges"]]) for x in a.cut_points(u, held, o, user)],
        nearest=near, approver=a.approver(o), subject=subject_of(u, user),
        view=view, user=u, object=o, type=a.kinds[o], priv=pv, privileges=[ALL] + opts, answer=ans, status=r["status"],
        dormant_days=d if sleep else None, admin_paths=admin, paths=r["paths"], owner=r["owner"], choke=r["choke"],
        closest=r["closest"], ask=[] if mine else r["ask"],
        options=[] if mine else [dict(iac=x["iac"], sql=x["sql"], affects=x["affects"], users=x["users"], edges=len(x["edges"]))
                                 for x in r["options"]],
        use_role=r["use_role"], warehouse=r["warehouse"], read=read,
        graph=g and build_graph("Paths combined", g[0], g[1], g[2]) or None, capped=sorted(a.capped))


def request_page(p, view):
    """Screen 15, Request access: the object, read or change, the suggested roles (smallest existing one first) with
    holders and what else each brings, the approver (owner tag) and the user's level today. Text only: the page writes
    SQL / Terraform / ticket text, nothing runs."""
    need(a.objects, "No objects in this data.")
    u, user = asker(p, view, "for_role")
    tables = [x for x in a.objects if a.is_data(a.kinds[x])]
    o = p.get("obj") or (tables[0] if tables else a.objects[0])
    need(o in a.kinds, f"{o} is not in this snapshot")
    k, nd = a.kinds[o], p.get("need") if p.get("need") in ("read", "change") else "read"
    pvs = a.need_privs(k, nd)
    mine = {x["privilege"] for x in a.grants(u, user) if x["object"] == o}
    now = max((a.obj_level(x, k) for x in mine), key=a.OBJ_LEVELS.index, default=None)
    held = all(x in mine for x in pvs) or "OWNERSHIP" in mine
    r, to = p.get("role"), p.get("to") if user else u
    asked = dict(role=r, kind=nk(r), to=to if to in a.roles else None) if r in a.roles else None  # picked on Can they?
    who = subject_of(u, user)
    if asked:  # the same warnings as on Can they?: rule 1, and everyone holding the grantee role gets it too
        n = len(a.ups(asked["to"])[1] - ({u} if user else set())) if asked["to"] else 0
        asked |= dict(rule1=a.role_kind(r) == "technical" and (user and not asked["to"] or a.role_kind(asked["to"] or "") == "group"),
                      people=n, broad=bool(asked["to"]) and n >= a.BROAD + (not user))
    sug = [] if held else a.suggest(pvs, o, u, is_user=user)
    for x in sug:
        x |= dict(people=0 if user else who["people"], broad=not user and who["people"] > a.BROAD)
    return dict(view=view, user=u, subject=who, object=o, type=k, database=a.split_name(o, k)[0], need=nd,
                privileges=pvs, level=now, has=held, asked=asked, suggestions=sug, approver=a.approver(o), owners=a.object_stats(o, k)["owners"])


# ---------- access graph (screen 4) ----------

FROM = {"table": "object", "role": "role", "user": "user"}
RISK = {"admin": "leads to an admin role or an account privilege", "public": "through PUBLIC: everyone has it",
        "writes": "a read role that writes"}


def map_page(p, view):
    """Screen 4, the access graph from a table (table=), a role (role=) or a person (user=): the graph, and per box
    who comes through it, what it leads to, its step and why it is risky."""
    need(a.users or a.roles, "No users or roles in this data.")
    start, name = next(((FROM[k], p[k]) for k in FROM if p.get(k)), ("user", None))
    if start == "user" and (view == "mine" or not name):
        name = a.users[0] if view == "mine" or DEMO_USER not in a.users else DEMO_USER
    try:
        g = a.access_graph(start, name, flag(p, "same", True), flag(p, "admin", True))
    except ValueError as x:
        raise ApiError(404, "not_found", str(x))
    who = len({u for x in g["people"].values() for u in x})
    objs = len(g["lanes"][-1][1]) if g["lanes"] else 0
    mid = sum(len(ns) for _, ns in g["lanes"][1:-1])
    folk = f"{who} {'person' if who == 1 else 'people'}"
    header = {"object": f"Everyone who reaches {name}: {folk}, {plural(mid, 'role')} in between.",
              "role": f"Who holds {name} (left) and everything it opens up (right): {folk}, {plural(objs, 'object')}.",
              "user": f"Every role {name} holds, and every object those roles reach: {plural(mid, 'role')}, {plural(objs, 'object')}."}[start]
    graph = build_graph("Access graph", g["lanes"], g["edges"], kinds={k: "fold" for k, v in g["kinds"].items() if v == "fold"},
                        selected=g["start"], header=header)
    bi = a.builtin_info()
    for n in graph["nodes"]:
        k = g["kinds"].get(n["id"])
        if k == "stack":
            us = g["stacks"][n["id"]]
            n.update(kind="user", name=n["id"], label=f"{len(us)} people", marks=n["marks"] + ["stack"], action=None,
                     sub=", ".join(us[:3]) + (f" +{len(us) - 3}" if len(us) > 3 else ""),
                     tip="People with the same lines, stacked into one box")
        elif k == "every":
            n.update(kind="admin", label="Every object", sub="admin roles inherit every role", action=None, tip="No grant needed")
        elif k == "fold":
            n.update(sub=f"{bi['objects']} objects · folded" if bi else None, action=None)
        elif n["id"] == "ACCOUNT":
            n.update(kind="admin", label="Account", sub="account privileges")
    detail = {n["id"]: dict(level=g["levels"].get(n["id"]), people=g["people"].get(n["id"], [])[:30],
                            people_count=len(g["people"].get(n["id"], [])), leads=g["leads"].get(n["id"], [])[:30],
                            leads_count=len(g["leads"].get(n["id"], [])), risk=g["risky_nodes"].get(n["id"]),
                            members=g["stacks"].get(n["id"]))
              for n in graph["nodes"]}
    risky = {e["id"]: g["risky"][(e["source"], e["target"])] for e in graph["edges"] if (e["source"], e["target"]) in g["risky"]}
    return dict(view=view, start=start, name=name, id=g["start"], graph=graph, detail=detail, risky=risky,
                risky_nodes=g["risky_nodes"], why=RISK, builtin=bi)


# ---------- what they see (screen 7) ----------

def subject(p, view):
    """(name, user) from role= or user= (My access: the signed-in user); 404 when unknown."""
    if view != "mine" and p.get("role"):
        need(p["role"] in a.roles, f"{p['role']} is not in this snapshot")
        return p["role"], False
    need(a.users, "No users in this data.")
    u = a.users[0] if view == "mine" else p.get("user") or (DEMO_USER if DEMO_USER in a.users else a.users[0])
    need(u in a.users, f"{u} is not in this snapshot")
    return u, True


def see_page(p, view):
    """Screen 7, what a person or a role sees when they query: a card per protected object (rows, each column clear
    or masked and why), the old What they see / Sensitive data they can see tables, and role usage."""
    name, user = subject(p, view)
    ok = view != "mine" or bool(S["sens"])
    s = a.seen(name, user) if ok else dict(cards=[], counts=None)
    pr = (a.profile.get(name) or {}) if user else {}
    who = dict(kind="user" if user else nk(name), name=name, id=a.uid(name, user),
               type=str(pr.get("TYPE") or "PERSON") if user else KIND.get(norm(a.role_kind(name)), "Role"),
               status=a.status(name) if user else None, default_role=pr.get("DEFAULT_ROLE") or None,
               secondary_all="ALL" in str(pr.get("DEFAULT_SECONDARY_ROLES") or "").upper(),
               roles=sorted(a.roles_of.get(name, [])) if user else [])
    return dict(view=view, who=who, known=ok, cards=s["cards"], counts=s["counts"],
                can_read=a.data_views(name, user) if ok else None, sensitive=sens_reach(name) if user else None,
                usage=usage(name) if user else None, role_usage=None if user else role_usage(name))


# ---------- granted vs used (screen 13), what changed (screen 14) ----------

ENABLE_USE = ("ACCESS_HISTORY needs Enterprise edition or higher, read by the role that owns SP_ACCESS_SNAPSHOT (or, "
              "with SOURCE=direct, your role): GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE <that role>; "
              "then rebuild the snapshot.")


def usage_page(p, view):
    """Screen 13: what a person or role was granted next to what they used (ACCESS_HISTORY), days=30|90|180."""
    name, user = subject(p, view)
    days = int(p["days"]) if str(p.get("days", "")).isdigit() else 0 if p.get("days") else 90
    if days not in a.PERIODS:
        raise ApiError(400, "bad_param", "days must be 30, 90 or 180")
    ok, why = a.use_state()
    if view == "mine" and not ok:
        why = "My access reads no ACCESS_HISTORY: open Granted vs used on the shared snapshot."
    who = dict(kind="user" if user else nk(name), name=name, id=a.uid(name, user), status=a.status(name) if user else None)
    out = dict(view=view, who=who, days=days, periods=list(a.PERIODS), available=ok, reason=why, enable=ENABLE_USE,
               source=(a.run.get("SOURCES") or {}).get("object_use") or ("demo values" if MODE == "fake" else None))
    if not ok:
        return out | dict(rows=[], weeks=[], counts=None, changes=[], people=0)
    return out | a.granted_used(name, user, days)


def changes_page(p, view):
    """Screen 14: the loaded snapshot against the previous one (demo: a.fake_previous(); else the copy cache.py kept
    in .cache/ when a refresh replaced it). subject= keeps the events about one user, role or object (a node id: a.uid() for users)."""
    out = dict(view=view, subject=p.get("subject") or None, available=False, events=[], counts=None)
    if view == "mine":
        return out | dict(reason="What changed compares two shared snapshots: open it on the shared snapshot.")
    if MODE == "fake":
        prev = a.fake_previous()
    else:
        got = None if a.INSIDE else cache.prev(KEY)
        if not got:
            return out | dict(reason=(
                "Inside Snowflake the app keeps its data in memory only, so there is no earlier snapshot to compare with. "
                "Use the local version, which keeps the previous snapshot in .cache/." if a.INSIDE else
                "No earlier snapshot yet: the app keeps the previous one in .cache/ when a refresh (Read Snowflake again "
                "or Rebuild snapshot) brings a new one. Refresh after the next snapshot run, then come back."
                if cache.HOURS > 0 else "CACHE_HOURS=0 keeps nothing on disk, so there is no earlier snapshot."))
        prev = got[0]
    d = a.cached(("diff", cache.run_of(prev)), lambda: a.diff(prev))
    ev = [e for e in d["events"] if not out["subject"] or out["subject"] in e["subjects"]]
    n, before = a.event_counts(ev), d["runs"]["before"]
    sub, mine = out["subject"], out["subject"] and a.node_kind(out["subject"]) == "user"  # subject= is a node id
    gained = [u for u in d["sens_gained"]
              if not sub or (u == a.node_name(sub) if mine else any(u in e["people"] for e in ev))]
    text = (f"Since the snapshot of {before}: {plural(n['all'], 'change')}"
            + (f", {plural(d['high'], 'new high finding')}" if d["high"] and not out["subject"] else "")
            + (f", {len(gained)} {'person' if len(gained) == 1 else 'people'} gained sensitive access" if gained else "") + ".")
    ev = [e | dict(edge=e["edge"] | dict(source_kind=norm(e["edge"]["source_kind"]), target_kind=norm(e["edge"]["target_kind"])))
          if e.get("edge") else e for e in ev]
    return out | dict(available=True, events=ev, counts=n, text=text, before=before,
                      now=d["runs"]["now"], new=d["new"], fixed=d["fixed"], high=d["high"],
                      severity=None if out["subject"] else d["severity"])


# ---------- compare (screen 9) ----------

def side_of(x):
    """(name, user) of one side of Compare: a user (also "X (user)"), else a role; 404 when unknown."""
    n = a.node_name(x)
    if x.endswith(a.UTAG) or (n in a.users and x not in a.roles):
        need(n in a.users, f"{n} is not in this snapshot")
        return n, True
    need(x in a.roles or x in a.users, f"{x} is not in this snapshot")
    return x, x not in a.roles


def compare_page(p, view):
    """Screen 9, two people or roles (a=, b=) compared on sensitive data, everything or one database (scope=, db=):
    counts, rows with the differences first, the changes that make B match A or remove A's extras (text only), and
    the old Compare two roles table over the sensitive objects."""
    need(a.users or a.roles, "No users or roles in this data.")
    me = (a.users[0] if view == "mine" or DEMO_USER not in a.users else DEMO_USER) if a.users else None
    x, xu = side_of(p.get("a") or me or a.roles[0])
    if p.get("b"):
        y, yu = side_of(p["b"])
    elif xu and len(a.users) > 1:
        mine, adm = set(a.roles_of.get(x, [])), a.admin_users()  # the closest other person, not an admin
        y, yu = max((u for u in a.users if u != x), key=lambda u: (u not in adm, len(mine & set(a.roles_of.get(u, []))))), True
    else:
        y, yu = next((r for r in a.roles if r != x and a.kind_of(r) == "functional"), a.roles[0]), False
    dbs = sorted({a.split_name(o, a.kinds[o])[0] for o in a.objects} - {""})
    scope = p.get("scope") if p.get("scope") in ("sensitive", "all", "db") else "sensitive" if S["sens"] else "all"
    db = p.get("db") if p.get("db") in dbs else dbs[0] if dbs else ""
    c = a.compare(x, xu, y, yu, scope, db)
    side = lambda n, u: dict(name=n, id=a.uid(n, u), kind="user" if u else nk(n))
    old = pair_rows(x, xu, y, yu, [r["object"] for r in a.sensitive_rank()]) if S["sens"] else None
    return dict(view=view, a=side(x, xu), b=side(y, yu), scope=scope, db=db, dbs=dbs, sensitive=bool(S["sens"]), old=old, **c)


# ---------- sensitive data ----------

def sensitive_page(p, view):
    mine = view == "mine"
    gov = a.governance_kpis()["text"] if not mine else None
    empty = dict(view=view, governance=gov, filters=dict(tag="", db="", people=False, tags=[], dbs=[]),
                 kpis=dict(objects=0, columns=0, whole=0, people=0, admin=0, disabled=0, service=0, unmasked=0, stale=[]),
                 objects=[], readers=[], catalog=[], compare=dict(a="", b="", roles=[], rows=[], diff=[]))
    if not S["sens"]:
        state = ("mine" if mine else "unavailable" if a.run["SOURCES"].get("tags") == "UNAVAILABLE"
                 else "no_tags" if not a.tags else "none_sensitive")
        return empty | dict(state=state)
    rank = a.sensitive_rank()
    labels = sorted({a.tag_label(t, v) for r in rank for _, t, v, _ in r["tags"]})
    dbs = sorted({r["database"] for r in rank})
    tg, db, people = p.get("tag", ""), p.get("db", ""), flag(p, "people")
    tg, db = tg if tg in labels else "", db if db in dbs else ""
    rank = [r for r in rank if (not db or r["database"] == db) and (not tg or tg in {a.tag_label(t, v) for _, t, v, _ in r["tags"]})]
    who = {}
    for r in rank:
        for (x, pv), e in a.who_users(r["object"]).items():  # counted, not every path listed
            if pv in a.READ_PRIVS:
                w, q = who.setdefault(x, dict(objs=set(), roles=set(), path=None)), e["path"]
                w["objs"].add(r["object"])
                w["roles"] |= e["firsts"]
                if w["path"] is None or len(q) < len(w["path"]) - 1:
                    w["path"] = q + [r["object"]]
    stale = sorted(u for u in who if not a.is_service(u) and a.status(u) != "active")
    if people:
        who = {u: w for u, w in who.items() if not a.is_disabled(u) and not a.is_service(u)}

    def every(k):
        return set().union(*(r[k] for r in rank))

    ppl, adm = every("people"), every("admin") - set(who)
    admins = a.admin_users()
    ad = sorted(u for u in admins if u not in who and not (people and (a.is_disabled(u) or a.is_service(u))))
    us = sorted(who, key=lambda u: (-len(who[u]["objs"]), u))

    def reader(u, w, via_admin):
        pr = a.profile.get(u) or {}
        return dict(user=u, type=str(pr.get("TYPE") or "PERSON"), status=a.status(u), last_login_text=login(u)[0],
                    objects=sorted(w["objs"]) if w else [r["object"] for r in rank],
                    roles=sorted(w["roles"]) if w else admins[u], path=w["path"] if w else None, via_admin=via_admin,
                    admin_paths=a.admin_paths(u, True) if via_admin else [])

    funcs = [r for r in a.roles if a.kind_of(r) == "functional"] or a.roles
    top = sorted(funcs, key=lambda r: (-sum(o in S["sens"] for o in a.reads([r])), r))
    x = p.get("a") if p.get("a") in a.roles else top[0]
    y = p.get("b") if p.get("b") in a.roles else top[1] if len(top) > 1 else top[0]
    cols = sum(len(r["cols"]) for r in rank)
    return dict(
        view=view, state="ok", governance=gov, filters=dict(tag=tg, db=db, people=people, tags=labels, dbs=dbs),
        kpis=dict(objects=len(rank), columns=cols, whole=sum(not r["cols"] for r in rank), people=len(ppl), admin=len(adm),
                  disabled=len(every("disabled")), service=len(every("service")),
                  unmasked=sum(n - k for k, n in (r["masked"] for r in rank)), stale=stale),
        objects=[dict(object=r["object"], database=r["database"], schema=r["schema"], name=r["name"], type=r["kind"],
                      tags=[dict(label=k, origins=list(dict.fromkeys(v))) for k, v in
                            {lab: [o + (f" {c}" if c else "") for c2, t2, v2, o in r["tags"] if a.tag_label(t2, v2) == lab
                                    for c in [c2]] for lab in dict.fromkeys(a.tag_label(t, v) for _, t, v, _ in r["tags"])}.items()],
                      cols=r["cols"], masked=list(r["masked"]), row_policies=r["row_policies"], people=r["people"],
                      disabled=r["disabled"], service=r["service"], admin=r["admin"], roles=r["roles"]) for r in rank],
        readers=[reader(u, who[u], False) for u in us] + [reader(u, None, True) for u in ad],
        catalog=[dict(object=r["object"], name=r["name"], ns=f'{r["database"]}.{r["schema"]}', type=r["kind"],
                      labels=r["labels"], groups=r["groups"], status=r["status"], masked=list(r["masked"]),
                      columns=r["columns"], unmasked=r["unmasked"], row_policies=r["row_policies"], readers=r["readers"],
                      admin=len(r["admin"]))
                 for r in a.catalog() if (not db or r["database"] == db)
                 and (not tg or tg in r["labels"])],
        compare=dict(a=x, b=y, roles=a.roles, **pair_rows(x, False, y, False, [r["object"] for r in rank])))


def reads_of(n, user):
    """Objects a role (or a user, through any role they hold) reads: {object: path}."""
    return {o: q for s in (a.starts(n, True) if user else [[n]]) for o, q in a.reads(s).items()}


def pair_rows(x, xu, y, yu, objs):
    """Compare two roles (Sensitive data, and the first tab of Compare): what each sees of every object in objs (None:
    cannot read it), and the differences in words."""
    got, txt = {x: reads_of(x, xu), y: reads_of(y, yu)}, {}
    for n, u in ((x, xu), (y, yu)):
        for o in objs:
            if o in got[n]:
                txt[(n, o)] = mask_text(n, o, u)
    diff = [f"{o}: through {n} yes; through {m} no" for o in objs for n, m in ((x, y), (y, x))
            if o in got[n] and o not in got[m]]
    diff += [f"{o}: {x} sees {txt[(x, o)]}; {y} sees {txt[(y, o)]}" for o in objs
             if (x, o) in txt and (y, o) in txt and txt[(x, o)] != txt[(y, o)]]
    return dict(diff=diff[:10] if x != y else [], rows=[dict(object=o, a=txt.get((x, o)), b=txt.get((y, o))) for o in objs])


# ---------- rules ----------

def rules_page(p, view):
    rows = S["rows"]
    gs = {x["grantee"] for x in rows}
    who = p.get("grantee", "") if p.get("grantee", "") in gs else ""
    mine = [x for x in rows if not who or x["grantee"] == who]
    count = {n: sum(x["num"] == n for x in mine) for n in a.RULES}
    sev = p.get("sev", "") if p.get("sev", "") in SEVS + ["Passing"] else ""
    sel = p.get("rule", "") if p.get("rule", "") in a.RULES else ""
    lvl = lambda n: a.SEVERITY.get(n, "Low")
    shown = [x for x in mine if not sel or x["num"] == sel]

    unknown = sorted(o for o in S["sens"] if any(a.row_terms(q) is None for q in a.policies_of(o)["rows"]))
    return dict(
        view=view, scope="mine" if view == "mine" else "account", filters=dict(grantee=who, sev=sev, rule=sel),
        counts={**{s: sum(count[n] for n in a.RULES if lvl(n) == s) for s in SEVS},
                "Passing": sum(not count[n] for n in a.RULES)},
        per_rule=count,
        findings=[finding(x) for x in shown],
        total=len(shown), rows_unknown=[] if who else unknown,
        admins=[dict(user=x["user"], service=x["service"], roles=x["roles"], account=list(dict.fromkeys(pv for pv, _ in x["account"])),
                     paths=x["paths"] + [q for _, q in x["account"]], status=x["status"],
                     last_login=str(x["last_login"])[:16] if x["last_login"] else None) for x in a.admin_people()])


def rules_csv(p, view):
    now, who = datetime.now(), p.get("grantee", "")
    sev = p.get("sev", "") if p.get("sev", "") in SEVS + ["Passing"] else ""
    sel = p.get("rule", "") if p.get("rule", "") in a.RULES else ""
    shown = [x for x in S["rows"] if (not who or x["grantee"] == who) and (not sev or x["severity"] == sev)
             and (not sel or x["num"] == sel)]
    what = [f"rule {sel}"] * bool(sel) + [sev] * bool(sev) + [who] * bool(who)
    text = csv_text(["Rule", "Title", "Severity", "Grantee", "Detail", "Fix", "SQL", "Affects users", "Same fix", "Paths"],
                    [[x["num"], x["title"], x["severity"], x["grantee"], x["detail"], x["iac"], x["sql"],
                      "" if x["affects"] is None else x["affects"], x["same_fix"], " | ".join(arrow(q) for q in x["paths"])]
                     for x in shown],
                    [["Rule checks", ", ".join(what) or "all"], ["Run", a.run.get("RUN_ID"), str(a.run.get("FINISHED_AT"))[:16]],
                     ["Generated", f"{now:%Y-%m-%d %H:%M}"]])
    return f"findings_{sev or 'all'}_{now:%Y-%m-%d}.csv", text


# ---------- what if ----------

WHATIF_KEYS = ["section", "name", "privilege", "type", "object", "cls", "status", "path", "detail"]


def what_if(p, cap):
    """a.what_if() of the changes param (a JSON list of {op, ...}); 400 on a malformed or unknown change."""
    try:
        changes = json.loads(p.get("changes") or "")
    except ValueError:
        changes = None
    if not (isinstance(changes, list) and changes and all(isinstance(c, dict) for c in changes)):
        raise ApiError(400, "bad_param", 'changes must be a JSON list of changes, e.g. [{"op": "empty_public"}]')
    try:
        return a.what_if(changes, cap)
    except ValueError as x:
        raise ApiError(400, "bad_change", str(x))


def whatif_page(p, view):
    out = what_if(p, a.MAX_PATHS)
    out.pop("csv")
    return out


def whatif_csv(p, view):
    now, out = datetime.now(), what_if(p, None)
    text = csv_text([k.capitalize() for k in WHATIF_KEYS], [[x[k] for k in WHATIF_KEYS] for x in out["csv"]],
                    [["What if", out["summary"]], ["Run", a.run.get("RUN_ID"), str(a.run.get("FINISHED_AT"))[:16]],
                     ["Generated", f"{now:%Y-%m-%d %H:%M}"], ["Infrastructure as code", out["iac"]],
                     ["SQL (never run by this app)", out["sql"]]])
    return f"what_if_{now:%Y-%m-%d}.csv", text


# ---------- access review ----------

REVIEW_KEYS = ["database", "schema", "object", "type", "user", "user_type", "status", "last_login", "privileges", "classes",
               "sensitive", "granted", "path", "reviewer", "decision"]
REVIEW_COLS = ["Database", "Schema", "Object", "Type", "User", "User type", "Status", "Last login", "Privileges", "Classes",
               "Sensitive", "Granted roles", "Path", "Reviewer", "Keep/Revoke"]


def review_ctx(p):
    dbs = sorted({a.split_name(o)[0] for o in a.objects} - {""})
    need(dbs, "No databases in this data.")
    db = p.get("db") or dbs[0]
    need(db == "*" or db in dbs, f"{db} is not in this snapshot")
    every = a.review(None if db == "*" else db)
    sc = p.get("schema", "")
    sc = sc if sc in {x["schema"] for x in every} else ""
    ob = p.get("object", "")
    active = flag(p, "active")
    rs = [x for x in every if not (active and x["status"] == "disabled") and (not sc or x["schema"] == sc or not x["type"])
          and (not ob or x["object"] == ob or not x["type"])]
    rs.sort(key=lambda x: (not x["type"], type_rank(x["type"] or ""), x["database"], x["schema"], x["object"], x["user"]))
    return dict(dbs=dbs, db=db, every=every, sc=sc, ob=ob, active=active, rs=rs)


def review_page(p, view):
    if view == "mine":
        raise ApiError(400, "shared_only", "The access review is about everyone: use the shared snapshot.")
    c = review_ctx(p)
    rs, db = c["rs"], c["db"]
    noise = flag(p, "hideusage", True)
    real = [x for x in rs if x["type"]]
    hide = lambda x: noise and x["type"] in ("DATABASE", "SCHEMA")
    label = {}  # per object, not per row
    fl = lambda x: label.setdefault((x["database"], x["schema"], x["object"], x["type"]), a.future_label(
        f'{x["database"]}.{x["schema"]}.{x["object"]}', x["type"] or ""))
    return dict(
        view="shared",
        filters=dict(db=db, dbs=c["dbs"], schema=c["sc"], schemas=sorted({x["schema"] for x in c["every"]} - {""}),
                     object=c["ob"], objects=sorted({x["object"] for x in c["every"] if x["type"] and (not c["sc"] or x["schema"] == c["sc"])}),
                     active=c["active"], hideusage=noise),
        kpis=dict(objects=len({(x["database"], x["schema"], x["object"]) for x in real}), users=len({x["user"] for x in real}),
                  not_active=len({x["user"] for x in real if x["status"] != "active"}), rows=len(rs),
                  admin_rows=len(rs) - len(real), hidden_usage=sum(map(hide, rs)),
                  sensitive=len({x["object"] for x in real if x["sensitive"]})),
        rows=[dict(database=x["database"], schema=x["schema"], object=x["object"], type=x["type"] or "",
                   future_label=fl(x),
                   user=x["user"], user_type=str(x["user_type"]), status=x["status"],
                   last_login=str(x["last_login"])[:16] if x["last_login"] else None,
                   privileges=[s for s in x["privileges"].split(", ") if s], classes=[s for s in x["classes"].split(", ") if s],
                   sensitive=[s for s in x["sensitive"].split(", ") if s], granted=[s for s in x["granted"].split(", ") if s],
                   path=x["path"].split(" > ") if x["path"] else [], admin=not x["type"], hidden=hide(x)) for x in rs])


def grid_page(p, view):
    """Screen 6 grid: people x objects (scope sensitive | db | all), or people x privileges of one object
    (object=&columns=privileges). Rows carry suggest (dormant / disabled / never logged in: suggested revoke)."""
    if view == "mine":
        raise ApiError(400, "shared_only", "The access review is about everyone: use the shared snapshot.")
    dbs = sorted({a.split_name(o)[0] for o in a.objects} - {""})
    obj = p.get("object", "") if p.get("columns") == "privileges" else ""
    need(not obj or obj in a.kinds, f"{obj} is not in this snapshot")
    scope = p.get("scope") if p.get("scope") in ("sensitive", "db", "all") else "sensitive" if S["sens"] else "all"
    db = p.get("db") or (dbs[0] if dbs else "")
    need(scope != "db" or db in dbs, f"{db} is not in this snapshot")
    g = a.review_grid(scope, db, obj or None, flag(p, "hideusage", True))
    rows = [r | dict(last_login=login(r["user"])[0], suggest=r["status"] if a.stale(r["user"]) else None)
            for r in g["rows"]]
    people = [r for r in rows if r["type"] not in ("SERVICE", "LEGACY_SERVICE")]
    return dict(view="shared", scope="object" if obj else scope, db=db, dbs=dbs, object=obj, columns=g["columns"],
                rows=rows, total=g["total"], cap=a.GRID_MAX, sensitive=len(S["sens"]),
                counts=dict(people=len(people), admin=sum(bool(r["admin"]) for r in people),
                            stale=sum(bool(r["suggest"]) for r in people), service=len(rows) - len(people)))


def flow_page(p, view):
    """Screen 16: where sensitive data flows (access.sens_flow), with the default selection: the dormant or disabled."""
    if view == "mine" or not S["sens"]:
        return dict(view=view, state="mine" if view == "mine" else "none", groups=[], roles=[], objects=[], links=[],
                    select=None)
    f = a.sens_flow()
    return dict(view=view, state="ok", **f,
                select="risky" if any(g["id"] == "risky" for g in f["groups"]) else None)


def review_csv(p, view):
    if view == "mine":
        raise ApiError(400, "shared_only", "The access review is about everyone: use the shared snapshot.")
    c = review_ctx(p)
    now, where = datetime.now(), "every database" if c["db"] == "*" else c["db"]
    filt = [f"schema {c['sc']}"] * bool(c["sc"]) + [f"object {c['ob']}"] * bool(c["ob"]) + ["disabled excluded"] * c["active"]
    text = csv_text(REVIEW_COLS, [[x[k] if x[k] is not None else "" for k in REVIEW_KEYS] for x in c["rs"]],
                    [["Access review", where], ["Run", a.run.get("RUN_ID"), str(a.run.get("FINISHED_AT"))[:16]],
                     ["Filter", ", ".join(filt) or "all users"], ["Generated", f"{now:%Y-%m-%d %H:%M}"]])
    return f"access_review_{'ALL' if c['db'] == '*' else c['db']}_{now:%Y-%m-%d}.csv", text


# ---------- find, list, graph, meta ----------

def find_page(p, view):
    names = [a.uid(u, True) for u in a.users] + a.roles + a.objects
    hits_ = a.search(p.get("q", ""), names)
    lim = int(p.get("limit", "20")) if p.get("limit", "20").isdigit() else 20
    out = []
    for n in hits_[:lim]:
        k = nk(n)
        name = a.node_name(n)
        out.append(dict(id=n, name=name, kind=k, kind_label=kind_label(name, a.node_kind(n)) if k != "object"
                        else (a.kinds.get(n) or "Object").capitalize(), type=a.kinds.get(n) if k == "object" else None,
                        sensitive=n in S["sens"], page=page_of(k), answer=answer(n, k, name)))
    return dict(items=out, total=len(hits_))


def answer(n, k, name):
    """One-line answer of a search hit: "reads 6 · changes 5 · owns 2" for a person or role (reach only, fast), the
    people with access for an object."""
    if k == "object":
        us = set().union(*(a.ups(r)[1] for r, _, _ in a.on.get(n, [])))
        return f"{len(us)} {'person has' if len(us) == 1 else 'people have'} access"
    c = a.reach_counts(name, k == "user")
    return f"reads {c['read']} · changes {c['change']} · owns {c['own']}"


def list_page(p, view):
    """Users, roles, objects (type=), types, databases or the holders of role= (What if). q= keeps the matches in search
    order and limit= the first ones (a picker asks for 50 per keystroke instead of the whole account); what= takes a
    comma list ("users,roles": one picker for a person or role). total: the matches before the limit."""
    whats = p.get("what", "users").split(",")
    if len(whats) > 1:
        items = [i for w in whats for i in list_page(dict(p, what=w, q="", limit=""), view)["items"]]
    else:
        items = list_items(p, whats[0])
    q = p.get("q", "").strip()
    if q:
        by = {i["id"]: i for i in items}
        items = [by[n] for n in a.search(q, list(by))]
    total = len(items)
    lim = p.get("limit", "")
    return dict(items=items[:int(lim)] if lim.isdigit() else items, total=total)


def list_items(p, what):
    if what == "users":
        items = [dict(id=u, name=u, kind="user", type=str((a.profile.get(u) or {}).get("TYPE") or "PERSON"), status=a.status(u))
                 for u in a.users]
    elif what == "roles":
        items = [dict(id=r, name=r, kind=nk(r), type=None, status=None) for r in a.roles]
    elif what == "objects":
        t = p.get("type", "")
        items = [dict(id=o, name=o, kind="object", type=a.kinds[o], status=None) for o in a.objects if not t or a.kinds[o] == t]
    elif what in ("role_holders", "user_holders"):  # who reaches role=X, directly or further down (What if)
        r = p.get("role", "")
        rs, us = a.ups(r) if r in a.roles else (set(), set())
        if what == "role_holders":
            items = [dict(id=x, name=x, kind=nk(x), type="direct" if r in a.holds.get(x, []) else "inherited", status=None)
                     for x in sorted(rs - {r})]
        else:
            items = [dict(id=u, name=u, kind="user", type="direct" if r in a.roles_of.get(u, []) else "inherited",
                          status=a.status(u)) for u in sorted(us)]
        items.sort(key=lambda i: i["type"] != "direct")
    elif what == "types":
        items = [dict(id=t, name=t, kind=None, type=t, status=None) for t in sorted(set(a.kinds.values()))]
    elif what == "databases":
        items = [dict(id=d, name=d, kind=None, type="DATABASE", status=None) for d in sorted({a.split_name(o)[0] for o in a.objects} - {""})]
    else:
        raise ApiError(400, "bad_param", "what must be users, roles, objects, types, databases, role_holders or user_holders")
    return items


def graph_page(p, view):
    of = p.get("of", "")
    if of in ("user", "role", "object", "check"):
        pg = ROUTES[of](p, view)
        return pg["graph"]
    if of == "user-tab":
        c = user_ctx(p, view)
        rows, walked = tab_rows(c["rows"], c["hidden"], c["reach"], p.get("tab", "all"))
        return tab_graph(c["u"], True, rows, walked, "roles held" if walked else "privileges")
    if of == "role-tab":
        c = role_ctx(p, view)
        rows, walked = tab_rows(c["eff"], [], c["held"], p.get("tab", "all"))
        return tab_graph(c["r"], False, rows, walked, "roles held" if walked else "privileges")
    raise ApiError(400, "bad_param", "of must be user, role, object, check, user-tab or role-tab")


def theme_tokens():
    out = {}
    for th, t in ui.TOKENS.items():
        k = dict(t["kind"])
        k["database_role"] = k["database"]
        for g in ("schema_group", "database_group", "type_group", "fold", "lane_group"):
            k[g] = k["object"]
        out[th] = dict(t) | dict(kind=k)
    return out


def meta(p, sid):
    view = p.get("view", "shared")
    base = dict(mode=MODE, source=SOURCE, where=WHERE, fetched_at=fetched(), view=view, loaded=False, run=None, sources={}, notes=[],
                mine=mine_state(sid), mine_available=mine_off() is None, cache_hours=cache.HOURS if cache.local() else 0,
                sql_copy=sql_copy(view, sid), inside=a.INSIDE, pages=[dict(key=k, label=lab, badge=None, group=GROUP[k]) for k, lab in PAGES.items()
                                              if not (view == "mine" and k in SHARED_ONLY)],
                default_user=DEMO_USER, prefixes=dict(func=a.FUNC, tech=a.TECH), admin_roles=sorted(a.ADMIN),
                build_roles=list(a.BUILD),
                limits=dict(max_paths=a.MAX_PATHS, max_objects=a.MAX_OBJECTS, max_hops=a.MAX_HOPS,
                            dormant_days=a.DORMANT_DAYS, max_depth_rule=a.MAX_DEPTH_RULE),
                read_privs=sorted(a.READ_PRIVS), sensitive_tags=a.SENSITIVE_TAGS,
                rules=[dict(num=n, title=a.RULES[n][0], why=a.RULES[n][1], severity=a.SEVERITY.get(n, "Low"),
                            area=RULE_INFO.get(n, ("", "Other", "", ""))[1], spot=RULE_INFO.get(n, ("", "", "", ""))[0],
                            meaning=RULE_INFO.get(n, ("", "", "", ""))[2], fix=RULE_INFO.get(n, ("", "", "", ""))[3])
                       for n in sorted(a.RULES, key=int)],
                governance=None, tokens=theme_tokens(), help=ui.HELP,
                type_icon={k: list(v) for k, v in ui.TYPE_ICON.items()}, pclass=ui.PCLASS)
    try:
        with session(view, sid, p.get("builtin") == "1") as d:
            run = a.run
            when, old = snap_time(run) if view == "shared" else ("live", False)
            worst = next((v for v in ("Critical", "High", "Medium", "Low") if any(x["severity"] == v for x in S["rows"])), None)
            badge = {"rules": sum(x["severity"] == worst for x in S["rows"]), "sensitive": len(S["sens"])}
            base.update(loaded=True, run=dict(run_id=str(run.get("RUN_ID")), finished_at=str(run.get("FINISHED_AT"))[:16],
                                              when=when, old=old),
                        sources=run.get("SOURCES") or {"all": "fake data"}, notes=notes_of(run, view) + loop_notes(),
                        pages=[dict(key=k, label=lab, badge=badge.get(k) or None, severity=worst if k == "rules" else None, group=GROUP[k])
                               for k, lab in PAGES.items() if not (view == "mine" and k in SHARED_ONLY)],
                        governance=a.governance_kpis()["text"] if view == "shared" else None,
                        protection=protection() if view == "shared" else None,
                        builtin=a.builtin_info(), what_if_ops=list(a.WHAT_IF_OPS),
                        default_user=DEMO_USER if DEMO_USER in a.users else (a.users[0] if a.users else DEMO_USER))
    except ApiError as x:
        base["error"] = dict(detail=x.detail, message=x.message)
    return clean(base)


def sql_copy(view, sid):
    """Where the DuckDB copy of what this view shows is (cache.sql_info): file, schema, or why there is none."""
    if view == "mine":
        m = mine_entry(sid)
        if m and m.get("cache_key"):
            return cache.sql_info(m["cache_key"])
        return cache.sql_info("", disk=False) | dict(on=False, schema=None, note=None if not m else
                                                     "Demo data: My access gets no SQL copy.")
    return cache.sql_info(KEY, disk=MODE == "snowflake")


def protection():
    """Sidebar "Protection": counts that link to where they are explained; unmasked sensitive columns are rule 6."""
    g = a.governance_kpis()
    return dict(row_tables=g["row_tables"], masked_columns=g["masked_columns"], tagged_objects=g["tagged_objects"],
                unmasked=sum(x["num"] == "6" for x in S["rows"]))


def reload(body):
    what = (body or {}).get("what", "page")
    if what == "rebuild":
        if MODE != "snowflake":
            return dict(ok=False, result=None, message="Demo: the CALL runs only on Snowflake (not FAKE=1).")
        res = None
        if not DIRECT:
            try:
                r = with_query(lambda q: q(f"CALL {WHERE}.SP_ACCESS_SNAPSHOT('AUTO')"))
            except Exception as x:
                raise ApiError(503, "rebuild_failed", a.line(x))
            res = json.loads(list(r[0].values())[0])
            st = (res or {}).get("status")
            if st != "OK":  # SKIPPED (another run still going) or FAILED: say so, and keep the copy we have
                err = ((res or {}).get("notes") or {}).get("error") or "no reason given"
                return dict(ok=False, result=res, message=f"Snapshot {str(st or 'not rebuilt').lower()}: {err}")
        cache.drop(KEY)
        if DIRECT:  # a click: read now, not at the next page
            load_shared()
        return dict(ok=True, result=res, message="Snapshot rebuilt." if not DIRECT else "Read Snowflake again.")
    if what == "load":  # the click that reads the shared data (SOURCE=direct)
        load_shared()
        return dict(ok=True, result=None, message="Loaded.")
    cache.drop(KEY)  # read the source again (Snowflake), not the local copy
    if MODE == "snowflake" and DIRECT:  # a click: read now, not at the next page
        load_shared()
    return dict(ok=True, result=None, message="Reloaded.")


# ---------- refs ----------

def mkrefs(out):
    """Kind of every id the answer mentions, which objects are sensitive and which users are disabled."""
    if S["known"] is None:
        S["known"] = a.cached("known", lambda: set(a.roles) | set(a.objects) | set(a.users) | {a.uid(u, True) for u in a.users})
    seen, todo = set(), [out]
    while todo:  # a loop, not recursion: a review answer has a million values
        x = todo.pop()
        t = type(x)
        if t is str:
            seen.add(x)
        elif t is dict:
            todo.extend(x.values())
        elif t in (list, tuple, set, frozenset):
            todo.extend(x)
        elif isinstance(x, str):
            seen.add(x)
        elif isinstance(x, dict):
            todo.extend(x.values())
    kinds, types, labels = {}, {}, {}
    for n in seen & S["known"]:
        kinds[n] = nk(n)
        if kinds[n] == "object":
            types[n] = a.kinds.get(n, "")
            lab = a.future_label(n, a.kinds.get(n, ""))
            if lab:
                labels[n] = lab
    return dict(kinds=kinds, types=types, labels=labels, sensitive=sorted(n for n in seen if n in S["sens"]),
                disabled=sorted(n for n, k in kinds.items() if k == "user" and a.is_disabled(a.node_name(n))))


ROUTES = {"home": home_page, "access": access_page, "user": user_page, "role": role_page, "object": object_page, "check": check_page, "sensitive": sensitive_page,
          "rules": rules_page, "review": review_page, "find": find_page, "list": list_page, "graph": graph_page,
          "whatif": whatif_page, "who": who_page, "request": request_page, "map": map_page, "see": see_page,
          "compare": compare_page, "grid": grid_page, "flow": flow_page, "usage": usage_page, "changes": changes_page}
WITH_REFS = {"request", "who", "access", "user", "role", "object", "check", "sensitive", "rules", "review",
             "whatif", "map", "see", "compare", "grid", "flow", "usage", "changes"}
CSV = {"rules": rules_csv, "review": review_csv, "whatif": whatif_csv}


def serve(name, params=None, sid=None):
    """The JSON answer of one endpoint (a dict), as the local server and the Streamlit components get it."""
    p = {k: str(v) for k, v in (params or {}).items()}
    with session(p.get("view", "shared"), sid, p.get("builtin") == "1"):
        out = ROUTES[name](p, p.get("view", "shared"))
        if name in WITH_REFS:
            out["refs"] = mkrefs(out)
        return clean(out)


def serve_csv(name, params=None, sid=None):
    p = {k: str(v) for k, v in (params or {}).items()}
    with session(p.get("view", "shared"), sid, p.get("builtin") == "1"):
        return CSV[name](p, p.get("view", "shared"))


# ---------- the web app ----------

def allowed_hosts():
    """Host names the local server answers: loopback, HOST when it names one, this machine's names when it listens on
    every address (HOST=0.0.0.0), plus ALLOWED_HOSTS (comma-separated; * = any)."""
    import socket
    host = os.environ.get("HOST", "127.0.0.1")
    out = set(LOOPBACK) | {h.strip().lower() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()}
    if host in ("0.0.0.0", "::"):
        out |= {socket.gethostname().lower(), socket.getfqdn().lower()}
        try:  # opened by IP address too
            out |= set(socket.gethostbyname_ex(socket.gethostname())[2])
        except OSError:
            pass
    elif host:
        out.add(host.lower())
    return out


def make_app():
    from fastapi import FastAPI, Request
    from fastapi.responses import FileResponse, JSONResponse, Response

    from starlette.middleware.gzip import GZipMiddleware

    app = FastAPI(title="Snowflake access explorer API")
    app.add_middleware(GZipMiddleware, minimum_size=2000)  # the bundle and big answers (review, objects) shrink ~5x
    hosts = allowed_hosts()

    def served(host):  # "name", "name:port", "[::1]:port"
        host = host.lower()
        name = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        return "*" in hosts or name.strip("[]") in hosts

    @app.middleware("http")
    async def same_site(request: Request, call_next):
        """Only this server's own pages: a Host it serves (no DNS rebinding), no POST from another site's page (a form
        or no-cors fetch could start a rebuild or a login) and no API call another page starts (an <img> on /api/home
        would start a Snowflake read and the SSO login)."""
        host = (request.headers.get("host") or "").lower()
        if not served(host):
            return JSONResponse(dict(detail="bad_host", message=f"Host {host} is not served here: add it to "
                                     "ALLOWED_HOSTS (comma-separated)."), status_code=400)
        origin = request.headers.get("origin")
        # Origin's host name, not the Host header: a proxy may rewrite Host
        cross = (request.method not in ("GET", "HEAD") and origin and not served(origin.split("://", 1)[-1])) or             (request.url.path.startswith("/api/") and request.headers.get("sec-fetch-site", "same-origin")
             not in ("same-origin", "none"))
        if cross:
            return JSONResponse(dict(detail="cross_site", message="Requests from another site are refused."),
                                status_code=403)
        return await call_next(request)

    @app.exception_handler(ApiError)
    def api_error(request, x):
        return JSONResponse(dict(detail=x.detail, message=x.message), status_code=x.status)

    @app.exception_handler(Exception)
    def any_error(request, x):  # the message in the page, as the Streamlit version shows it (st_react.answer)
        return JSONResponse(dict(detail="error", message=f"{type(x).__name__}: {x}"), status_code=500)

    def sid_of(request):
        return request.cookies.get("ae_sid")

    @app.get("/api/meta")
    def meta_(request: Request):
        return meta(dict(request.query_params), sid_of(request))

    @app.post("/api/reload")
    async def reload_(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        return reload(body)

    @app.post("/api/mine/load")
    def mine_load(request: Request):
        old = sid_of(request)
        sid = os.urandom(16).hex()
        out = load_mine(sid, request.query_params.get("fresh") == "1")
        MINE.pop(old, None)
        r = JSONResponse(clean(out))
        r.set_cookie("ae_sid", sid, max_age=TTL, httponly=True, samesite="strict", path="/api")
        return r

    @app.get("/api/mine")
    def mine_(request: Request):
        return mine_state(sid_of(request))

    def route(name):
        def h(request: Request):  # already plain JSON: FastAPI's own encoder takes a minute on a 100k row answer
            return JSONResponse(serve(name, dict(request.query_params), sid_of(request)))
        return h

    for n in ("home", "access", "user", "role", "object", "check", "sensitive", "rules", "review", "find", "list", "graph",
              "whatif", "who", "request", "map", "see", "compare", "grid", "flow", "usage", "changes"):
        app.get(f"/api/{n}")(route(n))

    def csv_route(name):
        def h(request: Request):
            fname, text = serve_csv(name, dict(request.query_params), sid_of(request))
            return Response(text, media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={fname}"})
        return h

    for n in CSV:
        app.get(f"/api/{n}.csv")(csv_route(n))

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse(dict(detail="not_found", message="No such endpoint."), status_code=404)
        f = (DIST / path).resolve()
        if path and f.is_file() and DIST.resolve() in f.parents:
            return FileResponse(f)
        if (DIST / "index.html").is_file():
            return FileResponse(DIST / "index.html")
        return JSONResponse(dict(detail="not_built", message="The web app is not built: run npm run build in web/."),
                            status_code=404)

    return app


def __getattr__(name):  # `uvicorn server:app` builds the app on first use
    if name == "app":
        g = globals()
        g["app"] = make_app()
        return g["app"]
    raise AttributeError(name)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(make_app(), host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("WEB_PORT", "8000")))
