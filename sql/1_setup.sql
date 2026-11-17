-- 1 · setup (developer role): the 10 snapshot tables, the snapshot procedure, the findings table, stage and procedure,
-- the worksheet table functions TF_ACCESS_OF / TF_WHO_CAN / TF_CAN, read access for the app role. Safe to run again.
-- run_sql.py runs each "-- name:" statement in order; "(may fail)" = skipped on error.
-- Names marked with & come from settings.local.sql. Real set-up: schema, roles and grants via infrastructure as code.
-- SnowSQL: !source sql/1_setup.sql (from the repo folder)
!source settings.local.sql
USE ROLE &DEV_ROLE;
USE SECONDARY ROLES NONE;   -- as inside the owner's-rights procedure
USE WAREHOUSE &WH;
USE DATABASE &DB;

-- name: TABLE_RUN
CREATE TABLE IF NOT EXISTS &DB.&SCHEMA.TBL_ACCESS_RUN (   -- one row per CALL, kept
    RUN_ID VARCHAR(36),
    STARTED_AT TIMESTAMP_LTZ,
    FINISHED_AT TIMESTAMP_LTZ,
    STATUS VARCHAR(10),              -- RUNNING, OK, FAILED
    SOURCES VARIANT,                 -- dataset -> ACCOUNT_USAGE / SHOW / INFORMATION_SCHEMA / UNAVAILABLE
    ROW_COUNTS VARIANT,              -- dataset -> rows written
    NOTES VARIANT                    -- dataset -> why a fallback was used, roles skipped, error
);

-- name: TABLE_GRANT
CREATE TABLE IF NOT EXISTS &DB.&SCHEMA.TBL_ACCESS_GRANT (   -- role -> object and role -> role (GRANTED_ON = ROLE)
    RUN_ID VARCHAR(36),
    GRANTEE_ROLE VARCHAR(255),
    PRIVILEGE VARCHAR(255),
    GRANTED_ON VARCHAR(255),         -- TABLE, VIEW, ROLE, SCHEMA, ACCOUNT, ...
    OBJECT_NAME VARCHAR(2000),       -- DB.SCHEMA.OBJECT, unquoted; future grants: DB.SCHEMA.<TABLE>
    IS_FUTURE BOOLEAN,
    GRANT_OPTION BOOLEAN,
    GRANTED_BY VARCHAR(255)
) DATA_RETENTION_TIME_IN_DAYS = 0;

-- name: TABLE_USER_ROLE
CREATE TABLE IF NOT EXISTS &DB.&SCHEMA.TBL_ACCESS_USER_ROLE (   -- role -> user
    RUN_ID VARCHAR(36),
    USER_NAME VARCHAR(255),
    ROLE_NAME VARCHAR(255),
    GRANTED_BY VARCHAR(255)
) DATA_RETENTION_TIME_IN_DAYS = 0;

-- name: TABLE_USER
CREATE TABLE IF NOT EXISTS &DB.&SCHEMA.TBL_ACCESS_USER (   -- user profile
    RUN_ID VARCHAR(36),
    USER_NAME VARCHAR(255),
    TYPE VARCHAR(50),                -- PERSON, SERVICE, LEGACY_SERVICE, empty = PERSON
    DISABLED BOOLEAN,
    DEFAULT_ROLE VARCHAR(255),
    DEFAULT_SECONDARY_ROLES VARCHAR(255),   -- e.g. ["ALL"]
    DEFAULT_WAREHOUSE VARCHAR(255),
    DEFAULT_NAMESPACE VARCHAR(500),
    LAST_SUCCESS_LOGIN TIMESTAMP_LTZ
) DATA_RETENTION_TIME_IN_DAYS = 0;

-- name: TABLE_USAGE
CREATE TABLE IF NOT EXISTS &DB.&SCHEMA.TBL_ACCESS_USAGE (   -- roles and warehouses used, per user
    RUN_ID VARCHAR(36),
    USER_NAME VARCHAR(255),
    KIND VARCHAR(20),                -- ROLE, SECONDARY ROLE, WAREHOUSE
    NAME VARCHAR(255),
    QUERIES NUMBER,
    LAST_USED TIMESTAMP_LTZ
) DATA_RETENTION_TIME_IN_DAYS = 0;

-- name: TABLE_TAG
CREATE TABLE IF NOT EXISTS &DB.&SCHEMA.TBL_ACCESS_TAG (   -- tags on databases, schemas, tables/views, columns
    RUN_ID VARCHAR(36),
    OBJECT_NAME VARCHAR(2000),       -- DATABASE: DB · SCHEMA: DB.SCHEMA · TABLE / COLUMN: DB.SCHEMA.OBJECT
    DOMAIN VARCHAR(50),              -- DATABASE, SCHEMA, TABLE, COLUMN
    COLUMN_NAME VARCHAR(255),
    TAG_NAME VARCHAR(500),           -- TAG_DATABASE.TAG_SCHEMA.TAG_NAME
    TAG_VALUE VARCHAR(500),
    APPLY_METHOD VARCHAR(50)         -- MANUAL, CLASSIFIED, PROPAGATED, INHERITED, ...
) DATA_RETENTION_TIME_IN_DAYS = 0;

-- name: TABLE_POLICY
CREATE TABLE IF NOT EXISTS &DB.&SCHEMA.TBL_ACCESS_POLICY (   -- masking and row access policies and where they sit
    RUN_ID VARCHAR(36),
    POLICY_NAME VARCHAR(500),        -- DB.SCHEMA.POLICY
    POLICY_KIND VARCHAR(50),         -- MASKING_POLICY, ROW_ACCESS_POLICY
    OBJECT_NAME VARCHAR(2000),       -- DB.SCHEMA.OBJECT; empty for a policy set on a tag
    COLUMN_NAME VARCHAR(255),
    ARG_COLUMNS VARCHAR(2000),       -- row access policy / conditional masking arguments
    TAG_NAME VARCHAR(500),           -- tag-based policy: DB.SCHEMA.TAG
    POLICY_BODY VARCHAR              -- policy text; the app reads role checks from it (not evaluated)
) DATA_RETENTION_TIME_IN_DAYS = 0;

-- name: TABLE_STREAM
CREATE TABLE IF NOT EXISTS &DB.&SCHEMA.TBL_ACCESS_STREAM (   -- streams and their source (rule 22), from SHOW STREAMS
    RUN_ID VARCHAR(36),
    STREAM_NAME VARCHAR(2000),       -- DB.SCHEMA.STREAM
    SOURCE_NAME VARCHAR(2000),       -- DB.SCHEMA.TABLE the stream reads
    SOURCE_TYPE VARCHAR(50)          -- Table, View, ...
) DATA_RETENTION_TIME_IN_DAYS = 0;

-- name: TABLE_OBJECT_USE
CREATE TABLE IF NOT EXISTS &DB.&SCHEMA.TBL_ACCESS_OBJECT_USE (   -- objects used per user and week, from ACCESS_HISTORY
    RUN_ID VARCHAR(36),              -- (Enterprise edition; empty when not readable: Granted vs used then says why)
    USER_NAME VARCHAR(255),
    OBJECT_NAME VARCHAR(2000),       -- DB.SCHEMA.OBJECT as ACCESS_HISTORY names it
    WEEK DATE,                       -- Monday of the ISO week
    ACTION VARCHAR(10),              -- READ (objects read) or WRITE (objects modified)
    QUERIES NUMBER,
    LAST_USED TIMESTAMP_LTZ
) DATA_RETENTION_TIME_IN_DAYS = 0;

-- name: TABLE_ACTIVITY
CREATE TABLE IF NOT EXISTS &DB.&SCHEMA.TBL_ACCESS_ACTIVITY (   -- table use per day, user, role, client and statement,
    RUN_ID VARCHAR(36),              -- from ACCESS_HISTORY + QUERY_HISTORY + SESSIONS (Enterprise edition; empty when not readable)
    DAY DATE,
    USER_NAME VARCHAR(255),
    ROLE_NAME VARCHAR(255),          -- the query's primary role
    CLIENT VARCHAR(255),             -- SESSIONS.CLIENT_APPLICATION_ID without its version; NULL when SESSIONS is not readable
    OBJECT_NAME VARCHAR(2000),       -- DB.SCHEMA.OBJECT as ACCESS_HISTORY names it
    ACTION VARCHAR(10),              -- READ (objects read), WRITE (objects modified) or DDL (created, altered, dropped)
    QUERY_TYPE VARCHAR(100),         -- QUERY_HISTORY.QUERY_TYPE: SELECT, INSERT, MERGE, DELETE, ALTER_TABLE_..., ...
    QUERIES NUMBER,
    LAST_USED TIMESTAMP_LTZ,
    HOURS VARIANT,                   -- {UTC hour of day: queries}; DAY is the UTC day too
    APP VARCHAR(2000)                -- the Streamlit app the queries ran for (QUERY_TAG StreamlitName), else NULL
) DATA_RETENTION_TIME_IN_DAYS = 0;

-- name: TABLE_ACTIVITY_HOURS (may fail)
ALTER TABLE &DB.&SCHEMA.TBL_ACCESS_ACTIVITY ADD COLUMN IF NOT EXISTS HOURS VARIANT;   -- a table made before the column

-- name: TABLE_ACTIVITY_APP (may fail)
ALTER TABLE &DB.&SCHEMA.TBL_ACCESS_ACTIVITY ADD COLUMN IF NOT EXISTS APP VARCHAR(2000);

-- every run writes the snapshot tables anew and deletes the run before it, and they can be rebuilt from ACCOUNT_USAGE
-- with a CALL: no Time Travel on them (Fail-safe stays, permanent tables). The run log keeps the default.
-- Tables made before this setting get it here.
-- name: RETENTION_GRANT (may fail)
ALTER TABLE &DB.&SCHEMA.TBL_ACCESS_GRANT SET DATA_RETENTION_TIME_IN_DAYS = 0;

-- name: RETENTION_USER_ROLE (may fail)
ALTER TABLE &DB.&SCHEMA.TBL_ACCESS_USER_ROLE SET DATA_RETENTION_TIME_IN_DAYS = 0;

-- name: RETENTION_USER (may fail)
ALTER TABLE &DB.&SCHEMA.TBL_ACCESS_USER SET DATA_RETENTION_TIME_IN_DAYS = 0;

-- name: RETENTION_USAGE (may fail)
ALTER TABLE &DB.&SCHEMA.TBL_ACCESS_USAGE SET DATA_RETENTION_TIME_IN_DAYS = 0;

-- name: RETENTION_TAG (may fail)
ALTER TABLE &DB.&SCHEMA.TBL_ACCESS_TAG SET DATA_RETENTION_TIME_IN_DAYS = 0;

-- name: RETENTION_POLICY (may fail)
ALTER TABLE &DB.&SCHEMA.TBL_ACCESS_POLICY SET DATA_RETENTION_TIME_IN_DAYS = 0;

-- name: RETENTION_STREAM (may fail)
ALTER TABLE &DB.&SCHEMA.TBL_ACCESS_STREAM SET DATA_RETENTION_TIME_IN_DAYS = 0;

-- name: RETENTION_OBJECT_USE (may fail)
ALTER TABLE &DB.&SCHEMA.TBL_ACCESS_OBJECT_USE SET DATA_RETENTION_TIME_IN_DAYS = 0;

-- name: RETENTION_ACTIVITY (may fail)
ALTER TABLE &DB.&SCHEMA.TBL_ACCESS_ACTIVITY SET DATA_RETENTION_TIME_IN_DAYS = 0;

