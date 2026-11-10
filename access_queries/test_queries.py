"""The query files on DuckDB, over fake ACCOUNT_USAGE views made from access.fake(), against access.py; and
functions.sql against the query files. Run: python access_queries/test_queries.py (needs duckdb, requirements-web.txt)."""
import os
import pathlib
import re
import sys

os.environ["FAKE"] = "1"
HERE = pathlib.Path(__file__).parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

try:
    import duckdb
except ImportError:
    sys.exit("skipped: duckdb is not installed (pip install -r requirements-web.txt)")

import access as a

F, T = a.FUNC, a.TECH
GONE = "2026-10-01"  # DELETED_ON of the rows that must be ignored


def account_usage(d):
    """d's grants as SNOWFLAKE.ACCOUNT_USAGE stores them, plus deleted rows; future grants are not in ACCOUNT_USAGE."""
    roles, users = [], []
    for g in d["GRANT"]:
        if g["IS_FUTURE"]:
            continue
        on, o, r = g["GRANTED_ON"], g["OBJECT_NAME"], g["GRANTEE_ROLE"]
        if on == "DATABASE":  # TABLE_CATALOG left NULL, so the grantee of a database role comes from NAME
            cat, sch, name = None, None, o
        elif on == "SCHEMA":
            (cat, name), sch = o.split(".", 1), None
        else:
            parts = o.split(".")
            cat, sch, name = parts if len(parts) == 3 else (parts[0], None, parts[1]) if len(parts) == 2 else (None, None, o)
        to, grantee = "ROLE", r
        if "." in r:  # a database role: ACCOUNT_USAGE has its bare name, the database is the granted object's
            to, (db, grantee) = "DATABASE_ROLE", r.split(".", 1)
            assert db == (o if on == "DATABASE" else cat), g
        roles.append((g["PRIVILEGE"], on, name, cat, sch, to, grantee, False, None))
    roles.append(("SELECT", "TABLE", "TBL_CUSTOMER", "SALES", "CORE", "ROLE", "GRP_ANALYSTS", False, GONE))
    roles.append(("USAGE", "ROLE", "SYSADMIN", None, None, "ROLE", f"{F}ANALYST", False, GONE))
    users += [(x["ROLE_NAME"], "USER", x["USER_NAME"], None) for x in d["USER_ROLE"]]
    users.append(("ACCOUNTADMIN", "USER", "ANALYST_01", GONE))
    people = [(u["USER_NAME"], u["DISABLED"], u["TYPE"], u["LAST_SUCCESS_LOGIN"], None) for u in d["USER"]]
    people.append(("GONE_01", False, "PERSON", None, GONE))
    con = duckdb.connect()
    con.execute("ATTACH ':memory:' AS SNOWFLAKE")
    con.execute("CREATE SCHEMA SNOWFLAKE.ACCOUNT_USAGE")
    con.execute("CREATE TABLE SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES (PRIVILEGE VARCHAR, GRANTED_ON VARCHAR, "
                "NAME VARCHAR, TABLE_CATALOG VARCHAR, TABLE_SCHEMA VARCHAR, GRANTED_TO VARCHAR, GRANTEE_NAME VARCHAR, "
                "GRANT_OPTION BOOLEAN, DELETED_ON TIMESTAMP)")
    con.execute("CREATE TABLE SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS (ROLE VARCHAR, GRANTED_TO VARCHAR, "
                "GRANTEE_NAME VARCHAR, DELETED_ON TIMESTAMP)")
    con.execute("CREATE TABLE SNOWFLAKE.ACCOUNT_USAGE.USERS (NAME VARCHAR, DISABLED BOOLEAN, TYPE VARCHAR, "
                "LAST_SUCCESS_LOGIN TIMESTAMP, DELETED_ON TIMESTAMP)")
    con.executemany("INSERT INTO SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", roles)
    con.executemany("INSERT INTO SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS VALUES (?, ?, ?, ?)", users)
    con.executemany("INSERT INTO SNOWFLAKE.ACCOUNT_USAGE.USERS VALUES (?, ?, ?, ?, ?)", people)
    return con


def body(text):
    """The query of a file: from WITH RECURSIVE to its closing semicolon."""
    return text[text.index("WITH RECURSIVE"):].rstrip().rstrip(";")


def lit(v):
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    return str(v) if isinstance(v, int) else "'" + v.replace("'", "''") + "'"


def run(con, file, **vals):
    """Rows of a query file as dicts, its SET values replaced by vals."""
    text = (HERE / file).read_text(encoding="utf-8")
    sets = dict(re.findall(r"^SET (\w+) = (.*);$", text, re.M)) | {k: lit(v) for k, v in vals.items()}
    cur = con.execute(re.sub(r"\$(\w+)", lambda m: sets[m.group(1)], body(text)))
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def kind(r):
    return "DATABASE ROLE" if a.role_kind(r) == "database" else "ROLE"


