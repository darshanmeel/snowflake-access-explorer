-- 1 · setup (developer role): the 7 snapshot tables, the snapshot procedure, read access for the app role. Safe to run again.
-- run_sql.py runs each "-- name:" statement in order; "(may fail)" = skipped on error.
-- Names marked with & come from settings.local.sql. Real set-up: schema, roles and grants via infrastructure as code.
-- SnowSQL: !source sql/1_setup.sql (from the access-explorer folder)
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
);

-- name: TABLE_USER_ROLE
CREATE TABLE IF NOT EXISTS &DB.&SCHEMA.TBL_ACCESS_USER_ROLE (   -- role -> user
    RUN_ID VARCHAR(36),
    USER_NAME VARCHAR(255),
    ROLE_NAME VARCHAR(255),
    GRANTED_BY VARCHAR(255)
);

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
);

-- name: TABLE_USAGE
CREATE TABLE IF NOT EXISTS &DB.&SCHEMA.TBL_ACCESS_USAGE (   -- roles and warehouses used, per user
    RUN_ID VARCHAR(36),
    USER_NAME VARCHAR(255),
    KIND VARCHAR(20),                -- ROLE, SECONDARY ROLE, WAREHOUSE
    NAME VARCHAR(255),
    QUERIES NUMBER,
    LAST_USED TIMESTAMP_LTZ
);

-- name: TABLE_TAG
CREATE TABLE IF NOT EXISTS &DB.&SCHEMA.TBL_ACCESS_TAG (   -- tags on databases, schemas, tables/views, columns
    RUN_ID VARCHAR(36),
    OBJECT_NAME VARCHAR(2000),       -- DATABASE: DB · SCHEMA: DB.SCHEMA · TABLE / COLUMN: DB.SCHEMA.OBJECT
    DOMAIN VARCHAR(50),              -- DATABASE, SCHEMA, TABLE, COLUMN
    COLUMN_NAME VARCHAR(255),
    TAG_NAME VARCHAR(500),           -- TAG_DATABASE.TAG_SCHEMA.TAG_NAME
    TAG_VALUE VARCHAR(500),
    APPLY_METHOD VARCHAR(50)         -- MANUAL, CLASSIFIED, PROPAGATED, INHERITED, ...
);

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
);

-- name: PROCEDURE
CREATE OR REPLACE PROCEDURE &DB.&SCHEMA.SP_ACCESS_SNAPSHOT(P_SOURCE VARCHAR DEFAULT 'AUTO')
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
EXECUTE AS OWNER
COMMENT = 'Access explorer: copies grants, users, role usage, tags and policies into the TBL_ACCESS_ tables'
AS
$$
# P_SOURCE: AUTO = ACCOUNT_USAGE where the owner can read it, else the SHOW fallback; ACCOUNT_USAGE or SHOW = force one.
# Rows carry RUN_ID; the app reads the last OK run, so a running or failed CALL never shows half a snapshot.
import json
import uuid

AU = "SNOWFLAKE.ACCOUNT_USAGE"
RUN = "&DB.&SCHEMA.TBL_ACCESS_RUN"
GRANT = "&DB.&SCHEMA.TBL_ACCESS_GRANT"
USER_ROLE = "&DB.&SCHEMA.TBL_ACCESS_USER_ROLE"
USER = "&DB.&SCHEMA.TBL_ACCESS_USER"
USAGE = "&DB.&SCHEMA.TBL_ACCESS_USAGE"
TAG = "&DB.&SCHEMA.TBL_ACCESS_TAG"
POLICY = "&DB.&SCHEMA.TBL_ACCESS_POLICY"
DATA = [GRANT, USER_ROLE, USER, USAGE, TAG, POLICY]
GRANT_COLS = ["RUN_ID", "GRANTEE_ROLE", "PRIVILEGE", "GRANTED_ON", "OBJECT_NAME", "IS_FUTURE", "GRANT_OPTION", "GRANTED_BY"]
TAG_COLS = ["RUN_ID", "OBJECT_NAME", "DOMAIN", "COLUMN_NAME", "TAG_NAME", "TAG_VALUE", "APPLY_METHOD"]
POLICY_COLS = ["RUN_ID", "POLICY_NAME", "POLICY_KIND", "OBJECT_NAME", "COLUMN_NAME", "ARG_COLUMNS", "TAG_NAME", "POLICY_BODY"]
DAYS = 30
TAG_FALLBACK_MAX = 300  # tables/views read one by one when the ACCOUNT_USAGE views are not readable


