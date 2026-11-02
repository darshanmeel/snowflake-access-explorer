"""Snowflake grants + recursive access lookups and rule checks. No Streamlit import, so it can be tested alone.

Data: fake() (layered RBAC model), snapshot() (the TBL_ACCESS_ tables filled by SP_ACCESS_SNAPSHOT, sql/1_setup.sql)
or mine() (the logged-in user's own access, live). All return the same dict; build() turns it into the lookups below.
"""
import difflib
import fnmatch
import json
import os
import re
from datetime import datetime

ADMIN = {"ACCOUNTADMIN", "SECURITYADMIN", "SYSADMIN", "USERADMIN", "ORGADMIN"}
MAX_HOPS = int(os.environ.get("MAX_HOPS", "50"))  # safety cap on role hops per walk
# functional and technical role prefixes; another naming: ROLE_PREFIXES=<functional>,<technical>
FUNC, TECH = os.environ.get("ROLE_PREFIXES", "F_,T_").split(",")
# may hold OWNER roles (rule 4): the build identity; fnmatch patterns, e.g. BUILD_ROLES=F_DEPLOY,F_*_STEWARD
BUILD = os.environ.get("BUILD_ROLES", FUNC + "DEPLOY").split(",")
TABLES = ["GRANT", "USER_ROLE", "USER", "USAGE", "TAG", "POLICY"]
# tag (last part of its name) = values that make a column/object sensitive; no "=" means any value
SENSITIVE_TAGS = os.environ.get("SENSITIVE_TAGS",
                                "PRIVACY_CATEGORY=IDENTIFIER|QUASI_IDENTIFIER|SENSITIVE,SENSITIVITY=PII|CONFIDENTIAL")
READ_PRIVS = set(os.environ.get("READ_PRIVS", "SELECT,OWNERSHIP").split(","))  # privileges that let you read data
DORMANT_DAYS = int(os.environ.get("DORMANT_DAYS", "90"))  # no login for this long (from the run's FINISHED_AT)
MAX_DEPTH_RULE = int(os.environ.get("MAX_DEPTH_RULE", "5"))  # rule 14
# rule 17: read-only roles by name (capability words only) and by behaviour (mostly read, a few writes)
READ_ROLE_PATTERNS = re.compile(os.environ.get(
    "READ_ROLE_PATTERNS", r"_READ$|_READ_|_R$|_R_|_RO$|_RO_|READONLY|READ_ONLY|VIEWER|_VIEW$|REPORTING|_RPT"), re.I)
READ_SHARE = float(os.environ.get("READ_SHARE", "0.8"))
READ_MIN_OBJECTS = int(os.environ.get("READ_MIN_OBJECTS", "5"))
RULES = {  # number -> (title, why); severity in SEVERITY
    "1": ("Technical role granted to a user or group role", "Technical roles belong under functional roles only."),
    "2": ("Direct privilege on a functional role", "Privileges sit on technical roles, so the role model stays reviewable."),
    "3": ("READ held directly and through another role", "The direct grant is redundant and survives when the other one is removed."),
    "4": ("OWNER role held by a consumer", "Owners can drop and re-grant objects; only the build identity should own."),
    "5": ("Admin role held by a person", "Admin roles bypass the role model; use them through break-glass only."),
    "6": ("Sensitive column without a masking policy", "Everyone who can read the object sees the value in clear."),
    "7": ("Dormant or disabled person can read sensitive data", "Unused access to sensitive data is pure risk."),
    "8": ("Disabled user still holds roles", "Re-enabling the user brings all access back at once."),
    "9": ("Privilege granted to PUBLIC", "Every user, present and future, gets it."),
    "10": ("Person can write to a sensitive object", "Writes to sensitive data should come from the build or a service user."),
    "11": ("Sensitive object reachable through a group role", "Group membership is managed outside Snowflake, so reviews miss it."),
    "12": ("Admin role is a user's default role", "Every session starts with admin rights."),
    "13": ("Orphan role: no users and no parent roles", "Unused roles hide access that nobody reviews."),
    "14": (f"Chain deeper than {MAX_DEPTH_RULE} roles", "Long chains are hard to review and hide where access comes from."),
    "15": ("Future grant in a schema that holds sensitive data", "New tables there are readable before anyone classifies them."),
    "16": (f"Dormant user (no login for {DORMANT_DAYS} days) still holds roles", "Unused accounts are an easy way in."),
    "17": ("Read-only role can write", "The role name or its use says read-only, but it can change data."),
}
SEVERITY = {"1": "Medium", "2": "Medium", "3": "Low", "4": "High", "5": "High", "6": "Medium", "7": "High", "8": "Low",
            "9": "High", "10": "Medium", "11": "Low", "12": "High", "13": "Low", "14": "Low", "15": "Medium",
            "16": "Medium", "17": "High"}  # rule number -> severity, edit freely

# ---------- fake data: users -> group role -> functional roles -> technical roles -> objects ----------

SCHEMAS = {
    "SALES": {"RAW": ["TBL_ORDER_RAW"], "CLEAN": ["TBL_ORDER"],
              "CORE": ["TBL_CUSTOMER", "SP_LOAD_CUSTOMER"], "MART": ["VW_CUSTOMER"]},
    "SHARED": {"LOGGING": ["TBL_LOGGING"], "MONITORING": ["SP_LOG_RUN"],
               "GOVERNANCE": ["SP_APPLY_RLS"]},
    "FINANCE": {"REPORT": ["TBL_REVENUE", "VW_REVENUE_MONTHLY"]},
}
# demo of deep nesting: group role -> 8 nested functional roles -> WRITE -> READ, 10 role hops from the user
CHAIN = ["GRP_EMEA_ALL", "EMEA", "EMEA_DE", "EMEA_DE_FINANCE", "EMEA_DE_FINANCE_CONTROLLING", "FINANCE",
         "FINANCE_REPORTING", "FINANCE_EDITOR"]
FIN_USERS = [f"FIN_{i:02}" for i in range(1, 15)]  # more than 12 users in one graph column


