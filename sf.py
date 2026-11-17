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
        host=os.environ.get("SNOWFLAKE_HOST"),  # PrivateLink: the private host, when the public one is blocked
        user=os.environ.get("SNOWFLAKE_USER"),
        role=os.environ.get("SNOWFLAKE_ROLE"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE"),
        database=os.environ.get("SNOWFLAKE_DATABASE"),
        schema=os.environ.get("SNOWFLAKE_SCHEMA"),
        session_parameters={"QUERY_TAG": access.QUERY_TAG},  # Activity leaves the app's own queries out
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
    """(column names, rows) of one statement; every read of the app goes through here. STATEMENT_TIMEOUT as a statement
    parameter, not ALTER SESSION: the same on a local login and on the app's session inside Snowflake (to verify there).
    A timeout says which step and how to give it longer."""
    cur = conn.cursor()
    p = limit(sql)
    try:
        cur.execute(sql, _statement_params=p) if p else cur.execute(sql)
    except Exception as e:
        if access.timed_out(e):
            raise TimeoutError(f"{access.step_name(sql)}: {access.timeout_hint(e, bool(p))}") from e
        raise
    return [c[0] for c in cur.description or []], cur.fetchall()


def limit(sql):
    """STATEMENT_TIMEOUT as statement parameters, none for a CALL: SP_ACCESS_SNAPSHOT limits each of its own statements
    (settings.local.sql), and a cut CALL would leave its run RUNNING, so the next CALLs answer SKIPPED for an hour."""
    n = access.STATEMENT_TIMEOUT
    return {"STATEMENT_TIMEOUT_IN_SECONDS": n} if n and not sql.lstrip().upper().startswith("CALL") else {}


def run(sql, conn=None):
    own = conn is None
    conn = conn or connect()
    try:
        return rows(conn, sql)
    finally:
        if own and owned():
            conn.close()


if __name__ == "__main__":
    sql = open(sys.argv[2], encoding="utf-8").read() if sys.argv[1] == "-f" else sys.argv[1]
    cols, got = run(sql)
    print("\t".join(cols))
    for r in got:
        print("\t".join(str(v) for v in r))
