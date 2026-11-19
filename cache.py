"""Where the data comes from and how long it is kept. No Streamlit or FastAPI import.

config(): FAKE / SOURCE / ACCESS_SNAPSHOT settings -> (mode, source, where).
get(): the data in memory and locally a file in .cache/ (CACHE_DIR), kept until a refresh or rebuild reads again (CACHE_HOURS=0: memory only).
When a new read replaces a local file of another run, that file is kept as <name>.prev.pkl (What changed compares them).
Streamlit in Snowflake (access.INSIDE) has no local disk: memory only there.
sql_copy(): each read from Snowflake also goes to .cache/access.duckdb, the TBL_ACCESS_ tables to query with SQL
(always, DUCKDB=1: also fake data); the app itself keeps reading the .pkl files.
"""
import contextvars
import datetime as dt
import decimal
import functools
import hashlib
import importlib
import os
import pathlib
import json
import pickle
import re
import shutil
import threading
import time

import access  # loads .env; access.INSIDE: no local disk

# CACHE_DIR: another folder (absolute, or relative to the repo), e.g. a copied .cache: its files are used, missing ones written there
DIR = pathlib.Path(__file__).parent / os.environ.get("CACHE_DIR", ".cache")
HOURS = float(os.environ.get("CACHE_HOURS", "24"))
TTL = 24 * 3600  # the My access session cookie
MEM = {}
OLD = {}  # key -> what drop() took out of memory: last() still finds it where there is no local file (inside Snowflake)
LOCK = threading.Lock()  # guards LOCKS
LOCKS = {}  # key -> its lock: one read per key at a time (Streamlit runs a session per thread), other keys never wait
SQL_LOCK = threading.Lock()  # every key writes the one .cache/access.duckdb


def lock(key):
    with LOCK:
        return LOCKS.setdefault(key, threading.RLock())


def config(env=os.environ):
    """(mode, source, where): mode fake|snowflake; source fake|direct|objects; where = DB.SCHEMA of the objects, else ''."""
    if env.get("FAKE") in ("1", "twin"):
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
    """Cache name of one account + source (fake|direct|objects) + snapshot location + login (+ ACTIVITY=0), or of one
    user's "mine": everything that changes what a read returns, so another ACCESS_SNAPSHOT, user or role never gets
    this copy."""
    e = os.environ
    return "_".join(filter(None, (e.get("SNOWFLAKE_ACCOUNT", "local"), what, where, user or e.get("SNOWFLAKE_USER"),
                                  e.get("SNOWFLAKE_ROLE"), "noactivity" * (not access.ACTIVITY_ON),
                                  e.get("FAKE") == "twin" and "twin" + e.get("FAKE_SCALE", "1"))))


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
            if d is not None and run_of(d)[0] is not None and run_of(d) != run_of(new):  # never an empty no-run read
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


def last(key):
    """The newest data kept for key (memory, the local file, the one drop() set aside, the previous one), else None:
    Direct mode then reads only the activity days it lacks."""
    m = MEM.get(key) or OLD.get(key)
    if m:
        return m[0]
    f = file(key)
    for x in (f, f.with_suffix(".old.pkl"), f.with_suffix(".prev.pkl")):
        d = load(x) if local() and x.is_file() else None
        if d is not None:
            return d
    return None


def get(key, fn, disk=True):
    """(data, fetched_at): from memory, else the local file, else fn() (stored in both)."""
    m = MEM.get(key)  # before the lock: a page whose data is in memory never waits for another key's read
    if m:
        return m
    with lock(key):
        m = MEM.get(key)  # another thread may have read it while this one waited
        if m:
            return m
        f = file(key)
        disk = disk and local()
        m = None
        if disk and f.is_file():
            d = load(f)
            m = (d, f.stat().st_mtime) if d is not None else None
        if not m:
            return store(key, fn(), disk)
        MEM[key] = m
        OLD.pop(key, None)
        return m


def store(key, d, disk=True):
    """(d, now) kept as key's data: memory, the local file (the one it replaces becomes the previous), the SQL copy."""
    m, f = (d, time.time()), file(key)
    kept = run_of(d)[0] is not None  # no OK run read: memory only, never a snapshot on disk or in SQL
    disk = disk and local() and kept
    if kept and sql_wanted(disk):  # in a thread: the app does not read it, and on millions of rows it takes minutes
        run = contextvars.copy_context().run  # its lines go to the load log of the read that made d
        COPYING[key] = threading.Thread(target=run, args=(sql_copy, key, d, m[1]), daemon=True)
        COPYING[key].start()
    if disk:
        DIR.mkdir(parents=True, exist_ok=True)
        keep_prev(f, d)
        tmp = f.with_suffix(".tmp")
        tmp.write_bytes(pickle.dumps(d))
        tmp.replace(f)
    MEM[key] = m
    OLD.pop(key, None)
    return m


