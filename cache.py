"""Where the data comes from and how long it is kept. No Streamlit or FastAPI import.

config(): FAKE / SOURCE / ACCESS_SNAPSHOT settings -> (mode, source, where).
get(): the data once a day is enough: memory for 24 h, and locally a file in .cache/ for CACHE_HOURS (0 = memory only).
When a new read replaces a local file of another run, that file is kept as <name>.prev.pkl (What changed compares them).
Streamlit in Snowflake (access.INSIDE) has no local disk: memory only there.
sql_copy(): each read from Snowflake also goes to .cache/access.duckdb, the TBL_ACCESS_ tables to query with SQL
(DUCKDB=0: off, 1: also fake data); the app itself keeps reading the .pkl files.
"""
import os
import pathlib
import json
import pickle
import re
import threading
import time

import access  # loads .env; access.INSIDE: no local disk

DIR = pathlib.Path(__file__).with_name(".cache")
HOURS = float(os.environ.get("CACHE_HOURS", "24"))
TTL = 24 * 3600  # memory
MEM = {}
LOCK = threading.RLock()  # one read at a time: Streamlit runs a session per thread


def config(env=os.environ):
    """(mode, source, where): mode fake|snowflake; source fake|direct|objects; where = DB.SCHEMA of the objects, else ''."""
    if env.get("FAKE") == "1":
        return "fake", "fake", ""
    where = env.get("ACCESS_SNAPSHOT", "")
    source = (env.get("SOURCE") or ("objects" if where else "direct")).lower()
    if source not in ("direct", "objects"):
        raise ValueError(f"SOURCE must be direct or objects, not {source!r}")
    if source == "direct":
        return "snowflake", "direct", ""
    where = where or ".".join(filter(None, (env.get("SNOWFLAKE_DATABASE"), env.get("SNOWFLAKE_SCHEMA"))))
    if where.count(".") != 1:
        raise ValueError("SOURCE=objects needs ACCESS_SNAPSHOT=<DB>.<SCHEMA> (or SNOWFLAKE_DATABASE and SNOWFLAKE_SCHEMA)")
    return "snowflake", "objects", where


def name(what, user=None, where=""):
    """Cache name of one account + source (fake|direct|objects) + snapshot location + login, or of one user's "mine":
    everything that changes what a read returns, so another ACCESS_SNAPSHOT, user or role never gets this copy."""
    e = os.environ
    return "_".join(filter(None, (e.get("SNOWFLAKE_ACCOUNT", "local"), what, where, user or e.get("SNOWFLAKE_USER"),
                                  e.get("SNOWFLAKE_ROLE"))))


def local():
    """Whether a local file may be kept: CACHE_HOURS > 0 and not inside Snowflake."""
    return HOURS > 0 and not access.INSIDE


def file(key):
    return DIR / (re.sub(r"[^\w.-]", "_", key) + ".pkl")


def load(f):
    try:
        return pickle.loads(f.read_bytes())
    except Exception:  # unreadable or from older code
        return None


def run_of(d):
    r = (d.get("run") or {}) if isinstance(d, dict) else {}
    return r.get("RUN_ID"), str(r.get("FINISHED_AT"))


def keep_prev(f, new):
    """The local file this read replaces (or the one drop() set aside) becomes the previous snapshot, unless it holds
    the same run (a refresh of an unchanged snapshot keeps the older previous one)."""
    for old in (f, f.with_suffix(".old.pkl")):
        if old.is_file():
            d = load(old)
            if d is not None and run_of(d) != run_of(new):
                old.replace(f.with_suffix(".prev.pkl"))
                break
    f.with_suffix(".old.pkl").unlink(missing_ok=True)


def prev(key):
    """(data, fetched_at) of the previous snapshot kept locally, else None (memory only, inside Snowflake, or none yet)."""
    f = file(key).with_suffix(".prev.pkl")
    if not local() or not f.is_file():
        return None
    d = load(f)
    return (d, f.stat().st_mtime) if d is not None else None


def get(key, fn, disk=True):
    """(data, fetched_at): from memory, else the local file, else fn() (stored in both)."""
    with LOCK:
        m = MEM.get(key)
        if m and time.time() - m[1] < TTL:
            return m
        f = file(key)
        disk = disk and local()
        m = None
        if disk and f.is_file() and time.time() - f.stat().st_mtime < HOURS * 3600:
            d = load(f)
            m = (d, f.stat().st_mtime) if d is not None else None
        if not m:
            m = fn(), time.time()
            if sql_wanted(disk):
                sql_copy(key, m[0], m[1])
            if disk:
                DIR.mkdir(exist_ok=True)
                keep_prev(f, m[0])
                tmp = f.with_suffix(".tmp")
                tmp.write_bytes(pickle.dumps(m[0]))
                tmp.replace(f)
        MEM[key] = m
        return m