def fake():
    def kind(obj):
        return {"TBL": "TABLE", "VW": "VIEW", "SP": "PROCEDURE"}[obj.split("_")[0]]

    F, T = FUNC, TECH
    rg, ur, pv = [], [], []  # (granted role, grantee role), (role, user), (role, privilege, type, object)
    for db, schemas in SCHEMAS.items():
        pv += [(f"{T}{db}_OWNER", p, "DATABASE", db) for p in ("USAGE", "CREATE SCHEMA")]
        for sc, objs in schemas.items():
            base = f"{T}{db}_{sc}"
            rg += [(f"{base}_OWNER", f"{T}{db}_OWNER"), (f"{base}_READ", f"{base}_WRITE")]
            for cap in ("OWNER", "READ", "WRITE", "EXECUTE"):
                pv.append((f"{base}_{cap}", "USAGE", "DATABASE", db))
            pv.append((f"{base}_OWNER", "OWNERSHIP", "SCHEMA", f"{db}.{sc}"))
            pv += [(f"{base}_{c}", "USAGE", "SCHEMA", f"{db}.{sc}") for c in ("READ", "WRITE", "EXECUTE")]
            for o in objs:
                name, k = f"{db}.{sc}.{o}", kind(o)
                pv.append((f"{base}_OWNER", "OWNERSHIP", k, name))
                if k in ("TABLE", "VIEW"):
                    pv.append((f"{base}_READ", "SELECT", k, name))
                if k == "TABLE":
                    pv += [(f"{base}_WRITE", p, k, name) for p in ("INSERT", "UPDATE", "DELETE", "TRUNCATE")]
                if k == "PROCEDURE":
                    pv.append((f"{base}_EXECUTE", "USAGE", k, name))
    pv += [(f"{T}SALES_CORE_READ", "SELECT", "FUTURE TABLE", "SALES.CORE.<TABLE>"),
           (f"{T}SHARED_STAGE_READ", "USAGE", "SCHEMA", "SHARED.STAGE"),  # schema not modelled above
           (f"{F}SECURITY", "MANAGE GRANTS", "ACCOUNT", "ACCOUNT"),  # fake: account privilege on a functional role
           (f"{F}ANALYST", "USAGE", "WAREHOUSE", "WH_SALES_XS"),  # fake: direct privilege on a functional role
           ("PUBLIC", "USAGE", "WAREHOUSE", "WH_SALES_XS"),  # fake: grant to PUBLIC (rule 9)
           (f"{T}SHARED_LOGGING_READ", "INSERT", "TABLE", "SHARED.LOGGING.TBL_LOGGING")]  # fake: READ role writes (17)
    rg += [
        # technical -> technical (same and cross database)
        (f"{T}SALES_RAW_OWNER", f"{T}SALES_CLEAN_OWNER"),
        (f"{T}SALES_CLEAN_READ", f"{T}SALES_CORE_OWNER"),
        (f"{T}SHARED_MONITORING_EXECUTE", f"{T}SALES_CORE_OWNER"),
        # technical -> functional
        (f"{T}SALES_MART_READ", f"{F}ANALYST"),
        (f"{T}SALES_CORE_READ", f"{F}ANALYST"),
        (f"{T}SALES_OWNER", f"{F}DEPLOY"),
        (f"{T}SHARED_OWNER", f"{F}DEPLOY"),
        (f"{T}SALES_CORE_WRITE", f"{F}ENGINEER"),
        (f"{T}SALES_CORE_READ", f"{F}ENGINEER"),  # fake: READ plus WRITE (rule 3)
        (f"{T}SALES_CORE_EXECUTE", f"{F}ENGINEER"),
        (f"{T}SHARED_LOGGING_READ", f"{F}ENGINEER"),
        (f"{T}SALES_MART_OWNER", f"{F}ENGINEER"),  # fake: OWNER role on a consumer (rule 4)
        (f"{T}SHARED_GOVERNANCE_EXECUTE", f"{F}SECURITY"),
        (f"{T}SHARED_MONITORING_EXECUTE", f"{F}SECURITY"),
        (f"{T}SHARED_STAGE_READ", f"{F}SECURITY"),
        # functional -> group role (synced from the identity provider)
        (f"{F}ANALYST", "GRP_ANALYSTS"),
        (f"{T}SHARED_LOGGING_READ", "GRP_ANALYSTS"),  # fake: technical role on a group role
        (f"{T}FINANCE_OWNER", f"{F}DEPLOY"),
        (f"{T}FINANCE_REPORT_WRITE", f"{F}{CHAIN[-1]}"),
        (f"{T}SALES_MART_READ", f"{F}LEGACY_REPORTING"),  # fake: orphan role, no users or parents (rule 13)
    ]
    # fake: read-only by name, with one write role inside (rule 17, name + behaviour heuristic)
    rg += [(f"{T}{x}", f"{F}REPORTING_RO") for x in ("SALES_CORE_READ", "SALES_MART_READ", "FINANCE_REPORT_READ",
                                                      "SALES_RAW_WRITE")]
    # fake: mostly read, no read-only name, one write role inside (rule 17, behaviour heuristic)
    rg += [(f"{T}{x}", f"{F}MARKETING") for x in ("SALES_CORE_READ", "SALES_MART_READ", "SALES_CLEAN_READ",
                                                   "FINANCE_REPORT_READ", "SHARED_GOVERNANCE_EXECUTE",
                                                   "SALES_CLEAN_WRITE")]
    chain = [CHAIN[0]] + [F + c for c in CHAIN[1:]]
    rg += [(child, parent) for parent, child in zip(chain, chain[1:])]
    rg += [(r, "SYSADMIN") for r in sorted({g for x in rg for g in x}) if r.startswith((F, T))]  # custom roles -> SYSADMIN
    rg += [("SYSADMIN", "ACCOUNTADMIN"), ("SECURITYADMIN", "ACCOUNTADMIN"),
           ("SYSADMIN", f"{F}SECURITY")]  # fake: functional role holding an admin role
    ur += [
        ("GRP_ANALYSTS", "ANALYST_01"),
        ("GRP_ANALYSTS", "ANALYST_02"),
        (f"{T}SALES_MART_READ", "ANALYST_02"),  # fake: technical role on a user
        (f"{F}ENGINEER", "ENGINEER_01"),
        (f"{F}ANALYST", "ENGINEER_01"),
        (f"{F}SECURITY", "ADMIN_01"),
        (f"{F}DEPLOY", "SVC_DEPLOY"),
        ("SECURITYADMIN", "ADMIN_01"),  # fake: user with an admin role directly
        (f"{F}REPORTING_RO", "REPORT_01"),
        (f"{F}MARKETING", "MARKETING_01"),
        ("SYSADMIN", "OPS_01"),  # fake: admin role that is also the default role (rules 5, 12)
    ]
    ur += [(CHAIN[0], u) for u in FIN_USERS]
    grants = [dict(GRANTEE_ROLE=p, PRIVILEGE="USAGE", GRANTED_ON="ROLE", OBJECT_NAME=c, IS_FUTURE=False) for c, p in rg]
    grants += [dict(GRANTEE_ROLE=r, PRIVILEGE=p, GRANTED_ON=k.replace("FUTURE ", ""), OBJECT_NAME=o,
                    IS_FUTURE=k.startswith("FUTURE")) for r, p, k, o in pv]
    logins = {"ANALYST_01": "2026-11-01 08:40", "ANALYST_02": "2026-07-15 10:05", "ENGINEER_01": "2026-11-02 06:55",
              "ADMIN_01": "2026-10-28 14:20", "SVC_DEPLOY": "2026-11-02 06:00", "FIN_12": None,
              "FIN_13": "2026-05-04 09:30", "FIN_14": "2026-03-02 11:00", "REPORT_01": "2026-10-31 09:15",
              "MARKETING_01": "2026-11-01 13:30", "OPS_01": "2026-10-29 16:45"}  # ANALYST_02, FIN_12/13/14 dormant
    users = [dict(USER_NAME=u, TYPE=t, DISABLED=u == "FIN_14", DEFAULT_ROLE=d, DEFAULT_SECONDARY_ROLES=s,
                  DEFAULT_WAREHOUSE=w, DEFAULT_NAMESPACE=None, LAST_SUCCESS_LOGIN=logins.get(u, "2026-10-30 08:12"))
             for u, t, d, s, w in [("ANALYST_01", "PERSON", "GRP_ANALYSTS", '["ALL"]', "WH_SALES_XS"),
                                   ("ANALYST_02", "PERSON", "GRP_ANALYSTS", "[]", "WH_SALES_XS"),
                                   ("ENGINEER_01", "PERSON", f"{F}ENGINEER", '["ALL"]', "WH_SALES_XS"),
                                   ("ADMIN_01", "PERSON", f"{F}SECURITY", '["ALL"]', None),
                                   ("SVC_DEPLOY", "SERVICE", f"{F}DEPLOY", None, "WH_SALES_XS"),
                                   ("REPORT_01", "PERSON", f"{F}REPORTING_RO", '["ALL"]', "WH_SALES_XS"),
                                   ("MARKETING_01", "PERSON", f"{F}MARKETING", '["ALL"]', "WH_SALES_XS"),
                                   ("OPS_01", "PERSON", "SYSADMIN", '["ALL"]', None)]
             + [(u, "PERSON", CHAIN[0], '["ALL"]', "WH_FINANCE_XS") for u in FIN_USERS]]  # FIN_14 disabled
    usage = [dict(USER_NAME=u, KIND=k, NAME=n, QUERIES=q, LAST_USED="2026-10-30 09:00")
             for u, k, n, q in [("ANALYST_01", "ROLE", "GRP_ANALYSTS", 412),
                                ("ANALYST_01", "WAREHOUSE", "WH_SALES_XS", 412),
                                ("ENGINEER_01", "ROLE", f"{F}ENGINEER", 95),
                                ("ENGINEER_01", "SECONDARY ROLE", f"{F}ANALYST", 40),
                                ("ENGINEER_01", "WAREHOUSE", "WH_SALES_XS", 95),
                                ("ADMIN_01", "ROLE", "SECURITYADMIN", 7),
                                ("SVC_DEPLOY", "ROLE", f"{F}DEPLOY", 1300),
                                ("FIN_01", "ROLE", CHAIN[0], 58),
                                ("FIN_01", "WAREHOUSE", "WH_FINANCE_XS", 58)]]
    sem, pc, sens = "SNOWFLAKE.CORE.SEMANTIC_CATEGORY", "SNOWFLAKE.CORE.PRIVACY_CATEGORY", "SHARED.GOVERNANCE.SENSITIVITY"
    tags = [dict(OBJECT_NAME=o, DOMAIN=dm, COLUMN_NAME=c, TAG_NAME=t, TAG_VALUE=v, APPLY_METHOD=m)
            for o, dm, c, t, v, m in [
                ("SALES.CORE.TBL_CUSTOMER", "COLUMN", "EMAIL", sem, "EMAIL", "CLASSIFIED"),
                ("SALES.CORE.TBL_CUSTOMER", "COLUMN", "EMAIL", pc, "IDENTIFIER", "CLASSIFIED"),
                ("SALES.CORE.TBL_CUSTOMER", "COLUMN", "PHONE", sem, "PHONE_NUMBER", "CLASSIFIED"),
                ("SALES.CORE.TBL_CUSTOMER", "COLUMN", "PHONE", pc, "IDENTIFIER", "CLASSIFIED"),
                ("SALES.CORE.TBL_CUSTOMER", "COLUMN", "BIRTH_DATE", sem, "DATE_OF_BIRTH", "CLASSIFIED"),
                ("SALES.CORE.TBL_CUSTOMER", "COLUMN", "BIRTH_DATE", pc, "QUASI_IDENTIFIER", "CLASSIFIED"),
                ("SALES.MART.VW_CUSTOMER", "COLUMN", "EMAIL", sens, "PII", "MANUAL"),
                ("SHARED.LOGGING.TBL_LOGGING", "COLUMN", "CLIENT_IP", sem, "IP_ADDRESS", "CLASSIFIED"),
                ("SHARED.LOGGING.TBL_LOGGING", "COLUMN", "CLIENT_IP", pc, "QUASI_IDENTIFIER", "CLASSIFIED"),
                ("FINANCE", "DATABASE", None, sens, "CONFIDENTIAL", "MANUAL"),  # inherited by every FINANCE object
                ("SALES.RAW.TBL_ORDER_RAW", "TABLE", None, sens, "INTERNAL", "MANUAL")]]  # tagged, not sensitive
    email = f"CASE WHEN IS_ROLE_IN_SESSION('{F}ENGINEER') THEN VAL ELSE '***MASKED***' END"
    policies = [dict(POLICY_NAME="SHARED.GOVERNANCE." + n, POLICY_KIND=k, OBJECT_NAME=o, COLUMN_NAME=c, ARG_COLUMNS=a,
                     TAG_NAME=t, POLICY_BODY=b) for n, k, o, c, a, t, b in [
        ("MP_EMAIL", "MASKING_POLICY", "SALES.CORE.TBL_CUSTOMER", "EMAIL", None, None, email),
        ("MP_EMAIL", "MASKING_POLICY", "SALES.MART.VW_CUSTOMER", "EMAIL", None, None, email),
        ("RAP_REGION", "ROW_ACCESS_POLICY", "FINANCE.REPORT.TBL_REVENUE", None, "REGION", None,
         f"IS_ROLE_IN_SESSION('{F}FINANCE') OR CURRENT_ROLE() = '{F}DEPLOY'"),
        ("MP_IP", "MASKING_POLICY", None, None, None, "SHARED.GOVERNANCE.NETWORK_DATA",  # on a tag nobody carries
         "CASE WHEN EXISTS (SELECT 1 FROM SHARED.GOVERNANCE.TBL_UNMASK U WHERE U.ROLE_NAME = CURRENT_ROLE()) "
         "THEN VAL ELSE '0.0.0.0' END")]]
    run = dict(RUN_ID="fake", FINISHED_AT="2026-11-02 07:00", SOURCES={}, NOTES={})
    return dict(run=run, GRANT=grants, USER_ROLE=[dict(USER_NAME=u, ROLE_NAME=r) for r, u in ur], USER=users, USAGE=usage,
                TAG=tags, POLICY=policies)


def snapshot(query, where):
    """The last OK run of the snapshot tables. query(sql) -> list of dicts; where = DB.SCHEMA of the tables."""
    runs = query(f"SELECT RUN_ID, FINISHED_AT, SOURCES, NOTES FROM {where}.TBL_ACCESS_RUN WHERE STATUS = 'OK' "
                 "ORDER BY FINISHED_AT DESC LIMIT 1")
    if not runs:
        raise RuntimeError(f"No OK run in {where}.TBL_ACCESS_RUN: CALL SP_ACCESS_SNAPSHOT() first (sql/2_snapshot.sql)")
    run = runs[0]
    for k in ("SOURCES", "NOTES"):  # VARIANT comes back as JSON text
        run[k] = json.loads(run[k]) if isinstance(run[k], str) else run[k] or {}
    d = {t: query(f"SELECT * FROM {where}.TBL_ACCESS_{t} WHERE RUN_ID = '{run['RUN_ID']}'") for t in TABLES}
    return d | {"run": run}


def ident(name):
    return '"' + name.replace('"', '""') + '"'


def line(e):
    return " ".join(str(e).split())[:300]


