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
    SEVERITY VARCHAR(20),            -- Critical, High, Medium, Low
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
DBS = {}  # run id -> database_list, read once per run: database roles, schema list and inventory share it


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


def spell(kind):  # GRANTS_TO_ROLES says EXTERNAL_TABLE, SHOW says EXTERNAL TABLE: one kind (as access.tidy); role links keep _ROLE
    return kind if not isinstance(kind, str) or kind.endswith("ROLE") else kind.replace("_", " ")


def clean(name):  # SHOW quotes names with special characters; ACCOUNT_USAGE does not
    return (name or "").replace('"', "")


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
        if timed_out(e):  # a busy warehouse, not a view this role can't read: the full read is tried (as access.live)
            return None
        return f"{AU}.{view} not readable: {first_line(e)}"


def save(session, table, cols, data):
    if data:
        session.create_dataframe(data, schema=cols).write.save_as_table(table, mode="append", column_order="name", **TIMED)
    return len(data)


def count(session, table, run_id):
    return session.sql(f"SELECT COUNT(*) AS N FROM {table} WHERE RUN_ID = '{run_id}'").collect(**TIMED)[0]["N"]


def au_of(mode):  # au of database_list / schema_list / inventory_read
    return True if mode != "SHOW" else "P_SOURCE = SHOW: ACCOUNT_USAGE not read"


def databases(session, run_id, mode):
    if run_id not in DBS:
        DBS[run_id] = database_list(lambda s: many(session, s), ["&DB"], au_of(mode), first_line)
    return DBS[run_id]


def grants(session, run_id, mode):
    """Role -> object and role -> role (ACCOUNT_USAGE.GRANTS_TO_ROLES or SHOW GRANTS TO ROLE), role -> user
    (GRANTS_TO_USERS or SHOW GRANTS OF ROLE). A refused SHOW gives no rows and a note, never a failed run."""
    out = {}
    why = fallback(session, "GRANTS_TO_ROLES", mode) or fallback(session, "GRANTS_TO_USERS", mode)
    if why is None:
        try:
            # NAME holds only the object's own name; DATABASE rows may repeat it in TABLE_CATALOG;
            # a database role grantee is a bare name: qualified with the database of what it is granted, DB.ROLE
            session.sql(f"""INSERT INTO {GRANT} ({", ".join(GRANT_COLS)})
                SELECT '{run_id}', IFF(GRANTED_TO = 'DATABASE_ROLE',
                           IFF(GRANTED_ON = 'DATABASE', NAME, TABLE_CATALOG) || '.' || GRANTEE_NAME, GRANTEE_NAME),
                       PRIVILEGE, IFF(GRANTED_ON LIKE '%ROLE', GRANTED_ON, REPLACE(GRANTED_ON, '_', ' ')) AS GRANTED_ON,
                       CASE WHEN GRANTED_ON = 'DATABASE' THEN NAME
                            WHEN GRANTED_ON = 'SCHEMA' THEN TABLE_CATALOG || '.' || NAME
                            ELSE ARRAY_TO_STRING(ARRAY_CONSTRUCT_COMPACT(TABLE_CATALOG, TABLE_SCHEMA, NAME), '.') END,
                       FALSE, GRANT_OPTION, GRANTED_BY
                FROM {AU}.GRANTS_TO_ROLES WHERE DELETED_ON IS NULL AND GRANTED_TO IN ('ROLE', 'DATABASE_ROLE')""").collect(**TIMED)
            session.sql(f"""INSERT INTO {USER_ROLE} (RUN_ID, USER_NAME, ROLE_NAME, GRANTED_BY)
                SELECT '{run_id}', GRANTEE_NAME, ROLE, GRANTED_BY FROM {AU}.GRANTS_TO_USERS WHERE DELETED_ON IS NULL""").collect(**TIMED)
            out["grants"] = out["user_roles"] = ("ACCOUNT_USAGE", None)
            return out
        except Exception as e:  # refused in full: SHOW, as access.live does; timed out: the run fails, SHOW is slower still
            if mode == "ACCOUNT_USAGE" or timed_out(e):
                raise
            for t in (GRANT, USER_ROLE):
                session.sql(f"DELETE FROM {t} WHERE RUN_ID = '{run_id}'").collect(**TIMED)
            why = f"{AU}.GRANTS_TO_ROLES / GRANTS_TO_USERS: {first_line(e)}"
    g, u, skipped = [], [], []
    try:  # refused: no grants, the rest of the run still loads and the note says why (as access.live)
        roles = [r["name"] for r in rows(session, "SHOW ROLES") if r.get("name")]
    except Exception as e:
        roles = []
        skipped.append(f"SHOW ROLES: {first_line(e)}")
    got = many(session, [f"SHOW GRANTS TO ROLE {ident(r)}" for r in roles] + [f"SHOW GRANTS OF ROLE {ident(r)}" for r in roles])
    for role, to, of in zip(roles, got[:len(roles)], got[len(roles):]):
        bad = next((x for x in (to, of) if isinstance(x, Exception)), None)
        if bad:  # both SHOWs before keeping either: a half-read role would look like it has no holders; a role the
            skipped.append(f"{role}: {first_line(bad)}")  # owner may not inspect: keep going, list it in NOTES
            continue
        g += [[run_id, role, x.get("privilege"), spell(x.get("granted_on")), clean(x.get("name")), False,
               str(x.get("grant_option")).lower() == "true", x.get("granted_by")]
              for x in to if x.get("granted_to") in ("ROLE", "ACCOUNT ROLE", None)]
        u += [[run_id, x.get("grantee_name"), role, x.get("granted_by")] for x in of if x.get("granted_to") == "USER"]
    # database roles: per database, their grants under DB.ROLE
    how, found, dwhy = databases(session, run_id, mode)  # none listed: no database roles; future() notes it too
    dbs = [d["name"] for d in found if d.get("name") and standard(d)]
    if how == "UNAVAILABLE":
        skipped.append(f"database roles: {dwhy}")
    lists = [rs if isinstance(rs, Exception) else [r for r in rs if r.get("name")]
             for rs in many(session, [f"SHOW DATABASE ROLES IN DATABASE {ident(db)}" for db in dbs])]
    names = [(db, clean(r["name"])) for db, rs in zip(dbs, lists) if not isinstance(rs, Exception) for r in rs]
    held = dict(zip(names, many(session, [f"SHOW GRANTS TO DATABASE ROLE {ident(db)}.{ident(r)}" for db, r in names])))
    for db, rs in zip(dbs, lists):  # notes in database order, as when read one after the other
        if isinstance(rs, Exception):
            if not unseen(rs):  # a database this role cannot see: no note (as access.live)
                skipped.append(f"database roles in {db}: {first_line(rs)}")
            continue
        for r in rs:  # one unreadable database role skips only itself (as access.live does)
            q, got = f"{db}.{clean(r['name'])}", held[(db, clean(r["name"]))]
            if isinstance(got, Exception):
                skipped.append(f"{q}: {first_line(got)}")
                continue
            g += [[run_id, q, x.get("privilege"), spell(x.get("granted_on")), clean(x.get("name")), False,
                   str(x.get("grant_option")).lower() == "true", x.get("granted_by")] for x in got]
    n = len(g) + len(u)  # a row without a name or privilege: left out, as the app leaves it out (access.tidy)
    g, u = [r for r in g if all(r[1:5])], [r for r in u if r[1]]
    gone = n - len(g) - len(u)
    save(session, GRANT, GRANT_COLS, g)
    save(session, USER_ROLE, ["RUN_ID", "USER_NAME", "ROLE_NAME", "GRANTED_BY"], u)
    note = (why + (f"; {len(skipped)} roles skipped: " + " | ".join(skipped[:20]) if skipped else "")
            + (f"; {gone} rows without a name or privilege left out" if gone else ""))
    out["grants"] = out["user_roles"] = ("SHOW", note)
    return out