def ready(key, disk=True):
    """Whether get(key) answers from memory or the local file, without reading the source."""
    m = MEM.get(key)
    if m and time.time() - m[1] < TTL:
        return True
    f = file(key)
    return (disk and local() and f.is_file()
            and time.time() - f.stat().st_mtime < HOURS * 3600)


def drop(key):
    """Read again next time: out of memory, and the local file set aside (the previous snapshot once a new one is read)."""
    MEM.pop(key, None)
    f = file(key)
    if f.is_file() and HOURS > 0:
        f.replace(f.with_suffix(".old.pkl"))
    f.unlink(missing_ok=True)

# ---------- SQL copy (DuckDB) ----------

DUCKDB = os.environ.get("DUCKDB", "")  # 0: no SQL copy; 1: also of fake data; else after each read from Snowflake
# the TBL_ACCESS_ tables of sql/1_setup.sql, same names and columns (test_duckdb checks them against that file)
COLUMNS = {
    "RUN": "RUN_ID VARCHAR, STARTED_AT TIMESTAMPTZ, FINISHED_AT TIMESTAMPTZ, STATUS VARCHAR, SOURCES JSON, "
           "ROW_COUNTS JSON, NOTES JSON",
    "GRANT": "RUN_ID VARCHAR, GRANTEE_ROLE VARCHAR, PRIVILEGE VARCHAR, GRANTED_ON VARCHAR, OBJECT_NAME VARCHAR, "
             "IS_FUTURE BOOLEAN, GRANT_OPTION BOOLEAN, GRANTED_BY VARCHAR",
    "USER_ROLE": "RUN_ID VARCHAR, USER_NAME VARCHAR, ROLE_NAME VARCHAR, GRANTED_BY VARCHAR",
    "USER": "RUN_ID VARCHAR, USER_NAME VARCHAR, TYPE VARCHAR, DISABLED BOOLEAN, DEFAULT_ROLE VARCHAR, "
            "DEFAULT_SECONDARY_ROLES VARCHAR, DEFAULT_WAREHOUSE VARCHAR, DEFAULT_NAMESPACE VARCHAR, "
            "LAST_SUCCESS_LOGIN TIMESTAMPTZ",
    "USAGE": "RUN_ID VARCHAR, USER_NAME VARCHAR, KIND VARCHAR, NAME VARCHAR, QUERIES BIGINT, LAST_USED TIMESTAMPTZ",
    "TAG": "RUN_ID VARCHAR, OBJECT_NAME VARCHAR, DOMAIN VARCHAR, COLUMN_NAME VARCHAR, TAG_NAME VARCHAR, "
           "TAG_VALUE VARCHAR, APPLY_METHOD VARCHAR",
    "POLICY": "RUN_ID VARCHAR, POLICY_NAME VARCHAR, POLICY_KIND VARCHAR, OBJECT_NAME VARCHAR, COLUMN_NAME VARCHAR, "
              "ARG_COLUMNS VARCHAR, TAG_NAME VARCHAR, POLICY_BODY VARCHAR",
    "STREAM": "RUN_ID VARCHAR, STREAM_NAME VARCHAR, SOURCE_NAME VARCHAR, SOURCE_TYPE VARCHAR",
    "OBJECT_USE": "RUN_ID VARCHAR, USER_NAME VARCHAR, OBJECT_NAME VARCHAR, WEEK DATE, ACTION VARCHAR, QUERIES BIGINT, "
                  "LAST_USED TIMESTAMPTZ",
}
SQL = {}  # cache key -> what the last copy in this process did: at and run_id, or a note


def sql_file():
    return DIR / "access.duckdb"


def schema(key):
    """The DuckDB schema of one cache key (account + source + location + login): one row set each."""
    return re.sub(r"\W", "_", key).lower()


def sql_wanted(disk):
    """Whether a read gets a SQL copy: never inside Snowflake or with DUCKDB=0; fake data (disk False) only with
    DUCKDB=1; a read from Snowflake whenever a local copy may be kept (CACHE_HOURS > 0)."""
    if DUCKDB == "0" or access.INSIDE:
        return False
    return DUCKDB == "1" or (disk and local())


def stamp(at):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(at))