-- name: TABLE_FINDING
CREATE TABLE IF NOT EXISTS &DB.&SCHEMA.TBL_ACCESS_FINDING (   -- rule findings of the last run, filled by SP_ACCESS_FINDINGS
    RUN_ID VARCHAR(36),
    RULE_NUM VARCHAR(10),
    TITLE VARCHAR(500),
    SEVERITY VARCHAR(20),            -- High, Medium, Low
    GRANTEE VARCHAR(2000),           -- user, role or object the finding is about
    KIND VARCHAR(20),                -- user, admin, functional, technical, group, object
    DETAIL VARCHAR,
    PATH VARCHAR,                    -- A > B > C
    CREATED_AT TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
);

-- name: PROCEDURE
CREATE OR REPLACE PROCEDURE &DB.&SCHEMA.SP_ACCESS_SNAPSHOT(P_SOURCE VARCHAR DEFAULT 'AUTO')
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
EXECUTE AS OWNER
COMMENT = 'Access explorer: copies grants, users, role and object usage, tags, policies and streams into the TBL_ACCESS_ tables'
AS
$$
# P_SOURCE: AUTO = ACCOUNT_USAGE where the owner can read it, else the SHOW fallback; ACCOUNT_USAGE or SHOW = force one.
# Rows carry RUN_ID; the app reads the last OK run, so a running or failed CALL never shows half a snapshot.
import json
import re
import uuid
from datetime import timedelta

AU = "SNOWFLAKE.ACCOUNT_USAGE"
RUN = "&DB.&SCHEMA.TBL_ACCESS_RUN"
GRANT = "&DB.&SCHEMA.TBL_ACCESS_GRANT"
USER_ROLE = "&DB.&SCHEMA.TBL_ACCESS_USER_ROLE"
USER = "&DB.&SCHEMA.TBL_ACCESS_USER"
USAGE = "&DB.&SCHEMA.TBL_ACCESS_USAGE"
TAG = "&DB.&SCHEMA.TBL_ACCESS_TAG"
POLICY = "&DB.&SCHEMA.TBL_ACCESS_POLICY"
STREAM = "&DB.&SCHEMA.TBL_ACCESS_STREAM"
OBJECT_USE = "&DB.&SCHEMA.TBL_ACCESS_OBJECT_USE"
ACTIVITY = "&DB.&SCHEMA.TBL_ACCESS_ACTIVITY"
DATA = [GRANT, USER_ROLE, USER, USAGE, TAG, POLICY, STREAM, OBJECT_USE, ACTIVITY]
GRANT_COLS = ["RUN_ID", "GRANTEE_ROLE", "PRIVILEGE", "GRANTED_ON", "OBJECT_NAME", "IS_FUTURE", "GRANT_OPTION", "GRANTED_BY"]
TAG_COLS = ["RUN_ID", "OBJECT_NAME", "DOMAIN", "COLUMN_NAME", "TAG_NAME", "TAG_VALUE", "APPLY_METHOD"]
POLICY_COLS = ["RUN_ID", "POLICY_NAME", "POLICY_KIND", "OBJECT_NAME", "COLUMN_NAME", "ARG_COLUMNS", "TAG_NAME", "POLICY_BODY"]
DAYS = 30
TAG_FALLBACK_MAX = 300  # tables/views read one by one when the ACCOUNT_USAGE views are not readable
USE_DAYS = 180  # object usage kept from ACCESS_HISTORY
ACTIVITY_DAYS = 60  # table activity kept (the app's ACTIVITY_DAYS)
QUERY_TAG = "&QUERY_TAG"  # the app's own queries, left out of the activity
APP_ST = "&STREAMLIT_APP"  # the app inside Snowflake: its queries carry this StreamlitName
TIMEOUT = int("&STATEMENT_TIMEOUT")  # seconds per statement (settings.sql), 0 = Snowflake's own
WORKERS = max(1, int("&WORKERS"))  # heavy INSERT ... SELECT jobs (later()) running at once
READ_ACTIVITY = "&ACTIVITY" != "0"  # 0: no ACCESS_HISTORY reads (object use, activity)
# a statement parameter, not ALTER SESSION (refused in an owner's-rights procedure). to verify: Snowflake applies
# STATEMENT_TIMEOUT_IN_SECONDS from statement_params to a procedure's child statements and async jobs
TIMED = {"statement_params": {"STATEMENT_TIMEOUT_IN_SECONDS": TIMEOUT}} if TIMEOUT else {}


BATCH = 16  # statements sent at once as async child jobs: one SHOW after another takes minutes on big accounts
ASYNC = True  # run() clears it when a probe job gives no rows: every step then runs one statement after another
PENDING = []  # wait() of the heavy jobs started by later(), oldest first: at most WORKERS run at once
STOP = []  # set when a run has failed: waits then end the jobs already started and start none


def async_ok(session):
    """to verify: SHOW through collect_nowait() in an owner's-rights procedure. One SHOW as an async child job, read
    back; when that fails, the async path is off for the run."""
    try:
        session.sql("SHOW ROLES LIMIT 1").collect_nowait(**TIMED).result()
        return True
    except Exception:
        return False


def low(found):  # lower-case keys: SHOW columns are lower case, views upper case
    return [{k.strip('"').lower(): v for k, v in r.as_dict().items()} for r in found]


def rows(session, sql):
    """Rows as dicts with lower-case keys."""
    return low(session.sql(sql).collect(**TIMED))


def many(session, sqls):
    """rows() of each sql, BATCH at a time as async child jobs, in order; a failed one gives its exception.
    to verify: SHOW / DESCRIBE / INFORMATION_SCHEMA calls through collect_nowait() in an owner's-rights procedure;
    a statement that cannot start async runs with collect() instead, one after the other as before."""
    if not ASYNC:
        return [one(session, s) for s in sqls]
    out = []
    for i in range(0, len(sqls), BATCH):
        part, jobs = sqls[i:i + BATCH], []
        for s in part:
            try:
                jobs.append(session.sql(s).collect_nowait(**TIMED))
            except Exception:
                jobs.append(None)
        for s, j in zip(part, jobs):
            try:
                out.append(low(j.result() if j else session.sql(s).collect(**TIMED)))
            except Exception as e:
                out.append(e)
    return out


def one(session, sql):  # rows(), or the exception of a refused statement
    try:
        return rows(session, sql)
    except Exception as e:
        return e


def ready(source, note):  # a step's (source, note) known now, in the shape of later()
    return lambda: (source, note)


def later(session, table, run_id, sql, ok):
    """Starts a heavy INSERT ... SELECT as an async child job, so the heavy steps overlap. The wait() it returns gives
    the step's (source, note) once the job ends: ok, or UNAVAILABLE with this run's rows of table deleted; it waits only
    once. to verify: collect_nowait() for an INSERT in an owner's-rights procedure; one that cannot start async runs
    in wait() with collect(), as before."""
    while len(PENDING) >= WORKERS:  # the oldest heavy job ends before this one starts
        PENDING.pop(0)()
    try:
        job = session.sql(sql).collect_nowait(**TIMED) if ASYNC else None
    except Exception:
        job = None
    got = []

    def wait():
        if not got:
            got.append(ok)
            if STOP and not job:  # the run failed: this statement never started, so it has no rows to wait for
                got[0] = ("UNAVAILABLE", "not run: the run failed")
                return got[0]
            try:
                job.result() if job else session.sql(sql).collect(**TIMED)
            except Exception as e:
                got[0] = ("UNAVAILABLE", first_line(e))
                if table:  # history()'s shared INSERT ALL: one statement, so a failed one inserted nothing
                    session.sql(f"DELETE FROM {table} WHERE RUN_ID = '{run_id}'").collect(**TIMED)
        return got[0]
    PENDING.append(wait)
    return wait


def ident(name):
    return '"' + name.replace('"', '""') + '"'


def clean(name):  # SHOW quotes names with special characters; ACCOUNT_USAGE does not
    return name.replace('"', "")


def blank(v):
    return None if v in ("", "null", None) else v


def sq(text):  # inside a '...' SQL string, where backslash also escapes
    return text.replace("\\", "\\\\").replace("'", "''")


def timed_out(e):  # as access.timed_out: error 000630
    return "reached its statement or warehouse timeout" in str(e)


def first_line(e):  # the cause is on the 2nd line of "SQL compilation error:\n..."; a timeout says how to give it longer
    text, hint = " ".join(str(e).split())[:500], ""
    if timed_out(e):  # as access.timeout_hint: a limit other than TIMEOUT is the warehouse's or the account's
        m = re.search(r"timeout of (\d+) second", text)
        n = int(m[1]) if m else TIMEOUT
        hint = (f"stopped after {n / 60:g} min (STATEMENT_TIMEOUT={n}); set STATEMENT_TIMEOUT={2 * n} for "
                f"{2 * n / 60:g} minutes in settings.local.sql and run sql/1_setup.sql again; " if TIMEOUT and n == TIMEOUT
                else (f"stopped after {n / 60:g} min" if m else "stopped") + " by the warehouse or account "
                "STATEMENT_TIMEOUT_IN_SECONDS, not STATEMENT_TIMEOUT of settings.local.sql: an admin can raise it; ")
    return hint + text


def fallback(session, view, mode):
    """None = read ACCOUNT_USAGE.<view>; else the reason to use the fallback."""
    if mode == "SHOW":
        return "SHOW forced by P_SOURCE"
    try:
        session.sql(f"SELECT 1 FROM {AU}.{view} LIMIT 1").collect(**TIMED)
        return None
    except Exception as e:
        if mode == "ACCOUNT_USAGE":
            raise
        return f"{AU}.{view} not readable: {first_line(e)}"


def save(session, table, cols, data):
    if data:
        session.create_dataframe(data, schema=cols).write.save_as_table(table, mode="append", column_order="name", **TIMED)
    return len(data)


def count(session, table, run_id):
    return session.sql(f"SELECT COUNT(*) AS N FROM {table} WHERE RUN_ID = '{run_id}'").collect(**TIMED)[0]["N"]


