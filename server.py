"""JSON API of the access explorer (contract: web/API.md). Run: python server.py -> http://localhost:8000
Data: Snowflake via sf.py (SOURCE=direct, or objects = the TBL_ACCESS_ tables), FAKE=1 fake data. Kept once a day (cache.py).
No logic of its own: every number, path and rule comes from access.py; this file picks, filters, renames to JSON.
FastAPI is imported only in make_app(), so st_react.py can `import server` and call serve() for the same JSON."""
import csv
import hashlib
import heapq
import io
import itertools
import json
import os
import pickle
import pathlib
import re
import threading
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal

import access as a
import cache
import twin
import ui

MODE, SOURCE, WHERE = cache.config()  # FAKE=1 fake data; else SOURCE=direct|objects (README > Settings)
DIRECT = SOURCE == "direct"  # no tables: read the grants straight from Snowflake (a.live)
# one shared copy and one My access copy per CACHE_DIR: another account or role gets its own CACHE_DIR
KEY = "shared_data" if MODE == "snowflake" else cache.name(SOURCE, where=WHERE)
OFFLINE = os.environ.get("BUILD_ONLY") == "1"  # run.py --build: built from the parts kept, never a Snowflake read
DEMO_USER = os.environ.get("DEMO_USER", "ENGINEER_01")
TTL = cache.TTL  # the My access session cookie (seconds); the data itself stays until read again
DIST = pathlib.Path(__file__).with_name("web") / "dist"

PAGES = {"home": "Home", "access": "A person or role", "object": "An object", "check": "Can they?",
         "graph": "Access graph", "see": "What they see", "compare": "Compare", "request": "Request access",
         "rules": "Risks", "whatif": "Change plan", "review": "Review & sign-off", "sensitive": "Sensitive data",
         "flow": "Sensitive data flow", "usage": "Grants to trim", "objuse": "Used or not", "activity": "Activity", "changes": "What changed",
         "user": "User paths", "role": "Role paths"}
GROUP = {"home": "home", "access": "access", "object": "access", "see": "access", "user": "access", "role": "access",
         "check": "ask", "compare": "ask", "request": "ask", "graph": "ask", "whatif": "ask",
         "rules": "risk", "sensitive": "risk", "flow": "risk", "usage": "risk", "objuse": "risk", "activity": "risk",
         "review": "govern", "changes": "govern"}  # side nav groups
SHARED_ONLY = {"review", "flow", "changes", "objuse", "activity"}
KIND = {"functional": "Functional role", "technical": "Technical role", "group": "Group role",
        "database": "Database role", "admin": "Admin role", "object": "Object"}
KNOWN = {"user", "functional", "technical", "group", "admin", "object"}
SEVS = ["Critical", "High", "Medium", "Low"]
TABS = [("account", "Account"), ("granted", "Granted roles"), ("database_roles", "Database roles"), ("usage", "Usage"),
        ("warehouses", "Warehouses"), ("execute", "Execute"), ("read", "Read"), ("write", "Write"), ("own", "Own"),
        ("manage", "Manage")]
GKIND = {"schema": "schema_group", "database": "database_group", "type-group": "type_group", "fold": "fold",
         "lane_group": "lane_group"}
ROWS_WORD = {"all": "all rows", "filtered": "filtered rows", "none": "no rows", "unknown": "rows unknown"}
MAX_MEMBERS = 1000  # members of a combined box sent for expansion (the graph groups them by schema, then type); the
# rest through the drill action
MAX_BOX = a.MAX_OBJECTS  # a tab diagram draws one box each up to this many objects / roles per lane
LAZY = 300  # over this many members in all combined boxes, a graph sends their counts only: a box's members come from
# graph?group=<box> when it is opened (a big user's graph was 27k member nodes, 19 MB)
MAX_MULTI = 300  # User page, "Reached more than one way": paths listed (the total counts them all)
MAX_LANE = 24  # role boxes one lane of a big (lazy) graph draws; more fold into one box, as web/src/components/graphs.ts does
GSRC = ("view", "builtin", "roles", "depth", "dataonly", "schema", "otype", "on", "priv", "full", "sensitive", "users", "lean")

LOCK = threading.RLock()  # access.py keeps its lookups in module globals: build + answer under one lock
LOAD = threading.Lock()  # one Snowflake read at a time
MINE = {}
S = dict(sens={}, rows=[], breaks={}, view="shared", known=None)  # per request, set under LOCK
PROGRESS = {}  # cache key -> its last read from Snowflake: view, running, start, lines (what /api/progress shows)
PLOCK = threading.Lock()  # lines come from each()'s threads too
LOG_LINES = False  # python server.py: progress lines also on the terminal
JOB = {}  # the last refresh (Rebuild snapshot / Read Snowflake again): id, what, state running|done|failed, ok, message
BACKGROUND = not a.INSIDE  # refresh in a thread; inside Snowflake on the script's own thread, with the app's session
MAX_LINES = 200
ANSWERS = {}  # (data, endpoint, params) -> answer: a page seen before skips LOCK, so users don't queue behind each other
MAX_ANSWERS = 200
PAGE = 50  # rows per page of a table the server pages (privs, access, sensitive objects and readers, an object's users)


class ApiError(Exception):
    def __init__(self, status, detail, message=""):
        super().__init__(message or detail)
        self.status, self.detail, self.message = status, detail, message or detail


# ---------- data ----------

def connect():  # one connection per load; st_react.py may replace this
    from sf import connect as sf
    return sf()


def with_query(fn, key=None):
    """fn(query) with query(sql) -> list of dicts, on a fresh connection, made at the first statement: a load whose
    parts are all kept logs in to nothing. key: every read kept as a part of key (cache.parted), so a load that stops
    resumes where it stopped; OFFLINE: from the parts only, never a connection."""
    import sf
    conn, clock, gone = [], threading.Lock(), []

    def query(sql):
        try:
            return ask(sql)
        except Exception as e:
            if a.lost(e):
                gone.append(e)
            raise

    def ask(sql):
        with clock:  # one login, also when each()'s threads ask at once; a failed one fails every statement the same
            if not conn:
                try:
                    conn.append(connect())
                except Exception as x:
                    conn.append(x)
        if isinstance(conn[0], Exception):  # a ConnectionError: no part keeps it, the load stops with its message
            raise ConnectionError(str(conn[0])) from conn[0]
        cols, got = sf.rows(conn[0], sql)
        return [dict(zip(cols, r)) for r in got]

    try:
        q = cache.parted(query, key, OFFLINE) if key and cache.local() else query
        got = fn(q)
        if gone:  # live() and mine() turn a failed read into an empty table: a lost session is no empty data set
            raise gone[0]
        if q is not query:
            q.prune()  # the parts this load did not ask for: an older run's tables, older activity days
        return got
    finally:
        if conn and not isinstance(conn[0], Exception) and sf.owned():  # inside Snowflake: the app's session, kept open
            conn[0].close()


def tracked(key, view, fn):
    """fn() with the lines it reports (a.say) kept under key, timed from the start, for /api/progress while it runs."""
    p = PROGRESS[key] = dict(view=view, running=True, start=time.time(), lines=[])

    def add(text):
        with PLOCK:
            p["lines"].append((round(time.time() - p["start"], 1), text))
            del p["lines"][:-MAX_LINES]
        if LOG_LINES:  # the server's terminal shows the same lines as the page
            print(f"{time.strftime('%H:%M:%S')} [{view}] {text}", flush=True)
    try:
        with a.progress(add):
            try:
                return fn()
            except Exception as x:
                a.say(f"failed: {a.line(x)}")
                raise
    finally:
        p["running"] = False


def progress(view=None):
    """The lines of the read running now (the latest of the view, any view when None); none when idle. Reads only
    PROGRESS: asking never starts a load."""
    p = max((p for p in list(PROGRESS.values()) if p["running"] and view in (None, p["view"])),
            key=lambda p: p["start"], default=None)
    with PLOCK:
        lines = [dict(t=t, text=x) for t, x in p["lines"]] if p else []
    return dict(running=bool(p), view=p["view"] if p else None, lines=lines, job=dict(JOB) or None)


def read_shared(key=KEY):
    """The shared data from its source, its reads kept as parts of key (refresh: a key of its own until it is built)."""
    if MODE == "fake":
        return twin.data()  # access.fake(), or the twin for FAKE=twin
    if DIRECT and cache.local() and (OFFLINE or cache.parts_of(key)):  # the SQL lines below then name saved files too
        a.say(f"Building from the saved reads in {cache.parts_dir(key)}: Snowflake is not connected, each SQL line below "
              "names the saved result it loads" if OFFLINE else
              f"Reads already saved in {cache.parts_dir(key)} are loaded, not sent to Snowflake again")
    if DIRECT:
        old = cache.old(key, KEY)  # kept with the parts: a resumed load asks for the same activity days
        d = with_query(lambda q: a.live(q, old.get("ACTIVITY"), old.get("OBJECT_USE")), key)
    else:  # the same run: one small query; with parts each table is a part of its own, read once
        d = with_query(lambda q: a.snapshot(q, WHERE, old=cache.last(KEY)), key)
    d["_read"] = time.time()  # a new build key (and rule check) even when the run is the same: a failed table read again
    return a.tidy(d)  # before it is kept: a restart skips the row scan, the SQL copy thread sees no rows change


def shared_key(d):
    run = d.get("run") or {}  # build() makes it a dict; the key is taken before
    return "shared", run.get("RUN_ID"), str(run.get("FINISHED_AT")), d.get("_read")  # _read: a re-read of the same run


def stages():
    """Stage 1, the reads (parts from disk, the missing ones from Snowflake), then stage 2: the local and SQL copies
    (cache.get), the lookups and the rule checks, so the first page does not build them unseen."""
    t0 = time.monotonic()
    if cache.ready(KEY, MODE == "snowflake"):  # after a restart: the saved copy, with its steps in the load log too
        a.say(f"Opening the saved copy in {cache.DIR} (no Snowflake read)")
    d = cache.get(KEY, read_shared, disk=MODE == "snowflake")[0]
    built(d)
    t = cache.COPYING.get(KEY)
    if t and t.is_alive():  # written beside the build; the pages open after it, not slowed down by it
        with a.step("Finishing the DuckDB copy (access.duckdb)"):
            t.join()
    a.say(f"Ready in {a.took(t0)}")
    return d


def built(d):
    """Stage 2's lookups and rule checks of data set d, timed step by step in the load log."""
    with LOCK:
        with a.step("Building the role graph"):
            a.build(d, shared_key(d))
        a.say(f"Role graph: {len(a.roles):,} roles, {len(a.users):,} users, {len(a.objects):,} objects")
        if a.roles and not ("rows" in a.memo or kept_rules("shared", shared_key(d), False)):
            with a.step("Checking the rules"):
                rows = a.cached("rows", a.rule_rows)
            if rows:  # what session() would work out on the first page, unseen: here it shows in the load log
                with a.step("Working out what each fix changes"):
                    ro = a.cached("ro", a.readonly_writes) if a.HIERARCHY_ON else []
                    a.cached("breaks", lambda: breaks(rows, ro))
            kept_rules("shared", shared_key(d), False, save=True)  # written beside the pages, not before them
        with a.step("Preparing the pages"):
            a.cached("sens", a.sensitive)


def load_shared(ask=False):
    """ask: a page wants it. Read directly from Snowflake (SOURCE=direct) only on a click (reload what=load): it can
    take minutes, and someone may want only My access; a copy in memory or .cache/, or the parts kept, are used at once."""
    disk = MODE == "snowflake"
    if ask and LOAD.locked() and not cache.ready(KEY, disk):  # a read runs (page reloaded mid-read): wait for it, never "not loaded"
        raise ApiError(409, "shared_loading", "The shared data is being read: the pages open when it is done.")
    if ask and disk and DIRECT and not cache.ready(KEY) and not cache.parts_read_at(KEY):
        raise ApiError(409, "shared_not_loaded", "The shared data is read from Snowflake on request: Load shared data.")
    if cache.ready(KEY, False):  # every page asks: no progress entry for an answer from memory
        return cache.get(KEY, read_shared, disk)[0]
    if not LOAD.acquire(blocking=not ask):  # a page never waits behind a read: it says so and asks again after it
        raise ApiError(409, "shared_loading", "The shared data is being read: the pages open when it is done.")
    try:
        if cache.ready(KEY, False):  # read by the load this one waited for
            return cache.get(KEY, read_shared, disk)[0]
        return tracked(KEY, "shared", stages)
    except ApiError:
        raise
    except Exception as x:
        raise ApiError(503, "shared_unreadable", load_error(x))
    finally:
        LOAD.release()


def load_error(x):
    """A load's error for the page: Snowflake's message, plus what to change when the session has no warehouse."""
    return a.line(x) + (" Set SNOWFLAKE_WAREHOUSE in .env to a warehouse this role may use (USAGE), then load again."
                        if "000606" in str(x) else "")


def fetched(ts=False):
    """When the shared data was read from its source: its oldest part, else the read itself (memory or local file);
    ts: as epoch seconds."""
    t = (cache.parts_read_at(KEY) or cache.MEM[KEY][1]) if KEY in cache.MEM else None
    return t if ts else datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else None


def mine_entry(sid):
    return MINE.get(sid) if sid else None  # kept until Reload my access: the data stays until read again


def mine_state(sid):
    m = mine_entry(sid)
    when = lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")
    return dict(loaded=bool(m), user=m["user"] if m else None, loaded_at=when(m["at"]) if m else None,
                expires_at=None)


LOOPBACK = ("127.0.0.1", "localhost", "::1")


def mine_off():
    """Why My access is off here, else None. It reads with the server's own login, so it is the viewer's access only
    on their own machine with their own SSO login: not inside Snowflake (the owner's rights), not on a server others
    reach (HOST not loopback, or ALLOWED_HOSTS names another host: a proxy or tunnel), not with a key pair (a service
    user). MY_ACCESS=1 / 0 decides outside Snowflake."""
    if a.INSIDE:
        return ("My access is not available inside Snowflake: the app runs with its owner's rights, not yours. "
                "Use the local version for your own access.")
    v = os.environ.get("MY_ACCESS")
    if v in ("0", "1"):
        return None if v == "1" else "My access is turned off here (MY_ACCESS=0)."
    extra = {h.strip().lower() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()} - set(LOOPBACK)
    if os.environ.get("HOST", "127.0.0.1") not in LOOPBACK or extra:
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
    at, ck = time.time(), None  # ck: the cache key (local copy, SQL copy)
    if MODE == "snowflake":
        ck = "my_data"
        if fresh:
            if OFFLINE:
                raise ApiError(409, "build_only", BUILD_ONLY_NOTE)
            cache.clear_parts(ck)
            cache.drop(ck)
        try:
            d, at = cache.get(ck, lambda: tracked(ck, "mine", lambda: with_query(
                lambda q: a.mine(q, WHERE.split(".")[0] or None), ck)))
        except Exception as x:  # a cancelled SSO, no warehouse, the network: the real message, as for the shared data
            raise ApiError(503, "mine_unreadable", load_error(x))
        at = cache.parts_read_at(ck) or at  # built from parts: when they were read
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
        key = shared_key(d)
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
        if not all(k in a.memo for k in KEPT):
            kept_rules(view, key, builtin)
        had = {k for k in KEPT if k in a.memo}
        rows = S["rows"] = a.cached("rows", a.rule_rows) if a.roles else []
        ro = (lambda: a.cached("ro", a.readonly_writes)) if a.HIERARCHY_ON else list  # HIERARCHY=0: rule 17 off
        S["breaks"] = a.cached("breaks", lambda: breaks(rows, ro())) if rows else {}
        if a.roles and any(k in a.memo and k not in had for k in KEPT):  # built() works them out; a builtin=1 switch here
            kept_rules(view, key, builtin, save=True)
        yield d


KEPT = ("findings", "rows", "ro", "breaks")  # the rule results a restart need not check again
SERVER_STAMP = hashlib.sha1(pathlib.Path(__file__).read_bytes()).hexdigest()  # breaks() is this file's


def kept_rules(view, key, builtin, save=False):
    """The shared data's rule results kept in .cache/<key>.rules.pkl across restarts, while the data set, the settings
    and access.py are the ones that made them: put back into a.memo (True when they were), or written (save)."""
    if view != "shared" or MODE != "snowflake" or not cache.local():
        return False
    f = cache.file(KEY).with_suffix(".rules.pkl")
    stamp = (key, builtin, a.rules_stamp(), SERVER_STAMP)
    if save:  # in a thread: the pages need a.memo, not the file, and a big file takes a while to write
        memo = {k: a.memo[k] for k in KEPT if k in a.memo}
        if BACKGROUND:
            threading.Thread(target=save_rules, args=(f, stamp, memo), daemon=True).start()
        else:
            save_rules(f, stamp, memo)
        return True
    if not (got := rules_file(f, full=False)) or got[0] != stamp or not (got := rules_file(f)):
        return False
    for k, v in got[1].items():
        a.memo.setdefault(k, v)
    a.say("Rule results kept from the last check of this data: not checked again")
    return True


RULES_LOCK = threading.Lock()  # one rules file write at a time


def rules_file(f, full=True):
    """(stamp, memo) of a rules file, memo None unless full: the stamp is read alone, so checking it never loads the
    results. None when missing, unreadable or in the older one-object format."""
    try:
        with open(f, "rb") as h:
            stamp = pickle.load(h)
            return (stamp, pickle.load(h) if full else None) if isinstance(stamp, tuple) else None
    except Exception:
        return None


def save_rules(f, stamp, memo):
    """Write a rules file: the stamp, then the results. The one it replaces, of another data set, becomes the previous
    snapshot's (What changed)."""
    with RULES_LOCK:
        f.parent.mkdir(parents=True, exist_ok=True)
        was = rules_file(f, full=False)
        tmp = f.with_suffix(".tmp")
        with open(tmp, "wb") as h:
            pickle.dump(stamp, h)
            pickle.dump(memo, h, protocol=pickle.HIGHEST_PROTOCOL)
        if was and was[0][0] != stamp[0]:
            f.replace(cache.file(KEY).with_suffix(".prev.rules.pkl"))
        tmp.replace(f)


def prev_findings(d):
    """The rule findings kept_rules() set aside for the previous snapshot d, while settings and code are the same,
    else None (What changed checks d's rules again)."""
    if MODE != "snowflake" or not cache.local() or a.source.get("builtin"):
        return None
    f = cache.file(KEY).with_suffix(".prev.rules.pkl")
    got = rules_file(f)
    return got[1].get("findings") if got and got[0] == (shared_key(d), False, a.rules_stamp(), SERVER_STAMP) else None


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
    # a cell starting with = + - @ tab or CR runs as a formula in Excel; object names are metadata anyone may set
    safe = lambda v: f"'{v}" if isinstance(v, str) and re.match(r"[=+\-@\t\r]", v) and not re.fullmatch(r"[+-]?\d+(\.\d+)?", v) else v
    f = io.StringIO()
    w = csv.writer(f)
    w.writerows([[safe(v) for v in r] for r in head] + ([[]] if head else []))  # head rows carry names from the link too
    w.writerow(cols)
    w.writerows([[safe(v) for v in r] for r in rows])
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
    "24": ("user", "Activity", "A person (not a service user) ran INSERT, UPDATE, DELETE, MERGE or DDL on a table, "
           "with a role that does not own it.", "Move the change into the build or a pipeline; give the person READ."),
    "25": ("user", "Activity", "A service user ran queries from Snowsight, SnowSQL or the Snowflake CLI.",
           "Give the person their own user; keep the service user's key in the pipeline only."),
    "26": ("admin", "Activity", "Someone read or changed a table with an admin role (ACCOUNTADMIN, SYSADMIN, ...).",
           "Do data work with a functional role; keep admin roles for account tasks."),
    "27": ("object", "Activity", f"A user who was active before touched a table for the first time in the last "
           f"{a.NEW_DAYS} days.", "Confirm the new use with the user or the table's owner."),
    "29": ("object", "Sensitive data", "People can open a Streamlit app whose owner role reads sensitive data they can't "
           "read themselves; the app runs with its owner's rights.", "Remove the app's USAGE from that role, or run the "
           "app with a caller's rights connection, or give it an owner role without the sensitive data."),
    "28": ("object", "Activity", f"One day had over {a.SPIKE[0]} times the user's usual queries on a table (and at "
           f"least {a.SPIKE[1]}).", "Check what ran that day: an export, a broken job or misuse."),
}


IP = "IMPORTED PRIVILEGES on database SNOWFLAKE"


def note_info(k, source, view):
    """A NOTES key in plain words: (title, what it means for the app, how to fix it or None)."""
    mine = view == "mine"
    if source == "SKIPPED":  # ACTIVITY=0
        return ({"activity": "Activity skipped", "object_use": "Object usage skipped"}.get(k, f"{k} skipped"),
                "ACTIVITY=0: ACCESS_HISTORY is not read, so the Activity tabs, rules 24-28 and Granted vs used are off.",
                "Set ACTIVITY=1 (the default) and read again.")
    if k == "usage":
        return (("Query history: 7 days only", "Roles and warehouses used before that look unused.",
                 f"{IP} gives 30 days.") if source == "INFORMATION_SCHEMA" else
                ("No query history", "No 'last used' for roles and warehouses. Grants and paths are complete.",
                 f"{IP}." if not mine else "None needed: grants and paths are complete."))
    if source == "UNAVAILABLE" and k in ("grants", "user_roles"):  # unreadable, not read the slow way
        return ("Grants unread" if k == "grants" else "User roles unread",
                "Shown empty: no role reaches anything." if k == "grants" else "Shown empty: no user holds a role.",
                f"{IP}, or SELECT on the snapshot tables.")
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
        "schemas": ("Schema list from a fallback", "Future grants are read per schema of this list: schemas this role "
                    "can't see are missing.", f"{IP}."),
        "streams": ("Streams unread", "The stream rule (22) can't run.", f"{IP}."),
        "objects": ("Object list partly read", "Objects of the kinds in the error show only where a grant names them.",
                    f"{IP}; for SHOW kinds (Streamlit apps, notebooks, ...) MONITOR or USAGE on them."),
        "app_grants": ("App grants partly read", "Who can open the apps in the error may be incomplete: their grants were "
                       "refused, or go to something other than a role (a user, an application), which no path shows.",
                       "For refused apps: MANAGE GRANTS, or a privilege on them."),
        "activity": ("No client in Activity", "SESSIONS is not readable: the Activity tabs show no client and rule 25 "
                     "can't run.", f"{IP}.") if source == "ACCOUNT_USAGE" else
                    ("No table activity", "The Activity tabs and rules 24-28 can't run: ACCESS_HISTORY is not readable "
                     "(Enterprise edition or higher).", f"{IP}, on Enterprise edition."),
        "object_use": ("No object usage", "Granted vs used has nothing to compare: ACCESS_HISTORY is not readable "
                       "(Enterprise edition or higher).", f"{IP}, on Enterprise edition."),
        "database_roles": ("Database roles partly read", "What the database roles in the error give is missing.",
                           "USAGE on those databases."),
        "error": ("Snapshot run failed", "The last SP_ACCESS_SNAPSHOT run failed.", "Run sql/2_snapshot.sql and read its error."),
        "no_run": ("No snapshot yet", "There is no OK SP_ACCESS_SNAPSHOT run to read: every page is empty.",
                   "Run sql/1_setup.sql and sql/2_snapshot.sql, then Read Snowflake again."),
        "missing_names": ("Rows left out", "Rows Snowflake gave without a name, day or action are not shown.", None),
        "missing_columns": ("Columns missing", "The snapshot tables lack newer columns: those values are empty.",
                            "Run sql/1_setup.sql again, then rebuild the snapshot."),
        "secondary_roles": ("Secondary roles off", "Only privileges of your primary role's tree count.", None),
        "user": ("No user", "Snowflake named no logged-in user: My access is empty.", "Log in again."),
    }.get(k, (k.replace("_", " ").capitalize(), "Read with a fallback, or partly.", None))


def loop_notes():
    """A side note per role loop (a.loops): path counts through it are approximate."""
    return [dict(key="role_loop", title="Role loop", raw=", ".join(x),
                 meaning=f"Roles {', '.join(x[:5])}{' ...' if len(x) > 5 else ''} hold each other: path counts through "
                 "them are approximate, and a page that lists every path can show more than it counts.",
                 fix="Snowflake refuses such grants: read the snapshot again once the change that made it is done.")
            for x in a.loops()]


def snap_time(run):
    """("2026-11-02 07:00 UTC · 13 h ago", older than 24 h, its epoch seconds or None: the page ages it itself)."""
    v = run.get("FINISHED_AT")
    if isinstance(v, datetime) and v.tzinfo:
        v = v.astimezone(timezone.utc)
    try:
        t = a.when(v)
    except Exception:
        t = None
    if t is None:
        return str(v), False, None
    h = max(0, (datetime.now(timezone.utc).replace(tzinfo=None) - t).total_seconds() / 3600)
    return (f"{t:%Y-%m-%d %H:%M} UTC · " + (f"{h:.0f} h ago" if h < 48 else f"{h / 24:.0f} days ago"), h > 24,
            t.replace(tzinfo=timezone.utc).timestamp())


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


LEVEL_WORD = {"names": "see its names", "use": "use it", "read": "read", "change": "change", "own": "own", "admin": "through an admin role"}


def focus_access(o):
    """Who has access to a focused database, schema or object, as the Object page's Who tab counts it (a.who_has):
    people per level, most first, and the roles on the way; None for a role or a box."""
    if o not in a.kinds:
        return None
    w = a.cached(("who_has", o), lambda: a.who_has(o, a.kinds[o]))
    n = Counter(x["level"] for x in w["people"])
    return dict(type=a.kinds[o], people=len(w["people"]), roles=len(w["roles"]),
                levels=[dict(level=k, word=LEVEL_WORD.get(k, k), n=n[k]) for k in a.OBJ_LEVELS[::-1] if n[k]])


def fold_lanes(lanes, edges, gx, kinds, info, keep, sizes=None):
    """A big graph's crowded lanes (over MAX_LANE roles or people) as one box each, "lane:<i>" for its roles and
    "lane:<i>:people" for its people (PUBLIC brings every user), as the graph component folds role lanes (graphs.ts
    foldRoles), so the members and their lines go out only when the box is opened; lines to the members point at the
    box, counting them. keep: names never folded (the start, the selected box); sizes: {box of people: how many}
    (the access graph's stacks)."""
    gx, kinds, to, out, sizes = dict(gx), dict(kinds), {}, [], sizes or {}
    person = lambda n: n in sizes or nk(n) == "user"
    for i, (lab, ns) in enumerate(lanes):
        free = [n for n in ns if n not in kinds and n not in keep and nk(n) != "object"]
        for gid, noun, ms in ((f"lane:{i}", "roles", [n for n in free if not person(n)]),
                              (f"lane:{i}:people", "people", [n for n in free if person(n)])):
            if len(ms) <= MAX_LANE:
                continue
            mem = set(ms)
            gx[gid] = dict(members=ms, edges=[e for e in edges if e[0] in mem or e[1] in mem], noun=noun,
                           count=sum(sizes.get(n, 1) for n in ms),
                           findings=sum(len(info.get(n, {}).get("rules", [])) for n in ms), drill=None, ids=ms)
            kinds[gid] = "lane_group"
            to.update(dict.fromkeys(ms, gid))
            ns = [n for n in ns if n not in mem] + [gid]
        out.append((lab, ns))
    if not to:
        return lanes, edges, gx, kinds
    new, per = [], {}
    for e in edges:
        x, y = to.get(e[0], e[0]), to.get(e[1], e[1])
        if (x, y) == (e[0], e[1]):
            new.append(e)
        elif x != y:
            per.setdefault((x, y, *e[2:4]), set()).add(e[0] if e[0] in to else e[1])
    return out, new + [k if len(k) == 2 else (*k, None, len(m))[:4] + (len(m),) for k, m in per.items()], gx, kinds


def through(edges, ids):
    """ids and every node on a line through them: what leads to them and what they lead to."""
    ins, outs = {}, {}
    for e in edges:
        ins.setdefault(e[1], []).append(e[0])
        outs.setdefault(e[0], []).append(e[1])
    keep = set(ids)
    for nxt in (ins, outs):
        todo, seen = list(ids), set(ids)
        while todo:
            for y in nxt.get(todo.pop(), ()):
                if y not in seen:
                    seen.add(y)
                    todo.append(y)
        keep |= seen
    return keep


def cut(lanes, edges, keep):
    """The lanes and edges of the nodes in keep; empty lanes go."""
    lanes = [(lab, [n for n in ns if n in keep]) for lab, ns in lanes]
    return [x for x in lanes if x[1]], [e for e in edges if e[0] in keep and e[1] in keep]


def scope_key(o):
    """DB.SCHEMA of an object (its database when it has no schema): a focused box's objects box again by it."""
    db, sc, _ = a.split_name(o)
    return f"{db}.{sc}" if sc else db or o