def sql_copy(key, d, at):
    """Write data set d to .cache/access.duckdb, schema schema(key): this read as the TBL_ACCESS_ tables, the read
    before as TBL_ACCESS_<name>_PREV (a read of the same snapshot run replaces only the current tables). COPIES (main
    schema) lists each schema with its cache key, run and read time. Without duckdb, or when the file is locked
    (another DuckDB session has it open), one note and no copy: the app works the same."""
    try:
        import duckdb
    except ImportError:
        SQL[key] = dict(note="duckdb is not installed (pip install -r requirements-web.txt), so no SQL copy was written.")
        return
    run = d.get("run") or {}
    rid = str(run.get("RUN_ID") or "")
    if rid in ("", "direct", "live", "fake"):  # direct reads and My access: a run id per read
        rid = f"{rid or 'read'}-{time.strftime('%Y%m%d%H%M%S', time.localtime(at))}"
    fin = run.get("FINISHED_AT")
    rows = {t: d.get(t) or [] for t in COLUMNS if t != "RUN"}
    rows["RUN"] = [dict(STARTED_AT=None, FINISHED_AT=stamp(at) if fin in (None, "now") else fin, STATUS="OK",
                        SOURCES=json.dumps(run.get("SOURCES") or {}, default=str),
                        ROW_COUNTS=json.dumps({t.lower(): len(v) for t, v in rows.items()}),
                        NOTES=json.dumps(run.get("NOTES") or {}, default=str))]
    s, tmp = schema(key), DIR / f"sql-{os.getpid()}.ndjson"
    try:
        DIR.mkdir(exist_ok=True)
        con = duckdb.connect(str(sql_file()))
        try:
            con.execute("SET enable_progress_bar = false")
            con.execute("BEGIN")
            con.execute("CREATE TABLE IF NOT EXISTS COPIES (SCHEMA_NAME VARCHAR, CACHE_KEY VARCHAR, RUN_ID VARCHAR, "
                        "READ_AT TIMESTAMPTZ, PREV_RUN_ID VARCHAR)")
            con.execute(f'CREATE SCHEMA IF NOT EXISTS "{s}"')
            had = con.execute("SELECT RUN_ID, PREV_RUN_ID FROM COPIES WHERE SCHEMA_NAME = ?", [s]).fetchone()
            turn = had is not None and had[0] != rid  # another run: the current tables become _PREV
            for t, cols in COLUMNS.items():
                name = f'"{s}".TBL_ACCESS_{t}'
                if turn:
                    con.execute(f'DROP TABLE IF EXISTS "{s}".TBL_ACCESS_{t}_PREV')
                    con.execute(f"ALTER TABLE IF EXISTS {name} RENAME TO TBL_ACCESS_{t}_PREV")
                con.execute(f"DROP TABLE IF EXISTS {name}")
                con.execute(f"CREATE TABLE {name} ({cols})")
                pairs = [c.split(" ") for c in cols.split(", ")]
                if rows[t]:  # one bulk read of a JSON lines file: an INSERT per row takes minutes on a big account
                    tmp.write_text("\n".join(json.dumps({c: rid if c == "RUN_ID" else r.get(c) for c, _ in pairs},
                                                        default=str) for r in rows[t]), encoding="utf-8")
                    spec = "{" + ", ".join(f"'{c}': 'VARCHAR'" for c, _ in pairs) + "}"
                    con.execute(f"INSERT INTO {name} SELECT " + ", ".join(f"TRY_CAST({c} AS {ty})" for c, ty in pairs)
                                + f" FROM read_json('{tmp.as_posix()}', format = 'newline_delimited', columns = {spec})")
            con.execute("DELETE FROM COPIES WHERE SCHEMA_NAME = ?", [s])
            con.execute("INSERT INTO COPIES VALUES (?, ?, ?, ?, ?)",
                        [s, key, rid, stamp(at), had[0] if turn else (had[1] if had else None)])
            con.execute("COMMIT")
        finally:
            con.close()
        SQL[key] = dict(run_id=rid, at=at)
    except Exception as e:
        SQL[key] = dict(note=f"The SQL copy was not written: {access.line(e)}")
    finally:
        tmp.unlink(missing_ok=True)


def sql_info(key, disk=True):
    """For the UI: where the SQL copy of this key is (file and schema), or why there is none."""
    on, done = sql_wanted(disk), SQL.get(key) or {}
    why = None if on else ("Inside Snowflake there is no local disk, so no SQL copy." if access.INSIDE else
                           "DUCKDB=0: no SQL copy." if DUCKDB == "0" else
                           "Demo data: no SQL copy (DUCKDB=1 writes one)." if not disk else
                           "CACHE_HOURS=0: nothing on disk, so no SQL copy (DUCKDB=1 writes one).")
    return dict(on=on, path=str(sql_file().resolve()), schema=schema(key), note=done.get("note") or why,
                written_at=stamp(done["at"])[:16] if done.get("at") else None)