def mine(query, db):
    """The logged-in user's own access, live, with their own rights. Writes nothing (no tables, no temp tables).
    query(sql) -> list of dicts; db: a database whose INFORMATION_SCHEMA the user can read."""
    me = query("SELECT CURRENT_USER() AS U")[0]["U"]
    query("USE SECONDARY ROLES ALL")  # every granted role counts, as with DEFAULT_SECONDARY_ROLES = ('ALL')
    roles = json.loads(query("SELECT CURRENT_AVAILABLE_ROLES() AS R")[0]["R"])  # granted + inherited, always readable
    src, notes, grants, skipped = {}, {}, [], []
    for r in roles:
        try:
            grants += [dict(GRANTEE_ROLE=r, PRIVILEGE=x["privilege"], GRANTED_ON=x["granted_on"],
                            OBJECT_NAME=x["name"].replace('"', ""), IS_FUTURE=False)
                       for x in query(f"SHOW GRANTS TO ROLE {ident(r)}")]
        except Exception as e:
            skipped.append(f"{r} ({line(e)})")
    src["grants"] = "SHOW GRANTS TO ROLE"
    try:  # role links of the user's roles, and the roles granted to the user: no privileges needed
        applicable = query(f"SELECT GRANTEE, ROLE_NAME FROM {db}.INFORMATION_SCHEMA.APPLICABLE_ROLES")
    except Exception as e:
        applicable, notes["applicable_roles"] = [], line(e)
    if skipped:
        bad = {s.split(" (")[0] for s in skipped}
        grants += [dict(GRANTEE_ROLE=x["GRANTEE"], PRIVILEGE="USAGE", GRANTED_ON="ROLE", OBJECT_NAME=x["ROLE_NAME"],
                        IS_FUTURE=False) for x in applicable if x["GRANTEE"] in bad]
        notes["grants"] = f"{len(skipped)} roles not readable, their links from APPLICABLE_ROLES: " + " | ".join(skipped[:10])
    try:
        direct = [x["role"] for x in query(f"SHOW GRANTS TO USER {ident(me)}")]
        src["user_roles"] = "SHOW GRANTS TO USER"
    except Exception as e:
        direct = [x["ROLE_NAME"] for x in applicable if x["GRANTEE"] == me]
        src["user_roles"] = "APPLICABLE_ROLES"
        if not direct:  # last resort: the available roles no other available role holds
            held = {g["OBJECT_NAME"] for g in grants if g["GRANTED_ON"] == "ROLE" and g["PRIVILEGE"] == "USAGE"}
            direct, src["user_roles"] = [r for r in roles if r not in held], "CURRENT_AVAILABLE_ROLES"
        notes["user_roles"] = f"SHOW GRANTS TO USER: {line(e)}"
    try:
        p = {x["property"]: x["value"] for x in query(f"DESC USER {ident(me)}")}
        user = {k: None if p.get(k) in ("null", "", None) else p.get(k)
                for k in ("TYPE", "DEFAULT_ROLE", "DEFAULT_SECONDARY_ROLES", "DEFAULT_WAREHOUSE", "DEFAULT_NAMESPACE")}
        user |= dict(DISABLED=str(p.get("DISABLED")).lower() == "true", LAST_SUCCESS_LOGIN=None,
                     LOGIN_UNKNOWN=True)  # DESC USER has no last login: unknown, not "never"
    except Exception as e:
        user, notes["users"] = {}, f"DESC USER: {line(e)}"
    try:
        usage = query(f"""WITH Q AS (SELECT ROLE_NAME, WAREHOUSE_NAME, START_TIME FROM TABLE({db}.INFORMATION_SCHEMA.QUERY_HISTORY_BY_USER(
                USER_NAME => '{me.replace("'", "''")}', END_TIME_RANGE_START => DATEADD(DAY, -7, CURRENT_TIMESTAMP()), RESULT_LIMIT => 10000)))
            SELECT 'ROLE' AS KIND, ROLE_NAME AS NAME, COUNT(*) AS QUERIES, MAX(START_TIME) AS LAST_USED FROM Q WHERE ROLE_NAME IS NOT NULL GROUP BY 2
            UNION ALL
            SELECT 'WAREHOUSE', WAREHOUSE_NAME, COUNT(*), MAX(START_TIME) FROM Q WHERE WAREHOUSE_NAME IS NOT NULL GROUP BY 2""")
        src["usage"] = "INFORMATION_SCHEMA"
    except Exception as e:
        usage, src["usage"], notes["usage"] = [], "UNAVAILABLE", line(e)
    src["tags"] = src["policies"] = "UNAVAILABLE"
    notes["tags"] = "sensitivity needs the governance views of the shared snapshot"
    run = dict(RUN_ID="live", FINISHED_AT="now", SOURCES=src, NOTES=notes)
    return dict(run=run, GRANT=grants, USER_ROLE=[dict(USER_NAME=me, ROLE_NAME=r) for r in direct],
                USER=[dict(USER_NAME=me) | user], USAGE=[dict(USER_NAME=me) | u for u in usage], TAG=[], POLICY=[])


def only(d, user):
    """Demo of mine() without Snowflake: one user's slice of a full data set."""
    build(d)
    seen = {r for s in starts(user, True) for p in down(s) for r in p[1:]}
    run = dict(RUN_ID="live", FINISHED_AT="now", SOURCES={"all": f"demo: {user}'s slice of the fake data"}, NOTES={})
    return dict(run=run, GRANT=[g for g in d["GRANT"] if g["GRANTEE_ROLE"] in seen], TAG=[], POLICY=[],
                **{t: [x for x in d[t] if x["USER_NAME"] == user] for t in ("USER_ROLE", "USER", "USAGE")})


# ---------- lookups (filled by build) ----------

role_grants, user_grants, privs = [], [], []  # (granted role, grantee role), (role, user), (role, privilege, type, object)
holds, held_by, users_of, roles_of, profile, used = {}, {}, {}, {}, {}, {}
granted, on = {}, {}  # role -> [(privilege, type, object)], object -> [(role, privilege, type)]
roles, users, objects, kinds, run = [], [], [], {}, {}
tags, policies, sens = [], [], {}  # TAG rows, POLICY rows, sensitive(): object -> [(column, tag, value, origin)]
capped = set()  # start of every walk cut at MAX_HOPS; the UI clears it before a page and warns when it is not empty
memo = {}  # results that only depend on the data set (rule findings, ...), cleared by build()


def build(d, key=None):
    """Fill the module lookups from fake() or snapshot(). key: the same key as the last build skips the work (the app
    passes the run of the shared snapshot, so a rerun does not rebuild or recheck the rules)."""
    global roles, users, objects, run
    if key is not None and memo.get("key") == key:
        return
    memo.clear()
    memo["key"] = key
    for x in (role_grants, user_grants, privs, holds, held_by, users_of, roles_of, profile, used, kinds, granted, on,
              capped, tags, policies, sens):
        x.clear()
    for g in d["GRANT"]:
        if g["GRANTED_ON"] == "ROLE" and g["PRIVILEGE"] == "USAGE":  # role inheritance; OWNERSHIP on a role is not
            # every custom role is also granted to SYSADMIN: dropped so admin roles don't swallow every graph;
            # holding an admin role is kept and flagged in red
            if g["GRANTEE_ROLE"] not in ADMIN:
                role_grants.append((g["OBJECT_NAME"], g["GRANTEE_ROLE"]))
        else:
            k = ("FUTURE " if g["IS_FUTURE"] else "") + g["GRANTED_ON"]
            privs.append((g["GRANTEE_ROLE"], g["PRIVILEGE"], k, g["OBJECT_NAME"]))
            if g["GRANTED_ON"] != "ROLE":  # OWNERSHIP on a role: it stays a role, not an object
                kinds[g["OBJECT_NAME"]] = k
    user_grants.extend((g["ROLE_NAME"], g["USER_NAME"]) for g in d["USER_ROLE"])
    for child, parent in role_grants:
        holds.setdefault(parent, []).append(child)
        held_by.setdefault(child, []).append(parent)
    for role, user in user_grants:
        users_of.setdefault(role, []).append(user)
        roles_of.setdefault(user, []).append(role)
    for r, pv, k, o in privs:
        granted.setdefault(r, []).append((pv, k, o))
        on.setdefault(o, []).append((r, pv, k))
    profile.update({u["USER_NAME"]: u for u in d["USER"]})
    for u in d["USAGE"]:
        used.setdefault(u["USER_NAME"], []).append(u)
    roles = sorted({r for g in role_grants for r in g} | {p[0] for p in privs} | {g[0] for g in user_grants})
    users = sorted(set(roles_of) | set(profile))
    objects = sorted(kinds)
    run = d["run"]
    tags.extend(d.get("TAG", []))  # older data sets have no TAG / POLICY
    policies.extend(d.get("POLICY", []))
    rules = tag_rules()
    for o in objects:
        hit = [t for t in tags_of(o) if tag_hit(rules, t[1], t[2])]
        if hit:
            sens[o] = hit


def cached(name, fn):
    """fn() once per data set (see build)."""
    if name not in memo:
        memo[name] = fn()
    return memo[name]


def kind_of(name):
    """user | admin | functional | technical | group | object. Group = any other role, PUBLIC included."""
    if name in profile or name in roles_of:
        return "user"
    if name in ADMIN:
        return "admin"
    if name.startswith(FUNC):
        return "functional"
    if name.startswith(TECH):
        return "technical"
    if name in kinds and name not in roles:
        return "object"
    return "group"


def priv_class(pv, kind=""):
    """read | write | own | use | admin (account-level: MANAGE GRANTS, CREATE ROLE, ...), for arrows and badges."""
    k = (kind or "").replace("FUTURE ", "")
    if k == "ACCOUNT":
        return "admin"
    if pv == "OWNERSHIP":
        return "own"
    if pv in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "WRITE") or pv.startswith(("CREATE ", "APPLY", "MODIFY", "ADD ")):
        return "write"
    if pv in ("SELECT", "REFERENCES", "READ") or (pv == "USAGE" and k in ("DATABASE", "SCHEMA")):
        return "read"
    return "use"


def tag_label(t, v):
    """"PRIVACY_CATEGORY=IDENTIFIER": tag (last name part) = value."""
    return f"{t.split('.')[-1]}={v}"


def future_label(o, kind):
    """"All future tables in SALES.CORE" for a future grant, else None."""
    if not (kind or "").startswith("FUTURE"):
        return None
    return f"All future {kind.split(' ', 1)[1].lower()}s in {o.rsplit('.', 1)[0]}"


NO_SPLIT = {"ACCOUNT", "WAREHOUSE", "ROLE", "USER", "INTEGRATION", "RESOURCE MONITOR", "COMPUTE POOL",
            "EXTERNAL VOLUME"}


def split_name(obj, kind=None):
    """(database, schema, own name) from OBJECT_NAME; account-level objects: ("", "", name). Role names never split."""
    k = (kind or kinds.get(obj) or "").replace("FUTURE ", "")
    if k == "DATABASE":
        return obj, "", obj
    if k == "SCHEMA" and "." in obj:
        db, sc = obj.split(".", 1)
        return db, sc, sc
    if k in NO_SPLIT or "." not in obj:
        return "", "", obj
    parts = obj.split(".", 2)
    return (parts[0], parts[1], parts[2]) if len(parts) == 3 else (parts[0], "", parts[1])  # future grant in a database


def is_data(kind):
    """Tables and views (any flavour), not future grants: what sensitivity and rule 17 count."""
    return not kind.startswith("FUTURE") and ("TABLE" in kind or "VIEW" in kind)


def stop(path, limit):
    """True when path may not grow: depth limit reached, or MAX_HOPS (then recorded in capped)."""
    if limit is not None and len(path) - 1 >= limit:
        return True
    if len(path) - 1 >= MAX_HOPS:
        capped.add(path[0])
        return True
    return False


def down(path, limit=None):
    """Every simple path from path[-1] to the roles it holds, recursively (path itself included).
    limit: max hops from path[0] (None = every level)."""
    if limit is not None and len(path) - 1 > limit:
        return
    yield path
    nxt = [r for r in holds.get(path[-1], []) if r not in path]
    if nxt and not stop(path, limit):
        for r in nxt:
            yield from down(path + [r], limit)