def narrow(lanes, edges, notes, kinds, gx, focus, later=None):
    """build_graph focus=: only the lines through one box. A combined box opens into its members first (objects over
    MAX_BOX box again per schema), a member of one (picked inside an opened box) opens it with only that member on;
    a box whose own lines do not reach its members (a summary fold) stays one box. The other boxes keep the members
    on those lines. later: the boxes fold_lanes makes afterwards (a folded lane: its members are drawn here). A box
    not drawn: the whole graph and a note. Returns lanes, edges, notes, kinds, gx, label of the focus or None, note."""
    lane = (later or {}).get(focus)
    at = focus  # the drawn box: the focus, or the combined box that holds it
    if focus not in {n for _, ns in lanes for n in ns} and not lane:
        at = next((k for k, x in gx.items() if focus in x["members"]), None)
        if at is None:
            return lanes, edges, notes, kinds, gx, None, f"{focus} is not in this graph: all of it is shown."
    gx, kinds = dict(gx), dict(kinds)  # often a cached graph's own: never changed in place
    box = gx.get(at)
    ids = ({focus} if at != focus else set(box["members"])) if box else {focus}
    if box and not any(e[0] in ids or e[1] in ids for e in box.get("edges") or ()):
        box, ids = None, {at}
    blabel = lambda k: k.split(" · ")[0].strip("⋯ ")
    label = a.node_name(focus) if box and at != focus or at not in gx else blabel(at)
    if lane:
        label, ids = f"{lane['count']} {lane['noun']}", set(lane["members"])
    if box:
        mem = box["members"]
        lanes = [(lab, [m for n in ns for m in (mem if n == at else [n])]) for lab, ns in lanes]
        edges = [e for e in edges if at not in e[:2]] + list(box.get("edges") or [])
        gx, kinds = {k: v for k, v in gx.items() if k != at}, {k: v for k, v in kinds.items() if k != at}
    # the walk takes the members' own lines in place of their box's: a box keeps a member only if a line through the
    # focus reaches it, not one an ancestor's other grants reach (a box id can be a member's name: DW.CORE)
    inner = {k for k, x in gx.items() if any(e[0] in x["members"] or e[1] in x["members"] for e in x.get("edges") or ())}
    keep = through([e for e in edges if e[0] not in inner and e[1] not in inner]
                   + [e for k in inner for e in gx[k]["edges"]], ids)
    for k in inner:
        x = gx[k]
        ms = [m for m in x["members"] if m in keep]
        if ms:
            keep.add(k)
        if ms and len(ms) < len(x["members"]):
            gx[k] = x | dict(members=ms, count=len(ms)) | (
                dict(label=f"{blabel(k)} · {len(ms)} {x.get('noun') or 'objects'}") if " · " in k else {})
    ins = {}
    for e in edges:
        ins.setdefault(e[1], []).append(e[0])
    fed = {e[1] for e in edges if e[0] in keep and e[1] in keep}
    todo = [n for n in keep if n not in fed and ins.get(n)]  # a holder fed only through a summary fold's own line: the
    while todo:  # members' walk misses it, so the way in comes back from the drawn lines (upstream only)
        for x in ins.get(todo.pop(), ()):
            if x not in keep:
                keep.add(x)
                todo.append(x)
    lanes, edges = cut(lanes, edges, keep)
    gx = {k: v for k, v in gx.items() if k in keep}
    notes = {k: v for k, v in notes.items() if k in keep}
    objs = [m for m in ids if m in keep and nk(m) == "object"]
    if box and len(objs) > MAX_BOX and len({scope_key(o) for o in objs}) > 1:
        at = next(i for i, (_, ns) in enumerate(lanes) if objs[0] in ns)
        lanes, edges, notes, kinds, more = combine_tab(lanes, edges, notes, kinds, at=at, key=scope_key, kind="schema")
        gx |= more
    return lanes, edges, notes, kinds, gx, label, None


def build_graph(title, lanes, edges, notes=None, info=None, kinds=None, selected=None, header="", level="object",
                note=None, full=False, bad=(), start=None, check=False, types=None, gx=None, src=None, only=None,
                sizes=None, focus=None):
    """Graph JSON from access.py's (lanes, edges, notes): nodes with kinds, marks, rule hits and click actions, merged
    edges, and the expansion payload of every combined box (gx: {box: dict(members, edges, drill, ...)}). src: the
    graph endpoint's params that draw this graph again; with it, over LAZY members the boxes go out empty (lazy), and
    only=<box> answers that box alone, members included. sizes: as fold_lanes. focus=<box>: only the lines through it
    (narrow), done before anything is folded, so a big account sends only those."""
    notes, kinds, types, gx = notes or {}, kinds or {}, types or {}, gx or {}
    shows = None
    if focus:
        later = None
        if src and focus.startswith("lane:") and gx.get(focus) is None:  # a folded lane of the big graph, once per graph
            later = a.cached(("later", tuple(sorted(src.items())), selected, start), lambda: fold_lanes(
                lanes, edges, gx, kinds, hits(lanes, edges, info), {selected, start}, sizes)[2])
        lanes, edges, notes, kinds, gx, shows, miss = narrow(lanes, edges, notes, kinds, gx, focus, later)
        note = " ".join(x for x in (note, miss) if x) or None
        src = src and src | dict(focus=focus)
    info = hits(lanes, edges, info)
    big = bool(src) and sum(len(x["members"]) for x in gx.values()) + sum(len(ns) for _, ns in lanes) > LAZY
    lazy = big and only is None
    if big or any(len(ns) > MAX_LANE for _, ns in lanes):  # a crowded lane folds even in a small graph:
        lanes, edges, gx, kinds = fold_lanes(lanes, edges, gx, kinds, info, {selected, start, focus}, sizes)  # 276 people
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
        name = (gx.get(n) or {}).get("label", n) if gk else a.node_name(n)  # a box narrowed by focus: its new count
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
            label = n.strip("⋯ ").join(["⋯ ", " ⋯"]) if gk == "fold" else n.split(" · ")[0] if gk in ("database", "schema") else n
            if gk == "lane_group":
                label, sub = sub, lanes[i][0]
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
        classes = None if gk or kind in ("user", "object") else role_classes(name)
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

    groups = {}
    for gid, x in gx.items():
        if only is not None and gid != only:
            continue
        mem = x["members"]
        gl = lane_of.get(gid, len(lanes) - 1)
        shown = [] if lazy else mem[:MAX_MEMBERS]
        keep = set(shown)
        es = x["edges"] if lazy else [e for e in x["edges"] if e[1] in keep or e[0] in keep]
        lo = dict(lane_of) | {n: gl for n in shown}
        sens = sum(n in S["sens"] for n in mem)
        gi = info.get(gid, {})
        classes = x.get("classes") or [c for c in a.CLS_ORDER if c in {e[2] for e in es if len(e) > 2}]
        groups[gid] = dict(
            kind=GKIND[kinds[gid]], label=x.get("label", gid), noun=x.get("noun") or gi.get("noun") or "objects",
            count=x.get("count") or gi.get("count") or len(mem), sensitive=x.get("sensitive", gi.get("sensitive", sens)),
            findings=x.get("findings", gi.get("findings", 0)), classes=classes,
            nodes=[node(n, gl, {}) for n in shown], edges=[] if lazy else edge_list(es, lo, hits([("", shown)], es)),
            truncated=0 if lazy else max(0, len(mem) - MAX_MEMBERS), drill=x.get("drill"), lazy=lazy,
            ids=x["ids"] if lazy and "ids" in x else None)  # a folded lane's role names: lines of other boxes end in it
    if only is not None:
        need(only in groups, f"{only} is not a combined box of this graph")
        return groups[only]
    nodes = [node(n, i, kinds) for i, (_, ns) in enumerate(lanes) for n in ns]
    eds = edge_list(edges, lane_of, info)
    allnodes = nodes + [n for g in groups.values() for n in g["nodes"]]
    return dict(
        title=title, header=header, level=level, note=note, full=full, selected=selected, focus=shows and dict(id=focus, label=shows, access=focus_access(focus)),
        lanes=[dict(index=i, label=lab, depth=lane_depth(lab)) for i, (lab, _) in enumerate(lanes)],
        nodes=nodes, edges=eds, groups=groups, src=src if lazy else None,
        legend=dict(kinds=list(dict.fromkeys(n["kind"] for n in nodes)),
                    edges=list(dict.fromkeys(e["cls"] for e in eds)),
                    marks=sorted({m for n in nodes for m in n["marks"]}),
                    rules=any(n["rules"] for n in allnodes) or any(e["rules"] for e in eds)
                    or any(g["lazy"] and g["findings"] for g in groups.values())))


def role_classes(r):
    """What a role's own grants allow (a graph box's classes: folded box counts), once per data set and role."""
    seen = a.cached("role_classes", dict)
    if r not in seen:
        seen[r] = [c for c in a.CLS_ORDER if c in {a.priv_class(pv, k) for pv, k, _ in a.granted.get(r, [])}]
    return seen[r]


def member_groups(rows, level, schema):
    """Members and holder edges of every combined box of graph_input (same keys as there)."""
    by = {}
    for r in rows:
        k = (f"{schema} · {r['type']}" if level == "type" else a.group_key(r, level)
             if (r["schema"] if level == "schema" else level == "database" and r["database"]) else None)
        if k is not None:
            by.setdefault(k, []).append(r)
    out = {}
    for k, rs in by.items():
        es = list(dict.fromkeys((h, r["object"], r["cls"], r["privilege"]) for r in rs for h in r["holders"]))
        cls = {e[2] for e in es}
        out[k] = dict(members=sorted({r["object"] for r in rs}), edges=es,
                      drill=dict(kind="otype", otype=rs[0]["type"]) if level == "type" else dict(kind="drill", schema=k),
                      classes=[c for c in a.CLS_ORDER if c in cls])
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


def input_graph(start, user, rows, schema=None, otype=None, default_only=False, limit=None, full=False, lean=False):
    """graph_input() of a user or role (a summary when big, unless full) with its expansion payloads, or None; once per
    data set (rows are grants() of the same walk; a box opened later asks again)."""
    return a.cached(("input_graph", start, user, schema, otype, default_only, limit, full, lean),
                    lambda: drawn_input(start, user, rows, schema, otype, default_only, limit, full, lean))


def drawn_input(start, user, rows, schema, otype, default_only, limit, full, lean):
    g = a.graph_input(start, schema, default_only=default_only, limit=limit, user=user, otype=otype, lean=lean)
    if not g:
        return None
    use = [r for r in rows if not (r["privilege"] == "USAGE" and r["type"] in ("DATABASE", "SCHEMA"))
           and a.in_scope(r, schema) and otype in (None, r["type"])]
    if g["left"]:
        use, g = g["rows"], g | dict(header=f"{g['header']} · left out: {g['left']}")
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


def combine_tab(lanes, edges, notes, kinds, at=None, key=None, kind="database"):
    """Tab diagram with many boxes: objects over MAX_BOX become one box per database (the graph component folds crowded
    role lanes: database roles per database, group roles, then the rest). at: the objects lane (default: the lanes
    labelled Object / Objects). key, kind: another box per object (scope_key, "schema"). An edge (a, b, cls,
    privilege, n) keeps its count n (the access graph's people). Returns lanes, edges, notes, kinds, gx."""
    gx, to = {}, {}  # to: member -> its box
    lanes = [(lab, list(ns)) for lab, ns in lanes]
    for i, (lab, ns) in enumerate(lanes):
        if (i == at if at is not None else lab in ("Object", "Objects")) and len(ns) > MAX_BOX:
            by = {}
            for o in ns:  # account-level objects and drawn boxes (every object, the built-ins) stay single
                by.setdefault(((key or (lambda x: a.split_name(x)[0] or x))(o)) if o in a.kinds else o, []).append(o)
            ids = []
            for k, os_ in by.items():
                if len(os_) == 1:
                    ids.append(os_[0])
                    continue
                gid = f"{k} · {len(os_)} objects"
                gx[gid] = dict(members=os_, count=len(os_), noun="objects", drill=dict(kind="drill", schema=k))
                kinds[gid] = kind
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
        elif len(e) > 4 and (x, y) == (e[0], e[1]):
            new.append(e)
        else:  # one line per (holder, box, class, privilege), counting its objects (or the most of n)
            o, n = per.get((x, y, e[2], e[3]), (set(), 0))
            o.add(e[1])
            per[(x, y, e[2], e[3])] = o, max(n, e[4] if len(e) > 4 else 0)
    new = list(dict.fromkeys(new)) + [(x, y, c, pv, n or (len(o) if y in gx else 1)) for (x, y, c, pv), (o, n) in per.items()]
    for g in gx.values():
        g["edges"] = []
    for e in edges:  # what an expansion draws: the original links, outside ends mapped to their box
        for gid in {to.get(e[0]), to.get(e[1])} - {None}:
            gx[gid]["edges"].append((e[0] if to.get(e[0]) == gid else to.get(e[0], e[0]),
                                     e[1] if to.get(e[1]) == gid else to.get(e[1], e[1]), *e[2:]))
    for g in gx.values():  # the classes of a box, once (a graph asks per box over all its lines)
        g["classes"] = [c for c in a.CLS_ORDER if c in {e[2] for e in g["edges"] if len(e) > 2}]
    notes = {n: v for n, v in notes.items() if n not in to}
    return lanes, new, notes, kinds, gx


def tab_graph(start, user, rows, walked=(), what="privileges", full_title="Graph", src=None, only=None, focus=None):
    """A Privileges tab's own diagram: start, the roles on the way, the objects of just these rows (walked: role paths).
    Over MAX_OBJECTS rows only the shortest path of each row is drawn. src, only: as build_graph."""
    big = len(rows) > a.MAX_OBJECTS

    def drawn():
        g = a.down_graph(start, [r | dict(paths=r["paths"][:1]) for r in rows] if big else rows, walked, user)
        return g and combine_tab([x for x in g[0] if x[1]], g[1], g[2], {})
    # a big user's tab takes seconds: once per data set and params (src draws it again), so a focus only narrows
    got = a.cached(("tab_graph", start, user, what, tuple(sorted(src.items()))), drawn) if src else drawn()
    if not got:
        return None
    lanes, edges, notes, kinds, gx = got
    n = len(rows) or len(walked)
    return build_graph(full_title, lanes, edges, notes, kinds=kinds, header=f"{n} {what}" + (" · shortest path each" if big else ""),
                       level="database" if any(k == "database" for k in kinds.values()) else "object",
                       start=start, check=user, gx=gx, src=src, only=only, focus=focus)


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


FIRST_FINDINGS = 50  # findings a User / Role page lists, worst first (a big user has 10k+); Risks & fixes pages them all


def subject_of_finding(name, of):
    """Test (grantee, kind) -> is it a finding of name: of="user" its own and those of the roles granted to it
    directly, "role" the role's own, else any grantee called name."""
    via = set(a.roles_of.get(name, [])) if of == "user" else set()
    if of in ("user", "role"):
        return lambda g, k: (g == name and (k == "user") == (of == "user")) or (g in via and k != "user")
    return lambda g, k: g == name


def findings_of(name, user, skip=()):
    """Rule findings of a user or role (for a user also of the roles granted to it directly): the worst
    FIRST_FINDINGS, the total and the count per severity."""
    mine = subject_of_finding(name, "user" if user else "role")
    xs = [x for x in S["rows"] if x["num"] not in skip and mine(x["grantee"], x["kind"])]
    sev = dict.fromkeys(SEV_RANK, 0)
    for x in xs:
        sev[x["severity"]] = sev.get(x["severity"], 0) + 1
    xs.sort(key=lambda x: SEV_RANK.get(x["severity"], 9))
    return [finding(x) for x in xs[:FIRST_FINDINGS]], len(xs), sev


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
            y["queries"] += int(x["QUERIES"] or 0)
            y["last_used"] = max(y["last_used"], str(x["LAST_USED"] or "")[:16])
            y["secondary"] &= x["KIND"] == "SECONDARY ROLE"
    dr = (a.profile.get(u) or {}).get("DEFAULT_ROLE")
    roles = []
    for r in sorted(a.roles_of.get(u, [])):
        x = by.get(r)
        status = "unused" if not x else "secondary" if x["secondary"] else "used"
        takes = a.loses_objects(u, r) if status == "unused" else None
        roles.append(dict(role=r, kind=norm(a.role_kind(r)), default=r == dr, status=status,
                          queries=x["queries"] if x else 0, last_used=x["last_used"] if x else None, takes=takes))
    roles.sort(key=lambda r: (r["status"] != "unused", -r["queries"], r["role"]))
    return dict(days=days, source=f"Query history, last {days} days, from {'INFORMATION_SCHEMA' if days == 7 else 'ACCOUNT_USAGE'}",
                readable=src != "UNAVAILABLE", roles=roles,
                warehouses=[dict(name=x["NAME"], queries=int(x["QUERIES"] or 0), last_used=str(x["LAST_USED"] or "")[:16])
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
    key = ("user_ctx", u, limit, default_only, data_only, p.get("schema", ""), p.get("otype", ""), p.get("on", ""),
           p.get("priv", ""))
    return a.cached(key, lambda: dict(user_rows(p, u, limit, default_only, data_only), key=key, mine=mine))


def user_rows(p, u, limit, default_only, data_only):
    """user_ctx without the cache (a big user's 200k rows filter and sort in seconds; the page, its tables and its
    tab diagrams all ask)."""
    every = a.grants(u, True, default_only, limit)
    scope, otype = scope_of(p, every), p.get("otype") or None
    ok = lambda r: a.in_scope(r, scope) and otype in (None, r["type"])
    rows = [r for r in every if ok(r) and not (data_only and r["privilege"] == "USAGE" and r["type"] in ("DATABASE", "SCHEMA"))]
    rank = {k: type_rank(k) for k in {r["type"] for r in rows}}
    rows.sort(key=lambda r: rank[r["type"]])  # grants() rows come sorted by object and privilege: a stable sort keeps it
    on, pv = p.get("on", ""), p.get("priv", "")
    privs = sorted({r["privilege"] for r in rows})
    rows = [r for r in rows if (not on or r["object"] == on) and (not pv or r["privilege"] == pv)]
    hidden = [r for r in every if data_only and r["privilege"] == "USAGE" and r["type"] in ("DATABASE", "SCHEMA") and ok(r)
              and (not on or r["object"] == on) and (not pv or r["privilege"] == pv)]
    reach = a.reach(u, True, default_only, limit)
    if scope:
        path = {n for r in rows for x in r["paths"] for n in x[1:-1]}
        reach = [x for x in reach if x["role"] in path]
    return dict(u=u, limit=limit, default_only=default_only, data_only=data_only, every=every, scope=scope,
                otype=otype, rows=rows, hidden=hidden, reach=reach, on=on, pv=pv, privs=privs)


def user_graph(p, c, only=None):
    """The User page diagram: one object or privilege = just those rows, else graph_input (grouped on big accounts,
    its boxes opened through graph?of=user&group=)."""
    u, rows = c["u"], c["rows"]
    if c["on"] or c["pv"]:
        g = a.down_graph(u, rows, user=True)
        return g and build_graph("Role hierarchy, by depth", g[0], g[1], g[2], header=f"{len(rows)} privileges shown",
                                 start=u, check=True, focus=p.get("focus"))
    ig = input_graph(u, True, c["every"], c["scope"] or None, c["otype"], c["default_only"], c["limit"], flag(p, "full"), flag(p, "lean"))
    return ig and build_graph("Role hierarchy, by depth", ig["g"]["lanes"], ig["g"]["edges"], ig["g"]["notes"],
                              ig["g"]["info"], ig["g"]["kinds"], header=ig["g"]["header"], level=ig["level"],
                              note=ig["note"], full=ig["full"], start=u, check=True, types=ig["g"].get("types"),
                              gx=ig["gx"], src=gsrc(p, of="user", name=u), only=only, focus=p.get("focus"))


def gsrc(p, **extra):
    """The graph endpoint's params that draw a page's graph again (build_graph src)."""
    return {k: p[k] for k in GSRC if p.get(k)} | extra


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
        n = a.grant_count(u, True, False, c["limit"]) - len(c["every"])
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
    findings, total, sev = findings_of(u, True)
    text, mark = login(u)
    sec = str(pr.get("DEFAULT_SECONDARY_ROLES") or "")
    twice = sum(r["count"] > 1 for r in rows)
    sens = sorted({r["object"] for r in rows if r["object"] in S["sens"] and r["privilege"] in a.READ_PRIVS})
    acc = account(admin, acct)
    graph = user_graph(p, c)
    many = [r for r in rows if r["count"] > 1]
    multi = list(itertools.islice(((r, x) for r in many for x in r["paths"]), MAX_MULTI))
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
                     schema=scope, otype=c["otype"] or "", on=c["on"], priv=c["pv"], privileges=c["privs"]),
        banners=banners, findings=findings, findings_total=total, findings_sev=sev,
        kpis=dict(privileges=len(rows), objects=len(objs), paths=sum(r["count"] for r in rows), multi=twice,
                  roles=len(reach), roles_direct=sum(x["direct"] for x in reach),
                  deepest=max((r["depth"] for r in rows), default=0), sensitive=len(sens) if (S["sens"] or shared) else None,
                  sensitive_known=bool(S["sens"]) or shared, admin_roles=len({x[-1] for x in admin}),
                  account_privs=len(acct)),
        account=acc, graph=graph, tabs=a.cached(("tabs", c["key"]), lambda: tab_list(rows, c["hidden"], reach, acc)),
        roles=[reach_row(x) for x in reach],
        multi=dict(rows=[dict(privilege=r["privilege"], cls=r["cls"], object=r["object"], depth=a.depth(x[:-1], True),
                              path=x) for r, x in multi], total=sum(len(r["paths"]) for r in many), shown=len(multi)),
        can_read=sees(p, [v for v in a.data_views(u, True) if not (scope or c["on"] or c["pv"]) or v["object"] in objs]) if shared else None,
        sensitive=sens_reach(u, objs if scope else None),
        granted=[dict(role=r, kind=norm(a.role_kind(r)), default=r == dr, used=use.get(r) and dict(
            queries=use[r]["queries"], last_used=str(use[r]["last_used"])[:16]),
            used_text="not readable" if src == "UNAVAILABLE" else f"{use[r]['queries']} queries · {str(use[r]['last_used'])[:10]}"
            if r in use else "not used") for r in sorted(a.roles_of.get(u, []))],
        usage=usage(u), capped=sorted(a.capped))


ACCESS = {"use": "Use", "read": "Read", "manage": "Manage", "write": "Write", "own": "Own", "admin": "Admin"}
PRIV_SORT = {"object": lambda r: r["label"], "type": lambda r: r["type"], "access": lambda r: ACCESS.get(r["access"], r["access"]),
             "grants": lambda r: ", ".join(r["grants"]), "holder": lambda r: r["holder"], "depth": lambda r: r["depth"],
             "count": lambda r: r["count"], "path": lambda r: " > ".join(r["path"])}


def by_object(rows):
    """One row per object, as web/src/components/tabs.ts byObject: the strongest access (own > write > manage > read >
    use; admin above all), every grant, the shortest path and up to 4 other distinct paths, the most paths of a grant."""
    rank = {k: i for i, k in enumerate(ACCESS)}
    out = {}
    for r in sorted(rows, key=lambda r: r["depth"]):
        o = out.get(r["object"])
        if o is None:
            o = out[r["object"]] = dict(object=r["object"], label=a.future_label(r["object"], r["type"]) or r["object"],
                                        type=r["type"], access=r["cls"], grants=[], holder=r["holder"], depth=r["depth"],
                                        path=r["path"], more=[], count=0, sensitive=r["object"] in S["sens"])
        elif len(o["more"]) < 4 and r["path"] != o["path"] and r["path"] not in o["more"]:
            o["more"].append(r["path"])
        if rank.get(r["cls"], 0) > rank.get(o["access"], 0):
            o["access"] = r["cls"]
        if r["privilege"] not in o["grants"]:
            o["grants"].append(r["privilege"])
        o["count"] = max(o["count"], r["count"])
    return list(out.values())


def privs_rows(p, view):
    """The rows of one Privileges tab (tab=) of the User page (of=role: the Role page), filtered (q=: every word in
    some column) and sorted (sort= a column key, dir=1|-1), from the page's own filters."""
    t = p.get("tab", "all")
    if p.get("of") == "role":
        c = role_ctx(p, view)
        rows = a.cached(("privs", c["key"], t), lambda: by_object(tab_rows(c["eff"], [], [], t)[0]))
    else:
        c = user_ctx(p, view)
        rows = a.cached(("privs", c["key"], t), lambda: by_object(tab_rows(c["rows"], c["hidden"], [], t)[0]))
    words = p.get("q", "").lower().split()
    if words:
        text = lambda r: " ".join([r["label"], r["type"], ACCESS.get(r["access"], r["access"]), ", ".join(r["grants"]),
                                   r["holder"], str(r["depth"]), str(r["count"]), " > ".join(r["path"])]).lower()
        rows = [r for r in rows if all(w in text(r) for w in words)]
    by = PRIV_SORT.get(p.get("sort", "depth"), PRIV_SORT["depth"])
    return sorted(rows, key=by, reverse=p.get("dir") == "-1")


def paged(p, rows):
    """(offset, limit, rows[offset:offset + limit]) from offset= and limit= (PAGE rows, at most 1000)."""
    num = lambda k, d: int(p[k]) if p.get(k, "").isdigit() else d
    off, lim = num("offset", 0), min(num("limit", PAGE), 1000)
    return off, lim, rows[off:off + lim]


def privs_page(p, view):
    """User page, one Privileges tab table, paged on the server: one row per object (web/API.md GET /api/privs)."""
    rows = privs_rows(p, view)
    off, lim, page = paged(p, rows)
    return dict(rows=page, total=len(rows), offset=off, limit=lim)


def privs_csv(p, view):
    rows = privs_rows(p, view)
    cols = ["Object", "Type", "Access", "Grants", "Grant holder", "Depth", "Paths", "Shortest path"]
    out = [[r["label"], r["type"], ACCESS.get(r["access"], r["access"]), ", ".join(r["grants"]), r["holder"], r["depth"],
            r["count"], " > ".join(r["path"])] for r in rows]
    who = role_ctx(p, view)["r"] if p.get("of") == "role" else user_ctx(p, view)["u"]
    return f"{who}_privileges_{p.get('tab', 'all')}.csv", csv_text(cols, out)


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
         "23": "CREATE on a read-only role", "24": "person changed a table", "25": "service user in Snowsight",
         "26": "admin role on data", "27": "first-time access", "28": "unusual volume", "29": "app opens owner's data"}
SEV_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def finding_edges():
    """S["rows"] once per data set: per grantee, the findings with role links (their link pairs); per object an edge
    goes to, (finding, edge grantee, privilege). row_findings then looks up what it needs instead of scanning every
    finding of every role on the paths (PUBLIC alone has thousands)."""
    def make():
        linked, by_to = {}, {}
        for x in S["rows"]:
            pairs = [(e["grantee"], e["to"]) for e in x["edges"] if not e["priv"]]
            if pairs:
                linked.setdefault(x["grantee"], []).append((x, pairs))
            for e in x["edges"]:
                by_to.setdefault(e["to"], []).append((x, e["grantee"], e["priv"]))
        return linked, by_to
    return a.cached(("finding_edges", id(S["rows"])), make)


def row_findings(subject, user, objs, rows):
    """Findings that sit on each access row: the finding is about the subject or a role on the row's paths, and one of
    its grants (edges) is a privilege the row has on the object, or a role link on those paths (data and runnable rows
    only: a link explains a privilege, not a power). One list per entry of objs."""
    ok = lambda x: x["kind"] != "user" or (user and x["grantee"] == subject)
    linked, by_to = finding_edges()
    of, hs = a.path_roles(subject, user), {}
    for r in rows:
        hs.setdefault(r["object"], set()).update(r["holders"])
    chip = lambda x: dict(num=x["num"], severity=x["severity"], label=SHORT.get(x["num"], x["title"]))
    links, out = {}, []  # per set of path roles: chips of its role links
    for o in objs:
        on = of(hs.get(o["object"], ()))
        if on not in links:
            got = {}
            for g in on & linked.keys():
                for x, pairs in linked[g]:
                    if x["num"] not in got and ok(x) and any(f in on and t in on for f, t in pairs):
                        got[x["num"]] = chip(x)
            links[on] = got
        hit = dict(links[on]) if o["category"] in ("data", "runnable") else {}
        for x, g, pv in by_to.get(o["object"], ()):
            if x["num"] not in hit and g in on and x["grantee"] in on and ok(x) and pv in (None, *o["privileges"]):
                hit[x["num"]] = chip(x)
        out.append(sorted(hit.values(), key=lambda f: (SEV_RANK.get(f["severity"], 9), int(f["num"]))))
    return out


def access_subject(p, view):
    """(name, is a user) of the Access page: role=, else user= (My access: the logged-in user)."""
    mine = view == "mine"
    role = p.get("role", "") if not mine else ""
    if role:
        need(role in a.roles, f"{role} is not in this snapshot")
        return role, False
    need(a.users, "No users in this data.")
    name = a.users[0] if mine else p.get("user") or (DEMO_USER if DEMO_USER in a.users else a.users[0])
    need(name in a.users, f"{name} is not in this snapshot")
    return name, True


def access_all(name, user, mine):
    """Every Access page entry, riskiest first, with its findings, sensitive columns and first paths, plus the ladder
    counts and the heat per schema; once per data set (a big user has 100k+ objects: the page sends one page of them)."""
    return a.cached(("access_all", name, user, mine), lambda: access_entries(name, user, mine))


def views_by(name, user, mine):
    return {v["object"]: v for v in a.data_views(name, user)} if not mine or S["sens"] else {}


def sens_columns(o, views):
    v = views.get(o["object"])
    return [dict(column=c["column"], state=c["state"], reason=c["reason"]) for c in v["columns"] if c["sensitive"]] if v else []


def in_clear(o, cols):
    """A sensitive object seen in clear (or unknown): the Access count and the risk strip."""
    return o["object"] in S["sens"] and o["level"] != "names" and (not cols or any(c["state"] != "masked" for c in cols))


