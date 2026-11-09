"""Run plain SQL on Snowflake from a local machine.

    python sf.py "select current_user(), current_role()"
    python sf.py -f query.sql

Settings: env vars or .env. Login: key pair when SNOWFLAKE_PRIVATE_KEY_FILE is set, else SSO in the browser.
No other method (no password). Inside Snowflake (SiS, access.INSIDE): the app's own session, never closed.

In Python:
    from sf import connect, run
    rows = run("select 1")
"""
import os
import sys

import access  # loads .env; access.INSIDE: running as Streamlit in Snowflake


def connect():
    if access.INSIDE:  # the app's own session (owner's rights); owned() says not to close it
        from snowflake.snowpark.context import get_active_session
        return get_active_session().connection
    if not os.environ.get("SNOWFLAKE_ACCOUNT"):
        raise RuntimeError("SNOWFLAKE_ACCOUNT is not set: copy .env.example to .env and fill it in "
                           "(README > Settings), or run python run.py --fake")
    import snowflake.connector
    args = dict(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ.get("SNOWFLAKE_USER"),
        role=os.environ.get("SNOWFLAKE_ROLE"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE"),
        database=os.environ.get("SNOWFLAKE_DATABASE"),
        schema=os.environ.get("SNOWFLAKE_SCHEMA"),
    )
    key = os.environ.get("SNOWFLAKE_PRIVATE_KEY_FILE")
    if key:  # key pair (service accounts)
        args.update(authenticator="SNOWFLAKE_JWT", private_key_file=key,
                    private_key_file_pwd=os.environ.get("SNOWFLAKE_PRIVATE_KEY_PWD"))
    else:  # SSO in the browser (human users); the token cache saves a login tab per connection (needs ALLOW_ID_TOKEN)
        args.update(authenticator="externalbrowser", client_store_temporary_credential=True)
    return snowflake.connector.connect(**{k: v for k, v in args.items() if v})


def owned():
    """Whether connect() made a connection of our own (to close), not the app's session inside Snowflake."""
    return not access.INSIDE


def rows(conn, sql):
    """(column names, rows) of one statement; every read of the app goes through here."""
    cur = conn.cursor()
    cur.execute(sql)
    return [c[0] for c in cur.description or []], cur.fetchall()


def run(sql, conn=None):
    own = conn is None
    conn = conn or connect()
    try:
        return rows(conn, sql)
    finally:
        if own and owned():
            conn.close()


if __name__ == "__main__":
    sql = open(sys.argv[2]).read() if sys.argv[1] == "-f" else sys.argv[1]
    cols, got = run(sql)
    print("\t".join(cols))
    for r in got:
        print("\t".join(str(v) for v in r))