def grants(session, run_id, mode):
    """Role -> object and role -> role (ACCOUNT_USAGE.GRANTS_TO_ROLES or SHOW GRANTS TO ROLE), role -> user
    (GRANTS_TO_USERS or SHOW GRANTS OF ROLE)."""
    out = {}
    why = fallback(session, "GRANTS_TO_ROLES", mode) or fallback(session, "GRANTS_TO_USERS", mode)
    if why is None:
        # NAME holds only the object's own name; DATABASE rows may repeat it in TABLE_CATALOG;
        # a database role grantee is a bare name: qualified with the database of what it is granted, DB.ROLE
        session.sql(f"""INSERT INTO {GRANT} ({", ".join(GRANT_COLS)})
            SELECT '{run_id}', IFF(GRANTED_TO = 'DATABASE_ROLE',
                       IFF(GRANTED_ON = 'DATABASE', NAME, TABLE_CATALOG) || '.' || GRANTEE_NAME, GRANTEE_NAME),
                   PRIVILEGE, GRANTED_ON,
                   CASE WHEN GRANTED_ON = 'DATABASE' THEN NAME
                        WHEN GRANTED_ON = 'SCHEMA' THEN TABLE_CATALOG || '.' || NAME
                        ELSE ARRAY_TO_STRING(ARRAY_CONSTRUCT_COMPACT(TABLE_CATALOG, TABLE_SCHEMA, NAME), '.') END,
                   FALSE, GRANT_OPTION, GRANTED_BY
            FROM {AU}.GRANTS_TO_ROLES WHERE DELETED_ON IS NULL AND GRANTED_TO IN ('ROLE', 'DATABASE_ROLE')""").collect(**TIMED)
        session.sql(f"""INSERT INTO {USER_ROLE} (RUN_ID, USER_NAME, ROLE_NAME, GRANTED_BY)
            SELECT '{run_id}', GRANTEE_NAME, ROLE, GRANTED_BY FROM {AU}.GRANTS_TO_USERS WHERE DELETED_ON IS NULL""").collect(**TIMED)
        out["grants"] = out["user_roles"] = ("ACCOUNT_USAGE", None)
        return out
    g, u, skipped = [], [], []
    roles = [r["name"] for r in rows(session, "SHOW ROLES")]
    got = many(session, [f"SHOW GRANTS TO ROLE {ident(r)}" for r in roles] + [f"SHOW GRANTS OF ROLE {ident(r)}" for r in roles])
    for role, to, of in zip(roles, got[:len(roles)], got[len(roles):]):
        bad = next((x for x in (to, of) if isinstance(x, Exception)), None)
        if bad:  # both SHOWs before keeping either: a half-read role would look like it has no holders; a role the
            skipped.append(f"{role}: {first_line(bad)}")  # owner may not inspect: keep going, list it in NOTES
            continue
        g += [[run_id, role, x["privilege"], x["granted_on"], clean(x["name"]), False,
               str(x.get("grant_option")).lower() == "true", x.get("granted_by")]
              for x in to if x.get("granted_to") in ("ROLE", None)]
        u += [[run_id, x["grantee_name"], role, x.get("granted_by")] for x in of if x.get("granted_to") == "USER"]
    # database roles: per database, their grants under DB.ROLE
    dbs = [d["name"] for d in rows(session, "SHOW DATABASES") if d.get("kind", "STANDARD") == "STANDARD"]
    lists = many(session, [f"SHOW DATABASE ROLES IN DATABASE {ident(db)}" for db in dbs])
    names = [(db, clean(r["name"])) for db, rs in zip(dbs, lists) if not isinstance(rs, Exception) for r in rs]
    held = dict(zip(names, many(session, [f"SHOW GRANTS TO DATABASE ROLE {ident(db)}.{ident(r)}" for db, r in names])))
    for db, rs in zip(dbs, lists):  # notes in database order, as when read one after the other
        if isinstance(rs, Exception):
            skipped.append(f"database roles in {db}: {first_line(rs)}")
            continue
        for r in rs:  # one unreadable database role skips only itself (as access.live does)
            q, got = f"{db}.{clean(r['name'])}", held[(db, clean(r["name"]))]
            if isinstance(got, Exception):
                skipped.append(f"{q}: {first_line(got)}")
                continue
            g += [[run_id, q, x["privilege"], x["granted_on"], clean(x["name"]), False,
                   str(x.get("grant_option")).lower() == "true", x.get("granted_by")] for x in got]
    save(session, GRANT, GRANT_COLS, g)
    save(session, USER_ROLE, ["RUN_ID", "USER_NAME", "ROLE_NAME", "GRANTED_BY"], u)
    note = why + (f"; {len(skipped)} roles skipped: " + " | ".join(skipped[:20]) if skipped else "")
    out["grants"] = out["user_roles"] = ("SHOW", note)
    return out


def future(session, run_id):
    """Future grants: no ACCOUNT_USAGE view, so always SHOW FUTURE GRANTS IN DATABASE / SCHEMA."""
    out, skipped = [], []
    try:  # when even SHOW DATABASES is refused, the rest of the run still loads (as access.live does)
        dbs = rows(session, "SHOW DATABASES")
    except Exception as e:
        return "UNAVAILABLE", f"SHOW DATABASES: {first_line(e)}"
    dbs = [d["name"] for d in dbs if d.get("kind", "STANDARD") == "STANDARD"]  # shares, applications: not ours
    places, nope = {}, {}  # every SHOW sent in async waves; the rows and notes then taken in database order
    for db, got in zip(dbs, many(session, [f"SHOW SCHEMAS IN DATABASE {ident(db)}" for db in dbs])):
        try:
            if isinstance(got, Exception):
                raise got
            places[db] = [f"DATABASE {ident(db)}"] + [f"SCHEMA {ident(db)}.{ident(s['name'])}"
                                                      for s in got if s["name"] != "INFORMATION_SCHEMA"]
        except Exception as e:
            nope[db] = f"{db}: {first_line(e)}"
    flat = [(db, p) for db, ps in places.items() for p in ps]
    found = dict(zip(flat, many(session, [f"SHOW FUTURE GRANTS IN {p}" for _, p in flat])))
    for db in dbs:
        if db in nope:
            skipped.append(nope[db])
            continue
        bad = None
        for p in places[db]:  # one refused place skips only itself, one note per database (as access.live does)
            got = found[(db, p)]
            if isinstance(got, Exception):
                bad = bad or f"{db}: {first_line(got)}"
                continue
            for x in got:  # to a database role of this database: DB.ROLE
                if x.get("grant_to") in ("ROLE", "DATABASE_ROLE"):
                    who = x["grantee_name"] if x["grant_to"] == "ROLE" else clean(x["grantee_name"])
                    who = who if x["grant_to"] == "ROLE" or who.startswith(db + ".") else f"{db}.{who}"
                    out.append([run_id, who, x["privilege"], x["grant_on"], clean(x["name"]), True,
                                str(x.get("grant_option")).lower() == "true", None])
        if bad:
            skipped.append(bad)
    save(session, GRANT, GRANT_COLS, out)
    return "SHOW", (f"{len(skipped)} database{'s' if len(skipped) != 1 else ''} skipped — " + " | ".join(skipped[:20]) if skipped else None)


def users(session, run_id, mode):
    why = fallback(session, "USERS", mode)
    if why is None:
        # OBJECT_CONSTRUCT(*): the secondary roles column name differs between Snowflake versions
        session.sql(f"""INSERT INTO {USER} SELECT '{run_id}', J:NAME::STRING, J:TYPE::STRING, TRY_TO_BOOLEAN(J:DISABLED::STRING),
                   J:DEFAULT_ROLE::STRING, COALESCE(J:DEFAULT_SECONDARY_ROLES, J:DEFAULT_SECONDARY_ROLE)::STRING,
                   J:DEFAULT_WAREHOUSE::STRING, J:DEFAULT_NAMESPACE::STRING, TRY_TO_TIMESTAMP_LTZ(J:LAST_SUCCESS_LOGIN::STRING)
            FROM (SELECT OBJECT_CONSTRUCT(*) AS J FROM {AU}.USERS WHERE DELETED_ON IS NULL)""").collect(**TIMED)
        return "ACCOUNT_USAGE", None
    data = [[run_id, x["name"], blank(x.get("type")), str(x.get("disabled")).lower() == "true", blank(x.get("default_role")),
             blank(x.get("default_secondary_roles")), blank(x.get("default_warehouse")), blank(x.get("default_namespace")),
             blank(x.get("last_success_login"))] for x in rows(session, "SHOW USERS")]
    save(session, USER, ["RUN_ID", "USER_NAME", "TYPE", "DISABLED", "DEFAULT_ROLE", "DEFAULT_SECONDARY_ROLES",
                         "DEFAULT_WAREHOUSE", "DEFAULT_NAMESPACE", "LAST_SUCCESS_LOGIN"], data)
    return "SHOW", why


def usage(session, run_id, mode):
    """Roles, secondary roles and warehouses used per user, aggregated in SQL: ACCOUNT_USAGE.QUERY_HISTORY (30 days)
    or INFORMATION_SCHEMA.QUERY_HISTORY (7 days, max 10000 queries, only those the owner may see)."""
    def insert_sql(src, secondary):  # grouped first, so the JSON is parsed on the groups, not on every query (as access.live)
        sql = f"""INSERT INTO {USAGE} (RUN_ID, USER_NAME, KIND, NAME, QUERIES, LAST_USED)
            WITH Q AS (SELECT USER_NAME, ROLE_NAME, WAREHOUSE_NAME, SECONDARY_ROLE_STATS, COUNT(*) AS N, MAX(START_TIME) AS T
                FROM ({src}) GROUP BY 1, 2, 3, 4)
            SELECT '{run_id}', USER_NAME, 'ROLE', ROLE_NAME, SUM(N), MAX(T) FROM Q WHERE ROLE_NAME IS NOT NULL GROUP BY 2, 4
            UNION ALL
            SELECT '{run_id}', USER_NAME, 'WAREHOUSE', WAREHOUSE_NAME, SUM(N), MAX(T) FROM Q WHERE WAREHOUSE_NAME IS NOT NULL GROUP BY 2, 4"""
        if secondary:  # SECONDARY_ROLE_STATS: JSON text, roleNames = comma-separated roles
            sql += f"""
            UNION ALL
            SELECT '{run_id}', Q.USER_NAME, 'SECONDARY ROLE', TRIM(S.VALUE::STRING), SUM(Q.N), MAX(Q.T)
            FROM Q, LATERAL FLATTEN(SPLIT(TRY_PARSE_JSON(Q.SECONDARY_ROLE_STATS):roleNames::STRING, ',')) S
            WHERE TRIM(S.VALUE::STRING) <> '' GROUP BY 2, 4"""
        return sql

    why = fallback(session, "QUERY_HISTORY", mode)
    if why is None:  # usage is extra (and a heavy read): without it the run stays OK, as in access.live
        return later(session, USAGE, run_id, insert_sql(f"""SELECT USER_NAME, ROLE_NAME, WAREHOUSE_NAME, SECONDARY_ROLE_STATS, START_TIME FROM {AU}.QUERY_HISTORY
                       WHERE START_TIME >= DATEADD(DAY, -{DAYS}, CURRENT_TIMESTAMP())""", True), ("ACCOUNT_USAGE", None))
    try:
        session.sql(insert_sql("""SELECT USER_NAME, ROLE_NAME, WAREHOUSE_NAME, NULL AS SECONDARY_ROLE_STATS, START_TIME FROM TABLE(&DB.INFORMATION_SCHEMA.QUERY_HISTORY(
                  END_TIME_RANGE_START => DATEADD(DAY, -7, CURRENT_TIMESTAMP()), RESULT_LIMIT => 10000))""", False)).collect(**TIMED)
        return ready("INFORMATION_SCHEMA", why + "; INFORMATION_SCHEMA.QUERY_HISTORY: 7 days, max 10000 queries, owner's view only")
    except Exception as e:
        return ready("UNAVAILABLE", why + f"; INFORMATION_SCHEMA.QUERY_HISTORY: {first_line(e)}")


def data_objects(session, run_id):
    """Tables and views in this run's grant data: the objects the per-object fallback reads."""
    return [r["object_name"] for r in rows(session, f"""SELECT DISTINCT OBJECT_NAME FROM {GRANT}
        WHERE RUN_ID = '{run_id}' AND NOT IS_FUTURE AND (GRANTED_ON LIKE '%TABLE%' OR GRANTED_ON LIKE '%VIEW%')
        ORDER BY 1""")]


# DB.SCHEMA.OBJECT (unquoted, as in the grant data) -> "DB"."SCHEMA"."OBJECT". To verify: clean() dropped SHOW's quotes,
# so a part that itself contains "." splits wrongly; that object's call fails and it is listed as skipped in NOTES
# (tags/policies of it lost on the SHOW fallback only; the ACCOUNT_USAGE path is not affected).
def quoted(name):
    return ".".join(ident(p) for p in name.split(".", 2))