def access_entries(name, user, mine):
    rows = a.grants(name, user)
    objs = a.access_objects(rows, user)
    views = views_by(name, user, mine)
    chips = row_findings(name, user, objs, rows)
    first = {}
    for r in rows:
        first.setdefault(r["object"], r["paths"])
    for o, f in zip(objs, chips):
        o["sensitive"] = o["object"] in S["sens"]
        o["columns"] = sens_columns(o, views)
        o["findings"] = f
        o["label"] = a.future_label(o["object"], o["type"])
        o["paths"] = first.get(o["object"], [])[:5]
    rank = lambda o: (min((SEV_RANK.get(f["severity"], 9) for f in o["findings"]), default=9), not o["sensitive"],
                      -a.LEVELS.index(o["level"]) if o["level"] else 0, o["object"])
    objs.sort(key=rank)
    did = {}  # the person's queries per object (a role: the queries run with it), in the activity window
    if not mine and a.act_state()[0]:
        for r in a.acts:
            if (r["USER_NAME"] if user else r["ROLE_NAME"]) == name:
                v = did.setdefault(r["OBJECT_NAME"], [0, ""])
                v[0] += int(r["QUERIES"] or 0)
                v[1] = max(v[1], str(r["LAST_USED"] or "")[:10])
    for o in objs:
        n = did.get(o["object"])
        o["used"] = None if mine or not a.act_state()[0] else dict(queries=n[0], last=n[1]) if n else dict(queries=0, last="")
    counts = a.ladder_counts(objs)
    data = [o for o in objs if o["category"] == "data" and not o["label"]]  # future grants are not objects
    counts["sensitive"] = sum(in_clear(o, o["columns"]) for o in data)
    tabs = [o for o in data if a.is_data(o["type"])]  # tables and views: what the headline counts
    nm = lambda xs: [o["object"].split(".")[-1] for o in xs[:3]] + [f"{len(xs) - 3:,} more"] * (len(xs) > 3)
    clear = [o for o in tabs if in_clear(o, o["columns"])]
    counts["tables"] = dict(read=len(tabs), change=sum(at_least(o, "change") for o in tabs), own=sum(at_least(o, "own") for o in tabs), clear=len(clear))
    counts["names"] = dict(clear=nm(clear), change=nm([o for o in tabs if at_least(o, "change")]),
                           schemas=(lambda xs: xs[:3] + [f"{len(xs) - 3:,} more"] * (len(xs) > 3))(list(dict.fromkeys(f'{o["database"]}.{o["schema"]}' for o in tabs))))
    counts["schemas"] = len({(o["database"], o["schema"] or o["object"]) for o in data})
    heat = {}
    for o in data:
        k = f'{o["database"]}.{o["schema"]}' if o["schema"] else o["object"]
        h = heat.setdefault(k, dict(schema=k, database=o["database"] or o["object"], name=o["schema"] or "",
                                   read=0, change=0, own=0, sensitive=0))
        i = a.LEVELS.index(o["level"]) if o["level"] else 0
        h["read"] += i == 1  # each object in one cell, as the ladder bar and the filter chips count it
        h["change"] += i == 2
        h["own"] += i >= 3
        h["sensitive"] += o["sensitive"]
    risk = lambda h: (-(h["own"] + h["change"] + h["sensitive"]), -h["own"], -h["read"], h["schema"])
    return dict(objs=objs, counts=counts, heat=sorted(heat.values(), key=risk),
                deepest=max((o["depth"] for o in objs), default=0))


def at_least(o, step):
    return o["level"] is not None and a.LEVELS.index(o["level"]) >= a.LEVELS.index(step)


def group_of(o, by):
    """The Access list group of an entry (web/src/pages/screens.ts groupKey)."""
    return (f'{o["database"]}.{o["schema"]}' if o["schema"] else o["object"]) if by == "schema" else o["type"] if by == "type" else ""


def access_list(p, objs):
    """The Access list entries the page asks for: data (usage=1: with database / schema USAGE), filter=read|change|own|
    multi, q= in the name, otype= one object type, cell=<schema>&min=read|change|own|sensitive (a heat cell), sort=risk|name, group=schema|type
    (kept together, in that order)."""
    lvl, q, cell, low = p.get("filter", "all"), p.get("q", "").lower(), p.get("cell", ""), p.get("min", "")
    otype = p.get("otype", "")
    usage = flag(p, "usage")
    step = lambda x, k: not x["label"] and (x["level"] in (k,) if k in ("read", "change") else at_least(x, "own") if k == "own" else False)
    keep = lambda x: (lvl == "all" or (x["ways"] > 1 if lvl == "multi" else step(x, lvl) if lvl in ("read", "change", "own")
                                       else True)) \
        and (not q or q in x["object"].lower()) and (not otype or x["type"] == otype) \
        and (not cell or (group_of(x, "schema") == cell and (x["sensitive"] if low == "sensitive" else step(x, low))))
    plain = lambda x: usage or lvl != "all" or q or otype or cell or p.get("more") or p.get("offset") or (not x["label"] and x["type"] not in ("SCHEMA", "DATABASE"))
    xs = [x for x in objs if (x["category"] == "data" or (usage and x["category"] == "names")) and keep(x)]
    if p.get("short"):  # the page's first list: tables, views and the like; schemas and future grants with more=1
        xs = [x for x in xs if plain(x)]
    if p.get("sort") == "name":
        xs.sort(key=lambda x: x["object"])
    by = p.get("group", "none")
    if by in ("schema", "type"):
        order = {}
        for x in xs:
            order.setdefault(group_of(x, by), len(order))
        xs.sort(key=lambda x: order[group_of(x, by)])
    return xs


HEAT = 15  # schemas in "Where the access is", riskiest first; hq= searches the rest
HOLDERS = 20  # roles that hold a role, listed above it
KIDS = 8  # roles listed under each role of "Why they have it"; Role paths lists them all


def kids(r):
    ks = sorted(a.holds.get(r, []))
    return dict(kids=ks[:KIDS], kids_total=len(ks))


def access_page(p, view):
    """A person (user=) or a role (role=), or My access: one page of objects at their highest level (access_list
    filters, offset=, limit=), things they can run, powers over the account, where the access is (per schema) and why
    they have it (roles)."""
    name, user = access_subject(p, view)
    x = access_all(name, user, view == "mine")
    objs = x["objs"]
    xs = access_list(p, objs)
    off, lim, page = paged(p, xs)
    by = p.get("group", "none")
    groups = {}
    for o in xs if by in ("schema", "type") else ():
        k = group_of(o, by)
        groups[k] = groups.get(k, 0) + 1
    runs = [o for o in objs if o["category"] == "runnable"]
    powers = [o for o in objs if o["category"] == "account"]
    usage = flag(p, "usage")
    pr = (a.profile.get(name) or {}) if user else {}
    if user:
        dr, sec = pr.get("DEFAULT_ROLE"), "ALL" in str(pr.get("DEFAULT_SECONDARY_ROLES") or "").upper()
        text, mark = login(name)
        top = sorted(a.roles_of.get(name, []), key=lambda r: (r != dr, r))
        why = [dict(role=r, kind=norm(a.role_kind(r)), note="default" if r == dr else "secondary" if sec else "",
                    **kids(r)) for r in top]
        if "PUBLIC" not in top:
            why.append(dict(role="PUBLIC", kind="group", note="everyone", **kids("PUBLIC")))
        who = dict(kind="user", name=name, id=a.uid(name, True), type=str(pr.get("TYPE") or "PERSON"), status=a.status(name),
                   disabled=a.is_disabled(name), last_login=text, login_mark=mark, default_role=dr or None, secondary_all=sec,
                   default_warehouse=pr.get("DEFAULT_WAREHOUSE") or None, owner=[], held_by=None)
    else:
        rs, us = a.ups(name)
        hb = sorted(set(a.held_by.get(name, [])))
        why = [dict(role=x, kind=nk(x), note="holds it", kids=[], kids_total=0) for x in hb[:HOLDERS]]
        why.append(dict(role=name, kind=nk(name), note="this role", **kids(name)))
        who = dict(kind=nk(name), name=name, id=name, type=KIND.get(norm(a.role_kind(name)), "Role"), status=None,
                   disabled=False, last_login=None, login_mark="", default_role=None, secondary_all=False, default_warehouse=None,
                   owner=[g for g, pv, t in a.on.get(name, []) if pv == "OWNERSHIP" and t == "ROLE"],
                   held_by=dict(users=len(us), roles=len(rs) - 1))
    out = lambda o: {k: v for k, v in o.items() if k != "holders"}
    hq = p.get("hq", "").lower()
    heat = [h for h in x["heat"] if hq in h["schema"].lower()]
    types = Counter(o["type"] for o in objs if o["category"] == "data" or (usage and o["category"] == "names")).most_common()
    return dict(view=view, who=who, counts=x["counts"], objects=[out(o) for o in page], total=len(xs),
                types=[dict(type=t, n=n) for t, n in types],
                data=sum(o["category"] == "data" or (usage and o["category"] == "names") for o in objs),
                offset=off, limit=lim, groups=groups, runs=[out(o) for o in runs[:PAGE]], runs_total=len(runs),
                powers=[out(o) for o in powers[:PAGE]], powers_total=len(powers), heat=heat[:HEAT],
                heat_total=len(heat), why=why, why_more=0 if user else max(0, len(hb) - HOLDERS), deepest=x["deepest"],
                roles=len(a.cached(("reach", name, user), lambda: a.reach(name, user))),
                admin_roles=sorted({q[-1] for q in a.admin_paths(name, user)} | ({name} & a.ADMIN if not user else set())),
                risks=subject_risks(name, user))


def access_csv(p, view):
    """Every entry of the Access list with the page's filters (access_list), as the list shows them."""
    name, user = access_subject(p, view)
    objs = access_all(name, user, view == "mine")["objs"]
    cols = ["Object", "Type", "Access", "Privileges", "Sensitive columns", "Granted through", "Ways", "Findings"]
    rows = [[o["object"], o["type"], o["level"] or "", " ".join(o["privileges"]),
             "; ".join(f'{c["column"]} {c["state"]}' for c in o["columns"]),
             " > ".join(x for x in (o["first"], o["holder"]) if x), o["ways"],
             "; ".join(f'{f["severity"]} #{f["num"]}' for f in o["findings"])] for o in access_list(p, objs)]
    return f"{name}_access.csv", csv_text(cols, rows)


# ---------- risk strip (top of the Access Overview, Role paths, Who has access, Can they?) ----------

BROAD = 0.25  # very broad access: reads at least this share of the account's data objects ...
BROAD_MIN = 20  # ... and at least this many (a few tables on a small account are not broad)
WIDE = 3  # unused but widely granted: no use in UNUSED days, yet at least this many users can read it
UNUSED = 90
RISK_TOP = 3  # rule names a findings line lists


RISK_ROWS = 10  # rows of the table a risk line opens in place; the link opens all of them


def risk(bad, text, n, to, cols=(), rows=()):
    """One risk line; cols and rows: the table it opens under itself (the first RISK_ROWS of rows)."""
    return dict(severity="bad" if bad else "warn", text=text, n=n, link=to,
                table=dict(cols=list(cols), rows=[list(r) for r in rows[:RISK_ROWS]], total=len(rows)) if rows else None)


def more(xs):
    return ", ".join(xs[:RISK_TOP]) + (f" +{len(xs) - RISK_TOP}" if len(xs) > RISK_TOP else "")


def findings_risk(xs, to):
    """One line for the rule findings xs (S["rows"]): the count per severity and the worst rules' short names."""
    if not xs:
        return None
    xs = sorted(xs, key=lambda x: SEV_RANK.get(x["severity"], 9))
    sev = Counter(x["severity"] for x in xs)
    names = list(dict.fromkeys(SHORT.get(x["num"], x["title"]) for x in xs))[:RISK_TOP]
    counts = ", ".join(f"{sev[s]} {s}" for s in SEVS if sev[s])
    return risk(sev["Critical"] or sev["High"], f"{plural(len(xs), 'rule finding')} ({counts}): {'; '.join(names)}", len(xs), to,
                ["Severity", "Finding", "On"], [(x["severity"], SHORT.get(x["num"], x["title"]), x["grantee"]) for x in xs])


def ranked(xs):
    return sorted((x for x in xs if x), key=lambda x: x["severity"] != "bad")  # stable: within a tone, the order built


def data_total():
    return a.cached("data_total", lambda: sum(a.is_data(k) and not k.startswith("FUTURE") for k in a.kinds.values()))


def seen_counts(name, user):
    """(data objects read, sensitive ones seen in clear [(object, columns in clear)]) as the Access page counts them,
    without its paths and findings: Role paths has no access_all."""
    def make():
        views = views_by(name, user, S["view"] == "mine")
        data = [o for o in a.access_objects(a.grants(name, user), user) if o["category"] == "data" and o["level"]
                and not o["type"].startswith("FUTURE")]
        cols = {o["object"]: sens_columns(o, views) for o in data}
        return sum(o["level"] != "names" for o in data), [
            (o["object"], ", ".join(c["column"] for c in cols[o["object"]] if c["state"] != "masked") or "not known")
            for o in data if in_clear(o, cols[o["object"]])]
    return a.cached(("seen_counts", name, user), make)


def subject_risks(name, user):
    """Risk strip of a person or role, worst first: [dict(severity bad | warn, text, n, link)], [] when nothing needs
    attention. From what the Access and Role pages have: admin paths, account privileges, the Access counts, the rule
    findings, the login state and the profile."""
    return a.cached(("risks", name, user), lambda: risks_of(name, user))


def risks_of(name, user):
    me = {"user" if user else "role": name}
    admins = link("Admin holders", "rules", part="admins")
    out = [risk(True, f"Is admin role {name}: {a.ADMIN_POWER.get(name, 'admin')}", 1, admins)] if not user and name in a.ADMIN else []
    first = {}
    for q in a.admin_paths(name, user):  # shortest first per admin role
        first.setdefault(q[-1], q)
    if first:
        via = "; ".join(f"{r} via {q[1]}" if len(q) > 2 else f"{r} directly" for r, q in first.items())
        out.append(risk(True, f"Holds {plural(len(first), 'admin role')}: {via}", len(first), admins,
                        ["Admin role", "Path"], [(r, " > ".join(q)) for r, q in first.items()]))
    acct = sorted({pv for pv, q in a.account_privs(name, user) if q[-1] != "PUBLIC"})  # PUBLIC's: everyone has them (rule 9)
    if acct:
        way = {}
        for pv, q in a.account_privs(name, user):
            if q[-1] != "PUBLIC":
                way.setdefault(pv, q)
        out.append(risk(True, f"{plural(len(acct), 'account privilege')}: {more(acct)}", len(acct),
                        link("Account powers", "access", **me, show="runs"),
                        ["Privilege", "Path"], [(pv, " > ".join(way[pv])) for pv in acct]))
    read, clear = seen_counts(name, user)
    if clear:
        out.append(risk(True, f"Reads {plural(len(clear), 'sensitive object')} unmasked", len(clear),
                        link("Column by column", "see", **me, show="cards"), ["Object", "Sensitive columns in clear"], clear))
    mine = subject_of_finding(name, "user" if user else "role")
    out.append(findings_risk([x for x in S["rows"] if mine(x["grantee"], x["kind"])],
                             link("Findings", "rules", grantee=name, of="user" if user else "role", sev="all")))
    pr = (a.profile.get(name) or {}) if user else {}
    dr, held = pr.get("DEFAULT_ROLE"), len(a.roles_of.get(name, [])) if user else 0
    if dr in a.ADMIN:
        out.append(risk(True, f"Default role is admin role {dr}: every session starts with it", 1, link("Rule 12", "rules", rule="12")))
    if held and a.stale(name):
        d = a.login_days(name)
        word = "Disabled" if a.is_disabled(name) else "Never logged in" if d is None else f"Dormant, no login for {d} days"
        out.append(risk(False, f"{word}, still holds {plural(held, 'role')}", held, link("Dormant & disabled", "rules", part="stale"),
                        ["Role held"], [(r,) for r in sorted(a.roles_of.get(name, []))]))
    total = data_total()
    if read >= BROAD_MIN and read >= BROAD * total:
        out.append(risk(False, f"Very broad access: reads {read:,} of the account's {total:,} data objects ({100 * read // total}%)",
                        read, link("Objects", "access", **me, show="summary")))
    if held > 1 and "ALL" in str(pr.get("DEFAULT_SECONDARY_ROLES") or "").upper():
        out.append(risk(False, f"Secondary roles ALL: every query uses all {held} granted roles at once", held,
                        link("Role usage", "user", name=name, part="usage"), ["Granted role"],
                        [(r,) for r in sorted(a.roles_of.get(name, []))]))
    return ranked(out)


def last_use():
    return a.cached("last_use", lambda: {r[0]: r for r in a.object_activity()["rows"]})


def object_risks(o):
    """Risk strip of an object, worst first (as subject_risks). From the grants, without the Who has access walk, so
    Can they? stays fast: readers through READ_PRIVS, writers through WRITES, without the people lacking USAGE on its
    database or schema (blocked: Snowflake refuses them), as Who has access counts them."""
    return a.cached(("object_risks", o), lambda: object_risks_of(o))


def object_risks_of(o):
    k, sens, grants = a.kinds[o], o in S["sens"], a.on.get(o, [])
    users = lambda ok: {u for r, pv, _ in grants if ok(pv) for u in a.ups(r)[1]}  # noqa: E731
    open_ = lambda us: sorted(u for u in us if not a.usage_gaps(u, o, True, k))  # noqa: E731
    readers = open_(users(lambda pv: pv in a.READ_PRIVS))
    who = link("Who has access", "object", name=o, show="who")
    out = []
    bare = [c for c in a.sensitive_cols(o) if c not in a.policies_of(o)["columns"]] if a.is_data(k) else []
    if bare and readers:
        out.append(risk(True, f"{plural(len(bare), 'sensitive column')} without masking ({more(bare)}): "
                              f"in clear for the {plural(len(readers), 'user')} who can read it (admin roles aside)", len(bare), who,
                        ["Column without masking"], [(c,) for c in bare]))
    pub = sorted({pv for r, pv, _ in grants if r == "PUBLIC"})
    if pub:
        out.append(risk(sens, f"Granted to PUBLIC (every user): {more(pub)}", len(pub), link("Rule 9", "rules", rule="9")))
    if sens:
        ws = open_(u for u in users(lambda pv: pv in WRITES) if not a.is_service(u))
        if ws:
            out.append(risk(True, f"{len(ws)} {'person' if len(ws) == 1 else 'people'} can change this sensitive object",
                            len(ws), link("Rule 10", "rules", rule="10"), ["Person"], [(u,) for u in ws]))
    stale = [u for u in readers if a.stale(u)]
    if stale:
        out.append(risk(sens, f"{plural(len(stale), 'disabled or dormant user')} can still read it", len(stale), who,
                        ["User", "Status"], [(u, a.status(u)) for u in stale]))
    q = o.lower()  # the findings Risks & fixes lists for q=<object>: about it, or naming it
    out.append(findings_risk([S["rows"][i] for i, x in enumerate(rule_index()) if q in x["text"]], link("Findings", "rules", q=o, sev="all")))
    adm = a.admin_readers(o, a.READ_PRIVS) if a.is_data(k) and not readers else {}
    if adm:
        out.append(risk(False, f"Only admin roles reach it ({plural(len(adm), 'user')}): no other role grants it", len(adm), who))
    r = last_use().get(o)
    if r and a.use_state()[0] and r[8] >= UNUSED and (r[4] is None or r[4] > UNUSED) and len(readers) >= WIDE:
        out.append(risk(False, f"Not used in {UNUSED} days, yet {plural(len(readers), 'user')} can read it", len(readers),
                        link("Activity", "object", name=o, show="activity")))
    return ranked(out)


def home_page(p, view):
    """Home: the default (or own) user's ladder counts, account risks by severity, data protection tiles."""
    me = (a.users[0] if a.users else None) if view == "mine" else None  # shared: nobody until one is picked
    mine = None
    if me:
        counts = a.cached(("home", me), lambda: a.ladder_counts(a.access_objects(a.grants(me, True), True)))
        mine = dict(user=me, counts=counts)
    if view != "shared":
        return dict(view=view, me=mine, risks=None, counts=home_summary()["counts"], per_rule=None, skipped=None, protection=None, cards=None)
    h = home_summary()
    return dict(view=view, me=mine, risks=h["risks"], counts=h["counts"], per_rule=h["per_rule"], subjects=h["subjects"],
                act_first=h["act_first"], rule_sev=h["rule_sev"],
                skipped=a.skipped_rules(),  # HIERARCHY=0 / ACTIVITY=0: not in the counts
                protection=h["protection"], cards=home_cards())


def home_summary():
    """Home's numbers once per data set, one pass over the findings: per severity, per rule, the distinct unmasked
    sensitive columns (rule 6) and the dormant readers (rule 7); per severity the distinct people and roles, and the
    rules to act on first (Critical, biggest first, then masking (rule 6), then High). The
    row-policy tables are listed on Sensitive data."""
    def make():
        sev, per_rule, unmasked, dormant, n6 = dict.fromkeys(SEVS, 0), {}, set(), set(), 0
        who, per = {v: (set(), set()) for v in SEVS}, {}  # severity -> (people, roles); (severity, rule) -> grantees
        for x in S["rows"]:
            sev[x["severity"]] = sev.get(x["severity"], 0) + 1
            per_rule[x["num"]] = per_rule.get(x["num"], 0) + 1
            if x["kind"] != "object":
                who[x["severity"]][x["kind"] != "user"].add(x["grantee"])
            per.setdefault((x["severity"], x["num"]), []).append(x)
            if x["num"] == "6":
                n6 += 1
                unmasked.add((x["grantee"], x["detail"].split(" ")[1].rstrip(":")))
            elif x["num"] == "7":
                dormant.add(x["grantee"])
        g, um, dm = a.governance_kpis(), sorted(unmasked), sorted(dormant)
        big = sorted((k for k in per if k[0] in ("Critical", "High")), key=lambda k: (SEV_RANK[k[0]], -len(per[k]), int(k[1])))
        mask = sorted((k for k in per if k[1] == "6"), key=lambda k: SEV_RANK[k[0]])[:1]
        top = [k for k in big if k[0] == "Critical" and k not in mask] + mask + [k for k in big if k[0] == "High" and k not in mask]
        first = [dict(num=n, severity=v, title=a.RULES[n][0], findings=len(per[(v, n)]),
                      names=[dict(id=a.uid(x["grantee"], x["kind"] == "user"), kind=norm(x["kind"]))
                             for x in list({(x["grantee"], x["kind"]): x for x in per[(v, n)]}.values())[:NAMES]],
                      subjects=len({(x["grantee"], x["kind"]) for x in per[(v, n)]})) for v, n in top[:ACT_FIRST]]
        rule_sev = {}
        for (v, n), xs in per.items():
            rule_sev.setdefault(v, {})[n] = len(xs)
        return dict(risks=sev, per_rule=per_rule, act_first=first, rule_sev=rule_sev,
                    subjects={v: dict(people=len(p), roles=len(r)) for v, (p, r) in who.items()},
                    counts=dict(users=len(a.users), roles=len(a.roles), objects=len(a.objects), sensitive=len(S["sens"])),
                    protection=dict(unmasked=n6, unmasked_names=[dict(object=o, column=k) for o, k in um[:NAMES]],
                                    unmasked_columns=len(um), dormant=len(dm), dormant_names=dm[:NAMES],
                                    tagged=g["tagged_objects"], masked=g["masked_columns"], row_tables=g["row_tables"]))
    return a.cached("home_summary", make)


ACT_FIRST = 5  # rules Home's Risks card names first
TOP_TYPES = 6  # object types Home names; the rest are one Other
DAYS = 60  # days of activity Home draws


TOP_BIG = 6  # Home's Biggest schemas card: bars per switch


def home_cards():
    """Home's area cards once per data set: admin holders by admin role, stale people by status (of all with that
    status), users by status and type, roles by kind, objects by type, chain depth, biggest schemas, daily queries and What changed counts when that diff is already made (Home
    never compares)."""
    def holder(x):
        return dict(user=x["user"], role=(x["roles"] or ["account privilege"])[0],
                    login=x["status"] if x["status"] in ("disabled", "never") else str(x["last_login"])[:10])

    def make():
        adm, stale = admin_list(), [x["user"] for x in stale_list()]
        by_role = Counter(r for x in adm for r in x["roles"])
        types = Counter(a.kinds.get(o) or "OTHER" for o in a.objects).most_common()
        ok, reason = a.act_state()
        status = dict(Counter(a.status(u) for u in a.users))
        inside = [a.split_name(o) for o in a.objects if a.kinds[o] not in ("SCHEMA", "DATABASE") and not a.kinds[o].startswith("FUTURE")]
        sc, db = Counter(f"{b}.{s}" for b, s, _ in inside if s), Counter(b for b, _, _ in inside if b)
        days, use = {}, a.object_activity()
        for x in a.acts:
            d = str(a.day(x["DAY"]))
            days[d] = days.get(d, 0) + int(x["QUERIES"] or 0)
        return dict(
            admins=dict(total=len(adm), service=sum(x["service"] for x in adm),
                        by_role=[dict(role=r, people=n) for r, n in by_role.most_common()],
                        account_only=sum(not x["roles"] for x in adm),
                        names=[holder(x) for x in adm[:NAMES]],
                        service_names=[holder(x) for x in adm if x["service"]][:NAMES]),  # Home: service users with admin
            readers=sens_readers_by(),
            stale=dict(total=len(stale), by_status=dict(Counter(a.status(u) for u in stale)), of_status=status, names=stale[:NAMES]),
            people=dict(by_status=status, service=sum(map(a.is_service, a.users))),
            roles=dict(Counter(a.role_kind(r) for r in a.roles)),
            objects=dict(by_type=[dict(type=t, n=n) for t, n in types[:TOP_TYPES]]
                         + ([dict(type="Other", n=sum(n for _, n in types[TOP_TYPES:]))] if types[TOP_TYPES:] else [])),
            depth=a.depth_counts(),
            biggest=dict(schemas=[dict(name=n, n=k) for n, k in sc.most_common(TOP_BIG)],
                         databases=[dict(name=n, n=k) for n, k in db.most_common(TOP_BIG)], n_schemas=len(set(sc) | {o for o in a.objects if a.kinds[o] == "SCHEMA"}),
                         n_databases=len(set(db) | {o for o in a.objects if a.kinds[o] == "DATABASE"})),
            activity=dict(ok=ok, reason=reason, users=len({x["USER_NAME"] for x in a.acts}),
                          daily=[dict(day=d, queries=days[d]) for d in sorted(days)[-DAYS:]]),
            objuse=dict(ok=a.use_state()[0], notes=use["notes"], new=use["new"], days=90,
                        unused=sum(b["180"] + b["none"] for b in use["types"].values()),  # not used in 90 days (history 90+ only)
                        unused_new=sum(r[6] and r[8] >= 90 and (r[4] is None or r[4] > 90) for r in use["rows"]),
                        types=[dict(type=t, buckets=b) for t, b in use["types"].items() if b["nodata"] < sum(b.values())][:TOP_TYPES],
                        nodata=sorted(t for t, b in use["types"].items() if b["nodata"] == sum(b.values())),
                        read_only=use["patterns"][90]["read_only"], write_only=use["patterns"][90]["write_only"]))
    out = a.cached("home_cards", make)
    d = next((v for k, v in reversed(a.memo.items()) if isinstance(k, tuple) and k[0] == "diff"), None)  # the newest
    if d:
        return out | dict(changes=dict(counts=a.event_counts(d["events"]), high=d["high"], before=d["runs"]["before"], reason=None))
    kept = MODE == "fake" or (not a.INSIDE and cache.local() and cache.file(KEY).with_suffix(".prev.pkl").is_file())
    return out | dict(changes=dict(counts=None, high=0, before=None, reason=None if kept else no_prev()))


def sens_readers_by():
    """Who can read sensitive data, each user once: {active, risky (dormant, disabled or never logged in, admins too),
    admin, service: users}."""
    if not S["sens"]:
        return {}
    by = {g: set(us) for g, _, us in a.flow_sets(None)["groups"]}
    idle = {u for us in by.values() for u in us if a.status(u) != "active" and not a.is_service(u)}
    risky = by.pop("risky", set()) | idle
    return {g: len(us - risky) for g, us in by.items()} | dict(risky=len(risky))


def no_prev():
    """Why What changed has no earlier snapshot to compare with."""
    return ("Inside Snowflake the app keeps its data in memory only, so there is no earlier snapshot to compare with. "
            "Use the local version, which keeps the previous snapshot in .cache/." if a.INSIDE else
            "No earlier snapshot yet: the app keeps the previous one in .cache/ when a refresh (Read Snowflake again "
            "or Rebuild snapshot) brings a new one. Refresh after the next snapshot run, then come back."
            if cache.HOURS > 0 else "CACHE_HOURS=0 keeps nothing on disk, so there is no earlier snapshot.")


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
                                             "roles on Risks & fixes for who holds the other admin roles.")
        raise ApiError(404, "not_found", f"{name} is not in this snapshot")
    limit = depth_of(p)
    key = ("role_ctx", name, limit, p.get("schema", ""), flag(p, "sensitive"), p.get("otype", ""), flag(p, "users"))
    return a.cached(key, lambda: dict(role_rows(p, name, limit), key=key))


def role_rows(p, r, limit):
    """role_ctx without the cache (the page, its tables and its tab diagrams all ask)."""
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


def role_up(c):
    """(held by rows drawn, read-only roles that write) of the Role page, once per data set and filters."""
    def make():
        full = a.held(c["r"], c["limit"])
        return [x for x in full if x["kind"] == "user"] if c["only_users"] else full, a.readonly_writes(c["r"])
    return a.cached(("role_up", c["key"]), make)