def swap(key, new, d):
    """d, read with its parts under key new (a refresh), becomes key's data: its parts replace key's."""
    with lock(key):
        if local():
            old = parts_dir(key).with_name(parts_dir(key).name + ".gone")
            shutil.rmtree(old, ignore_errors=True)
            if parts_dir(key).is_dir():
                parts_dir(key).rename(old)  # moved away whole first: a file held open on Windows fails here, nothing lost
            if parts_dir(new).is_dir():
                parts_dir(new).rename(parts_dir(key))
            shutil.rmtree(old, ignore_errors=True)
        return store(key, d)


def ready(key, disk=True):
    """Whether get(key) answers from memory or the local file, without reading the source."""
    m = MEM.get(key)
    if m:
        return True
    f = file(key)
    return disk and local() and f.is_file()


def drop(key):
    """Read again next time: out of memory, and the local file set aside (the previous snapshot once a new one is read).
    Under the key's lock: a read still running would otherwise store its older data after the drop."""
    with lock(key):
        m = MEM.pop(key, None)
        if m:
            OLD[key] = m
        f = file(key)
        if f.is_file() and HOURS > 0:
            f.replace(f.with_suffix(".old.pkl"))
        f.unlink(missing_ok=True)

# ---------- SQL copy (DuckDB) ----------

DUCKDB = os.environ.get("DUCKDB", "")  # 1: also of fake data; the SQL copy follows each read from Snowflake
COLUMNS = access.COLUMNS  # the TBL_ACCESS_ tables of sql/1_setup.sql (test_duckdb checks them against that file)
SQL = {}  # cache key -> what the last copy in this process did: at and run_id, or a note
COPYING = {}  # cache key -> the thread writing its SQL copy


def sql_file():
    return DIR / "access.duckdb"


def schema(key):
    """The DuckDB schema of one cache key (account + source + location + login): one row set each."""
    return re.sub(r"\W", "_", key).lower()


def sql_wanted(disk):
    """Whether a read gets a SQL copy: never inside Snowflake; fake data (disk False) only with DUCKDB=1; a read
    from Snowflake whenever a local copy may be kept (CACHE_HOURS > 0)."""
    if access.INSIDE:
        return False
    return DUCKDB == "1" or (disk and local())


def stamp(at):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(at))


def text(v):
    """A value as the text its column is TRY_CAST from: dicts/lists (HOURS) as compact JSON, booleans as true/false."""
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, (bool, int, float, dict, list)):
        return json.dumps(v, default=str, separators=(",", ":"))
    return str(v)


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
    try:
        import pyarrow as pa
    except ImportError:
        pa = None
    run = d.get("run") or {}
    rid = str(run.get("RUN_ID") or "")
    if rid in ("", "direct", "live", "fake"):  # direct reads and My access: a run id per read
        rid = f"{rid or 'read'}-{time.strftime('%Y%m%d%H%M%S', time.localtime(at))}"
    fin = run.get("FINISHED_AT")
    rows = {t: d.get(t) or [] for t in COLUMNS if t != "RUN"}
    rows["GRANT"] = rows["GRANT"] + (d.get("UNOWNED") or [])  # objects no role owns: tidy() keeps them apart
    rows["RUN"] = [dict(STARTED_AT=None, FINISHED_AT=stamp(at) if fin in (None, "now") else fin, STATUS="OK",
                        SOURCES=json.dumps(run.get("SOURCES") or {}, default=str),
                        ROW_COUNTS=json.dumps({t.lower(): len(v) for t, v in rows.items()}),
                        NOTES=json.dumps(run.get("NOTES") or {}, default=str))]
    s = schema(key)
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        with SQL_LOCK, access.step(f"DuckDB copy ({sql_file().name})"):  # one access.duckdb for every key: a second writer would find the file locked
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
                    if rows[t]:
                        access.say(f"DuckDB copy: TBL_ACCESS_{t}, {len(rows[t]):,} rows")
                        vals = [[rid] * len(rows[t]) if c == "RUN_ID" else  # text() only for what is not text yet
                                [v if v is None or type(v) is str else text(v) for v in (r.get(c) for r in rows[t])]
                                for c, _ in pairs]
                        if pa:  # one scan of an Arrow table: about 5x faster than list parameters on a million rows
                            con.register("src", pa.table({c: pa.array(v, pa.string()) for (c, _), v in zip(pairs, vals)}))
                            con.execute(f"INSERT INTO {name} SELECT "
                                        + ", ".join(f'TRY_CAST("{c}" AS {ty})' for c, ty in pairs) + " FROM src")
                            con.unregister("src")
                        else:  # one bulk insert, a text list per column unnested side by side: one per row takes minutes
                            con.execute(f"INSERT INTO {name} SELECT "
                                        + ", ".join(f"TRY_CAST(UNNEST(?::VARCHAR[]) AS {ty})" for _, ty in pairs), vals)
                con.execute("DELETE FROM COPIES WHERE SCHEMA_NAME = ?", [s])
                con.execute("INSERT INTO COPIES VALUES (?, ?, ?, ?, ?)",
                            [s, key, rid, stamp(at), had[0] if turn else (had[1] if had else None)])
                con.execute("COMMIT")
            finally:
                con.close()
        SQL[key] = dict(run_id=rid, at=at)
    except Exception as e:
        SQL[key] = dict(note=f"The SQL copy was not written: {access.line(e)}")