def future(session, run_id, mode):
    """Future grants: no view, so SHOW FUTURE GRANTS IN DATABASE / SCHEMA, over the schema list of schema_list()
    (ACCOUNT_USAGE, else INFORMATION_SCHEMA, else SHOW; P_SOURCE = SHOW: no ACCOUNT_USAGE)."""
    out, skipped, gone = [], [], 0
    dbl = databases(session, run_id, mode)
    how, listed, why = schema_list(lambda s: many(session, s), dbl, au_of(mode), first_line)
    res = {"schemas": (how, why)}
    if how == "UNAVAILABLE":  # the rest of the run still loads (as access.live does)
        return res | {"future_grants": ("UNAVAILABLE", why)}
    dbs = list(listed)  # standard databases only: shares and applications are not ours
    places, nope = {}, {}  # every SHOW sent in async waves; the rows and notes then taken in database order
    for db, got in listed.items():
        if isinstance(got, Exception):
            nope[db] = f"{db}: {first_line(got)}"
        else:
            places[db] = [f"DATABASE {ident(db)}"] + [f"SCHEMA {ident(db)}.{ident(s)}" for s in got]
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
                bad = bad or (None if unseen(got) else f"{db}: {first_line(got)}")
                continue
            for x in got:  # to a database role of this database: DB.ROLE; a row without a name is left out
                if x.get("grant_to") in ("ROLE", "DATABASE_ROLE") and not all(x.get(k) for k in ("grantee_name", "name", "privilege", "grant_on")):
                    gone += 1
                elif x.get("grant_to") in ("ROLE", "DATABASE_ROLE"):
                    who = x["grantee_name"] if x["grant_to"] == "ROLE" else clean(x["grantee_name"])
                    who = who if x["grant_to"] == "ROLE" or who.startswith(db + ".") else f"{db}.{who}"
                    out.append([run_id, who, x.get("privilege"), x.get("grant_on"), clean(x["name"]), True,
                                str(x.get("grant_option")).lower() == "true", None])
        if bad:
            skipped.append(bad)
    save(session, GRANT, GRANT_COLS, out)
    note = [f"{len(skipped)} database{'s' if len(skipped) != 1 else ''} skipped — " + " | ".join(skipped[:20])] * bool(skipped)
    note += [f"{gone} future grant row{'s' * (gone != 1)} without a name left out"] * bool(gone)  # as access.tidy does
    if flat and all(isinstance(x, Exception) for x in found.values()):  # nothing read (as access.live)
        return res | {"future_grants": ("UNAVAILABLE", "SHOW FUTURE GRANTS: "
                                        + (" | ".join(skipped[:20]) or first_line(next(iter(found.values())))))}
    return res | {"future_grants": ("SHOW", "; ".join(note) or None)}


def users(session, run_id, mode):
    why = fallback(session, "USERS", mode)
    if why is None:
        try:
            # OBJECT_CONSTRUCT(*): the secondary roles column name differs between Snowflake versions
            session.sql(f"""INSERT INTO {USER} SELECT '{run_id}', J:NAME::STRING, J:TYPE::STRING, TRY_TO_BOOLEAN(J:DISABLED::STRING),
                       J:DEFAULT_ROLE::STRING, COALESCE(J:DEFAULT_SECONDARY_ROLES, J:DEFAULT_SECONDARY_ROLE)::STRING,
                       J:DEFAULT_WAREHOUSE::STRING, J:DEFAULT_NAMESPACE::STRING, TRY_TO_TIMESTAMP_LTZ(J:LAST_SUCCESS_LOGIN::STRING)
                FROM (SELECT OBJECT_CONSTRUCT(*) AS J FROM {AU}.USERS WHERE DELETED_ON IS NULL)""").collect(**TIMED)
            return "ACCOUNT_USAGE", None
        except Exception as e:  # refused in full: SHOW USERS, as access.live does; timed out: the run fails
            if mode == "ACCOUNT_USAGE" or timed_out(e):
                raise
            session.sql(f"DELETE FROM {USER} WHERE RUN_ID = '{run_id}'").collect(**TIMED)
            why = f"{AU}.USERS: {first_line(e)}"
    try:  # refused: no users, the rest of the run still loads
        shown = rows(session, "SHOW USERS")
    except Exception as e:
        return "UNAVAILABLE", f"{why}; SHOW USERS: {first_line(e)}"
    data = [[run_id, x["name"], blank(x.get("type")), str(x.get("disabled")).lower() == "true", blank(x.get("default_role")),
             blank(x.get("default_secondary_roles")), blank(x.get("default_warehouse")), blank(x.get("default_namespace")),
             blank(x.get("last_success_login"))] for x in shown if x.get("name")]
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
        hours = [167, 144, 120, 96, 72, 48, 24, 0]  # as access.week: 7 windows, each call stops at 10,000 queries
        at = lambda h: f"DATEADD(HOUR, -{h}, CURRENT_TIMESTAMP())" if h else "CURRENT_TIMESTAMP()"
        session.sql(insert_sql(" UNION ALL ".join(
            "SELECT USER_NAME, ROLE_NAME, WAREHOUSE_NAME, NULL AS SECONDARY_ROLE_STATS, START_TIME FROM TABLE("
            f"&DB.INFORMATION_SCHEMA.QUERY_HISTORY(END_TIME_RANGE_START => {at(a)}, END_TIME_RANGE_END => {at(b)}, "
            "RESULT_LIMIT => 10000))" for a, b in zip(hours, hours[1:])), False)).collect(**TIMED)
        return ready("INFORMATION_SCHEMA", why + "; INFORMATION_SCHEMA.QUERY_HISTORY: 7 days, max 10000 queries a day, owner's view only")
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