def role_graph(p, c, up, ro, only=None):
    """The Role page diagram: who holds r (up; a crowded people lane folds into one box), r, then everything r reaches
    (boxes opened via graph?of=role&group=)."""
    r, every, admin_role = c["r"], c["every"], c["admin_role"]
    lanes, edges, notes, sel = a.role_graph(r, up, ro)
    above = {n for _, ns in lanes[:sel] for n in ns}
    lanes = [(lab.replace("Depth ", "Held by · D"), ns) for lab, ns in lanes[:sel]] + [lanes[sel]]
    edges = [x for x in edges if len(x) == 2 and x[0] in above]
    ig = None if admin_role else input_graph(r, False, every, c["scope"] or None, p.get("otype") or None, full=flag(p, "full"), lean=flag(p, "lean"))
    info, kinds, gx, types, header, level, note = a.graph_info(lanes, edges), {}, {}, {}, "", "object", None
    if ig:
        g = ig["g"]
        held = info
        info = {k: dict(v) for k, v in g["info"].items()}  # ig is kept for the next request: merged into a copy
        for k, v in held.items():
            x = info.setdefault(k, {})
            x["rules"] = sorted(set(x.get("rules", [])) | set(v.get("rules", [])), key=lambda t: int(t[0]))
        lanes += [(lab.replace("Depth ", "Holds · D"), ns) for lab, ns in g["lanes"][1:]]
        edges += g["edges"]
        notes = notes | g["notes"]
        kinds, gx, types, header, level, note = g["kinds"], ig["gx"], g.get("types"), g["header"], ig["level"], ig["note"]
    return build_graph("Held by (up) and holds (down)", lanes, edges, notes, info, kinds, selected=r, header=header,
                       level=level, note=note, full=bool(ig and ig["full"]), bad={x["holder"] for x in ro}, types=types,
                       gx=gx, src=gsrc(p, of="role", name=r), only=only, focus=p.get("focus"))


MAX_HELD = 50  # Role page, held by: rows of each kind sent with the page (its small diagram); the table pages them


def held_rows(p, c):
    """Role page, held by: one row per user or role that gets the role, with what revoking cut= would take away;
    once per data set, role filters and cut."""
    r = c["r"]
    direct = sorted(set(a.held_by.get(r, [])) | {a.uid(u, True) for u in a.users_of.get(r, [])})
    cut = p.get("cut", "")
    cut = cut if cut in direct else ""

    def make():
        up, _ = role_up(c)
        loses, lost, revoke = {}, set(), None
        if cut:
            for x in up:
                if all((cut, r) in zip(q, q[1:]) for q in x["paths"]):
                    lost.add((x["grantee"], x["kind"]))
                    if x["kind"] == "user":
                        loses[x["grantee"]] = a.loses(x["grantee"], a.node_name(cut), r)
            iac, sql = a.fix_text([a.role_edge(a.node_name(cut), r, a.node_kind(cut) == "user")])
            revoke = dict(grantee=a.node_name(cut), lost=len(lost), users=len(loses), iac=iac, sql=sql)
        rows = [dict(grantee=x["grantee"], id=a.uid(x["grantee"], x["kind"] == "user"), kind=norm(x["kind"]),
                     kind_label=kind_label(x["grantee"], x["kind"]),
                     status=a.status(x["grantee"]) if x["kind"] == "user" else None, depth=x["depth"],
                     used=sum(int(y["QUERIES"] or 0) for y in a.used.get(x["grantee"], []) if y["NAME"] == r and y["KIND"] in ("ROLE", "SECONDARY ROLE"))
                     if x["kind"] == "user" and a.used else None,  # queries with this role; None: a role, or no query history
                     direct=x["direct"], only_via=x["only_via"], path=x["path"], count=x["count"],
                     # no grantee picked: a direct holder loses the role when its own grant is its only path
                     loses_it=(x["grantee"], x["kind"]) in lost if cut else x["direct"] and x["count"] == 1,
                     loses=loses.get(x["grantee"], [])) for x in up]
        return dict(rows=rows, revoke=revoke)
    return dict(a.cached(("held_rows", c["key"], cut), make), direct=direct, cut=cut)


def revoke_text(r):
    """The If revoked column of held by (web/src/pages/Role.tsx revokeText)."""
    if r["loses_it"]:
        return f"loses {len(r['loses'])} privilege(s)" if r["loses"] else "loses access"
    if r["direct"]:
        return f"keeps it: {r['count'] - 1} other path{'' if r['count'] == 2 else 's'}"
    return f"only via {', '.join(r['only_via'])}" if r["only_via"] else "keeps it other ways"


HELD_SORT = {"g": lambda r: r["grantee"], "k": lambda r: r["kind_label"], "s": lambda r: r["status"] or "",
             "d": lambda r: r["depth"], "n": lambda r: r["count"], "u": lambda r: -1 if r["used"] is None else r["used"], "l": revoke_text, "path": lambda r: " > ".join(r["path"])}


def held_tab_rows(p, view):
    """The held by rows of one tab (tab=users|roles|all), filtered (q=) and sorted (sort=, dir=)."""
    c = role_ctx(p, view)
    h = held_rows(p, c)
    t = p.get("tab", "all")
    rows = [x for x in h["rows"] if t == "all" or (x["kind"] == "user") == (t == "users")]
    words = p.get("q", "").lower().split()
    if words:
        text = lambda r: " ".join([r["grantee"], r["kind_label"], r["status"] or "", str(r["depth"]), str(r["count"]),
                                   revoke_text(r), *r["path"]]).lower()
        rows = [r for r in rows if all(w in text(r) for w in words)]
    if p.get("sort"):
        rows = sorted(rows, key=HELD_SORT.get(p["sort"], HELD_SORT["d"]), reverse=p.get("dir") == "-1")
    return c, rows


def held_page(p, view):
    """Role page, held by, paged on the server (web/API.md GET /api/held)."""
    _, rows = held_tab_rows(p, view)
    off, lim, page = paged(p, rows)
    return dict(rows=page, total=len(rows), offset=off, limit=lim)


def held_csv(p, view):
    c, rows = held_tab_rows(p, view)
    cols = ["Grantee", "Kind", "Status", "Depth", "Paths", "Queries with it", "If revoked", "Path"]
    out = [[r["grantee"], r["kind_label"], r["status"] or "", r["depth"], r["count"], "" if r["used"] is None else r["used"], revoke_text(r), " > ".join(r["path"])]
           for r in rows]
    return f"{c['r']}_held_by_{p.get('tab', 'all')}.csv", csv_text(cols, out)


def role_page(p, view):
    c = role_ctx(p, view)
    r, limit, scope, every, admin_role = c["r"], c["limit"], c["scope"], c["every"], c["admin_role"]
    s, hold = a.cached(("role_stats", r, limit), lambda: a.role_stats(r, limit)), a.holds_of(r)
    up, ro = role_up(c)
    if scope:
        hold = [h for h in hold if a.in_scope(h, scope)]
    owner = [g for g, pv, t in a.on.get(r, []) if pv == "OWNERSHIP" and t == "ROLE"]
    admin, acct = a.admin_paths(r), a.account_privs(r)
    findings, total, sev = findings_of(r, False, {"17"} if ro else ())
    banners = []
    if p.get("schema") and not scope:
        banners.append(banner("info", f"{p['schema']} is not reached by {r}", ["Showing all of its access."]))
    if admin_role:
        n = len(a.admin_below(r)) - 1
        banners.append(banner("bad", f"Admin role: {a.ADMIN_POWER[r]} (hierarchy hidden)", [
            f"It reaches {plural(n, 'role')} and {plural(len(a.admin_objects(r)), 'object')} through the roles granted to it; "
            "they are not listed here." if n else "No role is granted to it: it reads no data through other roles."],
            [link("People with admin roles", "rules")]))
    sc = [x for x in every if a.in_scope(x, scope)]
    graph = role_graph(p, c, up, ro)
    h = held_rows(p, c)
    direct, cut = h["direct"], h["cut"]
    us = [x for x in h["rows"] if x["kind"] == "user"]
    rs = [x for x in h["rows"] if x["kind"] != "user"]
    # holds as a has / lacks grid
    objs = {}
    for x in hold:
        if not x["type"].startswith("FUTURE") and x["type"] != "ACCOUNT":
            objs.setdefault(x["object"], x)
    other = [x for x in hold if x["object"] not in objs]
    direct_pv = {(x["object"], x["privilege"]) for x in hold}
    hl = {o: a.has_lacks(r, o) for o in objs}
    gaps = sorted({pv for x in hl.values() for pv in x["lacks"]})
    lack = p.get("lacks", "")
    lack = lack if lack in gaps else ""
    shown = [o for o in objs if not lack or lack in hl[o]["lacks"]]

    def cell(o, pv):
        x = hl[o]
        return ("direct" if (o, pv) in direct_pv else "inherited" if pv in x["has"] else "owner" if pv in x["implied"]
                else "lacks")

    types_, ts = [], sorted({objs[o]["type"] for o in shown}, key=lambda t: (type_rank(t), t))
    active = p.get("htype") if p.get("htype") in ts else ts[0] if ts else ""
    for t in ts:  # one page of the open type's rows (htype=, h_offset=, limit=): a big role holds 100k objects
        cols, os_ = a.valid_privs(t), [o for o in shown if objs[o]["type"] == t]
        w, h_off = window(p, "h_offset", len(os_)) if t == active else (slice(0, 0), 0)
        types_.append(dict(type=t, privs=cols, count=len(os_), offset=h_off,
                           rows=[dict(object=o, name=objs[o]["name"], cells={pv: cell(o, pv) for pv in cols}, text=hl[o]["text"])
                                 for o in os_[w]]))
    acc = account(admin, acct)
    ow, o_off = window(p, "o_offset", len(other))  # account and future grants: thousands on a big role
    ro_rows = [dict(object=x["object"], privileges=x["privileges"], holder=x["holder"], inherited=x["inherited"],
                    how=x["how"], read_only=x["read_only"], objects=x["objects"]) for x in ro]
    eff = c["eff"]
    return dict(
        view=view, role=dict(id=r, name=r, kind=nk(r), owner=owner, admin=admin_role),
        filters=dict(depth=limit, users=c["only_users"], sensitive=c["only_sens"], schema=scope,
                     otype=p.get("otype", ""), cut=cut, lacks=lack, cuts_total=len(direct), gaps=gaps),
        kpis=dict(privileges=s["privileges"], future=s["future"], effective=s["effective"], above=s["above"],
                  above_direct=s["above_direct"], users=s["users"], users_direct=s["users_direct"],
                  farthest=s["farthest"], sensitive=s["sensitive"], holds_roles=s["holds_roles"]),
        scope_kpis=dict(direct=len(hold), effective=len(sc), objects=len({x["object"] for x in sc}),
                        holders=len({x["holder"] for x in sc}), sensitive=len({x["object"] for x in sc if x["object"] in S["sens"]}))
        if scope else None,
        risks=subject_risks(r, False), banners=banners, findings=findings, findings_total=total, findings_sev=sev, usage=role_usage(r), readonly_writes=ro_rows, account=acc, graph=graph,
        held_by=dict(rows=us[:MAX_HELD] + rs[:MAX_HELD], total=len(h["rows"]), users=len(us), roles=len(rs),
                     revoke=h["revoke"]),
        holds=dict(types=types_, other=[dict(privilege=x["privilege"], cls=x["cls"], type=x["type"], object=x["object"],
                                             name=x["name"]) for x in other[ow]], other_total=len(other), other_offset=o_off,
                   count=len(hold), objects=len(objs)),
        tabs=a.cached(("role_tabs", c["key"]), lambda: tab_list(eff, [], c["held"], acc)),
        roles=[reach_row(x) for x in c["held"]],
        can_read=sees(p, [v for v in a.data_views(r, False) if not scope or v["object"] in {x["object"] for x in eff}])
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
    sp = a.split_users(a.readers(o), a.admin_readers(o, a.READ_PRIVS))
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
            semantic=", ".join(v or "" for t, v in ct if t.upper().endswith("SEMANTIC_CATEGORY")),
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


def object_ctx(p, view):
    """The object, its filters, matrix rows, grantees and graph input, once per data set and filter set (the page, its
    graph and its grantee tables all ask)."""
    need(a.kinds, "No objects in this data.")
    name = p.get("name") or next((x for x in a.objects if a.kinds[x] == (p.get("type") or "TABLE")), a.objects[0])
    need(name in a.kinds, f"{name} is not in this snapshot")
    o, t = name, a.kinds[name]
    pv, active, only_users = p.get("priv", ""), flag(p, "active"), flag(p, "users")
    key = ("object_ctx", o, pv, active, only_users)
    return a.cached(key, lambda: dict(object_rows(o, t, pv, active, only_users), key=key))


def object_rows(o, t, pv, active, only_users):
    m = [x for x in a.matrix(o, t, priv=pv or None) if not (active and x["status"] == "disabled")]
    g = [x for x in a.grantees(o, t) if not pv or x["privilege"] == pv]
    users = sorted({x["grantee"] for x in g if x["kind"] == "user" and a.from_user(x["path"])
                    and not (active and a.is_disabled(x["grantee"]))})
    keep = set(users)
    shown = [x for x in g if x["kind"] != "user" or x["grantee"] in keep]
    if only_users:
        shown = [x for x in shown if x["grantee"] in keep]
    merged = {}
    for x in shown:
        merged.setdefault((x["grantee"], x["kind"], tuple(x["path"])), []).append(x)
    grantees = [dict(grantee=k[0], id=a.uid(k[0], k[1] == "user"), kind=norm(k[1]), kind_label=kind_label(k[0], k[1]),
                     status=a.status(k[0]) if k[1] == "user" else None,
                     privileges=[dict(privilege=y["privilege"], cls=y["cls"], tab=grantee_tab(y["privilege"], t)) for y in v],
                     tabs=sorted({grantee_tab(y["privilege"], t) for y in v}), depth=v[0]["depth"], path=list(k[2]),
                     count=max(y["count"] for y in v)) for k, v in merged.items()]
    return dict(o=o, t=t, pv=pv, active=active, only_users=only_users, m=m, users=users, shown=shown, grantees=grantees,
                stats=a.object_stats(o, t, pv or None))


def object_graph(p, c, only=None):
    """The Object page diagram: who comes in (a crowded people lane folds into one box: PUBLIC brings every user), the
    roles on the way, the object; boxes opened through graph?of=object&group=."""
    og = a.cached(("object_graph", c["key"]), lambda: a.object_graph(c["o"], c["t"], c["shown"], c["users"]))
    return og and build_graph("Paths into the object", og[0], og[1], og[2],
                              src=gsrc(p, of="object", name=c["o"], **{k: p[k] for k in ("active",) if p.get(k)}), only=only,
                              focus=p.get("focus"))


RANK = {k: i for i, k in enumerate(("use", "read", "manage", "write", "own", "admin"))}  # Grantees.tsx RANK
BAD = ("disabled", "dormant", "never", "active")
MAX_CHIPS = 100  # people listed in one grantee group (its count covers them all)
GRANTEE_SORT = {"g": lambda r: r["grantee"], "k": lambda r: r["kind_label"], "s": lambda r: r["status"] or "",
                "p": lambda r: ", ".join(x["privilege"] for x in r["privileges"]), "d": lambda r: r["depth"],
                "n": lambda r: r["count"], "path": lambda r: " > ".join(r["path"])}


def grantee_tab_rows(p, view):
    """The Object page's grantee rows of one tab (tab=, "all" by default), filtered (q=: every word in some column)
    and sorted (sort= a column key, dir=1|-1)."""
    c = object_ctx(p, view)
    t = p.get("tab", "all")
    rows = c["grantees"] if t == "all" else [x for x in c["grantees"] if t in x["tabs"]]
    words = p.get("q", "").lower().split()
    if words:
        text = lambda r: " ".join([r["grantee"], r["kind_label"], r["status"] or "", str(r["depth"]), str(r["count"]),
                                   *(x["privilege"] for x in r["privileges"]), *r["path"]]).lower()
        rows = [r for r in rows if all(w in text(r) for w in words)]
    if p.get("sort"):
        rows = sorted(rows, key=GRANTEE_SORT.get(p["sort"], GRANTEE_SORT["d"]), reverse=p.get("dir") == "-1")
    return c, rows


def grantee_groups(rows):
    """Users who come in through the same chain with the same privileges as one group, every role its own group, as
    web/src/components/Grantees.tsx groupGrantees: most users first; people listed up to MAX_CHIPS, problems first."""
    out = {}
    for r in rows:
        user = r["kind"] == "user"
        privs = [x["privilege"] for x in r["privileges"]]
        k = f'{">".join(r["path"][1:])}|{",".join(privs)}' if user else f'role:{r["id"]}'
        g = out.get(k)
        if g is None:
            g = out[k] = dict(key=k, entry=(r["path"][1] if len(r["path"]) > 1 else r["grantee"]) if user else r["grantee"],
                              chain=r["path"][1:] if user else r["path"], users=[], count=0, role=None if user else r,
                              privileges=privs, depth=r["depth"], status={},
                              cls=max((x["cls"] for x in r["privileges"]), key=lambda c: RANK.get(c, 0), default="use"))
        if user:
            st = r["status"] or "active"
            g["users"].append(r)
            g["count"] += 1
            g["status"][st] = g["status"].get(st, 0) + 1
    gs = sorted(out.values(), key=lambda g: (g["role"] is not None, -g["count"], g["depth"]))
    rank = lambda u: (BAD.index(u["status"]) if u["status"] in BAD else 3, u["grantee"])
    for g in gs:
        g["users"] = [dict(grantee=u["grantee"], id=u["id"], status=u["status"])
                      for u in sorted(g["users"], key=rank)[:MAX_CHIPS]]
    return gs


def grantees_page(p, view):
    """Object page, who has access, paged on the server (web/API.md GET /api/grantees): by=rows one row per grantee
    and chain, by=groups the groups of grantee_groups and how many users and roles they hold."""
    c, rows = grantee_tab_rows(p, view)
    if p.get("by") == "groups":
        gs = a.cached(("grantee_groups", c["key"], p.get("tab", "all"), p.get("q", "")), lambda: grantee_groups(rows))
        off, lim, page = paged(p, gs)
        us = sum(r["kind"] == "user" for r in rows)
        return dict(rows=page, total=len(gs), offset=off, limit=lim, users=us, roles=len(rows) - us)
    off, lim, page = paged(p, rows)
    return dict(rows=page, total=len(rows), offset=off, limit=lim)


def grantees_csv(p, view):
    c, rows = grantee_tab_rows(p, view)
    cols = ["Grantee", "Kind", "Status", "Privileges", "Depth", "Paths", "Shortest path"]
    out = [[r["grantee"], r["kind_label"], r["status"] or "", ", ".join(x["privilege"] for x in r["privileges"]),
            r["depth"], r["count"], " > ".join(r["path"])] for r in rows]
    return f"{c['o'].split('.')[-1]}_grantees_{p.get('tab', 'all')}.csv", csv_text(cols, out)


MAX_ADMIN_PATHS = 20  # Object page banner: admin paths listed per admin role (the counts cover every admin user)
WRITES = ("OWNERSHIP", "INSERT", "UPDATE", "DELETE", "TRUNCATE")  # Users × privileges: red for a person on sensitive data (rule 10)
ADMIN_ORDER = ["ACCOUNTADMIN", "ORGADMIN", "SECURITYADMIN", "SYSADMIN", "USERADMIN"]


def admin_roles(adm):
    """Admin paths grouped by the admin role they end at, strongest first: users and paths counted, the first 3 users
    and MAX_ADMIN_PATHS paths sent."""
    by = {}
    for q in adm:
        by.setdefault(q[-1], []).append(q)
    rank = lambda r: (ADMIN_ORDER.index(r) if r in ADMIN_ORDER else len(ADMIN_ORDER), r)
    out = []
    for r, qs in sorted(by.items(), key=lambda x: rank(x[0])):
        us = list(dict.fromkeys(q[0] for q in qs))
        out.append(dict(role=r, users=len(us), first=us[:3], paths=qs[:MAX_ADMIN_PATHS], total=len(qs)))
    return out


def object_page(p, view):
    c = object_ctx(p, view)
    o, t, pv, active, only_users, m, s = c["o"], c["t"], c["pv"], c["active"], c["only_users"], c["m"], c["stats"]
    via = a.admin_readers(o, None, t)  # the admin users whose admin roles reach o through their real links
    adm = [q for q in a.cached("admin_from_user", lambda: [q for x, q in a.admin_holders() if a.from_user(q)])
           if q[-1] in via.get(q[0], [])]
    real = [x for x in m if not x["admin"] or x["via"]]
    n_cls = {k: sum(k in x["via"] for x in real) for k in ("read", "write", "own")}
    data = a.is_data(t)
    scols = a.sensitive_cols(o) if data else []
    rpol = a.policies_of(o)["rows"] if data else []
    rows, mw = [], window(p, "m_offset", len(m))
    for x in m[mw[0]]:
        u = x["user"]
        isreal = any((v["has"] or v["owner"]) and not v["admin"] for v in x["privs"].values())
        ds = [v["depth"] for v in x["privs"].values() if v["has"]]
        n = max((v["count"] for v in x["privs"].values()), default=0)
        best = min((v["path"] for v in x["privs"].values() if v["has"]), key=len, default=None)
        aps = a.admin_paths(u, True) if x["admin"] else []
        reads = any(x["privs"].get(k, {}).get("has") or x["privs"].get(k, {}).get("owner")
                    for k in a.READ_PRIVS if k in x["privs"])
        dv = a.data_view(u, o, True) if reads and (scols or rpol) else None
        col_of = {k["column"]: k for k in dv["columns"]} if dv else {}
        typ = str((a.profile.get(u) or {}).get("TYPE") or "PERSON")
        flags = {"status": f"{x['status'].capitalize()} user who can still read this object"} if (
            x["status"] in ("disabled", "dormant") and reads) else {}
        if o in S["sens"] and "SERVICE" not in typ:
            flags |= {k: f"A person can {'own' if k == 'OWNERSHIP' else 'change'} this sensitive object"
                      for k in WRITES if x["privs"].get(k, {}).get("has")}
        rows.append(dict(
            user=u, type=typ, status=x["status"], admin=x["admin"], unknown=x["unknown"], flags=flags,
            real=isreal, cells={k: {f: v[f] for f in ("has", "owner", "depth", "count", "title", "admin")}
                                for k, v in x["privs"].items()},
            seen={k: col_of.get(k) or dict(state="clear", reason="no masking policy") for k in scols} if dv else {},
            rows_state=dv["rows"] if dv and rpol else None, via=via_groups(x), depth=min(ds) if ds else None, paths=n,
            path=best, admin_paths=aps if x["admin"] else []))
    tabs = {}
    for x in c["grantees"]:
        for k in x["tabs"]:
            tabs[k] = tabs.get(k, 0) + 1
    sees = None
    shared = view == "shared"
    ps = a.policies_of(o)
    if shared and data and (ps["rows"] or ps["columns"] or a.sensitive_cols(o)):
        rs = sorted({x for r, q_pv, _ in a.on.get(o, []) if q_pv in a.READ_PRIVS for x in a.ups(r)[0]})
        vs = [a.data_view(r, o, False) for r in rs]
        sees = dict(cols=[k["column"] for k in vs[0]["columns"]] if vs else [], row_policy=bool(ps["rows"]),
                    rows=[dict(role=v["name"], rows=v["rows"], columns=v["columns"]) for v in vs])
    db, sc, nm = a.split_name(o, t)
    us = sum(x["kind"] == "user" for x in c["grantees"])
    return dict(
        view=view, object=dict(id=o, type=t, database=db, schema=sc, name=nm, sensitive=o in S["sens"],
                               privileges=a.valid_privs(t)),
        filters=dict(type=t, priv=pv, active=active, users=only_users),
        kpis=dict(people=len(s["people"]), disabled=len(s["disabled"]), service=len(s["service"]), admin=len(s["admin"]),
                  read=n_cls["read"], write=n_cls["write"], own=n_cls["own"], roles=s["roles"], direct=s["direct"],
                  owners=s["owners"], deployers=s["deployers"], owner_note=s["owner_note"], longest=s["longest"]),
        admin_roles=admin_roles(adm), admin_users=len({q[0] for q in adm}), admin_total=len(adm),
        sensitivity=sensitivity(o) if shared else None,
        matrix=dict(privs=list(m[0]["privs"]) if m else [], sensitive_cols=scols, row_policy=bool(rpol), rows=rows,
                    total=len(m), offset=mw[1]),
        graph=object_graph(p, c), sees=sees,
        tabs=[dict(key=k, label=lab, count=tabs[k]) for k, lab in TABS if k in tabs] + [dict(key="all", label="All", count=len(c["grantees"]))],
        grantees=dict(total=len(c["grantees"]), users=us, roles=len(c["grantees"]) - us), capped=sorted(a.capped))


MAX_WHO = 200  # Who has access: people and roles sent, highest step first (q= finds the rest; counts cover all)
MAX_WHO_GROUPS = 100  # groups of people with the same route sent, biggest first


def need_object(o):
    """404 when o is not in the data; builtin_hidden when only Snowflake's built-in grants, left out, reach it."""
    if o not in a.kinds and any(g["OBJECT_NAME"] == o and g["GRANTED_ON"] not in a.ROLE_ON for g in a.hidden):
        raise ApiError(404, "builtin_hidden", f"{o} is reached only through Snowflake's built-in grants, which are hidden.")
    need(o in a.kinds, f"{o} is not in this snapshot")


def who_all(p, view):
    """Everything screen 2 shows of one object (or the admin preset), once per data set: the people (5,941 on a
    big account: PUBLIC reaches everyone) are walked, dressed and grouped once; who_page sends a part of them."""
    if p.get("preset") == "admin":
        o = None
    else:
        need(a.objects, "No objects in this data.")
        o = p.get("name") or next((x for x in a.objects if a.kinds[x] == "TABLE"), a.objects[0])
        need_object(o)
    return a.cached(("who_all", o), lambda: who_data(o, view))


def who_data(o, view):
    if o is None:
        w, t, cols, seen = a.admin_access(), None, [], {}
        head = dict(id=None, preset="admin", type="Admin roles", database=None, schema=None, name="Admin roles",
                    sensitive=False, tags=[], columns=0, masking=[], row_policies=[], owners=[], owner_note="")
    else:
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
    # active people first within a level: on a big account most holders never log in or are disabled
    w["people"] = sorted(w["people"], key=lambda x: (-a.OBJ_LEVELS.index(x["level"]), x["status"] != "active", x["name"]))
    for x in w["people"]:
        x["state"] = ("disabled" if x["status"] == "disabled" else "service" if a.is_service(x["name"])
                      else "active" if x["status"] == "active" else "dormant")
        x["id"] = a.uid(x["name"], True)
        x["login"], x["mark"] = login(x["name"])
        x["columns"] = seen.get(x["name"], [])
    did = {}
    if o and a.act_state()[0]:
        for r in a.acts:
            if r["OBJECT_NAME"] == o:
                did[r["USER_NAME"]] = did.get(r["USER_NAME"], 0) + int(r["QUERIES"] or 0)
    for x in w["people"]:
        x["queries"] = did.get(x["name"], 0) if o and a.act_state()[0] else None  # None: the activity is not read
    for x in w["people"] + w["roles"]:
        x.setdefault("blocked", None)
    for x in w["roles"]:
        x["kind"] = nk(x["name"])
    # blocked (the privilege without USAGE on the database or schema) are not readers: counted on their own
    levels = {lv: sum(x["level"] == lv and not x["blocked"] for x in w["people"]) for lv in a.OBJ_LEVELS[::-1]}
    return dict(o=o, head=head, people=w["people"], roles=w["roles"], groups=a.same_paths(w["people"]),
                used=a.used_by(o, {x["name"] for x in w["people"]}) if o and view == "shared" and a.act_state()[0] else None,
                app=a.app_exposure(o) if o and a.kinds.get(o) == "STREAMLIT" else None, columns=cols,
                counts=dict(levels=levels, blocked=sum(bool(x["blocked"]) for x in w["people"]),
                            people=len(w["people"]), roles=len(w["roles"]),
                            states=dict(Counter(x["state"] for x in w["people"])),
                            disabled=sum(x["status"] == "disabled" for x in w["people"]),
                            dormant=sum(x["status"] in ("dormant", "never") and not a.is_service(x["name"])
                                        for x in w["people"])))


def who_page(p, view):
    """Screen 2: who has access to one object (name=), or the Admin holders preset (preset=admin): people and roles at
    their highest step, people with the same route grouped, the object's tags and policies, and who sees each sensitive
    column unmasked. Big objects: the first MAX_WHO people and roles matching q= (plus as= and sel=) and the first
    MAX_WHO_GROUPS groups; shown counts the people and roles that match. used: users who used it though no grant
    reaches them (never in people or counts), null when the activity is not read."""
    x = who_all(p, view)
    q = p.get("q", "").lower()
    st = p.get("st") if p.get("st") in ("active", "dormant", "disabled", "service") else ""  # people: before the cap
    state = {e["name"]: e["state"] for e in x["people"]}
    ok = lambda n: q in n.lower() and (not st or state.get(n) == st)
    hit = lambda e: q in e["name"].lower()
    du = None if view == "shared" else (a.users[0] if a.users else None)  # shared: nobody until one is picked
    every = [g | dict(names=[n for n in g["names"] if ok(n)]) for g in x["groups"]]
    every = [g for g in every if g["names"]]
    who = {e["name"]: e for e in x["people"]}  # a group's facts count everyone in it, sent or not
    groups = [g | dict(off=sum(who[n]["status"] != "active" for n in g["names"]),
                       queries=sum(who[n]["queries"] or 0 for n in g["names"])) for g in every[:MAX_WHO_GROUPS]]
    people = [e for e in x["people"] if ok(e["name"])]
    roles = [e for e in x["roles"] if hit(e)]
    want = {p.get("as") or du, p.get("sel")} | {g["names"][0] for g in groups}
    sent = people[:MAX_WHO] + [e for e in x["people"] if e["name"] in want and e not in people[:MAX_WHO]]
    sel = [e for e in roles[MAX_WHO:] if e["name"] == p.get("sel")]
    o, ps = x["o"], a.policies_of(x["o"]) if x["o"] else None
    by_role = bool(o and view == "shared" and a.is_data(a.kinds[o]) and (ps["rows"] or ps["columns"] or a.sensitive_cols(o)))  # object_page's sees
    return dict(view=view, object=x["head"], by_role=by_role, risks=object_risks(x["o"]) if x["o"] else None, people=sent, roles=roles[:MAX_WHO] + sel, groups=groups,
                shown=dict(people=len(people), roles=len(roles), groups=len(every)), st=st,
                used=None if x["used"] is None else dict(days=a.ACTIVITY_DAYS, total=len(x["used"]), rows=x["used"][:MAX_WHO],
                                                         users=len({r["user"] for r in x["used"]})),
                app=x["app"], counts=x["counts"], columns=x["columns"], default_user=du,
                builtin=a.builtin_on(x["o"]) if x["o"] else None)


def who_csv(p, view):
    x = who_all(p, view)
    out = [[e["name"], e["status"], e["login"], e["level"], e["blocked"] or "", " ".join(e["privileges"]),
            " > ".join(e["path"]), e["ways"]] for e in x["people"]]
    return f"{(x['o'] or 'admin_roles').split('.')[-1]}_who.csv", csv_text(
        ["User", "Status", "Last login", "Access", "Blocked", "Privileges", "Path", "Ways"], out)


# ---------- can they ----------

ALL = "*"  # Can they?: every privilege on the object


def named(x, pool, what):
    """x as typed, else the name in pool equal to it ignoring case (Home's typed question: real names hold lower case)."""
    if not x or x in pool:
        return x
    return a.cached(("lower", what), lambda: {k.lower(): k for k in pool}).get(x.lower(), x)


def asker(p, view, key="role"):
    """Can they? / Request access subject: (name, user). A role from key= (role= on Can they?, for_role= on Request,
    where role= is the role to ask for), else a user from user= or name= (old links); a name that is no user but a
    role is that role (Home's typed question). My access: always the signed-in user."""
    mine = view == "mine"
    if not mine and p.get(key):
        r = named(p[key], a.roles, "roles")
        need(r in a.roles, f"{p[key]} is not in this snapshot")
        return r, False
    need(a.users, "No users in this data.")
    u = p.get("user") or p.get("name") or (a.users[0] if mine or DEMO_USER not in a.users else DEMO_USER)
    if not mine and u not in a.users:
        u = named(u, a.users, "users")
        if u not in a.users and named(u, a.roles, "roles") in a.roles:
            return named(u, a.roles, "roles"), False
    need(u in a.users, f"{u} is not in this snapshot")
    return u, True


def subject_of(u, user):
    """Who the question is about: kind (user or role kind), name, id (a.uid), user, people (users holding a role),
    database (of a database role, else None)."""
    return dict(kind="user" if user else nk(u), name=u, id=a.uid(u, user), user=user,
                people=None if user else len(a.ups(u)[1]), database=None if user else a.role_db(u))


MAX_WH = 10  # Can they?: warehouses named in the note under the answer


def does(pv):
    """"can SELECT", but "has USAGE on": a privilege whose name is no verb."""
    return f"can {pv}" if pv in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "MODIFY", "OPERATE", "MONITOR", "READ", "WRITE") else f"has {pv} on"


