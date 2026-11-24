"""The worksheet SQL of sql/1_setup.sql (table functions, findings procedure) against access.py, on DuckDB in memory.
Run: python test_sql.py (no pytest needed). The function bodies are read from sql/1_setup.sql, so the shipped text is tested."""
import json
import pathlib
import re
import sys
import threading
from collections import Counter
from types import ModuleType, SimpleNamespace

import os

os.environ["FAKE"] = "1"

import duckdb

import access as a

COLS = {
    "GRANT": "GRANTEE_ROLE, PRIVILEGE, GRANTED_ON, OBJECT_NAME, IS_FUTURE, GRANTED_BY",
    "USER_ROLE": "USER_NAME, ROLE_NAME, GRANTED_BY",
    "USER": "USER_NAME, TYPE, DISABLED, DEFAULT_ROLE, DEFAULT_SECONDARY_ROLES, DEFAULT_WAREHOUSE, DEFAULT_NAMESPACE, LAST_SUCCESS_LOGIN",
    "USAGE": "USER_NAME, KIND, NAME, QUERIES, LAST_USED",
    "TAG": "OBJECT_NAME, DOMAIN, COLUMN_NAME, TAG_NAME, TAG_VALUE, APPLY_METHOD",
    "POLICY": "POLICY_NAME, POLICY_KIND, OBJECT_NAME, COLUMN_NAME, ARG_COLUMNS, TAG_NAME, POLICY_BODY",
    "STREAM": "STREAM_NAME, SOURCE_NAME, SOURCE_TYPE",
    "OBJECT_USE": "USER_NAME, OBJECT_NAME, WEEK, ACTION, QUERIES, LAST_USED",
    "ACTIVITY": "DAY, USER_NAME, ROLE_NAME, CLIENT, OBJECT_NAME, ACTION, QUERY_TYPE, QUERIES, LAST_USED, HOURS, APP",
}


def write(db, d):
    """Data set d into the duckdb connection db as the Snowflake TBL_ACCESS_ tables: run log (2 OK runs, 1 failed) + rows of run-2."""
    db.execute("CREATE OR REPLACE TABLE TBL_ACCESS_RUN (RUN_ID VARCHAR, STARTED_AT TIMESTAMP, FINISHED_AT TIMESTAMP, "
               "STATUS VARCHAR, SOURCES VARCHAR, ROW_COUNTS VARCHAR, NOTES VARCHAR)")
    src = json.dumps({"grants": "ACCOUNT_USAGE", "user_roles": "ACCOUNT_USAGE", "future_grants": "SHOW",
                      "users": "ACCOUNT_USAGE", "usage": "ACCOUNT_USAGE", "tags": "ACCOUNT_USAGE",
                      "policies": "ACCOUNT_USAGE", "streams": "SHOW"})
    counts = json.dumps({k: len(d.get(t, [])) for k, t in [("grants", "GRANT"), ("user_roles", "USER_ROLE"), ("users", "USER"),
                                                   ("usage", "USAGE"), ("tags", "TAG"), ("policies", "POLICY"),
                                                   ("streams", "STREAM"), ("object_use", "OBJECT_USE")]})
    db.executemany("INSERT INTO TBL_ACCESS_RUN VALUES (?, ?, ?, ?, ?, ?, ?)", [
        ("run-1", "2026-11-01 07:00", "2026-11-01 07:02", "OK", src, "{}", "{}"),
        ("run-2", "2026-11-02 07:00", "2026-11-02 07:03", "OK", src, counts,
         json.dumps({"future_grants": "1 database skipped — DEMO_DB: insufficient privileges"})),
        ("run-3", "2026-11-02 08:00", None, "FAILED", src, "{}", json.dumps({"error": "demo: failed run, never shown"}))])
    for t, cols in COLS.items():
        names = cols.split(", ")
        types = ["BOOLEAN" if c in ("IS_FUTURE", "DISABLED") else "BIGINT" if c == "QUERIES" else "VARCHAR" for c in names]
        db.execute(f"CREATE OR REPLACE TABLE TBL_ACCESS_{t} (RUN_ID VARCHAR, "
                   + ", ".join(f"{c} {k}" for c, k in zip(names, types)) + ")")
        data = [["run-2"] + [json.dumps(v) if isinstance(v := row.get(c), dict) else v for c in names] for row in d.get(t, [])]
        if data:
            db.executemany(f"INSERT INTO TBL_ACCESS_{t} VALUES ({', '.join(['?'] * (len(names) + 1))})", data)


SETUP = (pathlib.Path(__file__).parent / "sql" / "1_setup.sql").read_text(encoding="utf-8")
PROC_SETTINGS = {"&STATEMENT_TIMEOUT": "300", "&WORKERS": "3", "&ACTIVITY": "1"}  # settings.sql defaults


def proc_text(body):
    """SP_ACCESS_SNAPSHOT's Python with the names run_sql.py fills in."""
    for k, v in PROC_SETTINGS.items():
        body = body.replace(k, v)
    return body.replace("&DB.&SCHEMA", "main").replace("&DB", "main")
LIMITS = [None, 0, 1, 2, 3, 4, 6, 10]
LOCK = threading.Lock()
OBJS = ["SALES.CORE.TBL_CUSTOMER", "FINANCE.REPORT.TBL_REVENUE"]


def duck(sql):
    """Snowflake -> DuckDB, the only changes: tables in DuckDB's default schema, TABLE(f(...)) -> f(...),
    ARRAY_CONSTRUCT -> list_value, ARRAY_CONTAINS(x::VARIANT, arr) -> list_contains(arr, x)."""
    sql = re.sub(r"TABLE\((\w+\(.*?\))\)", r"\1", sql.replace("&DB.&SCHEMA.", ""))
    sql = re.sub(r"ARRAY_CONTAINS\(([\w.]+)::VARIANT, ([\w.]+)\)", r"list_contains(\2, \1)", sql)
    return sql.replace("ARRAY_CONSTRUCT(", "list_value(")


def load(d, build=True):
    """DuckDB with d in TBL_ACCESS_ tables (write below), the table functions as table macros; access.py built from
    the same tables through access.snapshot()."""
    con = duckdb.connect()
    write(con, d)
    for name, args, body in re.findall(r"CREATE OR REPLACE FUNCTION &DB\.&SCHEMA\.(TF_\w+)\((.*?)\)\s*RETURNS TABLE.*?"
                                       r"\$\$(.*?)\$\$", SETUP, re.S):
        params = ", ".join(x.split()[0] for x in args.split(","))
        con.execute(f"CREATE OR REPLACE MACRO {name}({params}) AS TABLE {duck(body)}")
    if build:  # the table functions see Snowflake's built-in grants too
        a.build(a.snapshot(lambda sql: query(con, sql), "main"), builtin=True)
    return con


def query(con, sql, params=None):
    with LOCK:  # snapshot() reads the tables in parallel; one DuckDB connection runs one at a time
        cur = con.execute(sql, params or [])
        cols = [c[0] for c in cur.description or []]
        return [dict(zip(cols, r)) for r in cur.fetchall()] if cols else []


def rows(con, sql, params):
    return Counter(con.execute(sql, params).fetchall())


def same(got, want, what):
    assert got == want, f"{what}: SQL only {list((got - want).items())[:3]}, Python only {list((want - got).items())[:3]}"


def check_access_of(con, name, user, limit):
    def place(o, k):
        db, sc, _ = a.split_name(o, k)
        return db or None, sc or None

    want = Counter((pv, k, *place(o, k), o, a.depth(p, user), " > ".join(p), p[-1])
                   for pv, k, o, p in a.access_of(name, user, limit=limit))
    same(rows(con, "SELECT * FROM TF_ACCESS_OF(?, ?)", [name, limit]), want, f"TF_ACCESS_OF({name}, {limit})")
    return sum(want.values())