def streams(session, run_id, mode):
    """Streams and the table they read: ACCOUNT_USAGE.STREAMS (one query), else SHOW STREAMS IN ACCOUNT (only the
    streams the owner's role can see). An error: UNAVAILABLE, the run stays OK (rule 22 then finds nothing)."""
    try:
        try:
            if mode == "SHOW":
                raise LookupError("ACCOUNT_USAGE not read")
            got, src = [dict(x, name=x["stream"]) for x in rows(session, STREAMS_SQL)], "ACCOUNT_USAGE"
        except Exception:
            got, src = [dict(x, name=f"{x['database_name']}.{x['schema_name']}.{clean(x['name'])}")
                        for x in rows(session, "SHOW STREAMS IN ACCOUNT")], "SHOW"
        data = [[run_id, x["name"], clean(x.get("table_name") or ""), blank(x.get("source_type"))] for x in got]
        save(session, STREAM, ["RUN_ID", "STREAM_NAME", "SOURCE_NAME", "SOURCE_TYPE"], data)
        return src, None
    except Exception as e:
        session.sql(f"DELETE FROM {STREAM} WHERE RUN_ID = '{run_id}'").collect(**TIMED)
        return "UNAVAILABLE", first_line(e)


STREAMS_SQL = f"""SELECT STREAM_CATALOG || '.' || STREAM_SCHEMA || '.' || STREAM_NAME AS STREAM, TABLE_NAME, SOURCE_TYPE
    FROM {AU}.STREAMS WHERE DELETED IS NULL"""


