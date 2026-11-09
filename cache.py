"""Where the data comes from and how long it is kept. No Streamlit or FastAPI import.

config(): FAKE / SOURCE / ACCESS_SNAPSHOT settings -> (mode, source, where).
get(): the data once a day is enough: memory for 24 h, and locally a file in .cache/ for CACHE_HOURS (0 = memory only).
When a new read replaces a local file of another run, that file is kept as <name>.prev.pkl (What changed compares them).
Streamlit in Snowflake (access.INSIDE) has no local disk: memory only there.
"""
import os
import pathlib
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