def up(path, limit=None):
    """Every simple path from path[-1] up to the roles and users that hold it. limit: max hops from path[0]."""
    yield path
    nxt = [r for r in held_by.get(path[-1], []) if r not in path]
    us = users if path[-1] == "PUBLIC" else users_of.get(path[-1], [])  # every user holds PUBLIC; it is never listed
    if (nxt or us) and not stop(path, limit):
        for r in nxt:
            yield from up(path + [r], limit)
        for u in us:
            yield path + [u]


def bfs(path):
    """Shortest path from path[0] through path[-1] to every role path[-1] holds: {role: path}. Cheap, no path explosion."""
    best, todo = {path[-1]: path}, [path]
    while todo:
        nxt = []
        for p in todo:
            for r in holds.get(p[-1], []):
                if r not in best:
                    best[r] = p + [r]
                    nxt.append(p + [r])
        todo = nxt
    return best


def users_through(name):
    """Users who reach a role (every user for PUBLIC); a user name gives itself."""
    if kind_of(name) == "user":
        return {name}
    seen, todo, out = {name}, [name], set()
    while todo:
        r = todo.pop()
        out.update(users if r == "PUBLIC" else users_of.get(r, []))
        for p in held_by.get(r, []):
            if p not in seen:
                seen.add(p)
                todo.append(p)
    return out


def starts(name, user=False, default_only=False):
    """Start paths: [role], or [user, role] per granted role. default_only: only paths to the user's default role
    (it may be inherited, not granted directly)."""
    if not user:
        return [[name]]
    paths = [[name, r] for r in roles_of.get(name, [])]
    if default_only:
        dr = (profile.get(name) or {}).get("DEFAULT_ROLE")
        paths = [p for s in paths for p in down(s) if p[-1] == dr]
    got = {r for p in paths for r in p[1:]}
    return paths + ([] if "PUBLIC" in got else [[name, "PUBLIC"]])  # every user holds PUBLIC; it is never listed


def walk(name, user=False, default_only=False, limit=None):
    """Every role path from a user or role: [name, ..., role]. limit: max depth (see depth())."""
    hops = None if limit is None else limit - (0 if user else 1)
    return [p for s in starts(name, user, default_only) for p in down(s, hops)]


def depth(chain, user):
    """Depth = number of roles in the chain from the start to the role holding the grant, holder included.
    A user is not a role, so ANALYST_01 > GRP_ANALYSTS > F_ANALYST > T_SALES_CORE_READ is 3, a grant holder alone is 1.
    The same on every page: grants, reach, held, grantees, matrix, object_stats, can."""
    return len(chain) - (1 if user else 0)


def chains(paths, up_paths=False):
    """Every depth of every node with its first chain: {node: {depth: chain}}. Down paths start at the selected
    user/role; up paths are grantee -> ... -> holder (no object), depth counted from the holder (= 1)."""
    out = {}
    for p in paths:
        u = kind_of(p[0]) == "user"
        for i, n in enumerate(p):
            d = (len(p) - i - (u and i == 0)) if up_paths else i + (not u)
            out.setdefault(n, {}).setdefault(d, p[i:] if up_paths else p[:i + 1])
    return out


# ---------- graph inputs (ui.lane_graph): lanes, edges, notes; one box per node at its shortest depth ----------

def notes(ch, nodes, word="D{}"):
    """{node: (badge, tooltip)}: badge "D2 · also D3" when a node is reached at more than one depth; the tooltip
    lists every depth with its chain."""
    out = {}
    for n in nodes:
        ds = sorted(ch.get(n, {}))
        if ds:
            badge = word.format(ds[0]) + " · also " + ", ".join(word.format(d) for d in ds[1:]) if len(ds) > 1 else ""
            out[n] = (badge, "\n".join(f"{word.format(d)}: {' > '.join(ch[n][d])}" for d in ds))
    return out


def role_links(paths):
    """Role -> role links of paths that end at a role ("inherits")."""
    return list(dict.fromkeys((p[i], p[i + 1]) for p in paths for i in range(len(p) - 1)))


def priv_links(rows):
    """Holder -> object links, one per privilege (lane_graph merges one class into one line): rows with privilege,
    type, paths (...->holder->object)."""
    return list(dict.fromkeys((p[-2], p[-1], priv_class(r["privilege"], r["type"]), r["privilege"])
                              for r in rows for p in r["paths"]))


def by_depth(nodes, depth_of, word, order):
    """[(label, names)] one lane per depth; order: depths left to right."""
    return [(word.format(d), sorted(n for n in nodes if depth_of.get(n) == d)) for d in order]


def down_graph(start, rows, walked=()):
    """User page / Can they? graph: grants() rows (as shown) + walk() paths of roles without grants.
    Returns (lanes, edges, notes) or None when nothing is reached."""
    part = [x[:-1] for r in rows for x in r["paths"]] + list(walked)
    if not part:
        return None
    ch = chains(part)
    d = {n: min(v) for n, v in ch.items()}
    nodes = set(d) - {start}
    objs = list(dict.fromkeys(r["object"] for r in rows))
    lanes = ([("User" if kind_of(start) == "user" else "Role", [start])]
             + by_depth(nodes, d, "Depth {}", range(1, max([d[n] for n in nodes] + [0]) + 1))
             + [("Object" if len(objs) == 1 else "Objects", objs)])
    return lanes, role_links(part) + priv_links(rows), notes(ch, nodes)


def object_graph(obj, kind, shown, users):
    """Object page graph: grantees() rows as shown and the users drawn. Returns (lanes, edges, notes) or None."""
    paths = [x[:-1] for row in shown for x in row["paths"]]
    if not paths:
        return None
    ch = chains(paths, True)
    d = {n: min(v) for n, v in ch.items()}
    nodes = set(d) - set(users)
    far = max([d[n] for n in nodes] + [1])
    lanes = ([("Users", [u for u in users if u in {x[0] for x in paths}])]
             + by_depth(nodes, d, "Depth {}", range(far, 1, -1))
             + by_depth(nodes, d, "Depth 1 · Grant holders", [1]) + [("Object", [obj])])
    edges = role_links(paths) + priv_links([dict(privilege=x["privilege"], type=kind, paths=x["paths"]) for x in shown])
    return lanes, edges, notes(ch, nodes)


def role_graph(role, up_rows, writes=()):
    """Role page graph: held() rows as shown (up), the role, what it holds (down) and the stray writes of a read-only
    role (writes: readonly_writes(role) rows). Lanes by depth, as in held(): the role is D1, a role holding it D2, ...;
    users in their own lane on the left. Returns (lanes, edges, notes, selected lane)."""
    paths = [x for row in up_rows for x in row["paths"]]
    ch = chains(paths, True)
    d = {n: min(v) for n, v in ch.items()}
    us = sorted(n for n in d if n != role and kind_of(n) == "user")
    nodes = set(d) - set(us) - {role}
    far = max([d[n] for n in nodes] + [1])
    hold, kids = holds_of(role), sorted(holds.get(role, []))
    objs = list(dict.fromkeys(h["object"] for h in hold))
    stray = [x for x in writes if x["inherited"] and x["holder"] in kids and x["object"] not in objs]
    lanes = ([("Users", us)] if us else []) + by_depth(nodes, d, "Depth {}", range(far, 1, -1))
    sel = len(lanes)
    lanes += [("Depth 1 · Selected role", [role]), ("Holds", kids + objs)]
    if stray:
        lanes.append(("Writes through held roles", list(dict.fromkeys(x["object"] for x in stray))))
    edges = role_links(paths) + [(role, x) for x in kids] + list(dict.fromkeys(
        (role, h["object"], h["cls"], h["privilege"]) for h in hold))
    edges += [(x["holder"], x["object"], priv_class(pv, kinds.get(x["object"], "")), pv) for x in stray
              for pv in x["privileges"]]
    return lanes, edges, notes(ch, nodes), sel


def access_of(name, user=False, default_only=False, limit=None):
    """Privileges of a user or role: rows (privilege, type, object, path user->...->role)."""
    return [(pv, k, o, p) for p in walk(name, user, default_only, limit) for pv, k, o in granted.get(p[-1], [])]


def admin_paths(name, user=False, default_only=False, limit=None):
    """Paths from a user or role to an admin role it holds."""
    return [p for p in walk(name, user, default_only, limit) if p[-1] in ADMIN and p[-1] != name]


def account_privs(name, user=False, default_only=False, limit=None):
    """Account-level privileges (MANAGE GRANTS, CREATE DATABASE, ...): rows (privilege, path)."""
    return [(pv, p) for pv, k, o, p in access_of(name, user, default_only, limit) if k == "ACCOUNT"]


def admin_holders():
    """Users and roles holding an admin role: rows (grantee, path grantee->...->admin role)."""
    return [(p[-1], p[::-1]) for r in sorted(ADMIN) for p in list(up([r]))[1:]]


def from_user(path):
    """path grantee->...->role starts at a user (not at a role of the same name)."""
    return len(path) > 1 and path[0] in (users if path[1] == "PUBLIC" else users_of.get(path[1], []))


def who_can(obj, kind=None, limit=None):
    """Who has which privilege on obj (of type kind): rows (grantee, privilege, path grantee->...->holder).
    limit: max depth (grant holder = 1, see depth())."""
    rows = [(p[-1], pv, p[::-1]) for r, pv, k in on.get(obj, []) if kind in (None, k) for p in up([r], limit)]
    return [x for x in rows if limit is None or depth(x[2], from_user(x[2])) <= limit]


def group(items):
    """[(key, path)] -> {key: [paths, shortest first]}."""
    out = {}
    for key, p in items:
        out.setdefault(key, []).append(p)
    return {key: sorted(ps, key=len) for key, ps in out.items()}


# ---------- users: status, dormancy ----------

def when(v):
    """Timestamp from Snowflake (datetime) or fake/DuckDB text; None for empty."""
    if v in (None, "", "now"):
        return None
    if isinstance(v, str):
        v = datetime.fromisoformat(v.strip()[:19].replace("T", " "))
    return v.replace(tzinfo=None)


def ref_time():
    """Dormancy is measured from the run's FINISHED_AT, not the wall clock."""
    return when((run or {}).get("FINISHED_AT")) or datetime.now()


def login_days(u):
    """Days since the last login, None when the user never logged in."""
    last = when((profile.get(u) or {}).get("LAST_SUCCESS_LOGIN"))
    return None if last is None else (ref_time() - last).days


def is_service(u):
    return (profile.get(u) or {}).get("TYPE") in ("SERVICE", "LEGACY_SERVICE")


def is_disabled(u):
    return str((profile.get(u) or {}).get("DISABLED")).lower() == "true"


def login_unknown(u):
    """My access: the last login is not readable for yourself (and you are logged in now)."""
    return bool((profile.get(u) or {}).get("LOGIN_UNKNOWN"))


def is_dormant(u):
    """No login for DORMANT_DAYS, or never logged in."""
    d = login_days(u)
    return not login_unknown(u) and (d is None or d >= DORMANT_DAYS)


def status(u):
    """disabled | never | dormant | active."""
    if is_disabled(u):
        return "disabled"
    if login_unknown(u):
        return "active"
    if login_days(u) is None:
        return "never"
    return "dormant" if is_dormant(u) else "active"


def split_users(names, admin=()):
    """KPI split: people (enabled persons), disabled, service (enabled service users), admin (only via admin roles)."""
    names = set(names)
    return dict(people=sorted(u for u in names if not is_disabled(u) and not is_service(u)),
                disabled=sorted(u for u in names if is_disabled(u)),
                service=sorted(u for u in names if is_service(u) and not is_disabled(u)),
                admin=sorted(set(admin) - names))