def rows(session, sql):
    """Rows as dicts with lower-case keys (SHOW columns are lower case, views upper case)."""
    return [{k.strip('"').lower(): v for k, v in r.as_dict().items()} for r in session.sql(sql).collect()]


def ident(name):
    return '"' + name.replace('"', '""') + '"'


def clean(name):  # SHOW quotes names with special characters; ACCOUNT_USAGE does not
    return name.replace('"', "")


def blank(v):
    return None if v in ("", "null", None) else v


def sq(text):  # inside a '...' SQL string
    return text.replace("'", "''")


def first_line(e):  # the cause is on the 2nd line of "SQL compilation error:\n..."
    return " ".join(str(e).split())[:500]


def fallback(session, view, mode):
    """None = read ACCOUNT_USAGE.<view>; else the reason to use the fallback."""
    if mode == "SHOW":
        return "SHOW forced by P_SOURCE"
    try:
        session.sql(f"SELECT 1 FROM {AU}.{view} LIMIT 1").collect()
        return None
    except Exception as e:
        if mode == "ACCOUNT_USAGE":
            raise
        return f"{AU}.{view} not readable: {first_line(e)}"


def save(session, table, cols, data):
    if data:
        session.create_dataframe(data, schema=cols).write.save_as_table(table, mode="append", column_order="name")
    return len(data)


def count(session, table, run_id):
    return session.sql(f"SELECT COUNT(*) AS N FROM {table} WHERE RUN_ID = '{run_id}'").collect()[0]["N"]


def grants(session, run_id, mode):
    """Role -> object and role -> role (ACCOUNT_USAGE.GRANTS_TO_ROLES or SHOW GRANTS TO ROLE), role -> user
    (GRANTS_TO_USERS or SHOW GRANTS OF ROLE)."""
    out = {}
    why = fallback(session, "GRANTS_TO_ROLES", mode) or fallback(session, "GRANTS_TO_USERS", mode)
    if why is None:
        # NAME holds only the object's own name; DATABASE rows may repeat it in TABLE_CATALOG
        session.sql(f"""INSERT INTO {GRANT} ({", ".join(GRANT_COLS)})
            SELECT '{run_id}', GRANTEE_NAME, PRIVILEGE, GRANTED_ON,
                   CASE WHEN GRANTED_ON = 'DATABASE' THEN NAME
                        WHEN GRANTED_ON = 'SCHEMA' THEN TABLE_CATALOG || '.' || NAME
                        ELSE ARRAY_TO_STRING(ARRAY_CONSTRUCT_COMPACT(TABLE_CATALOG, TABLE_SCHEMA, NAME), '.') END,
                   FALSE, GRANT_OPTION, GRANTED_BY
            FROM {AU}.GRANTS_TO_ROLES WHERE DELETED_ON IS NULL AND GRANTED_TO = 'ROLE'""").collect()
        session.sql(f"""INSERT INTO {USER_ROLE} (RUN_ID, USER_NAME, ROLE_NAME, GRANTED_BY)
            SELECT '{run_id}', GRANTEE_NAME, ROLE, GRANTED_BY FROM {AU}.GRANTS_TO_USERS WHERE DELETED_ON IS NULL""").collect()
        out["grants"] = out["user_roles"] = ("ACCOUNT_USAGE", None)
        return out
    g, u, skipped = [], [], []
    for role in [r["name"] for r in rows(session, "SHOW ROLES")]:
        try:
            for x in rows(session, f"SHOW GRANTS TO ROLE {ident(role)}"):
                if x.get("granted_to") in ("ROLE", None):
                    g.append([run_id, role, x["privilege"], x["granted_on"], clean(x["name"]), False,
                              str(x.get("grant_option")).lower() == "true", x.get("granted_by")])
            for x in rows(session, f"SHOW GRANTS OF ROLE {ident(role)}"):
                if x.get("granted_to") == "USER":
                    u.append([run_id, x["grantee_name"], role, x.get("granted_by")])
        except Exception as e:  # a role the owner may not inspect: keep going, list it in NOTES
            skipped.append(f"{role}: {first_line(e)}")
    save(session, GRANT, GRANT_COLS, g)
    save(session, USER_ROLE, ["RUN_ID", "USER_NAME", "ROLE_NAME", "GRANTED_BY"], u)
    note = why + (f"; {len(skipped)} roles skipped: " + " | ".join(skipped[:20]) if skipped else "")
    out["grants"] = out["user_roles"] = ("SHOW", note)
    return out