def check_page(p, view):
    """Can they? priv=USAGE on an object without USAGE of its own: USAGE on its database and schema (container_usage)."""
    r = check_object(p if p.get("priv") != "USAGE" else {**p, "priv": ""}, view)
    if p.get("priv") == "USAGE" and "USAGE" in r["privileges"]:  # a privilege of its own (an app, a warehouse): asked as it is
        r = check_object(p, view)
    r["not_applicable"] = sorted(set(a.priv_types()) - set(r["privileges"]) - ({"USAGE"} if r["usage"] else set()))
    if p.get("priv") in r["not_applicable"]:
        return r | not_applicable(r, p["priv"])
    if r["usage"] and "USAGE" not in r["privileges"]:
        r["privileges"].append("USAGE")
        if p.get("priv") == "USAGE":
            r |= container_usage(r, p.get("focus"))
    has = {x["privilege"] for x in r["held"] if x["held"]}
    r["access"] = dict(words=a.access_words(r["type"], has) if r["verdict"] in ("yes", "partly") else "",
                       share=a.can_share(r["user"], r["subject"]["user"], r["object"]) if has else {},
                       app=a.app_rights(r["object"]) if r["type"] == "STREAMLIT" and has and view != "mine" else None,
                       hidden=sorted(((a.app_exposure(r["object"]) or {}).get("exposed") or {}).get(r["user"], []))
                       if r["type"] == "STREAMLIT" and has and view != "mine" and r["subject"]["user"] else [],
                       days=a.ACTIVITY_DAYS, activity=a.act_state()[0])
    r["used_anyway"] = None
    if view != "mine" and r["verdict"] in ("no", "blocked") and a.act_state()[0]:  # evidence beside the grants, no verdict
        x = a.used_anyway(r["user"], r["subject"]["user"], r["object"], None if r["priv"] == ALL else r["priv"])
        r["used_anyway"] = dict(days=a.ACTIVITY_DAYS, total=len(x), queries=sum(g["queries"] for g in x),
                                last=max((g["last"] for g in x), default=""), rows=x[:MAX_WH])
    return r


def not_applicable(r, pv):
    """The answer for a privilege the object's type does not have: neither Yes nor No."""
    kind, ts = r["type"].lower(), sorted(t.lower() for t in a.priv_types()[pv])
    more = f" and {len(ts) - 6} more" if len(ts) > 6 else ""
    inside = " The Inside tab answers for the tables and views in it." if r["inside"] and pv in a.READ_PRIVS | a.WRITE_PRIVS else ""
    ans = dict(yes=False, how="none", tone=None, title=f"{pv} is not applicable to this object", stats=[],
               text=f"{pv} is not applicable to this {kind}: it is a privilege on {', '.join(ts[:6])}{more}.{inside}")
    return dict(priv=pv, answer=ans, verdict="na", paths=[], paths_total=0, owner=[], admin_paths=[], lanes=[], lanes_total=0,
                cut=[], cuts=[], options=[], choke=[], layers=None, read=None, nearest=[], nearest_own=None, narrow=None,
                blocked=[], unblock=None, graph=None, used_anyway=None, access=None)


def container_usage(r, focus):
    """The answer, paths and graph of USAGE on the object's database and schema, which Snowflake checks before any
    privilege on the object itself."""
    u, user, o = r["user"], r["subject"]["user"], r["object"]
    rs = {c: a.can(u, "USAGE", c, is_user=user) for _, c in a.containers(o, a.kinds[o])}
    ps = [q | dict(privilege="USAGE") for v in rs.values() for q in v["paths"]]
    own = list({tuple(q): q for v in rs.values() for q in v["owner"]}.values())
    adm = list({tuple(q): q for c in rs for q in a.admin_can(u, c, user, ["USAGE"])}.values())
    miss = [x for x in r["usage"] if not x["held"]]
    names = " and ".join(f"{x['type'].lower()} {x['name']}" for x in r["usage"])
    ans = dict(yes=not miss, how="paths" if not miss else "none", tone=None if not miss else "low",
               title="Yes, USAGE on its database and schema" if not miss else
               f"No USAGE on {' or '.join(x['type'].lower() + ' ' + x['name'] for x in miss)}",
               text=f"{u} has USAGE on {names}, so Snowflake lets statements on {o} through to its own privileges." if not miss
               else f"Snowflake refuses every statement on {o} until {u} has USAGE on {names}.",
               stats=[["Paths", sum(v["count"] for v in rs.values())], ["Missing USAGE", len(miss)]])
    g = ps and a.down_graph(u, [dict(privilege="USAGE", type=a.kinds[c], object=c, paths=[q["path"] for q in v["paths"]])
                                for c, v in rs.items() if v["paths"]], user=user)
    ls, _ = a.lanes(ps)
    return dict(priv="USAGE", answer=ans, verdict="yes" if not miss else "no", paths=ps, paths_total=sum(v["count"] for v in rs.values()), owner=own, admin_paths=adm, lanes=ls[:20],
                lanes_total=len(ls), cut=[], cuts=[], options=[], layers=None, read=None, nearest=[], nearest_own=None,
                narrow=None, held=[],
                graph=g and build_graph("Paths combined", g[0], g[1], g[2], focus=focus) or None)


def check_object(p, view):
    need(a.objects, "No objects in this data.")
    mine = view == "mine"
    u, user = asker(p, view)
    tables = [x for x in a.objects if a.is_data(a.kinds[x])]
    mine_rows = a.grants(u, user)  # once: a big account takes a second per walk
    o = named(p.get("obj"), a.kinds, "objects") or (p.get("on") if p.get("on") in a.kinds else next(
        (r["object"] for r in mine_rows if a.is_data(r["type"])), tables[0] if tables else a.objects[0]))
    need_object(o)
    opts = a.ask_privs(a.kinds[o])
    do = {"read": a.basic_priv(a.kinds[o]), "change": a.need_privs(a.kinds[o], "change")[0], "own": "OWNERSHIP"}
    pv = p.get("priv") if p.get("priv") in opts else do.get(p.get("do"), ALL)
    if pv == ALL:  # every privilege the user holds on o, each with its own paths
        held = list(dict.fromkeys(x["privilege"] for x in mine_rows if x["object"] == o))
        rs = {x: a.can(u, x, o, is_user=user) for x in held}
        r = (dict(next(iter(rs.values())), choke=[]) if rs else a.can(u, opts[0], o, is_user=user)) | dict(ask=[], options=a.removal(u, None, o, user) if rs and not mine else [], closest=None)
        r["paths"] = [q | dict(privilege=x) for x, v in rs.items() for q in v["paths"]]
        r["owner"] = list({tuple(q): q for v in rs.values() for q in v["owner"]}.values())
        r["choke"] = [c for c in (next(iter(rs.values()))["choke"] if rs else []) if all(c in v["choke"] for v in rs.values())]
        r["shortest"] = min((q["depth"] for q in r["paths"]), default=None)
        r["count"] = sum(v["count"] for v in rs.values())
        r["owner_count"] = max((v["owner_count"] for v in rs.values()), default=0)
    else:
        held, r = [pv], a.can(u, pv, o, is_user=user)
        r["paths"] = [q | dict(privilege=pv) for q in r["paths"]]
    ps, admin = r["paths"], a.admin_can(u, o, user, None if pv == ALL else [pv])  # through an admin role's real links
    power = "".join(f" {x} {a.ADMIN_POWER[x]}." for x in a.held_admin(u, user) if x not in {q[-1] for q in admin})
    what = (", ".join(held) if held else "anything") if pv == ALL else pv
    off = r["status"] == "disabled"
    sleep = user and not off and a.is_dormant(u) and not a.is_service(u)
    d = a.login_days(u) if user else None
    note = (" The user is disabled: cannot log in." if off else
            (" The user never logged in (dormant)." if d is None else f" The user has not logged in for {d} days "
                                                                       "(dormant).") if sleep else "")
    yes_text = "Yes, but the user is disabled" if off else "Yes, but the user is dormant" if sleep else ""
    tone = "warn" if (ps or r["owner"] or admin) and (off or sleep) else None
    gaps = r["blocked"] if (ps or r["owner"]) and not admin else []  # the grant is there, USAGE on its database or schema is not
    if gaps:
        has = what if ps else "OWNERSHIP"
        fix = r["unblock"]
        ans = dict(yes=False, how="blocked", title=f"Has {has}, but {a.gap_text(gaps)}: blocked",
                   text=f"{u} holds {has} on {o}, but no role {u} reaches{'' if user else ' (itself included)'} has USAGE on the "
                        f"{' or '.join(f'{t.lower()} {c}' for t, c in gaps)}, so Snowflake refuses the statement. "
                        f"Smallest fix: {fix[0][0].lower()}{fix[0][1:]}.", tone="low",
                   stats=[["Paths", r["count"] or r["owner_count"]], ["Missing USAGE", len(gaps)]])
    elif not ps and r["owner"]:
        ans = dict(yes=True, how="owner", title=yes_text or "Yes, via ownership",
                   text=f"{u} reaches OWNERSHIP of {o}, which implies {pv}.{note}", tone=tone,
                   stats=[["Paths", r["owner_count"]], ["Shortest depth", a.depth(r["owner"][0][:-1], user)]])
    elif not ps and admin:
        via = list(dict.fromkeys(next(x for x in q if x in a.ADMIN) for q in admin))
        ans = dict(yes=True, how="admin", title=yes_text or f"Yes, through admin role {', '.join(via)}",
                   text=f"{u} {does(pv)} {o} through the roles granted to admin role {via[0]}: {' > '.join(admin[0])}.{note}",
                   tone=tone, stats=[["Paths", 0], ["Via admin", len(admin)]])
    elif not ps:
        ans = dict(yes=False, how="none", title="No, by the grants in this data",
                   text=f"No role {'granted to' if user else 'held by'} {u}, at any depth, "
                   f"{'' if user else f'and not {u} itself, '}holds {'any privilege' if pv == ALL else pv} on {o}, by the grants in this data.{note}{power}", tone="low",
                   stats=[["Paths", 0], ["Shortest depth", "—"]])
    else:
        ends = {x["holder"] for x in ps}
        ans = dict(yes=True, how="paths", title=yes_text or (f"Yes: {plural(len(held), 'privilege')} through {plural(r['count'], 'path')}"
                                                             if pv == ALL else f"Yes, through {plural(r['count'], 'path')}"),
                   text=(f"{u} has {what} on {o}." if pv == ALL else f"{u} {does(pv)} {o}.") + (f" Every path ends at {ps[0]['holder']}." if len(ends) == 1 else "")
                   + (" Also through an admin role." if admin else "") + note, tone=tone,
                   stats=([["Privileges", len(held)]] if pv == ALL else []) + [["Paths", r["count"]], ["Shortest depth", r["shortest"]]])
    wa = sorted({x for q in a.held_admin(u, user) for x in a.admin_objects(q) if a.kinds.get(x) == "WAREHOUSE"} - set(r["warehouses"]))
    whs = r["warehouses"] + wa  # a warehouse an admin role reaches through its real links runs queries too
    read = None
    if not mine and not gaps and any(x in a.READ_PRIVS for x in held) and a.is_data(a.kinds[o]) and (ps or r["owner"]):
        v = a.data_view(u, o, user)
        if v["can_read"]:
            w = a.data_view(r["use_role"], o, False) if r["use_role"] and user else None
            read = dict(summary=v["summary"], rows=v["rows"] if v["rows"]["policy"] else None, columns=v["columns"],
                        role_only=w["summary"] if w and w["summary"] != v["summary"] else None)
    g = ps and a.down_graph(u, [dict(privilege=x, type=a.kinds[o], object=o, paths=[q["path"] for q in ps if q["privilege"] == x])
                                for x in held if any(q["privilege"] == x for q in ps)], user=user)
    k = a.kinds[o]
    got = {x["privilege"] for x in mine_rows if x["object"] == o}
    has = set(opts) if "OWNERSHIP" in got or a.admin_can(u, o, user, ["OWNERSHIP"]) else         got | {x for x in opts if admin and a.admin_can(u, o, user, [x])}
    ls, cut = a.lanes(ps)
    cut = [x for x in cut if x in r["choke"]]  # lanes list at most MAX_PATHS paths; choke is counted over all
    ask = pv if pv != ALL else a.basic_priv(k)
    # the slow part of a No (seconds on a big account): only when the Ways in tab asks (near=1)
    near = [] if mine or ps or r["owner"] or admin else a.nearest(u, ask, o, is_user=user) if p.get("near") == "1" else None
    # "do anything": the way to use it first, the way to own it apart; the narrowest grant before handing over a big role
    own = a.nearest(u, "OWNERSHIP", o, is_user=user) if near is not None and not mine and pv == ALL and ask != "OWNERSHIP" else None
    narrow = a.narrowest(u, user, ask, o) if near is not None and not mine and ask != "OWNERSHIP" else None
    for x in (near or []) + (own or []):  # the grant text right on the answer; a new account role between is planned on Request access
        x["change"] = a.with_sql(dict(op="grant", role=x["role"], to=x["to"], toUser=x["to_user"])) if x["cost"] == 1 else None
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
    verdict = "blocked" if gaps else "partly" if ans["yes"] and partly else "yes" if ans["yes"] else "no"
    miss = set(a.usage_gaps(u, o, user, k)) if o not in {x for q in a.held_admin(u, user) for x in a.admin_objects(q)} else set()
    return dict(
        usage=[dict(type=t, name=c, held=(t, c) not in miss) for t, c in a.containers(o, k)],  # Snowflake checks these first
        inside=inside_page(p, u, user, o, mine_rows) if k in ("DATABASE", "SCHEMA") else None,
        verdict=verdict, layers=layers, roles_count=len(set(a.best_paths(u, user)) - (set() if user else {u})), ask_priv=ask,
        held=[dict(privilege=x, held=x in has) for x in opts], lanes=ls[:20], lanes_total=len(ls), cut=cut,
        cuts=[] if mine or not ps else [dict(iac=x["iac"], sql=x["sql"], people=x["people"], lost=x["lost"],
                                             edges=[dict(grantee=e["grantee"], to=e["to"], priv=e["priv"], user=e["user"])
                                                    for e in x["edges"]]) for x in a.cut_points(u, held, o, user)],
        nearest=near, nearest_own=own, narrow=narrow, approver=a.approver(o), subject=subject_of(u, user),
        view=view, user=u, object=o, type=a.kinds[o], priv=pv, privileges=[ALL] + opts, answer=ans, status=r["status"],
        dormant_days=d if sleep else None, admin_paths=admin, paths=r["paths"], paths_total=r["count"], owner=r["owner"], choke=r["choke"],
        options=[] if mine else [dict(iac=x["iac"], sql=x["sql"], affects=x["affects"], users=x["users"], edges=len(x["edges"]),
                                      links=[{k: e.get(k) for k in ("grantee", "to", "priv", "user")} for e in x["edges"]])
                                 for x in r["options"]],
        use_role=r["use_role"], warehouse=r["warehouse"], read=read,
        blocked=[dict(type=t, name=c) for t, c in gaps], unblock=dict(iac=r["unblock"][0], sql=r["unblock"][1]) if gaps else None,
        warehouses=dict(names=whs[:MAX_WH], total=len(whs), admin=bool(wa)), builtin=a.builtin_on(o),
        graph=g and build_graph("Paths combined", g[0], g[1], g[2], focus=p.get("focus")) or None, capped=sorted(a.capped),
        risks=ranked([x | dict(text=f"{n}: {x['text']}") for n, xs in ((u, subject_risks(u, user)), (o, object_risks(o))) for x in xs]))


INSIDE_PAGE = 100  # Can they? on a database or schema: objects per page


def inside_page(p, u, user, o, rows):
    """Can they? on a database or schema: the tables and views in it for mode= read | dml | ddl, filtered by show_in=
    all | can | cannot and in_q=, paged (offset=), with the counts."""
    mode = p.get("inside") if p.get("inside") in a.INSIDE_NEEDS else "read"
    x = a.inside_access(u, user, o, mode, rows)
    rs, want = x["rows"], p.get("show_in") if p.get("show_in") in ("can", "cannot") else "all"
    can = sum(r["ok"] for r in rs)
    words = p.get("in_q", "").upper().split()
    pick = [r for r in rs if (want == "all" or r["ok"] == (want == "can")) and all(w in r["object"] for w in words)]
    off = int(p["offset"]) if p.get("offset", "").isdigit() else 0
    return dict(mode=mode, show=want, total=len(rs), can=can, cannot=len(rs) - can, blocked=sum(bool(r["blocked"]) for r in rs),
                matched=len(pick), rows=pick[off:off + INSIDE_PAGE], offset=off, limit=INSIDE_PAGE, create=x["create"])


def request_page(p, view):
    """Screen 15, Request access: the object, read or change, the suggested roles (smallest existing one first) with
    holders and what else each brings, the approver (owner tag) and the user's level today. Text only: the page writes
    SQL / Terraform / ticket text, nothing runs."""
    need(a.objects, "No objects in this data.")
    u, user = asker(p, view, "for_role")
    o = p.get("obj")
    if not o:  # never a guessed object: the page asks for one
        return dict(view=view, user=u, subject=subject_of(u, user), object=None)
    need(o in a.kinds, f"{o} is not in this snapshot")
    k, nd = a.kinds[o], p.get("need") if p.get("need") in ("read", "change") else "read"
    pvs = a.need_privs(k, nd)
    mine = {x["privilege"] for x in a.grants(u, user) if x["object"] == o}
    now = max((a.obj_level(x, k) for x in mine), key=a.OBJ_LEVELS.index, default=None)
    held = all(x in mine for x in pvs) or "OWNERSHIP" in mine
    adm = sorted({x for q in a.admin_can(u, o, user, pvs) for x in q if x in a.ADMIN})         if all(a.admin_can(u, o, user, [x]) for x in pvs) else []  # as Can they? says Yes: every privilege needed
    if adm and not held:
        held, now = True, "admin"
    r, to = p.get("role"), p.get("to") if user else u
    asked = dict(role=r, kind=nk(r), to=to if to in a.roles else None) if r in a.roles else None  # picked on Can they?
    who = subject_of(u, user)
    if asked:  # the same warnings as on Can they?: rule 1, and everyone holding the grantee role gets it too
        n = len(a.ups(asked["to"])[1] - ({u} if user else set())) if asked["to"] else 0
        asked |= dict(rule1=a.role_kind(r) == "technical" and (user and not asked["to"] or a.role_kind(asked["to"] or "") == "group"),
                      people=n, broad=bool(asked["to"]) and n >= a.BROAD + (not user))
    sug = [] if held else a.suggest(pvs, o, u, is_user=user)
    for x in sug:
        x |= dict(people=0 if user else who["people"], broad=not user and who["people"] > a.BROAD,
                  change=a.with_sql(dict(op="grant", role=x["role"], to=u, toUser=user)))
    if asked:
        asked["change"] = a.with_sql(dict(op="grant", role=r, to=asked["to"] or u, toUser=not asked["to"]))
    return dict(view=view, user=u, subject=who, object=o, type=k, database=a.split_name(o, k)[0], need=nd,
                privileges=pvs, level=now, has=held, via_admin=adm if now == "admin" else [], asked=asked, suggestions=sug, approver=a.approver(o), owners=a.object_stats(o, k)["owners"])


# ---------- access graph (screen 4) ----------

FROM = {"table": "object", "role": "role", "user": "user"}
RISK = {"admin": "leads to an admin role or an account privilege", "public": "through PUBLIC: everyone has it",
        "writes": "a read role that writes"}


MAP_ACCESS = ("read", "write", "own")  # the access graph's Access filter: lines that carry that step


def map_filters(p):
    """(scope, object type, access) of the access graph: schema= a database or DB.SCHEMA, otype=, access=."""
    acc = p.get("access") or None
    if acc and acc not in MAP_ACCESS:
        raise ApiError(400, "bad_param", "access must be read, write or own")
    return p.get("schema") or None, p.get("otype") or None, acc


def map_cut(g, scope, otype, acc):
    """The access graph's lanes and edges with only the objects in scope, of otype, reached by an acc line, and the
    roles and people on the lines to them (the start stays)."""
    if not (scope or otype or acc):
        return g["lanes"], g["edges"]
    objs = set(g["lanes"][-1][1])
    ok = lambda o: (o in a.kinds and (not otype or a.kinds[o] == otype)
                    and (not scope or scope in (a.split_name(o)[0], scope_key(o))))
    es = [e for e in g["edges"] if e[1] not in objs or ok(e[1]) and (not acc or e[2] == acc)]
    # objects lead nowhere: through them is what leads to them, not every other branch of a kept role
    return cut(g["lanes"], es, through(es, {e[1] for e in es if e[1] in objs}) | {g["start"]})


def map_graph(p, view, only=None):
    """The access graph of map_page, drawn: over MAX_BOX objects one box per database, crowded people and role lanes
    folded (big accounts: the boxes go out empty and open through graph?of=map&group=). Returns dict(g (a.access_graph,
    once per data set), graph (only=<box>: that box), name, start, header)."""
    need(a.users or a.roles, "No users or roles in this data.")
    start, name = next(((FROM[k], p[k]) for k in FROM if p.get(k)), ("user", None))
    if start == "user" and (view == "mine" or not name):
        name = a.users[0] if view == "mine" or DEMO_USER not in a.users else DEMO_USER
    same, adm = flag(p, "same", True), flag(p, "admin", True)
    try:
        g = a.cached(("access_graph", start, name, same, adm), lambda: a.access_graph(start, name, same, adm))
    except ValueError as x:
        raise ApiError(404, "not_found", str(x))
    who = len(set().union(*(g["people"].get(n, ()) for n in g["lanes"][0][1]))) if g["lanes"] else 0  # the people lane
    objs = sum(n not in g["kinds"] for n in g["lanes"][-1][1]) if g["lanes"] else 0
    mid = sum(len(ns) for _, ns in g["lanes"][1:-1])
    folk = f"{who} {'person' if who == 1 else 'people'}"
    header = {"object": f"Everyone who reaches {name}: {folk}, {plural(mid, 'role')} in between.",
              "role": f"Who holds {name} (left) and everything it opens up (right): {folk}, {plural(objs, 'object')}.",
              "user": f"Every role {name} holds, and every object those roles reach: {plural(mid, 'role')}, {plural(objs, 'object')}."}[start]
    f = map_filters(p) if start != "object" else (None, None, None)
    def combined():
        ls, es = map_cut(g, *f)
        at = next((i for i, (lab, _) in enumerate(ls) if lab == g["lanes"][-1][0]), len(ls))
        return combine_tab(ls, es, {}, {k: "fold" for k, v in g["kinds"].items() if v == "fold"}, at=at)
    # 450k grant lines of a big user roll up in seconds: once per data set and filters
    lanes, edges, _, kinds, gx = a.cached(("map_combined", start, name, same, adm, f), combined)
    if any(f) and lanes:  # the counts above are before the filters
        last = lanes[-1][1] if lanes[-1][0] == g["lanes"][-1][0] else []
        mid = sum(len(ns) for _, ns in lanes[1:len(lanes) - bool(last)])
        objs = sum((gx.get(n) or {}).get("count", 1) for n in last)
        header += f" With the filters: {plural(mid, 'role')}, {plural(objs, 'object')}."
    src = {k: p[k] for k in ("view", "builtin", "table", "role", "user", "same", "admin", "schema", "otype", "access")
           if p.get(k)} | dict(of="map")
    graph = build_graph("Access graph", lanes, edges, kinds=kinds, selected=g["start"], header=header, gx=gx, src=src,
                        only=only, sizes={s: len(us) for s, us in g["stacks"].items()}, focus=p.get("focus"))
    bi = a.builtin_info()
    for n in graph["nodes"]:
        dress(n, g, bi)
    return dict(g=g, graph=graph, name=name, start=start, bi=bi, gx=gx)


def dress(n, g, bi):
    """An access graph box as the map draws it: stacked people, what the admin roles reach, the built-ins, the account."""
    k = g["kinds"].get(n["id"])
    if k == "stack":
        us = g["stacks"][n["id"]]
        n.update(kind="user", name=n["id"], label=f"{len(us)} people", marks=n["marks"] + ["stack"], action=None,
                 sub=", ".join(us[:3]) + (f" +{len(us) - 3}" if len(us) > 3 else ""),
                 tip="People with the same lines, stacked into one box")
    elif k == "every":
        n.update(kind="admin", label="Through admin roles", sub=f"{plural(g['every_objects'], 'object')} below their real links",
                 action=None, tip="What the roles granted to the admin roles reach; the every role -> SYSADMIN links are not drawn")
    elif k == "fold":
        n.update(sub=f"{bi['objects']} objects · folded" if bi else None, action=None)
    elif n["id"] == "ACCOUNT":
        n.update(kind="admin", label="Account", sub="account privileges")


def map_detail(g, n, members=None):
    """Who comes through a box of the access graph, what it leads to, its step and why it is risky. members: a
    combined box's members (all of theirs, the highest step)."""
    if members is None:
        ps, ls, lv = g["people"].get(n, ()), g["leads"].get(n, ()), g["levels"].get(n)
    else:
        ps = set().union(*(g["people"].get(m, ()) for m in members))
        ls = set().union(*(g["leads"].get(m) or ({m} if m in a.kinds else ()) for m in members))
        lv = max((g["levels"][m] for m in members if g["levels"].get(m)), default=None,
                 key=lambda v: a.OBJ_LEVELS.index(v) if v in a.OBJ_LEVELS else len(a.OBJ_LEVELS))
    if g["kinds"].get(n) == "fold" and not ls:  # the built-ins box: what PUBLIC brings, the grants build() left out
        on = a.ROLE_ON + ("APPLICATION_ROLE",)
        ls = {x["OBJECT_NAME"] for x in a.hidden if x["GRANTED_ON"] not in on}
    return dict(level=lv, people=heapq.nsmallest(30, ps), people_count=len(ps),
                leads=heapq.nsmallest(30, ls), leads_count=len(ls), risk=g["risky_nodes"].get(n),
                members=g["stacks"].get(n))


