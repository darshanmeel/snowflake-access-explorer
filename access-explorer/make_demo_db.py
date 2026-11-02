"""Demo: write the fake data into DuckDB tables shaped like the Snowflake TBL_ACCESS_ tables.
    python make_demo_db.py            # -> demo.duckdb
    $env:DUCKDB="demo.duckdb"; streamlit run app.py
The app then reads it with the same SQL as the real snapshot (last OK run, rows of that RUN_ID)."""
import json

import duckdb

import access as a

COLS = {
    "GRANT": "GRANTEE_ROLE, PRIVILEGE, GRANTED_ON, OBJECT_NAME, IS_FUTURE",
    "USER_ROLE": "USER_NAME, ROLE_NAME",
    "USER": "USER_NAME, TYPE, DISABLED, DEFAULT_ROLE, DEFAULT_SECONDARY_ROLES, DEFAULT_WAREHOUSE, DEFAULT_NAMESPACE, LAST_SUCCESS_LOGIN",
    "USAGE": "USER_NAME, KIND, NAME, QUERIES, LAST_USED",
    "TAG": "OBJECT_NAME, DOMAIN, COLUMN_NAME, TAG_NAME, TAG_VALUE, APPLY_METHOD",
    "POLICY": "POLICY_NAME, POLICY_KIND, OBJECT_NAME, COLUMN_NAME, ARG_COLUMNS, TAG_NAME, POLICY_BODY",
}


def write(db, d):
    """The fake data d into the duckdb connection db: run log (2 OK runs, 1 failed) + rows of run-2."""
    db.execute("CREATE OR REPLACE TABLE TBL_ACCESS_RUN (RUN_ID VARCHAR, STARTED_AT TIMESTAMP, FINISHED_AT TIMESTAMP, "
               "STATUS VARCHAR, SOURCES VARCHAR, ROW_COUNTS VARCHAR, NOTES VARCHAR)")
    src = json.dumps({"grants": "ACCOUNT_USAGE", "user_roles": "ACCOUNT_USAGE", "future_grants": "SHOW",
                      "users": "ACCOUNT_USAGE", "usage": "ACCOUNT_USAGE", "tags": "ACCOUNT_USAGE",
                      "policies": "ACCOUNT_USAGE"})
    counts = json.dumps({k: len(d[t]) for k, t in [("grants", "GRANT"), ("user_roles", "USER_ROLE"), ("users", "USER"),
                                                   ("usage", "USAGE"), ("tags", "TAG"), ("policies", "POLICY")]})
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
        db.executemany(f"INSERT INTO TBL_ACCESS_{t} VALUES ({', '.join(['?'] * (len(names) + 1))})",
                       [["run-2"] + [row.get(c) for c in names] for row in d[t]])


if __name__ == "__main__":
    con = duckdb.connect("demo.duckdb")
    data = a.fake()
    write(con, data)
    con.close()
    print({t: len(data[t]) for t in COLS})