def expect(items, top):
    """items: (key, fields, depth, path) per access.py path -> {key: (fields, depth, ways, {shortest paths})}."""
    out = {}
    for key, fields, dp, path in items:
        if dp > top:
            continue
        f, d, n, ps = out.get(key, (fields, dp, 0, set()))
        if dp < d:
            ps = set()
        if dp <= d:
            ps.add(path)
        out[key] = (f, min(d, dp), n + 1, ps)
    return out


FAILS = []


def same(what, got, want, rows):
    """got: {key: (fields, depth, ways, path)} from SQL against expect(); rows: the SQL rows, one per key."""
    if len(rows) != len(got):
        FAILS.append(f"{what}: {len(rows)} rows for {len(got)} answers")
    for k in sorted(set(got) | set(want), key=str):
        if k not in want:
            FAILS.append(f"{what}: SQL only {k} {got[k]}")
        elif k not in got:
            FAILS.append(f"{what}: missing {k} {want[k][:3]}")
        elif got[k][:3] != want[k][:3] or got[k][3] not in want[k][3]:
            FAILS.append(f"{what}: {k} SQL {got[k]} want {want[k][:3]} one of {sorted(want[k][3])[:3]}")


def user_roles(con, user, top=20, builtin=False):
    rows = run(con, "1_user_roles.sql", USER_NAME=user, MAX_DEPTH=top, SHOW_BUILTIN=builtin)
    got = {r["ROLE_NAME"]: ((r["ROLE_KIND"],), r["DEPTH"], r["WAYS"], r["PATH"]) for r in rows}
    want = expect([(p[-1], (kind(p[-1]),), a.depth(p, True), " > ".join(p)) for p in a.walk(user, True)
                   if user in a.users], top)  # an unknown name gets no PUBLIC here, unlike access.py
    same(f"1_user_roles {user} {top}", got, want, rows)
    return got


def access(con, name, user, top=20, builtin=False):
    file, var = ("2_user_access.sql", "USER_NAME") if user else ("3_role_access.sql", "ROLE_NAME")
    rows = run(con, file, **{var: name}, MAX_DEPTH=top, SHOW_BUILTIN=builtin)
    got = {(r["PRIVILEGE"], r["GRANTED_ON"], r["OBJECT_NAME"]): ((), r["DEPTH"], r["WAYS"], (r["PATH"], r["VIA_ROLE"]))
           for r in rows}
    want = expect([((pv, k, o), (), a.depth(p, user), (" > ".join(p), p[-1])) for pv, k, o, p in a.access_of(name, user)
                   if not user or name in a.users],
                  top)
    same(f"{file} {name} {top}", got, want, rows)
    return got


def up_items(role):
    """(name, kind, depth, path holder > ... > role) per access.py up() path from role, role itself left out."""
    for p in a.up([role]):
        if len(p) > 1:
            q = p[::-1]
            u = a.from_user(q)
            yield a.node_name(q[0]), "USER" if u else kind(q[0]), a.depth(q, u), " > ".join([a.node_name(q[0])] + q[1:])


def holders(con, role, top=20, builtin=False):
    rows = run(con, "4_role_holders.sql", ROLE_NAME=role, MAX_DEPTH=top, SHOW_BUILTIN=builtin)
    got = {(r["HOLDER"], r["HOLDER_KIND"]): ((), r["DEPTH"], r["WAYS"], r["PATH"]) for r in rows}
    want = expect([((x, k), (), d, p) for x, k, d, p in up_items(role)], top)
    same(f"4_role_holders {role} {top}", got, want, rows)
    return got


def object_users(con, obj, priv="", top=20, builtin=False):
    rows = run(con, "5_object_users.sql", OBJECT_NAME=obj, PRIVILEGE=priv, MAX_DEPTH=top, SHOW_BUILTIN=builtin)
    got = {(r["GRANTEE"], r["GRANTEE_KIND"], r["PRIVILEGE"], r["GRANTED_ON"]): ((), r["DEPTH"], r["WAYS"],
                                                                                 (r["PATH"], r["HOLDER"])) for r in rows}
    items = []
    for r, pv, k in a.on.get(obj, []):
        if priv in ("", pv):
            items += [((x, kd, pv, k), (), d, (p, r)) for x, kd, d, p in up_items(r)]
            items.append(((r, kind(r), pv, k), (), 1, (r, r)))
    same(f"5_object_users {obj} {priv!r} {top}", got, expect(items, top), rows)
    return got