def used_roles(user):
    """Roles this user ran queries with (USAGE: 30 days, or 7 with the fallback): {role: dict(kind, queries, last_used)}."""
    return {u["NAME"]: dict(kind=u["KIND"], queries=u["QUERIES"], last_used=u["LAST_USED"])
            for u in used.get(user, []) if u["KIND"] in ("ROLE", "SECONDARY ROLE")}


# ---------- sensitive data: tags and policies ----------

def tag_rules():
    """SENSITIVE_TAGS -> {tag (last name part, upper): {values} or None (any value)}."""
    out = {}
    for x in filter(None, SENSITIVE_TAGS.split(",")):
        t, _, v = x.partition("=")
        out[t.strip().upper()] = {y.strip().upper() for y in v.split("|")} if v else None
    return out


def tag_hit(rules, tag, value):
    vals = rules.get(tag.split(".")[-1].upper(), False)
    return vals is None or (vals is not False and str(value).upper() in vals)


def tags_of(obj):
    """Every tag on obj, inherited ones included: [(column|None, tag, value, origin)]."""
    db, sc, _ = split_name(obj)
    out = []
    for t in tags:
        o, dm = t["OBJECT_NAME"], t["DOMAIN"]
        if o == obj:
            origin = "inherited" if t.get("APPLY_METHOD") == "INHERITED" else \
                "on column" if dm == "COLUMN" else f"on {(kinds.get(obj) or 'table').lower()}"
        elif dm == "SCHEMA" and o == f"{db}.{sc}":
            origin = f"inherited from schema {o}"
        elif dm == "DATABASE" and o == db:
            origin = f"inherited from database {o}"
        else:
            continue
        out.append((t["COLUMN_NAME"] if dm == "COLUMN" else None, t["TAG_NAME"], t["TAG_VALUE"], origin))
    return out


def sensitive():
    """Sensitive tables and views: {object: [(column|None, tag, value, origin)]}, sensitive tags only (SENSITIVE_TAGS).
    A database/schema/table tag makes the whole object sensitive (column None)."""
    return {o: t for o, t in sens.items() if is_data(kinds.get(o, ""))}


def sensitive_cols(obj):
    """Sensitive column names of obj, [] when the whole object is sensitive (or it is not)."""
    return sorted({c for c, *_ in sens.get(obj, []) if c})


SQL_OK = {"IS_ROLE_IN_SESSION", "CURRENT_ROLE", "CURRENT_USER", "INVOKER_ROLE", "CURRENT_ACCOUNT", "IN", "AND", "OR",
          "NOT", "IFF", "IFNULL", "NVL", "NVL2", "COALESCE", "NULLIF", "SHA2", "SHA1", "MD5", "HASH", "LEFT", "RIGHT",
          "SUBSTR", "SUBSTRING", "CONCAT", "REGEXP_REPLACE", "REPLACE", "LENGTH", "LEN", "REPEAT", "TO_VARCHAR",
          "TO_CHAR", "TO_NUMBER", "TO_DATE", "CAST", "TRY_CAST", "UPPER", "LOWER", "TRIM", "DATE_TRUNC", "YEAR",
          "OBJECT_INSERT", "CURRENT_DATE", "CURRENT_TIMESTAMP", "WHEN", "THEN"}


def clear_for(body):
    """Roles that see a masking policy's value in clear (or a row policy's rows), from the policy text, not evaluated.
    Returns (roles, exact): roles {role: "session" (IS_ROLE_IN_SESSION, hierarchy-aware) | "primary" (CURRENT_ROLE)};
    exact False when the body also checks the user or account. None = cannot derive (subquery, mapping table,
    UDF, database roles)."""
    if not body:
        return None
    b = body.upper()
    if re.search(r"\bSELECT\b|IS_DATABASE_ROLE_IN_SESSION|\w+\.\w+\s*\(", b):
        return None
    if set(re.findall(r"([A-Z_][A-Z0-9_$]*)\s*\(", b)) - SQL_OK:
        return None
    out = {r: "session" for r in re.findall(r"IS_ROLE_IN_SESSION\s*\(\s*'([^']+)'", b)}
    for m in re.finditer(r"CURRENT_ROLE\s*\(\s*\)\s*(?:=\s*'([^']+)'|IN\s*\(([^)]*)\))", b):
        for r in [m.group(1)] if m.group(1) else re.findall(r"'([^']+)'", m.group(2)):
            out.setdefault(r, "primary")
    return out, not re.search(r"CURRENT_USER|INVOKER_ROLE|CURRENT_ACCOUNT", b)


def pol(p, via=None):
    return dict(name=p["POLICY_NAME"], kind=p["POLICY_KIND"], body=p["POLICY_BODY"], args=p.get("ARG_COLUMNS"),
                tag=p.get("TAG_NAME"), via=via, clear=clear_for(p["POLICY_BODY"]))


def policies_of(obj):
    """Policies on obj: dict(columns={column: [policy]}, rows=[policy]). policy: name, kind, body, args, tag,
    via (tag the column carries for a tag-based policy, else None), clear (clear_for(body))."""
    cols, rows = {}, []
    for p in policies:
        if p["OBJECT_NAME"] == obj and p["POLICY_KIND"] == "ROW_ACCESS_POLICY":
            rows.append(pol(p))
        elif p["OBJECT_NAME"] == obj and p["COLUMN_NAME"]:
            cols.setdefault(p["COLUMN_NAME"], []).append(pol(p))
        elif not p["OBJECT_NAME"] and p.get("TAG_NAME"):  # attached to a tag: every column carrying that tag
            for c, t, _, _ in tags_of(obj):
                if c and t.upper() == p["TAG_NAME"].upper():
                    cols.setdefault(c, []).append(pol(p, t))
    return dict(columns=cols, rows=rows)


def policy_list():
    """Every policy row with a note: dict(policy fields..., object, column, note)."""
    out = []
    for p in policies:
        note = ""
        if not p["OBJECT_NAME"] and p.get("TAG_NAME"):
            n = sum(1 for t in tags if t["DOMAIN"] == "COLUMN" and t["TAG_NAME"].upper() == p["TAG_NAME"].upper())
            note = f"attached to tag {p['TAG_NAME']}, " + (f"{n} tagged columns" if n else "no tagged columns")
        out.append(pol(p) | dict(object=p["OBJECT_NAME"], column=p["COLUMN_NAME"], note=note))
    return out


def masked(name, obj, col=None):
    """clear | masked | ? for a column (col) or the rows (col None, row access policy) of obj, when name is in use:
    a role (as primary role) or a user (any role they hold). From the policy text, not evaluated. No policy = clear."""
    ps = policies_of(obj)
    found = ps["columns"].get(col, []) if col else ps["rows"]
    if not found:
        return "clear"
    user = kind_of(name) == "user"
    inside = {r for s in starts(name, user) for r in bfs(s)}
    c = min(found, key=lambda p: p["via"] is not None)["clear"]  # a direct policy wins over a tag-based one
    if c is None:
        return "?"
    return "clear" if any(r in inside if how == "session" or user else r == name for r, how in c[0].items()) else "masked"


def reads(path):
    """Objects the end of path reads (READ_PRIVS), shortest path each: {object: path ...->holder->object}."""
    out = {}
    for r, p in bfs(path).items():
        for pv, k, o in granted.get(r, []):
            if pv in READ_PRIVS and (o not in out or len(p) + 1 < len(out[o])):
                out[o] = p + [o]
    return out


def sensitive_reach(user):
    """Sensitive data per granted role (depth 1, PUBLIC included): one row per (sensitive object, granted role).
    Row: object, cols (sensitive columns, [] = whole object), role, path (user->role->...->holder->object) or None,
    masked {column: clear|masked|?} and rows (row policy: clear|masked|?) when there is a path."""
    out, s = [], sensitive()
    for st in starts(user, True):
        got = reads(st)
        for o in sorted(s):
            p = got.get(o)
            out.append(dict(object=o, cols=sensitive_cols(o), role=st[1], path=p,
                            masked={c: masked(st[1], o, c) for c in sensitive_cols(o)} if p else {},
                            rows=masked(st[1], o) if p else None))
    return out


def readers(obj):
    """Users who can read obj (READ_PRIVS, any path)."""
    return {x for x, pv, p in who_can(obj) if pv in READ_PRIVS and from_user(p)}


def sensitive_rank():
    """Sensitive objects, most people first. Row: object, database, schema, name, kind, tags, cols, masked (k, n),
    row_policies, users, people, disabled, service, admin, roles (roles with read)."""
    out, adm = [], admin_users()
    for o, t in sensitive().items():
        us, cols, ps = readers(o), sensitive_cols(o), policies_of(o)
        db, sc, nm = split_name(o)
        out.append(dict(object=o, database=db, schema=sc, name=nm, kind=kinds.get(o), tags=t, cols=cols,
                        masked=(sum(c in ps["columns"] for c in cols), len(cols)),
                        row_policies=[p["name"] for p in ps["rows"]], users=sorted(us), **split_users(us, adm),
                        roles=sorted({x for x, pv, p in who_can(o) if pv in READ_PRIVS and not from_user(p)})))
    return sorted(out, key=lambda r: (-len(r["people"]) - len(r["disabled"]) - len(r["service"]), r["object"]))


# ---------- page aggregations: plain lists of dicts ----------

def grants(name, user=False, default_only=False, limit=None):
    """User or role page (effective privileges, inherited included): one row per (privilege, type, object).
    Row: privilege, type, object, database, schema, name, cls (priv_class), holder, granted (depth-1 role: "Use role"),
    direct (held by the role itself), depth, path (shortest, name->...->holder->object), paths (shortest first), count."""
    g = group(((pv, k, o), p + [o]) for pv, k, o, p in access_of(name, user, default_only, limit))
    out = []
    for (pv, k, o), ps in sorted(g.items(), key=lambda x: (x[0][2], x[0][0], x[0][1])):
        db, sc, nm = split_name(o, k)
        p = ps[0]
        out.append(dict(privilege=pv, type=k, object=o, database=db, schema=sc, name=nm, cls=priv_class(pv, k),
                        holder=p[-2], granted=p[1] if user else p[0], direct=len(p) == 2 and not user,
                        depth=depth(p[:-1], user), path=p, paths=ps, count=len(ps)))
    return out


def reach(name, user=False, default_only=False, limit=None):
    """Roles a user or role reaches. Row: role, kind, depth (shortest, see depth()), direct (granted to name itself),
    path (shortest), paths, count."""
    g = group((p[-1], p) for p in walk(name, user, default_only, limit) if len(p) > 1)
    return [dict(role=r, kind=kind_of(r), depth=depth(ps[0], user), direct=len(ps[0]) == 2, path=ps[0], paths=ps,
                 count=len(ps)) for r, ps in sorted(g.items(), key=lambda x: (len(x[1][0]), x[0]))]


def holds_of(role):
    """Role page, holds (down): the role's own grants. Row: privilege, type, object, database, schema, name, cls."""
    out = []
    for pv, k, o in sorted(granted.get(role, []), key=lambda x: (x[2], x[0])):
        db, sc, nm = split_name(o, k)
        out.append(dict(privilege=pv, type=k, object=o, database=db, schema=sc, name=nm, cls=priv_class(pv, k)))
    return out