def capped_note(why, objs, skipped):
    note = [why]
    if len(objs) > TAG_FALLBACK_MAX:
        note.append(f"{len(objs) - TAG_FALLBACK_MAX} objects past TAG_FALLBACK_MAX={TAG_FALLBACK_MAX} not read: "
                    + ", ".join(objs[TAG_FALLBACK_MAX:TAG_FALLBACK_MAX + 20]))
    if skipped:
        note.append(f"{len(skipped)} objects skipped: " + " | ".join(skipped[:20]))
    return "; ".join(note)


def tags(session, run_id, mode):
    """Tags on databases, schemas, tables/views and columns: ACCOUNT_USAGE.TAG_REFERENCES (Enterprise edition; empty on
    Standard), else INFORMATION_SCHEMA.TAG_REFERENCES + TAG_REFERENCES_ALL_COLUMNS per table/view (TAG_FALLBACK_MAX).
    Inheritance (database > schema > table > column) is resolved in the app. An error: UNAVAILABLE, the run stays OK."""
    why = fallback(session, "TAG_REFERENCES", mode)
    try:
        if why is None:
            # to verify: OBJECT_NAME holds the schema name on SCHEMA rows and the database name on DATABASE rows;
            # views come as DOMAIN = 'TABLE'; APPLY_METHOD values
            session.sql(f"""INSERT INTO {TAG} ({", ".join(TAG_COLS)})
                SELECT '{run_id}', CASE DOMAIN WHEN 'DATABASE' THEN OBJECT_NAME
                                              WHEN 'SCHEMA' THEN OBJECT_DATABASE || '.' || OBJECT_NAME
                                              ELSE OBJECT_DATABASE || '.' || OBJECT_SCHEMA || '.' || OBJECT_NAME END,
                       DOMAIN, IFF(DOMAIN = 'COLUMN', COLUMN_NAME, NULL), TAG_DATABASE || '.' || TAG_SCHEMA || '.' || TAG_NAME,
                       TAG_VALUE, APPLY_METHOD
                FROM {AU}.TAG_REFERENCES
                WHERE OBJECT_DELETED IS NULL AND DOMAIN IN ('DATABASE', 'SCHEMA', 'TABLE', 'COLUMN')""").collect(**TIMED)
            return "ACCOUNT_USAGE", None
        objs, out, skipped = data_objects(session, run_id), [], []
        cap = objs[:TAG_FALLBACK_MAX]  # each statement list sent in async waves, zipped back (as access.live)
        fns = [f"{ident(o.split('.')[0])}.INFORMATION_SCHEMA" for o in cap]
        tab = many(session, [f"SELECT * FROM TABLE({fn}.TAG_REFERENCES('{sq(quoted(o))}', 'table'))" for o, fn in zip(cap, fns)])
        ok = [i for i, r in enumerate(tab) if not isinstance(r, Exception)]  # columns only where the table call worked
        col = dict(zip(ok, many(session, [f"SELECT * FROM TABLE({fns[i]}.TAG_REFERENCES_ALL_COLUMNS('{sq(quoted(cap[i]))}', 'table'))"
                                          for i in ok])))
        for i, o in enumerate(cap):
            try:  # the table rows stay when only the column call failed, as when they ran one after the other
                # to verify: LEVEL = where the tag is set (DATABASE, SCHEMA, TABLE, COLUMN); TABLE rows include the
                # tags inherited from the schema and database; column rows set higher up are skipped (the table row has them)
                if isinstance(tab[i], Exception):
                    raise tab[i]
                for x in tab[i]:
                    out.append([run_id, o, "TABLE", None, f"{x['tag_database']}.{x['tag_schema']}.{x['tag_name']}",
                                x.get("tag_value"), "INHERITED" if x.get("level") not in (None, "TABLE") else "MANUAL"])
                if isinstance(col[i], Exception):
                    raise col[i]
                for x in col[i]:
                    if x.get("level") in (None, "COLUMN"):
                        out.append([run_id, o, "COLUMN", x.get("column_name"),
                                    f"{x['tag_database']}.{x['tag_schema']}.{x['tag_name']}", x.get("tag_value"),
                                    x.get("apply_method") or "MANUAL"])
            except Exception as e:  # an object the owner may not inspect: keep going, list it in NOTES
                skipped.append(f"{o}: {first_line(e)}")
        save(session, TAG, TAG_COLS, out)
        return "INFORMATION_SCHEMA", capped_note(why, objs, skipped)
    except Exception as e:
        session.sql(f"DELETE FROM {TAG} WHERE RUN_ID = '{run_id}'").collect(**TIMED)
        return "UNAVAILABLE", "; ".join(filter(None, [why, first_line(e)]))


def policies(session, run_id, mode):
    """Masking and row access policies with their text: ACCOUNT_USAGE.POLICY_REFERENCES + MASKING_POLICIES /
    ROW_ACCESS_POLICIES, else INFORMATION_SCHEMA.POLICY_REFERENCES per table/view (TAG_FALLBACK_MAX) and DESCRIBE for
    the text (empty when DESCRIBE fails). An error: UNAVAILABLE, the run stays OK."""
    why = fallback(session, "POLICY_REFERENCES", mode)
    try:
        if why is None:
            # to verify: a policy set on a tag comes as REF_ENTITY_DOMAIN = 'TAG'; REF_ARG_COLUMN_NAMES type;
            # whether rows of detached policies stay (POLICY_STATUS); POLICY_BODY in MASKING_POLICIES / ROW_ACCESS_POLICIES
            session.sql(f"""INSERT INTO {POLICY} ({", ".join(POLICY_COLS)})
                SELECT '{run_id}', R.POLICY_DB || '.' || R.POLICY_SCHEMA || '.' || R.POLICY_NAME, R.POLICY_KIND,
                       IFF(R.REF_ENTITY_DOMAIN = 'TAG', NULL,
                           R.REF_DATABASE_NAME || '.' || R.REF_SCHEMA_NAME || '.' || R.REF_ENTITY_NAME),
                       R.REF_COLUMN_NAME, R.REF_ARG_COLUMN_NAMES::STRING,
                       IFF(R.REF_ENTITY_DOMAIN = 'TAG', R.REF_DATABASE_NAME || '.' || R.REF_SCHEMA_NAME || '.' || R.REF_ENTITY_NAME,
                           IFF(R.TAG_NAME IS NULL, NULL, R.TAG_DATABASE || '.' || R.TAG_SCHEMA || '.' || R.TAG_NAME)),
                       COALESCE(M.POLICY_BODY, A.POLICY_BODY)
                FROM {AU}.POLICY_REFERENCES R
                LEFT JOIN {AU}.MASKING_POLICIES M ON M.POLICY_ID = R.POLICY_ID AND M.DELETED IS NULL
                LEFT JOIN {AU}.ROW_ACCESS_POLICIES A ON A.POLICY_ID = R.POLICY_ID AND A.DELETED IS NULL
                WHERE R.POLICY_KIND IN ('MASKING_POLICY', 'ROW_ACCESS_POLICY')""").collect(**TIMED)
            return "ACCOUNT_USAGE", None
        objs, out, skipped, kept, kind = data_objects(session, run_id), [], [], ("MASKING_POLICY", "ROW_ACCESS_POLICY"), {}
        cap = objs[:TAG_FALLBACK_MAX]  # each statement list sent in async waves, zipped back (as access.live)
        got = many(session, [f"""SELECT * FROM TABLE({ident(o.split('.')[0])}.INFORMATION_SCHEMA.POLICY_REFERENCES(
                        REF_ENTITY_NAME => '{sq(quoted(o))}', REF_ENTITY_DOMAIN => 'table'))""" for o in cap])
        for r in got:  # every policy found, described once, all in one wave
            for x in [] if isinstance(r, Exception) else r:
                try:
                    if x.get("policy_kind") in kept:
                        kind.setdefault(f"{x['policy_db']}.{x['policy_schema']}.{x['policy_name']}", x["policy_kind"])
                except KeyError:  # its object is skipped below with this error
                    pass
        body = {}  # to verify: DESCRIBE returns the text in column "body"
        for name, b in zip(kind, many(session, [f"DESCRIBE {'MASKING POLICY' if k == 'MASKING_POLICY' else 'ROW ACCESS POLICY'} "
                                                f"{quoted(name)}" for name, k in kind.items()])):
            body[name] = None if isinstance(b, Exception) or not b else b[0].get("body")  # no rights: "cannot derive"
        for o, r in zip(cap, got):
            try:
                if isinstance(r, Exception):
                    raise r
                for x in r:
                    if x.get("policy_kind") not in kept:
                        continue
                    name = f"{x['policy_db']}.{x['policy_schema']}.{x['policy_name']}"
                    tag = f"{x['tag_database']}.{x['tag_schema']}.{x['tag_name']}" if x.get("tag_name") else None
                    out.append([run_id, name, x["policy_kind"], o, x.get("ref_column_name"),
                                blank(x.get("ref_arg_column_names")), tag, body[name]])
            except Exception as e:
                skipped.append(f"{o}: {first_line(e)}")
        save(session, POLICY, POLICY_COLS, out)
        return "INFORMATION_SCHEMA", capped_note(why, objs, skipped)
    except Exception as e:
        session.sql(f"DELETE FROM {POLICY} WHERE RUN_ID = '{run_id}'").collect(**TIMED)
        return "UNAVAILABLE", "; ".join(filter(None, [why, first_line(e)]))


def streams(session, run_id):
    """Streams and the table they read: no ACCOUNT_USAGE view, so always SHOW STREAMS IN ACCOUNT (only the streams the
    owner's role can see). An error: UNAVAILABLE, the run stays OK (rule 22 then finds nothing).
    to verify: columns database_name, schema_name, name, table_name (fully qualified, may be quoted), source_type."""
    try:
        data = [[run_id, f"{x['database_name']}.{x['schema_name']}.{clean(x['name'])}", clean(x.get("table_name") or ""),
                 blank(x.get("source_type"))] for x in rows(session, "SHOW STREAMS IN ACCOUNT")]
        save(session, STREAM, ["RUN_ID", "STREAM_NAME", "SOURCE_NAME", "SOURCE_TYPE"], data)
        return "SHOW", None
    except Exception as e:
        session.sql(f"DELETE FROM {STREAM} WHERE RUN_ID = '{run_id}'").collect(**TIMED)
        return "UNAVAILABLE", first_line(e)


def use_sql(since):
    """Object usage from ACCESS_HISTORY (query metadata, never table data), aggregated in Snowflake per user, object,
    ISO week (its Monday, whatever WEEK_START says) and READ (objects read) / WRITE (objects modified). since: first
    Monday read ('YYYY-MM-DD'), cut at the session's midnight like the weeks, so a week read again replaces a whole
    week; ACCESS_HISTORY is scanned once. The same text is in access.py and SP_ACCESS_SNAPSHOT (sql/1_setup.sql)."""
    return f"""WITH A AS (
            SELECT QUERY_ID, USER_NAME, QUERY_START_TIME AS T, DIRECT_OBJECTS_ACCESSED, OBJECTS_MODIFIED
            FROM {AU}.ACCESS_HISTORY WHERE QUERY_START_TIME >= '{since}'::TIMESTAMP_LTZ),
        H AS (
            SELECT A.USER_NAME, A.QUERY_ID, A.T, O.VALUE:"objectName"::STRING AS OBJECT_NAME, 'READ' AS ACTION
            FROM A, LATERAL FLATTEN(A.DIRECT_OBJECTS_ACCESSED) O
            UNION ALL
            SELECT A.USER_NAME, A.QUERY_ID, A.T, O.VALUE:"objectName"::STRING, 'WRITE'
            FROM A, LATERAL FLATTEN(A.OBJECTS_MODIFIED) O)
        SELECT USER_NAME, OBJECT_NAME, DATEADD(DAY, 1 - DAYOFWEEKISO(T), T::DATE) AS WEEK, ACTION,
               COUNT(DISTINCT QUERY_ID) AS QUERIES, MAX(T) AS LAST_USED
        FROM H WHERE OBJECT_NAME IS NOT NULL GROUP BY 1, 2, 3, 4"""