def functions():
    """functions.sql: each body is its query file with $NAME -> NAME and without the last ORDER BY (a function's
    row order is not kept), arguments = the file's SET names, and the
    returned columns = the file's output columns (con: the DuckDB run)."""
    text = (HERE / "functions.sql").read_text(encoding="utf-8")
    found = re.findall(r"CREATE OR REPLACE FUNCTION AQ_DB\.AQ_SCHEMA\.(AQ_\w+)\((.*?)\)\s*RETURNS TABLE \((.*?)\)"
                       r".*?\$\$\n(.*?)\n\$\$", text, re.S)
    files = sorted(HERE.glob("[0-9]_*.sql"))
    if len(found) != len(files):
        FAILS.append(f"functions.sql: {len(found)} functions for {len(files)} query files")
    fns = {n: (args, ret, b) for n, args, ret, b in found}
    for f in files:
        name = "AQ_" + f.stem.split("_", 1)[1].upper()
        if name not in fns:
            FAILS.append(f"functions.sql: no {name} for {f.name}")
            continue
        args, ret, b = fns[name]
        plain = f.read_text(encoding="utf-8")
        if b != re.sub(r"\nORDER BY [^\n]*$", "", re.sub(r"\$(\w+)", r"\1", body(plain))):
            FAILS.append(f"functions.sql: {name} body differs from {f.name}")
        if [x.split()[0] for x in args.split(",")] != re.findall(r"^SET (\w+) =", plain, re.M):
            FAILS.append(f"functions.sql: {name} arguments differ from the SET lines of {f.name}")
        cols = [c[0] for c in CON.execute(re.sub(r"\$(\w+)", "NULL", body(plain)) + " LIMIT 0").description]
        if [x.split()[0] for x in ret.split(",")] != cols:
            FAILS.append(f"functions.sql: {name} RETURNS TABLE columns differ from {f.name}: {cols}")


def notebook():
    """access_examples.ipynb is what make_notebook.py builds now; its cells hold the files' queries and functions."""
    import json
    import make_notebook as m
    raw = m.OUT.read_text(encoding="utf-8")
    if raw != m.text():
        FAILS.append("access_examples.ipynb is out of date: run python access_queries/make_notebook.py")
    code = {c["metadata"]["name"]: "".join(c["source"]) for c in json.loads(raw)["cells"] if c["cell_type"] == "code"}
    fns = re.findall(r"CREATE OR REPLACE FUNCTION .*?\n\$\$;", (HERE / "functions.sql").read_text(encoding="utf-8"), re.S)
    if [code.get(f"create_{i + 1}") for i in range(len(fns))] != fns:
        FAILS.append("notebook: create cells differ from functions.sql")
    for n, f in [("roles_of_user", "1_user_roles.sql"), ("access_of_user", "2_user_access.sql"),
                 ("access_of_role", "3_role_access.sql"), ("holders_of_role", "4_role_holders.sql")]:
        if code.get(f"b_{n}") != body((HERE / f).read_text(encoding="utf-8")) + ";":
            FAILS.append(f"notebook: b_{n} differs from {f}")
    for n, f in [("user_reaches_object", "2_user_access.sql"), ("users_of_object", "5_object_users.sql"),
                 ("deep_users", "5_object_users.sql"), ("access_summary", "2_user_access.sql")]:
        plain = re.sub(r"\nORDER BY [^\n]*$", "", body((HERE / f).read_text(encoding="utf-8")))
        if plain not in code.get(f"b_{n}", ""):
            FAILS.append(f"notebook: b_{n} does not hold the query of {f}")
    for n in [n for n in code if n.startswith("a_") and "$SHOW_BUILTIN" not in code[n]]:
        FAILS.append(f"notebook: {n} does not pass $SHOW_BUILTIN, so path A and B can differ")
    if len(code) != 1 + len(fns) + 2 * len(m.EXAMPLES):
        FAILS.append(f"notebook: {len(code)} code cells")


d = a.fake()
d["GRANT"] += [dict(GRANTEE_ROLE=r, PRIVILEGE=pv, GRANTED_ON="ROLE", OBJECT_NAME=o, IS_FUTURE=False) for r, pv, o in [
    (f"{T}SALES_MART_READ", "USAGE", f"{F}ANALYST"),  # a cycle: F_ANALYST holds T_SALES_MART_READ
    (f"{F}ANALYST", "OWNERSHIP", "GRP_ANALYSTS"),  # a privilege on a role, not a role link
    ("PUBLIC", "USAGE", f"{T}SALES_MART_READ")]]  # PUBLIC holding a custom role