def future(session, run_id):
    """Future grants: no ACCOUNT_USAGE view, so always SHOW FUTURE GRANTS IN DATABASE / SCHEMA."""
    out, skipped = [], []
    for d in rows(session, "SHOW DATABASES"):
        if d.get("kind", "STANDARD") != "STANDARD":  # shares, applications: their grants are not ours
            continue
        db = d["name"]
        try:
            places = [f"DATABASE {ident(db)}"] + [f"SCHEMA {ident(db)}.{ident(s['name'])}"
                                                  for s in rows(session, f"SHOW SCHEMAS IN DATABASE {ident(db)}")
                                                  if s["name"] != "INFORMATION_SCHEMA"]
            for p in places:
                for x in rows(session, f"SHOW FUTURE GRANTS IN {p}"):
                    if x.get("grant_to") == "ROLE":
                        out.append([run_id, x["grantee_name"], x["privilege"], x["grant_on"], clean(x["name"]), True,
                                    str(x.get("grant_option")).lower() == "true", None])
        except Exception as e:
            skipped.append(f"{db}: {first_line(e)}")
    save(session, GRANT, GRANT_COLS, out)
    return "SHOW", (f"{len(skipped)} database{'s' if len(skipped) != 1 else ''} skipped — " + " | ".join(skipped[:20]) if skipped else None)


def users(session, run_id, mode):
    why = fallback(session, "USERS", mode)
    if why is None:
        # OBJECT_CONSTRUCT(*): the secondary roles column name differs between Snowflake versions
        session.sql(f"""INSERT INTO {USER} SELECT '{run_id}', J:NAME::STRING, J:TYPE::STRING, TRY_TO_BOOLEAN(J:DISABLED::STRING),
                   J:DEFAULT_ROLE::STRING, COALESCE(J:DEFAULT_SECONDARY_ROLES, J:DEFAULT_SECONDARY_ROLE)::STRING,
                   J:DEFAULT_WAREHOUSE::STRING, J:DEFAULT_NAMESPACE::STRING, TRY_TO_TIMESTAMP_LTZ(J:LAST_SUCCESS_LOGIN::STRING)
            FROM (SELECT OBJECT_CONSTRUCT(*) AS J FROM {AU}.USERS WHERE DELETED_ON IS NULL)""").collect()
        return "ACCOUNT_USAGE", None
    data = [[run_id, x["name"], blank(x.get("type")), str(x.get("disabled")).lower() == "true", blank(x.get("default_role")),
             blank(x.get("default_secondary_roles")), blank(x.get("default_warehouse")), blank(x.get("default_namespace")),
             blank(x.get("last_success_login"))] for x in rows(session, "SHOW USERS")]
    save(session, USER, ["RUN_ID", "USER_NAME", "TYPE", "DISABLED", "DEFAULT_ROLE", "DEFAULT_SECONDARY_ROLES",
                         "DEFAULT_WAREHOUSE", "DEFAULT_NAMESPACE", "LAST_SUCCESS_LOGIN"], data)
    return "SHOW", why