def check_who_can(con, obj, priv, limit):
    want = Counter((x, "user" if a.from_user(p) else "role", pv, a.depth(p, a.from_user(p)),
                    " > ".join([a.node_name(p[0])] + p[1:]))
                   for x, pv, p in a.who_can(obj, limit=limit) if priv in (None, pv))
    same(rows(con, "SELECT * FROM TF_WHO_CAN(?, ?, ?)", [obj, priv, limit]), want, f"TF_WHO_CAN({obj}, {priv}, {limit})")
    return sum(want.values())


def check_can(con, user, priv, obj):
    res = a.can(user, priv, obj)
    gap = a.gap_text(res["blocked"])
    want = Counter((" > ".join(r["path"]), r["depth"], r["holder"], False, gap) for r in res["paths"])
    want += Counter((" > ".join(p), len(p) - 2, p[-2], True, gap) for p in res["owner"])
    same(rows(con, "SELECT * FROM TF_CAN(?, ?, ?)", [user, priv, obj]), want, f"TF_CAN({user}, {priv}, {obj})")
    return sum(want.values())


SLOW = os.environ.get("SLOW") == "1"  # every name at every limit (about a minute); else the limits at its edges


def limits(name, user):
    """No limit, 0, 1 and the name's own deepest depth and one less: where a depth limit can go wrong."""
    if SLOW:
        return LIMITS
    deep = max((r["depth"] for r in a.grants(name, user)), default=1)
    return list(dict.fromkeys([None, 0, 1, deep - 1, deep]))


def test_demo():
    con = load(a.fake())
    n = sum(check_access_of(con, u, True, lim) for u in a.users for lim in limits(u, True))
    n += sum(check_access_of(con, r, False, lim) for r in a.roles if r not in a.users for lim in limits(r, False))
    assert n > 1000
    privs = {o: sorted({pv for _, pv, _ in a.on[o]}) for o in a.objects}
    lims = LIMITS if SLOW else [None, 1, 2, 4]
    assert sum(check_who_can(con, o, pv, lim) for o in OBJS for pv in [None] + privs[o] for lim in lims) > 100
    some = [o for o in a.objects if not a.is_builtin(o)] + [o for o in a.objects if a.is_builtin(o)][:5]
    assert sum(check_who_can(con, o, None, None) for o in some) > 100
    assert sum(check_can(con, u, pv, o) for u in a.users for o in OBJS for pv in privs[o] + ["USAGE"]) > 10
    sandbox = "DW.SANDBOX.TBL_SANDBOX_01"  # the fake read role without USAGE on its schema: blocked
    assert sum(check_can(con, u, pv, sandbox) for u in a.users for pv in ("SELECT", "INSERT")) >= 3
    assert a.can("DW_BI_01", "SELECT", sandbox)["blocked"] == [("SCHEMA", "DW.SANDBOX")]
    deep = con.execute("SELECT MAX(DEPTH) FROM TF_ACCESS_OF('FIN_01', NULL)").fetchone()[0]
    assert deep == 10 and con.execute("SELECT MAX(DEPTH) FROM TF_ACCESS_OF('FIN_01', 9)").fetchone()[0] < 10
    assert con.execute("SELECT COUNT(*) FROM TF_CAN('FIN_01', 'DROP', 'NO.SUCH.OBJECT')").fetchone()[0] == 0


def test_cap_and_admin():
    """60-role chain with a cycle back to the start: SQL stops at 50 hops like access.MAX_HOPS; links granted to an
    admin role are dropped, holding one is kept."""
    rs = [f"R{i:02}" for i in range(60)]
    g = [dict(GRANTEE_ROLE=p, PRIVILEGE="USAGE", GRANTED_ON="ROLE", OBJECT_NAME=c, IS_FUTURE=False)
         for p, c in zip(rs, rs[1:] + rs[:1])]
    g += [dict(GRANTEE_ROLE=r, PRIVILEGE="SELECT", GRANTED_ON="TABLE", OBJECT_NAME="D.S.T", IS_FUTURE=False) for r in rs]
    g += [dict(GRANTEE_ROLE="SYSADMIN", PRIVILEGE="USAGE", GRANTED_ON="ROLE", OBJECT_NAME="R00", IS_FUTURE=False),
          dict(GRANTEE_ROLE="R05", PRIVILEGE="USAGE", GRANTED_ON="ROLE", OBJECT_NAME="SYSADMIN", IS_FUTURE=False),
          dict(GRANTEE_ROLE="SYSADMIN", PRIVILEGE="CREATE DATABASE", GRANTED_ON="ACCOUNT", OBJECT_NAME="ACC",
               IS_FUTURE=True)]
    d = dict(run={}, GRANT=g, USER_ROLE=[dict(USER_NAME="U1", ROLE_NAME="R00")], USER=[dict(USER_NAME="U2")],
             USAGE=[dict(USER_NAME="U1")], TAG=[dict(OBJECT_NAME="D.S.T", DOMAIN="TABLE", TAG_NAME="T.S.NOTE", TAG_VALUE="x")],
             POLICY=[dict(OBJECT_NAME="D.S.T")])  # no empty tables
    con = load(d)
    assert a.MAX_HOPS == 50
    for name, user in [("U1", True), ("U2", True), ("R00", False), ("SYSADMIN", False)]:
        for lim in [None, 1, 5, 50, 51, 60]:
            check_access_of(con, name, user, lim)
    for lim in [None, 1, 2, 50, 51, 60]:
        check_who_can(con, "D.S.T", None, lim)
        check_who_can(con, "ACC", "CREATE DATABASE", lim)
    assert con.execute("SELECT MAX(DEPTH) FROM TF_ACCESS_OF('U1', NULL)").fetchone()[0] == 50
    assert con.execute("SELECT MAX(DEPTH) FROM TF_ACCESS_OF('R00', NULL)").fetchone()[0] == 51


def test_edges():
    """Ownership in TF_CAN, a user and a role with one name, a duplicate user-role row, ' > ' in a role name, a NULL
    user name."""
    def grant(p, pv, k, o):
        return dict(GRANTEE_ROLE=p, PRIVILEGE=pv, GRANTED_ON=k, OBJECT_NAME=o, IS_FUTURE=False)

    links = [("X", "R2"), ("A", "B > C"), ("B > C", "C"), ("C", "B"), ("R9", "Z")]
    g = [grant(p, "USAGE", "ROLE", c) for p, c in links]
    g += [grant("R1", "OWNERSHIP", "TABLE", "D.S.T"), grant("R2", "SELECT", "TABLE", "D.S.T"),
          grant("R3", "SELECT", "TABLE", "D.S.T"), grant("B", "SELECT", "TABLE", "D.S.T2"),
          grant("Z", "SELECT", "TABLE", "D.S.Z")]
    ur = [("U", "R1"), ("X", "R2"), ("U2", "R3"), ("U2", "R3"), ("U3", "A"), ("Z", "R9")]
    d = dict(run={}, GRANT=g, USER_ROLE=[dict(USER_NAME=u, ROLE_NAME=r) for u, r in ur], USER=[dict(USER_NAME="U")],
             USAGE=[dict(USER_NAME="U")], TAG=[dict(OBJECT_NAME="D.S.T", DOMAIN="TABLE", TAG_NAME="T.S.N", TAG_VALUE="x")],
             POLICY=[dict(OBJECT_NAME="D.S.T")])
    con = load(d)
    assert check_can(con, "U", "SELECT", "D.S.T") == 1  # owner only: "Yes, via ownership"
    assert rows(con, "SELECT * FROM TF_CAN('U', 'SELECT', 'D.S.T')", []) == Counter([("U > R1 > D.S.T", 1, "R1", True,
                                                                               "no USAGE on database D, no USAGE on schema D.S")])
    for lim in [None, 1, 2]:
        check_who_can(con, "D.S.T", None, lim)
    got = rows(con, "SELECT * FROM TF_WHO_CAN('D.S.T', 'SELECT', NULL)", [])
    assert got[("X", "role", "SELECT", 2, "X > R2")] == 1 and got[("X", "user", "SELECT", 1, "X > R2")] == 1
    assert check_access_of(con, "U2", True, None) == 2  # the duplicate row counts twice, as in access.py
    assert check_access_of(con, "U3", True, None) == 1  # 'B > C' is one role, B is not on the path yet
    # role Z under user Z: users and roles are separate namespaces, the cycle checks cover roles only
    got = rows(con, "SELECT PATH, DEPTH FROM TF_ACCESS_OF('Z', NULL) WHERE OBJECT_NAME = 'D.S.Z'", [])
    assert got == Counter([("Z > R9 > Z", 2)]) and check_access_of(con, "Z", True, None) == 1
    n = con.execute("SELECT COUNT(*) FROM TF_ACCESS_OF('R1', NULL)").fetchone()[0]
    con = load(dict(d, USER=d["USER"] + [dict(USER_NAME=None)]), build=False)
    assert n == 1 and con.execute("SELECT COUNT(*) FROM TF_ACCESS_OF('R1', NULL)").fetchone()[0] == 1