def map_page(p, view):
    """Screen 4, the access graph from a table (table=), a role (role=) or a person (user=): the graph, and per drawn
    box who comes through it, what it leads to, its step and why it is risky; node=<id> answers that detail alone (a
    box opened later)."""
    x = map_graph(p, view)
    g, graph = x["g"], x["graph"]
    if p.get("node"):
        n, grp = p["node"], graph["groups"].get(p["node"])
        if n in g["people"] or n in g["leads"]:
            return dict(detail={n: map_detail(g, n)})
        mem = (x["gx"].get(n) or {}).get("members") or grp and (grp.get("ids") or [m["id"] for m in grp["nodes"]])
        need(mem, f"{n} is not in this graph")  # a combined box: what its members bring together
        return dict(detail={n: map_detail(g, n, mem)})
    for grp in graph["groups"].values():
        for n in grp["nodes"]:
            dress(n, g, x["bi"])
    drawn = {n["id"] for n in graph["nodes"] if n["id"] not in graph["groups"]} | {
        n["id"] for grp in graph["groups"].values() for n in grp["nodes"]}  # a lazy box's members come with node=
    es = graph["edges"] + [e for grp in graph["groups"].values() for e in grp["edges"]]
    risky = {e["id"]: g["risky"][(e["source"], e["target"])] for e in es if (e["source"], e["target"]) in g["risky"]}
    return dict(view=view, start=x["start"], name=x["name"], id=g["start"], graph=graph,
                detail={n: map_detail(g, n) for n in sorted(drawn)}, risky=risky,
                risky_nodes={n: v for n, v in g["risky_nodes"].items() if n in drawn}, why=RISK, builtin=x["bi"])


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
    or masked and why), the All protected and Sensitive reach tables, and role usage."""
    name, user = subject(p, view)
    ok = view != "mine" or bool(S["sens"])
    s = a.cached(("seen", name, user), lambda: a.seen(name, user)) if ok else dict(cards=[], counts=None)
    cards = [x for x in s["cards"] if p.get("all") == "1" or x["sensitive"]]  # Column by column, one page (c_offset=)
    w, c_off = window(p, "c_offset", len(cards))
    pr = (a.profile.get(name) or {}) if user else {}
    who = dict(kind="user" if user else nk(name), name=name, id=a.uid(name, user),
               type=str(pr.get("TYPE") or "PERSON") if user else KIND.get(norm(a.role_kind(name)), "Role"),
               status=a.status(name) if user else None, default_role=pr.get("DEFAULT_ROLE") or None,
               secondary_all="ALL" in str(pr.get("DEFAULT_SECONDARY_ROLES") or "").upper(),
               roles=sorted(a.roles_of.get(name, [])) if user else [])
    return dict(view=view, who=who, known=ok, cards=cards[w], cards_total=len(cards), cards_offset=c_off, counts=s["counts"],
                can_read=sees(p, a.data_views(name, user)) if ok else None, sensitive=sens_reach(name) if user else None,
                usage=usage(name) if user else None, role_usage=None if user else role_usage(name),
                risks=subject_risks(name, user) if view != "mine" else None)


# ---------- granted vs used (screen 13), what changed (screen 14) ----------

ENABLE_USE = ("ACCESS_HISTORY needs Enterprise edition or higher, read by the role that owns SP_ACCESS_SNAPSHOT (or, "
              "with SOURCE=direct, your role): GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE <that role>; "
              "then rebuild the snapshot.")


MAX_ACTIVITY = 2000  # Activity rows sent (user, role, client, object, statement); the counts above them cover all


def activity_page(p, view):
    """Activity tab of an object (name=), a person (user=) or a role (role=): table use per day over ACTIVITY_DAYS,
    by user, role, client and statement, DDL changes and the rule 24-28 findings on it; else why there is none. None of
    them: the whole account (Activity page), days= back, r= by c= (a.ACT_DIMS)."""
    if not (p.get("name") or p.get("user") or p.get("role")):
        ok, why = a.act_state()
        if view == "mine":
            ok, why = False, "My access reads no ACCESS_HISTORY: open Activity on the shared data."
        days = p.get("days", "30")
        if not days.isdigit() or int(days) not in a.ACT_PERIODS:
            raise ApiError(400, "bad_param", f"days must be one of {a.ACT_PERIODS}")
        r, c = p.get("r", "user"), p.get("c", "client")
        if r == c or not {r, c} <= set(a.ACT_DIMS):
            raise ApiError(400, "bad_param", f"r and c must be two of {list(a.ACT_DIMS)}")
        out = dict(view=view, what="all", name="", available=ok, reason=why, days=int(days), periods=list(a.ACT_PERIODS),
                   work=dict(start=a.WORK_HOURS[0], end=a.WORK_HOURS[1]), note=(a.run.get("NOTES") or {}).get("activity"),
                   last=a.day(a.ref_time()).isoformat())
        if not ok:
            return out
        x = a.activity_all(int(days), r, c)
        known = dict(user=set(a.users), role=set(a.roles), object=set(a.kinds))
        seen = {(k, v) for k in known for v in [w[k] for w in x["who"]] + [d["key"] for d in x["dims"][k]]}
        seen |= {(k, v) for k, vs in ((r, x["cross"]["rows"]), (c, x["cross"]["cols"])) if k in known for v in vs}
        return out | x | dict(gone=sorted({v for k, v in seen if v not in known[k]}))  # used, not in the snapshot: no page
    what = "object" if p.get("name") else "user" if p.get("user") else "role"
    name = p.get("name") or p.get("user") or p.get("role") or ""
    kind = a.kinds.get(name) if what == "object" else None
    what = {"STREAMLIT": "app", "DATABASE": "scope", "SCHEMA": "scope"}.get(kind, what)  # an app: the queries it ran
    # for its viewers; a database or schema: every object in it
    who = p.get("as") if what in ("object", "app", "scope") else None  # the object page's "Access for": one user's use
    ok, why = a.act_state()
    if view == "mine" and not ok:
        why = "My access reads no ACCESS_HISTORY: open Activity on the shared data."
    if kind == "WAREHOUSE":  # no ACCESS_HISTORY rows: who ran queries on it comes from QUERY_HISTORY (the usage read)
        src = (a.run.get("SOURCES") or {}).get("usage")
        return dict(view=view, what="warehouse", kind=kind, name=name, user=None, available=src != "UNAVAILABLE",
                    reason=(a.run.get("NOTES") or {}).get("usage") or "Query history is not readable.",
                    warehouse=a.warehouse_use(name), source=src or "demo values")
    out = dict(view=view, what=what, kind=kind, name=name, user=who, days=a.ACTIVITY_DAYS, available=ok, reason=why,
               work=dict(start=a.WORK_HOURS[0], end=a.WORK_HOURS[1]), note=(a.run.get("NOTES") or {}).get("activity"),
               admin=bool(a.admin_users().get(name)) if what == "user" else what == "role" and name in a.ADMIN)
    if not ok:
        return out
    x = a.activity(name, what, who)
    g, gone = a.activity_graph(name, what, x["rows"]) if what not in ("app", "scope") else (None, [])
    data = what == "object" and a.is_data(a.kinds.get(name, ""))
    return out | x | dict(
        total=len(x["rows"]), rows=x["rows"][:MAX_ACTIVITY], gone=gone,
        graph=g and build_graph("Who used it, through which grant", g[0], g[1], g[2],
                                header=f"Role used, then the grant path it has now · top {a.MAX_OBJECTS} objects"
                                if what != "object" else "User, role used, then the grant path it has now", focus=p.get("focus")),
        sensitive=a.activity_sensitive(name, what, x["rows"]), query_sql=a.query_sql(name, what, x["first"], x["last"]),
        section_sql={k: a.activity_section_sql(name, what, x["first"], x["last"], k)["sql"] for k in a.ACT_SECTIONS},
        objects={o: dict(kind=(a.kinds.get(o) or "").lower() or "gone", sensitive=o in a.sens)
                 for o in dict.fromkeys(r["object"] for r in x["rows"])},
        mark=a.mark_sensitive(name) if data and name not in a.sens else None,
        app=a.app_use(name, x["rows"]) if what == "app" else None, findings=[
        dict(num=r["num"], title=r["title"], severity=r["severity"], grantee=r["grantee"], detail=r["detail"])
        for r in S["rows"] if int(r["num"]) >= 24 and (r["grantee"] == name or name in r["path"])
        and (not who or r["grantee"] == who)])


def sql_page(p, view):
    """The SQL to run yourself behind a page (page= and its own parameters): commented, with SET lines filled in."""
    return dict(page=p.get("page") or "home", queries=[q for q in a.page_sql(p.get("page") or "home", p) if q])


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
        return out | dict(rows=[], rows_total=0, offset=0, f="all", weeks=[], counts=None, changes=[], sql="", people=0,
                          trim_text="", changes_capped=False, base_read=False)
    g = a.cached(("granted_used", name, user, days), lambda: a.granted_used(name, user, days))
    f = p.get("f") if p.get("f") in ("drop", "trim", "keep", "sensitive") else "all"
    q = p.get("q", "").strip().lower()
    rows = [r for r in g["rows"] if (f == "all" or (r["sensitive"] if f == "sensitive" else r["suggest"] == f))
            and (not q or q in r["object"].lower())]
    w, off = window(p, "u_offset", len(rows))
    big = len(g["changes"]) > TRIM_MAX
    cut = [r for r in g["rows"] if r["changes"]]
    text = " · ".join(f"{', '.join(dict.fromkeys(c['privilege'] for c in r['changes']))} on {r['object'].split('.')[-1]}"
                      for r in cut[:TRIM_NAMES]) + (f" · and {len(cut) - TRIM_NAMES} more objects" if len(cut) > TRIM_NAMES else "")
    return out | dict(days=g["days"], weeks=g["weeks"], people=g["people"], base_read=g["base_read"], f=f, offset=off, rows_total=len(rows),
                      rows=[{k: v for k, v in r.items() if k not in ("changes", "people")} for r in rows[w]],
                      counts=g["counts"] | dict(sensitive=sum(r["sensitive"] for r in g["rows"])), trim_text=text,
                      changes=[] if big else g["changes"], sql="" if big else g["sql"], changes_capped=big)


TRIM_MAX = 1000  # revokes Granted vs used lists and hands to the change plan; more: the CSV has every unused privilege
TRIM_NAMES = 20  # objects named in the trim's one-line summary

OBJUSE_TABS = ("unused", "read_only", "write_only", "all")
BUCKET_WORD = {"30": "last 30 days", "90": "31-90 days ago", "180": "91-180 days ago", "none": "not used", "nodata": "no activity data"}
NO_OLDER = "not used in its {} days of history"  # bucket nodata of a warehouse or app with history: older use unknown
NEVER = 10 ** 6  # days_since of an object never used: sorts as the oldest
# row tuple of a.object_activity(): (object, type, last read, last write, days since, bucket, new, use per window, history days)
OBJUSE_SORT = {"object": lambda r: r[0], "type": lambda r: (r[1], r[0]), "last_read": lambda r: r[2], "last_write": lambda r: r[3],
               "days": lambda r: NEVER if r[4] is None else r[4], "bucket": lambda r: a.BUCKETS.index(r[5])}
OBJUSE_USE = {"read_q": 0, "write_q": 1, "readers": 2, "writers": 3}  # sort keys read from the window's use


def objuse_rows(p, view):
    """Object activity: (days, everything a.object_activity() has, the rows in scope=, counts in scope, the rows of
    tab= / type= / q=, sorted by sort= / dir=). unused: not used in the last days (never used included), "no
    activity data" and a window longer than the type's history (warehouses, apps) left out; read_only / write_only:
    tables read and not written in the window, or the reverse."""
    days = int(p["days"]) if str(p.get("days", "")).isdigit() else 0 if p.get("days") else 90
    if days not in a.PERIODS:
        raise ApiError(400, "bad_param", "days must be 30, 90 or 180")
    x, i = a.object_activity(), a.PERIODS.index(days)
    sc = p.get("scope", "").strip()
    rows = [r for r in x["rows"] if not sc or r[0] == sc or r[0].startswith(sc + ".")] if sc else x["rows"]
    pat = lambda r: a.pattern(r[7][i]) if r[8] and a.writable(r[1]) else None  # noqa: E731
    unused = lambda r: r[8] >= days and (r[4] is None or r[4] > days)  # noqa: E731
    types, tabs, pats, fresh = {}, dict.fromkeys(OBJUSE_TABS, 0), dict(read_only=0, write_only=0, both=0, none=0), 0
    for r in rows:
        types.setdefault(r[1], dict.fromkeys(a.BUCKETS, 0))[r[5]] += 1
        u = unused(r)
        tabs["unused"] += u
        fresh += u and r[6]
        pt = pat(r)
        if pt:
            pats[pt] += 1
    tabs.update(read_only=pats["read_only"], write_only=pats["write_only"], all=len(rows))
    tab = p.get("tab") if p.get("tab") in OBJUSE_TABS else "unused"
    t, words = p.get("type", ""), p.get("q", "").lower().split()
    keep = unused if tab == "unused" else (lambda r: True) if tab == "all" else (lambda r: pat(r) == tab)
    out = [r for r in rows if keep(r) and (not t or r[1] == t) and all(w in r[0].lower() for w in words)]
    by = p.get("sort") or {"unused": "days", "read_only": "read_q", "write_only": "write_q"}.get(tab, "object")
    u = OBJUSE_USE.get(by)
    key = (lambda r: r[7][i][u]) if u is not None else OBJUSE_SORT.get(by, OBJUSE_SORT["object"])
    desc = p.get("dir") == "-1" if p.get("dir") else by not in ("object", "type")
    return dict(days=days, i=i, x=x, types=types, tabs=tabs, patterns=pats, unused_new=fresh, tab=tab,
                rows=sorted(out, key=key, reverse=desc), pat=pat)


def objuse_row(r, i, pat):
    db, sc, _ = a.split_name(r[0], r[1])
    rq, wq, rs, ws = r[7][i]
    return dict(object=r[0], type=r[1], database=db, schema=sc, last_read=r[2] or None, last_write=r[3] or None,
                days_since=r[4], readers=rs, writers=ws, read_q=rq, write_q=wq, bucket=r[5], pattern=pat(r), new=r[6],
                history=r[8], sensitive=r[0] in S["sens"])


def objuse_page(p, view):
    """Object activity: every table, view, warehouse and Streamlit app by last use (ACCESS_HISTORY, QUERY_HISTORY),
    counts per type and age, read but never written and the reverse, one table page (offset=, limit=)."""
    if view == "mine":
        return dict(view=view, available=False, reason="My access reads no ACCESS_HISTORY: open Object activity on the shared data.",
                    enable=ENABLE_USE, notes=[], rows=[], total=0)
    c = objuse_rows(p, view)
    ok, why = a.use_state()
    off, lim, page = paged(p, c["rows"])
    return dict(view=view, available=ok, reason=why, enable=ENABLE_USE, notes=c["x"]["notes"], days=c["days"],
                periods=list(a.PERIODS), tab=c["tab"], type=p.get("type", ""), scope=p.get("scope", ""),
                base_read=c["x"]["base_read"], history=dict(data=a.USE_DAYS, warehouse=a.DAYS_USAGE, app=a.ACTIVITY_DAYS),
                types=[dict(type=k, buckets=v, total=sum(v.values())) for k, v in sorted(c["types"].items(), key=lambda t: -sum(t[1].values()))],
                tabs=c["tabs"], patterns=c["patterns"], new=c["x"]["new"], unused_new=c["unused_new"],
                rows=[objuse_row(r, c["i"], c["pat"]) for r in page], total=len(c["rows"]), offset=off, limit=lim,
                source=(a.run.get("SOURCES") or {}).get("object_use") or ("demo values" if MODE == "fake" else None))


def objuse_csv(p, view):
    c = objuse_rows(p, view)
    cols = ["Object", "Type", "Last read", "Last written", "Days since used", "Read queries", "Write queries", "Readers",
            "Writers", "Last used", "Pattern", "New or changed"]
    out = []
    for r in c["rows"]:
        x = objuse_row(r, c["i"], c["pat"])
        out.append([x["object"], x["type"], x["last_read"] or "", x["last_write"] or "", "" if x["days_since"] is None else x["days_since"],
                    x["read_q"], x["write_q"], x["readers"], x["writers"],
                    NO_OLDER.format(x["history"]) if x["bucket"] == "nodata" and x["history"] else BUCKET_WORD[x["bucket"]],
                    x["pattern"] or "", "yes" if x["new"] else ""])
    return f"object_activity_{c['tab']}_{c['days']}d.csv", csv_text(cols, out)


NAMES = 20  # people, objects and subjects sent per What changed event


def changes_page(p, view):
    """Screen 14: the loaded snapshot against the previous one (demo: a.fake_previous(); else the copy cache.py kept
    in .cache/ when a refresh replaced it). subject= keeps the events about one user, role or object (a node id: a.uid() for users).
    f= (all, gain, lose, risk, sensitive; access: grants and people; findings: new and fixed) keeps one filter's events; they come one page at a time (offset=, limit=:
    PAGE, 0 every one), with events_total: a big change has tens of thousands. An event sends its first NAMES people,
    objects and subjects (plus subject=): one change on a big account names every user, and no page lists them."""
    out = dict(view=view, subject=p.get("subject") or None, available=False, events=[], events_total=0, offset=0, counts=None)
    if view == "mine":
        return out | dict(reason="What changed compares two shared snapshots: open it on the shared snapshot.")
    if MODE == "fake":
        prev = twin.data_previous()
    else:
        got = None if a.INSIDE else cache.prev(KEY)
        if not got:
            return out | dict(reason=no_prev())
        prev = got[0]
    d = diff_of(prev)
    ev = [e for e in d["events"] if not out["subject"] or out["subject"] in e["subjects"]]
    n, before = a.event_counts(ev), d["runs"]["before"]
    sub, mine = out["subject"], out["subject"] and a.node_kind(out["subject"]) == "user"  # subject= is a node id
    seen = set().union(*(e["people"] for e in ev)) if sub and not mine else set()
    gained = [u for u in d["sens_gained"] if not sub or (u == a.node_name(sub) if mine else u in seen)]
    text = (f"Since the snapshot of {before}: {plural(n['all'], 'change')}"
            + (f", {plural(d['high'], 'new high finding')}" if d["high"] and not out["subject"] else "")
            + (f", {len(gained)} {'person' if len(gained) == 1 else 'people'} gained sensitive access" if gained else "") + "."
            + (f" Big changes name only their first {a.EVENT_NAMES} people and objects, so some about {a.node_name(sub)} "
               "may be missing here." if sub and any(e.get("capped") for e in d["events"]) else ""))
    f = p.get("f") if p.get("f") in ("gain", "lose", "risk", "sensitive", "access", "findings") else "all"
    keep = {"all": lambda e: True, "sensitive": lambda e: e["sensitive"], "risk": lambda e: any(not x["fixed"] for x in e["findings"]),
            "access": lambda e: e["kind"] in ("gain", "lose", "user"), "findings": lambda e: e["kind"] in ("risk", "fixed")}.get(f, lambda e: e["kind"] == f)
    shown = [e for e in ev if keep(e)]
    shown = [e for e in shown if f != "access" or e["sensitive"]] + [e for e in shown if f == "access" and not e["sensitive"]]
    sl, off = window(p, "offset", len(shown))
    short = lambda xs: xs[:NAMES] + ([sub] if sub and sub not in xs[:NAMES] and sub in xs else [])
    ev = [e | dict(people=short(e["people"]), objects=short(e["objects"]), subjects=short(e["subjects"]))
          | (dict(edge=e["edge"] | dict(source_kind=norm(e["edge"]["source_kind"]), target_kind=norm(e["edge"]["target_kind"])))
             if e.get("edge") else {}) for e in shown[sl]]
    return out | dict(available=True, events=ev, events_total=len(shown), offset=off, f=f, counts=n, text=text, before=before,
                      now=d["runs"]["now"], new=d["new"], fixed=d["fixed"], high=d["high"],
                      severity=None if out["subject"] else d["severity"])


def diff_of(prev):
    """a.diff() of the loaded data set against prev, without its (user, object) pairs, once per pair of data sets:
    a refresh makes it (renew), and .cache/<key>.diff.pkl keeps it across restarts while both data sets, the
    settings, access.py and this file are the ones that made it."""
    def make():
        for k in [k for k in ANSWERS if k[1] == "home"]:  # Home's What changed card gets this comparison
            ANSWERS.pop(k, None)
        stamp = (shared_key(prev), shared_key(a.source["data"]), a.source.get("builtin"), a.rules_stamp(), SERVER_STAMP)
        f = cache.file(KEY).with_suffix(".diff.pkl") if MODE == "snowflake" and cache.local() else None
        got = cache.load(f) if f and f.is_file() else None
        if isinstance(got, dict) and got.get("stamp") == stamp:
            return got["diff"]
        with a.step("Comparing with the previous snapshot"):
            d = a.diff(prev, prev_findings(prev), shared_key(prev), pairs=False)
        if f:
            tmp = f.with_suffix(".tmp")
            tmp.write_bytes(pickle.dumps(dict(stamp=stamp, diff=d)))
            tmp.replace(f)
        return d
    return a.cached(("diff", cache.run_of(prev)), make)


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
    counts, rows with the differences first and the changes that make B match A, equal to A (match + trim) or remove
    A's extras (text only).
    The database picker searches /api/list?what=databases, so the page sends only the one picked."""
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
    c = a.cached(("compare", x, xu, y, yu, scope, db), lambda: a.compare(x, xu, y, yu, scope, db))
    side = lambda n, u: dict(name=n, id=a.uid(n, u), kind="user" if u else nk(n))
    # one page of rows (c_offset=, limit=; scope "everything" is 200k rows on a big account): f=only_a|only_b|both,
    # else the differences (same=1: the same ones too)
    f = p.get("f") if p.get("f") in ("only_a", "only_b", "both") else ""
    keep = lambda r: (r["a"] and r["b"]) if f == "both" else r["diff"] == f if f else p.get("same") == "1" or r["diff"] != "same"
    rows = [r for r in c["rows"] if keep(r)]
    w, off = window(p, "c_offset", len(rows))
    return dict(view=view, a=side(x, xu), b=side(y, yu), scope=scope, db=db, sensitive=bool(S["sens"]), **c) | dict(
        rows=rows[w], rows_total=len(rows), offset=off, any=bool(c["rows"]))


# ---------- sensitive data ----------

def sees(p, views):
    """What they see (data_views), one page of objects (v_offset=, limit=; 0: every one, for the CSV), with only what
    the table shows: a big account has thousands of governed objects, each with its policy text."""
    w, off = window(p, "v_offset", len(views))
    rows = [dict(object=v["object"], columns=[dict(column=c["column"], state=c["state"], reason=c["reason"]) for c in v["columns"]],
                 rows=dict(state=v["rows"]["state"], reason=v["rows"]["reason"], condition=v["rows"].get("condition")))
            for v in views[w]]
    return dict(rows=rows, total=len(views), offset=off)


def window(p, key, n):
    """The rows of a long table the page sends: slice(offset, offset + limit) of n rows from the params key= (offset)
    and limit= (PAGE by default, 0: every row, as a CSV export asks), and the offset used."""
    lim = int(p["limit"]) if p.get("limit", "").isdigit() else PAGE
    off = int(p[key]) if p.get(key, "").isdigit() else 0
    off = 0 if off >= n else off
    return slice(off, off + lim if lim else None), off


def sensitive_page(p, view):
    """Screen 7. objects and readers are long on a big account: one page each (o_offset= / r_offset=, limit=), with
    objects_total / readers_total; limit=0 sends every row (the CSV). row_list: the tables with a row policy, sensitive
    or not (shared only), one page at t_offset=."""
    mine = view == "mine"
    gov = a.governance_kpis()["text"] if not mine else None
    q = p.get("t_q", "").strip().upper()  # a table or policy name
    rt = [(o, v) for o, v in a.row_tables().items() if not q or q in o.upper() or any(q in x.upper() for x in v)] if not mine else []
    tw, to = window(p, "t_offset", len(rt))
    rows = dict(row_list=[row_policy_row(o, v) for o, v in rt[tw]], row_total=len(rt), row_offset=to)
    empty = dict(view=view, governance=gov, filters=dict(tag="", db="", people=False, tags=[], dbs=[]),
                 kpis=dict(objects=0, readers=0, columns=0, whole=0, people=0, admin=0, disabled=0, service=0, unmasked=0, stale=[],
                           stale_total=0),
                 objects=[], objects_total=0, objects_offset=0, readers=[], readers_total=0, readers_offset=0,
                 catalog=[], catalog_total=0) | rows
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
    rank = sorted(rank, key=lambda r: (-(r["masked"][1] - r["masked"][0]) / max(1, r["masked"][1]) if r["cols"] else 0, not r["cols"], -(r["masked"][1] - r["masked"][0])))  # least protected first
    order = [r["object"] for r in rank]
    who = a.sens_readers(order)
    idle = {u for u in a.users if a.status(u) != "active"}  # once per user, not once per object they read

    def every(k):
        return set().union(*(r[k] for r in rank))

    stale = sorted(u for u in who if not a.is_service(u) and u in idle)
    # admin readers: the objects their admin roles reach through real links (sensitive_rank "admin"), never all of them
    ppl, adm = every("people"), every("admin") - set(who)  # the tiles count every reader, People only or not
    everyone = len(who) + len(adm)  # the Who can read tab without People only
    if people:
        who = {u: w for u, w in who.items() if not a.is_disabled(u) and not a.is_service(u)}
    admins, by_adm = a.admin_users(), Counter(u for r in rank for u in r["admin"])
    ad = sorted(u for u in adm if not (people and (a.is_disabled(u) or a.is_service(u))))
    us = sorted(who, key=lambda u: (-len(who[u][0]), u)) + ad

    def reader(u):
        pr, w = a.profile.get(u) or {}, who.get(u)
        first = None if w else next(r["object"] for r in rank if u in r["admin"])
        return dict(user=u, type=str(pr.get("TYPE") or "PERSON"), status=a.status(u), last_login_text=login(u)[0],
                    objects=len(w[0]) + by_adm[u] if w else by_adm[u], roles=sorted(w[1]) if w else admins[u],
                    path=a.sens_path(u, [o for o in order if o in w[0]]) if w else a.admin_ways_to(first, a.READ_PRIVS)[u][0],
                    via_admin=not w, admin_paths=[] if w else a.admin_paths(u, True))

    def parts(r):  # the bar of "Who can read": each reader once
        n = sum(u in idle for u in r["people"])
        return dict(active=len(r["people"]) - n, dormant=n + len(r["disabled"]), service=len(r["service"]),
                    admin=len(r["admin"]))

    cols = sum(len(r["cols"]) for r in rank)
    ow, oo = window(p, "o_offset", len(rank))
    cat = [r for r in a.catalog() if (not db or r["database"] == db) and (not tg or tg in r["labels"])]
    col_of, clear_of = {r["object"]: r["columns"] for r in cat}, {r["object"]: r["clear"] for r in cat}
    every_role = p.get("limit") == "0"  # the CSV: every role
    rw, ro = window(p, "r_offset", len(us))
    return dict(
        view=view, state="ok", governance=gov, filters=dict(tag=tg, db=db, people=people, tags=labels, dbs=dbs),
        kpis=dict(objects=len(rank), readers=everyone, columns=cols, whole=sum(not r["cols"] for r in rank), people=len(ppl), admin=len(adm),
                  disabled=len(every("disabled")), service=len(every("service")),
                  by=None if tg or db else sens_readers_by(),
                  unmasked=sum(n - k for k, n in (r["masked"] for r in rank)), stale=stale[:NAMES], stale_total=len(stale)),
        objects=[dict(object=r["object"], database=r["database"], schema=r["schema"], name=r["name"], type=r["kind"],
                      tags=[dict(label=k, origins=list(dict.fromkeys(v))) for k, v in
                            {lab: [o + (f" {c}" if c else "") for c2, t2, v2, o in r["tags"] if a.tag_label(t2, v2) == lab
                                    for c in [c2]] for lab in dict.fromkeys(a.tag_label(t, v) for _, t, v, _ in r["tags"])}.items()],
                      cols=r["cols"], masked=list(r["masked"]), row_policies=r["row_policies"], readers=parts(r),
                      columns=col_of.get(r["object"], []), clear=clear_of.get(r["object"]), roles=r["roles"] if every_role else r["roles"][:ROLES_SHOWN],
                      roles_total=len(r["roles"])) for r in rank[ow]],
        objects_total=len(rank), objects_offset=oo,
        readers=[reader(u) for u in us[rw]], readers_total=len(us), readers_offset=ro,
        catalog=[dict(object=r["object"], name=r["name"], ns=f'{r["database"]}.{r["schema"]}', type=r["kind"],
                      labels=r["labels"], groups=r["groups"], status=r["status"], masked=list(r["masked"]),
                      columns=r["columns"], unmasked=r["unmasked"], row_policies=r["row_policies"], readers=r["readers"],
                      clear=r["clear"], admin=len(r["admin"]))
                 for r in cat] if p.get("show") == "catalog" else None, catalog_total=len(cat), **rows)  # only for its tab