def object_use(session, run_id, why, plan=False):
    """Objects used per user, ISO week and READ / WRITE: ACCOUNT_USAGE.ACCESS_HISTORY (Enterprise edition; query
    metadata, never table data), aggregated in SQL (access.use_sql has the same text). why: run()'s ACCESS_HISTORY
    probe. To keep the cost down the last OK run's whole weeks are copied, all but its last two, which are read again
    (ACCESS_HISTORY lags up to 3 hours; access.use_start does the same): the same rows as a read of every week. No
    fallback: UNAVAILABLE, the run stays OK and the app's Granted vs used screen explains it. plan: for history(), the
    first Monday read and this step's own INSERT instead of starting it."""
    try:
        if why:
            return ready("SKIPPED" if why.startswith("skipped") else "UNAVAILABLE", why)
        prev = session.sql(f"SELECT MAX_BY(RUN_ID, FINISHED_AT) AS R FROM {RUN} WHERE STATUS = 'OK'").collect(**TIMED)[0]["R"]
        first = session.sql("SELECT CURRENT_DATE() AS D").collect(**TIMED)[0]["D"] - timedelta(days=USE_DAYS)
        first -= timedelta(days=first.weekday())  # whole ISO weeks: a copied week is never counted again
        last = prev and session.sql(f"SELECT MAX(WEEK) AS W FROM {OBJECT_USE} WHERE RUN_ID = '{prev}'").collect(**TIMED)[0]["W"]
        since = max(first, last - timedelta(days=7)) if last else first
        cols = "USER_NAME, OBJECT_NAME, WEEK, ACTION, QUERIES, LAST_USED"
        if last:
            session.sql(f"""INSERT INTO {OBJECT_USE} (RUN_ID, {cols}) SELECT '{run_id}', {cols} FROM {OBJECT_USE}
                            WHERE RUN_ID = '{prev}' AND WEEK >= '{first}' AND WEEK < '{since}'""").collect(**TIMED)
        sql = f"""INSERT INTO {OBJECT_USE} (RUN_ID, {cols})
            SELECT '{run_id}', U.* FROM ({use_sql(since.isoformat())}) U"""
        return (since, sql) if plan else later(session, OBJECT_USE, run_id, sql, ("ACCOUNT_USAGE", None))
    except Exception as e:
        session.sql(f"DELETE FROM {OBJECT_USE} WHERE RUN_ID = '{run_id}'").collect(**TIMED)
        return ready("UNAVAILABLE", first_line(e))


def activity_sql(since, client=True):
    """Table activity from ACCESS_HISTORY (query metadata, never query text or table data), aggregated in Snowflake per
    day, user, role, client, object, ACTION (READ: objects read, WRITE: objects modified, DDL: created, altered or
    dropped) and QUERY_TYPE (SELECT, INSERT, MERGE, ...). Role and statement type come from QUERY_HISTORY, the client
    from SESSIONS (client=False: not readable, CLIENT stays empty). since: first day read ('YYYY-MM-DD'); both history
    views are cut at its UTC midnight (not the session's), so Snowflake prunes them, and ACCESS_HISTORY is scanned once.
    The app's own queries are left out: QUERY_TAG locally, its Streamlit app (APP_ST) inside Snowflake, and its
    TBL_ACCESS_ tables, which SP_ACCESS_SNAPSHOT writes. DAY and HOURS are in UTC: HOURS = {hour of day: queries}, so the app can count off-hours for any
    working hours without reading again. APP: the Streamlit app the query ran for (Snowflake tags them with
    {"StreamlitName": ...}, older ones "streamlitName: ..."), else NULL. The same text is in access.py and
    SP_ACCESS_SNAPSHOT (sql/1_setup.sql)."""
    col = "S.CLIENT" if client else "NULL"
    tag, app = (v.replace("\\", "\\\\").replace("'", "''") for v in (QUERY_TAG, APP_ST))  # quotes cannot end the strings
    join = (f"""LEFT JOIN (SELECT SESSION_ID, REGEXP_REPLACE(CLIENT_APPLICATION_ID, ' [0-9][0-9.]*$', '') AS CLIENT
                       FROM {AU}.SESSIONS) S ON S.SESSION_ID = Q.SESSION_ID""" if client else "")
    return f"""WITH A AS (
            SELECT QUERY_ID, USER_NAME, QUERY_START_TIME AS T, DIRECT_OBJECTS_ACCESSED, OBJECTS_MODIFIED, OBJECT_MODIFIED_BY_DDL,
                   CONVERT_TIMEZONE('UTC', QUERY_START_TIME) AS L
            FROM {AU}.ACCESS_HISTORY WHERE QUERY_START_TIME >= '{since} 00:00:00 +00:00'::TIMESTAMP_TZ),
        H AS (
            SELECT A.QUERY_ID, A.USER_NAME, A.T, A.L, O.VALUE:"objectName"::STRING AS OBJECT_NAME, 'READ' AS ACTION
            FROM A, LATERAL FLATTEN(A.DIRECT_OBJECTS_ACCESSED) O
            UNION ALL
            SELECT A.QUERY_ID, A.USER_NAME, A.T, A.L, O.VALUE:"objectName"::STRING, 'WRITE'
            FROM A, LATERAL FLATTEN(A.OBJECTS_MODIFIED) O
            UNION ALL
            SELECT QUERY_ID, USER_NAME, T, L, OBJECT_MODIFIED_BY_DDL:"objectName"::STRING, 'DDL'
            FROM A WHERE OBJECT_MODIFIED_BY_DDL IS NOT NULL),
        Q AS (
            SELECT QUERY_ID, ROLE_NAME, QUERY_TYPE, SESSION_ID,
                   COALESCE(TRY_PARSE_JSON(QUERY_TAG):StreamlitName::STRING,
                            REGEXP_SUBSTR(QUERY_TAG, 'streamlitName: ?([^,]+)', 1, 1, 'e')) AS APP
            FROM {AU}.QUERY_HISTORY
            WHERE START_TIME >= '{since} 00:00:00 +00:00'::TIMESTAMP_TZ AND COALESCE(QUERY_TAG, '') <> '{tag}'
              AND COALESCE(QUERY_TAG, '') NOT LIKE '%.{app}%'),
        G AS (
            SELECT H.L::DATE AS DAY, H.USER_NAME, Q.ROLE_NAME, {col} AS CLIENT, H.OBJECT_NAME, H.ACTION, Q.QUERY_TYPE, Q.APP,
                   HOUR(H.L) AS HR, COUNT(DISTINCT H.QUERY_ID) AS N, MAX(H.T) AS LAST_USED
            FROM H JOIN Q ON Q.QUERY_ID = H.QUERY_ID {join}
            WHERE H.OBJECT_NAME IS NOT NULL AND NOT STARTSWITH(SPLIT_PART(H.OBJECT_NAME, '.', 3), 'TBL_ACCESS_')
            GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9)
        SELECT DAY, USER_NAME, ROLE_NAME, CLIENT, OBJECT_NAME, ACTION, QUERY_TYPE, SUM(N) AS QUERIES, MAX(LAST_USED) AS LAST_USED,
               OBJECT_AGG(HR::STRING, N::VARIANT) AS HOURS, APP
        FROM G GROUP BY DAY, USER_NAME, ROLE_NAME, CLIENT, OBJECT_NAME, ACTION, QUERY_TYPE, APP"""

def activity(session, run_id, why, plan=False):
    """Table activity per day, user, role, client, object and statement (access.activity_sql has the same text). To
    keep the cost down only the days the last OK run lacks are read: its rows are copied up to the day before its last
    day, and that day and newer are read again (ACCESS_HISTORY lags up to 3 hours; access.activity_start does the
    same). why: run()'s ACCESS_HISTORY probe. No fallback: UNAVAILABLE, the run stays OK and the Activity tabs explain it.
    plan: for history(), (first day read, this step's own INSERT, its (source, note), SESSIONS readable) instead."""
    try:
        if why:
            return ready("SKIPPED" if why.startswith("skipped") else "UNAVAILABLE", why)
        prev = session.sql(f"SELECT MAX_BY(RUN_ID, FINISHED_AT) AS R FROM {RUN} WHERE STATUS = 'OK'").collect(**TIMED)[0]["R"]
        first = session.sql("SELECT CURRENT_DATE() AS D").collect(**TIMED)[0]["D"] - timedelta(days=ACTIVITY_DAYS)
        last = prev and session.sql(f"SELECT MAX(DAY) AS D FROM {ACTIVITY} WHERE RUN_ID = '{prev}'").collect(**TIMED)[0]["D"]
        since = max(first, last - timedelta(days=1)) if last else first
        cols = "DAY, USER_NAME, ROLE_NAME, CLIENT, OBJECT_NAME, ACTION, QUERY_TYPE, QUERIES, LAST_USED, HOURS, APP"
        if last:
            session.sql(f"""INSERT INTO {ACTIVITY} (RUN_ID, {cols}) SELECT '{run_id}', {cols} FROM {ACTIVITY}
                            WHERE RUN_ID = '{prev}' AND DAY >= '{first}' AND DAY < '{since}'""").collect(**TIMED)
        no_client = fallback(session, "SESSIONS", "AUTO")
        sql = f"""INSERT INTO {ACTIVITY} (RUN_ID, {cols})
            SELECT '{run_id}', A.* FROM ({activity_sql(since.isoformat(), no_client is None)}) A"""
        ok = ("ACCOUNT_USAGE", no_client and f"{no_client}: no client")
        return (since, sql, ok, no_client is None) if plan else later(session, ACTIVITY, run_id, sql, ok)
    except Exception as e:
        session.sql(f"DELETE FROM {ACTIVITY} WHERE RUN_ID = '{run_id}'").collect(**TIMED)
        return ready("UNAVAILABLE", first_line(e))


def history_sql(use_since, act_since, client=True):
    """use_sql(use_since) and activity_sql(act_since, client) as one statement that scans ACCESS_HISTORY once (A0,
    from the earlier of the two cuts) for both. Each part keeps its own cut on A0, so it gives the rows of its own
    read; PART = 'USE' rows carry use_sql's columns, 'ACT' rows activity_sql's, the rest NULL (split by
    history_rows, or SP_ACCESS_SNAPSHOT's INSERT ALL). The same text is in access.py and SP_ACCESS_SNAPSHOT
    (sql/1_setup.sql).
    to verify: Snowflake computes A0 once for both references (one WithClause in the query profile), prunes
    ACCESS_HISTORY on the LEAST() cut, and allows the parts' own WITH inside a subquery reading the outer A0."""
    def own(sql):
        return sql.replace(f"FROM {AU}.ACCESS_HISTORY WHERE", "FROM A0 WHERE")
    return f"""WITH A0 AS (
            SELECT QUERY_ID, USER_NAME, QUERY_START_TIME, DIRECT_OBJECTS_ACCESSED, OBJECTS_MODIFIED, OBJECT_MODIFIED_BY_DDL
            FROM {AU}.ACCESS_HISTORY WHERE QUERY_START_TIME >= LEAST('{use_since}'::TIMESTAMP_LTZ,
                '{act_since} 00:00:00 +00:00'::TIMESTAMP_TZ::TIMESTAMP_LTZ))
        SELECT 'USE' AS PART, USER_NAME, OBJECT_NAME, WEEK, ACTION, QUERIES, LAST_USED, NULL AS DAY, NULL AS ROLE_NAME,
               NULL AS CLIENT, NULL AS QUERY_TYPE, NULL AS HOURS, NULL AS APP
        FROM ({own(use_sql(use_since))}) U
        UNION ALL
        SELECT 'ACT', USER_NAME, OBJECT_NAME, NULL, ACTION, QUERIES, LAST_USED, DAY, ROLE_NAME, CLIENT, QUERY_TYPE, HOURS, APP
        FROM ({own(activity_sql(act_since, client))}) V"""