def inventory_sql():
    """The object inventory: every object the account lists, also those with no grant row (a Streamlit app or notebook
    GRANTS_TO_ROLES does not list). (step, kind, sql, info, show), read level by level by inventory_read(), so a refused
    read loses only its own kind; kind None: the row's KIND. sql: the ACCOUNT_USAGE view (DELETED IS NULL; None: none
    exists), info: the same columns from one database's INFORMATION_SCHEMA ({db} its quoted name; None: no view there;
    the DATABASES one lists every database), show: [(SHOW ... IN ACCOUNT, kind)] (only what the role can see; empty: no
    SHOW names the owner). Each read gives DATABASE_NAME, SCHEMA_NAME, NAME, OWNER, OWNER_ROLE_TYPE, as SHOW does (NULL
    where INFORMATION_SCHEMA has no OWNER_ROLE_TYPE: read as a role). Kinds as GRANTS_TO_ROLES names them (underscores).
    The same text is in access.py and SP_ACCESS_SNAPSHOT (sql/1_setup.sql). to verify: GRANTED_ON of hybrid and Iceberg
    tables (an object already granted keeps its kind); owner and owner_role_type in SHOW SEQUENCES / TASKS / TAGS /
    MASKING POLICIES / ROW ACCESS POLICIES / STREAMS / DATABASES."""
    def au(view, pre, name=None, owner=None, more="", where=""):  # a view with <pre>_CATALOG, _SCHEMA, _NAME, _OWNER
        return f"""SELECT {pre}_CATALOG AS DATABASE_NAME, {pre}_SCHEMA AS SCHEMA_NAME, {name or pre + '_NAME'} AS NAME,
                   {owner or pre + '_OWNER'} AS OWNER, OWNER_ROLE_TYPE{more}
            FROM {AU}.{view} WHERE DELETED IS NULL{where}"""

    def info(view, pre, name=None, typed=False, more="", where=""):  # the same from {db}.INFORMATION_SCHEMA.<view>
        return f"""SELECT {pre}_CATALOG AS DATABASE_NAME, {pre}_SCHEMA AS SCHEMA_NAME, {name or pre + '_NAME'} AS NAME,
                   {pre}_OWNER AS OWNER, {'' if typed else 'NULL AS '}OWNER_ROLE_TYPE{more}
            FROM {{db}}.INFORMATION_SCHEMA.{view} WHERE {pre}_SCHEMA <> 'INFORMATION_SCHEMA'{where}"""
    kind = """,
                   CASE WHEN IS_DYNAMIC = 'YES' THEN 'DYNAMIC_TABLE' WHEN IS_ICEBERG = 'YES' THEN 'ICEBERG_TABLE'
                        WHEN IS_HYBRID = 'YES' THEN 'HYBRID_TABLE' WHEN TABLE_TYPE = 'BASE TABLE' THEN 'TABLE'
                        ELSE REPLACE(TABLE_TYPE, ' ', '_') END AS KIND"""
    fn, pr = "FUNCTION_NAME || ARGUMENT_SIGNATURE", "PROCEDURE_NAME || ARGUMENT_SIGNATURE"
    return [  # DATABASES first: database_list reads it, the other kinds per database it names
        ("DATABASES", "DATABASE", f"""SELECT NULL AS DATABASE_NAME, NULL AS SCHEMA_NAME, DATABASE_NAME AS NAME,
                   DATABASE_OWNER AS OWNER, OWNER_ROLE_TYPE, TYPE FROM {AU}.DATABASES WHERE DELETED IS NULL""",
         """SELECT NULL AS DATABASE_NAME, NULL AS SCHEMA_NAME, DATABASE_NAME AS NAME, DATABASE_OWNER AS OWNER,
                   OWNER_ROLE_TYPE, TYPE FROM {db}.INFORMATION_SCHEMA.DATABASES""", [("SHOW DATABASES", "DATABASE")]),
        ("SCHEMATA", "SCHEMA", f"""SELECT CATALOG_NAME AS DATABASE_NAME, NULL AS SCHEMA_NAME, SCHEMA_NAME AS NAME,
                   SCHEMA_OWNER AS OWNER, OWNER_ROLE_TYPE FROM {AU}.SCHEMATA
            WHERE DELETED IS NULL AND SCHEMA_NAME <> 'INFORMATION_SCHEMA'""",
         """SELECT CATALOG_NAME AS DATABASE_NAME, NULL AS SCHEMA_NAME, SCHEMA_NAME AS NAME, SCHEMA_OWNER AS OWNER,
                   NULL AS OWNER_ROLE_TYPE FROM {db}.INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME <> 'INFORMATION_SCHEMA'""",
         [("SHOW SCHEMAS IN ACCOUNT", "SCHEMA")]),
        # views too; a temporary table lives only in its session
        ("TABLES", None, au("TABLES", "TABLE", more=kind, where=" AND TABLE_TYPE <> 'TEMPORARY TABLE'"),
         info("TABLES", "TABLE", more=kind, where=" AND TABLE_TYPE <> 'TEMPORARY TABLE'"),
         [("SHOW TABLES IN ACCOUNT", "TABLE"), ("SHOW VIEWS IN ACCOUNT", "VIEW")]),
        ("FUNCTIONS", "FUNCTION", au("FUNCTIONS", "FUNCTION", fn), info("FUNCTIONS", "FUNCTION", fn), []),
        ("PROCEDURES", "PROCEDURE", au("PROCEDURES", "PROCEDURE", pr), info("PROCEDURES", "PROCEDURE", pr, True), []),
        ("STAGES", "STAGE", au("STAGES", "STAGE"), info("STAGES", "STAGE"), [("SHOW STAGES IN ACCOUNT", "STAGE")]),
        ("PIPES", "PIPE", au("PIPES", "PIPE"), info("PIPES", "PIPE"), [("SHOW PIPES IN ACCOUNT", "PIPE")]),
        ("SEQUENCES", "SEQUENCE", au("SEQUENCES", "SEQUENCE"), info("SEQUENCES", "SEQUENCE"),
         [("SHOW SEQUENCES IN ACCOUNT", "SEQUENCE")]),
        ("FILE_FORMATS", "FILE_FORMAT", au("FILE_FORMATS", "FILE_FORMAT"), info("FILE_FORMATS", "FILE_FORMAT"),
         [("SHOW FILE FORMATS IN ACCOUNT", "FILE_FORMAT")]),
        ("STREAMS", "STREAM", au("STREAMS", "STREAM", owner="OWNER"), None, [("SHOW STREAMS IN ACCOUNT", "STREAM")]),
        ("TASKS", "TASK", f"""SELECT TASK_DATABASE AS DATABASE_NAME, TASK_SCHEMA AS SCHEMA_NAME, TASK_NAME AS NAME,
                   TASK_OWNER AS OWNER, OWNER_ROLE_TYPE FROM {AU}.TASKS WHERE DELETED IS NULL""", None,
         [("SHOW TASKS IN ACCOUNT", "TASK")]),
        ("TAGS", "TAG", f"""SELECT TAG_DATABASE AS DATABASE_NAME, TAG_SCHEMA AS SCHEMA_NAME, TAG_NAME AS NAME,
                   TAG_OWNER AS OWNER, OWNER_ROLE_TYPE FROM {AU}.TAGS WHERE DELETED IS NULL""", None,
         [("SHOW TAGS IN ACCOUNT", "TAG")]),
        ("MASKING_POLICIES", "MASKING_POLICY", au("MASKING_POLICIES", "POLICY"), None,
         [("SHOW MASKING POLICIES IN ACCOUNT", "MASKING_POLICY")]),
        ("ROW_ACCESS_POLICIES", "ROW_ACCESS_POLICY", au("ROW_ACCESS_POLICIES", "POLICY"), None,
         [("SHOW ROW ACCESS POLICIES IN ACCOUNT", "ROW_ACCESS_POLICY")]),
        ("INTEGRATIONS", "INTEGRATION", f"""SELECT NULL AS DATABASE_NAME, NULL AS SCHEMA_NAME, NAME, OWNER, OWNER_ROLE_TYPE
            FROM {AU}.INTEGRATIONS WHERE DELETED IS NULL""", None, []),
        ("COMPUTE_POOLS", "COMPUTE_POOL", f"""SELECT NULL AS DATABASE_NAME, NULL AS SCHEMA_NAME, NAME, OWNER, OWNER_ROLE_TYPE
            FROM {AU}.COMPUTE_POOLS WHERE DELETED IS NULL""", None, [("SHOW COMPUTE POOLS", "COMPUTE_POOL")]),
        ("STREAMLITS", "STREAMLIT", None, None, [("SHOW STREAMLITS IN ACCOUNT", "STREAMLIT")]),
        ("NOTEBOOKS", "NOTEBOOK", None, None, [("SHOW NOTEBOOKS IN ACCOUNT", "NOTEBOOK")]),
        ("ALERTS", "ALERT", None, None, [("SHOW ALERTS IN ACCOUNT", "ALERT")]),
        ("WAREHOUSES", "WAREHOUSE", None, None, [("SHOW WAREHOUSES", "WAREHOUSE")])]


def inventory_seen(grants):
    """{object name before "(": [kind, owned]} of the grant rows read, (OBJECT_NAME, GRANTED_ON, PRIVILEGE) each; a
    function's grant name carries its argument types and return type, the inventory's its argument names."""
    seen = {}
    for o, k, pv in grants:
        if isinstance(o, str) and o and k not in ("ROLE", "DATABASE_ROLE", "ACCOUNT"):
            got = seen.setdefault(o.split("(", 1)[0], [k, False])
            got[1] = got[1] or pv == "OWNERSHIP"
    return seen