def sql_info(key, disk=True):
    """For the UI: where the SQL copy of this key is (file and schema), or why there is none."""
    on, done = sql_wanted(disk), SQL.get(key) or {}
    why = None if on else ("Inside Snowflake there is no local disk, so no SQL copy." if access.INSIDE else
                           "Demo data: no SQL copy (DUCKDB=1 writes one)." if not disk else
                           "CACHE_HOURS=0: nothing on disk, so no SQL copy (DUCKDB=1 writes one).")
    busy = COPYING.get(key) is not None and COPYING[key].is_alive()
    return dict(on=on, path=str(sql_file().resolve()), schema=schema(key),
                note="Being written now: it is ready in a minute or two." if busy else done.get("note") or why,
                written_at=stamp(done["at"])[:16] if done.get("at") else None)

# ---------- parts (stage 1: every Snowflake read kept on disk, so a load resumes) ----------
# .cache/reads/<key>/<PART>.parquet, one per read: a heavy ACCOUNT_USAGE read, a SHOW wave, a snapshot table, a small
# statement; parts.json lists the finished ones. A part is never read again on its own (no CACHE_HOURS): only a manual
# Rebuild / Read Snowflake again (clear_parts) or run.py --export --fresh. A missing part, or one that timed out, is
# read on the next load. Stage 2 (build, rules, .pkl, access.duckdb) then needs no Snowflake.


def parts_dir(key):
    return DIR / "reads" / re.sub(r"[^\w.-]", "_", key)


