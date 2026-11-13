"""The worksheet SQL of sql/1_setup.sql (table functions, findings procedure) against access.py, on DuckDB in memory.
Run: python test_sql.py (no pytest needed). The function bodies are read from sql/1_setup.sql, so the shipped text is tested."""
import json
import pathlib
import re
import sys
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
LIMITS = [None, 0, 1, 2, 3, 4, 6, 10]
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
    want = Counter((" > ".join(r["path"]), r["depth"], r["holder"], False) for r in res["paths"])
    want += Counter((" > ".join(p), len(p) - 2, p[-2], True) for p in res["owner"])
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
    assert rows(con, "SELECT * FROM TF_CAN('U', 'SELECT', 'D.S.T')", []) == Counter([("U > R1 > D.S.T", 1, "R1", True)])
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


class Row(dict):  # a Snowpark Row: row["N"] and row.as_dict()
    def as_dict(self):
        return dict(self)


def fake_session(con):
    """The parts of a Snowpark session SP_ACCESS_FINDINGS uses, on DuckDB."""
    def sql(text, params=None):
        found = query(con, text, params)
        return SimpleNamespace(collect=lambda: [Row(r) for r in found])

    def create_dataframe(data, schema):
        def save(table, mode, column_order):
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
    """SP_ACCESS_SNAPSHOT's streams step: SHOW STREAMS rows -> TBL_ACCESS_STREAM; an error -> UNAVAILABLE."""
    con = load(a.fake(), build=False)
    body = re.search(r"PROCEDURE &DB\.&SCHEMA\.SP_ACCESS_SNAPSHOT.*?\$\$(.*?)\$\$", SETUP, re.S).group(1)
    ns = {}
    exec(body.replace("&DB.&SCHEMA", "main").replace("&DB", "main"), ns)
    session = fake_session(con)
    show = [dict(database_name="D", schema_name="S", name='"ST 1"', table_name='D.S."T"', source_type="Table")]
    sql = session.sql

    def fake_sql(text, params=None):
        if not text.startswith("SHOW STREAMS"):
            return sql(text, params)
        return SimpleNamespace(collect=lambda: [SimpleNamespace(as_dict=lambda r=r: r) for r in show])

    session.sql = fake_sql
    assert ns["streams"](session, "run-9") == ("SHOW", None)
    got = con.execute("SELECT * FROM TBL_ACCESS_STREAM WHERE RUN_ID = 'run-9'").fetchall()
    assert got == [("run-9", "D.S.ST 1", "D.S.T", "Table")]
    show = None  # not iterable: the SHOW fails
    assert ns["streams"](session, "run-8")[0] == "UNAVAILABLE"