def test_blocked():
    """TF_CAN's BLOCKED as access.can(): a grant without USAGE on the schema is blocked; USAGE from another role the
    user holds counts, a database role has its own database, a future grant does not count, an admin role misses
    nothing."""
    def grant(p, pv, k, o, future=False):
        return dict(GRANTEE_ROLE=p, PRIVILEGE=pv, GRANTED_ON=k, OBJECT_NAME=o, IS_FUTURE=future)

    g = [grant(r, "SELECT", "TABLE", "D.S.T") for r in ("R1", "R2", "R3", "R5", "D.DR")]
    g += [grant(r, "USAGE", "DATABASE", "D") for r in ("R1", "R2", "R3")]
    g += [grant("R2", "USAGE", "SCHEMA", "D.S"), grant("D.DR", "USAGE", "SCHEMA", "D.S"),
          grant("R3", "USAGE", "SCHEMA", "D.<SCHEMA>", True), grant("R4", "USAGE", "DATABASE_ROLE", "D.DR"),
          grant("R5", "USAGE", "ROLE", "SYSADMIN"), grant("R6", "SELECT", "TABLE", "E.S.T"),
          grant("R6", "IMPORTED PRIVILEGES", "DATABASE", "E")]  # a shared database: its schemas need nothing more
    ur = [("U1", "R1"), ("U2", "R2"), ("U3", "R3"), ("U4", "R4"), ("U5", "R5"), ("U6", "R1"), ("U6", "R2"), ("U7", "R6")]
    d = dict(run={}, GRANT=g, USER_ROLE=[dict(USER_NAME=u, ROLE_NAME=r) for u, r in ur], USER=[dict(USER_NAME="U1")],
             USAGE=[dict(USER_NAME="U1")], TAG=[dict(OBJECT_NAME="D.S.T", DOMAIN="TABLE", TAG_NAME="T.S.N", TAG_VALUE="x")],
             POLICY=[dict(OBJECT_NAME="D.S.T")])
    con = load(d)
    want = dict(U1="no USAGE on schema D.S", U2=None, U3="no USAGE on schema D.S", U4=None, U5=None, U6=None)
    for u, gap in want.items():
        assert check_can(con, u, "SELECT", "D.S.T") >= 1
        assert {r[4] for r in con.execute("SELECT * FROM TF_CAN(?, 'SELECT', 'D.S.T')", [u]).fetchall()} == {gap}, u
        assert a.gap_text(a.can(u, "SELECT", "D.S.T")["blocked"]) == gap, u
    assert {r[4] for r in con.execute("SELECT * FROM TF_CAN('U7', 'SELECT', 'E.S.T')").fetchall()} == {None}
    assert a.can("U7", "SELECT", "E.S.T")["blocked"] == []


class Row(dict):  # a Snowpark Row: row["N"] and row.as_dict()
    def as_dict(self):
        return dict(self)


def fake_session(con):
    """The parts of a Snowpark session SP_ACCESS_FINDINGS uses, on DuckDB."""
    def sql(text, params=None):
        found = query(con, text, params)
        return SimpleNamespace(collect=lambda **k: [Row(r) for r in found])

    def create_dataframe(data, schema):
        def save(table, mode, column_order, **k):
            con.executemany(f"INSERT INTO {table} ({', '.join(schema)}) VALUES ({', '.join('?' * len(schema))})", data)
        return SimpleNamespace(write=SimpleNamespace(save_as_table=save))

    return SimpleNamespace(sql=sql, create_dataframe=create_dataframe)


def test_findings():
    con = load(a.fake())
    ddl = re.search(r"CREATE TABLE IF NOT EXISTS &DB\.&SCHEMA\.TBL_ACCESS_FINDING .*?\);", SETUP, re.S).group(0)
    con.execute(duck(ddl).replace("TIMESTAMP_LTZ", "TIMESTAMPTZ").replace("CURRENT_TIMESTAMP()", "current_timestamp"))
    body = re.search(r"PROCEDURE &DB\.&SCHEMA\.SP_ACCESS_FINDINGS.*?\$\$(.*?)\$\$", SETUP, re.S).group(1)
    ns = {}
    if "snowflake.snowpark.types" not in sys.modules:  # Snowpark is not installed here: the schema = column names
        types = ModuleType("snowflake.snowpark.types")
        types.StringType, types.StructField, types.StructType = str, lambda name, t: name, list
        sys.modules.update({"snowflake": ModuleType("snowflake"), "snowflake.snowpark": ModuleType("snowflake.snowpark"),
                            "snowflake.snowpark.types": types})
    exec(body.replace("&DB.&SCHEMA", "main"), ns)
    session = fake_session(con)
    con.execute("INSERT INTO TBL_ACCESS_FINDING (RUN_ID, RULE_NUM) VALUES ('run-1', '1')")  # an older run's finding
    for _ in range(2):  # the second CALL replaces the run's rows; only the last run's findings stay
        out = ns["run"](session, None)
        want = Counter(f"{n} {t}" for n, t, *_ in a.checks())  # on the data the procedure just built
        assert out["run_id"] == "run-2" and out["per_rule"] == dict(want) and out["findings"] == sum(want.values())
        assert con.execute("SELECT COUNT(*) FROM TBL_ACCESS_FINDING").fetchone()[0] == out["findings"] > 0
    out = ns["run"](session, json.dumps({"MAX_DEPTH_RULE": 3}))
    assert any(k.startswith("14 Chain deeper than 3") for k in out["per_rule"])
    assert out["per_rule"] != dict(want)
    out = ns["run"](session, "{}")  # settings from an earlier CALL do not stick
    assert out["per_rule"] == dict(want)
    try:
        ns["run"](session, '{"NO_SUCH": 1}')
        raise AssertionError("unknown setting accepted")
    except ValueError:
        pass