def row_policy_row(o, names):
    """A table with row policies: sensitive or not, how many users read it, and from the policy text which roles see
    every row and which see some (all others see none); known False when a policy's logic is not plain role checks."""
    see, known = {"all": set(), "some": set()}, True
    for x in a.policies_of(o)["rows"]:
        t = a.row_terms(x)
        if t is None:
            known = False
            continue
        for term in t:
            see["some" if term["conds"] else "all"].update(r for g in term["roles"] for r, _ in g)
    return dict(object=o, policies=names, sensitive=o in a.sensitive(), readers=len(a.readers(o)),
                all_rows=sorted(see["all"]), some_rows=sorted(see["some"] - see["all"]), known=known)


ROLES_SHOWN = 5  # roles listed per sensitive object (a big account has thousands); roles_total counts them


# ---------- rules ----------

FINDINGS_PAGE = 100  # findings per answer (limit= up to 500); counts and groups cover every finding
MAX_GROUPS = 200  # rule / person / object groups and heat grid rows per answer
MAX_ADMINS = 200


def rule_index():
    """Per finding what the Rules page filters, groups and searches on, once per data set (S["rows"] order)."""
    def make():
        out = []
        for x in S["rows"]:
            user = x["kind"] == "user"
            g, os_ = a.uid(x["grantee"], user), a.finding_objects(x)
            out.append(dict(num=x["num"], sev=x["severity"], area=RULE_INFO.get(x["num"], ("", "Other"))[1], grantee=x["grantee"],
                            gid=g, kind=norm(x["kind"]), people=[x["grantee"]] if user else x["losers"],  # all: groups count them
                            reach=1 if user else len(x["losers"]),
                            objects=os_, text=" ".join((x["title"], g, x["detail"], x["num"], *os_)).lower()))  # an object's risk strip links q=<object>
        return out
    return a.cached("rule_index", make)


def finding_row(i):
    """One finding in a list: finding() without its fix texts and with the first path and people only; the whole
    finding comes from /api/finding?id=."""
    x = S["rows"][i]
    user = x["kind"] == "user"
    people = [x["grantee"]] if user else x["losers"]
    return dict(id=i, num=x["num"], title=x["title"], severity=x["severity"], area=RULE_INFO.get(x["num"], ("", "Other"))[1],
                grantee=a.uid(x["grantee"], user), kind=norm(x["kind"]), what=x["detail"], impact=impact(x),
                people=people[:5], people_total=len(people), paths=x["paths"][:1], paths_total=len(x["paths"]),
                fix=bool(x["iac"] or x["sql"]), same_fix=x["same_fix"], changes=a.fix_changes(x["edges"]),
                objects=a.finding_objects(x)[:5])


def num_param(p, k, default, top):
    v = p.get(k, "")
    return min(int(v), top) if v.isdigit() else default


def rule_groups(ix, idx, by):
    """Findings idx grouped by rule (most people first), person or object (most findings first; none under "") or,
    for the heat grid, grantee (worst first): {key: [finding index]} in that order, plus one summary per group."""
    m = {}
    for i in idx:
        x = ix[i]
        for k in ([x["num"]] if by == "rule" else [x["gid"]] if by in ("grid", "grantee") else x["people" if by == "person" else "objects"] or [""]):
            m.setdefault(k, []).append(i)
    people = lambda its: len({u for i in its for u in ix[i]["people"]})
    sums = [dict(key=k, findings=len(its), severity=min((ix[i]["sev"] for i in its), key=lambda s: SEV_RANK.get(s, 9)),
                 people=people(its) if by == "rule" else None) for k, its in m.items()]
    order = {"rule": lambda g: (-g["people"], -g["findings"], int(g["key"])),
             "grid": lambda g: (SEV_RANK.get(g["severity"], 9), -g["findings"], g["key"])}.get(
        by, lambda g: (not g["key"], -g["findings"], g["key"]))
    sums.sort(key=order)
    for g in sums[:MAX_GROUPS]:  # what only the groups sent show
        its = m[g["key"]]
        g.update(rules=len({ix[i]["num"] for i in its}), title=a.RULES[g["key"]][0] if by == "rule" else None,
                 sevs=dict(Counter(ix[i]["sev"] for i in its)),
                 kind=ix[its[0]]["kind"] if by in ("grid", "grantee") else None,
                 people=people(its) if by in ("object", "grantee") else g["people"])
        if by == "rule":  # who it is about, most people affected first
            top = sorted(its, key=lambda i: (SEV_RANK.get(ix[i]["sev"], 9), -ix[i]["reach"], ix[i]["gid"]))
            xs = list(dict.fromkeys(ix[i]["grantee"] for i in top))
            g.update(names=xs[:4], subjects=len(xs))
        if by == "grantee":  # thousands of findings that say the same thing: its objects, and what most of them say
            g["objects"] = len({o for i in its for o in ix[i]["objects"]})
            if all(ix[i]["num"] == "17" for i in its):  # one finding per object: one example, why it is read-only
                ex, hows = ro_said(S["rows"][its[0]]["detail"]), {ro_said(S["rows"][i]["detail"], True) for i in its}
                g.update(said=[dict(text=ex, findings=None)], said_total=1, tags=sorted(hows))
            else:
                said = Counter(pattern(i) for i in its)
                g.update(said=[dict(text=t, findings=n) for t, n in said.most_common(3)], said_total=len(said))
    return {g["key"]: m[g["key"]] for g in sums}, sums


RO_HOW = {"name": "named read-only", "behaviour": "used read-only", "both": "named and used read-only"}


def ro_said(t, how=False):
    """A rule 17 detail without its "mostly read: ...; " and "; heuristic: ..." parts, or (how) why the role counts as
    read-only."""
    t, _, h = t.partition("; heuristic: ")
    return RO_HOW.get(h, h) if how else t.split("; ")[-1]


def pattern(i):
    """A finding's detail with its objects as "…": the same issue on many objects reads as one line."""
    x = S["rows"][i]
    t = x["detail"]
    for o in sorted(a.finding_objects(x), key=len, reverse=True):
        t = t.replace(o, "…")
    return t


def rules_pool(p):
    """The findings Risks & fixes shows (its filters, the default severity the worst one with findings), for the page
    and its CSV."""
    ix = rule_index()
    who = p.get("grantee", "")
    is_of = subject_of_finding(who, p.get("of", ""))
    mine = [i for i, x in enumerate(ix) if is_of(x["grantee"], x["kind"])] if who else range(len(ix))
    if who and not mine:
        who, mine = "", range(len(ix))
    count = dict.fromkeys(a.RULES, 0)
    for i in mine:
        count[ix[i]["num"]] += 1
    skipped = a.skipped_rules()  # HIERARCHY=0 / ACTIVITY=0: did not run, so they do not pass either
    sel = p.get("rule", "") if p.get("rule", "") in a.RULES else ""
    off = set(p.get("off", "").split(",")) & set(a.RULES)
    q, area, ppl = p.get("q", "").strip().lower(), p.get("area", ""), p.get("people") == "1"
    pool = [i for i in mine if (not sel or ix[i]["num"] == sel) and ix[i]["num"] not in off and (not area or ix[i]["area"] == area)
            and (not ppl or ix[i]["people"]) and (not q or q in ix[i]["text"])]
    sev_counts = dict.fromkeys(SEV_RANK, 0)
    for i in pool:
        sev_counts[ix[i]["sev"]] += 1
    sev = p.get("sev", "")
    sev = sev if sev in SEV_RANK else "" if sev == "all" else next((s for s in SEV_RANK if sev_counts[s]), "")
    shown = [i for i in pool if not sev or ix[i]["sev"] == sev]
    return dict(ix=ix, who=who, mine=mine, count=count, skipped=skipped, sel=sel, off=off, q=q, area=area, ppl=ppl,
                sev_counts=sev_counts, sev=sev, shown=shown)


def rules_page(p, view):
    """Risks & fixes: counts over every finding, the groups of the filtered ones and one page of findings (of the
    group= when given). Filters: grantee, rule, sev (default the worst one with findings, all = every), q, area,
    people=1, off (rules turned off in the browser), by (rule | person | object | grid), offset, limit."""
    ix, who, mine, count, skipped, sel, off, q, area, ppl, sev_counts, sev, shown = rules_pool(p).values()
    by = p.get("by") if p.get("by") in ("person", "object", "grid", "grantee") else "rule"
    groups, sums = rule_groups(ix, shown, by)
    group = p.get("group")
    items = sorted(groups.get(group, []), key=lambda i: (-ix[i]["reach"], ix[i]["gid"])) if group is not None else [i for g in groups.values() for i in g] if by == "rule" else shown
    off_at, lim = num_param(p, "offset", 0, len(items)), max(1, num_param(p, "limit", FINDINGS_PAGE, 500))
    grid = None
    if by == "grid":
        worst = {}
        for i in shown:  # per finding: rules 5 and 9 can be Critical for some findings
            worst[ix[i]["num"]] = min(worst.get(ix[i]["num"], 9), SEV_RANK.get(ix[i]["sev"], 9))
        cols = sorted(worst, key=lambda n: (worst[n], int(n)))
        grid = dict(rules=cols, rows=[dict(grantee=g["key"], kind=g["kind"], severity=g["severity"], total=g["findings"],
                                           counts={n: c for n in cols if (c := sum(ix[i]["num"] == n for i in groups[g["key"]]))})
                                      for g in sums[:MAX_GROUPS]])
    out = dict(
        view=view, scope="mine" if view == "mine" else "account",
        filters=dict(grantee=who, of=p.get("of", "") if who else "", sev=sev, rule=sel, q=q, area=area, people=ppl, off=sorted(off, key=int), by=by, group=group),
        counts={**{s: sum(ix[i]["sev"] == s for i in mine) for s in SEVS},
                "Passing": sum(not count[n] and n not in skipped for n in a.RULES)},
        per_rule=count, skipped=skipped, sev_counts=sev_counts, hidden_off=sum(ix[i]["num"] in off for i in mine),
        areas=sorted({ix[i]["area"] for i in mine}), total=len(shown),
        groups=sums[:MAX_GROUPS], groups_total=len(sums), grid=grid,
        findings=[finding_row(i) for i in items[off_at:off_at + lim]], findings_total=len(items), offset=off_at, limit=lim)
    if group is None:  # a group's next page needs neither
        unknown = sorted(o for o in S["sens"] if any(a.row_terms(q) is None for q in a.policies_of(o)["rows"]))
        admins, st = admin_list(), stale_list()
        sq = p.get("sq", "").strip().lower()  # Dormant & disabled: a name search, one page at s_offset= (limit=0: all)
        sm = [x for x in st if sq in x["user"].lower()]
        w, s_off = window(p, "s_offset", len(sm))
        out.update(rows_unknown=[] if who else unknown, admins_total=len(admins), stale_total=len(st), stale=sm[w], stale_matched=len(sm),
                   stale_offset=s_off, stale_split=dict(Counter(x["status"] for x in st)), admins=[
            dict(user=x["user"], service=x["service"], roles=x["roles"], account=sorted(acct := {pv for pv, q in x["account"] if q[-1] != "PUBLIC"},
                                                                                   key=lambda pv: (pv not in a.ADMIN_LEVEL, pv)),
                 strong=sorted(acct & a.ADMIN_LEVEL), paths=x["paths"] + [q for _, q in x["account"] if q[-1] != "PUBLIC"], status=x["status"],
                 default_role=(a.profile.get(x["user"]) or {}).get("DEFAULT_ROLE"),
                 last_login=str(x["last_login"])[:16] if x["last_login"] else None) for x in admins[:MAX_ADMINS]])
    return out


TOP_ADMIN = ("ACCOUNTADMIN", "SECURITYADMIN")


def admin_list():
    """a.admin_people() without those whose only account privileges come through PUBLIC: every user has what PUBLIC
    holds, so it would list everyone (rule 9 shows it once). Riskiest first: ACCOUNTADMIN / SECURITYADMIN holders, then
    disabled, dormant or never logged in, then service users; their roles in that order too."""
    def make():
        out = [x | dict(roles=sorted(x["roles"], key=lambda r: (r not in TOP_ADMIN, TOP_ADMIN.index(r) if r in TOP_ADMIN else 0, r)))
               for x in a.admin_people() if x["roles"] or any(q[-1] != "PUBLIC" for _, q in x["account"])]
        return sorted(out, key=lambda x: (not set(x["roles"]) & set(TOP_ADMIN), x["status"] == "active", not x["service"], x["user"]))
    return a.cached("admin_list", make)


def stale_list():
    """People disabled, dormant or never logged in who still hold roles (rules 8 and 16), each once: those reading
    sensitive data (rule 7) first, then by findings."""
    def make():
        n, r7 = Counter(x["grantee"] for x in S["rows"]), {x["grantee"] for x in S["rows"] if x["num"] == "7"}
        reads = {x["grantee"]: x["detail"].partition("reads ")[2] for x in S["rows"] if x["num"] == "7"}
        out = [dict(user=u, status=a.status(u), service=a.is_service(u), roles=len(a.roles_of[u]), findings=n[u],
                    holds=sorted(a.roles_of[u])[:3], reads=reads.get(u, ""), login=login(u)[0],
                    sensitive=u in r7, last_login=str(v)[:16] if (v := (a.profile.get(u) or {}).get("LAST_SUCCESS_LOGIN")) else None)
               for u in a.users if a.stale(u) and a.roles_of.get(u)]
        return sorted(out, key=lambda x: (not x["sensitive"], -x["findings"], x["user"]))
    return a.cached("stale_list", make)


def finding_page(p, view):
    """One finding in full (id= from a Rules page list): every field of finding(), fix texts included."""
    i = p.get("id", "")
    need(i.isdigit() and int(i) < len(S["rows"]), f"Finding {i} is not in this data.")
    return dict(view=view, finding=finding(S["rows"][int(i)]) | dict(id=int(i)))


def rules_csv(p, view):
    """The findings the screen shows (rules_pool), each with its first CSV_PATHS paths and the path count."""
    now, f = datetime.now(), rules_pool(p)
    sev, sel, who = f["sev"], f["sel"], f["who"]
    rows = [S["rows"][i] for i in f["shown"]]
    what = ([f"rule {sel}"] * bool(sel) + [sev] * bool(sev) + [who] * bool(who) + [f'"{f["q"]}"'] * bool(f["q"])
            + [f["area"]] * bool(f["area"]) + ["people only"] * f["ppl"] + [f'rules off: {", ".join(sorted(f["off"], key=int))}'] * bool(f["off"]))
    text = csv_text(["Rule", "Title", "Severity", "Grantee", "Detail", "Fix", "SQL", "Affects users", "Same fix", "Paths", "Path count"],
                    [[x["num"], x["title"], x["severity"], x["grantee"], x["detail"], x["iac"], x["sql"],
                      "" if x["affects"] is None else x["affects"], x["same_fix"], " | ".join(arrow(q) for q in x["paths"][:CSV_PATHS]),
                      len(x["paths"])] for x in rows],
                    [["Rule checks", ", ".join(what) or "all"], ["Run", a.run.get("RUN_ID"), str(a.run.get("FINISHED_AT"))[:16]],
                     ["Generated", f"{now:%Y-%m-%d %H:%M}"]])
    return f"findings_{sev or 'all'}_{now:%Y-%m-%d}.csv", text


CSV_PATHS = 3  # paths per finding in the CSV: a finding lists up to MAX_PATHS, 130k findings would make it huge


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


WHATIF_USERS, WHATIF_GROUPS, WHATIF_OBJECTS = 200, 50, 100  # people (findings, objects left, roles), groups, objects lost a What if answer
# lists; the counts stay exact and the CSV has every row
WHATIF = {}  # (data set, changes) -> a.what_if(): a person's rows (user=) and the plan panel ask again for the same plan


def loss_groups(us):
    """People who lose the same privileges on the same objects (and keep the same ones another way) as one group,
    biggest first: the first names, the first lost / kept rows and a sentence."""
    sig = lambda rows: "|".join(sorted(f'{r["object"]}:{",".join(r["privileges"])}' for r in rows))
    drawn = lambda rows: sorted(rows, key=lambda r: 2 if r["type"] in ("DATABASE", "SCHEMA") else r["type"].startswith("FUTURE"))  # the plan graph's rows: real objects first
    by = {}
    for u in us:
        by.setdefault((sig(u["lost_rows"]), sig(u["kept_rows"]), u["objects"], str(u["lost_where"])), []).append(u)
    out = []
    for i, g in enumerate(sorted(by.values(), key=lambda g: (-len(g), -len(g[0]["lost_rows"])))):
        n, lost = len(g), g[0]["lost_rows"]
        who, verb = (g[0]["user"], "loses") if n == 1 else (f"{n} people", "lose")
        where = g[0]["lost_where"]
        text = (f"{who} {verb} {', '.join(lost[0]['privileges'])} on {lost[0]['object']}" if g[0]["objects"] == 1 else
                f"{who} {verb} access to {plural(g[0]['objects'], 'object')} in {plural(len(where), 'place')}" if lost else f"{who} {verb} nothing")
        out.append(dict(key=str(i), n=n, users=[dict(user=u["user"], status=u["status"]) for u in g[:WHATIF_USERS]],
                        off=sum(u["status"] != "active" for u in g), lost=drawn(lost)[:6], kept=drawn(g[0]["kept_rows"])[:2],
                        lost_sum=sum(u["lost"] for u in g), kept_sum=sum(u["kept"] for u in g),
                        where=where[:LOSS_WHERE], where_total=len(where), text=text))
    return out


LOSS_WHERE = 5  # schemas (or database / account) a loss group lists; where_total counts them


def object_impact(us):
    """Objects people lose, most people first: {object, type, people, privileges}."""
    by = {}
    for u in us:
        for r in u["lost_rows"]:
            x = by.setdefault(r["object"], dict(object=r["object"], type=r["type"], who=set(), pv=set()))
            x["who"].add(u["user"])
            x["pv"].update(r["privileges"])
    out = [dict(object=x["object"], type=x["type"], people=len(x["who"]), privileges=sorted(x["pv"])) for x in by.values()]
    return sorted(out, key=lambda x: (-x["people"], x["object"]))


def one_more(changes):
    """The roles a plan takes from one holder only, and who else holds each: the people dropping the role instead would
    touch too. Most people first, at most 3."""
    out, gone = {}, {}
    for c in changes:
        if c["op"] == "revoke_role_from_user":
            gone.setdefault(c["role"], set()).add(c["user"])
        elif c["op"] == "revoke_role_from_role":
            gone.setdefault(c["role"], set()).update(a.ups(c["grantee"])[1])
    for r, us in gone.items():
        rest = sorted(a.ups(r)[1] - us)
        if rest and r != "PUBLIC" and r not in a.ADMIN:
            out[r] = dict(role=r, people=len(rest), names=rest[:3])
    return sorted(out.values(), key=lambda x: (-x["people"], x["role"]))[:3]


def whatif_page(p, view):
    """What if: counts, groups and objects for the plan, the first WHATIF_USERS people as counts; user= one person's
    rows (lost, kept, roles still reached)."""
    k = (S["key"], p.get("changes", ""))
    if k not in WHATIF:
        if len(WHATIF) >= 4:
            WHATIF.clear()
        WHATIF[k] = what_if(p, a.MAX_PATHS)
    x = WHATIF[k]
    us = x["users"]
    if p.get("user"):
        u = next((u for u in us if u["user"] == p["user"]), None)
        need(u, f'{p["user"]} loses nothing in this plan')
        return dict(user=u)
    gs, objs = loss_groups(us), object_impact(us)
    return {k: v for k, v in x.items() if k not in ("csv", "users")} | dict(
        findings=x["findings"][:WHATIF_USERS], findings_total=len(x["findings"]), objects=x["objects"][:WHATIF_USERS],
        objects_total=len(x["objects"]), roles=x["roles"][:WHATIF_USERS], roles_total=len(x["roles"]), users=[{k: v for k, v in u.items() if k in ("user", "status", "lost", "objects", "kept")} for u in us[:WHATIF_USERS]],
        users_total=len(us), groups=gs[:WHATIF_GROUPS], groups_total=len(gs), impact=objs[:WHATIF_OBJECTS],
        one_more=one_more(json.loads(p["changes"])),
        critical_stay=sum(r["severity"] == "Critical" for r in S["rows"])
        + sum((f["status"] == "new") - (f["status"] == "fixed") for f in x["findings"] if f["severity"] == "Critical"),
        impact_total=len(objs), lost_privs=sum(u["lost"] for u in us), kept_privs=sum(u["kept"] for u in us),
        rows_capped=any(len(u["lost_rows"]) < u["objects"] for u in us))


def whatif_csv(p, view):
    now, out = datetime.now(), what_if(p, None)
    text = csv_text([k.capitalize() for k in WHATIF_KEYS], [[x[k] for k in WHATIF_KEYS] for x in out["csv"]],
                    [["What if", out["summary"]], ["Run", a.run.get("RUN_ID"), str(a.run.get("FINISHED_AT"))[:16]],
                     ["Generated", f"{now:%Y-%m-%d %H:%M}"], ["Infrastructure as code", out["iac"]],
                     ["SQL (never run by this app)", out["sql"]]])
    return f"what_if_{now:%Y-%m-%d}.csv", text


# ---------- access review ----------

REVIEW_COLS = ["Database", "Schema", "Object", "Type", "User", "User type", "Status", "Last login", "Privileges", "Classes",
               "Sensitive", "Granted roles", "Path", "Reviewer", "Keep/Revoke"]


REVIEW_SORT = {"o": "object", "db": "object", "u": 0, "l": "login", "p": "privileges", "g": 2, "path": 3}  # web columns
REVIEW_PAGE = 50
REVIEW_CSV_MAX = int(os.environ.get("REVIEW_CSV_MAX", "300000"))  # rows of one review CSV (about 60 MB)


def review_ctx(p):
    """The review filtered by db, schema, object and active, never a row per (user, object): ents [(entry, rows)]
    in review order (entry as a.review_parts() objects, rows (user, fields, granted, path to the holder) shared by
    objects with the same holders), the admin rows last as one entry with object None."""
    dbs = sorted({a.split_name(o)[0] for o in a.objects} - {""})
    need(dbs, "No databases in this data.")
    sens = Counter(a.split_name(o)[0] for o in S["sens"])
    db = p.get("db") or max(dbs, key=lambda d: (sens[d], -dbs.index(d)))  # where the sensitive data is, not the first name
    need(db == "*" or db in dbs, f"{db} is not in this snapshot")
    rv = a.review_parts(None if db == "*" else db)
    sc = p.get("schema", "")
    sc = sc if sc in {x[2] for x in rv["objects"]} else ""
    ob = p.get("object", "")
    active, kept = flag(p, "active"), {}
    rows = lambda sig: kept.setdefault(sig, [r for r in rv["rows"][sig] if r[1]["status"] != "disabled"]) if active \
        else rv["rows"][sig]
    ents = [(x, rows(x[6])) for x in rv["objects"] if (not sc or x[2] == sc) and (not ob or x[3] == ob)]
    ents.sort(key=lambda e: (type_rank(e[0][4] or ""), e[0][1], e[0][2], e[0][3]))
    adm = [(x["user"], {k: x[k] for k in ("user_type", "status", "last_login", "privileges", "classes")}, x["granted"], "")
           for x in rv["admins"] if not (active and x["status"] == "disabled")]
    ents.append(((None, db if db != "*" else "(every database)", "", "(what their admin roles reach through real links)", "", "", None), adm))
    return dict(dbs=dbs, db=db, sc=sc, ob=ob, active=active, rv=rv, ents=[e for e in ents if e[1]])


def review_text(x, r):
    """What the web table's filter box looks in: the row's column texts, lower case."""
    u, e, g, path = r
    login = str(e["last_login"])[:16] if e["last_login"] else "never"
    return "\x01".join([f"{x[1]}.{x[2]}.{x[3]}", u, login, e["privileges"], g, f"{path} > {x[0]}" if x[0] else ""]).lower()


def review_page(p, view):
    """Access review, one page of rows (offset=, limit=, sort= a REVIEW_SORT column, dir=1|-1, q= words that must
    all be in a row, part=sens|all the tab): kpis and counts over the filtered review, rows counted per object and
    built only for the page asked."""
    if view == "mine":
        raise ApiError(400, "shared_only", "The access review is about everyone: use the shared snapshot.")
    c = review_ctx(p)
    noise = flag(p, "hideusage", True)
    hide = lambda x: noise and x[0] and x[4] in ("DATABASE", "SCHEMA")
    hidden = sum(len(rs) for x, rs in c["ents"] if hide(x))
    ents = [(x, rs) for x, rs in c["ents"] if not hide(x)]
    words, found = (p.get("q") or "").lower().split(), {}
    if words:
        def hits(x, rs):  # words in the object's name hold for all its rows: a row list is searched once per word set
            left = tuple(w for w in words if w not in f"{x[1]}.{x[2]}.{x[3]}".lower()) if x[0] else tuple(words)
            k = (id(rs), left)
            if k not in found:
                found[k] = [r for r in rs if all(w in review_text(x, r) for w in left)] if left else rs
            return found[k]
        ents = [(x, got) for x, rs in ents if (got := hits(x, rs))]
    real = [(x, rs) for x, rs in ents if x[0]]  # the tiles count what the table holds: after the search and hiding
    us = {}
    for rs in {id(rs): rs for _, rs in real}.values():  # per shared row list, not per object
        us.update((r[0], r[1]["status"]) for r in rs)
    kpis = dict(objects=len(real), users=len(us), not_active=sum(st != "active" for st in us.values()),
                rows=sum(len(rs) for _, rs in ents), admin_rows=sum(len(rs) for x, rs in ents if not x[0]),
                hidden_usage=hidden, sensitive=len({x[3] for x, _ in real if x[5]}),
                csv_rows=sum(len(rs) for _, rs in c["ents"]))  # the CSV has every row of the picked scope
    counts = dict(sens=sum(len(rs) for x, rs in ents if x[5]), all=sum(len(rs) for _, rs in ents))
    part = "all" if p.get("part") == "all" or not counts["sens"] else "sens"
    note = None if part == "sens" or p.get("part") == "all" else \
        f"No sensitive objects in {'every database' if c['db'] == '*' else c['db']}{' for this search' if words else ''}: showing all rows."
    if part == "sens":
        ents = [(x, rs) for x, rs in ents if x[5]]
    key = p.get("sort") if p.get("sort") in REVIEW_SORT else "o"
    desc = p.get("dir") == "-1"
    off = int(p["offset"]) if p.get("offset", "").isdigit() else 0
    lim = max(1, min(int(p["limit"]), 1000)) if p.get("limit", "").isdigit() else REVIEW_PAGE
    label = {}  # per object, not per row
    fl = lambda x: label.setdefault(x, a.future_label(f"{x[1]}.{x[2]}.{x[3]}", x[4] or ""))
    split = lambda v: [s for s in v.split(", ") if s]
    return dict(
        view="shared",
        filters=dict(db=c["db"], schema=c["sc"], schemas=sorted({x[2] for x in c["rv"]["objects"]} - {""}),
                     object=c["ob"], objects=sorted({x[3] for x in c["rv"]["objects"] if not c["sc"] or x[2] == c["sc"]}),
                     active=c["active"], hideusage=noise),
        kpis=kpis, counts=counts, part=part, note=note, total=counts[part], offset=off, limit=lim, sort=key, dir=-1 if desc else 1,
        csv_max=REVIEW_CSV_MAX, rows=[dict(database=x[1], schema=x[2], object=x[3], type=x[4] or "", future_label=fl(x),
                   user=r[0], user_type=str(r[1]["user_type"]), status=r[1]["status"],
                   last_login=str(r[1]["last_login"])[:16] if r[1]["last_login"] else None,
                   privileges=split(r[1]["privileges"]), classes=split(r[1]["classes"]), sensitive=split(x[5]),
                   granted=split(r[2]), path=f"{r[3]} > {x[0]}".split(" > ") if x[0] else [], admin=not x[0])
              for x, r in review_slice(ents, key, desc, off, lim)])


def review_slice(ents, key, desc, off, lim):
    """Rows off..off+lim of the entries sorted by a web table column, as (entry, row) pairs. An object column sorts
    the objects and skips whole ones; a row column merges the row lists, each sorted once, objects by name."""
    full = lambda x: f"{x[1]}.{x[2]}.{x[3]}".casefold()
    by = REVIEW_SORT[key]
    if by == "object":
        ok = (lambda x: (full(x),)) if key == "o" else (lambda x: (f"{x[1]}.{x[2]}".casefold(), full(x)))
        out, at = [], off
        for x, rs in sorted(ents, key=lambda e: ok(e[0]), reverse=desc):
            if at >= len(rs):
                at -= len(rs)
                continue
            out += [(x, r) for r in (rs[::-1] if desc else rs)[at:at + lim - len(out)]]
            at = 0
            if len(out) >= lim:
                break
        return out
    rk = (lambda r: str(r[1]["last_login"])[:16] if r[1]["last_login"] else "never") if by == "login" else \
        (lambda r: r[1]["privileges"]) if by == "privileges" else (lambda r: r[by])
    groups = {}  # objects sharing one row list: one sorted stream
    for x, rs in ents:
        groups.setdefault(id(rs), (rs, []))[1].append(x)

    def stream(gi, rs, xs):  # in (key, object, ...) order: rows with the same key go object by object
        names = [(x[0] or "").casefold() if by == 3 else full(x) for x in xs]  # path: ends at the object itself
        keyed = sorted(((rk(r).casefold(), i) for i, r in enumerate(rs)), reverse=desc)
        for k, same in itertools.groupby(keyed, key=lambda t: t[0]):
            ids = [i for _, i in same]
            for j, f in enumerate(names):
                for i in ids:
                    yield k, f, gi, i, j
    streams = [(rs, sorted(xs, key=lambda x: (x[0] or "").casefold() if by == 3 else full(x), reverse=desc))
               for rs, xs in groups.values()]
    merged = heapq.merge(*(stream(gi, rs, xs) for gi, (rs, xs) in enumerate(streams)), reverse=desc)
    return [(streams[gi][1][j], streams[gi][0][i]) for _, _, gi, i, j in itertools.islice(merged, off, off + lim)]


