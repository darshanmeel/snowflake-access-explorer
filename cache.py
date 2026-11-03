"""Where the data comes from and how long it is kept. No Streamlit or FastAPI import.

config(): FAKE / SOURCE / ACCESS_SNAPSHOT settings -> (mode, source, where).
get(): the data once a day is enough: memory for 24 h, and locally a file in .cache/ for CACHE_HOURS (0 = memory only).
A Streamlit-in-Snowflake app has no SNOWFLAKE_ACCOUNT variable and no local disk: memory only there.
"""
import os
import pathlib
import pickle
import re
import threading
import time

import access  # noqa: F401  (loads .env)

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


def name(what, user=None):
    """Cache name of one account + source (fake|direct|objects), or of one user's "mine"."""
    return "_".join(filter(None, (os.environ.get("SNOWFLAKE_ACCOUNT", "local"), what, user)))


def file(key):
    return DIR / (re.sub(r"[^\w.-]", "_", key) + ".pkl")


def get(key, fn, disk=True):
    """(data, fetched_at): from memory, else the local file, else fn() (stored in both)."""
    with LOCK:
        m = MEM.get(key)
        if m and time.time() - m[1] < TTL:
            return m
        f = file(key)
        disk = disk and HOURS > 0 and "SNOWFLAKE_ACCOUNT" in os.environ
        m = None
        if disk and f.is_file() and time.time() - f.stat().st_mtime < HOURS * 3600:
            try:
                m = pickle.loads(f.read_bytes()), f.stat().st_mtime
            except Exception:  # unreadable or from older code: read again
                m = None
        if not m:
            m = fn(), time.time()
            if disk:
                DIR.mkdir(exist_ok=True)
                tmp = f.with_suffix(".tmp")
                tmp.write_bytes(pickle.dumps(m[0]))
                tmp.replace(f)
        MEM[key] = m
        return m


def drop(key):
    MEM.pop(key, None)
    file(key).unlink(missing_ok=True)