def usage(session, run_id, mode):
    """Roles, secondary roles and warehouses used per user, aggregated in SQL: ACCOUNT_USAGE.QUERY_HISTORY (30 days)
    or INFORMATION_SCHEMA.QUERY_HISTORY (7 days, max 10000 queries, only those the owner may see)."""
    def insert(src, secondary):
        sql = f"""INSERT INTO {USAGE} (RUN_ID, USER_NAME, KIND, NAME, QUERIES, LAST_USED)
            WITH Q AS ({src})
            SELECT '{run_id}', USER_NAME, 'ROLE', ROLE_NAME, COUNT(*), MAX(START_TIME) FROM Q WHERE ROLE_NAME IS NOT NULL GROUP BY 2, 4
            UNION ALL
            SELECT '{run_id}', USER_NAME, 'WAREHOUSE', WAREHOUSE_NAME, COUNT(*), MAX(START_TIME) FROM Q WHERE WAREHOUSE_NAME IS NOT NULL GROUP BY 2, 4"""
        if secondary:  # SECONDARY_ROLE_STATS: JSON text, roleNames = comma-separated roles
            sql += f"""
            UNION ALL
            SELECT '{run_id}', Q.USER_NAME, 'SECONDARY ROLE', TRIM(S.VALUE::STRING), COUNT(*), MAX(Q.START_TIME)
            FROM Q, LATERAL FLATTEN(SPLIT(TRY_PARSE_JSON(Q.SECONDARY_ROLE_STATS):roleNames::STRING, ',')) S
            WHERE TRIM(S.VALUE::STRING) <> '' GROUP BY 2, 4"""
        session.sql(sql).collect()

    why = fallback(session, "QUERY_HISTORY", mode)
    if why is None:
        insert(f"""SELECT USER_NAME, ROLE_NAME, WAREHOUSE_NAME, SECONDARY_ROLE_STATS, START_TIME FROM {AU}.QUERY_HISTORY
                   WHERE START_TIME >= DATEADD(DAY, -{DAYS}, CURRENT_TIMESTAMP())""", True)
        return "ACCOUNT_USAGE", None
    try:
        insert("""SELECT USER_NAME, ROLE_NAME, WAREHOUSE_NAME, START_TIME FROM TABLE(&DB.INFORMATION_SCHEMA.QUERY_HISTORY(
                  END_TIME_RANGE_START => DATEADD(DAY, -7, CURRENT_TIMESTAMP()), RESULT_LIMIT => 10000))""", False)
        return "INFORMATION_SCHEMA", why + "; INFORMATION_SCHEMA.QUERY_HISTORY: 7 days, max 10000 queries, owner's view only"
    except Exception as e:
        return "UNAVAILABLE", why + f"; INFORMATION_SCHEMA.QUERY_HISTORY: {first_line(e)}"


def data_objects(session, run_id):
    """Tables and views in this run's grant data: the objects the per-object fallback reads."""
    return [r["object_name"] for r in rows(session, f"""SELECT DISTINCT OBJECT_NAME FROM {GRANT}
        WHERE RUN_ID = '{run_id}' AND NOT IS_FUTURE AND (GRANTED_ON LIKE '%TABLE%' OR GRANTED_ON LIKE '%VIEW%')
        ORDER BY 1""")]