def inventory_rows(seen, kind, found):
    """(owner, kind, object) for each object of one inventory read (found: rows with lower-case keys) whose ownership
    the grant read lacks: one OWNERSHIP grant row each, so an object with no grant row is listed too. Named like the
    grant rows (DB, DB.SCHEMA, DB.SCHEMA.NAME, unquoted); an object already granted keeps its kind, so kinds and counts
    merge. Owner: the role, a database role as DB.ROLE, None when no role owns it (an application) or the read does
    not say: listed with no holder. seen (inventory_seen) is updated, so a later read adds no duplicate."""
    out = []
    for x in found:
        db, sc, n = ((x.get(c) or "").replace('"', "") for c in ("database_name", "schema_name", "name"))
        k = kind or x.get("kind")
        if not n or not k or "INFORMATION_SCHEMA" in (sc, n):  # SHOW SCHEMAS / VIEWS IN ACCOUNT list it too
            continue
        name = ".".join(p for p in (db, sc, n) if p)
        got = seen.get(name.split("(", 1)[0])
        if got and got[1]:
            continue
        who, typ = x.get("owner") or None, str(x.get("owner_role_type") or "ROLE").upper()
        if typ == "DATABASE_ROLE" and who and not who.startswith(db + "."):
            who = f"{db}.{who}"
        out.append((who if typ in ("ROLE", "DATABASE_ROLE") else None, got[0] if got else k, name))
        seen[name.split("(", 1)[0]] = [out[-1][1], True]
    return out


def app_grants(apps, have, many, text):
    """Grants on Streamlit apps, which GRANTS_TO_ROLES may not list: SHOW GRANTS ON STREAMLIT per app (DB.SCHEMA.NAME).
    have: the (grantee, privilege, object) already read; an app whose owner is read keeps it. many, text: as
    database_list. A refused app is noted and skipped; a grant to anything but a role (a user, an application) is
    counted per app in the note, no row holds it. -> ([(grantee, privilege, object, grant option, granted by)], source,
    note). The same text is in access.py and SP_ACCESS_SNAPSHOT (sql/1_setup.sql). to verify: granted_to's values."""
    apps, have, out, bad, other = sorted({o for o in apps if o and o.count(".") >= 2}), set(have), [], [], {}
    owned = {o for who, pv, o in have if who and pv == "OWNERSHIP"}
    got = many(["SHOW GRANTS ON STREAMLIT " + ".".join(ident(p) for p in o.split(".", 2)) for o in apps])
    for o, r in zip(apps, got):
        if isinstance(r, Exception):
            bad.append(f"{o}: {text(r)}")
            continue
        for x in r:
            typ = str(x.get("granted_to") or "ROLE").upper().replace("_", " ")
            who, pv, db = (x.get("grantee_name") or "").replace('"', ""), x.get("privilege"), o.split(".")[0]
            if typ not in ("ROLE", "ACCOUNT ROLE", "DATABASE ROLE"):
                other[(o, typ)] = other.get((o, typ), 0) + 1
                continue
            if typ == "DATABASE ROLE" and who and not who.startswith(db + "."):
                who = f"{db}.{who}"
            if who and pv and (who, pv, o) not in have and not (pv == "OWNERSHIP" and o in owned):
                have.add((who, pv, o))
                out.append((who, pv, o, str(x.get("grant_option")).lower() == "true", x.get("granted_by")))
    note = [f"{len(bad)} of {len(apps)} apps unread: " + " | ".join(bad[:20])] * bool(bad)
    note += ["grants not to a role, not shown: "
             + " | ".join(f"{o} to {k}: {n}" for (o, k), n in sorted(other.items()))] * bool(other)
    return out, "UNAVAILABLE" if apps and len(bad) == len(apps) else "SHOW", "; ".join(note) or None


def unseen(e):
    """A database or object this role cannot see ("does not exist or not authorized"): ACCOUNT_USAGE lists every
    database, SHOW and INFORMATION_SCHEMA only those the role sees, so such a read is skipped without a note."""
    return "does not exist or not authorized" in str(e)


def standard(x):  # a database of this account, not a share or application; no type said: standard
    return (x.get("type") or x.get("kind") or "STANDARD") == "STANDARD"


def database_list(many, home, au, text):
    """Every database, for the per-database reads: ACCOUNT_USAGE.DATABASES (au True: may be read, else why it is not; lags
    up to 3 h and lists databases this role may not see), else INFORMATION_SCHEMA.DATABASES from the first database of
    home that answers, else SHOW DATABASES. The inventory's DATABASES read (inventory_sql), so inventory_read takes its
    rows. many(sqls): rows (lower-case keys) or the exception of each, in order; text(e): an error as one line. ->
    (source, rows: name, owner, owner_role_type, type (SHOW: kind), why a lower level was used)."""
    top, why = inventory_sql()[0], [] if au is True else [au]
    if au is True:
        r = many([top[2]])[0]
        if isinstance(r, list):
            return "ACCOUNT_USAGE", r, None
        why.append(f"{AU}.DATABASES: {text(r)}")
    tried = many([top[3].format(db=ident(h)) for h in home[:5]])
    found = next((r for r in tried if isinstance(r, list)), None)
    if found is not None:
        return "INFORMATION_SCHEMA", found, "; ".join(why) or None
    why.append("INFORMATION_SCHEMA.DATABASES: " + (text(tried[0]) if tried else "no database to read it from"))
    r = many(["SHOW DATABASES"])[0]
    if isinstance(r, list):
        return "SHOW", r, "; ".join(why)
    return "UNAVAILABLE", [], "; ".join(why + [f"SHOW DATABASES: {text(r)}"])


def show_kind(x, k):  # SHOW TABLES names Iceberg and hybrid tables TABLE, SHOW VIEWS a materialized view VIEW
    flag = lambda c: str(x.get(c)).upper() in ("Y", "TRUE")  # noqa: E731
    return "ICEBERG_TABLE" if flag("is_iceberg") else "HYBRID_TABLE" if flag("is_hybrid") else (
        "MATERIALIZED_VIEW" if flag("is_materialized") else k)