def test_streams():
    """SP_ACCESS_SNAPSHOT's streams step: ACCOUNT_USAGE.STREAMS rows (or SHOW STREAMS when it is not readable) ->
    TBL_ACCESS_STREAM; both refused -> UNAVAILABLE."""
    con = load(a.fake(), build=False)
    body = re.search(r"PROCEDURE &DB\.&SCHEMA\.SP_ACCESS_SNAPSHOT.*?\$\$(.*?)\$\$", SETUP, re.S).group(1)
    ns = {}
    exec(proc_text(body), ns)
    session = fake_session(con)
    show = [dict(database_name="D", schema_name="S", name='"ST 1"', table_name='D.S."T"', source_type="Table")]
    sql = session.sql

    au = [dict(STREAM="D.S.ST 2", TABLE_NAME="D.S.T2", SOURCE_TYPE="View")]

    def fake_sql(text, params=None):
        got = show if text.startswith("SHOW STREAMS") else au if "ACCOUNT_USAGE.STREAMS" in text else None
        if got is None and not text.startswith("SHOW STREAMS") and "ACCOUNT_USAGE.STREAMS" not in text:
            return sql(text, params)
        return SimpleNamespace(collect=lambda **k: [SimpleNamespace(as_dict=lambda r=r: r) for r in got])

    session.sql = fake_sql
    assert ns["streams"](session, "run-7", "ACCOUNT_USAGE") == ("ACCOUNT_USAGE", None)  # one query, not SHOW
    got = con.execute("SELECT * FROM TBL_ACCESS_STREAM WHERE RUN_ID = 'run-7'").fetchall()
    assert got == [("run-7", "D.S.ST 2", "D.S.T2", "View")]
    au = None  # not iterable: ACCOUNT_USAGE refused -> SHOW
    assert ns["streams"](session, "run-9", "ACCOUNT_USAGE") == ("SHOW", None)
    got = con.execute("SELECT * FROM TBL_ACCESS_STREAM WHERE RUN_ID = 'run-9'").fetchall()
    assert got == [("run-9", "D.S.ST 1", "D.S.T", "Table")]
    show = None  # both refused
    assert ns["streams"](session, "run-8", "ACCOUNT_USAGE")[0] == "UNAVAILABLE"


def test_object_use():
    """SP_ACCESS_SNAPSHOT's object usage step: the same ACCESS_HISTORY SELECT as access.use_sql(); not readable (DuckDB
    has no ACCESS_HISTORY) -> UNAVAILABLE with the reason, no rows, the run goes on."""
    import inspect
    assert inspect.getsource(a.use_sql) in SETUP
    con = load(a.fake(), build=False)
    body = re.search(r"PROCEDURE &DB\.&SCHEMA\.SP_ACCESS_SNAPSHOT.*?\$\$(.*?)\$\$", SETUP, re.S).group(1)
    ns = {}
    exec(proc_text(body), ns)
    session = fake_session(con)
    src, why = ns["object_use"](session, "run-9", ns["fallback"](session, "ACCESS_HISTORY", "AUTO"))()  # run()'s probe
    assert src == "UNAVAILABLE" and "ACCESS_HISTORY" in why
    assert ns["object_use"](session, "run-9", ns["fallback"](session, "ACCESS_HISTORY", "SHOW"))()[0] == "UNAVAILABLE"
    assert not con.execute("SELECT * FROM TBL_ACCESS_OBJECT_USE WHERE RUN_ID = 'run-9'").fetchall()
    assert "OBJECT_USE" in ns["DATA"][-2] and 'keep("object_use"' in body


def test_activity():
    """SP_ACCESS_SNAPSHOT's activity step: the same SELECT as access.activity_sql(); not readable (DuckDB has no
    ACCESS_HISTORY) -> UNAVAILABLE with the reason, no rows, the run goes on."""
    import inspect
    assert inspect.getsource(a.activity_sql) in SETUP
    con = load(a.fake(), build=False)
    body = re.search(r"PROCEDURE &DB\.&SCHEMA\.SP_ACCESS_SNAPSHOT.*?\$\$(.*?)\$\$", SETUP, re.S).group(1)
    ns = {}
    exec(proc_text(body).replace("&QUERY_TAG", a.QUERY_TAG)
         .replace("&STREAMLIT_APP", a.APP_ST), ns)
    assert ns["ACTIVITY_DAYS"] == a.ACTIVITY_DAYS and ns["QUERY_TAG"] == a.QUERY_TAG and ns["APP_ST"] == a.APP_ST
    session = fake_session(con)
    src, why = ns["activity"](session, "run-9", ns["fallback"](session, "ACCESS_HISTORY", "AUTO"))()
    assert src == "UNAVAILABLE" and "ACCESS_HISTORY" in why
    assert not con.execute("SELECT * FROM TBL_ACCESS_ACTIVITY WHERE RUN_ID = 'run-9'").fetchall()
    assert "ACTIVITY" in ns["DATA"][-1] and 'keep("activity"' in body