def test_object_use():
    """SP_ACCESS_SNAPSHOT's object usage step: the same ACCESS_HISTORY SELECT as access.use_sql(); not readable (DuckDB
    has no ACCESS_HISTORY) -> UNAVAILABLE with the reason, no rows, the run goes on."""
    import inspect
    assert inspect.getsource(a.use_sql) in SETUP
    con = load(a.fake(), build=False)
    body = re.search(r"PROCEDURE &DB\.&SCHEMA\.SP_ACCESS_SNAPSHOT.*?\$\$(.*?)\$\$", SETUP, re.S).group(1)
    ns = {}
    exec(body.replace("&DB.&SCHEMA", "main").replace("&DB", "main"), ns)
    src, why = ns["object_use"](fake_session(con), "run-9", "AUTO")
    assert src == "UNAVAILABLE" and "ACCESS_HISTORY" in why
    assert ns["object_use"](fake_session(con), "run-9", "SHOW")[0] == "UNAVAILABLE"
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
    exec(body.replace("&DB.&SCHEMA", "main").replace("&DB", "main"), ns)
    assert ns["ACTIVITY_DAYS"] == a.ACTIVITY_DAYS and ns["QUERY_TAG"] == a.QUERY_TAG
    src, why = ns["activity"](fake_session(con), "run-9", "AUTO")
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
    exec(body.replace("&DB.&SCHEMA", "main").replace("&DB", "main"), ns)
    session = fake_session(con)
    duck_sql = session.sql

    def sql(text, params=None):
        if text.lstrip().upper().startswith("SHOW") or "ACCOUNT_USAGE" in text:
            got = answer(text)
            return SimpleNamespace(collect=lambda: [SimpleNamespace(as_dict=lambda r=r: r) for r in got])
        return duck_sql(text, params)

    session.sql = sql
    out = ns["grants"](session, "run-9", "SHOW")
    assert out["grants"][0] == "SHOW" and f"{bad}: Insufficient privileges" in out["grants"][1], out
    proc = Counter((r["GRANTEE_ROLE"], r["PRIVILEGE"], r["GRANTED_ON"], r["OBJECT_NAME"])
                   for r in query(con, "SELECT * FROM TBL_ACCESS_GRANT WHERE RUN_ID = 'run-9'"))
    proc_users = Counter((r["USER_NAME"], r["ROLE_NAME"]) for r in query(con, "SELECT * FROM TBL_ACCESS_USER_ROLE WHERE RUN_ID = 'run-9'"))
    live = a.live(answer)
    direct = Counter((g["GRANTEE_ROLE"], g["PRIVILEGE"], g["GRANTED_ON"], g["OBJECT_NAME"]) for g in live["GRANT"] if not g["IS_FUTURE"])
    same(proc, direct, "SHOW grants")
    same(proc_users, Counter((x["USER_NAME"], x["ROLE_NAME"]) for x in live["USER_ROLE"]), "SHOW user roles")
    assert not any(k[0] == bad for k in proc) and any("." in k[0] for k in proc)  # the other database roles are read
    assert f"{bad}: " in str(live["run"].get("NOTES"))
    assert f"{half}: Insufficient privileges" in out["grants"][1] and not any(k[0] == half for k in proc)
    assert not any(r == half for _, r in proc_users)
    src, why = ns["future"](session, "run-10")  # one refused place skips only itself, as in live()
    fut = Counter((r["GRANTEE_ROLE"], r["PRIVILEGE"], r["GRANTED_ON"], r["OBJECT_NAME"])
                  for r in query(con, "SELECT * FROM TBL_ACCESS_GRANT WHERE RUN_ID = 'run-10'"))
    same(fut, Counter((g["GRANTEE_ROLE"], g["PRIVILEGE"], g["GRANTED_ON"], g["OBJECT_NAME"])
                      for g in live["GRANT"] if g["IS_FUTURE"]), "SHOW future grants")
    assert src == "SHOW" and why.startswith("1 database") and "SALES: " in why and sum(fut.values()) == 2

    def refused(text, params=None):  # SOURCE=direct inside Snowflake when even SHOW DATABASES is refused
        if text.lstrip().upper().startswith("SHOW DATABASES"):
            raise RuntimeError("SHOW DATABASES is not allowed")
        return sql(text, params)

    session.sql = refused
    src, why = ns["future"](session, "run-9")
    assert src == "UNAVAILABLE" and "not allowed" in why  # the run goes on, as access.live() does


def snapshot_proc():
    body = re.search(r"PROCEDURE &DB\.&SCHEMA\.SP_ACCESS_SNAPSHOT.*?\$\$(.*?)\$\$", SETUP, re.S).group(1)
    ns = {}
    exec(body.replace("&DB.&SCHEMA", "main").replace("&DB", "main"), ns)
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
    ns.update({k: step for k in ("future", "users", "usage", "tags", "policies", "streams", "object_use", "activity")})

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


def test_usage_extra():
    """ACCOUNT_USAGE.QUERY_HISTORY readable but the usage read fails (a timeout): usage UNAVAILABLE, the run goes on,
    as in access.live()."""
    con = load(a.fake(), build=False)
    ns = snapshot_proc()
    session = fake_session(con)
    duck_sql = session.sql

    def sql(text, params=None):
        if "ACCOUNT_USAGE.QUERY_HISTORY LIMIT 1" in text:
            return SimpleNamespace(collect=lambda: [])
        if "ACCOUNT_USAGE.QUERY_HISTORY" in text:
            raise RuntimeError("Statement reached its statement or warehouse timeout")
        return duck_sql(text, params)

    session.sql = sql
    assert ns["usage"](session, "run-9", "AUTO") == ("UNAVAILABLE", "Statement reached its statement or warehouse timeout")
    assert not con.execute("SELECT * FROM TBL_ACCESS_USAGE WHERE RUN_ID = 'run-9'").fetchall()


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


if __name__ == "__main__":
    for t in (test_demo, test_cap_and_admin, test_edges, test_findings, test_streams, test_object_use, test_activity, test_show_fallback,
              test_run_overlap, test_usage_extra, test_same_queries):
        t()
        print("ok", t.__name__)