def inventory_read(many, dbl, au, text):
    """The inventory (inventory_sql), level by level per kind: ACCOUNT_USAGE (au as in database_list), else
    INFORMATION_SCHEMA per database (where a view exists; not when the database list came from SHOW), else SHOW; one
    level per kind, the first that answers. Per database at most, every level one wave; about one query per kind and
    database at the INFORMATION_SCHEMA level. DATABASES: the rows of database_list (dbl), which also names the
    databases. many, text: as database_list. -> ([(step, kind, rows)], source, note): source the levels used
    ("ACCOUNT_USAGE + SHOW"), note why a lower level was used and which kinds no level read."""
    steps, (how, dbs, dwhy) = inventory_sql(), dbl
    first = [s for s in steps[1:] if s[2] and au is True]
    got = dict(zip([s[0] for s in first], many([s[2] for s in first])))
    out, used = [], {}
    why = {name: [] if au is True else [au] for name, *_ in steps}
    why["DATABASES"] = [dwhy] if dwhy else []
    if how != "UNAVAILABLE":
        out.append(("DATABASES", "DATABASE", dbs))
        used["DATABASES"] = how
    for name, kind, *_ in steps[1:]:
        r = got.get(name)
        if isinstance(r, list):
            out.append((name, kind, r))
            used[name] = "ACCOUNT_USAGE"
        elif r is not None:
            why[name].append(f"{AU}.{name}: {text(r)}")
    names = [x["name"] for x in dbs if x.get("name") and standard(x)]
    per = [s for s in steps if s[0] not in used and s[3]]
    if per and how in ("SHOW", "UNAVAILABLE"):  # INFORMATION_SCHEMA.DATABASES refused: no per-database tries
        for s in per:
            why[s[0]].append(f"INFORMATION_SCHEMA: skipped, database list from {how}")
        per = []
    res = many([s[3].format(db=ident(x)) for s in per for x in names])
    for i, (name, kind, *_) in enumerate(per):
        part = res[i * len(names):(i + 1) * len(names)]
        bad = [(x, r) for x, r in zip(names, part) if isinstance(r, Exception)]
        if any(isinstance(r, list) for r in part):  # a refused database skips only itself, one it cannot see silently
            out.append((name, kind, [x for r in part if isinstance(r, list) for x in r]))
            used[name] = "INFORMATION_SCHEMA"
            bad = [(x, r) for x, r in bad if not unseen(r)]
        if bad:
            why[name].append(f"INFORMATION_SCHEMA.{name} in {len(bad)} of {len(part)} databases: "
                             + " | ".join(f"{x}: {text(r)}" for x, r in bad[:5]))
    plan = [(name, sql, k) for name, _, _, _, show in steps if name not in used for sql, k in show]
    for (name, sql, k), r in zip(plan, many([p[1] for p in plan])):
        if isinstance(r, list):  # SHOW TABLES also lists this session's temporary tables
            out.append((name, None, [dict(x, kind=show_kind(x, k)) for x in r if x.get("kind") != "TEMPORARY"]))
            used[name] = "SHOW"
        else:
            why[name].append(f"{sql}: {text(r)}")
    lower = [f"{n}: {used[n]} ({'; '.join(why[n])})" for n in used if why[n]]
    unread = [f"{n}: " + ("; ".join(why[n]) or "no view or SHOW names its owner") for n, *_ in steps if n not in used]
    note = ([f"{len(unread)} of {len(steps)} kinds unread: " + " | ".join(unread[:20])] * bool(unread)
            + ["read with a fallback: " + " | ".join(lower[:20])] * bool(lower))
    return out, " + ".join(sorted(set(used.values()))) or "UNAVAILABLE", "; ".join(note) or None


def schema_list(many, dbl, au, text):
    """The standard databases of database_list (dbl; no shares or applications) and their schemas, for SHOW FUTURE GRANTS
    (future grants have no view): ACCOUNT_USAGE.SCHEMATA (au as in database_list; lags up to 2 h), else
    INFORMATION_SCHEMA.SCHEMATA per database (not when the database list came from SHOW), else SHOW SCHEMAS per
    database; a database this role cannot see is left out. many, text: as database_list. -> (source, {database: [schema]
    or the exception of its read}, why a lower level was used or why none worked)."""
    how, dbs, dwhy = dbl
    if how == "UNAVAILABLE":
        return "UNAVAILABLE", {}, dwhy
    names, why = [x["name"] for x in dbs if x.get("name") and standard(x)], [] if au is True else [au]
    if au is True:
        r = many([f"""SELECT CATALOG_NAME AS DB, SCHEMA_NAME AS SC FROM {AU}.SCHEMATA
            WHERE DELETED IS NULL AND SCHEMA_NAME <> 'INFORMATION_SCHEMA' ORDER BY 1, 2"""])[0]
        if isinstance(r, list):
            out = {x: [] for x in names}
            for x in r:
                if x.get("db") in out and x.get("sc"):
                    out[x["db"]].append(x["sc"])
            return "ACCOUNT_USAGE", out, None
        why.append(f"{AU}.SCHEMATA: {text(r)}")
    if how == "SHOW":
        why.append("INFORMATION_SCHEMA: skipped, database list from SHOW")
    levels = ((lambda x: f"SELECT SCHEMA_NAME AS NAME FROM {ident(x)}.INFORMATION_SCHEMA.SCHEMATA "
               "WHERE SCHEMA_NAME <> 'INFORMATION_SCHEMA'", "INFORMATION_SCHEMA.SCHEMATA", "INFORMATION_SCHEMA"),
              (lambda x: f"SHOW SCHEMAS IN DATABASE {ident(x)}", "SHOW SCHEMAS", "SHOW"))
    for sql, what, level in levels[how == "SHOW":]:  # INFORMATION_SCHEMA.DATABASES refused: no per-database tries
        got = many([sql(x) for x in names])
        if not names or any(isinstance(r, list) for r in got):  # a refused database skips only itself
            out = {x: r if isinstance(r, Exception) else [s["name"] for s in r if s.get("name") not in (None, "INFORMATION_SCHEMA")]
                   for x, r in zip(names, got) if not (isinstance(r, Exception) and unseen(r))}
            return level, out, "; ".join(why) or None
        why.append(f"{what}: {text(got[0])}")
    return "UNAVAILABLE", {}, "; ".join(why)