def quoted(name):  # DB.SCHEMA.OBJECT (unquoted, as in the grant data) -> "DB"."SCHEMA"."OBJECT"
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
                WHERE OBJECT_DELETED IS NULL AND DOMAIN IN ('DATABASE', 'SCHEMA', 'TABLE', 'COLUMN')""").collect()
            return "ACCOUNT_USAGE", None
        objs, out, skipped = data_objects(session, run_id), [], []
        for o in objs[:TAG_FALLBACK_MAX]:
            fn = f"{ident(o.split('.')[0])}.INFORMATION_SCHEMA"
            try:
                # to verify: LEVEL = where the tag is set (DATABASE, SCHEMA, TABLE, COLUMN); TABLE rows include the
                # tags inherited from the schema and database; column rows set higher up are skipped (the table row has them)
                for x in rows(session, f"SELECT * FROM TABLE({fn}.TAG_REFERENCES('{sq(quoted(o))}', 'table'))"):
                    out.append([run_id, o, "TABLE", None, f"{x['tag_database']}.{x['tag_schema']}.{x['tag_name']}",
                                x.get("tag_value"), "INHERITED" if x.get("level") not in (None, "TABLE") else "MANUAL"])
                for x in rows(session, f"SELECT * FROM TABLE({fn}.TAG_REFERENCES_ALL_COLUMNS('{sq(quoted(o))}', 'table'))"):
                    if x.get("level") in (None, "COLUMN"):
                        out.append([run_id, o, "COLUMN", x.get("column_name"),
                                    f"{x['tag_database']}.{x['tag_schema']}.{x['tag_name']}", x.get("tag_value"),
                                    x.get("apply_method") or "MANUAL"])
            except Exception as e:  # an object the owner may not inspect: keep going, list it in NOTES
                skipped.append(f"{o}: {first_line(e)}")
        save(session, TAG, TAG_COLS, out)
        return "INFORMATION_SCHEMA", capped_note(why, objs, skipped)
    except Exception as e:
        session.sql(f"DELETE FROM {TAG} WHERE RUN_ID = '{run_id}'").collect()
        return "UNAVAILABLE", "; ".join(filter(None, [why, first_line(e)]))


def policies(session, run_id, mode):
    """Masking and row access policies with their text: ACCOUNT_USAGE.POLICY_REFERENCES + MASKING_POLICIES /
    ROW_ACCESS_POLICIES, else INFORMATION_SCHEMA.POLICY_REFERENCES per table/view (TAG_FALLBACK_MAX) and DESCRIBE for
    the text (empty when DESCRIBE fails). An error: UNAVAILABLE, the run stays OK."""
    why = fallback(session, "POLICY_REFERENCES", mode)
    try:
        if why is None:
            # to verify: a policy set on a tag comes as REF_ENTITY_DOMAIN = 'TAG'; REF_ARG_COLUMN_NAMES type;
            # whether rows of detached policies stay (POLICY_STATUS)
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
                WHERE R.POLICY_KIND IN ('MASKING_POLICY', 'ROW_ACCESS_POLICY')""").collect()
            return "ACCOUNT_USAGE", None
        objs, out, skipped, body = data_objects(session, run_id), [], [], {}
        for o in objs[:TAG_FALLBACK_MAX]:
            fn = f"{ident(o.split('.')[0])}.INFORMATION_SCHEMA"
            try:
                for x in rows(session, f"""SELECT * FROM TABLE({fn}.POLICY_REFERENCES(
                        REF_ENTITY_NAME => '{sq(quoted(o))}', REF_ENTITY_DOMAIN => 'table'))"""):
                    if x.get("policy_kind") not in ("MASKING_POLICY", "ROW_ACCESS_POLICY"):
                        continue
                    name = f"{x['policy_db']}.{x['policy_schema']}.{x['policy_name']}"
                    if name not in body:
                        what = "MASKING POLICY" if x["policy_kind"] == "MASKING_POLICY" else "ROW ACCESS POLICY"
                        try:
                            body[name] = rows(session, f"DESCRIBE {what} {quoted(name)}")[0].get("body")
                        except Exception:  # no rights on the policy: its text stays empty, "cannot derive" in the app
                            body[name] = None
                    tag = f"{x['tag_database']}.{x['tag_schema']}.{x['tag_name']}" if x.get("tag_name") else None
                    out.append([run_id, name, x["policy_kind"], o, x.get("ref_column_name"),
                                blank(x.get("ref_arg_column_names")), tag, body[name]])
            except Exception as e:
                skipped.append(f"{o}: {first_line(e)}")
        save(session, POLICY, POLICY_COLS, out)
        return "INFORMATION_SCHEMA", capped_note(why, objs, skipped)
    except Exception as e:
        session.sql(f"DELETE FROM {POLICY} WHERE RUN_ID = '{run_id}'").collect()
        return "UNAVAILABLE", "; ".join(filter(None, [why, first_line(e)]))