def test_show_fallback():
    """SP_ACCESS_SNAPSHOT's SHOW fallback and access.live() (Direct mode) give the same role grants, database-role
    grants and user roles from the same SHOW answers, and an unreadable database role skips only itself in both."""
    import test_access
    d = a.fake()
    bad = next(g["GRANTEE_ROLE"] for g in d["GRANT"] if "." in g["GRANTEE_ROLE"])  # one database role
    half = next(x["ROLE_NAME"] for x in d["USER_ROLE"]  # a role with grants and users: its SHOW GRANTS OF is refused
                if any(g["GRANTEE_ROLE"] == x["ROLE_NAME"] and not g["IS_FUTURE"] for g in d["GRANT"]))
    show, _ = test_access.fake_snowflake(d, au=False)
    refuse = {"SHOW GRANTS TO DATABASE ROLE " + a.db_ident(bad), f'SHOW GRANTS OF ROLE "{half}"',
              'SHOW FUTURE GRANTS IN DATABASE "SALES"'}  # the database place before SALES.CORE, which has future grants

    def answer(sql):
        if " ".join(sql.split()) in refuse:
            raise RuntimeError("Insufficient privileges")
        return show(sql)

    con = load(d, build=False)
    for t, c, k in (("GRANT", "GRANT_OPTION", "BOOLEAN"), ("GRANT", "GRANTED_BY", "VARCHAR"), ("USER_ROLE", "GRANTED_BY", "VARCHAR")):
        con.execute(f"ALTER TABLE TBL_ACCESS_{t} ADD COLUMN IF NOT EXISTS {c} {k}")  # the full columns of 1_setup.sql
    body = re.search(r"PROCEDURE &DB\.&SCHEMA\.SP_ACCESS_SNAPSHOT.*?\$\$(.*?)\$\$", SETUP, re.S).group(1)
    ns = {}
    exec(proc_text(body), ns)
    session = fake_session(con)
    duck_sql = session.sql

    sent = []  # statements started as async child jobs (many()); a refusal comes from result(), as in Snowpark

    def sql(text, params=None):
        if text.lstrip().upper().startswith("SHOW") or "ACCOUNT_USAGE" in text or ".INFORMATION_SCHEMA." in text:
            got = lambda **k: [SimpleNamespace(as_dict=lambda r=r: r) for r in answer(text)]  # noqa: E731
            return SimpleNamespace(collect=got, collect_nowait=lambda **k: sent.append(text) or SimpleNamespace(result=got))
        return duck_sql(text, params)

    session.sql = sql
    out = ns["grants"](session, "run-9", "SHOW")
    assert out["grants"][0] == "SHOW" and f"{bad}: Insufficient privileges" in out["grants"][1], out
    assert ns["objects"](session, "run-9", "SHOW")[0] == "SHOW"  # the Streamlit apps and notebooks SHOW GRANTS lacks
    assert ns["app_grants_step"](session, "run-9") == ("SHOW", None)  # and the grants on the apps
    proc = Counter((r["GRANTEE_ROLE"], r["PRIVILEGE"], r["GRANTED_ON"], r["OBJECT_NAME"])
                   for r in query(con, "SELECT * FROM TBL_ACCESS_GRANT WHERE RUN_ID = 'run-9'"))
    assert any(k[1:3] == ("USAGE", "STREAMLIT") for k in proc)
    proc_users = Counter((r["USER_NAME"], r["ROLE_NAME"]) for r in query(con, "SELECT * FROM TBL_ACCESS_USER_ROLE WHERE RUN_ID = 'run-9'"))
    live = a.live(answer)
    direct = Counter((g["GRANTEE_ROLE"], g["PRIVILEGE"], g["GRANTED_ON"], g["OBJECT_NAME"]) for g in live["GRANT"] if not g["IS_FUTURE"])
    same(proc, direct, "SHOW grants")
    same(proc_users, Counter((x["USER_NAME"], x["ROLE_NAME"]) for x in live["USER_ROLE"]), "SHOW user roles")
    assert not any(k[0] == bad for k in proc) and any("." in k[0] for k in proc)  # the other database roles are read
    assert f"{bad}: " in str(live["run"].get("NOTES"))
    assert f"{half}: Insufficient privileges" in out["grants"][1] and not any(k[0] == half for k in proc)
    assert not any(r == half for _, r in proc_users)
    got = ns["future"](session, "run-10", "AUTO")  # one refused place skips only itself, as in live()
    (src, why), schemas = got["future_grants"], got["schemas"]
    assert schemas[0] == "SHOW" and "ACCOUNT_USAGE.SCHEMATA" in schemas[1] and "database list from SHOW" in schemas[1]
    fut = Counter((r["GRANTEE_ROLE"], r["PRIVILEGE"], r["GRANTED_ON"], r["OBJECT_NAME"])
                  for r in query(con, "SELECT * FROM TBL_ACCESS_GRANT WHERE RUN_ID = 'run-10'"))
    same(fut, Counter((g["GRANTEE_ROLE"], g["PRIVILEGE"], g["GRANTED_ON"], g["OBJECT_NAME"])
                      for g in live["GRANT"] if g["IS_FUTURE"]), "SHOW future grants")
    assert src == "SHOW" and why.startswith("1 database") and "SALES: " in why and sum(fut.values()) == 2
    assert any(x.startswith("SHOW GRANTS OF ROLE") for x in sent) and any(x.startswith("SHOW FUTURE GRANTS") for x in sent)
    ns["ASYNC"], sent[:] = False, []  # run()'s probe job gave no rows: the same result, one statement after another
    assert ns["grants"](session, "run-11", "SHOW") == out and not sent
    ns["objects"](session, "run-11", "SHOW")
    ns["app_grants_step"](session, "run-11")
    assert Counter((r["GRANTEE_ROLE"], r["PRIVILEGE"], r["GRANTED_ON"], r["OBJECT_NAME"])
                   for r in query(con, "SELECT * FROM TBL_ACCESS_GRANT WHERE RUN_ID = 'run-11'")) == proc
    ns["ASYNC"] = True
    refuse.clear()  # a future grant row without a grantee: left out with a note, as tidy() does in Direct mode
    show_before = show
    show = lambda q: show_before(q) + ([dict(grant_to="ROLE", grantee_name=None, privilege="SELECT", grant_on="TABLE",  # noqa: E731
                                             name="X.Y.<TABLE>")] if q.startswith("SHOW FUTURE GRANTS IN DATABASE") else [])
    src, why = ns["future"](session, "run-12", "SHOW")["future_grants"]
    assert src == "SHOW" and re.fullmatch(r"[1-9]\d* future grant rows? without a name left out", why or ""), why

    def refused(text, params=None):  # SOURCE=direct inside Snowflake when even SHOW DATABASES is refused
        if text.lstrip().upper().startswith("SHOW DATABASES"):
            raise RuntimeError("SHOW DATABASES is not allowed")
        return sql(text, params)

    session.sql = refused
    src, why = ns["future"](session, "run-13", "SHOW")["future_grants"]
    assert src == "UNAVAILABLE" and "not allowed" in why and why.startswith("P_SOURCE = SHOW: ACCOUNT_USAGE not read"), why  # the run goes on, as access.live() does
    session.sql = sql  # the schema list from ACCOUNT_USAGE, else INFORMATION_SCHEMA: the same future grants, no SHOW SCHEMAS
    for au, info, want in ((True, False, "ACCOUNT_USAGE"), (False, True, "INFORMATION_SCHEMA")):
        show, _ = test_access.fake_snowflake(d, au, info)
        sent[:] = []
        got = ns["future"](session, f"run-{want}", "AUTO")
        assert got["schemas"][0] == want and got["future_grants"] == ("SHOW", None), got
        assert not [x for x in sent if x.startswith("SHOW SCHEMAS") or x.startswith("SHOW DATABASES")], sent
        same(Counter((r["GRANTEE_ROLE"], r["PRIVILEGE"], r["GRANTED_ON"], r["OBJECT_NAME"])
                     for r in query(con, f"SELECT * FROM TBL_ACCESS_GRANT WHERE RUN_ID = 'run-{want}'")), fut, f"future grants, schemas from {want}")
    got = ns["future"](session, "run-x", "SHOW")["schemas"]  # P_SOURCE = SHOW: no ACCOUNT_USAGE, the note says so
    assert got == ("INFORMATION_SCHEMA", "P_SOURCE = SHOW: ACCOUNT_USAGE not read"), got
    hidden = {"SHOW FUTURE GRANTS IN DATABASE \"SALES\"", "SHOW FUTURE GRANTS IN SCHEMA \"SALES\".\"CORE\""}
    show_au = show  # a database this role cannot see (ACCOUNT_USAGE lists it): left out, no note

    def show(q):
        if " ".join(q.split()) in hidden:
            raise RuntimeError("Database 'SALES' does not exist or not authorized.")
        return show_au(q)
    got = ns["future"](session, "run-y", "AUTO")
    assert got["schemas"][0] == "INFORMATION_SCHEMA" and got["future_grants"] == ("SHOW", None), got