def objects(session, run_id, mode):
    """Every object the account lists (inventory_sql), as an OWNERSHIP row in TBL_ACCESS_GRANT for each one whose
    ownership the grant read lacks (inventory_rows, as access.live): objects with no grant row are shown too. Per kind
    ACCOUNT_USAGE, else INFORMATION_SCHEMA, else SHOW (inventory_read; P_SOURCE = SHOW: no ACCOUNT_USAGE), in async
    waves; a kind no level reads is noted and skipped. An error: UNAVAILABLE, the run stays OK."""
    try:
        seen = inventory_seen((r["object_name"], r["granted_on"], r["privilege"]) for r in rows(session, f"""
            SELECT OBJECT_NAME, GRANTED_ON, MAX(CASE WHEN PRIVILEGE = 'OWNERSHIP' THEN PRIVILEGE END) AS PRIVILEGE
            FROM {GRANT} WHERE RUN_ID = '{run_id}' AND NOT IS_FUTURE GROUP BY 1, 2"""))
        found, how, why = inventory_read(lambda s: many(session, s), databases(session, run_id, mode), au_of(mode),
                                         first_line)
        added = []
        for _, kind, got in found:
            added += inventory_rows(seen, kind, got)
        save(session, GRANT, GRANT_COLS, [[run_id, who, "OWNERSHIP", spell(k), o, False, False, None] for who, k, o in added])
        return how, why
    except Exception as e:
        return "UNAVAILABLE", first_line(e)


def app_grants_step(session, run_id):
    """Grants on the Streamlit apps the grant read and the inventory list (app_grants, as access.live), added to
    TBL_ACCESS_GRANT; after objects(), which lists the apps. An error: UNAVAILABLE, the run stays OK."""
    try:
        on_app = [(r["grantee_role"], r["privilege"], r["object_name"]) for r in rows(session, f"""
            SELECT DISTINCT GRANTEE_ROLE, PRIVILEGE, OBJECT_NAME FROM {GRANT}
            WHERE RUN_ID = '{run_id}' AND GRANTED_ON = 'STREAMLIT' AND NOT IS_FUTURE""")]
        more, how, why = app_grants({x[2] for x in on_app}, on_app, lambda s: many(session, s), first_line)
        save(session, GRANT, GRANT_COLS, [[run_id, who, pv, "STREAMLIT", o, False, go, by] for who, pv, o, go, by in more])
        return how, why
    except Exception as e:
        return "UNAVAILABLE", first_line(e)


def use_sql(since):
    """Object usage from ACCESS_HISTORY (query metadata, never table data), aggregated in Snowflake per user, object,
    ISO week (its Monday, whatever WEEK_START says) and READ (objects read) / WRITE (objects modified) /
    BASE (tables read only through a view, or by an owner's-rights procedure or task). since: first
    Monday read ('YYYY-MM-DD'), cut at the session's midnight like the weeks, so a week read again replaces a whole
    week; ACCESS_HISTORY is scanned once. The same text is in access.py and SP_ACCESS_SNAPSHOT (sql/1_setup.sql)."""
    return f"""WITH A AS (
            SELECT QUERY_ID, USER_NAME, QUERY_START_TIME AS T, DIRECT_OBJECTS_ACCESSED, BASE_OBJECTS_ACCESSED, OBJECTS_MODIFIED
            FROM {AU}.ACCESS_HISTORY WHERE QUERY_START_TIME >= '{since}'::TIMESTAMP_LTZ),
        H AS (
            SELECT A.USER_NAME, A.QUERY_ID, A.T, O.VALUE:"objectName"::STRING AS OBJECT_NAME, 'READ' AS ACTION
            FROM A, LATERAL FLATTEN(A.DIRECT_OBJECTS_ACCESSED) O
            UNION ALL
            SELECT A.USER_NAME, A.QUERY_ID, A.T, O.VALUE:"objectName"::STRING, 'BASE'
            FROM A, LATERAL FLATTEN(A.BASE_OBJECTS_ACCESSED) O
            UNION ALL
            SELECT A.USER_NAME, A.QUERY_ID, A.T, O.VALUE:"objectName"::STRING, 'WRITE'
            FROM A, LATERAL FLATTEN(A.OBJECTS_MODIFIED) O),
        B AS (  -- a base object the query also read directly is a READ, not a BASE
            SELECT * FROM H
            QUALIFY ACTION <> 'BASE' OR COUNT_IF(ACTION = 'READ') OVER (PARTITION BY QUERY_ID, OBJECT_NAME) = 0)
        SELECT USER_NAME, OBJECT_NAME, DATEADD(DAY, 1 - DAYOFWEEKISO(T), T::DATE) AS WEEK, ACTION,
               COUNT(DISTINCT QUERY_ID) AS QUERIES, MAX(T) AS LAST_USED
        FROM B WHERE OBJECT_NAME IS NOT NULL GROUP BY 1, 2, 3, 4"""


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
    # SESSIONS from a week before since: unbounded it scans a year of sessions; a session open longer has no CLIENT
    join = (f"""LEFT JOIN (SELECT SESSION_ID, REGEXP_REPLACE(CLIENT_APPLICATION_ID, ' [0-9][0-9.]*$', '') AS CLIENT
                       FROM {AU}.SESSIONS WHERE CREATED_ON >= DATEADD(DAY, -7, '{since} 00:00:00 +00:00'::TIMESTAMP_TZ)) S
                ON S.SESSION_ID = Q.SESSION_ID""" if client else "")
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
            SELECT QUERY_ID, USER_NAME, QUERY_START_TIME, DIRECT_OBJECTS_ACCESSED, BASE_OBJECTS_ACCESSED, OBJECTS_MODIFIED,
                   OBJECT_MODIFIED_BY_DDL
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
    DBS.clear()
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
        for name, (source, note) in future(session, run_id, mode).items():
            keep(name, source, note)
        step = "users"
        keep("users", *users(session, run_id, mode))
        waits.append(usage(session, run_id, mode))
        step = "tags"
        keep("tags", *tags(session, run_id, mode))
        step = "policies"
        keep("policies", *policies(session, run_id, mode))
        step = "streams"
        keep("streams", *streams(session, run_id, mode))
        step = "objects"
        keep("objects", *objects(session, run_id, mode))
        step = "app_grants"
        keep("app_grants", *app_grants_step(session, run_id))
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
RETURNS TABLE (PATH VARCHAR, HOPS NUMBER, HOLDER VARCHAR, VIA_OWNERSHIP BOOLEAN, BLOCKED VARCHAR)
COMMENT = 'Access explorer: every path through which a user holds a privilege on an object, or OWNERSHIP of it; no rows = no; BLOCKED = the USAGE on its database or schema that is missing (the statement is refused)'
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
    WHERE W.HOPS < 50 AND NOT ARRAY_CONTAINS(E.CHILD::VARIANT, W.ROLES)),