# a user named like a role it reaches (separate namespaces), a user with no grants, a disabled one with no grants
d["USER"] += [dict(d["USER"][0], USER_NAME=u, DISABLED=off, DEFAULT_ROLE=None)
              for u, off in [(f"{T}SALES_CORE_READ", False), ("LONELY_01", False), ("GHOST_01", True)]]
d["USER_ROLE"] += [dict(USER_NAME=f"{T}SALES_CORE_READ", ROLE_NAME=f"{F}ANALYST", GRANTED_BY="SECURITYADMIN"),
                   dict(USER_NAME="ANALYST_02", ROLE_NAME="PUBLIC", GRANTED_BY="SECURITYADMIN")]  # PUBLIC granted
CON = account_usage(d)
d["GRANT"] = [g for g in d["GRANT"] if not g["IS_FUTURE"]]

a.build(d)
for u in ["ANALYST_01", "ANALYST_02", "ENGINEER_01", "ADMIN_01", "OPS_01", "SVC_DEPLOY", "FIN_01", "HR_01", "DW_DEV_01",
          "NOBODY", f"{T}SALES_CORE_READ", "LONELY_01", "GHOST_01"]:
    user_roles(CON, u)
    access(CON, u, True)
for r in [f"{F}ANALYST", f"{F}ENGINEER", f"{T}SALES_CORE_READ", "HR.SC_W_PEOPLE", "SYSADMIN", "PUBLIC", "GRP_EMEA_ALL"]:
    access(CON, r, False)
for r in [f"{T}SALES_CORE_READ", f"{T}SALES_MART_READ", "HR.SC_R_PEOPLE", "SYSADMIN", "SECURITYADMIN", "PUBLIC",
          f"{F}FINANCE_EDITOR", "GRP_ANALYSTS", "SNOWFLAKE.CORE_VIEWER"]:
    holders(CON, r)
for o, pv in [("SALES.CORE.TBL_CUSTOMER", ""), ("SALES.CORE.TBL_CUSTOMER", "SELECT"), ("HR.PEOPLE.TBL_EMPLOYEE", ""),
              ("FINANCE.REPORT.TBL_REVENUE", "SELECT"), ("WH_SALES_XS", ""), ("SALES", "USAGE"), ("SALES.CORE", ""),
              ("ACCOUNT", "MANAGE GRANTS"), ("NO.SUCH.OBJECT", ""), ("GRP_ANALYSTS", "OWNERSHIP"), ("SNOWFLAKE", "USAGE"),
              ("SYSTEM_COMPUTE_POOL_CPU", "")]:
    object_users(CON, o, pv)
for top in (0, 1, 3, 9):  # MAX_DEPTH: FIN_01's chain is 10 roles deep
    user_roles(CON, "FIN_01", top)
    access(CON, "FIN_01", True, top)
    access(CON, "GRP_EMEA_ALL", False, top)
    holders(CON, f"{F}FINANCE_EDITOR", top)
    object_users(CON, "FINANCE.REPORT.TBL_REVENUE", "SELECT", top)

# spot checks: a user via a group role, a role reached through 2 paths, an admin holder, deleted rows ignored
roles = user_roles(CON, "ANALYST_01")
assert roles["GRP_ANALYSTS"][1] == 1 and f"{F}ANALYST" in roles and "ACCOUNTADMIN" not in roles, roles
assert user_roles(CON, "ENGINEER_01")[f"{T}SALES_CORE_READ"][2] >= 2
assert ("SECURITYADMIN", "TABLE", "SALES.CORE.TBL_CUSTOMER") not in access(CON, "ANALYST_01", True)
assert ("ADMIN_01", "USER") in holders(CON, "SECURITYADMIN") and ("GONE_01", "USER") not in holders(CON, "PUBLIC")
assert user_roles(CON, "HR_01")["HR.SC_R_PAYROLL"][0] == ("DATABASE ROLE",)

a.build(d, builtin=True)  # SHOW_BUILTIN = TRUE: Snowflake's own grants via PUBLIC too
user_roles(CON, "ANALYST_01", builtin=True)
assert any(k[2].startswith("SNOWFLAKE.") for k in access(CON, "ANALYST_01", True, builtin=True))
access(CON, "PUBLIC", False, builtin=True)
assert ("ANALYST_01", "USER") in holders(CON, "SNOWFLAKE.CORE_VIEWER", builtin=True)
assert object_users(CON, "SNOWFLAKE", "USAGE", builtin=True) and object_users(CON, "SYSTEM_COMPUTE_POOL_CPU", builtin=True)

functions()
notebook()

if FAILS:
    print("\n".join(FAILS[:50]))
    sys.exit(f"{len(FAILS)} failures")
print("ok: query files match access.py on the fake data, functions.sql matches the query files, the notebook is current")