def held(role, limit=None):
    """Role page, held by (up). Row: grantee, kind, depth (roles from the grantee to this role, both included;
    a user holding it directly = 1, a role holding it directly = 2), direct, path (shortest, grantee->...->role),
    paths, count, only_via (roles every path passes through: revoking one of them removes it)."""
    g = group((p[-1], p[::-1]) for p in list(up([role], limit))[1:])
    out = []
    for x, ps in sorted(g.items(), key=lambda x: (len(x[1][0]), x[0])):
        d = depth(ps[0], from_user(ps[0]))
        if limit is None or d <= limit:
            out.append(dict(grantee=x, kind=kind_of(x), depth=d, direct=len(ps[0]) == 2, path=ps[0], paths=ps,
                            count=len(ps), only_via=[n for n in ps[0][1:-1] if all(n in p for p in ps)]))
    return out


def loses(user, grantee, role):
    """[(privilege, object)] user no longer reaches once role is revoked from grantee (every path uses that grant)."""
    g = group(((pv, o), p) for pv, k, o, p in access_of(user, True))
    return sorted(key for key, ps in g.items() if all((grantee, role) in zip(p, p[1:]) for p in ps))


def role_stats(role, limit=None):
    """Role page KPIs: kind, privileges, effective (privileges incl. inherited), future, above, above_direct, users,
    users_direct, farthest (max depth), holds_roles (direct child roles), sensitive (sensitive objects read)."""
    h, own = held(role, limit), granted.get(role, [])
    above, us = [x for x in h if x["kind"] != "user"], [x for x in h if x["kind"] == "user"]
    return dict(kind=kind_of(role), privileges=len(own), effective=len(grants(role)),
                future=sum(k.startswith("FUTURE") for _, k, _ in own),
                above=len(above), above_direct=sum(x["direct"] for x in above),
                users=len(us), users_direct=sum(x["direct"] for x in us),
                farthest=max((x["depth"] for x in h), default=0), holds_roles=sorted(holds.get(role, [])),
                sensitive=len(set(reads([role])) & set(sensitive())))


def grantees(obj, kind=None, limit=None):
    """Object page, all grantees: one row per (grantee, privilege). Row: grantee, kind, privilege, cls,
    depth (see depth(): grant holder = 1, ANALYST_01 on TBL_CUSTOMER = 3), path (shortest, grantee->...->holder->object),
    paths, count."""
    g = group(((x, pv), p + [obj]) for x, pv, p in who_can(obj, kind, limit))
    k0 = kind or kinds.get(obj)
    return [dict(grantee=x, kind=kind_of(x), privilege=pv, cls=priv_class(pv, k0),
                 depth=depth(ps[0][:-1], from_user(ps[0])), path=ps[0], paths=ps, count=len(ps))
            for (x, pv), ps in sorted(g.items(), key=lambda x: (len(x[1][0]), x[0]))]


STANDARD = {"TABLE": {"SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES"}, "VIEW": {"SELECT", "REFERENCES"},
            "WAREHOUSE": {"USAGE", "OPERATE", "MONITOR"}, "PROCEDURE": {"USAGE"}, "FUNCTION": {"USAGE"}}