NODES AS (SELECT DISTINCT W.NODE FROM WALK W),
DB_ROLES AS (   -- database roles: Snowflake grants each USAGE on its own database when it is made
    SELECT G.OBJECT_NAME AS R FROM &DB.&SCHEMA.TBL_ACCESS_GRANT G JOIN LAST_RUN L ON G.RUN_ID = L.RUN_ID
    WHERE G.GRANTED_ON = 'DATABASE_ROLE'
    UNION
    SELECT G.GRANTEE_ROLE FROM &DB.&SCHEMA.TBL_ACCESS_GRANT G JOIN LAST_RUN L ON G.RUN_ID = L.RUN_ID
    WHERE POSITION('.' IN G.GRANTEE_ROLE) > 0),
HAVE AS (   -- databases and schemas the subject has USAGE on through any role it reaches; future grants don't count
    SELECT DISTINCT G.GRANTED_ON AS T, G.OBJECT_NAME AS C
    FROM &DB.&SCHEMA.TBL_ACCESS_GRANT G JOIN LAST_RUN L ON G.RUN_ID = L.RUN_ID JOIN NODES N ON N.NODE = G.GRANTEE_ROLE
    WHERE G.GRANTED_ON IN ('DATABASE', 'SCHEMA') AND G.PRIVILEGE IN ('USAGE', 'OWNERSHIP', 'IMPORTED PRIVILEGES')
      AND NOT COALESCE(G.IS_FUTURE, FALSE)
    UNION   -- IMPORTED PRIVILEGES on a shared database cover its schemas too
    SELECT DISTINCT 'IMPORTED', G.OBJECT_NAME
    FROM &DB.&SCHEMA.TBL_ACCESS_GRANT G JOIN LAST_RUN L ON G.RUN_ID = L.RUN_ID JOIN NODES N ON N.NODE = G.GRANTEE_ROLE
    WHERE G.GRANTED_ON = 'DATABASE' AND G.PRIVILEGE = 'IMPORTED PRIVILEGES'
    UNION
    SELECT 'DATABASE', SPLIT_PART(D.R, '.', 1) FROM DB_ROLES D JOIN NODES N ON N.NODE = D.R),
ADM AS (   -- an admin role inherits every role: nothing is missing
    SELECT COUNT(*) AS N FROM NODES N WHERE N.NODE IN ('ACCOUNTADMIN', 'SECURITYADMIN', 'SYSADMIN', 'USERADMIN', 'ORGADMIN')),
HIT AS (
    SELECT W.PATH || ' > ' || P.OBJECT_NAME AS PATH, W.HOPS + 1 - W.IS_USER AS HOPS, W.NODE AS HOLDER,
           P.PRIVILEGE <> A.A_PRIV AS VIA_OWNERSHIP,
           CASE WHEN P.GRANTED_ON IN ('DATABASE', 'ACCOUNT', 'WAREHOUSE', 'ROLE', 'USER', 'INTEGRATION', 'RESOURCE MONITOR',
                                      'COMPUTE POOL', 'EXTERNAL VOLUME') OR POSITION('.' IN P.OBJECT_NAME) = 0 THEN NULL
                ELSE SPLIT_PART(P.OBJECT_NAME, '.', 1) END AS DB_NAME,
           CASE WHEN P.GRANTED_ON IN ('DATABASE', 'SCHEMA', 'ACCOUNT', 'WAREHOUSE', 'ROLE', 'USER', 'INTEGRATION',
                                      'RESOURCE MONITOR', 'COMPUTE POOL', 'EXTERNAL VOLUME')
                     OR SPLIT_PART(P.OBJECT_NAME, '.', 3) = '' THEN NULL
                ELSE SPLIT_PART(P.OBJECT_NAME, '.', 1) || '.' || SPLIT_PART(P.OBJECT_NAME, '.', 2) END AS SC_NAME
    FROM WALK W CROSS JOIN ARGS A
    JOIN &DB.&SCHEMA.TBL_ACCESS_GRANT P ON P.GRANTEE_ROLE = W.NODE AND P.OBJECT_NAME = A.A_OBJ
         AND (P.PRIVILEGE = A.A_PRIV OR (P.PRIVILEGE = 'OWNERSHIP' AND A.A_PRIV <> 'OWNERSHIP'))
    JOIN LAST_RUN L ON P.RUN_ID = L.RUN_ID
    WHERE NOT (P.GRANTED_ON IN ('ROLE', 'DATABASE_ROLE') AND P.PRIVILEGE = 'USAGE')),
GAP AS (
    SELECT H.*, CASE WHEN H.DB_NAME IS NOT NULL AND HD.C IS NULL THEN 'no USAGE on database ' || H.DB_NAME END AS NO_DB,
           CASE WHEN H.SC_NAME IS NOT NULL AND HS.C IS NULL AND HI.C IS NULL THEN 'no USAGE on schema ' || H.SC_NAME END AS NO_SC
    FROM HIT H
    LEFT JOIN HAVE HD ON HD.T = 'DATABASE' AND HD.C = H.DB_NAME
    LEFT JOIN HAVE HS ON HS.T = 'SCHEMA' AND HS.C = H.SC_NAME
    LEFT JOIN HAVE HI ON HI.T = 'IMPORTED' AND HI.C = H.DB_NAME)
SELECT G.PATH, G.HOPS, G.HOLDER, G.VIA_OWNERSHIP,
       CASE WHEN M.N > 0 THEN NULL ELSE COALESCE(G.NO_DB || ', ' || G.NO_SC, G.NO_DB, G.NO_SC) END AS BLOCKED
FROM GAP G CROSS JOIN ADM M
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