def parts_of(key):
    """parts.json of key: part name -> rows, read_at, status, ..."""
    try:
        return json.loads((parts_dir(key) / "parts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def clear_parts(key):
    """Every part read again next time. Under the key's lock: a read still running finishes first."""
    with lock(key):
        shutil.rmtree(parts_dir(key), ignore_errors=True)


def parts_read_at(key):
    """When the oldest part was read (epoch seconds), else None: the time the data is from."""
    return min((p["read_at"] for p in parts_of(key).values()), default=None) if local() else None


def old(key, base=None):
    """The earlier read (of base, else key) a Direct load starts from (the activity days and object use weeks it need
    not read again), kept with the parts: a resumed load asks for the same days, so each part's SQL, and so its name,
    stays the same."""
    d = last(base or key) or {}
    keep = {k: d.get(k) for k in ("ACTIVITY", "OBJECT_USE")}
    if not local():
        return keep
    f = parts_dir(key) / "old.pkl"
    got = load(f) if f.is_file() else None
    if isinstance(got, dict):
        return got
    f.parent.mkdir(parents=True, exist_ok=True)
    f.with_suffix(".tmp").write_bytes(pickle.dumps(keep))
    f.with_suffix(".tmp").replace(f)
    return keep


@functools.cache
def engine():
    """What writes and reads parquet: pyarrow, else duckdb, else None (no parts: a load reads everything, as before)."""
    for m, mod in (("pyarrow", "pyarrow.parquet"), ("duckdb", "duckdb")):  # pyarrow may import without its parquet DLL
        try:
            importlib.import_module(mod)
            return m
        except ImportError:
            pass
    return None


def duck_type(vals):
    """The DuckDB type of one column's values; a mix of Python types raises (that part is not kept)."""
    kinds = {type(v) for v in vals if v is not None}
    if len(kinds) > 1:
        raise TypeError(f"mixed types {sorted(k.__name__ for k in kinds)}")
    k = kinds.pop() if kinds else str
    if k is decimal.Decimal:
        return f"DECIMAL(38, {max(-v.as_tuple().exponent for v in vals if v is not None)})"
    if issubclass(k, dt.datetime):
        return "TIMESTAMPTZ" if any(v.tzinfo for v in vals if v is not None) else "TIMESTAMP"
    if k is int and all(-2**63 <= v < 2**63 for v in vals if v is not None):
        return "BIGINT"  # Parquet has no HUGEINT: DuckDB would write it as DOUBLE, read back as floats
    types = [(bool, "BOOLEAN"), (int, "HUGEINT"), (float, "DOUBLE"), (str, "VARCHAR"), (bytes, "BLOB"), (dt.date, "DATE")]
    return next(t for py, t in types if issubclass(k, py))


def write_part(f, rows):
    tmp = f.with_name(f.name + ".tmp")  # renamed when complete: a half-written file never counts
    if engine() == "pyarrow":
        import pyarrow as pa
        import pyarrow.parquet as pq
        cols = list(dict.fromkeys(k for r in rows for k in r))  # a wave's statements may answer other columns
        pq.write_table(pa.table({c: [r.get(c) for r in rows] for c in cols}), tmp)
    else:  # DuckDB: one typed list per column, as sql_copy() inserts
        import duckdb
        cols = list(dict.fromkeys(k for r in rows for k in r))
        vals = [[json.dumps(v) if isinstance(v, (dict, list)) else v for v in (r.get(c) for r in rows)] for c in cols]
        types = [duck_type(v) for v in vals]  # a dict or list as its JSON text, as Snowflake answers a VARIANT
        con = duckdb.connect()
        try:
            con.execute("CREATE TABLE t (" + ", ".join(access.ident(c) + " " + t for c, t in zip(cols, types)) + ")")
            con.execute("INSERT INTO t SELECT " + ", ".join(f"UNNEST(?::{t}[])" for t in types), vals)
            con.execute("COPY t TO '" + str(tmp).replace("'", "''") + "' (FORMAT parquet)")
        finally:
            con.close()
    tmp.replace(f)


def read_part(f):
    if engine() == "pyarrow":
        import pyarrow.parquet as pq
        return pq.read_table(f).to_pylist()
    import duckdb
    con = duckdb.connect()
    try:
        cur = con.execute("SELECT * FROM read_parquet(?)", [str(f)])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()


def part_name(label, sqls):
    """A readable name plus a hash of the statements: other statements (another run, other days) are another part."""
    h = hashlib.sha1("\n".join(sqls).encode()).hexdigest()[:10]
    return re.sub(r"[^\w.-]+", "_", label).strip("_")[:60] + "-" + h


def parted(query, key, offline=False):
    """query(sql) that keeps every read as a part of key and answers from the parts already kept; access.each() hands
    a wave to its keep(). offline (run.py --build): never Snowflake, a part that is not there fails as not exported.
    A USE statement answered from its part runs again before the first statement that goes to Snowflake: the reads
    after it need the session setting."""
    d, mlock, ulock, said, uses, used = parts_dir(key), threading.Lock(), threading.Lock(), [], [], set()
    man, eng = parts_of(key), engine()

    def take(name, timed_out=False):  # the kept results of a part (rows, or an exception, per statement), else None
        used.add(name)
        m = man.get(name)  # timed_out: a part with timed-out statements too (a wave reads only those again)
        if not m or (m["status"] == "failed" and not offline and not timed_out):
            return None
        try:
            got = read_part(d / m["file"]) if m["file"] else []
        except Exception:  # a file gone or damaged: read again
            return None
        if m["statements"] == 1 and not m["errors"] and not (got and "__i" in got[0]):
            return [got]  # one statement's rows as written: no second copy (millions of rows)
        by = {}
        for r in got:
            by.setdefault(r.pop("__i"), []).append(r)
        out = []
        for i in range(m["statements"]):
            e, cols = m["errors"].get(str(i)), m["colsets"][m["of"][i]]
            out.append((TimeoutError if e[0] == "timeout" else RuntimeError)(e[1]) if e else
                       [{c: r.get(c) for c in cols} for r in by.get(i, [])])
        return out

    def save():  # parts.json, under mlock
        tmp = d / "parts.tmp"
        tmp.write_text(json.dumps(man), encoding="utf-8")
        tmp.replace(d / "parts.json")

    def put(name, results):
        used.add(name)
        if offline or any(isinstance(r, Exception) and access.lost(r) for r in results):
            return  # a lost session is no answer: read again next time
        if eng is None:
            if not said:
                said.append(1)
                access.say("Neither pyarrow nor duckdb is installed: no parts kept, the next load reads everything again")
            return
        sets, of, rows, errors = [], [], [], {}
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                errors[str(i)] = ["timeout" if isinstance(r, TimeoutError) or access.timed_out(r) else "error", str(r)]
                r = []
            cols = list(r[0]) if r else []
            if cols not in sets:
                sets.append(cols)
            of.append(sets.index(cols))
            if len(results) == 1:
                rows = r  # one statement: no index column, no copy
            else:
                rows += [x | {"__i": i} for x in r]
        try:
            d.mkdir(parents=True, exist_ok=True)
            if rows:
                write_part(d / f"{name}.parquet", rows)
        except Exception as e:  # e.g. a column of mixed types: kept in memory only, read again next time
            access.say(f"{name}: not kept as a part ({access.line(e)})")
            return
        with mlock:
            man[name] = dict(file=f"{name}.parquet" if rows else None, rows=len(rows), read_at=time.time(),
                             statements=len(results), colsets=sets, of=of, errors=errors,
                             status="failed" if any(e[0] == "timeout" for e in errors.values()) else "ok")
            save()

    def prune():  # after a whole load: the parts it did not ask for (an older run's tables, older activity days) go
        with mlock:
            gone = [n for n in man if n not in used]
            for n in gone:
                if man[n]["file"]:
                    (d / man[n]["file"]).unlink(missing_ok=True)
                del man[n]
            if gone and d.is_dir():
                save()

    def ask(sql):
        if offline:
            raise RuntimeError(f"{access.step_name(sql)}: not exported yet (python run.py --export reads it)")
        with ulock:
            while uses:
                try:
                    query(uses.pop(0))
                except Exception:  # its answer is the one kept
                    pass
        return query(sql)

    def saved(name):  # ask(sql), kept as part name the moment it answers (or fails)
        def one(sql):
            try:
                r = ask(sql)
            except Exception as e:
                put(name(sql), [e])
                raise
            put(name(sql), [r])
            return r
        return one

    def q(sql):
        name = part_name(access.step_name(sql), [sql])
        got = take(name)
        if got is None:
            got = [saved(lambda _: name)(sql)]
        elif sql.lstrip()[:4].upper() == "USE ":
            uses.append(sql)
        if isinstance(got[0], Exception):
            raise got[0]
        return got[0]

    def keep(sqls, what, run):
        if isinstance(what, list):  # heavy reads, one name each: a part each, kept the moment it is read
            names = dict(zip(sqls, (part_name(w, [s]) for w, s in zip(what, sqls))))
            got = [take(names[s]) for s in sqls]
            for w, g in zip(what, got):
                if g is not None:
                    access.say(f"{w}: from the part kept, " + (f"failed: {access.line(g[0])}" if isinstance(g[0], Exception)
                                                               else f"{len(g[0]):,} rows"))
            todo = [i for i, g in enumerate(got) if g is None]
            if todo:
                for i, r in zip(todo, run(saved(names.get), [sqls[i] for i in todo], [what[i] for i in todo])):
                    got[i] = [r]
            return [g[0] for g in got]
        name = part_name(what or (access.step_name(sqls[0]) if sqls else "none"), sqls)
        got = take(name, True)
        redo = [] if got is None or offline else [i for i, r in enumerate(got) if isinstance(r, TimeoutError)]
        if got is not None and not redo:
            if what:
                access.say(f"{what}: from the part kept ({len(sqls):,} statements)")
            return got
        if redo:  # the statements that timed out last time, not the whole wave
            access.say(f"{what or name}: {len(sqls) - len(redo):,} statements from the part kept, {len(redo):,} read again")
            for i, r in zip(redo, run(ask, [sqls[i] for i in redo], what)):
                got[i] = r
        else:
            got = run(ask, sqls, what)
        put(name, got)
        return got
    q.keep = keep
    # what may change between loads (the last OK run): always asked, its answer kept for an offline build
    q.fresh = q if offline else (lambda sql: saved(lambda _: part_name(access.step_name(sql), [sql]))(sql))
    q.prune = prune
    return q