def valid_privs(kind):
    """Privileges that exist on objects of this type (in the data, plus the standard ones of the type, so My access
    can ask about one it lacks), common ones first; OWNERSHIP always."""
    order = ["OWNERSHIP", "SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "USAGE"]
    return sorted({pv for _, pv, k, _ in privs if k == kind} | STANDARD.get(kind, set()) | {"OWNERSHIP"},
                  key=lambda p: (order.index(p) if p in order else 99, p))


def admin_users():
    """Users holding an admin role: {user: [admin roles]}."""
    out = {}
    for x, p in admin_holders():
        if from_user(p) and p[-1] not in out.get(x, []):
            out.setdefault(x, []).append(p[-1])
    return out


def admin_people():
    """Users holding an admin role or an account-level privilege (MANAGE GRANTS, ...), service users included.
    Row: user, roles, paths (user->...->admin role), account [(privilege, path)], service, status, last_login, days."""
    ps = group((p[0], p) for x, p in admin_holders() if from_user(p))
    acct = {u: account_privs(u, True) for u in users}
    return [dict(user=u, roles=sorted({p[-1] for p in ps.get(u, [])}), paths=ps.get(u, []), account=acct[u],
                 service=is_service(u), status=status(u), last_login=(profile.get(u) or {}).get("LAST_SUCCESS_LOGIN"),
                 days=login_days(u))
            for u in sorted(set(ps) | {u for u, v in acct.items() if v})]


def title(pv, path):
    """Tooltip of a matrix tick: "INSERT via F_ENGINEER > T_SALES_CORE_WRITE"."""
    return f"{pv} via {' > '.join(path[1:-1])}"


def matrix(obj, kind=None, limit=None, priv=None):
    """Object page, effective access by user. Row: user, admin ([admin roles held]; admins inherit everything),
    status, service, privs {privilege: dict(has, owner (implied by OWNERSHIP), depth, count, title, path)} over
    the privileges of valid_privs(kind or the object's type) found in the data, via {cls: [granted roles]} ("Read via / Write via"), holders {cls: [grant
    holders]}.
    priv: only users who have it (or OWNERSHIP, which implies it). Users with a path first, then admin users."""
    k0 = kind or kinds.get(obj)
    cols = [c for c in valid_privs(k0) if c == "OWNERSHIP" or any(pv == c for _, pv, k, _ in privs if k == k0)]
    got = {}
    for r in grantees(obj, kind, limit):
        if r["kind"] == "user" and from_user(r["path"]):
            got.setdefault(r["grantee"], {})[r["privilege"]] = r
    adm, out = admin_users(), []
    for u, g in sorted(got.items()):
        if priv and priv not in g and "OWNERSHIP" not in g:
            continue
        own = "OWNERSHIP" in g
        cells = {}
        for c in cols:
            r = g.get(c)
            cells[c] = dict(has=r is not None, owner=r is None and own, depth=r["depth"] if r else None,
                            count=r["count"] if r else 0, path=r["path"] if r else None,
                            title=title(c, r["path"]) if r else "implied by OWNERSHIP" if own else "")
        via, hs = {}, {}
        for pv, r in g.items():
            via.setdefault(priv_class(pv, k0), set()).update(p[1] for p in r["paths"])
            hs.setdefault(priv_class(pv, k0), set()).update(p[-2] for p in r["paths"])
        out.append(dict(user=u, admin=adm.get(u, []), status=status(u), service=is_service(u), privs=cells,
                        via={c: sorted(v) for c, v in via.items()}, holders={c: sorted(v) for c, v in hs.items()}))
    empty = {c: dict(has=False, owner=False, depth=None, count=0, path=None, title="") for c in cols}
    return out + [dict(user=u, admin=a, status=status(u), service=is_service(u), privs=empty, via={}, holders={})
                  for u, a in sorted(adm.items()) if u not in got]


def object_stats(obj, kind=None, priv=None, limit=None):
    """Object page KPIs for priv (None = any; OWNERSHIP implies every privilege): users, admin_users (more users only
    through admin roles), people, disabled, service, admin (split_users), roles, direct (grant holders),
    owners (roles with an OWNERSHIP grant, whatever priv), deployers (users reaching OWNERSHIP, whatever priv),
    owner_note ("" | "no OWNERSHIP grant in snapshot" | "no user reaches it"), longest (max depth)."""
    every = grantees(obj, kind, limit)
    g = [r for r in every if priv in (None, r["privilege"])]
    has = {r["grantee"] for r in g if r["kind"] == "user" and from_user(r["path"])}
    owns = {r["grantee"] for r in every if r["privilege"] == "OWNERSHIP" and r["kind"] == "user" and from_user(r["path"])}
    us = has | (owns if priv else set())
    adm = admin_users()
    direct = {r for r, pv, k in on.get(obj, []) if kind in (None, k) and priv in (None, pv)}
    owners = sorted({r for r, pv, k in on.get(obj, []) if kind in (None, k) and pv == "OWNERSHIP"})
    return dict(users=len(us), admin_users=len(set(adm) - us), **split_users(us, adm),
                roles=len({r["grantee"] for r in g if r["kind"] != "user"}), direct=len(direct), owners=owners,
                deployers=sorted(owns),
                owner_note="" if owns else "no user reaches it" if owners else "no OWNERSHIP grant in snapshot",
                longest=max((r["depth"] for r in g), default=0))


# ---------- removal and requests ----------

def sql_name(n):
    """A role, user or column name for copy-paste SQL: plain upper-case names as they are, anything else quoted, so a
    crafted name can't add a statement."""
    return n if re.fullmatch(r"[A-Z_][A-Z0-9_$]*", n) else ident(n)


def sql_obj(o):
    """DB.SCHEMA.OBJECT for copy-paste SQL, each part through sql_name."""
    return ".".join(sql_name(p) for p in o.split(".", 2))


def role_edge(grantee, role, user=False):
    return dict(grantee=grantee, to=role, priv=None, kind=None, user=user)


def priv_edge(role, pv, k, obj):
    return dict(grantee=role, to=obj, priv=pv, kind=k, user=False)


def holder_edge(role, pv, obj):
    """The grant edge of pv on obj held by role itself."""
    return priv_edge(role, pv, next(k for p, k, o in granted[role] if p == pv and o == obj), obj)


def revoke(e, pvs=None):
    """(infrastructure-as-code text, equivalent SQL) to remove one grant edge; pvs: several privileges of the same role
    on the same object, in one statement. OWNERSHIP can't be revoked in Snowflake, only transferred."""
    g, x, k = e["grantee"], e["to"], e["kind"]
    if e["priv"] is None:
        who = "USER" if e["user"] else "ROLE"
        return (f"Remove in the infrastructure-as-code repo: role {x} granted to {who.lower()} {g}",
                f"REVOKE ROLE {sql_name(x)} FROM {who} {sql_name(g)};")
    pv = ", ".join(pvs or [e["priv"]])
    if k == "ACCOUNT":
        return (f"Remove in the infrastructure-as-code repo: {pv} on account granted to role {g}",
                f"REVOKE {pv} ON ACCOUNT FROM ROLE {sql_name(g)};")
    if k.startswith("FUTURE"):
        kk, where = k.replace("FUTURE ", "") + "S", x.rsplit(".", 1)[0]
        place = "SCHEMA " if "." in where else "DATABASE "
        return (f"Remove in the infrastructure-as-code repo: {pv} on future {kk.lower()} in {place.lower()}{where} "
                f"granted to role {g}", f"REVOKE {pv} ON FUTURE {kk} IN {place}{sql_obj(where)} FROM ROLE {sql_name(g)};")
    if pv == "OWNERSHIP":
        return (f"Transfer ownership in the infrastructure-as-code repo: {k.lower()} {x}, now owned by role {g}",
                f"GRANT OWNERSHIP ON {k} {sql_obj(x)} TO ROLE <new owner role> COPY CURRENT GRANTS;")
    return (f"Remove in the infrastructure-as-code repo: {pv} on {k.lower()} {x} granted to role {g}",
            f"REVOKE {pv} ON {k} {sql_obj(x)} FROM ROLE {sql_name(g)};")


def fix_text(edges):
    """(iac, sql) for several grant edges; the privileges of one role on one object go in one statement."""
    groups = {}
    for e in edges:
        key = (e["grantee"], e["to"], e["kind"], e["priv"] == "OWNERSHIP") if e["priv"] else (e["grantee"], e["to"])
        groups.setdefault(key, {})[e["priv"]] = e
    ts = [revoke(next(iter(es.values())), None if None in es else sorted(es)) for es in groups.values()]
    return "; ".join(t[0] for t in ts), " ".join(t[1] for t in ts)


def lose(e):
    """Users who lose something when grant edge e goes, net of their other paths: a role edge -> users who no longer
    reach the role; a privilege edge -> users who no longer hold that privilege on the object."""
    g, x = e["grantee"], e["to"]
    if e["priv"] is None:
        return {v for v in users_through(g) if all((g, x) in zip(p, p[1:]) for p in walk(v, True) if p[-1] == x)}
    return {v for v in users_through(g) if all(p[-1] == g for pv, k, o, p in access_of(v, True)
                                               if pv == e["priv"] and o == x)}


def losers(edges, priv, obj):
    """Users who no longer hold priv on obj once every edge in edges is cut (each of their paths uses one)."""
    gone = {(e["grantee"], e["to"]) for e in edges}
    us = set().union(*(users_through(e["grantee"]) for e in edges))
    return {v for v in us if all(gone & set(zip(p, p[1:] + [obj])) for pv, k, o, p in access_of(v, True)
                                 if pv == priv and o == obj)}


def removal(user, priv, obj):
    """Ways to remove priv on obj from user, fewest users losing it first, then closest to the user: one option per
    grant edge that every path uses (a choke point); when no single grant to the user cuts every path, one option
    revoking each granted role on a path (all needed). Option: edges, edge (first), iac, sql, affects (users who lose
    priv on obj, net of their other paths), users."""
    ps = [p + [obj] for pv, k, o, p in access_of(user, True) if pv == priv and o == obj]
    if not ps:
        return []
    pairs = [set(zip(p, p[1:])) for p in ps]
    out = []

    def option(edges, order):
        iac, sql = fix_text(edges)
        us = losers(edges, priv, obj)
        out.append(dict(edges=edges, edge=edges[0], iac=iac, sql=sql, affects=len(us), users=sorted(us), order=order))

    for i, (x, y) in enumerate(zip(ps[0], ps[0][1:])):
        if y == "PUBLIC" or not all((x, y) in s for s in pairs):  # every user holds PUBLIC: not revocable
            continue
        option([holder_edge(x, priv, obj) if y == obj else role_edge(x, y, i == 0)], i)
    firsts = list(dict.fromkeys(p[1] for p in ps))
    if not any(o["order"] == 0 for o in out) and "PUBLIC" not in firsts:
        option([role_edge(user, r, True) for r in firsts], -1)
    return sorted(out, key=lambda r: (r["affects"], r["order"]))


def reaches_admin(role):
    return any(r in ADMIN for r in bfs([role]))


def ask_for(priv, obj):
    """Functional roles that reach priv on obj, fewest effective privileges first, then the closest to the grant:
    [dict(role, privileges, path)]. Build roles (BUILD) and roles that reach an admin role are never suggested."""
    out = {}
    for x, pv, p in who_can(obj):
        if (pv == priv and kind_of(x) == "functional" and (x not in out or len(p) < len(out[x]))
                and not any(fnmatch.fnmatch(x, b) for b in BUILD) and not reaches_admin(x)):
            out[x] = p + [obj]
    return sorted((dict(role=r, privileges=sum(len(granted.get(y, [])) for y in bfs([r])), path=p)
                   for r, p in out.items()), key=lambda r: (r["privileges"], len(r["path"]), r["role"]))


def can(user, priv, obj, default_only=False):
    """Can they? page. Returns dict:
    paths: [dict(path user->...->holder->object, depth, holder, how)], shortest first;
    shortest: depth or None; choke: roles on every path, in shortest-path order; owner: paths to OWNERSHIP when
    priv is another privilege (OWNERSHIP implies it: "Yes, via ownership"); options: removal(); ask: ask_for() when
    there is no path; use_role, warehouse: what to run with; status: user status; closest: when no path, the shortest
    chain grantee->...->holder->object holding priv on obj (from a user if any, else from a role), else None."""
    dr = (profile.get(user) or {}).get("DEFAULT_ROLE")
    acc = access_of(user, True, default_only)
    ps = sorted((p + [obj] for pv, k, o, p in acc if pv == priv and o == obj), key=len)
    rows = []
    for p in ps:
        how = f"direct grant on {p[-2]}"
        if len(p) > 3 and p[-3].startswith(TECH):
            how = f"inherited through technical role {p[-3]}"
        if dr not in p[1:-1]:
            how += ", via secondary role"
        rows.append(dict(path=p, depth=len(p) - 2, holder=p[-2], how=how))
    owner = [] if priv == "OWNERSHIP" else sorted((p + [obj] for pv, k, o, p in acc if pv == "OWNERSHIP" and o == obj),
                                                  key=len)
    choke = [r for r in ps[0][1:-1] if all(r in p for p in ps)] if ps else []
    closest = None
    if not ps:
        ups = sorted((p[::-1] + [obj] for r, pv, k in on.get(obj, []) if pv == priv for p in up([r])), key=len)
        closest = next((p for p in ups if from_user(p)), ups[0] if ups else None)
    whs = sorted({o for pv, k, o, p in acc if k == "WAREHOUSE" and pv in ("USAGE", "OWNERSHIP")})
    wh = (profile.get(user) or {}).get("DEFAULT_WAREHOUSE")
    best = ps or owner
    return dict(paths=rows, shortest=rows[0]["depth"] if rows else None, choke=choke, closest=closest, owner=owner,
                options=removal(user, priv, obj), ask=[] if best else ask_for(priv, obj),
                use_role=best[0][1] if best else None, warehouse=wh if wh in whs else (whs[0] if whs else None),
                status=status(user))


def review(db=None):
    """Access review export for one database (None: every database): one row per (user, object) with any privilege,
    then one row per admin user. Row: database, schema, object, type, user, user_type, status, last_login, privileges, classes, sensitive
    (tags), granted (depth-1 roles), path (shortest), reviewer, decision (blank, for sign-off)."""
    out, adm = [], admin_users()
    for o in objects:
        d, sc, nm = split_name(o)
        if not d or db not in (None, d):
            continue
        got = group(((x, pv), p) for x, pv, p in who_can(o) if from_user(p))
        per = {}
        for (x, pv), ps in got.items():
            per.setdefault(x, []).append((pv, ps))
        for x, v in sorted(per.items()):
            ps = sorted((p for _, pp in v for p in pp), key=len)
            out.append(dict(database=d, schema=sc, object=nm, type=kinds.get(o), user=x,
                            user_type=(profile.get(x) or {}).get("TYPE") or "PERSON", status=status(x),
                            last_login=(profile.get(x) or {}).get("LAST_SUCCESS_LOGIN"),
                            privileges=", ".join(sorted(pv for pv, _ in v)),
                            classes=", ".join(sorted({priv_class(pv, kinds.get(o)) for pv, _ in v})),
                            sensitive=", ".join(sorted({tag_label(t, val) for _, t, val, _ in sens.get(o, [])})),
                            granted=", ".join(sorted({p[1] for p in ps})), path=" > ".join(ps[0] + [o]),
                            reviewer="", decision=""))
    for u, rs in sorted(adm.items()):
        out.append(dict(database=db or "(every database)", schema="", object="(every object, through an admin role)",
                        type="", user=u,
                        user_type=(profile.get(u) or {}).get("TYPE") or "PERSON", status=status(u),
                        last_login=(profile.get(u) or {}).get("LAST_SUCCESS_LOGIN"), privileges="ALL", classes="own",
                        sensitive="", granted=", ".join(rs), path="", reviewer="", decision=""))
    return out


def search(q, names):
    """Search ranking: substring matches first (prefix, then earlier position, then shorter); fuzzy matches only
    when nothing contains q."""
    q = q.strip().upper()
    if not q:
        return list(names)
    hits = [n for n in names if q in n.upper()]
    if hits:
        return sorted(hits, key=lambda n: (n.upper().find(q) != 0, n.upper().find(q), len(n), n))
    return difflib.get_close_matches(q, list(names), n=10, cutoff=0.6)


# ---------- rules ----------

def plural(n, word):
    return f"{n} {word}{'s' * (n != 1)}"


def rule_rows():
    """Rule checks page. Row: rule ("1 ..."), num, title, why, severity (SEVERITY), grantee, kind, detail, path,
    paths, iac, sql (fix texts, "" when no SQL fits), affects (users who lose something when the fix is applied, net of
    their other paths; None when the fix revokes nothing), impact (affects as text: "3 users lose it", "5 readers
    exposed", "—"), same_fix (rule label of an earlier finding with the same fix), edges (grant edges the fix removes)."""
    out, seen = [], {}
    for f in cached("findings", findings):
        iac, sql = f.get("fix") or fix_text(f["edges"])
        n, t = f["num"], RULES[f["num"]][0]
        affects, impact = f.get("affects"), f.get("impact")
        if f["edges"]:
            affects = len(set().union(*(lose(e) for e in f["edges"])))
            impact = plural(affects, "user") + " lose" + "s" * (affects == 1) + " access"
        out.append(dict(rule=f"{n} {t}", num=n, title=t, why=RULES[n][1], severity=SEVERITY.get(n, "Low"),
                        grantee=f["grantee"], kind=kind_of(f["grantee"]), detail=f["detail"], path=f["path"],
                        paths=f.get("paths", [f["path"]]), edges=f["edges"], iac=iac, sql=sql, affects=affects,
                        impact=impact or "—", same_fix=seen.get(sql, "") if sql else ""))
        if sql:
            seen.setdefault(sql, f"Rule {n}")
    return out


def checks():
    """Rules broken by the grants: rows (num, title, grantee, detail, path)."""
    return [(f["num"], RULES[f["num"]][0], f["grantee"], f["detail"], f["path"]) for f in findings()]


def find(num, grantee, detail, path, edges=(), **kw):
    uniq = [dict(t) for t in dict.fromkeys(tuple(e.items()) for e in edges)]
    return dict(num=num, grantee=grantee, detail=detail, path=path, edges=uniq, **kw)


def is_build(r):
    return any(fnmatch.fnmatch(r, b) for b in BUILD)


def readonly_writes(role=None):
    """Rule 17, read-only roles that can write (role=None: every role but admin and BUILD roles).
    name heuristic: READ_ROLE_PATTERNS -> any write/own privilege; _EXECUTE -> write/own; _WRITE -> OWNERSHIP.
    behaviour heuristic: share of data objects it can only read >= READ_SHARE over >= READ_MIN_OBJECTS objects,
    but it writes/owns some. Row per (role, object): role, object, privileges, holder, path (role->...->holder->object),
    via {privilege: path role->...->holder}, inherited (holder is another role), how (name | behaviour | both),
    read_only, objects (counts for behaviour)."""
    out = []
    for r in [role] if role else roles:
        if r in ADMIN or r == "PUBLIC" or is_build(r):
            continue
        eff = [(pv, k, o, p) for x, p in bfs([r]).items() for pv, k, o in granted.get(x, [])]
        bad = {"own"} if r.upper().endswith("_WRITE") else \
            {"write", "own"} if READ_ROLE_PATTERNS.search(r) or r.upper().endswith("_EXECUTE") else set()
        by_name = {(pv, o): p for pv, k, o, p in eff if priv_class(pv, k) in bad}
        cls = {}
        for pv, k, o, p in eff:
            if is_data(k) and priv_class(pv, k) in ("read", "write", "own"):
                cls.setdefault(o, set()).add(priv_class(pv, k))
        ro = [o for o, c in cls.items() if c == {"read"}]
        stray = {o for o, c in cls.items() if c & {"write", "own"}}
        beh = len(cls) >= READ_MIN_OBJECTS and stray and len(ro) / len(cls) >= READ_SHARE
        by_beh = {(pv, o): p for pv, k, o, p in eff if beh and o in stray and priv_class(pv, k) in ("write", "own")}
        per = {}
        for (pv, o), p in (by_name | by_beh).items():
            per.setdefault(o, []).append((pv, p))
        for o, v in sorted(per.items()):
            p = min((p for _, p in v), key=len)
            n, b = any((pv, o) in by_name for pv, _ in v), any((pv, o) in by_beh for pv, _ in v)
            out.append(dict(role=r, object=o, privileges=sorted({pv for pv, _ in v}), holder=p[-1], path=p + [o],
                            via=dict(sorted(v)), inherited=p[-1] != r, how="both" if n and b else "name" if n else
                            "behaviour", read_only=len(ro), objects=len(cls)))
    return out


def rules_model():
    """Rules 1-4, 13, 14: the layered role model."""
    out = []
    for role, user in user_grants:
        if role.startswith(TECH):
            out.append(find("1", user, role, [user, role], [role_edge(user, role, True)]))
    for child, parent in role_grants:
        if child.startswith(TECH) and not parent.startswith((FUNC, TECH)) and parent not in ADMIN:  # group role
            out.append(find("1", parent, child, [parent, child], [role_edge(parent, child)]))
    for r, pv, k, o in privs:
        if r.startswith(FUNC):
            out.append(find("2", r, f"{pv} on ACCOUNT" if k == "ACCOUNT" else f"{pv} on {k} {o}", [r, o],
                            [priv_edge(r, pv, k, o)]))
    # rule 3 without parsing DB/schema from names: a consumer holds a technical ..._READ role directly and also through
    # another role it holds (READ inside WRITE); technical-to-technical links are the model's own, so not checked
    consumers = list(roles_of.items()) + [(g, h) for g, h in holds.items() if not g.startswith(TECH)]
    for g, direct in consumers:
        for d in direct:
            for p in down([d]):
                if len(p) > 1 and p[-1] in direct and p[-1].startswith(TECH) and p[-1].endswith("_READ"):
                    out.append(find("3", g, p[-1], [g] + p, [role_edge(g, p[-1], g in roles_of and g not in roles)],
                                    paths=[[g, p[-1]], [g] + p]))
    for r in roles:
        if r.startswith(TECH) and r.endswith("_OWNER"):
            for g in users_of.get(r, []):
                out.append(find("4", g, r, [g, r], [role_edge(g, r, True)]))
            for g in held_by.get(r, []):
                if not g.startswith(TECH) and not is_build(g):
                    out.append(find("4", g, r, [g, r], [role_edge(g, r)]))
    for r in roles:  # 13; technical roles without holders are the model's unused capability roles, by design
        if kind_of(r) in ("functional", "group") and r != "PUBLIC" and not users_of.get(r) and not held_by.get(r):
            kids = sorted(holds.get(r, []))
            out.append(find("13", r, f"holds {plural(len(kids), 'role')}" + (f": {', '.join(kids)}" if kids else "")
                            + f"; {plural(len(granted.get(r, [])), 'privilege')} of its own", [r],
                            fix=(f"Remove in the infrastructure-as-code repo: role {r}", f"DROP ROLE {sql_name(r)};")))
    for r in sorted(users_of):  # 14: per role granted to users, the deepest grant it leads to
        deep = max(((len(p), pv, o, p, is_data(k)) for x, p in bfs([r]).items() for pv, k, o in granted.get(x, [])),
                   default=None, key=lambda t: (t[0], t[4]))
        if deep and deep[0] > MAX_DEPTH_RULE:
            out.append(find("14", r, f"{deep[0]} roles deep to {deep[1]} on {deep[2]}; held by "
                                     f"{len(users_of[r])} users", deep[3] + [deep[2]],
                            fix=("Shorten the chain in the infrastructure-as-code repo", "")))
    return out


def rules_admin():
    """Rules 5, 9, 12: admin roles, PUBLIC, admin default roles."""
    out = []
    for u in users:
        if not is_service(u):
            out += [find("5", u, p[-1], p, [role_edge(p[-2], p[-1], len(p) == 2)]) for p in admin_paths(u, user=True)]
    for r, pv, k, o in privs:
        if r == "PUBLIC":
            out.append(find("9", r, f"{pv} on {k} {o}", [r, o], [priv_edge(r, pv, k, o)]))
    for child, parent in role_grants:
        if parent == "PUBLIC":
            out.append(find("9", parent, f"role {child}", [parent, child], [role_edge(parent, child)]))
    for u in users:
        dr = (profile.get(u) or {}).get("DEFAULT_ROLE")
        if dr in ADMIN:
            out.append(find("12", u, f"default role {dr}", [u, dr], affects=1, impact="1 user", fix=(f"Change in the infrastructure-as-code repo: default role of "
                                                          f"user {u}", f"ALTER USER {sql_name(u)} SET DEFAULT_ROLE = "
                                                                       "<functional role>;")))
    return out


def rules_sensitive():
    """Rules 6, 7, 10, 11, 15: sensitive data."""
    out, s = [], sensitive()
    for o in s:  # 6
        ps = policies_of(o)["columns"]
        for c in sensitive_cols(o):
            if c not in ps:
                k = "VIEW" if "VIEW" in (kinds.get(o) or "") else "TABLE"
                n = len(readers(o))
                out.append(find("6", o, f"column {c}: " + ", ".join(tag_label(t, v) for cc, t, v, _ in s[o] if cc == c),
                                [o], affects=n, impact=f"{plural(n, 'reader')} see it in clear",
                                fix=(f"Add in the infrastructure-as-code repo: a masking policy on {o}.{c}",
                                     f"ALTER {k} {sql_obj(o)} MODIFY COLUMN {sql_name(c)} SET MASKING POLICY <policy>;")))
    wc = {o: who_can(o) for o in s}
    read_by = {o: {x for x, pv, p in wc[o] if pv in READ_PRIVS and from_user(p)} for o in s}
    for u in users:  # 7
        if is_service(u):
            continue
        objs = sorted(o for o, us in read_by.items() if u in us)
        if objs and (is_dormant(u) or is_disabled(u)):
            d = login_days(u)
            why = ("disabled; " if is_disabled(u) else "") + ("never logged in" if d is None else f"last login {d} days ago")
            out.append(find("7", u, f"{why}; reads {len(objs)} sensitive: {', '.join(objs)}", [u],
                            [role_edge(u, r, True) for r in roles_of.get(u, [])]))
    for u in users:  # 10: one finding per person; the fix revokes every write grant it uses, on the holder
        if is_service(u):
            continue
        got = {}
        for o in s:
            for x, pv, p in wc[o]:
                if x == u and from_user(p) and priv_class(pv, kinds.get(o)) in ("write", "own"):
                    got.setdefault(o, []).append((pv, p))
        if got:
            v = {o: sorted({pv for pv, _ in x}) for o, x in sorted(got.items())}
            edges = [holder_edge(p[-1], pv, o) for o, x in sorted(got.items()) for pv, p in x]
            o0 = next(iter(v))
            out.append(find("10", u, "; ".join(f"{', '.join(pv)} on {o}" for o, pv in v.items()),
                            min((p for _, p in got[o0]), key=len) + [o0], edges))
    for r in roles:  # 11: the fix cuts every held role (and own grant) that leads to sensitive data
        if kind_of(r) == "group":
            got = reads([r])
            objs = sorted(set(got) & set(s))
            if objs:
                edges = [role_edge(r, c) for c in sorted(holds.get(r, [])) if set(reads([c])) & set(s)]
                edges += [priv_edge(r, pv, k, o) for pv, k, o in granted.get(r, []) if o in s and pv in READ_PRIVS]
                out.append(find("11", r, f"reads {len(objs)} sensitive: {', '.join(objs)}; {len(users_through(r))} "
                                         "users", got[objs[0]], edges))
    for r, pv, k, o in privs:  # 15
        if k.startswith("FUTURE"):
            where = o.rsplit(".", 1)[0]
            hit = sorted(x for x in s if x.startswith(where + "."))
            if hit:
                out.append(find("15", r, f"{pv} on {k.lower()}s in {where}; sensitive: "
                                         f"{', '.join(hit)}", [r, o], [priv_edge(r, pv, k, o)]))
    return out


def rules_users():
    """Rules 8, 16: disabled and dormant users that still hold roles (rule 16 leaves disabled ones to rule 8)."""
    out = []
    for u in users:
        if is_disabled(u) and roles_of.get(u):
            out.append(find("8", u, "holds " + ", ".join(roles_of[u]), [u],
                            [role_edge(u, r, True) for r in roles_of[u]]))
    for u in users:
        if not is_service(u) and not is_disabled(u) and roles_of.get(u) and is_dormant(u):
            d = login_days(u)
            out.append(find("16", u, ("never logged in" if d is None else f"last login {d} days ago") + "; holds "
                            + ", ".join(roles_of[u]), [u], [role_edge(u, r, True) for r in roles_of[u]]))
    return out


def rule17():
    """Rule 17: read-only roles that can write. An inherited write on a role flagged by its name only, that is not
    mostly read either, gets a review hint instead of SQL (the name may just be a team name)."""
    out = []
    for x in cached("ro", readonly_writes):
        r, p = x["role"], x["path"]
        mostly = f"mostly read: {x['read_only']} of {x['objects']} objects read-only; " if x["how"] != "name" else ""
        src = f"via {x['holder']} (inherited)" if x["inherited"] else "direct"
        edges = [holder_edge(r, pv, x["object"]) if q[-1] == r else role_edge(r, q[1]) for pv, q in x["via"].items()]
        kw = {}
        if x["how"] == "name" and x["inherited"] and (not x["objects"] or x["read_only"] / x["objects"] < READ_SHARE):
            kw = dict(fix=(f"Check what {r} is for; if it is read-only, remove the write role it inherits in the "
                           "infrastructure-as-code repo", ""))
            edges = []
        out.append(find("17", r, f"{mostly}{', '.join(x['privileges'])} on {x['object']} {src}; heuristic: {x['how']}",
                        p, edges, **kw))
    return out


def findings():
    """Every rule finding, in rule order: dict(num, grantee, detail, path, edges [grant edges the fix removes], fix,
    paths, affects, impact)."""
    out = rules_model() + rules_admin() + rules_sensitive() + rules_users() + rule17()
    return sorted(out, key=lambda f: int(f["num"]))


LOADED = os.path.getmtime(__file__)  # app.fresh() reloads this module when the file is newer
