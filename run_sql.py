"""Run the "-- name:" statements of a sql/ file as the developer role, with &NAME filled in from settings.local.sql
(real values, git-ignored; falls back to the settings.sql template).

    python run_sql.py sql/1_setup.sql            # work: each statement in order, "(may fail)" ones skipped on error
    python run_sql.py sql/1_setup_verify.sql     # checks: OK / MISSING / WRONG / SKIPPED per check, then VERIFIED or not

Connection: sf.py env vars (SNOWFLAKE_USER, ...), from the environment or .env. SnowSQL runs the same files with !source.
"""
import pathlib
import re
import sys

import access  # noqa: F401  (loads .env)
from sf import connect

HERE = pathlib.Path(__file__).parent
SETTINGS = HERE / "settings.local.sql" if (HERE / "settings.local.sql").exists() else HERE / "settings.sql"
NAMES = dict(re.findall(r"^!define (\w+)=(.*?)\s*$", SETTINGS.read_text(encoding="utf-8"), re.M))
NAMES["HERE"] = HERE.resolve().as_posix()  # PUT needs an absolute path to access.py


def fill(sql):
    return re.sub(r"&(\w+)", lambda m: NAMES[m.group(1)], sql)


def statements(text):
    """(name, flags, sql): each starts at a '-- name: X' line and ends at its last ';'."""
    parts = re.split(r"^-- name: (\w+)(.*)$", text, flags=re.M)
    return [(n, f, b[:b.rfind(";")].strip()) for n, f, b in zip(parts[1::3], parts[2::3], parts[3::3])]


def main(path):
    conn = connect()
    cur = conn.cursor()
    for s in ("USE ROLE &DEV_ROLE", "USE SECONDARY ROLES NONE", "USE WAREHOUSE &WH", "USE DATABASE &DB"):
        cur.execute(fill(s))
    check, bad = path.endswith("_verify.sql"), []
    for name, flags, sql in statements((HERE / path).read_text(encoding="utf-8")):
        may_fail, expect = "may fail" in flags, re.search(r"expect (\d+)", flags)
        try:
            cur.execute(fill(sql))
            rows = cur.fetchall() if cur.description else []
        except Exception as e:
            if not (may_fail or check):
                raise
            print(f"{'SKIPPED' if may_fail else 'MISSING'}: {name}: {str(e).strip().splitlines()[-1]}")
            bad += [] if may_fail else [name]
            continue
        status = f"WRONG (expected {expect.group(1)} rows)" if expect and len(rows) != int(expect.group(1)) else "OK"
        print(f"{status}: {name} ({len(rows)} rows)")
        for r in rows[:20]:
            print("   ", tuple(r))
        bad += [] if status == "OK" else [name]
    if check:
        print("\nVERIFIED" if not bad else f"\nNOT VERIFIED: {bad}")
    conn.close()


if __name__ == "__main__":
    main(sys.argv[1])