def history(session, run_id, why):
    """[wait() of object_use, wait() of activity], read from one ACCESS_HISTORY scan: each step copies its earlier
    rows first, then one INSERT ALL of history_sql fills both tables. When that INSERT fails (one statement: it
    inserted nothing), each step reads on its own as before, so a failing read still fails only its own step; not
    after a timeout (a read apart scans the same rows under the same limit) or once the run has failed (STOP).
    to verify: INSERT ALL from an owner's-rights procedure, as an async child job."""
    use, act = object_use(session, run_id, why, True), activity(session, run_id, why, True)
    if callable(use) or callable(act):  # skipped, not readable or failed: the other step reads alone
        return [use if callable(use) else later(session, OBJECT_USE, run_id, use[1], ("ACCOUNT_USAGE", None)),
                act if callable(act) else later(session, ACTIVITY, run_id, act[1], act[2])]
    ucols = "USER_NAME, OBJECT_NAME, WEEK, ACTION, QUERIES, LAST_USED"
    acols = "DAY, USER_NAME, ROLE_NAME, CLIENT, OBJECT_NAME, ACTION, QUERY_TYPE, QUERIES, LAST_USED, HOURS, APP"
    shared = later(session, None, run_id, f"""INSERT ALL
            WHEN PART = 'USE' THEN INTO {OBJECT_USE} (RUN_ID, {ucols}) VALUES (RUN_ID, {ucols})
            WHEN PART = 'ACT' THEN INTO {ACTIVITY} (RUN_ID, {acols}) VALUES (RUN_ID, {acols})
            SELECT '{run_id}' AS RUN_ID, H.* FROM ({history_sql(use[0].isoformat(), act[0].isoformat(), act[3])}) H""", True)
    alone = []

    def step(i):
        def wait():
            got = shared()
            if got is True:
                return [("ACCOUNT_USAGE", None), act[2]][i]
            if STOP or timed_out(got[1]):
                return got
            if not alone:
                alone.extend([later(session, OBJECT_USE, run_id, use[1], ("ACCOUNT_USAGE", None)),
                              later(session, ACTIVITY, run_id, act[1], act[2])])
            return alone[i]()
        return wait
    return [step(0), step(1)]


def run(session, p_source):
    mode = (p_source or "AUTO").upper()
    if mode not in ("AUTO", "ACCOUNT_USAGE", "SHOW"):
        raise ValueError("P_SOURCE must be AUTO, ACCOUNT_USAGE or SHOW")
    run_id = str(uuid.uuid4())
    # insert first, then look (the app has a Refresh button): with a look first, two CALLs a moment apart both start;
    # with both rows in, the earliest RUNNING of the last hour goes on and the other steps back
    session.sql(f"INSERT INTO {RUN} (RUN_ID, STARTED_AT, STATUS) SELECT '{run_id}', CURRENT_TIMESTAMP(), 'RUNNING'").collect(**TIMED)
    first = session.sql(f"""SELECT RUN_ID FROM {RUN} WHERE STATUS = 'RUNNING'
                            AND STARTED_AT > DATEADD(HOUR, -1, CURRENT_TIMESTAMP())
                            ORDER BY STARTED_AT, RUN_ID LIMIT 1""").collect(**TIMED)[0]["RUN_ID"]
    if first != run_id:
        session.sql(f"DELETE FROM {RUN} WHERE RUN_ID = '{run_id}'").collect(**TIMED)
        return {"status": "SKIPPED", "notes": {"error": f"run {first} is still running"}}
    global ASYNC
    ASYNC = async_ok(session)
    PENDING.clear()
    STOP.clear()
    result = {"run_id": run_id, "sources": {}, "row_counts": {}, "notes": {}}

    def keep(name, source, note):
        result["sources"][name] = source
        if note:
            result["notes"][name] = note

    waits = []  # wait() of the steps started as async jobs: each one ends before the counts and any cleanup
    step = "access_history"  # the step running, named in a timeout
    try:
        try:  # probed once for object use and activity; an error (P_SOURCE=ACCOUNT_USAGE) fails only those two steps
            ah = fallback(session, "ACCESS_HISTORY", mode) if READ_ACTIVITY else "skipped (ACTIVITY=0)"
        except Exception as e:
            ah = first_line(e)
        waits += history(session, run_id, ah)  # the heaviest reads start first
        step = "grants"
        for name, (source, note) in grants(session, run_id, mode).items():
            keep(name, source, note)
        step = "future_grants"
        keep("future_grants", *future(session, run_id))
        step = "users"
        keep("users", *users(session, run_id, mode))
        waits.append(usage(session, run_id, mode))
        step = "tags"
        keep("tags", *tags(session, run_id, mode))
        step = "policies"
        keep("policies", *policies(session, run_id, mode))
        step = "streams"
        keep("streams", *streams(session, run_id))
        step = "usage"
        keep("usage", *waits[2]())
        step = "object_use"
        keep("object_use", *waits[0]())
        step = "activity"
        keep("activity", *waits[1]())
        result["status"] = "OK"
    except Exception as e:
        result["status"], result["notes"]["error"] = "FAILED", (f"{step}: " if timed_out(e) else "") + first_line(e)
        STOP.append(1)
        for w in waits:
            try:
                w()
            except Exception:  # its error does not change FAILED; its rows go below
                pass
    for name, t in [("grants", GRANT), ("user_roles", USER_ROLE), ("users", USER), ("usage", USAGE), ("tags", TAG),
                    ("policies", POLICY), ("streams", STREAM), ("object_use", OBJECT_USE), ("activity", ACTIVITY)]:
        result["row_counts"][name] = count(session, t, run_id)
    if result["status"] == "FAILED":  # drop this run's partial rows
        for t in DATA:
            session.sql(f"DELETE FROM {t} WHERE RUN_ID = '{run_id}'").collect(**TIMED)
    session.sql(f"""UPDATE {RUN} SET FINISHED_AT = CURRENT_TIMESTAMP(), STATUS = ?, SOURCES = PARSE_JSON(?),
                    ROW_COUNTS = PARSE_JSON(?), NOTES = PARSE_JSON(?) WHERE RUN_ID = ?""",
                params=[result["status"], json.dumps(result["sources"]), json.dumps(result["row_counts"]),
                        json.dumps(result["notes"]), run_id]).collect(**TIMED)
    if result["status"] == "OK":  # only now, so the app always finds the rows of the last OK run; a run still
        # running (started over an hour ago, so not refused above) keeps its rows, one a day old is taken as dead
        for t in DATA:
            session.sql(f"""DELETE FROM {t} WHERE RUN_ID <> '{run_id}' AND RUN_ID NOT IN (SELECT RUN_ID FROM {RUN}
                            WHERE STATUS = 'RUNNING' AND STARTED_AT > DATEADD(DAY, -1, CURRENT_TIMESTAMP())
                            AND RUN_ID IS NOT NULL)""").collect(**TIMED)
    return result
$$;

-- ---------- worksheet access without the app: table functions + findings procedure ----------
-- The functions walk the last OK run with the same rules as access.py (test_sql.py runs this exact text on DuckDB):
-- role links = GRANTED_ON 'ROLE' or 'DATABASE_ROLE' (a database role, named DB.ROLE) + PRIVILEGE 'USAGE', minus
-- links granted to an admin role (every custom role sits under SYSADMIN), simple paths only (ROLES = the roles on the path, a user is not one), MAX_DEPTH NULL = every
-- level, cut at a fixed 50 hops without a flag (the MAX_HOPS setting is not read here).
-- Depth = roles from the start to the grant holder, holder included (a user is not a role). PATH = 'A > B > C'.
-- Arguments are read once in ARGS, so they never clash with the column names of the snapshot tables.
-- Recursive columns are cast in the anchor: Snowflake types them from the anchor and rejects a wider recursive value.
-- to verify: a recursive CTE is allowed inside a SQL UDTF, and a function argument in a CTE without FROM. The three
--   FUNCTION statements may fail so the rest of setup still runs, 1_setup_verify.sql then reports them MISSING.
--   Fallback if they fail: SQL Scripting procedures RETURNS TABLE(...) with the same body in
--   a RESULTSET returned with RETURN TABLE(res), arguments as :NAME (CALL, then RESULT_SCAN)
-- to verify: ARRAY_CONSTRUCT / ARRAY_APPEND in a recursive CTE, and ARRAY_CONTAINS with a VARIANT-cast VARCHAR

-- name: FUNCTION_ACCESS_OF (may fail)
CREATE OR REPLACE FUNCTION &DB.&SCHEMA.TF_ACCESS_OF(NAME VARCHAR, MAX_DEPTH NUMBER)
RETURNS TABLE (PRIVILEGE VARCHAR, GRANTED_ON VARCHAR, DATABASE_NAME VARCHAR, SCHEMA_NAME VARCHAR, OBJECT_NAME VARCHAR,
               DEPTH NUMBER, PATH VARCHAR, HOLDER VARCHAR)
COMMENT = 'Access explorer: every privilege a user (granted roles + PUBLIC) or role reaches, with its role path'
AS
$$
WITH RECURSIVE
ARGS AS (SELECT CAST(NAME AS VARCHAR) AS A_NAME, MAX_DEPTH AS A_MAX),
LAST_RUN AS (SELECT MAX_BY(R.RUN_ID, R.FINISHED_AT) AS RUN_ID FROM &DB.&SCHEMA.TBL_ACCESS_RUN R WHERE R.STATUS = 'OK'),
UR AS (
    SELECT U.USER_NAME, U.ROLE_NAME
    FROM &DB.&SCHEMA.TBL_ACCESS_USER_ROLE U JOIN LAST_RUN L ON U.RUN_ID = L.RUN_ID),
ALL_USERS AS (
    SELECT U.USER_NAME AS USR FROM UR U
    UNION
    SELECT U.USER_NAME FROM &DB.&SCHEMA.TBL_ACCESS_USER U JOIN LAST_RUN L ON U.RUN_ID = L.RUN_ID),
ME AS (   -- joins, not IN / NOT IN: a NULL user name would empty NOT IN
    SELECT (SELECT COUNT(*) FROM ALL_USERS X JOIN ARGS A ON X.USR = A.A_NAME) AS IS_USER,
           (SELECT COUNT(*) FROM UR U JOIN ARGS A ON U.USER_NAME = A.A_NAME WHERE U.ROLE_NAME = 'PUBLIC') AS HAS_PUBLIC),
EDGE AS (
    SELECT G.GRANTEE_ROLE AS PARENT, G.OBJECT_NAME AS CHILD
    FROM &DB.&SCHEMA.TBL_ACCESS_GRANT G JOIN LAST_RUN L ON G.RUN_ID = L.RUN_ID
    WHERE G.GRANTED_ON IN ('ROLE', 'DATABASE_ROLE') AND G.PRIVILEGE = 'USAGE'
      AND G.GRANTEE_ROLE NOT IN ('ACCOUNTADMIN', 'SECURITYADMIN', 'SYSADMIN', 'USERADMIN', 'ORGADMIN')),