def run(session, p_source):
    mode = (p_source or "AUTO").upper()
    if mode not in ("AUTO", "ACCOUNT_USAGE", "SHOW"):
        raise ValueError("P_SOURCE must be AUTO, ACCOUNT_USAGE or SHOW")
    busy = session.sql(f"""SELECT RUN_ID FROM {RUN} WHERE STATUS = 'RUNNING'
                           AND STARTED_AT > DATEADD(HOUR, -1, CURRENT_TIMESTAMP())""").collect()
    if busy:  # the app has a Refresh button: two CALLs at once would delete each other's rows
        return {"status": "SKIPPED", "notes": {"error": f"run {busy[0]['RUN_ID']} is still running"}}
    run_id = str(uuid.uuid4())
    session.sql(f"INSERT INTO {RUN} (RUN_ID, STARTED_AT, STATUS) SELECT '{run_id}', CURRENT_TIMESTAMP(), 'RUNNING'").collect()
    result = {"run_id": run_id, "sources": {}, "row_counts": {}, "notes": {}}

    def keep(name, source, note):
        result["sources"][name] = source
        if note:
            result["notes"][name] = note

    try:
        for name, (source, note) in grants(session, run_id, mode).items():
            keep(name, source, note)
        keep("future_grants", *future(session, run_id))
        keep("users", *users(session, run_id, mode))
        keep("usage", *usage(session, run_id, mode))
        keep("tags", *tags(session, run_id, mode))
        keep("policies", *policies(session, run_id, mode))
        result["status"] = "OK"
    except Exception as e:
        result["status"], result["notes"]["error"] = "FAILED", first_line(e)
    for name, t in [("grants", GRANT), ("user_roles", USER_ROLE), ("users", USER), ("usage", USAGE), ("tags", TAG),
                    ("policies", POLICY)]:
        result["row_counts"][name] = count(session, t, run_id)
    if result["status"] == "FAILED":  # drop this run's partial rows
        for t in DATA:
            session.sql(f"DELETE FROM {t} WHERE RUN_ID = '{run_id}'").collect()
    session.sql(f"""UPDATE {RUN} SET FINISHED_AT = CURRENT_TIMESTAMP(), STATUS = ?, SOURCES = PARSE_JSON(?),
                    ROW_COUNTS = PARSE_JSON(?), NOTES = PARSE_JSON(?) WHERE RUN_ID = ?""",
                params=[result["status"], json.dumps(result["sources"]), json.dumps(result["row_counts"]),
                        json.dumps(result["notes"]), run_id]).collect()
    if result["status"] == "OK":  # only now, so the app always finds the rows of the last OK run
        for t in DATA:
            session.sql(f"DELETE FROM {t} WHERE RUN_ID <> '{run_id}'").collect()
    return result
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

-- the app's "Refresh snapshot now" button: the CALL runs with the owner's rights, whoever clicks
-- name: GRANT_PROCEDURE_APP (may fail)
GRANT USAGE ON PROCEDURE &DB.&SCHEMA.SP_ACCESS_SNAPSHOT(VARCHAR) TO ROLE &APP_ROLE;

-- what the developer role needs to read every grant (real set-up: infrastructure as code), one of:
--   ACCOUNT_USAGE:  GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE &DEV_ROLE;   (every view)
--                   or the SNOWFLAKE database roles SECURITY_VIEWER (GRANTS_TO_*, USERS) + GOVERNANCE_VIEWER (QUERY_HISTORY,
--                   TAG_REFERENCES, POLICY_REFERENCES, MASKING_POLICIES, ROW_ACCESS_POLICIES; Enterprise edition for tags)
--   SHOW fallback:  GRANT MANAGE GRANTS ON ACCOUNT TO ROLE &DEV_ROLE;   (without it SHOW lists only what the role may see)