GRID_ROWS = int(os.environ.get("GRID_ROWS", "300"))  # review grid: people sent, admins and the highest access first


def grid_page(p, view):
    """Screen 6 grid: people x objects (scope sensitive | db | all), or people x privileges of one object
    (object=&columns=privileges). Rows carry suggest (dormant / disabled / never logged in: suggested revoke); people=0
    keeps service users, stale=1 only those suggested, q= a name in the user or its roles; at most GRID_ROWS rows."""
    if view == "mine":
        raise ApiError(400, "shared_only", "The access review is about everyone: use the shared snapshot.")
    dbs = sorted({a.split_name(o)[0] for o in a.objects} - {""})
    obj = p.get("object", "") if p.get("columns") == "privileges" else ""
    need(not obj or obj in a.kinds, f"{obj} is not in this snapshot")
    scope = p.get("scope") if p.get("scope") in ("sensitive", "db", "all") else "sensitive" if S["sens"] else "all"
    db = p.get("db") or (dbs[0] if dbs else "")
    need(scope != "db" or db in dbs, f"{db} is not in this snapshot")
    people, stale, q = flag(p, "people", True), flag(p, "stale"), (p.get("q") or "").strip().lower()
    keep = lambda u, roles: (not people or not a.is_service(u)) and (not stale or a.stale(u)) and         (not q or any(q in x.lower() for x in [u, *roles]))  # the web's People only, Only dormant / disabled, search
    g = a.review_grid(scope, db, obj or None, flag(p, "hideusage", True), people=GRID_ROWS, keep=keep)
    rows = [r | dict(last_login=login(r["user"])[0], suggest=r["status"] if a.stale(r["user"]) else None)
            for r in g["rows"]]
    ppl, adm = [u for u in g["users"] if not a.is_service(u)], a.admin_users()
    return dict(view="shared", scope="object" if obj else scope, db=db, dbs=dbs, object=obj, columns=g["columns"],
                rows=rows, matched=g["matched"], rows_cap=GRID_ROWS, total=g["total"], cap=a.GRID_MAX, sensitive=len(S["sens"]),
                counts=dict(people=len(ppl), admin=sum(u in adm for u in ppl), stale=sum(map(a.stale, ppl)),
                            service=len(g["users"]) - len(ppl)))


def flow_page(p, view):
    """Screen 16: where sensitive data flows (access.sens_flow, counts only), with the default selection: the dormant
    or disabled. sel= follows one box (none: everyone): follow holds its links, headline and people."""
    if view == "mine" or not S["sens"]:
        return dict(view=view, state="mine" if view == "mine" else "none", groups=[], roles=[], objects=[], links=[],
                    select=None, follow=None, roles_all=[], roles_total=0, roles_offset=0)
    graph = p.get("show") == "graph"  # the tables need neither the links nor a followed box
    f = a.sens_flow(max_objects=FLOW_OBJECTS if graph else None)
    select = "risky" if any(g["id"] == "risky" for g in f["groups"]) else None
    sel = None if p.get("sel") == "none" else p.get("sel") or select
    every = f.pop("every")
    w, off = window(p, "e_offset", len(every))
    return dict(view=view, state="ok", **f, select=select, roles_all=every[w], roles_total=len(every), roles_offset=off,
                follow=a.flow_follow(sel, max_objects=FLOW_OBJECTS) if graph else None) | (
        {} if graph else dict(links=[]))


FLOW_OBJECTS = 15  # object boxes the flow graph draws, most read first; the rest are one box (the tables list all)


def flow_csv(p, view):
    """Every person of the Flow page's selected box (sel= as flow_page), disabled and service users included."""
    need(view != "mine" and S["sens"], "The flow needs the shared snapshot and sensitive data.")
    sel = None if p.get("sel") == "none" else p.get("sel") or (
        "risky" if any(g["id"] == "risky" for g in a.sens_flow()["groups"]) else None)
    f, now = a.flow_follow(sel, cap=None, max_objects=FLOW_OBJECTS), datetime.now()
    pr = lambda u: a.profile.get(u) or {}
    text = csv_text(["User", "Type", "Status", "Last login", "Roles"],
                    [[u, str(pr(u).get("TYPE") or "PERSON"), a.status(u), str(pr(u).get("LAST_SUCCESS_LOGIN") or "")[:16],
                      ", ".join(sorted(a.roles_of.get(u, [])))] for u in f["users"]],
                    [["Sensitive data flow", f["sel"] or "everyone"], ["Run", a.run.get("RUN_ID"), str(a.run.get("FINISHED_AT"))[:16]],
                     ["Generated", f"{now:%Y-%m-%d %H:%M}"]])
    return f"sensitive_flow_people_{now:%Y-%m-%d}.csv", text


def review_csv(p, view):
    if view == "mine":
        raise ApiError(400, "shared_only", "The access review is about everyone: use the shared snapshot.")
    c = review_ctx(p)
    n = sum(len(rs) for _, rs in c["ents"])
    if n > REVIEW_CSV_MAX:  # all databases of a big account: millions of rows, built in memory
        raise ApiError(400, "too_big", f"{n:,} rows are too many for one file (at most {REVIEW_CSV_MAX:,}): "
                                       "pick one database or schema.")
    now, where = datetime.now(), "every database" if c["db"] == "*" else c["db"]
    filt = [f"schema {c['sc']}"] * bool(c["sc"]) + [f"object {c['ob']}"] * bool(c["ob"]) + ["disabled excluded"] * c["active"]
    v = lambda x: "" if x is None else x
    rows = ([x[1], x[2], x[3], x[4], u, v(e["user_type"]), v(e["status"]), v(e["last_login"]), e["privileges"], e["classes"],
             x[5], g, f"{path} > {x[0]}" if x[0] else "", "", ""] for x, rs in c["ents"] for u, e, g, path in rs)
    text = csv_text(REVIEW_COLS, rows,
                    [["Access review", where], ["Run", a.run.get("RUN_ID"), str(a.run.get("FINISHED_AT"))[:16]],
                     ["Filter", ", ".join(filt) or "all users"], ["Generated", f"{now:%Y-%m-%d %H:%M}"]])
    return f"access_review_{'ALL' if c['db'] == '*' else c['db']}_{now:%Y-%m-%d}.csv", text


# ---------- find, list, graph, meta ----------

FIND = {}  # (data key, builtin) -> find_index(): search as you type needs no LOCK once a data set has one
SAID = {}  # (data key, builtin, id) -> answer() of a search hit
ANSWER_TOP = 8  # hits that get an answer() line (a walk each); the rest show name and kind


def find_index():
    """Every searchable name with what a hit shows, worked out once per data set: {id: item without answer}."""
    adm = {x["user"] for x in admin_list()}
    out = {}
    for n in [a.uid(u, True) for u in a.users] + a.roles + a.objects:
        k, name = nk(n), a.node_name(n)
        group = k if k in ("user", "object") and a.kinds.get(n) != "WAREHOUSE" else "warehouse" if k == "object" else "role"
        out[n] = dict(id=n, name=name, kind=k, kind_label=kind_label(name, a.node_kind(n)) if k != "object"
                      else (a.kinds.get(n) or "Object").capitalize(), type=a.kinds.get(n) if k == "object" else None,
                      sensitive=n in S["sens"], page=page_of(k), status=a.status(name) if k == "user" else None,
                      admin=k == "user" and name in adm, group=group)
    return out


def find_items(p, ix, fk):
    """The Find answer from an index; missing: the top hits whose answer() is not worked out yet."""
    hits_ = a.search(p.get("q", ""), ix)
    lim = int(p.get("limit", "20")) if p.get("limit", "20").isdigit() else 20
    out = [{k: v for k, v in ix[n].items() if k != "group"} | dict(answer=SAID.get(fk + (n,), "")) for n in hits_[:lim]]
    missing = [x for x in out[:ANSWER_TOP] if fk + (x["id"],) not in SAID]
    return dict(items=out, total=len(hits_), totals=dict(Counter(ix[n]["group"] for n in hits_))), missing  # Home.groupOf


def find_page(p, view):
    fk = S["key"]
    if fk not in FIND and len(FIND) >= 4:
        FIND.clear()
    if len(SAID) > 100000:
        SAID.clear()
    ix = FIND[fk] = FIND.get(fk) or a.cached("find_ix", find_index)
    out, missing = find_items(p, ix, fk)
    for x in missing:
        x["answer"] = SAID[fk + (x["id"],)] = answer(x["id"], x["kind"], x["name"])
    return out


def answer(n, k, name):
    """One-line answer of a search hit: "reads 6 · changes 5 · owns 2" for a person or role (reach only, fast), for an
    object its people and admin holders as the Object page counts them (split_users)."""
    if k == "object":
        s = a.split_users(set().union(*(a.ups(r)[1] for r, _, _ in a.on.get(n, []))), a.admin_readers(n))
        n_ = len(s["people"])
        return f"{n_} {'person' if n_ == 1 else 'people'} + {plural(len(s['admin']), 'admin holder')}"
    c = a.reach_counts(name, k == "user")
    return f"reads {c['read']} · changes {c['change']} · owns {c['own']}"


def list_page(p, view):
    """Users, roles, objects (type=), types, databases, or the holders of role= (What if; direct_holders: the Role
    page's cut). q= keeps the matches in search order and limit= the first ones (a picker asks for 50 per keystroke
    instead of the whole account); what= takes a comma list ("users,roles": one picker for a person or role). total:
    the matches before the limit."""
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
    elif what == "direct_holders":  # Role page, "If revoked from": who holds role=X by its own grant (graph ids)
        r = p.get("role", "")
        items = [dict(id=x, name=x, kind=nk(x), type="role", status=None) for x in sorted(a.held_by.get(r, []))]
        items += [dict(id=a.uid(u, True), name=u, kind="user", type="user", status=a.status(u)) for u in sorted(a.users_of.get(r, []))]
    elif what == "types":
        items = [dict(id=t, name=t, kind=None, type=t, status=None) for t in sorted(set(a.kinds.values()))]
    elif what == "databases":
        items = [dict(id=d, name=d, kind=None, type="DATABASE", status=None)
                 for d in a.cached("db_names", lambda: sorted({a.split_name(o)[0] for o in a.objects} - {""}))]  # per keystroke of the Compare / Review pickers
    else:
        raise ApiError(400, "bad_param", "what must be users, roles, objects, types, databases, role_holders, user_holders or direct_holders")
    return items


def graph_page(p, view):
    """A page's graph alone (of=); group=<box> answers just that combined box with its members (a lazy box opened)."""
    of, only = p.get("of", ""), p.get("group") or None
    if of == "user":
        return user_graph(p, user_ctx(p, view), only)
    if of == "role":
        c = role_ctx(p, view)
        return role_graph(p, c, *role_up(c), only)
    if of == "object":
        return object_graph(p, object_ctx(p, view), only)
    if of == "map":
        return map_graph(p, view, only)["graph"]
    if of == "check":
        return check_page(p, view)["graph"]
    if of == "user-tab":
        c = user_ctx(p, view)
        t = p.get("tab", "all")
        rows, walked = tab_rows(c["rows"], c["hidden"], c["reach"], t)
        return tab_graph(c["u"], True, rows, walked, "roles held" if walked else "privileges",
                         src=gsrc(p, of=of, name=c["u"], tab=t), only=only, focus=p.get("focus"))
    if of == "role-tab":
        c = role_ctx(p, view)
        t = p.get("tab", "all")
        rows, walked = tab_rows(c["eff"], [], c["held"], t)
        return tab_graph(c["r"], False, rows, walked, "roles held" if walked else "privileges",
                         src=gsrc(p, of=of, name=c["r"], tab=t), only=only, focus=p.get("focus"))
    raise ApiError(400, "bad_param", "of must be user, role, object, check, map, user-tab or role-tab")


def theme_tokens():
    out = {}
    for th, t in ui.TOKENS.items():
        k = dict(t["kind"])
        k["database_role"] = k["database"]
        for g in ("schema_group", "database_group", "type_group", "fold", "lane_group"):
            k[g] = k["object"]
        out[th] = dict(t) | dict(kind=k)
    return out


def side_people():
    """Side menu counts: admin holders (admin_list) and people disabled or dormant who hold roles (stale_list)."""
    return dict(admins=len(admin_list()), stale=len(stale_list()))


def meta(p, sid):
    view = p.get("view", "shared")
    base = dict(mode=MODE, source=SOURCE, where=WHERE, fetched_at=fetched(), fetched_ts=fetched(True), view=view, loaded=False, run=None, sources={}, notes=[],
                mine=mine_state(sid), mine_available=mine_off() is None, mine_note=mine_off(), cache_hours=cache.HOURS if cache.local() else 0,
                sql_copy=sql_copy(view, sid), inside=a.INSIDE, csv=csv_on(), pages=[dict(key=k, label=lab, badge=None, group=GROUP[k]) for k, lab in PAGES.items()
                                              if not (view == "mine" and k in SHARED_ONLY)],
                default_user=None, rule_counts={}, rule_sev={}, prefixes=dict(func=a.FUNC, tech=a.TECH), admin_roles=sorted(a.ADMIN),
                build_roles=list(a.BUILD),
                limits=dict(max_paths=a.MAX_PATHS, max_objects=a.MAX_OBJECTS, max_hops=a.MAX_HOPS,
                            dormant_days=a.DORMANT_DAYS, max_depth_rule=a.MAX_DEPTH_RULE),
                read_privs=sorted(a.READ_PRIVS), sensitive_tags=a.SENSITIVE_TAGS,
                rules=[dict(num=n, title=a.RULES[n][0], why=a.RULES[n][1], severity=a.SEVERITY.get(n, "Low"), critical=a.CRITICAL_WHEN.get(n),
                            area=RULE_INFO.get(n, ("", "Other", "", ""))[1], spot=RULE_INFO.get(n, ("", "", "", ""))[0],
                            meaning=RULE_INFO.get(n, ("", "", "", ""))[2], fix=RULE_INFO.get(n, ("", "", "", ""))[3])
                       for n in sorted(a.RULES, key=int)],
                governance=None, tokens=theme_tokens(), help=ui.HELP,
                type_icon={k: list(v) for k, v in ui.TYPE_ICON.items()}, pclass=ui.PCLASS)
    try:
        key = (data_key(view, sid), view, p.get("builtin") == "1")
        if key[0] and key in META:  # every page view asks for meta: a seen data set answers without LOCK
            run, part = META[key]
        else:
            run, part = meta_part(view, sid, p.get("builtin") == "1")
            if key[0]:
                if len(META) >= 8:
                    META.clear()
                META[key] = run, part
        when, old, at = snap_time(run) if view == "shared" else ("live", False, None)
        base.update(part, run=dict(run_id=str(run.get("RUN_ID")), finished_at=str(run.get("FINISHED_AT"))[:16],
                                   when=when, old=old, at=at))
    except ApiError as x:
        base["error"] = dict(detail=x.detail, message=x.message)
    return clean(base)


META = {}  # (data key, view, builtin) -> (run, the part of meta worked out from the data)


def meta_part(view, sid, builtin):
    with session(view, sid, builtin):
        run = a.run
        worst, hit, hit_rules, rule_counts = rule_badge()
        badge = {"rules": hit, "sensitive": len(S["sens"])}  # findings at the worst severity
        base = dict(loaded=True,
                    sources=run.get("SOURCES") or {"all": "fake data"}, notes=notes_of(run, view) + loop_notes(),
                    pages=[dict(key=k, label=lab, badge=badge.get(k) or None, severity=worst if k == "rules" else None, group=GROUP[k],
                                title=f"{plural(hit, worst.lower() + ' finding')} in {plural(hit_rules, 'rule')}" if k == "rules" and hit else None)
                           for k, lab in PAGES.items() if not (view == "mine" and k in SHARED_ONLY)],
                    governance=a.governance_kpis()["text"] if view == "shared" else None,
                    protection=protection() if view == "shared" else None,
                    builtin=a.builtin_info(), what_if_ops=list(a.WHAT_IF_OPS),
                    rule_counts=rule_counts, rule_sev=home_summary()["rule_sev"],  # the side menu's Findings: severity, then rule
                    people=side_people() if view == "shared" else None,
                    default_user=(a.users[0] if a.users else None) if view == "mine" else None)  # shared: the pages ask for a pick
    return dict(run), base


def rule_badge():
    """meta's findings once per data set: the worst severity found, its findings and rules, and findings per rule."""
    def make():
        worst = next((v for v in ("Critical", "High", "Medium", "Low") if any(x["severity"] == v for x in S["rows"])), None)
        hit = [x["num"] for x in S["rows"] if x["severity"] == worst]
        return worst, len(hit), len(set(hit)), dict(Counter(x["num"] for x in S["rows"]))
    return a.cached("rule_badge", make)


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
                unmasked=home_summary()["protection"]["unmasked"])


BUILD_ONLY_NOTE = ("Started with run.py --build: built from the parts kept, Snowflake is not read. "
                   "Restart without --build to read it again.")


def reload(body):
    """load (the first read) reads the parts still missing and waits for them; rebuild (objects: the CALL first) and
    page (Read Snowflake again) read every part again in the background (refresh)."""
    what = (body or {}).get("what", "page")
    if OFFLINE and what != "load" and MODE == "snowflake":
        return dict(ok=False, result=None, message=BUILD_ONLY_NOTE)
    if what == "load":  # the click that reads the shared data (SOURCE=direct)
        load_shared()
        return dict(ok=True, result=None, message="Loaded.")
    if MODE != "snowflake":
        if what == "rebuild":
            return dict(ok=False, result=None, message="Demo: the CALL runs only on Snowflake (not FAKE=1).")
        cache.drop(KEY)
        return dict(ok=True, result=None, message="Reloaded.")
    return refresh(what)


def refresh(what):
    """Rebuild snapshot / Read Snowflake again, in a thread (BACKGROUND): the pages keep answering from the data they
    have, the new read replaces it only once built, and a failure keeps it. JOB says how it went (/api/progress)."""
    with PLOCK:
        if JOB.get("state") == "running":
            return dict(ok=False, result=None, message="A refresh is already running: see its progress.")
        n = JOB.get("id", 0) + 1
        JOB.clear()
        JOB.update(id=n, what=what, state="running", ok=None, message=None)

    def job():
        try:
            out = renew(what)
        except Exception as x:
            JOB.update(state="failed", ok=False, message=x.message if isinstance(x, ApiError) else a.line(x))
            raise
        JOB.update(state="done" if out["ok"] else "failed", ok=out["ok"], message=out["message"])
        return out
    if not BACKGROUND:
        return job()

    def run():
        try:
            job()
        except Exception:  # its message is in JOB and in the load log
            pass
    threading.Thread(target=run, daemon=True).start()
    return dict(ok=True, started=True, job=n, result=None, message="Reading Snowflake in the background.")


def renew(what):
    """The CALL (rebuild, objects mode), then every part read again under a key of its own, built, and swapped in."""
    new = KEY + ".new"

    def work():
        res = None
        if what == "rebuild" and not DIRECT:
            res = call_snapshot()
            st = (res or {}).get("status")
            if st != "OK":  # SKIPPED (another run still going) or FAILED: say so, and keep the copy we have
                err = ((res or {}).get("notes") or {}).get("error") or "no reason given"
                return dict(ok=False, result=res, message=f"Snapshot {str(st or 'not rebuilt').lower()}: {err}")
        if time.time() - (cache.parts_read_at(new) or 0) > 3600:  # a refresh that failed within the hour resumes
            cache.clear_parts(new)
        d = read_shared(new)
        late = [n for n, m in cache.parts_of(new).items() if m["status"] == "failed"]
        if late:  # timed out (not unreadable: that stays empty with a note): the old data stays
            return dict(ok=False, result=res, message=f"{len(late)} reads timed out: the data you have is kept. "
                        "Click again within the hour to read only those.")
        built(d)
        cache.swap(KEY, new, d)  # its parts become the key's
        compared(d)
        return dict(ok=True, result=res, message="Snapshot rebuilt." if what == "rebuild" and not DIRECT
                    else "Read Snowflake again.")
    with LOAD:
        return tracked(KEY, "shared", work)


def compared(d):
    """What changed of new data set d against the previous snapshot, made while the one it replaced is still kept
    built with its rule findings (a.built), so its first open answers at once. A failure only leaves it to that open."""
    prev = None if a.INSIDE else cache.prev(KEY)
    if not prev or not any(k[0] == shared_key(prev[0]) for k in a.built):  # a same-run refresh keeps an older one:
        return  # building that again would hold every page behind LOCK, so its first open compares
    try:
        with LOCK:
            a.build(d, shared_key(d))
            diff_of(prev[0])
    except Exception as x:
        a.say(f"What changed is compared on its first open instead: {a.line(x)}")


def call_snapshot():
    """CALL SP_ACCESS_SNAPSHOT: the procedure's JSON outcome as a dict; none, NULL or other text: None."""
    sql = f"CALL {WHERE}.SP_ACCESS_SNAPSHOT('AUTO')"
    try:
        r = with_query(lambda q: a.say(f"{sql}: runs in Snowflake, its steps show when it ends") or q(sql))
    except Exception as x:
        raise ApiError(503, "rebuild_failed", a.line(x))
    v = next(iter(r[0].values()), None) if r else None
    try:
        res = json.loads(v) if isinstance(v, str) else v
    except ValueError:
        res = None
    return res if isinstance(res, dict) else None


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


ROUTES = {"home": home_page, "access": access_page, "user": user_page, "privs": privs_page, "held": held_page, "grantees": grantees_page, "role": role_page, "object": object_page, "check": check_page, "sensitive": sensitive_page,
          "rules": rules_page, "review": review_page, "find": find_page, "list": list_page, "graph": graph_page,
          "whatif": whatif_page, "who": who_page, "request": request_page, "map": map_page, "see": see_page,
          "compare": compare_page, "grid": grid_page, "flow": flow_page, "usage": usage_page, "objuse": objuse_page, "changes": changes_page,
          "activity": activity_page, "sql": sql_page, "finding": finding_page}
WITH_REFS = {"request", "who", "access", "user", "role", "object", "check", "sensitive", "rules", "review",
             "whatif", "map", "see", "compare", "grid", "flow", "usage", "objuse", "changes", "activity", "finding"}
CSV = {"rules": rules_csv, "review": review_csv, "whatif": whatif_csv, "privs": privs_csv, "access": access_csv,
       "held": held_csv, "grantees": grantees_csv, "who": who_csv, "flow": flow_csv, "objuse": objuse_csv}


def data_key(view, sid):
    """Which data set a request answers from (the run, or one My access load), None when it isn't loaded."""
    if view == "shared":
        run = load_shared(ask=True).get("run") or {}
        return "shared", run.get("RUN_ID"), str(run.get("FINISHED_AT"))
    m = mine_entry(sid) if view == "mine" else None
    return m and m["key"]


def forget():
    """Drop every answer kept per data set (a new run has a new key; tests reuse one)."""
    for x in (ANSWERS, META, FIND, SAID, WHATIF):
        x.clear()


def serve(name, params=None, sid=None):
    """The JSON answer of one endpoint (a dict), as the local server and the Streamlit components get it. Answers
    depend only on the data set and the parameters, so a repeat comes from ANSWERS without the lock."""
    p = {k: str(v) for k, v in (params or {}).items()}
    dk = data_key(p.get("view", "shared"), sid)
    key = dk and (dk, name, tuple(sorted(p.items())))
    if key in ANSWERS:
        return ANSWERS[key]
    fk = (dk, p.get("builtin") == "1")
    if name == "find" and fk in FIND:  # matched without LOCK; the answer lines of new hits need it, unless it is busy
        out, missing = find_items(p, FIND[fk], fk)
        if not missing:
            return out
        if not LOCK.acquire(blocking=False):
            return out | dict(partial=True)  # the client asks again; the answer lines need LOCK
        LOCK.release()
    with session(p.get("view", "shared"), sid, p.get("builtin") == "1"):
        S["key"] = fk  # the data set, for what a page keeps across calls (FIND, WHATIF)
        out = ROUTES[name](p, p.get("view", "shared"))
        if name in WITH_REFS:
            out["refs"] = mkrefs(out)
        out = clean(out)
    if key:
        if len(ANSWERS) >= MAX_ANSWERS:
            ANSWERS.pop(next(iter(ANSWERS)), None)  # oldest first
        ANSWERS[key] = out
    return out


def csv_on():
    return os.environ.get("CSV", "1") != "0"


def serve_csv(name, params=None, sid=None):
    if not csv_on():
        raise ApiError(403, "csv_off", "CSV export is off here (CSV=0).")
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


FRESH = {"Cache-Control": "no-cache"}  # the page names the bundle of its build: an old copy would show the old app


def make_app():
    from fastapi import FastAPI, Request
    from fastapi.responses import FileResponse, JSONResponse, Response

    from starlette.concurrency import run_in_threadpool
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
        try:
            return await call_next(request)
        except RuntimeError:  # the page was reloaded or closed while a long answer was made: nobody to answer
            if await request.is_disconnected():  # (Starlette says "No response returned"); the work is kept
                return Response(status_code=204)
            raise

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
        return await run_in_threadpool(reload, body)  # a load takes minutes: /api/progress answers meanwhile

    @app.get("/api/progress")
    def progress_(request: Request):
        return progress(request.query_params.get("view"))

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

    async def body_of(request):  # a GET whose query would be too long for a URL (a big change plan) comes as a POST
        try:
            b = await request.json()
        except ValueError:
            b = None
        if not isinstance(b, dict):
            raise ApiError(400, "bad_param", "The body must be a JSON object of parameters.")
        return dict(request.query_params) | {k: str(v) for k, v in b.items() if v is not None}

    def post_route(name):
        async def h(request: Request):
            p = await body_of(request)
            return JSONResponse(await run_in_threadpool(serve, name, p, sid_of(request)))
        return h

    def post_csv(name):
        async def h(request: Request):
            p = await body_of(request)
            fname, text = await run_in_threadpool(serve_csv, name, p, sid_of(request))
            return Response(text, media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={fname}"})
        return h

    for n in ("home", "access", "user", "privs", "held", "grantees", "role", "object", "check", "sensitive", "rules", "review", "find", "list", "graph",
              "whatif", "who", "request", "map", "see", "compare", "grid", "flow", "usage", "objuse", "changes", "activity", "sql", "finding"):
        app.get(f"/api/{n}")(route(n))
        app.post(f"/api/{n}")(post_route(n))

    def csv_route(name):
        def h(request: Request):
            fname, text = serve_csv(name, dict(request.query_params), sid_of(request))
            return Response(text, media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={fname}"})
        return h

    for n in CSV:
        app.get(f"/api/{n}.csv")(csv_route(n))
        app.post(f"/api/{n}.csv")(post_csv(n))

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse(dict(detail="not_found", message="No such endpoint."), status_code=404)
        f = (DIST / path).resolve()
        if path and f.is_file() and DIST.resolve() in f.parents:
            return FileResponse(f, headers=FRESH if f.suffix == ".html" else None)
        if (DIST / "index.html").is_file():
            return FileResponse(DIST / "index.html", headers=FRESH)
        return JSONResponse(dict(detail="not_built", message="The web app is not built: run npm run build in web/."),
                            status_code=404)

    return app


def __getattr__(name):  # `uvicorn server:app` builds the app on first use
    if name == "app":
        g = globals()
        g["app"] = make_app()
        return g["app"]
    raise AttributeError(name)


def quiet_log():
    """uvicorn's logging without the access line of GET /api/progress: the page asks it every second during a load."""
    import uvicorn.config
    c = json.loads(json.dumps(uvicorn.config.LOGGING_CONFIG))
    c["filters"] = {"progress": {"()": f"{__name__}.NoProgress"}}
    c["handlers"]["access"]["filters"] = ["progress"]
    return c


class NoProgress:  # a logging filter: logging.config builds it from its dotted name
    def filter(self, r):
        return "/api/progress" not in r.getMessage()


def export(fresh=False):
    """Stage 1 only (run.py --export): the shared data's missing parts read from Snowflake (fresh: every part), the
    progress lines on the terminal, nothing built. 0 when every part is kept, else 1 (run it again to resume)."""
    if MODE != "snowflake" or not cache.local():
        print("Nothing to export: " + ("FAKE=1 reads no Snowflake." if MODE != "snowflake" else
                                       "CACHE_HOURS=0 or inside Snowflake: nothing is kept on disk."))
        return 1
    if fresh:
        cache.clear_parts(KEY)
    t0 = time.time()
    try:
        with a.progress(lambda x: print(f"{time.time() - t0:7.0f} s  {x}", flush=True)):
            read_shared()
    except Exception as x:
        print(f"Export stopped: {a.line(x)}. Run it again: only the parts still missing are read.")
        return 1
    m = cache.parts_of(KEY)
    bad = [k for k, v in m.items() if v["status"] != "ok"]
    print(f"{len(m)} parts in {cache.parts_dir(KEY)}"
          + (f"; {len(bad)} timed out, read again by the next export or load: " + ", ".join(bad) if bad else ""))
    if bad:
        return 1
    cache.drop(KEY)  # the next start builds from these parts, not from an older local copy
    return 0


if __name__ == "__main__":
    import sys
    if "--export" in sys.argv:
        sys.exit(export("--fresh" in sys.argv))
    import uvicorn
    LOG_LINES = True
    uvicorn.run(make_app(), log_config=quiet_log(), host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("WEB_PORT", "8000")))