STARTS AS (   -- a user: each granted role row, plus PUBLIC unless granted (1 hop); a role: itself (0 hops)
    SELECT A.A_NAME || ' > ' || U.ROLE_NAME AS PATH, U.ROLE_NAME AS NODE, 1 AS HOPS, 1 AS IS_USER
    FROM ARGS A JOIN UR U ON U.USER_NAME = A.A_NAME
    UNION ALL
    SELECT A.A_NAME || ' > PUBLIC', 'PUBLIC', 1, 1 FROM ARGS A CROSS JOIN ME M WHERE M.IS_USER > 0 AND M.HAS_PUBLIC = 0
    UNION ALL
    SELECT A.A_NAME, A.A_NAME, 0, 0 FROM ARGS A CROSS JOIN ME M WHERE M.IS_USER = 0),
WALK (PATH, ROLES, NODE, HOPS, IS_USER) AS (
    SELECT CAST(S.PATH AS VARCHAR), ARRAY_CONSTRUCT(S.NODE), CAST(S.NODE AS VARCHAR), CAST(S.HOPS AS INTEGER),
           CAST(S.IS_USER AS INTEGER)
    FROM STARTS S CROSS JOIN ARGS A
    WHERE A.A_MAX IS NULL OR S.HOPS + 1 - S.IS_USER <= A.A_MAX
    UNION ALL
    SELECT W.PATH || ' > ' || E.CHILD, ARRAY_APPEND(W.ROLES, E.CHILD), E.CHILD, W.HOPS + 1, W.IS_USER
    FROM WALK W JOIN EDGE E ON E.PARENT = W.NODE CROSS JOIN ARGS A
    WHERE W.HOPS < 50 AND (A.A_MAX IS NULL OR W.HOPS + 2 - W.IS_USER <= A.A_MAX)
      AND NOT ARRAY_CONTAINS(E.CHILD::VARIANT, W.ROLES))
SELECT P.PRIVILEGE AS PRIVILEGE,
       CASE WHEN COALESCE(P.IS_FUTURE, FALSE) THEN 'FUTURE ' || P.GRANTED_ON ELSE P.GRANTED_ON END AS GRANTED_ON,
       CASE WHEN P.GRANTED_ON = 'DATABASE' THEN P.OBJECT_NAME
            WHEN P.GRANTED_ON IN ('ACCOUNT', 'WAREHOUSE', 'ROLE', 'USER', 'INTEGRATION', 'RESOURCE MONITOR', 'COMPUTE POOL',
                                  'EXTERNAL VOLUME') OR POSITION('.' IN P.OBJECT_NAME) = 0 THEN NULL
            ELSE SPLIT_PART(P.OBJECT_NAME, '.', 1) END AS DATABASE_NAME,
       CASE WHEN P.GRANTED_ON = 'DATABASE' OR POSITION('.' IN P.OBJECT_NAME) = 0
                 OR P.GRANTED_ON IN ('ACCOUNT', 'WAREHOUSE', 'ROLE', 'USER', 'INTEGRATION', 'RESOURCE MONITOR', 'COMPUTE POOL',
                                     'EXTERNAL VOLUME') THEN NULL
            WHEN P.GRANTED_ON = 'SCHEMA' THEN SUBSTR(P.OBJECT_NAME, POSITION('.' IN P.OBJECT_NAME) + 1)
            WHEN SPLIT_PART(P.OBJECT_NAME, '.', 3) = '' THEN NULL
            ELSE SPLIT_PART(P.OBJECT_NAME, '.', 2) END AS SCHEMA_NAME,
       P.OBJECT_NAME AS OBJECT_NAME, W.HOPS + 1 - W.IS_USER AS DEPTH, W.PATH AS PATH, W.NODE AS HOLDER
FROM WALK W
JOIN &DB.&SCHEMA.TBL_ACCESS_GRANT P ON P.GRANTEE_ROLE = W.NODE
JOIN LAST_RUN L ON P.RUN_ID = L.RUN_ID
WHERE NOT (P.GRANTED_ON IN ('ROLE', 'DATABASE_ROLE') AND P.PRIVILEGE = 'USAGE')
$$;

-- name: FUNCTION_WHO_CAN (may fail)
CREATE OR REPLACE FUNCTION &DB.&SCHEMA.TF_WHO_CAN(OBJECT_NAME VARCHAR, PRIVILEGE VARCHAR, MAX_DEPTH NUMBER)
RETURNS TABLE (GRANTEE VARCHAR, GRANTEE_KIND VARCHAR, PRIVILEGE VARCHAR, DEPTH NUMBER, PATH VARCHAR)
COMMENT = 'Access explorer: every role and user that reaches a privilege on an object (PRIVILEGE NULL = any), with its path'
AS
$$
WITH RECURSIVE
ARGS AS (SELECT CAST(OBJECT_NAME AS VARCHAR) AS A_OBJ, CAST(PRIVILEGE AS VARCHAR) AS A_PRIV, MAX_DEPTH AS A_MAX),
LAST_RUN AS (SELECT MAX_BY(R.RUN_ID, R.FINISHED_AT) AS RUN_ID FROM &DB.&SCHEMA.TBL_ACCESS_RUN R WHERE R.STATUS = 'OK'),
ALL_USERS AS (
    SELECT U.USER_NAME AS USR FROM &DB.&SCHEMA.TBL_ACCESS_USER_ROLE U JOIN LAST_RUN L ON U.RUN_ID = L.RUN_ID
    UNION
    SELECT U.USER_NAME FROM &DB.&SCHEMA.TBL_ACCESS_USER U JOIN LAST_RUN L ON U.RUN_ID = L.RUN_ID),
MEMBER AS (   -- role -> user; every user holds PUBLIC, which is never listed
    SELECT U.ROLE_NAME AS NODE, U.USER_NAME AS USR
    FROM &DB.&SCHEMA.TBL_ACCESS_USER_ROLE U JOIN LAST_RUN L ON U.RUN_ID = L.RUN_ID WHERE U.ROLE_NAME <> 'PUBLIC'
    UNION ALL
    SELECT 'PUBLIC', A.USR FROM ALL_USERS A),
EDGE AS (
    SELECT G.GRANTEE_ROLE AS PARENT, G.OBJECT_NAME AS CHILD
    FROM &DB.&SCHEMA.TBL_ACCESS_GRANT G JOIN LAST_RUN L ON G.RUN_ID = L.RUN_ID
    WHERE G.GRANTED_ON IN ('ROLE', 'DATABASE_ROLE') AND G.PRIVILEGE = 'USAGE'
      AND G.GRANTEE_ROLE NOT IN ('ACCOUNTADMIN', 'SECURITYADMIN', 'SYSADMIN', 'USERADMIN', 'ORGADMIN')),
HELD AS (   -- the grants on the object; duplicates kept, each is a row of the result
    SELECT P.GRANTEE_ROLE, P.PRIVILEGE
    FROM &DB.&SCHEMA.TBL_ACCESS_GRANT P JOIN LAST_RUN L ON P.RUN_ID = L.RUN_ID CROSS JOIN ARGS A
    WHERE P.OBJECT_NAME = A.A_OBJ AND (A.A_PRIV IS NULL OR P.PRIVILEGE = A.A_PRIV)
      AND NOT (P.GRANTED_ON IN ('ROLE', 'DATABASE_ROLE') AND P.PRIVILEGE = 'USAGE')),
UP (HOLDER, PATH, ROLES, NODE, HOPS) AS (   -- grantee > ... > holder, walking up once per holder, not per privilege
    SELECT CAST(H.GRANTEE_ROLE AS VARCHAR), CAST(H.GRANTEE_ROLE AS VARCHAR), ARRAY_CONSTRUCT(H.GRANTEE_ROLE),
           CAST(H.GRANTEE_ROLE AS VARCHAR), CAST(0 AS INTEGER)
    FROM (SELECT DISTINCT X.GRANTEE_ROLE FROM HELD X) H
    UNION ALL
    SELECT U.HOLDER, E.PARENT || ' > ' || U.PATH, ARRAY_APPEND(U.ROLES, E.PARENT), E.PARENT, U.HOPS + 1
    FROM UP U JOIN EDGE E ON E.CHILD = U.NODE CROSS JOIN ARGS A
    WHERE U.HOPS < 50 AND (A.A_MAX IS NULL OR U.HOPS + 1 < A.A_MAX)
      AND NOT ARRAY_CONTAINS(E.PARENT::VARIANT, U.ROLES))
SELECT U.NODE AS GRANTEE, 'role' AS GRANTEE_KIND, H.PRIVILEGE AS PRIVILEGE, U.HOPS + 1 AS DEPTH, U.PATH AS PATH
FROM UP U JOIN HELD H ON H.GRANTEE_ROLE = U.HOLDER CROSS JOIN ARGS A
WHERE A.A_MAX IS NULL OR U.HOPS + 1 <= A.A_MAX
UNION ALL
SELECT M.USR, 'user', H.PRIVILEGE, U.HOPS + 1, M.USR || ' > ' || U.PATH
FROM UP U JOIN HELD H ON H.GRANTEE_ROLE = U.HOLDER JOIN MEMBER M ON M.NODE = U.NODE CROSS JOIN ARGS A
WHERE U.HOPS < 50 AND (A.A_MAX IS NULL OR U.HOPS + 1 <= A.A_MAX)
$$;

-- name: FUNCTION_CAN (may fail)
CREATE OR REPLACE FUNCTION &DB.&SCHEMA.TF_CAN(USER_NAME VARCHAR, PRIVILEGE VARCHAR, OBJECT_NAME VARCHAR)
RETURNS TABLE (PATH VARCHAR, HOPS NUMBER, HOLDER VARCHAR, VIA_OWNERSHIP BOOLEAN)
COMMENT = 'Access explorer: every path through which a user holds a privilege on an object, or OWNERSHIP of it; no rows = no'
AS
$$
WITH RECURSIVE   -- the TF_ACCESS_OF walk, with the object filter in the grant join instead of after it
ARGS AS (SELECT CAST(USER_NAME AS VARCHAR) AS A_NAME, CAST(PRIVILEGE AS VARCHAR) AS A_PRIV,
                CAST(OBJECT_NAME AS VARCHAR) AS A_OBJ),
LAST_RUN AS (SELECT MAX_BY(R.RUN_ID, R.FINISHED_AT) AS RUN_ID FROM &DB.&SCHEMA.TBL_ACCESS_RUN R WHERE R.STATUS = 'OK'),
UR AS (
    SELECT U.USER_NAME, U.ROLE_NAME
    FROM &DB.&SCHEMA.TBL_ACCESS_USER_ROLE U JOIN LAST_RUN L ON U.RUN_ID = L.RUN_ID),
ALL_USERS AS (
    SELECT U.USER_NAME AS USR FROM UR U
    UNION
    SELECT U.USER_NAME FROM &DB.&SCHEMA.TBL_ACCESS_USER U JOIN LAST_RUN L ON U.RUN_ID = L.RUN_ID),
ME AS (
    SELECT (SELECT COUNT(*) FROM ALL_USERS X JOIN ARGS A ON X.USR = A.A_NAME) AS IS_USER,
           (SELECT COUNT(*) FROM UR U JOIN ARGS A ON U.USER_NAME = A.A_NAME WHERE U.ROLE_NAME = 'PUBLIC') AS HAS_PUBLIC),