def test_objects():
    """SP_ACCESS_SNAPSHOT's object inventory (the same functions as access.live): an object with no grant row becomes an
    OWNERSHIP row of its owner, one already owned in the grant read adds nothing, one no role owns is kept with no
    grantee, a refused read leaves a note and the rest still loads."""
    import inspect
    for f in (a.inventory_sql, a.inventory_seen, a.inventory_rows, a.inventory_read, a.schema_list, a.app_grants):
        assert inspect.getsource(f) in SETUP, f.__name__
    con = load(a.fake(), build=False)
    for c, k in (("GRANT_OPTION", "BOOLEAN"), ("GRANTED_BY", "VARCHAR")):
        con.execute(f"ALTER TABLE TBL_ACCESS_GRANT ADD COLUMN IF NOT EXISTS {c} {k}")
    con.execute("INSERT INTO TBL_ACCESS_GRANT (RUN_ID, GRANTEE_ROLE, PRIVILEGE, GRANTED_ON, OBJECT_NAME, IS_FUTURE) VALUES "
                "('run-9', 'R_OWN', 'OWNERSHIP', 'FUNCTION', 'D.S.FN(NUMBER):NUMBER(38,0)', FALSE), "
                "('run-9', 'R_USE', 'USAGE', 'STREAMLIT', 'D.S.APP', FALSE)")
    ns, session = snapshot_proc(), fake_session(con)
    duck_sql = session.sql
    steps = ns["inventory_sql"]()
    au = {q: n for n, _, q, _, _ in steps if q}
    shows = {q: n for n, *_, show in steps for q, _ in show}
    answers = {  # (level, step) -> rows; a missing one is refused
        ("AU", "FUNCTIONS"): [dict(DATABASE_NAME="D", SCHEMA_NAME="S", NAME="FN(X NUMBER)", OWNER="R_OWN", OWNER_ROLE_TYPE="ROLE")],
        ("IS", "DATABASES"): [dict(DATABASE_NAME=None, SCHEMA_NAME=None, NAME="D", OWNER="R_DB", OWNER_ROLE_TYPE="ROLE",
                                   TYPE="STANDARD"), dict(NAME="SHARED", OWNER=None, TYPE="IMPORTED DATABASE")],
        ("IS", "TABLES"): [dict(DATABASE_NAME="D", SCHEMA_NAME="S", NAME="T_NEW", OWNER="R_T", OWNER_ROLE_TYPE=None, KIND="TABLE")],
        ("SHOW", "SHOW STREAMLITS IN ACCOUNT"): [dict(database_name="D", schema_name="S", name="APP", owner="R_APP",
                                                      owner_role_type="ROLE")],
        ("SHOW", "SHOW NOTEBOOKS IN ACCOUNT"): [
            dict(database_name="D", schema_name="S", name="NB", owner="DBR", owner_role_type="DATABASE_ROLE"),
            dict(database_name="D", schema_name="S", name="NB2", owner=None, owner_role_type=None)],
        ("SHOW", "SHOW WAREHOUSES"): [dict(name="WH_NEW", owner="R_WH")],
        ("SHOW", "SHOW VIEWS IN ACCOUNT"): [dict(database_name="D", schema_name="S", name="V_SHOW", owner="R_V"),
                                            dict(database_name="D", schema_name="S", name="MV", owner="R_V", is_materialized="true"),
                                            dict(database_name="D", schema_name="INFORMATION_SCHEMA", name="TABLES", owner="")],
        ("SHOW", "SHOW TABLES IN ACCOUNT"): [dict(database_name="D", schema_name="S", name="T_SHOW", owner="R_T", kind="TABLE"),
                                             dict(database_name="D", schema_name="S", name="T_ICE", owner="R_T", kind="TABLE",
                                                  is_iceberg="Y", is_hybrid="N"),
                                             dict(database_name="D", schema_name="S", name="T_TMP", owner="R_T", kind="TEMPORARY")]}
    sent = []

    def sql(text, params=None):
        if text in au:
            key = ("AU", au[text])
        elif ".INFORMATION_SCHEMA." in text:  # one database's INFORMATION_SCHEMA: DATABASES once, the others per database
            key = ("IS", re.search(r"INFORMATION_SCHEMA\.(\w+)", text)[1])
            assert key[1] == "DATABASES" or text.startswith("SELECT") and '"D".' in text, text  # never the shared database
        elif text in shows:
            key = ("SHOW", text)
        else:
            return duck_sql(text, params)
        sent.append(key)

        def got(**k):
            if key not in answers:
                raise RuntimeError("Object does not exist or not authorized.")
            return [Row(r) for r in answers[key]]
        return SimpleNamespace(collect=got, collect_nowait=lambda **k: SimpleNamespace(result=got))

    def owned(run):
        return sorted(((r["GRANTEE_ROLE"], r["GRANTED_ON"], r["OBJECT_NAME"]) for r in query(
            con, f"SELECT * FROM TBL_ACCESS_GRANT WHERE RUN_ID = '{run}' AND GRANTEE_ROLE IS DISTINCT FROM 'R_USE' "
                 "AND GRANTEE_ROLE IS DISTINCT FROM 'R_OWN'")), key=str)
    session.sql = sql
    src, note = ns["objects"](session, "run-9", "AUTO")  # functions from ACCOUNT_USAGE, tables from INFORMATION_SCHEMA
    assert src == "ACCOUNT_USAGE + INFORMATION_SCHEMA + SHOW" and "owner role" not in note, note
    assert "TABLES: INFORMATION_SCHEMA (SNOWFLAKE.ACCOUNT_USAGE.TABLES: Object does not exist" in note, note  # why lower
    assert "INTEGRATIONS: SNOWFLAKE.ACCOUNT_USAGE.INTEGRATIONS: Object does not exist" in note, note  # no lower level
    assert ("SHOW", "SHOW TABLES IN ACCOUNT") not in sent and ("IS", "FUNCTIONS") not in sent  # one level each
    app = [("R_APP", "STREAMLIT", "D.S.APP"), ("D.DBR", "NOTEBOOK", "D.S.NB"), (None, "NOTEBOOK", "D.S.NB2"),
           ("R_WH", "WAREHOUSE", "WH_NEW")]
    dbs = [("R_DB", "DATABASE", "D"), (None, "DATABASE", "SHARED")]  # every database is an object, a share too
    assert owned("run-9") == sorted(app + dbs + [("R_T", "TABLE", "D.S.T_NEW")], key=str), owned("run-9")  # the function: no 2nd row
    sent.clear()
    src, note = ns["objects"](session, "run-10", "SHOW")  # P_SOURCE = SHOW: no ACCOUNT_USAGE, the note says why
    assert src == "INFORMATION_SCHEMA + SHOW" and "TABLES: INFORMATION_SCHEMA (P_SOURCE = SHOW: ACCOUNT_USAGE not read)" in note, note
    assert not [k for k in sent if k[0] == "AU"] and owned("run-10") == owned("run-9")
    for k in [k for k in answers if k[0] == "IS"]:  # INFORMATION_SCHEMA refused too: SHOW, without temporary tables
        answers.pop(k)
    src, note = ns["objects"](session, "run-11", "SHOW")
    assert src == "SHOW" and "INFORMATION_SCHEMA.DATABASES: Object does not exist" in note, note
    assert owned("run-11") == sorted(app + [("R_T", "TABLE", "D.S.T_SHOW"), ("R_V", "VIEW", "D.S.V_SHOW"),  # kinds as
                                            ("R_T", "ICEBERG TABLE", "D.S.T_ICE"), ("R_V", "MATERIALIZED VIEW", "D.S.MV")],
                                     key=str), owned("run-11")  # ACCOUNT_USAGE names them


def snapshot_proc():
    body = re.search(r"PROCEDURE &DB\.&SCHEMA\.SP_ACCESS_SNAPSHOT.*?\$\$(.*?)\$\$", SETUP, re.S).group(1)
    ns = {}
    exec(proc_text(body), ns)
    return ns


def test_run_overlap():
    """SP_ACCESS_SNAPSHOT's run(): a CALL while another started in the last hour steps back, also when both insert their
    RUNNING row at once; an OK run keeps the rows of a run still running (started over an hour ago)."""
    con = load(a.fake(), build=False)
    con.execute("CREATE MACRO PARSE_JSON(x) AS x")
    ns = snapshot_proc()
    session = fake_session(con)
    duck_sql = session.sql
    race = []

    def sql(text, params=None):  # Snowflake's DATEADD / CURRENT_TIMESTAMP() in DuckDB
        text = re.sub(r"DATEADD\((\w+), (-?\d+), CURRENT_TIMESTAMP\(\)\)", r"(current_timestamp + INTERVAL (\2) \1)", text)
        if text.startswith("INSERT INTO main.TBL_ACCESS_RUN") and race:  # another CALL's row lands first
            con.execute(f"INSERT INTO TBL_ACCESS_RUN (RUN_ID, STARTED_AT, STATUS) VALUES ('{race.pop()}', "
                        "current_timestamp - INTERVAL 1 SECOND, 'RUNNING')")
        return duck_sql(text.replace("CURRENT_TIMESTAMP()", "current_timestamp"), params)

    session.sql = sql
    step = lambda *x: ("SHOW", None)  # noqa: E731
    ns.update({k: step for k in ("users", "tags", "policies", "streams", "objects", "app_grants_step")})
    ns["future"] = lambda *x: {"schemas": ("SHOW", None), "future_grants": ("SHOW", None)}
    ns.update({k: lambda *x: lambda: ("SHOW", None) for k in ("usage", "object_use", "activity")})  # wait() of a job

    def grants(session, run_id, mode):
        con.execute(f"INSERT INTO TBL_ACCESS_GRANT (RUN_ID, GRANTEE_ROLE) VALUES ('{run_id}', 'R')")
        return {"grants": ("SHOW", None), "user_roles": ("SHOW", None)}

    ns["grants"] = grants
    con.execute("INSERT INTO TBL_ACCESS_RUN (RUN_ID, STARTED_AT, STATUS) VALUES ('run-a', current_timestamp - INTERVAL 2 HOUR, 'RUNNING')")
    con.execute("INSERT INTO TBL_ACCESS_GRANT (RUN_ID, GRANTEE_ROLE) VALUES ('run-a', 'R')")
    out = ns["run"](session, "SHOW")
    left = dict(con.execute("SELECT RUN_ID, COUNT(*) FROM TBL_ACCESS_GRANT GROUP BY 1").fetchall())
    assert out["status"] == "OK" and left == {out["run_id"]: 1, "run-a": 1}, left  # run-2's rows gone, run-a's kept
    runs = con.execute("SELECT COUNT(*) FROM TBL_ACCESS_RUN").fetchone()[0]
    con.execute("INSERT INTO TBL_ACCESS_RUN (RUN_ID, STARTED_AT, STATUS) VALUES ('run-b', current_timestamp, 'RUNNING')")
    out = ns["run"](session, "SHOW")
    assert out == {"status": "SKIPPED", "notes": {"error": "run run-b is still running"}}
    assert con.execute("SELECT COUNT(*) FROM TBL_ACCESS_RUN").fetchone()[0] == runs + 1  # no row left by the skipped CALL
    con.execute("DELETE FROM TBL_ACCESS_RUN WHERE RUN_ID = 'run-b'")
    race.append("run-c")
    out = ns["run"](session, "SHOW")
    assert out == {"status": "SKIPPED", "notes": {"error": "run run-c is still running"}}, out
    con.execute("DELETE FROM TBL_ACCESS_RUN WHERE RUN_ID = 'run-c'")
    waited = []  # a step that fails the run: the jobs already started end before its rows are deleted

    def broken(session, run_id, mode):
        raise RuntimeError("SHOW ROLES refused")

    ns["grants"] = broken
    ns["object_use"] = lambda *x: lambda: waited.append(1) or ("ACCOUNT_USAGE", None)
    out = ns["run"](session, "SHOW")
    assert out["status"] == "FAILED" and waited == [1] and "object_use" not in out["sources"], out


