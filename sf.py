"""Run plain SQL on Snowflake from a local machine.

    python sf.py "select current_user(), current_role()"
    python sf.py -f query.sql

In Python:
    from sf import connect, run
    rows = run("select 1")
"""
import os
import sys

import snowflake.connector


def connect():
    args = dict(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        role=os.environ.get("SNOWFLAKE_ROLE"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE"),
        database=os.environ.get("SNOWFLAKE_DATABASE"),
        schema=os.environ.get("SNOWFLAKE_SCHEMA"),
    )
    key = os.environ.get("SNOWFLAKE_PRIVATE_KEY_FILE")
    if key:  # key pair (service accounts)
        args.update(authenticator="SNOWFLAKE_JWT", private_key_file=key,
                    private_key_file_pwd=os.environ.get("SNOWFLAKE_PRIVATE_KEY_PWD"))
    else:  # SSO in the browser (human users)
        args["authenticator"] = "externalbrowser"
    return snowflake.connector.connect(**{k: v for k, v in args.items() if v})


def run(sql, conn=None):
    own = conn is None
    conn = conn or connect()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [c[0] for c in cur.description or []]
        return cols, cur.fetchall()
    finally:
        if own:
            conn.close()


if __name__ == "__main__":
    sql = open(sys.argv[2]).read() if sys.argv[1] == "-f" else sys.argv[1]
    cols, rows = run(sql)
    print("\t".join(cols))
    for r in rows:
        print("\t".join(str(v) for v in r))