EDGE AS (
    SELECT G.GRANTEE_ROLE AS PARENT, G.OBJECT_NAME AS CHILD
    FROM &DB.&SCHEMA.TBL_ACCESS_GRANT G JOIN LAST_RUN L ON G.RUN_ID = L.RUN_ID
    WHERE G.GRANTED_ON IN ('ROLE', 'DATABASE_ROLE') AND G.PRIVILEGE = 'USAGE'
      AND G.GRANTEE_ROLE NOT IN ('ACCOUNTADMIN', 'SECURITYADMIN', 'SYSADMIN', 'USERADMIN', 'ORGADMIN')),
STARTS AS (
    SELECT A.A_NAME || ' > ' || U.ROLE_NAME AS PATH, U.ROLE_NAME AS NODE, 1 AS HOPS, 1 AS IS_USER
    FROM ARGS A JOIN UR U ON U.USER_NAME = A.A_NAME
    UNION ALL
    SELECT A.A_NAME || ' > PUBLIC', 'PUBLIC', 1, 1 FROM ARGS A CROSS JOIN ME M WHERE M.IS_USER > 0 AND M.HAS_PUBLIC = 0
    UNION ALL
    SELECT A.A_NAME, A.A_NAME, 0, 0 FROM ARGS A CROSS JOIN ME M WHERE M.IS_USER = 0),
WALK (PATH, ROLES, NODE, HOPS, IS_USER) AS (
    SELECT CAST(S.PATH AS VARCHAR), ARRAY_CONSTRUCT(S.NODE), CAST(S.NODE AS VARCHAR), CAST(S.HOPS AS INTEGER),
           CAST(S.IS_USER AS INTEGER)
    FROM STARTS S
    UNION ALL
    SELECT W.PATH || ' > ' || E.CHILD, ARRAY_APPEND(W.ROLES, E.CHILD), E.CHILD, W.HOPS + 1, W.IS_USER
    FROM WALK W JOIN EDGE E ON E.PARENT = W.NODE
    WHERE W.HOPS < 50 AND NOT ARRAY_CONTAINS(E.CHILD::VARIANT, W.ROLES))
SELECT W.PATH || ' > ' || P.OBJECT_NAME AS PATH, W.HOPS + 1 - W.IS_USER AS HOPS, W.NODE AS HOLDER,
       P.PRIVILEGE <> A.A_PRIV AS VIA_OWNERSHIP
FROM WALK W CROSS JOIN ARGS A
JOIN &DB.&SCHEMA.TBL_ACCESS_GRANT P ON P.GRANTEE_ROLE = W.NODE AND P.OBJECT_NAME = A.A_OBJ
     AND (P.PRIVILEGE = A.A_PRIV OR (P.PRIVILEGE = 'OWNERSHIP' AND A.A_PRIV <> 'OWNERSHIP'))
JOIN LAST_RUN L ON P.RUN_ID = L.RUN_ID
WHERE NOT (P.GRANTED_ON IN ('ROLE', 'DATABASE_ROLE') AND P.PRIVILEGE = 'USAGE')
$$;

-- access.py on a stage, imported by SP_ACCESS_FINDINGS. &HERE = this folder (run_sql.py fills it in, SnowSQL reads it from settings)
-- name: STAGE_CODE
CREATE STAGE IF NOT EXISTS &DB.&SCHEMA.STG_ACCESS_CODE COMMENT = 'Access explorer: access.py for SP_ACCESS_FINDINGS';

-- to verify: PUT through snowflake-connector-python with a quoted Windows path 'file://C:/...'
-- name: PUT_CODE
PUT 'file://&HERE/access.py' @&DB.&SCHEMA.STG_ACCESS_CODE AUTO_COMPRESS = FALSE OVERWRITE = TRUE;

-- name: PROCEDURE_FINDINGS
CREATE OR REPLACE PROCEDURE &DB.&SCHEMA.SP_ACCESS_FINDINGS(P_SETTINGS VARCHAR DEFAULT '{}')
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
IMPORTS = ('@&DB.&SCHEMA.STG_ACCESS_CODE/access.py')
HANDLER = 'run'
EXECUTE AS OWNER
COMMENT = 'Access explorer: the app''s rule checks on the last OK snapshot, written to TBL_ACCESS_FINDING'
AS
$$
# P_SETTINGS: JSON text with any of the keys in SETTINGS (README > Settings); missing keys keep access.py's defaults.
# to verify: access.py from IMPORTS is importable by name, and re-read after PUT_CODE + CREATE OR REPLACE
# to verify: os.environ may be changed inside the procedure's Python sandbox
import importlib
import json
import os

from snowflake.snowpark.types import StringType, StructField, StructType

WHERE = "&DB.&SCHEMA"
FINDING = "&DB.&SCHEMA.TBL_ACCESS_FINDING"
SETTINGS = ["ROLE_PREFIXES", "BUILD_ROLES", "SENSITIVE_TAGS", "READ_PRIVS", "DORMANT_DAYS", "MAX_DEPTH_RULE",
            "READ_ROLE_PATTERNS", "READ_SHARE", "READ_MIN_OBJECTS", "MAX_HOPS", "MAX_PATHS", "CAP_PRIVS"]
COLS = ["RUN_ID", "RULE_NUM", "TITLE", "SEVERITY", "GRANTEE", "KIND", "DETAIL", "PATH"]  # CREATED_AT: column default
# every column a string: Snowpark infers mixed or all-None columns badly
SCHEMA = StructType([StructField(c, StringType()) for c in COLS])


def run(session, p_settings):
    s = json.loads(p_settings or "{}")
    bad = sorted(set(s) - set(SETTINGS))
    if bad:
        raise ValueError(f"Unknown settings {bad}; allowed: {SETTINGS}")
    for k in SETTINGS:  # a warm Python process keeps the previous CALL's environment
        os.environ.pop(k, None)
    os.environ.update({k: str(v) for k, v in s.items()})
    import access
    importlib.reload(access)  # access.py reads its settings at import time
    d = access.snapshot(lambda sql: [r.as_dict() for r in session.sql(sql).collect()], WHERE)
    access.build(d)
    found = access.rule_rows()
    run_id = d["run"]["RUN_ID"]
    data = [[None if v is None else str(v) for v in
             (run_id, f["num"], f["title"], f["severity"], f["grantee"], f["kind"], f["detail"], " > ".join(f["path"]))]
            for f in found]
    session.sql("BEGIN TRANSACTION").collect()  # each statement commits on its own: keep the old rows if the insert fails
    try:
        session.sql(f"DELETE FROM {FINDING}").collect()  # the last run only, as the snapshot tables
        # to verify: append with column_order="name" fills the omitted CREATED_AT from its default, and stays inside the
        # transaction (Snowpark may upload many rows through a temporary table, and DDL would commit)
        if data:
            session.create_dataframe(data, schema=SCHEMA).write.save_as_table(FINDING, mode="append", column_order="name")
        session.sql("COMMIT").collect()
    except Exception:
        session.sql("ROLLBACK").collect()
        raise
    per_rule = {}
    for f in found:
        per_rule[f["rule"]] = per_rule.get(f["rule"], 0) + 1
    return {"run_id": run_id, "findings": len(found), "per_rule": per_rule}
$$;

-- app role: reads the snapshot tables, nothing else (POC: app role = developer role, so these are skipped or no-ops)
-- name: GRANT_DATABASE_APP (may fail)
GRANT USAGE ON DATABASE &DB TO ROLE &APP_ROLE;

-- name: GRANT_SCHEMA_APP (may fail)
GRANT USAGE ON SCHEMA &DB.&SCHEMA TO ROLE &APP_ROLE;

-- name: GRANT_WAREHOUSE_APP (may fail)
GRANT USAGE ON WAREHOUSE &WH TO ROLE &APP_ROLE;

-- name: GRANT_TABLES_APP (may fail)
GRANT SELECT ON TABLE &DB.&SCHEMA.TBL_ACCESS_RUN TO ROLE &APP_ROLE;

-- name: GRANT_TABLE_GRANT_APP (may fail)
GRANT SELECT ON TABLE &DB.&SCHEMA.TBL_ACCESS_GRANT TO ROLE &APP_ROLE;

-- name: GRANT_TABLE_USER_ROLE_APP (may fail)
GRANT SELECT ON TABLE &DB.&SCHEMA.TBL_ACCESS_USER_ROLE TO ROLE &APP_ROLE;

-- name: GRANT_TABLE_USER_APP (may fail)
GRANT SELECT ON TABLE &DB.&SCHEMA.TBL_ACCESS_USER TO ROLE &APP_ROLE;

-- name: GRANT_TABLE_USAGE_APP (may fail)
GRANT SELECT ON TABLE &DB.&SCHEMA.TBL_ACCESS_USAGE TO ROLE &APP_ROLE;

-- name: GRANT_TABLE_TAG_APP (may fail)
GRANT SELECT ON TABLE &DB.&SCHEMA.TBL_ACCESS_TAG TO ROLE &APP_ROLE;

-- name: GRANT_TABLE_POLICY_APP (may fail)
GRANT SELECT ON TABLE &DB.&SCHEMA.TBL_ACCESS_POLICY TO ROLE &APP_ROLE;

-- name: GRANT_TABLE_STREAM_APP (may fail)
GRANT SELECT ON TABLE &DB.&SCHEMA.TBL_ACCESS_STREAM TO ROLE &APP_ROLE;

-- name: GRANT_TABLE_OBJECT_USE_APP (may fail)
GRANT SELECT ON TABLE &DB.&SCHEMA.TBL_ACCESS_OBJECT_USE TO ROLE &APP_ROLE;

-- name: GRANT_TABLE_ACTIVITY_APP (may fail)
GRANT SELECT ON TABLE &DB.&SCHEMA.TBL_ACCESS_ACTIVITY TO ROLE &APP_ROLE;

-- name: GRANT_TABLE_FINDING_APP (may fail)
GRANT SELECT ON TABLE &DB.&SCHEMA.TBL_ACCESS_FINDING TO ROLE &APP_ROLE;

-- worksheet table functions. to verify: a SQL UDTF reads the tables with its owner's rights, so USAGE is enough
-- name: GRANT_FUNCTION_ACCESS_OF_APP (may fail)
GRANT USAGE ON FUNCTION &DB.&SCHEMA.TF_ACCESS_OF(VARCHAR, NUMBER) TO ROLE &APP_ROLE;

-- name: GRANT_FUNCTION_WHO_CAN_APP (may fail)
GRANT USAGE ON FUNCTION &DB.&SCHEMA.TF_WHO_CAN(VARCHAR, VARCHAR, NUMBER) TO ROLE &APP_ROLE;

-- name: GRANT_FUNCTION_CAN_APP (may fail)
GRANT USAGE ON FUNCTION &DB.&SCHEMA.TF_CAN(VARCHAR, VARCHAR, VARCHAR) TO ROLE &APP_ROLE;

-- the app's "Refresh snapshot now" button: the CALL runs with the owner's rights, whoever clicks
-- name: GRANT_PROCEDURE_APP (may fail)
GRANT USAGE ON PROCEDURE &DB.&SCHEMA.SP_ACCESS_SNAPSHOT(VARCHAR) TO ROLE &APP_ROLE;

-- what the developer role needs to read every grant (real set-up: infrastructure as code), one of:
--   ACCOUNT_USAGE:  GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE &DEV_ROLE   (every view)
--                   or the SNOWFLAKE database roles SECURITY_VIEWER (GRANTS_TO_*, USERS) + GOVERNANCE_VIEWER (QUERY_HISTORY,
--                   TAG_REFERENCES, POLICY_REFERENCES, MASKING_POLICIES, ROW_ACCESS_POLICIES, Enterprise edition for tags)
--   SHOW fallback:  GRANT MANAGE GRANTS ON ACCOUNT TO ROLE &DEV_ROLE   (without it SHOW lists only what the role may see)