def test_usage_extra():
    """ACCOUNT_USAGE.QUERY_HISTORY readable but the usage read fails (a timeout): usage UNAVAILABLE, the run goes on,
    as in access.live()."""
    con = load(a.fake(), build=False)
    ns = snapshot_proc()
    session = fake_session(con)
    duck_sql = session.sql

    def sql(text, params=None):
        if "ACCOUNT_USAGE.QUERY_HISTORY LIMIT 1" in text:
            return SimpleNamespace(collect=lambda **k: [])
        if "ACCOUNT_USAGE.QUERY_HISTORY" in text:
            raise RuntimeError("Statement reached its statement or warehouse timeout")
        return duck_sql(text, params)

    session.sql = sql
    timeout = ("UNAVAILABLE", "stopped after 5 min (STATEMENT_TIMEOUT=300); set STATEMENT_TIMEOUT=600 for 10 minutes in "
               "settings.local.sql and run sql/1_setup.sql again; Statement reached its statement or warehouse timeout")
    assert ns["usage"](session, "run-9", "AUTO")() == timeout
    assert not con.execute("SELECT * FROM TBL_ACCESS_USAGE WHERE RUN_ID = 'run-9'").fetchall()

    def slow(text, params=None):  # started as an async job that fails later: its rows are deleted, the step alone fails
        if "ACCOUNT_USAGE.QUERY_HISTORY" in text and "LIMIT 1" not in text:
            con.execute("INSERT INTO TBL_ACCESS_USAGE (RUN_ID, USER_NAME) VALUES ('run-8', 'U')")  # a half-done insert
            return SimpleNamespace(collect_nowait=lambda **k: SimpleNamespace(result=lambda: sql(text)))
        return sql(text, params)

    session.sql = slow
    wait = ns["usage"](session, "run-8", "AUTO")
    assert wait() == wait() == timeout
    assert not con.execute("SELECT * FROM TBL_ACCESS_USAGE WHERE RUN_ID = 'run-8'").fetchall()


