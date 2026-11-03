"""The worksheet SQL of sql/1_setup.sql (table functions, findings procedure) against access.py, on DuckDB in memory.
Run: python test_sql.py (no pytest needed). The function bodies are read from sql/1_setup.sql, so the shipped text is tested."""
import json
import pathlib
import re
import sys
from collections import Counter
from types import ModuleType, SimpleNamespace

import duckdb

import access as a

COLS = {
    "GRANT": "GRANTEE_ROLE, PRIVILEGE, GRANTED_ON, OBJECT_NAME, IS_FUTURE",
    "USER_ROLE": "USER_NAME, ROLE_NAME",
    "USER": "USER_NAME, TYPE, DISABLED, DEFAULT_ROLE, DEFAULT_SECONDARY_ROLES, DEFAULT_WAREHOUSE, DEFAULT_NAMESPACE, LAST_SUCCESS_LOGIN",
    "USAGE": "USER_NAME, KIND, NAME, QUERIES, LAST_USED",
    "TAG": "OBJECT_NAME, DOMAIN, COLUMN_NAME, TAG_NAME, TAG_VALUE, APPLY_METHOD",
    "POLICY": "POLICY_NAME, POLICY_KIND, OBJECT_NAME, COLUMN_NAME, ARG_COLUMNS, TAG_NAME, POLICY_BODY",
    "STREAM": "STREAM_NAME, SOURCE_NAME, SOURCE_TYPE",
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
                                                   ("streams", "STREAM")]})
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
        data = [["run-2"] + [row.get(c) for c in names] for row in d.get(t, [])]
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


def test_demo():
    con = load(a.fake())
    n = sum(check_access_of(con, u, True, lim) for u in a.users for lim in LIMITS)
    n += sum(check_access_of(con, r, False, lim) for r in a.roles if r not in a.users for lim in LIMITS)
    assert n > 1000
    privs = {o: sorted({pv for _, pv, _ in a.on[o]}) for o in a.objects}
    assert sum(check_who_can(con, o, pv, lim) for o in OBJS for pv in [None] + privs[o] for lim in LIMITS) > 100
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


def fake_session(con):
    """The parts of a Snowpark session SP_ACCESS_FINDINGS uses, on DuckDB."""
    def sql(text, params=None):
        found = query(con, text, params)
        return SimpleNamespace(collect=lambda: [SimpleNamespace(as_dict=lambda r=r: r) for r in found])

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
    for _ in range(2):  # the second CALL replaces the run's rows
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


if __name__ == "__main__":
    for t in (test_demo, test_cap_and_admin, test_edges, test_findings, test_streams):
        t()
        print("ok", t.__name__)