def test_object_use_weeks():
    """Object use copies the last OK run's weeks but its last two and reads ACCESS_HISTORY from that Monday on
    (SP_ACCESS_SNAPSHOT, and access.use_start in Direct mode): the same rows as a read of every week of the window."""
    import random
    from datetime import datetime, timedelta
    rnd, t0 = random.Random(7), datetime(2026, 11, 2, 7)
    log = [(f"q{i}", rnd.choice("AB"), rnd.choice(["D.S.T1", "D.S.T2"]), rnd.choice(["READ", "WRITE"]),
            t0 - timedelta(days=200) + timedelta(hours=rnd.randrange(24 * 215))) for i in range(3000)]

    def read(since, now):  # what use_sql(since) gives at now: every query from since's midnight on
        g = {}
        for q, u, o, act, t in log:
            if since <= t.date() and t <= now:
                n, last = g.get((u, o, a.monday(t), act), (set(), t))
                g[(u, o, a.monday(t), act)] = (n | {q}, max(last, t))
        return [dict(USER_NAME=u, OBJECT_NAME=o, WEEK=w, ACTION=act, QUERIES=len(n), LAST_USED=last)
                for (u, o, w, act), (n, last) in g.items()]

    def first(now):
        return a.monday(a.day(now) - timedelta(days=a.USE_DAYS))

    def key(x):
        return x["USER_NAME"], x["OBJECT_NAME"], a.day(x["WEEK"]), x["ACTION"], x["QUERIES"], x["LAST_USED"]

    t1 = t0 + timedelta(days=10)
    prev, full = read(first(t0), t0), Counter(map(key, read(first(t1), t1)))
    keep, since = a.use_start(prev, t1)  # Direct mode
    assert since.weekday() == 0 and since > first(t1) and keep
    same(Counter(map(key, keep + read(since, t1))), full, "use_start")
    assert a.use_start(None, t1) == ([], first(t1))

    con = load(a.fake(), build=False)  # the procedure, with run-2 as the last OK run
    con.execute("CREATE OR REPLACE TABLE TBL_ACCESS_OBJECT_USE (RUN_ID VARCHAR, USER_NAME VARCHAR, OBJECT_NAME VARCHAR, "
                "WEEK DATE, ACTION VARCHAR, QUERIES BIGINT, LAST_USED TIMESTAMP)")
    cols = COLS["OBJECT_USE"].split(", ")

    def put(run_id, xs):
        con.executemany("INSERT INTO TBL_ACCESS_OBJECT_USE VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [[run_id] + [x[c] for c in cols] for x in xs])

    put("run-2", prev)
    ns, session, scans = snapshot_proc(), fake_session(con), []
    duck_sql = session.sql

    def sql(text, params=None):
        if text.strip() == "SELECT CURRENT_DATE() AS D":
            return SimpleNamespace(collect=lambda **k: [Row(D=t1.date())])
        if "ACCOUNT_USAGE.ACCESS_HISTORY" in text:
            assert "CURRENT_TIMESTAMP" not in text and text.count("ACCOUNT_USAGE.ACCESS_HISTORY") == 1  # one scan
            on = a.day(re.search(r"'([0-9-]+)'::TIMESTAMP_LTZ", text).group(1))
            scans.append(on)
            return SimpleNamespace(collect_nowait=lambda **k: SimpleNamespace(result=lambda: put("run-9", read(on, t1))))
        return duck_sql(text, params)

    session.sql = sql
    assert ns["object_use"](session, "run-9", None)() == ("ACCOUNT_USAGE", None)
    got = Counter(map(key, query(con, f"SELECT {COLS['OBJECT_USE']} FROM TBL_ACCESS_OBJECT_USE WHERE RUN_ID = 'run-9'")))
    assert scans == [since], scans  # the same Monday as use_start
    same(got, full, "SP_ACCESS_SNAPSHOT object use")


def test_same_queries():
    """Each ACCOUNT_USAGE SELECT of access.live() has the same text in SP_ACCESS_SNAPSHOT, apart from the column
    aliases, the RUN_ID column and the INSERT around it."""
    import inspect

    def queries(src):
        out = {}
        for q in re.findall(r'f"""(.*?)"""', src, re.S):
            view = re.search(r"\{AU\}\.(\w+)", q)
            if view and "LIMIT 1" not in q:
                q = " ".join(q.split()).replace("-{DAYS}", "-30").replace("'{run_id}', ", "")
                q = re.sub(r"^INSERT INTO .*? SELECT ", "SELECT ", q)
                out[view.group(1)] = re.sub(r" AS [A-Z_]+\b", "", q)
        return out

    live = queries(inspect.getsource(a.live))
    proc = queries(re.search(r"PROCEDURE &DB\.&SCHEMA\.SP_ACCESS_SNAPSHOT.*?\$\$(.*?)\$\$", SETUP, re.S).group(1))
    views = {"GRANTS_TO_ROLES", "GRANTS_TO_USERS", "USERS", "QUERY_HISTORY", "TAG_REFERENCES", "POLICY_REFERENCES"}
    assert views <= set(live) & set(proc), (sorted(live), sorted(proc))
    for v in views:
        assert live[v] == proc[v], f"{v}:\n live {live[v]}\n proc {proc[v]}"


def test_proc_settings():
    """SP_ACCESS_SNAPSHOT's settings.sql names: every statement carries STATEMENT_TIMEOUT as a statement parameter,
    later() runs at most WORKERS heavy jobs at once, ACTIVITY=0 skips object use and activity (SKIPPED, the run stays
    OK), and a timeout that fails the run names its step."""
    ns = snapshot_proc()
    body = re.search(r"PROCEDURE &DB\.&SCHEMA\.SP_ACCESS_SNAPSHOT.*?\$\$(.*?)\$\$", SETUP, re.S).group(1)
    assert ns["TIMED"] == {"statement_params": {"STATEMENT_TIMEOUT_IN_SECONDS": 300}} and ns["WORKERS"] == 3
    assert ".collect()" not in body and ".collect_nowait()" not in body
    log = []

    def sql(text, params=None):
        return SimpleNamespace(collect=lambda **k: log.append(("sync", text, k)) or [],
                               collect_nowait=lambda **k: log.append(("start", text, k))
                               or SimpleNamespace(result=lambda: log.append(("end", text))))
    session = SimpleNamespace(sql=sql)
    for workers, want in ((1, ["start A", "end A", "start B", "end B", "start C"]), (3, ["start A", "start B", "start C"])):
        ns["WORKERS"], log[:] = workers, []
        ns["PENDING"].clear()
        for q in "ABC":
            ns["later"](session, "T", "r", q, ("ACCOUNT_USAGE", None))
        assert [f"{x[0]} {x[1]}" for x in log] == want, (workers, log)
        assert all(x[2] == ns["TIMED"] for x in log if x[0] == "start")
    ns["ASYNC"], log[:] = False, []  # a run that failed (STOP): a job that never started is not run while draining
    ns["PENDING"].clear()
    wait = ns["later"](session, "T", "r", "D", ("ACCOUNT_USAGE", None))
    ns["STOP"].append(1)
    assert wait() == ("UNAVAILABLE", "not run: the run failed") and not log, log
    ns["ASYNC"] = True
    ns["STOP"].clear()
    for step in ("object_use", "activity"):
        assert ns[step](session, "r", "skipped (ACTIVITY=0)")() == ("SKIPPED", "skipped (ACTIVITY=0)")

    con = load(a.fake(), build=False)  # run() with ACTIVITY=0, then with a grants read that times out
    con.execute("CREATE MACRO PARSE_JSON(x) AS x")
    duck = fake_session(con)
    session = SimpleNamespace(sql=lambda text, params=None: duck.sql(
        re.sub(r"DATEADD\((\w+), (-?\d+), CURRENT_TIMESTAMP\(\)\)", r"(current_timestamp + INTERVAL (\2) \1)", text)
        .replace("CURRENT_TIMESTAMP()", "current_timestamp"), params))
    ns, seen = snapshot_proc(), []
    ns.update({k: lambda *x: ("SHOW", None) for k in ("users", "tags", "policies", "streams", "objects", "app_grants_step")})
    ns["future"] = lambda *x: {"schemas": ("SHOW", None), "future_grants": ("SHOW", None)}
    ns["usage"] = lambda *x: lambda: ("SHOW", None)
    ns["grants"] = lambda *x: {"grants": ("SHOW", None), "user_roles": ("SHOW", None)}
    ns["fallback"] = lambda *x: seen.append(x[1]) or None
    ns["READ_ACTIVITY"] = False
    out = ns["run"](session, "AUTO")
    assert out["status"] == "OK" and "ACCESS_HISTORY" not in seen, (out, seen)
    assert out["sources"]["object_use"] == out["sources"]["activity"] == "SKIPPED"
    assert out["notes"]["activity"] == "skipped (ACTIVITY=0)"

    def slow(*x):
        raise RuntimeError("Statement reached its statement or warehouse timeout of 300 second(s) and was canceled.")
    ns["grants"] = slow
    out = ns["run"](session, "AUTO")
    assert out["status"] == "FAILED" and out["notes"]["error"].startswith(
        "grants: stopped after 5 min (STATEMENT_TIMEOUT=300); set STATEMENT_TIMEOUT=600 for 10 minutes"), out


def test_history_shared():
    """SP_ACCESS_SNAPSHOT reads ACCESS_HISTORY once for object use and activity: one INSERT ALL of history_sql (the
    same text as access.history_sql) fills both tables; when it fails, each step runs its own INSERT, and a step that
    is skipped or fails leaves the other reading alone."""
    import inspect
    from datetime import date
    assert inspect.getsource(a.history_sql) in SETUP
    ns, log = snapshot_proc(), []
    ns["object_use"] = lambda s, r, why, plan=False: ns["ready"]("SKIPPED", why) if why else (date(2026, 5, 4), "USE ALONE")
    ok = ("ACCOUNT_USAGE", "no client")
    ns["activity"] = lambda s, r, why, plan=False: ns["ready"]("SKIPPED", why) if why else (date(2026, 9, 4), "ACT ALONE", ok, False)

    def sql(text, params=None):
        def result():
            log.append(text.split()[0] + " " + text.split()[1])
            if text.startswith("INSERT ALL") and fail:
                raise RuntimeError(fail)
        return SimpleNamespace(collect_nowait=lambda **k: SimpleNamespace(result=result), collect=lambda **k: result())
    session = SimpleNamespace(sql=sql)
    for fail, want in ((False, ["INSERT ALL"]), ("SQL compilation error", ["INSERT ALL", "USE ALONE", "ACT ALONE"])):
        log[:] = []
        ns["PENDING"].clear()
        waits = ns["history"](session, "r", None)
        assert [w() for w in waits] == [("ACCOUNT_USAGE", None), ok] and log == want, (fail, log)
    # a timeout, or a run that has failed (STOP): no read apart, both steps end with the shared read's note
    for fail, stop in (("Statement reached its statement or warehouse timeout of 300 second(s)", False),
                       ("SQL compilation error", True)):
        log[:] = []
        ns["PENDING"].clear()
        ns["STOP"][:] = [1] * stop
        got = [w() for w in ns["history"](session, "r", None)]
        assert log == ["INSERT ALL"] and got[0] == got[1] and got[0][0] == "UNAVAILABLE", (fail, log, got)
        assert ("set STATEMENT_TIMEOUT=600" in got[0][1]) != stop, got
    ns["STOP"].clear()
    ns["PENDING"].clear()
    assert [w() for w in ns["history"](session, "r", "skipped (ACTIVITY=0)")] == [("SKIPPED", "skipped (ACTIVITY=0)")] * 2
    ns["object_use"] = lambda *x: ns["ready"]("UNAVAILABLE", "x")  # one step fails: the other reads alone
    log[:] = []
    assert [w() for w in ns["history"](session, "r", None)] == [("UNAVAILABLE", "x"), ok] and log == ["ACT ALONE"]
    text = ns["history_sql"]("2026-05-04", "2026-09-04", False)
    assert text.count("ACCOUNT_USAGE.ACCESS_HISTORY") == 1 and text.count("FROM A0 WHERE") == 2


if __name__ == "__main__":
    for t in (test_demo, test_cap_and_admin, test_edges, test_blocked, test_findings, test_streams, test_objects, test_object_use, test_activity, test_show_fallback,
              test_run_overlap, test_usage_extra, test_object_use_weeks, test_same_queries, test_proc_settings, test_history_shared):
        t()
        print("ok", t.__name__)
