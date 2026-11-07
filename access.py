"""Snowflake grants + recursive access lookups and rule checks. No Streamlit import, so it can be tested alone.

Data: fake() (layered RBAC model), snapshot() (the TBL_ACCESS_ tables filled by SP_ACCESS_SNAPSHOT, sql/1_setup.sql)
or mine() (the logged-in user's own access, live). All return the same dict; build() turns it into the lookups below.
"""
import difflib
import fnmatch
import functools
import json
import os
import pathlib
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timedelta

# .env (template .env.example) fills in what the environment lacks: no file, a missing name or an empty value
# leaves the environment variable (or the default) in place, and a variable set in the shell wins.
ENV = pathlib.Path(__file__).with_name(".env")
for line in ENV.read_text(encoding="utf-8-sig").splitlines() if ENV.is_file() else []:
    k, _, v = line.partition("=")
    k, v = k.strip(), v.strip().strip("\"'")
    if k and v and not k.startswith("#"):
        os.environ.setdefault(k, v)
# Streamlit in Snowflake: no account variable there (the app uses its own session, with the owner's rights)
INSIDE = "SNOWFLAKE_ACCOUNT" not in os.environ and os.environ.get("FAKE") != "1"

ADMIN = {"ACCOUNTADMIN", "SECURITYADMIN", "SYSADMIN", "USERADMIN", "ORGADMIN"}
# account privileges Snowflake grants to PUBLIC by default (plus the SNOWFLAKE.* database roles): not rule 9
DEFAULT_PUBLIC = set(os.environ.get("DEFAULT_PUBLIC",
                                    "VIEW LINEAGE,USE AI FUNCTIONS,INGEST LINEAGE,BIND SERVICE ENDPOINT").split(","))
# Snowflake's own roles and objects every account gets through PUBLIC (fnmatch on the name): the SNOWFLAKE.* database
# roles and application role, system compute pools and warehouses, the learning role / warehouse / database. Their
# grants are hidden by default (build(builtin=False)): no counts, one fold box in graphs, never rule 9 or 13
BUILTIN = os.environ.get("BUILTIN", "SNOWFLAKE.*,SYSTEM_COMPUTE_POOL_*,SYSTEM$*,SNOWFLAKE_LEARNING_*").split(",")
BUILTIN_RE = re.compile("|".join(fnmatch.translate(b) for b in BUILTIN))
BUILTIN_NODE = "Snowflake built-in (via PUBLIC)"
MAX_HOPS = int(os.environ.get("MAX_HOPS", "50"))  # safety cap on role hops per walk
# functional and technical role prefixes; another naming: ROLE_PREFIXES=<functional>,<technical>
FUNC, TECH = os.environ.get("ROLE_PREFIXES", "F_,T_").split(",")
# may hold OWNER roles (rule 4): the build identity; fnmatch patterns, e.g. BUILD_ROLES=F_DEPLOY,F_*_STEWARD
BUILD = os.environ.get("BUILD_ROLES", FUNC + "DEPLOY").split(",")
TABLES = ["GRANT", "USER_ROLE", "USER", "USAGE", "TAG", "POLICY", "STREAM"]
OPTIONAL = ["OBJECT_USE"]  # snapshot tables an older setup may lack: read when there, else empty
USE_DAYS = int(os.environ.get("USE_DAYS", "180"))  # object usage read from ACCESS_HISTORY (Granted vs used)
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
MAX_PATHS = int(os.environ.get("MAX_PATHS", "200"))  # full chains listed per row; counts are always exact
# rule 18: standard privileges per capability suffix (<TECH>..._READ, ...), JSON {"READ": [...], ...}
_READ = ["SELECT", "REFERENCES", "USAGE", "READ"]  # READ / WRITE: the privileges of an internal stage
CAP_PRIVS = {k: set(v) for k, v in json.loads(os.environ.get("CAP_PRIVS") or json.dumps({
    "READ": _READ, "WRITE": _READ + ["INSERT", "UPDATE", "DELETE", "TRUNCATE", "WRITE"], "EXECUTE": ["USAGE"],
    "OWNER": ["OWNERSHIP"]})).items()}
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
    "18": ("Unusual privilege set", "The role holds more or fewer privileges than its capability (READ, WRITE, ...) "
                                    "stands for, so its name no longer tells what it can do."),
    "19": ("EXECUTE TASK held by a person or consumer role", "Running tasks belongs to the build or a service user."),
    "20": ("OPERATE on a task outside owner/build roles", "The task runs with its owner's privileges, so whoever can "
                                                          "start or resume it borrows them."),
    "21": ("Warehouse MODIFY or OPERATE outside owner/build roles", "Resizing, suspending or resuming a warehouse "
                                                                     "changes cost and availability for everyone."),
    "22": ("Stream on sensitive table readable without the table", "A stream returns the table's changed rows, so it "
                                                                    "leaks data its reader cannot read in the table."),
    "23": ("CREATE privilege on a schema held by a read-only role", "A read-only role that can create objects can "
                                                                     "copy data or change the schema."),
}
SEVERITY = {"1": "Medium", "2": "Medium", "3": "Low", "4": "High", "5": "High", "6": "Medium", "7": "High", "8": "Low",
            "9": "High", "10": "Medium", "11": "Low", "12": "High", "13": "Low", "14": "Low", "15": "Medium",
            "16": "Medium", "17": "High", "18": "Low", "19": "Medium", "20": "High", "21": "Medium", "22": "High",
            "23": "High"}  # rule number -> severity, edit freely

# ---------- fake data: users -> group role -> functional roles -> technical roles -> objects ----------

SCHEMAS = {
    "SALES": {"RAW": ["TBL_ORDER_RAW"], "CLEAN": ["TBL_ORDER"],
              "CORE": ["TBL_CUSTOMER", "SP_LOAD_CUSTOMER"], "MART": ["VW_CUSTOMER"],
              "PIPELINE": ["TSK_LOAD_CUSTOMER", "STR_CUSTOMER", "STG_LANDING", "FN_MASK_EMAIL", "SEQ_ORDER_ID",
                           "PIPE_ORDER_RAW", "DT_CUSTOMER_DAILY", "TBL_CUSTOMER_CHANGES"]},
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
        return {"TBL": "TABLE", "VW": "VIEW", "SP": "PROCEDURE", "TSK": "TASK", "STR": "STREAM", "STG": "STAGE",
                "FN": "FUNCTION", "SEQ": "SEQUENCE", "PIPE": "PIPE", "DT": "DYNAMIC TABLE"}[obj.split("_")[0]]

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
                if k in ("TABLE", "VIEW", "STREAM", "DYNAMIC TABLE"):
                    pv.append((f"{base}_READ", "SELECT", k, name))
                if k in ("STAGE", "SEQUENCE"):
                    pv.append((f"{base}_READ", "USAGE", k, name))
                if k == "TABLE":  # fake: partial write set on TBL_CUSTOMER_CHANGES (rule 18, has / lacks)
                    pv += [(f"{base}_WRITE", p, k, name) for p in ("INSERT", "UPDATE", "DELETE", "TRUNCATE")
                           if not (o == "TBL_CUSTOMER_CHANGES" and p in ("DELETE", "TRUNCATE"))]
                if k in ("PROCEDURE", "FUNCTION"):
                    pv.append((f"{base}_EXECUTE", "USAGE", k, name))
    pv += [(f"{T}SALES_CORE_READ", "SELECT", "FUTURE TABLE", "SALES.CORE.<TABLE>"),
           (f"{T}SHARED_STAGE_READ", "USAGE", "SCHEMA", "SHARED.STAGE"),  # schema not modelled above
           (f"{F}SECURITY", "MANAGE GRANTS", "ACCOUNT", "ACCOUNT"),  # fake: account privilege on a functional role
           (f"{F}ANALYST", "USAGE", "WAREHOUSE", "WH_SALES_XS"),  # fake: direct privilege on a functional role
           ("PUBLIC", "USAGE", "WAREHOUSE", "WH_SALES_XS"),  # fake: grant to PUBLIC (rule 9)
           ("PUBLIC", "VIEW LINEAGE", "ACCOUNT", "ACCOUNT"),  # Snowflake's default on PUBLIC: no rule 9
           (f"{T}SHARED_LOGGING_READ", "INSERT", "TABLE", "SHARED.LOGGING.TBL_LOGGING"),  # fake: READ role writes (17)
           (f"{T}SALES_CORE_WRITE", "CREATE TABLE", "SCHEMA", "SALES.CORE"),
           (f"{T}FINANCE_REPORT_READ", "CREATE VIEW", "SCHEMA", "FINANCE.REPORT"),  # fake: read-only role creates (23)
           (f"{T}WAREHOUSE_OWNER", "OWNERSHIP", "WAREHOUSE", "WH_SALES_XS"),
           (f"{T}WAREHOUSE_OWNER", "OWNERSHIP", "WAREHOUSE", "WH_FINANCE_XS"),
           (f"{T}WAREHOUSE_OWNER", "MODIFY", "WAREHOUSE", "WH_FINANCE_XS"),
           (f"{T}SHARED_MONITORING_EXECUTE", "MONITOR", "WAREHOUSE", "WH_SALES_XS"),
           (f"{T}SALES_CORE_EXECUTE", "OPERATE", "WAREHOUSE", "WH_SALES_XS"),  # fake: not the owner (21)
           (f"{T}SALES_PIPELINE_EXECUTE", "OPERATE", "TASK", "SALES.PIPELINE.TSK_LOAD_CUSTOMER"),  # fake: (18, 20)
           (f"{T}SALES_PIPELINE_EXECUTE", "EXECUTE TASK", "ACCOUNT", "ACCOUNT")]  # fake: reaches a person (19)
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
        (f"{T}SALES_PIPELINE_EXECUTE", f"{F}ENGINEER"),
        (f"{T}SALES_PIPELINE_READ", f"{F}SUPPORT"),  # fake: reads the stream, not its sensitive table (22)
        (f"{T}WAREHOUSE_OWNER", f"{F}DEPLOY"),
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
        (f"{F}SUPPORT", "SUPPORT_01"),
    ]
    ur += [(CHAIN[0], u) for u in FIN_USERS]
    # database roles (DB.ROLE): hold grants inside their database, held by account roles like any role; schema
    # HR.PEOPLE is reachable only through them. SC_W holds SC_R; F_ENGINEER holds SC_W
    pv += [("HR.SC_R_PEOPLE", p, k, o) for p, k, o in [("USAGE", "DATABASE", "HR"), ("USAGE", "SCHEMA", "HR.PEOPLE"),
                                                         ("SELECT", "TABLE", "HR.PEOPLE.TBL_EMPLOYEE")]]
    pv += [("HR.SC_W_PEOPLE", p, "TABLE", "HR.PEOPLE.TBL_EMPLOYEE") for p in ("INSERT", "UPDATE")]
    dbr = [("HR.SC_R_PEOPLE", "HR.SC_W_PEOPLE"), ("HR.SC_W_PEOPLE", f"{F}ENGINEER")]
    # HR_01 reads 15 objects of one schema through a database role: over MAX_OBJECTS, so its graph groups them
    # (by schema, and scoped to HR.PAYROLL by type: TABLE and VIEW boxes that open with ?otype=)
    pay = [f"HR.PAYROLL.TBL_PAY_{i:02}" for i in range(13)] + ["HR.PAYROLL.VW_PAY_MONTH", "HR.PAYROLL.VW_PAY_YEAR"]
    pv += [("HR.SC_R_PAYROLL", "USAGE", "DATABASE", "HR"), ("HR.SC_R_PAYROLL", "USAGE", "SCHEMA", "HR.PAYROLL")]
    pv += [("HR.SC_R_PAYROLL", "SELECT", "VIEW" if ".VW_" in o else "TABLE", o) for o in pay]
    dbr += [("HR.SC_R_PAYROLL", f"{F}HR")]
    ur += [(f"{F}HR", "HR_01")]
    # a database granted through database roles only: read / write / manage / create per schema (W holds R, M holds
    # W), 18 of them, held by two group roles (engineers: manage + create, readers: read)
    for sc in ("ODS", "STG", "CORE", "MART", "SANDBOX"):
        r, w, m, c = (f"DW.SC_{x}_{sc}" for x in "RWMC")
        caps = (r, w) if sc == "SANDBOX" else (r, w, m, c)
        pv += [(x, "USAGE", k, o) for x in caps for k, o in (("DATABASE", "DW"), ("SCHEMA", f"DW.{sc}"))]
        for i in range(1, 4):
            o = f"DW.{sc}.TBL_{sc}_{i:02}"
            pv += [(r, "SELECT", "TABLE", o)] + [(w, p, "TABLE", o) for p in ("INSERT", "UPDATE", "DELETE", "TRUNCATE")]
        dbr += [(r, w), (w, m)] if m in caps else [(r, w), (w, "GRP_DW_ENGINEERS")]
        dbr += [(r, "GRP_DW_READERS")] + [(x, "GRP_DW_ENGINEERS") for x in (m, c) if x in caps]
        pv += [(m, p, "SCHEMA", f"DW.{sc}") for p in ("MODIFY", "MONITOR") if m in caps]
        pv += [(c, p, "SCHEMA", f"DW.{sc}") for p in ("CREATE TABLE", "CREATE VIEW") if c in caps]
    ur += [("GRP_DW_ENGINEERS", "DW_DEV_01"), ("GRP_DW_READERS", "DW_BI_01"), ("GRP_DW_READERS", "DW_BI_02")]
    # Snowflake's own grants to PUBLIC (BUILTIN, hidden by default): system database roles reaching a few hundred
    # functions and views, the application role, system compute pools and warehouse, the learning role
    for r, sc, k, n in [("CORE_VIEWER", "CORE", "VIEW", 12), ("DATA_METRIC_USER", "CORE", "FUNCTION", 260),
                        ("CORTEX_USER", "CORTEX", "FUNCTION", 40), ("ML_USER", "ML", "FUNCTION", 20),
                        ("ALERT_VIEWER", "ALERT", "VIEW", 5), ("SPCS_VIEWER", "SPCS", "VIEW", 5)]:
        dbr.append((f"SNOWFLAKE.{r}", "PUBLIC"))
        pv += [(f"SNOWFLAKE.{r}", "USAGE", "DATABASE", "SNOWFLAKE"), (f"SNOWFLAKE.{r}", "USAGE", "SCHEMA", f"SNOWFLAKE.{sc}")]
        pv += [(f"SNOWFLAKE.{r}", "USAGE" if k == "FUNCTION" else "SELECT", k,
                f"SNOWFLAKE.{sc}.{'FN' if k == 'FUNCTION' else 'VW'}_{r}_{i:03}") for i in range(n)]
    pv += [("PUBLIC", "USAGE", "APPLICATION_ROLE", "SNOWFLAKE.PUBLIC"),
           ("PUBLIC", "USAGE", "COMPUTE_POOL", "SYSTEM_COMPUTE_POOL_CPU"),
           ("PUBLIC", "USAGE", "COMPUTE_POOL", "SYSTEM_COMPUTE_POOL_GPU"),
           ("PUBLIC", "USAGE", "WAREHOUSE", "SYSTEM$STREAMLIT_NOTEBOOK_WH"),
           ("SNOWFLAKE_LEARNING_ROLE", "USAGE", "WAREHOUSE", "SNOWFLAKE_LEARNING_WH"),
           ("SNOWFLAKE_LEARNING_ROLE", "USAGE", "DATABASE", "SNOWFLAKE_LEARNING_DB")]
    rg.append(("SNOWFLAKE_LEARNING_ROLE", "PUBLIC"))
    grants = [dict(GRANTEE_ROLE=p, PRIVILEGE="USAGE", GRANTED_ON="ROLE", OBJECT_NAME=c, IS_FUTURE=False) for c, p in rg]
    grants += [dict(GRANTEE_ROLE=p, PRIVILEGE="USAGE", GRANTED_ON="DATABASE_ROLE", OBJECT_NAME=c, IS_FUTURE=False)
               for c, p in dbr]
    grants += [dict(GRANTEE_ROLE=r, PRIVILEGE=p, GRANTED_ON=k.replace("FUTURE ", ""), OBJECT_NAME=o,
                    IS_FUTURE=k.startswith("FUTURE")) for r, p, k, o in pv]
    for g in grants:  # fake: the deploy role granted the READ role its INSERT (What changed: "by")
        g["GRANTED_BY"] = F + "DEPLOY" if g["PRIVILEGE"] == "INSERT" and g["GRANTEE_ROLE"] == f"{T}SHARED_LOGGING_READ"             else "SECURITYADMIN"
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
                                   ("OPS_01", "PERSON", "SYSADMIN", '["ALL"]', None),
                                   ("SUPPORT_01", "PERSON", f"{F}SUPPORT", '["ALL"]', "WH_SALES_XS"),
                                   ("HR_01", "PERSON", f"{F}HR", '["ALL"]', None),
                                   ("DW_DEV_01", "PERSON", "GRP_DW_ENGINEERS", '["ALL"]', None),
                                   ("DW_BI_01", "PERSON", "GRP_DW_READERS", '["ALL"]', None),
                                   ("DW_BI_02", "PERSON", "GRP_DW_READERS", '["ALL"]', None)]
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
                ("SALES.RAW.TBL_ORDER_RAW", "TABLE", None, sens, "INTERNAL", "MANUAL"),  # tagged, not sensitive
                ("HR.PEOPLE", "SCHEMA", None, "SHARED.GOVERNANCE.OWNER", "HR data owner", "MANUAL")]]  # approver
    email = f"CASE WHEN IS_ROLE_IN_SESSION('{F}ENGINEER') THEN VAL ELSE '***MASKED***' END"
    policies = [dict(POLICY_NAME="SHARED.GOVERNANCE." + n, POLICY_KIND=k, OBJECT_NAME=o, COLUMN_NAME=c, ARG_COLUMNS=a,
                     TAG_NAME=t, POLICY_BODY=b) for n, k, o, c, a, t, b in [
        ("MP_EMAIL", "MASKING_POLICY", "SALES.CORE.TBL_CUSTOMER", "EMAIL", None, None, email),
        ("MP_EMAIL", "MASKING_POLICY", "SALES.MART.VW_CUSTOMER", "EMAIL", None, None, email),
        # never uses REGION: every role not listed sees no rows
        ("RAP_REGION", "ROW_ACCESS_POLICY", "FINANCE.REPORT.TBL_REVENUE", None, "REGION", None,
         f"IS_ROLE_IN_SESSION('{F}FINANCE') OR CURRENT_ROLE() = '{F}DEPLOY'"),
        ("RAP_ORDER_REGION", "ROW_ACCESS_POLICY", "SALES.CLEAN.TBL_ORDER", None, "REGION", None,  # really filters
         f"IS_ROLE_IN_SESSION('{F}DEPLOY') OR (CURRENT_ROLE() = '{F}MARKETING' AND REGION = 'EU')"),
        ("RAP_ORDER_MAP", "ROW_ACCESS_POLICY", "SALES.RAW.TBL_ORDER_RAW", None, "REGION", None,  # mapping table: unknown
         "EXISTS (SELECT 1 FROM SHARED.GOVERNANCE.TBL_REGION_MAP M WHERE M.ROLE_NAME = CURRENT_ROLE() "
         "AND M.REGION = REGION)"),
        ("MP_IP", "MASKING_POLICY", None, None, None, "SHARED.GOVERNANCE.NETWORK_DATA",  # on a tag nobody carries
         "CASE WHEN EXISTS (SELECT 1 FROM SHARED.GOVERNANCE.TBL_UNMASK U WHERE U.ROLE_NAME = CURRENT_ROLE()) "
         "THEN VAL ELSE '0.0.0.0' END")]]
    run = dict(RUN_ID="fake", FINISHED_AT="2026-11-02 07:00", SOURCES={}, NOTES={})
    streams = [dict(STREAM_NAME="SALES.PIPELINE.STR_CUSTOMER", SOURCE_NAME="SALES.CORE.TBL_CUSTOMER",
                    SOURCE_TYPE="Table")]
    return dict(run=run, GRANT=grants, USER_ROLE=[dict(USER_NAME=u, ROLE_NAME=r, GRANTED_BY="SECURITYADMIN") for r, u in ur],
                USER=users, USAGE=usage, TAG=tags, POLICY=policies, STREAM=streams, OBJECT_USE=fake_use(run["FINISHED_AT"]))


def fake_use(end):
    """Demo ACCESS_HISTORY, per user, object, week and READ / WRITE: some grants never used (Granted vs used: Trim),
    ENGINEER_01 read HR.PEOPLE.TBL_EMPLOYEE only 20+ weeks ago, ANALYST_02 (dormant) nothing since July."""
    w0 = monday(end)
    rd, wr = "READ", "WRITE"
    plan = [("ENGINEER_01", "SALES.CORE.TBL_CUSTOMER", rd, range(26)), ("ENGINEER_01", "SALES.CORE.TBL_CUSTOMER", wr, range(26)),
            ("ENGINEER_01", "SALES.MART.VW_CUSTOMER", rd, range(26)), ("ENGINEER_01", "SHARED.LOGGING.TBL_LOGGING", rd, range(0, 26, 2)),
            ("ENGINEER_01", "HR.PEOPLE.TBL_EMPLOYEE", rd, range(20, 25)),
            ("ANALYST_01", "SALES.CORE.TBL_CUSTOMER", rd, range(26)), ("ANALYST_01", "SALES.MART.VW_CUSTOMER", rd, range(26)),
            ("ANALYST_02", "SALES.MART.VW_CUSTOMER", rd, range(17, 26)),
            ("FIN_01", "FINANCE.REPORT.TBL_REVENUE", rd, range(26)), ("FIN_01", "FINANCE.REPORT.VW_REVENUE_MONTHLY", rd, range(0, 26, 3)),
            ("REPORT_01", "SALES.MART.VW_CUSTOMER", rd, range(26)), ("REPORT_01", "FINANCE.REPORT.TBL_REVENUE", rd, range(0, 12)),
            ("SVC_DEPLOY", "SALES.CORE.TBL_CUSTOMER", wr, range(26)), ("SVC_DEPLOY", "SALES.CLEAN.TBL_ORDER", wr, range(26)),
            ("SVC_DEPLOY", "SALES.RAW.TBL_ORDER_RAW", rd, range(26)), ("HR_01", "HR.PAYROLL.TBL_PAY_00", rd, range(26)),
            ("HR_01", "HR.PAYROLL.VW_PAY_MONTH", rd, range(0, 26, 4))]
    out = []
    for u, o, act, weeks in plan:
        for i in weeks:
            wk = w0 - timedelta(weeks=i)
            n = 1 + (i * 5 + len(o) + len(u)) % (9 if act == rd else 4)
            last = datetime.combine(wk, datetime.min.time()) + timedelta(days=min(4, (day(end) - wk).days), hours=6)
            out.append(dict(USER_NAME=u, OBJECT_NAME=o, WEEK=wk.isoformat(), ACTION=act, QUERIES=n,
                            LAST_USED=last.strftime("%Y-%m-%d %H:%M")))
    return out


def day(v):
    """A date from Snowflake (date / datetime) or text."""
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else date.fromisoformat(str(v).strip()[:10])


def monday(v):
    """Start (Monday) of the week of v: weeks are counted the same whatever WEEK_START the account uses."""
    d = day(v)
    return d - timedelta(days=d.weekday())


def fake_previous():
    """The demo's earlier snapshot (What changed): a week before fake(), GRP_ANALYSTS without F_ANALYST, the READ role
    without its INSERT, F_MARKETING still holding SALES.CORE write, F_ANALYST holding an OWNER role (rule 4, fixed
    since) and ANALYST_02 not dormant yet."""
    d, F, T = fake(), FUNC, TECH
    gone = {("GRP_ANALYSTS", "USAGE", F + "ANALYST"), (T + "SHARED_LOGGING_READ", "INSERT", "SHARED.LOGGING.TBL_LOGGING")}
    g = [x for x in d["GRANT"] if (x["GRANTEE_ROLE"], x["PRIVILEGE"], x["OBJECT_NAME"]) not in gone]
    g += [dict(GRANTEE_ROLE=r, PRIVILEGE="USAGE", GRANTED_ON="ROLE", OBJECT_NAME=c, IS_FUTURE=False, GRANTED_BY="SECURITYADMIN")
          for c, r in [(T + "SALES_CORE_WRITE", F + "MARKETING"), (T + "SALES_MART_OWNER", F + "ANALYST")]]
    us = [x | dict(LAST_SUCCESS_LOGIN="2026-10-20 10:05") if x["USER_NAME"] == "ANALYST_02" else x for x in d["USER"]]
    return d | dict(GRANT=g, USER=us, run=dict(d["run"], RUN_ID="fake-previous", FINISHED_AT="2026-10-26 07:00"),
                    OBJECT_USE=fake_use("2026-10-26 07:00"))


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
    for t in OPTIONAL:  # a setup from before the table: the screen that needs it says so
        try:
            d[t] = query(f"SELECT * FROM {where}.TBL_ACCESS_{t} WHERE RUN_ID = '{run['RUN_ID']}'")
        except Exception:
            d[t] = None
    return d | {"run": run}


def ident(name):
    return '"' + name.replace('"', '""') + '"'


def line(e):
    return " ".join(str(e).split())[:300]


def db_ident(name):
    """A database role's qualified name DB.ROLE (unquoted) -> "DB"."ROLE"."""
    return ".".join(ident(p) for p in name.split(".", 1))


def qualify(db, name):
    """A database role of db as DB.ROLE, whether SHOW gave it bare or qualified."""
    return name if name.startswith(db + ".") else f"{db}.{name}"


SHOW_THREADS = int(os.environ.get("SHOW_THREADS", "16"))  # SHOW statements sent at once (one per role is slow in a row)


def each(query, sqls):
    """query(sql) for every sql, SHOW_THREADS at a time, in order: the rows, or the exception of a failed one."""
    def one(sql):
        try:
            return query(sql)
        except Exception as e:
            return e
    sqls = list(sqls)
    if len(sqls) < 2 or SHOW_THREADS < 2:
        return [one(s) for s in sqls]
    with ThreadPoolExecutor(min(SHOW_THREADS, len(sqls))) as pool:
        return list(pool.map(one, sqls))


def held_db_roles(grants):
    """Database roles granted in these GRANT rows (USAGE on DATABASE_ROLE)."""
    return [g["OBJECT_NAME"] for g in grants if g["GRANTED_ON"] == "DATABASE_ROLE" and g["PRIVILEGE"] == "USAGE"]


def info_schema(query, dbs, sql):
    """sql(db) on the first database whose INFORMATION_SCHEMA works; the first error if none does."""
    err = None
    for d in dbs[:5]:
        try:
            return query(sql(ident(d)))
        except Exception as e:
            err = err or e
    raise err


def mine(query, db):
    """The logged-in user's own access, live, with their own rights. Writes nothing (no tables, no temp tables).
    query(sql) -> list of dicts; db: a database whose INFORMATION_SCHEMA the user can read
    (None: the current one, else one the user's roles can use)."""
    me = query("SELECT CURRENT_USER() AS U")[0]["U"]
    db = db or query("SELECT CURRENT_DATABASE() AS D")[0]["D"]
    query("USE SECONDARY ROLES ALL")  # every granted role counts, as with DEFAULT_SECONDARY_ROLES = ('ALL')
    roles = json.loads(query("SELECT CURRENT_AVAILABLE_ROLES() AS R")[0]["R"])  # granted + inherited, always readable
    src, notes, grants, skipped = {}, {}, [], []
    for r, got in zip(roles, each(query, [f"SHOW GRANTS TO ROLE {ident(r)}" for r in roles])):
        if isinstance(got, Exception):
            skipped.append(f"{r} ({line(got)})")
        else:
            grants += [dict(GRANTEE_ROLE=r, PRIVILEGE=x["privilege"], GRANTED_ON=x["granted_on"],
                            OBJECT_NAME=x["name"].replace('"', ""), IS_FUTURE=False) for x in got]
    todo, seen, bad = held_db_roles(grants), set(), []  # database roles: their own SHOW, recursively, a wave at a time
    while todo:
        wave = sorted(set(todo) - seen)
        seen |= set(wave)
        todo = []
        for r, got in zip(wave, each(query, [f"SHOW GRANTS TO DATABASE ROLE {db_ident(r)}" for r in wave])):
            if isinstance(got, Exception):
                bad.append(f"{r} ({line(got)})")
                continue
            got = [dict(GRANTEE_ROLE=r, PRIVILEGE=x["privilege"], GRANTED_ON=x["granted_on"],
                        OBJECT_NAME=x["name"].replace('"', ""), IS_FUTURE=False) for x in got]
            grants += got
            todo += held_db_roles(got)
    if bad:
        notes["database_roles"] = (f"{len(bad)} database roles not readable, held but their grants unknown: "
                                   + " | ".join(bad[:10]))
    src["grants"] = "SHOW GRANTS TO ROLE"
    # SNOWFLAKE last: without IMPORTED PRIVILEGES the user can't even see it, any usable database works
    dbs = list(dict.fromkeys(([db] if db else []) + [g["OBJECT_NAME"] for g in grants if g["GRANTED_ON"] == "DATABASE"]
                             + ["SNOWFLAKE"]))
    try:  # role links of the user's roles, and the roles granted to the user: no privileges needed
        applicable = info_schema(query, dbs, lambda d: f"SELECT GRANTEE, ROLE_NAME FROM {d}.INFORMATION_SCHEMA.APPLICABLE_ROLES")
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
    who, agg = me.replace("'", "''"), """
            SELECT 'ROLE' AS KIND, ROLE_NAME AS NAME, COUNT(*) AS QUERIES, MAX(START_TIME) AS LAST_USED FROM Q WHERE ROLE_NAME IS NOT NULL GROUP BY 2
            UNION ALL
            SELECT 'WAREHOUSE', WAREHOUSE_NAME, COUNT(*), MAX(START_TIME) FROM Q WHERE WAREHOUSE_NAME IS NOT NULL GROUP BY 2"""
    try:  # ACCOUNT_USAGE first (30 days, needs IMPORTED PRIVILEGES), else INFORMATION_SCHEMA (7 days, own queries)
        usage = query(f"""WITH Q AS (SELECT ROLE_NAME, WAREHOUSE_NAME, START_TIME FROM {AU}.QUERY_HISTORY
                WHERE USER_NAME = '{who}' AND START_TIME >= DATEADD(DAY, -30, CURRENT_TIMESTAMP()))""" + agg)
        src["usage"] = "ACCOUNT_USAGE"
    except Exception as au:
        try:
            usage = info_schema(query, dbs, lambda d: f"""WITH Q AS (SELECT ROLE_NAME, WAREHOUSE_NAME, START_TIME FROM TABLE({d}.INFORMATION_SCHEMA.QUERY_HISTORY_BY_USER(
                    USER_NAME => '{who}', END_TIME_RANGE_START => DATEADD(DAY, -7, CURRENT_TIMESTAMP()), RESULT_LIMIT => 10000)))""" + agg)
            src["usage"] = "INFORMATION_SCHEMA"
        except Exception as e:
            usage, src["usage"] = [], "UNAVAILABLE"
            notes["usage"] = f"{AU}.QUERY_HISTORY: {line(au)}; INFORMATION_SCHEMA.QUERY_HISTORY_BY_USER: {line(e)}"
    src["tags"] = src["policies"] = "UNAVAILABLE"
    notes["tags"] = "sensitivity needs the governance views of the shared snapshot"
    run = dict(RUN_ID="live", FINISHED_AT="now", SOURCES=src, NOTES=notes)
    return dict(run=run, GRANT=grants, USER_ROLE=[dict(USER_NAME=me, ROLE_NAME=r) for r in direct],
                USER=[dict(USER_NAME=me) | user], USAGE=[dict(USER_NAME=me) | u for u in usage], TAG=[], POLICY=[],
                STREAM=[])


AU = "SNOWFLAKE.ACCOUNT_USAGE"
TAG_FALLBACK_MAX = 300  # tables/views read one by one when the ACCOUNT_USAGE views are not readable


def live(query):
    """The whole account, read now with the caller's role, kept in memory: what SP_ACCESS_SNAPSHOT('AUTO') writes to the
    tables, for accounts where procedures can't be created. ACCOUNT_USAGE where readable, else SHOW / INFORMATION_SCHEMA
    (keep in step with sql/1_setup.sql). Writes nothing. query(sql) -> list of dicts; same dict as snapshot()."""
    def rows(sql):  # lower-case keys: SHOW columns are lower case, views upper case
        return [{k.lower(): v for k, v in r.items()} for r in query(sql)]

    def many(sqls):  # rows of each sql, SHOW_THREADS at a time; a failed one gives its exception
        return [r if isinstance(r, Exception) else [{k.lower(): v for k, v in x.items()} for x in r] for r in each(query, sqls)]

    def readable(view):
        try:
            query(f"SELECT 1 FROM {AU}.{view} LIMIT 1")
            return None
        except Exception as e:
            return f"{AU}.{view} not readable: {line(e)}"

    def clean(name):  # SHOW quotes names with special characters; ACCOUNT_USAGE does not
        return (name or "").replace('"', "")

    def blank(v):
        return None if v in ("", "null", None) else v

    src, notes, d = {}, {}, {t: [] for t in TABLES + OPTIONAL}
    try:  # privileges of every granted role count (e.g. IMPORTED PRIVILEGES through another role)
        query("USE SECONDARY ROLES ALL")
    except Exception:
        pass
    now = query("SELECT CURRENT_TIMESTAMP() AS T")[0]["T"]
    db = query("SELECT CURRENT_DATABASE() AS D")[0]["D"]

    def note(name, source, why):
        src[name] = source
        if why:
            notes[name] = why

    why = readable("GRANTS_TO_ROLES") or readable("GRANTS_TO_USERS")
    if why is None:  # NAME holds only the object's own name; DATABASE rows may repeat it in TABLE_CATALOG;
        # a database role grantee is a bare name: qualified with the database of what it is granted, DB.ROLE
        d["GRANT"] = query(f"""SELECT IFF(GRANTED_TO = 'DATABASE_ROLE',
                       IFF(GRANTED_ON = 'DATABASE', NAME, TABLE_CATALOG) || '.' || GRANTEE_NAME, GRANTEE_NAME) AS GRANTEE_ROLE,
                   PRIVILEGE, GRANTED_ON,
                   CASE WHEN GRANTED_ON = 'DATABASE' THEN NAME
                        WHEN GRANTED_ON = 'SCHEMA' THEN TABLE_CATALOG || '.' || NAME
                        ELSE ARRAY_TO_STRING(ARRAY_CONSTRUCT_COMPACT(TABLE_CATALOG, TABLE_SCHEMA, NAME), '.') END AS OBJECT_NAME,
                   FALSE AS IS_FUTURE, GRANT_OPTION, GRANTED_BY
            FROM {AU}.GRANTS_TO_ROLES WHERE DELETED_ON IS NULL AND GRANTED_TO IN ('ROLE', 'DATABASE_ROLE')""")
        d["USER_ROLE"] = query(f"""SELECT GRANTEE_NAME AS USER_NAME, ROLE AS ROLE_NAME, GRANTED_BY
            FROM {AU}.GRANTS_TO_USERS WHERE DELETED_ON IS NULL""")
        note("grants", "ACCOUNT_USAGE", None)
    else:
        skipped = []
        roles = [r["name"] for r in rows("SHOW ROLES")]
        got = many([f"SHOW GRANTS TO ROLE {ident(r)}" for r in roles] + [f"SHOW GRANTS OF ROLE {ident(r)}" for r in roles])
        for role, to, of in zip(roles, got[:len(roles)], got[len(roles):]):
            bad = next((x for x in (to, of) if isinstance(x, Exception)), None)
            if bad:  # a role this role may not inspect: keep going, list it in the notes
                skipped.append(f"{role}: {line(bad)}")
                continue
            d["GRANT"] += [dict(GRANTEE_ROLE=role, PRIVILEGE=x["privilege"], GRANTED_ON=x["granted_on"],
                                OBJECT_NAME=clean(x["name"]), IS_FUTURE=False,
                                GRANT_OPTION=str(x.get("grant_option")).lower() == "true", GRANTED_BY=x.get("granted_by"))
                           for x in to if x.get("granted_to") in ("ROLE", None)]
            d["USER_ROLE"] += [dict(USER_NAME=x["grantee_name"], ROLE_NAME=role, GRANTED_BY=x.get("granted_by"))
                               for x in of if x.get("granted_to") == "USER"]
        dbs = [x["name"] for x in rows("SHOW DATABASES") if x.get("kind", "STANDARD") == "STANDARD"]
        qs = []  # database roles: per database, their grants under DB.ROLE
        for name, got in zip(dbs, many([f"SHOW DATABASE ROLES IN DATABASE {ident(x)}" for x in dbs])):
            if isinstance(got, Exception):
                skipped.append(f"database roles in {name}: {line(got)}")
            else:
                qs += [(name, f"{name}.{clean(r['name'])}") for r in got]
        for (name, q), got in zip(qs, many([f"SHOW GRANTS TO DATABASE ROLE {db_ident(q)}" for _, q in qs])):
            if isinstance(got, Exception):
                skipped.append(f"database roles in {name}: {line(got)}")
                continue
            d["GRANT"] += [dict(GRANTEE_ROLE=q, PRIVILEGE=g["privilege"], GRANTED_ON=g["granted_on"],
                                OBJECT_NAME=clean(g["name"]), IS_FUTURE=False,
                                GRANT_OPTION=str(g.get("grant_option")).lower() == "true",
                                GRANTED_BY=g.get("granted_by")) for g in got]
        note("grants", "SHOW", why + (f"; {len(skipped)} roles skipped: " + " | ".join(skipped[:20]) if skipped else ""))
    note("user_roles", src["grants"], notes.get("grants"))

    skipped = []  # future grants: no ACCOUNT_USAGE view; shares and applications: their grants are not ours
    dbs = [x["name"] for x in rows("SHOW DATABASES") if x.get("kind", "STANDARD") == "STANDARD"]
    places, failed = [], set()
    for name, got in zip(dbs, many([f"SHOW SCHEMAS IN DATABASE {ident(x)}" for x in dbs])):
        if isinstance(got, Exception):
            skipped.append(f"{name}: {line(got)}")
            continue
        places += [(name, f"DATABASE {ident(name)}")] + [
            (name, f"SCHEMA {ident(name)}.{ident(s['name'])}") for s in got if s["name"] != "INFORMATION_SCHEMA"]
    for (name, p), got in zip(places, many([f"SHOW FUTURE GRANTS IN {p}" for _, p in places])):
        if isinstance(got, Exception):
            if name not in failed:  # one note per database
                failed.add(name)
                skipped.append(f"{name}: {line(got)}")
            continue
        d["GRANT"] += [dict(GRANTEE_ROLE=f["grantee_name"] if f["grant_to"] == "ROLE" else  # to a database role: DB.ROLE
                            qualify(name, clean(f["grantee_name"])), PRIVILEGE=f["privilege"],
                            GRANTED_ON=f["grant_on"], OBJECT_NAME=clean(f["name"]), IS_FUTURE=True,
                            GRANT_OPTION=str(f.get("grant_option")).lower() == "true", GRANTED_BY=None)
                       for f in got if f.get("grant_to") in ("ROLE", "DATABASE_ROLE")]
    note("future_grants", "SHOW", f"{len(skipped)} databases skipped: " + " | ".join(skipped[:20]) if skipped else None)

    why = readable("USERS")
    if why is None:  # OBJECT_CONSTRUCT(*): the secondary roles column name differs between Snowflake versions
        d["USER"] = query(f"""SELECT J:NAME::STRING AS USER_NAME, J:TYPE::STRING AS TYPE,
                   TRY_TO_BOOLEAN(J:DISABLED::STRING) AS DISABLED, J:DEFAULT_ROLE::STRING AS DEFAULT_ROLE,
                   COALESCE(J:DEFAULT_SECONDARY_ROLES, J:DEFAULT_SECONDARY_ROLE)::STRING AS DEFAULT_SECONDARY_ROLES,
                   J:DEFAULT_WAREHOUSE::STRING AS DEFAULT_WAREHOUSE, J:DEFAULT_NAMESPACE::STRING AS DEFAULT_NAMESPACE,
                   TRY_TO_TIMESTAMP_LTZ(J:LAST_SUCCESS_LOGIN::STRING) AS LAST_SUCCESS_LOGIN
            FROM (SELECT OBJECT_CONSTRUCT(*) AS J FROM {AU}.USERS WHERE DELETED_ON IS NULL)""")
        note("users", "ACCOUNT_USAGE", None)
    else:
        d["USER"] = [dict(USER_NAME=x["name"], TYPE=blank(x.get("type")), DISABLED=str(x.get("disabled")).lower() == "true",
                          DEFAULT_ROLE=blank(x.get("default_role")),
                          DEFAULT_SECONDARY_ROLES=blank(x.get("default_secondary_roles")),
                          DEFAULT_WAREHOUSE=blank(x.get("default_warehouse")),
                          DEFAULT_NAMESPACE=blank(x.get("default_namespace")),
                          LAST_SUCCESS_LOGIN=blank(x.get("last_success_login"))) for x in rows("SHOW USERS")]
        note("users", "SHOW", why)

    def usage(q, secondary):  # roles, secondary roles and warehouses used per user, aggregated in SQL
        sql = f"""WITH Q AS ({q})
            SELECT USER_NAME, 'ROLE' AS KIND, ROLE_NAME AS NAME, COUNT(*) AS QUERIES, MAX(START_TIME) AS LAST_USED
            FROM Q WHERE ROLE_NAME IS NOT NULL GROUP BY 1, 3
            UNION ALL
            SELECT USER_NAME, 'WAREHOUSE', WAREHOUSE_NAME, COUNT(*), MAX(START_TIME) FROM Q WHERE WAREHOUSE_NAME IS NOT NULL GROUP BY 1, 3"""
        if secondary:  # SECONDARY_ROLE_STATS: JSON text, roleNames = comma-separated roles
            sql += """
            UNION ALL
            SELECT Q.USER_NAME, 'SECONDARY ROLE', TRIM(S.VALUE::STRING), COUNT(*), MAX(Q.START_TIME)
            FROM Q, LATERAL FLATTEN(SPLIT(TRY_PARSE_JSON(Q.SECONDARY_ROLE_STATS):roleNames::STRING, ',')) S
            WHERE TRIM(S.VALUE::STRING) <> '' GROUP BY 1, 3"""
        return query(sql)

    why = readable("QUERY_HISTORY")
    if why is None:
        try:  # usage is extra: without it the rest still loads
            d["USAGE"] = usage(f"""SELECT USER_NAME, ROLE_NAME, WAREHOUSE_NAME, SECONDARY_ROLE_STATS, START_TIME
                FROM {AU}.QUERY_HISTORY WHERE START_TIME >= DATEADD(DAY, -30, CURRENT_TIMESTAMP())""", True)
            note("usage", "ACCOUNT_USAGE", None)
        except Exception as e:
            note("usage", "UNAVAILABLE", line(e))
    else:
        try:
            d["USAGE"] = usage(f"""SELECT USER_NAME, ROLE_NAME, WAREHOUSE_NAME, START_TIME FROM TABLE({ident(db or "SNOWFLAKE")}.INFORMATION_SCHEMA.QUERY_HISTORY(
                END_TIME_RANGE_START => DATEADD(DAY, -7, CURRENT_TIMESTAMP()),
                RESULT_LIMIT => 10000))""", False)
            note("usage", "INFORMATION_SCHEMA", why + "; INFORMATION_SCHEMA.QUERY_HISTORY: 7 days, max 10000 queries, "
                                                      "only the queries this role may see")
        except Exception as e:
            note("usage", "UNAVAILABLE", why + f"; INFORMATION_SCHEMA.QUERY_HISTORY: {line(e)}")

    objs = sorted({g["OBJECT_NAME"] for g in d["GRANT"] if not g["IS_FUTURE"]
                   and ("TABLE" in g["GRANTED_ON"] or "VIEW" in g["GRANTED_ON"])})  # for the per-object fallbacks

    def capped(why, skipped):
        out = [why]
        if len(objs) > TAG_FALLBACK_MAX:
            out.append(f"{len(objs) - TAG_FALLBACK_MAX} objects past TAG_FALLBACK_MAX={TAG_FALLBACK_MAX} not read: "
                       + ", ".join(objs[TAG_FALLBACK_MAX:TAG_FALLBACK_MAX + 20]))
        if skipped:
            out.append(f"{len(skipped)} objects skipped: " + " | ".join(skipped[:20]))
        return "; ".join(out)

    def quoted(name):  # DB.SCHEMA.OBJECT -> "DB"."SCHEMA"."OBJECT"
        return ".".join(ident(p) for p in name.split(".", 2))

    def sq(text):  # inside a '...' string, where backslash also escapes
        return text.replace("\\", "\\\\").replace("'", "''")

    why = readable("TAG_REFERENCES")
    try:
        if why is None:
            d["TAG"] = query(f"""SELECT CASE DOMAIN WHEN 'DATABASE' THEN OBJECT_NAME
                                          WHEN 'SCHEMA' THEN OBJECT_DATABASE || '.' || OBJECT_NAME
                                          ELSE OBJECT_DATABASE || '.' || OBJECT_SCHEMA || '.' || OBJECT_NAME END AS OBJECT_NAME,
                       DOMAIN, IFF(DOMAIN = 'COLUMN', COLUMN_NAME, NULL) AS COLUMN_NAME,
                       TAG_DATABASE || '.' || TAG_SCHEMA || '.' || TAG_NAME AS TAG_NAME, TAG_VALUE, APPLY_METHOD
                FROM {AU}.TAG_REFERENCES WHERE OBJECT_DELETED IS NULL AND DOMAIN IN ('DATABASE', 'SCHEMA', 'TABLE', 'COLUMN')""")
            note("tags", "ACCOUNT_USAGE", None)
        else:
            skipped = []
            for o in objs[:TAG_FALLBACK_MAX]:
                fn = f"{ident(o.split('.')[0])}.INFORMATION_SCHEMA"
                try:
                    for x in rows(f"SELECT * FROM TABLE({fn}.TAG_REFERENCES('{sq(quoted(o))}', 'table'))"):
                        d["TAG"].append(dict(OBJECT_NAME=o, DOMAIN="TABLE", COLUMN_NAME=None,
                                             TAG_NAME=f"{x['tag_database']}.{x['tag_schema']}.{x['tag_name']}",
                                             TAG_VALUE=x.get("tag_value"),
                                             APPLY_METHOD="INHERITED" if x.get("level") not in (None, "TABLE") else "MANUAL"))
                    for x in rows(f"SELECT * FROM TABLE({fn}.TAG_REFERENCES_ALL_COLUMNS('{sq(quoted(o))}', 'table'))"):
                        if x.get("level") in (None, "COLUMN"):
                            d["TAG"].append(dict(OBJECT_NAME=o, DOMAIN="COLUMN", COLUMN_NAME=x.get("column_name"),
                                                 TAG_NAME=f"{x['tag_database']}.{x['tag_schema']}.{x['tag_name']}",
                                                 TAG_VALUE=x.get("tag_value"), APPLY_METHOD=x.get("apply_method") or "MANUAL"))
                except Exception as e:
                    skipped.append(f"{o}: {line(e)}")
            note("tags", "INFORMATION_SCHEMA", capped(why, skipped))
    except Exception as e:
        d["TAG"] = []
        note("tags", "UNAVAILABLE", "; ".join(filter(None, [why, line(e)])))

    why = readable("POLICY_REFERENCES")
    try:
        if why is None:
            d["POLICY"] = query(f"""SELECT R.POLICY_DB || '.' || R.POLICY_SCHEMA || '.' || R.POLICY_NAME AS POLICY_NAME,
                       R.POLICY_KIND, IFF(R.REF_ENTITY_DOMAIN = 'TAG', NULL,
                           R.REF_DATABASE_NAME || '.' || R.REF_SCHEMA_NAME || '.' || R.REF_ENTITY_NAME) AS OBJECT_NAME,
                       R.REF_COLUMN_NAME AS COLUMN_NAME, R.REF_ARG_COLUMN_NAMES::STRING AS ARG_COLUMNS,
                       IFF(R.REF_ENTITY_DOMAIN = 'TAG', R.REF_DATABASE_NAME || '.' || R.REF_SCHEMA_NAME || '.' || R.REF_ENTITY_NAME,
                           IFF(R.TAG_NAME IS NULL, NULL, R.TAG_DATABASE || '.' || R.TAG_SCHEMA || '.' || R.TAG_NAME)) AS TAG_NAME,
                       COALESCE(M.POLICY_BODY, A.POLICY_BODY) AS POLICY_BODY
                FROM {AU}.POLICY_REFERENCES R
                LEFT JOIN {AU}.MASKING_POLICIES M ON M.POLICY_ID = R.POLICY_ID AND M.DELETED IS NULL
                LEFT JOIN {AU}.ROW_ACCESS_POLICIES A ON A.POLICY_ID = R.POLICY_ID AND A.DELETED IS NULL
                WHERE R.POLICY_KIND IN ('MASKING_POLICY', 'ROW_ACCESS_POLICY')""")
            note("policies", "ACCOUNT_USAGE", None)
        else:
            skipped, body = [], {}
            for o in objs[:TAG_FALLBACK_MAX]:
                fn = f"{ident(o.split('.')[0])}.INFORMATION_SCHEMA"
                try:
                    for x in rows(f"""SELECT * FROM TABLE({fn}.POLICY_REFERENCES(
                            REF_ENTITY_NAME => '{sq(quoted(o))}', REF_ENTITY_DOMAIN => 'table'))"""):
                        if x.get("policy_kind") not in ("MASKING_POLICY", "ROW_ACCESS_POLICY"):
                            continue
                        name = f"{x['policy_db']}.{x['policy_schema']}.{x['policy_name']}"
                        if name not in body:
                            what = "MASKING POLICY" if x["policy_kind"] == "MASKING_POLICY" else "ROW ACCESS POLICY"
                            try:
                                body[name] = rows(f"DESCRIBE {what} {quoted(name)}")[0].get("body")
                            except Exception:  # no rights on the policy: its text stays empty, "cannot derive" in the app
                                body[name] = None
                        tag = f"{x['tag_database']}.{x['tag_schema']}.{x['tag_name']}" if x.get("tag_name") else None
                        d["POLICY"].append(dict(POLICY_NAME=name, POLICY_KIND=x["policy_kind"], OBJECT_NAME=o,
                                                COLUMN_NAME=x.get("ref_column_name"),
                                                ARG_COLUMNS=blank(x.get("ref_arg_column_names")), TAG_NAME=tag,
                                                POLICY_BODY=body[name]))
                except Exception as e:
                    skipped.append(f"{o}: {line(e)}")
            note("policies", "INFORMATION_SCHEMA", capped(why, skipped))
    except Exception as e:
        d["POLICY"] = []
        note("policies", "UNAVAILABLE", "; ".join(filter(None, [why, line(e)])))

    why = readable("ACCESS_HISTORY")  # Enterprise edition; no fallback: Granted vs used then explains it
    try:
        if why:
            raise RuntimeError(why)
        d["OBJECT_USE"] = query(use_sql())
        note("object_use", "ACCOUNT_USAGE", None)
    except Exception as e:
        d["OBJECT_USE"] = []
        note("object_use", "UNAVAILABLE", line(e))

    try:  # streams: no ACCOUNT_USAGE view; only the streams this role can see
        d["STREAM"] = [dict(STREAM_NAME=f"{x['database_name']}.{x['schema_name']}.{clean(x['name'])}",
                            SOURCE_NAME=clean(x.get("table_name")), SOURCE_TYPE=blank(x.get("source_type")))
                       for x in rows("SHOW STREAMS IN ACCOUNT")]
        note("streams", "SHOW", None)
    except Exception as e:
        note("streams", "UNAVAILABLE", line(e))
    return d | {"run": dict(RUN_ID="direct", FINISHED_AT=now, SOURCES=src, NOTES=notes)}


def use_sql(days=USE_DAYS):
    """Object usage from ACCESS_HISTORY (query metadata, never table data), aggregated in Snowflake per user, object,
    ISO week (its Monday, whatever WEEK_START says) and READ (objects read) / WRITE (objects modified). The same text
    is in access.py and SP_ACCESS_SNAPSHOT (sql/1_setup.sql)."""
    return f"""WITH H AS (
            SELECT H.USER_NAME, H.QUERY_ID, H.QUERY_START_TIME AS T, O.VALUE:"objectName"::STRING AS OBJECT_NAME, 'READ' AS ACTION
            FROM {AU}.ACCESS_HISTORY H, LATERAL FLATTEN(H.DIRECT_OBJECTS_ACCESSED) O
            WHERE H.QUERY_START_TIME >= DATEADD(DAY, -{days}, CURRENT_TIMESTAMP())
            UNION ALL
            SELECT H.USER_NAME, H.QUERY_ID, H.QUERY_START_TIME, O.VALUE:"objectName"::STRING, 'WRITE'
            FROM {AU}.ACCESS_HISTORY H, LATERAL FLATTEN(H.OBJECTS_MODIFIED) O
            WHERE H.QUERY_START_TIME >= DATEADD(DAY, -{days}, CURRENT_TIMESTAMP()))
        SELECT USER_NAME, OBJECT_NAME, DATEADD(DAY, 1 - DAYOFWEEKISO(T), T::DATE) AS WEEK, ACTION,
               COUNT(DISTINCT QUERY_ID) AS QUERIES, MAX(T) AS LAST_USED
        FROM H WHERE OBJECT_NAME IS NOT NULL GROUP BY 1, 2, 3, 4"""


def only(d, user):
    """Demo of mine() without Snowflake: one user's slice of a full data set."""
    build(d, builtin=True)
    seen = {r for s in starts(user, True) for p in down(s, user=True) for r in p[1:]}
    run = dict(RUN_ID="live", FINISHED_AT="now", SOURCES={"all": f"demo: {user}'s slice of the fake data",
                                                          "usage": "INFORMATION_SCHEMA"},
               NOTES={"usage": "demo: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY not readable",
                      "applicable_roles": "demo: INFORMATION_SCHEMA.APPLICABLE_ROLES not readable"})
    return dict(run=run, GRANT=[g for g in d["GRANT"] if g["GRANTEE_ROLE"] in seen], TAG=[], POLICY=[], STREAM=[],
                **{t: [x for x in d.get(t) or [] if x["USER_NAME"] == user] for t in ("USER_ROLE", "USER", "USAGE", "OBJECT_USE")})


# ---------- lookups (filled by build) ----------

role_grants, user_grants, privs = [], [], []  # (granted role, grantee role), (role, user), (role, privilege, type, object)
holds, held_by, users_of, roles_of, profile, used = {}, {}, {}, {}, {}, {}
granted, on = {}, {}  # role -> [(privilege, type, object)], object -> [(role, privilege, type)]
roles, users, objects, kinds, run = [], [], [], {}, {}
tags, policies, sens = [], [], {}  # TAG rows, POLICY rows, sensitive(): object -> [(column, tag, value, origin)]
streams = {}  # stream -> source table (STREAM rows)
obj_use = {}  # user -> OBJECT_USE rows (ACCESS_HISTORY per object, week and READ / WRITE)
capped = set()  # start of every walk cut at MAX_HOPS; the UI clears it before a page and warns when it is not empty
db_roles = set()  # database roles, by their qualified name DB.ROLE
ROLE_ON = ("ROLE", "DATABASE_ROLE")  # GRANTED_ON of a role link (with USAGE): an account or a database role is held
memo = {}  # results that only depend on the data set (rule findings, ...), cleared by build()
hidden = []  # GRANT rows of Snowflake's built-in grants (builtin_grant) left out by build(builtin=False)
source = {}  # data: the dict build() got, builtin: its flag (what_if rebuilds from them)


def is_builtin(name):
    return bool(BUILTIN_RE.match(name or ""))


def builtin_grant(g):
    """A GRANT row Snowflake makes itself: held by a built-in role, or PUBLIC's on a built-in role or object."""
    return is_builtin(g["GRANTEE_ROLE"]) or (g["GRANTEE_ROLE"] == "PUBLIC" and is_builtin(g["OBJECT_NAME"]))


def build(d, key=None, builtin=False):
    """Fill the module lookups from fake() or snapshot(). key: the same key as the last build skips the work (the app
    passes the run of the shared snapshot, so a rerun does not rebuild or recheck the rules). builtin: keep Snowflake's
    built-in grants (BUILTIN); left out by default, kept in hidden."""
    global roles, users, objects, run
    if key is not None and memo.get("key") == (key, builtin):
        return
    memo.clear()
    memo["key"] = (key, builtin)
    source.update(data=d, builtin=builtin)
    for x in (role_grants, user_grants, privs, holds, held_by, users_of, roles_of, profile, used, kinds, granted, on,
              capped, tags, policies, sens, streams, db_roles, hidden, obj_use):
        x.clear()
    for g in d["GRANT"]:
        if not builtin and builtin_grant(g):
            hidden.append(g)
            continue
        if g["GRANTED_ON"] in ROLE_ON and g["PRIVILEGE"] == "USAGE":  # role inheritance; OWNERSHIP on a role is not
            # every custom role is also granted to SYSADMIN: dropped so admin roles don't swallow every graph;
            # holding an admin role is kept and flagged in red
            if g["GRANTEE_ROLE"] not in ADMIN:
                role_grants.append((g["OBJECT_NAME"], g["GRANTEE_ROLE"]))
        else:
            k = ("FUTURE " if g["IS_FUTURE"] else "") + g["GRANTED_ON"]
            privs.append((g["GRANTEE_ROLE"], g["PRIVILEGE"], k, g["OBJECT_NAME"]))
            if g["GRANTED_ON"] not in ROLE_ON:  # OWNERSHIP on a role: it stays a role, not an object
                kinds[g["OBJECT_NAME"]] = k
        if g["GRANTED_ON"] == "DATABASE_ROLE":
            db_roles.add(g["OBJECT_NAME"])
        if "." in (g["GRANTEE_ROLE"] or ""):  # a grantee DB.ROLE: account role names have no dot (unless quoted)
            db_roles.add(g["GRANTEE_ROLE"])
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
    streams.update({x["STREAM_NAME"]: x["SOURCE_NAME"] for x in d.get("STREAM", [])})
    for x in d.get("OBJECT_USE") or []:
        obj_use.setdefault(x["USER_NAME"], []).append(x)
    rules = tag_rules()
    for o in objects:
        hit = [t for t in tags_of(o) if tag_hit(rules, t[1], t[2])]
        if hit:
            sens[o] = hit


def builtin_info():
    """Snowflake's built-in grants left out by build(): dict(label, grants, roles [built-in roles], objects (count)),
    None when nothing is left out."""
    if not hidden:
        return None
    role_on = ROLE_ON + ("APPLICATION_ROLE",)
    rs = {g["OBJECT_NAME"] for g in hidden if g["GRANTED_ON"] in role_on} | {g["GRANTEE_ROLE"] for g in hidden} - {"PUBLIC"}
    return dict(label=BUILTIN_NODE, grants=len(hidden), roles=sorted(rs),
                objects=len({g["OBJECT_NAME"] for g in hidden if g["GRANTED_ON"] not in role_on}))


def cached(name, fn):
    """fn() once per data set (see build)."""
    if name not in memo:
        memo[name] = fn()
    return memo[name]


def kind_of(name):
    """user | admin | database | functional | technical | group | object. Group = any other role, PUBLIC included;
    database = a database role (DB.ROLE)."""
    if name in profile or name in roles_of:
        return "user"
    return role_kind(name)


def role_kind(name):
    """kind_of for a name known to be a role or object: a role named like a user is still a role."""
    if name in ADMIN:
        return "admin"
    if name in db_roles:
        return "database"
    if name.startswith(FUNC):
        return "functional"
    if name.startswith(TECH):
        return "technical"
    if name in kinds and name not in roles:
        return "object"
    return "group"


UTAG = " (user)"  # graph node id of a user named like a role: users and roles are separate namespaces


def uid(name, user):
    """Graph node id: name, or name + UTAG for a user whose name is also a role's, so both get their own box."""
    return name + UTAG if user and name in cached("rset", lambda: set(roles)) else name


def node_kind(n):
    """Kind of a graph node id (see uid): a bare name that is a role is the role, even when a user has that name."""
    if n.endswith(UTAG) and n[:-len(UTAG)] in cached("rset", lambda: set(roles)):
        return "user"
    return role_kind(n) if n in cached("rset", lambda: set(roles)) else kind_of(n)


def node_name(n):
    """The user or role name of a graph node id."""
    return n[:-len(UTAG)] if node_kind(n) == "user" and n.endswith(UTAG) else n


@functools.cache  # pure, and called for every grant a walk reaches
def priv_class(pv, kind=""):
    """read | write | own | use | manage | admin, for arrows and badges. manage: CREATE ..., MODIFY, OPERATE, APPLY ...
    (changes or runs objects without touching data); admin: account-level (MANAGE GRANTS, EXECUTE TASK, ...)."""
    k = (kind or "").replace("FUTURE ", "")
    if k == "ACCOUNT":
        return "admin"
    if pv == "OWNERSHIP":
        return "own"
    if pv.startswith(("CREATE ", "APPLY")) or pv in ("MODIFY", "OPERATE"):
        return "manage"
    if pv in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "WRITE") or pv.startswith("ADD "):
        return "write"
    if pv in ("SELECT", "REFERENCES", "READ") or (pv == "USAGE" and k in ("DATABASE", "SCHEMA")):
        return "read"
    return "use"


CATS = {"usage": "Usage", "read": "Read", "write": "Write", "execute": "Execute", "own": "Own", "manage": "Manage",
        "hold": "Hold"}  # Privileges tabs, in this order


def priv_cat(pv, kind=""):
    """Privileges tab of a privilege: usage (USAGE / MONITOR on a database, schema, warehouse, ...), read, write,
    execute (USAGE on a function or procedure, EXECUTE ..., OPERATE on a task), own, manage (CREATE ..., MODIFY, account
    privileges, the rest), hold (USAGE on a database role: holding it; the roles reached are reach())."""
    k = (kind or "").replace("FUTURE ", "")
    c = priv_class(pv, k)
    if c == "own":
        return c
    if k in ROLE_ON:
        return "hold"
    if pv.startswith("EXECUTE ") or (pv == "USAGE" and k in ("FUNCTION", "PROCEDURE")) or (pv == "OPERATE" and k == "TASK"):
        return "execute"
    if c == "admin":
        return "manage"
    if pv in ("USAGE", "MONITOR") or c == "use":
        return "usage"
    return c if c in ("read", "write") else "manage"


LEVELS = ("names", "read", "change", "own", "admin")  # access ladder, low to high power
RUN_TYPES = {"WAREHOUSE", "FUNCTION", "PROCEDURE", "TASK", "PIPE", "ALERT", "COMPUTE POOL", "INTEGRATION", "NOTEBOOK",
             "STREAMLIT", "SEQUENCE"}


def category(pv, kind=""):
    """Where a grant shows on the access screen: data (on the ladder), runnable (warehouses, functions, procedures,
    tasks), account (account privileges and CREATE / MODIFY on a database or schema), names (USAGE on a database or
    schema: can see names) or hold (a role held)."""
    k = (kind or "").replace("FUTURE ", "")
    if k == "ACCOUNT":
        return "account"
    if k in ROLE_ON:
        return "hold"
    if k in RUN_TYPES or priv_cat(pv, k) == "execute":
        return "runnable"
    if k in ("DATABASE", "SCHEMA"):
        return "names" if pv in ("USAGE", "MONITOR") else "data" if pv == "OWNERSHIP" else "account"
    return "data"


def level_of(pv, kind=""):
    """Ladder step of one privilege on a data object (None: not on the ladder, e.g. APPLY on a table)."""
    k = (kind or "").replace("FUTURE ", "")
    if k in ("DATABASE", "SCHEMA") and pv in ("USAGE", "MONITOR"):
        return "names"
    return {"own": "own", "write": "change", "read": "read"}.get(priv_class(pv, k))


CAT_RANK = ("data", "runnable", "account", "names")


def access_objects(rows, user=False):
    """One entry per object from grants() rows, at the highest ladder step any of its privileges gives ("admin" when a
    path runs through an admin role). path summary: first role after the subject (None: granted straight), grant
    holder of the shortest path, ways = distinct routes (every path, counted)."""
    by = {}
    for r in rows:
        c = category(r["privilege"], r["type"])
        if c == "hold":
            continue
        key = (r["object"], r["privilege"]) if c == "account" else (r["object"], "")  # each account power on its own
        x = by.setdefault(key, dict(object=r["object"], type=r["type"], database=r["database"], schema=r["schema"],
                                    category=c, rows=[]))
        x["rows"].append(r)
        if CAT_RANK.index(c) < CAT_RANK.index(x["category"]):  # an owned schema is data, its USAGE folds in
            x["category"] = c
    out = []
    for x in by.values():
        rs = sorted(x.pop("rows"), key=lambda r: (len(r["path"]), r["privilege"]))
        steps = [level_of(r["privilege"], r["type"]) for r in rs if x["category"] in ("data", "names")]
        top = max((s for s in steps if s), key=LEVELS.index, default=None)
        if top and any(n in ADMIN for r in rs for p in r["paths"] for n in p[1:-1]):
            top = "admin"
        best = rs[0]["path"]
        routes = {tuple(p[:-1]) for r in rs for p in r["paths"]}
        ways = max(len(routes), max(r["count"] for r in rs))
        order = sorted({r["privilege"] for r in rs}, key=lambda pv: (-LEVELS.index(level_of(pv, x["type"]) or "names"), pv))
        out.append(x | dict(level=top, privileges=order, path=best, first=best[1] if len(best) > 2 else None,
                            holder=best[-2], ways=ways, depth=depth(best[:-1], user),
                            holders=sorted({h for r in rs for h in r["holders"]})))
    return out


def ladder_counts(objs):
    """Counts of data objects at each step or higher (read counts change and own too): one number per idea. usage:
    USAGE grants on databases and schemas (hidden by default, "can see names")."""
    data = [x for x in objs if x["category"] == "data" and x["level"]]
    at = lambda s: sum(LEVELS.index(x["level"]) >= LEVELS.index(s) for x in data)
    return dict(read=at("read"), change=at("change"), own=at("own"), admin=at("admin"),
                usage=sum(pv == "USAGE" and x["type"] in ("DATABASE", "SCHEMA") for x in objs for pv in x["privileges"]),
                runnable=sum(x["category"] == "runnable" for x in objs),
                account=sum(x["category"] == "account" for x in objs))


OBJ_LEVELS = ("names", "use", "read", "change", "own", "admin")  # one object's steps: "use" = run it (a warehouse)


def obj_level(pv, kind=""):
    """Step of one privilege on the Who has access screen: the ladder (level_of), else own, change (MODIFY,
    OPERATE, CREATE ...: changes or runs the object) or use (USAGE on a warehouse, function ...)."""
    return level_of(pv, kind) or {"own": "own", "manage": "change"}.get(priv_class(pv, kind), "use")


def who_entry(name, rows, kind):
    """One user or role from its grantees() rows on one object: level (highest step), privileges (highest first),
    path (shortest of the highest step, name->...->holder->object), first (role after name; None when name holds the
    grant), holder, ways (distinct routes, counted), depth."""
    lv = lambda pv: OBJ_LEVELS.index(obj_level(pv, kind))
    rs = sorted(rows, key=lambda r: (-lv(r["privilege"]), len(r["path"]), r["privilege"]))
    best = rs[0]["path"]
    return dict(name=name, level=obj_level(rs[0]["privilege"], kind),
                privileges=sorted({r["privilege"] for r in rs}, key=lambda pv: (-lv(pv), pv)), path=best,
                first=best[1] if len(best) > 2 else None, holder=best[-2],
                ways=max(len({tuple(p[:-1]) for r in rs for p in r["paths"]}), max(r["count"] for r in rs)),
                depth=rs[0]["depth"])


def person(u, e, adm):
    """A user's entry with status and login; a user holding an admin role is "admin", shown by the shortest path to
    an admin role (admin roles inherit every role, so that is the path that gives the access)."""
    if adm.get(u):
        ps = sorted(admin_paths(u, True), key=len)
        e = e | dict(level="admin", path=ps[0], first=(ps[0][1:-1] or [None])[0], holder=ps[0][-1], ways=len(ps),
                     depth=depth(ps[0], True))
    return e | dict(admin=adm.get(u, []), status=status(u), service=is_service(u), days=login_days(u))


def who_has(obj, kind=None):
    """Who has access to one object (screen 2): dict(people, roles), one who_entry each, highest step first. A user
    holding an admin role is "admin" (see person()), also without any grant on obj. People also: admin (admin roles
    held), status, service, days (since the last login); roles: users (how many users reach the role)."""
    k0 = kind or kinds.get(obj)
    by = {}
    for r in grantees(obj, kind):
        by.setdefault((r["grantee"], r["kind"] == "user"), []).append(r)
    adm = admin_users()
    people = [person(n, who_entry(n, rs, k0), adm) for (n, u), rs in by.items() if u]
    people += [person(u, dict(name=u, privileges=[]), adm) for u in adm if (u, True) not in by]
    roles = [who_entry(n, rs, k0) | dict(users=len(ups(n)[1])) for (n, u), rs in by.items() if not u]
    rank = lambda e: (-OBJ_LEVELS.index(e["level"]), e["name"])
    return dict(people=sorted(people, key=rank), roles=sorted(roles, key=rank))


def admin_access():
    """The Admin holders preset of screen 2: users and roles holding an admin role, as who_has() entries (privileges =
    the admin roles held, path = the shortest one to an admin role)."""
    ps = group(((x, from_user(p)), p) for x, p in admin_holders())
    out, adm = dict(people=[], roles=[]), admin_users()
    for (x, u), qs in sorted(ps.items()):
        e = dict(name=x, level="admin", privileges=sorted({q[-1] for q in qs}), path=qs[0], first=(qs[0][1:-1] or [None])[0],
                 holder=qs[0][-1], ways=len(qs), depth=depth(qs[0], u))
        if u:
            out["people"].append(person(x, e, adm))
        elif x not in ADMIN:
            out["roles"].append(e | dict(users=len(ups(x)[1])))
    return out


def same_paths(entries):
    """Entries with the same level, privileges and route after their own name in one group ("12 people via PUBLIC"),
    biggest first. Group: level, privileges, route (path without the first name), names."""
    gs = {}
    for e in entries:
        gs.setdefault((e["level"], tuple(e["privileges"]), tuple(e["path"][1:])), []).append(e["name"])
    return sorted((dict(level=k[0], privileges=list(k[1]), route=list(k[2]), names=v) for k, v in gs.items()),
                  key=lambda g: (-len(g["names"]), -OBJ_LEVELS.index(g["level"]), g["route"]))


def column_view(obj, names):
    """Who sees each sensitive or masked column of obj in clear, over the users in names (data_view with any role
    they hold). Returns (columns, seen): column dict(column, tags, sensitive, policies, clear, masked, unknown [users]),
    seen {user: [dict(column, state, reason)]}."""
    ps, sc = policies_of(obj), set(sensitive_cols(obj))
    cols = {c: dict(column=c, tags=[], sensitive=c in sc, policies=[x["name"] for x in ps["columns"].get(c, [])],
                    clear=[], masked=[], unknown=[]) for c in sorted(sc | set(ps["columns"]))}
    seen = {}
    for u in names:
        for c in data_view(u, obj, True)["columns"]:
            if c["column"] in cols:
                x = cols[c["column"]]
                x["tags"] = c["tags"]
                x[c["state"] if c["state"] in ("clear", "masked") else "unknown"].append(u)
                seen.setdefault(u, []).append(dict(column=c["column"], state=c["state"], reason=c["reason"]))
    return list(cols.values()), seen


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


@functools.cache
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


def down(path, limit=None, user=False):
    """Every simple path from path[-1] to the roles it holds, recursively (path itself included).
    limit: max hops from path[0] (None = every level). user: path[0] is a user, not a role, so a role of the same
    name is not on the path (users and roles are separate namespaces)."""
    if limit is not None and len(path) - 1 > limit:
        return
    yield path
    nxt = [r for r in holds.get(path[-1], []) if r not in path[user:]]
    if nxt and not stop(path, limit):
        for r in nxt:
            yield from down(path + [r], limit, user)


def up(path, limit=None):
    """Every simple path from path[-1] up to the roles and users that hold it. limit: max hops from path[0].
    A user ends a path as its graph node id (uid), so user X and role X holding the same role stay apart."""
    yield path
    nxt = [r for r in held_by.get(path[-1], []) if r not in path]
    us = users if path[-1] == "PUBLIC" else users_of.get(path[-1], [])  # every user holds PUBLIC; it is never listed
    if (nxt or us) and not stop(path, limit):
        for r in nxt:
            yield from up(path + [r], limit)
        for u in us:
            yield path + [uid(u, True)]


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


def users_through(name, user=False):
    """Users who reach a role (every user for PUBLIC); user=True: the user name itself."""
    return {name} if user else ups(name)[1]


def ups(role):
    """(roles that reach role, itself included; users who reach it), once per data set. Reach only, no paths, so
    big accounts stay fast."""
    def make():
        seen, todo, out = {role}, [role], set()
        while todo:
            r = todo.pop()
            out.update(users if r == "PUBLIC" else users_of.get(r, []))
            for p in held_by.get(r, []):
                if p not in seen:
                    seen.add(p)
                    todo.append(p)
        return seen, out
    return cached(("ups", role), make)


def best_paths(name, user=False):
    """{role: shortest path name->...->role} for every role name reaches, once per data set."""
    return cached(("best", name, user), lambda: paths_from(starts(name, user)))


def starts(name, user=False, default_only=False):
    """Start paths: [role], or [user, role] per granted role. default_only: only paths to the user's default role
    (it may be inherited, not granted directly)."""
    if not user:
        return [[name]]
    paths = [[name, r] for r in roles_of.get(name, [])]
    if default_only:
        dr = (profile.get(name) or {}).get("DEFAULT_ROLE")
        paths = [p for s in paths for p in down(s, user=True) if p[-1] == dr]
    got = {r for p in paths for r in p[1:]}
    return paths + ([] if "PUBLIC" in got else [[name, "PUBLIC"]])  # every user holds PUBLIC; it is never listed


def walk(name, user=False, default_only=False, limit=None):
    """Every role path from a user or role: [name, ..., role]. limit: max depth (see depth())."""
    hops = None if limit is None else limit - (0 if user else 1)
    return [p for s in starts(name, user, default_only) for p in down(s, hops, user)]


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
        u = node_kind(p[0]) == "user"
        for i, n in enumerate(p):
            d = (len(p) - i - (u and i == 0)) if up_paths else i + (not u)
            out.setdefault(n, {}).setdefault(d, p[i:] if up_paths else p[:i + 1])
    return out


# ---------- fast walks: path counts without enumerating, shortest by BFS, chains listed lazily (MAX_PATHS) ----------

def dag(sts):
    """Role links reachable from the start paths, minus the links that close a loop (depth-first back edges):
    {role: [child roles]}, in holds order. Duplicate grant rows stay, so they count twice as in down()."""
    kids, state = {}, {}
    for s in sts:
        if s[-1] in state:
            continue
        state[s[-1]], kids[s[-1]] = 1, []
        stack = [(s[-1], iter(holds.get(s[-1], [])))]
        while stack:
            v, it = stack[-1]
            r = next(it, None)
            if r is None:
                state[v] = 2
                stack.pop()
            elif state.get(r) != 1:  # 1 = on the current branch: the link closes a loop
                kids[v].append(r)
                if r not in state:
                    state[r], kids[r] = 1, []
                    stack.append((r, iter(holds.get(r, []))))
    return kids


def top_hop(hops):
    return MAX_HOPS if hops is None else min(hops, MAX_HOPS)


def counts(sts, kids, hops):
    """Number of paths from the start paths to every role, layer by layer (hop = len(path) - 1): {role: n}.
    Marks the start in capped when MAX_HOPS cuts paths, as down() does."""
    start = {}
    for s in sts:
        start.setdefault(len(s) - 1, {}).setdefault(s[-1], 0)
        start[len(s) - 1][s[-1]] += 1
    out, cur, top = {}, {}, top_hop(hops)
    for h in range(min(start, default=0), top + 1):
        for r, n in start.get(h, {}).items():
            cur[r] = cur.get(r, 0) + n
        if not cur and h >= max(start, default=0):
            break
        nxt = {}
        for v, n in cur.items():
            out[v] = out.get(v, 0) + n
            for r in kids[v]:
                nxt[r] = nxt.get(r, 0) + n
        if h == top and nxt and h == MAX_HOPS and (hops is None or hops > MAX_HOPS):
            capped.add(sts[0][0])
        cur = nxt
    return out


def shortest(sts, kids, hops):
    """Shortest path to every role (BFS over the same links as counts()): {role: path}."""
    best, top = {}, top_hop(hops)
    todo = sorted(sts, key=len)
    while todo:
        nxt = []
        for p in todo:
            if p[-1] not in best:
                best[p[-1]] = p
                if len(p) - 1 < top:
                    nxt += [p + [r] for r in kids[p[-1]] if r not in best]
        todo = nxt
    return best


def listed(sts, kids, hops, targets, cap=None):
    """Paths from the start paths to any role in targets, in down() order, at most cap (MAX_PATHS)."""
    cap, top = cap or MAX_PATHS, top_hop(hops)
    ups = {}
    for v, rs in kids.items():
        for r in rs:
            ups.setdefault(r, []).append(v)
    keep, todo = set(targets), list(targets)  # roles that lead to a target
    while todo:
        for v in ups.get(todo.pop(), []):
            if v not in keep:
                keep.add(v)
                todo.append(v)
    out = []

    def go(p, block):
        if len(out) >= cap:
            return
        if p[-1] in targets:
            out.append(p)
        if len(p) - 1 < top:
            for r in kids[p[-1]]:
                if r in keep and r not in block:
                    go(p + [r], block)

    for s in sts:
        if s[-1] in keep:
            go(s, set(s[1:-1]))
    return out


def fast(name, user=False, default_only=False, limit=None):
    """The walk of name as (starts, links, counts, hops); limit: max depth (see depth())."""
    hops = None if limit is None else limit - (0 if user else 1)
    sts = [s for s in starts(name, user, default_only) if hops is None or len(s) - 1 <= hops]
    kids = dag(sts)
    return sts, kids, counts(sts, kids, hops), hops


def capped_paths(ps, count, best):
    """Shortest first; when the list is cut, the shortest path (best) is always in it."""
    if count > len(ps) and best not in ps:
        ps = ps[:-1] + [best]
    return sorted(ps, key=len)


def paths_note(row):
    """"first 200 of 1,234" when a row lists fewer chains than it has, else ""."""
    return f"first {len(row['paths'])} of {row['count']:,}" if row["count"] > len(row["paths"]) else ""


# ---------- graph inputs (ui.lane_graph): lanes, edges, notes; one box per node at its shortest depth ----------

def notes(ch, nodes, word="D{}"):
    """{node: (badge, tooltip)}: badge "D2 · also D3" when a node is reached at more than one depth; the tooltip
    lists every depth with its chain."""
    out = {}
    for n in nodes:
        ds = sorted(ch.get(n, {}))
        if ds:
            more = ", ".join(word.format(d) for d in ds[1:]) if len(ds) < 5 else \
                f"{word.format(ds[1])}…{word.format(ds[-1])}"  # a short badge; the tooltip has every depth
            badge = word.format(ds[0]) + " · also " + more if len(ds) > 1 else ""
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


def down_graph(start, rows, walked=(), user=None):
    """User page / Can they? graph: grants() rows (as shown) + walk() paths of roles without grants. user: start is a
    user (None: kind_of). Returns (lanes, edges, notes) or None when nothing is reached."""
    user = kind_of(start) == "user" if user is None else user
    sid = uid(start, user)
    part = [[sid] + x[1:] for x in [x[:-1] for r in rows for x in r["paths"]] + list(walked)]
    if not part:
        return None
    ch = chains(part)
    d = {n: min(v) for n, v in ch.items()}
    nodes = set(d) - {sid}
    objs = list(dict.fromkeys(r["object"] for r in rows))
    first = 1 if user else 2  # a role start is depth 1 itself
    lanes = ([("User" if user else "Role", [sid])]
             + by_depth(nodes, d, "Depth {}", range(first, max([d[n] for n in nodes] + [0]) + 1))
             + [("Object" if len(objs) == 1 else "Objects", objs)])
    return lanes, role_links(part) + priv_links(rows), notes(ch, nodes)


def object_graph(obj, kind, shown, users):
    """Object page graph: grantees() rows as shown and the users drawn. Lanes follow the chain (a role sits right of
    every user or role holding it: longest chain from a start), so every line runs left to right; badges give the
    depth from the start as on every page, plus "also grant holder" on a holder that also holds roles drawn here.
    Returns (lanes, edges, notes) or None."""
    paths = [tagged(x[:-1], row["kind"]) for row in shown for x in row["paths"]]
    if not paths:
        return None
    links = role_links(paths)
    users = [uid(u, True) for u in users]
    lane = {}
    for p in paths:
        for i, n in enumerate(p):
            lane.setdefault(n, 0 if i == 0 and node_kind(n) == "user" else 1)
    for _ in lane:  # longest chain; at most one pass per node, so a loop can't hang it
        moved = False
        for x, y in links:
            if lane[y] <= lane[x]:
                lane[y], moved = lane[x] + 1, True
        if not moved:
            break
    nodes = set(lane) - set(users)
    lanes = ([("Users", [u for u in users if u in lane])]
             + by_depth(nodes, lane, "Depth {}", range(1, max([lane[n] for n in nodes] + [0]) + 1)) + [("Object", [obj])])
    edges = links + priv_links([dict(privilege=x["privilege"], type=kind, paths=x["paths"]) for x in shown])
    out = notes(chains(paths), nodes)
    for n in {p[-1] for p in paths} & {x for x, _ in links}:
        badge, tip = out.get(n, ("", ""))
        out[n] = (" · ".join(filter(None, [badge, "also grant holder"])),
                  "\n".join(filter(None, [tip, f"Also a grant holder: its own grant on {obj}, besides the roles it holds."])))
    return lanes, edges, out


def tagged(p, kind):
    """A path whose start has this kind, with the start as its graph node id (uid)."""
    return [uid(p[0], kind == "user")] + p[1:]


def role_graph(role, up_rows, writes=()):
    """Role page graph: held() rows as shown (up), the role, what it holds (down) and the stray writes of a read-only
    role (writes: readonly_writes(role) rows). Lanes by depth, as in held(): the role is D1, a role holding it D2, ...;
    users in their own lane on the left. Returns (lanes, edges, notes, selected lane)."""
    paths = [tagged(x, row["kind"]) for row in up_rows for x in row["paths"]]
    ch = chains(paths, True)
    d = {n: min(v) for n, v in ch.items()}
    us = sorted(n for n in d if n != role and node_kind(n) == "user")
    nodes = set(d) - set(us) - {role}
    far = max([d[n] for n in nodes] + [1])
    hold, kids = holds_of(role), sorted(holds.get(role, []))
    objs = list(dict.fromkeys(h["object"] for h in hold)) + [BUILTIN_NODE] * (role == "PUBLIC" and bool(hidden))
    stray = [x for x in writes if x["inherited"] and x["holder"] in kids and x["object"] not in objs]
    lanes = ([("Users", us)] if us else []) + by_depth(nodes, d, "Depth {}", range(far, 1, -1))
    sel = len(lanes)
    lanes += [("Depth 1 · Selected role", [role]), ("Holds", kids + objs)]
    if stray:
        lanes.append(("Writes through held roles", list(dict.fromkeys(x["object"] for x in stray))))
    edges = role_links(paths) + [(role, x) for x in kids] + list(dict.fromkeys(
        (role, h["object"], h["cls"], h["privilege"]) for h in hold))
    edges += [(role, BUILTIN_NODE, "use", "USAGE")] * (BUILTIN_NODE in objs)
    edges += [(x["holder"], x["object"], priv_class(pv, kinds.get(x["object"], "")), pv) for x in stray
              for pv in x["privileges"]]
    return lanes, edges, notes(ch, nodes), sel


def access_of(name, user=False, default_only=False, limit=None):
    """Privileges of a user or role: rows (privilege, type, object, path user->...->role)."""
    return [(pv, k, o, p) for p in walk(name, user, default_only, limit) for pv, k, o in granted.get(p[-1], [])]


def admin_paths(name, user=False, default_only=False, limit=None):
    """Paths from a user or role to an admin role it holds (at most MAX_PATHS)."""
    sts, kids, cnt, hops = fast(name, user, default_only, limit)
    return listed(sts, kids, hops, {r for r in cnt if r in ADMIN and r != name})


def account_privs(name, user=False, default_only=False, limit=None):
    """Account-level privileges (MANAGE GRANTS, CREATE DATABASE, ...): rows (privilege, path), at most MAX_PATHS
    paths."""
    sts, kids, cnt, hops = fast(name, user, default_only, limit)
    hs = {r for r in cnt if any(k == "ACCOUNT" for _, k, _ in granted.get(r, []))}
    return [(pv, p) for p in listed(sts, kids, hops, hs) for pv, k, o in granted[p[-1]] if k == "ACCOUNT"]


def admin_holders():
    """Users and roles holding an admin role: rows (grantee, path grantee->...->admin role)."""
    return [(node_name(p[-1]), p[::-1]) for r in sorted(ADMIN) for p in list(up([r]))[1:]]


def from_user(path):
    """path grantee->...->role (from up()) starts at a user, not at a role of the same name (see uid)."""
    return len(path) > 1 and path[0] not in cached("rset", lambda: set(roles))


def who_can(obj, kind=None, limit=None):
    """Who has which privilege on obj (of type kind): rows (grantee, privilege, path grantee->...->holder).
    limit: max depth (grant holder = 1, see depth())."""
    rows = [(node_name(p[-1]), pv, p[::-1]) for r, pv, k in on.get(obj, []) if kind in (None, k) for p in up([r], limit)]
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
    """clear | masked | ? for a column (col) or the rows (col None: all rows = clear, filtered or no rows = masked) of
    obj, when name is in use. Short form of data_view(), which gives the reason."""
    v = data_view(name, obj)
    x = next((c for c in v["columns"] if c["column"] == col), None) if col else v["rows"]
    return {"clear": "clear", "all": "clear", "masked": "masked", "filtered": "masked", "none": "masked"}.get(
        x["state"] if x else "clear", "?")


HOW = {"session": "in session", "primary": "primary role"}
HOW_NOTE = {"session": "in session = the role or any role it inherits", "primary": "primary role = only the role in USE ROLE"}


def split_top(s, word):
    """s split on the keyword word (AND / OR) outside quotes and brackets."""
    out, depth, q, start, i, n = [], 0, False, 0, 0, len(word)
    while i < len(s):
        ch = s[i]
        if ch == "'":
            q = not q
        elif not q and ch == "(":
            depth += 1
        elif not q and ch == ")":
            depth -= 1
        elif (not q and depth == 0 and s[i:i + n].upper() == word and (i == 0 or not (s[i - 1].isalnum() or s[i - 1] == "_"))
              and (i + n == len(s) or not (s[i + n].isalnum() or s[i + n] == "_"))):
            out.append(s[start:i])
            start = i = i + n
            continue
        i += 1
    return [x.strip() for x in out + [s[start:]]]


def unwrap(s):
    """s without brackets around all of it."""
    s = s.strip()
    while s.startswith("(") and s.endswith(")"):
        depth = 0
        for i, ch in enumerate(s):
            depth += (ch == "(") - (ch == ")")
            if depth == 0 and i < len(s) - 1:
                return s
        s = s[1:-1].strip()
    return s


def row_terms(p):
    """A row access policy body (pol() dict) as OR-terms when it is simple: [dict(roles=[[(role, how), ...] (any of),
    ...] (all of), conds=[condition on an argument column])]. None when not derivable: mapping table, function, NOT,
    CASE, user or account checks, a condition that does not use an argument column (ARG_COLUMNS)."""
    c = p["clear"]
    if c is None or not c[1]:
        return None
    args = [x.upper() for x in re.findall(r"[A-Za-z_][A-Za-z0-9_$]*", p.get("args") or "")]
    out = []
    for term in split_top(unwrap(p["body"]), "OR"):
        t = dict(roles=[], conds=[])
        for atom in map(unwrap, split_top(unwrap(term), "AND")):
            u = re.sub(r"'[^']*'", "''", atom).upper()
            m = re.fullmatch(r"IS_ROLE_IN_SESSION\s*\(\s*'([^']+)'\s*\)", atom, re.I)
            m2 = re.fullmatch(r"CURRENT_ROLE\s*\(\s*\)\s*=\s*'([^']+)'", atom, re.I)
            m3 = re.fullmatch(r"CURRENT_ROLE\s*\(\s*\)\s+IN\s*\(([^)]*)\)", atom, re.I)
            if m:
                t["roles"].append([(m.group(1).upper(), "session")])
            elif m2:
                t["roles"].append([(m2.group(1).upper(), "primary")])
            elif m3:
                t["roles"].append([(r.upper(), "primary") for r in re.findall(r"'([^']+)'", m3.group(1))])
            elif (re.search(r"\b(NOT|CASE|IS_ROLE_IN_SESSION|CURRENT_ROLE)\b", u)
                  or not any(re.search(rf"\b{re.escape(x)}\b", u) for x in args)):
                return None
            else:
                t["conds"].append(atom)
        if not t["roles"] and not t["conds"]:
            return None
        out.append(t)
    return out


def ok_for(group, name, user, inside):
    """One role check of a policy holds for name: IS_ROLE_IN_SESSION when the role is inside name's hierarchy;
    CURRENT_ROLE() when name is that role (a user may USE ROLE any role they hold)."""
    return any(r in inside if how == "session" or user else r == name for r, how in group)


def either(pairs):
    return " or ".join(f"{r} ({HOW[h]})" for r, h in dict.fromkeys(pairs))


def notes_for(pairs):
    return " (" + "; ".join(HOW_NOTE[h] for h in sorted({h for _, h in pairs})) + ")" if pairs else ""


def neither(n):
    return "does not hold it" if n == 1 else "holds neither" if n == 2 else "holds none of them"


def row_view(name, user, p, inside):
    """Rows name sees under row access policy p: dict(state all | filtered | none | unknown, reason, policy, body,
    condition)."""
    short, terms = p["name"].split(".")[-1], row_terms(p)
    out = dict(policy=p["name"], body=p["body"], condition=None)
    if terms is None:
        return out | dict(state="unknown", reason=f"{short}: unknown, depends on policy logic (mapping table, function "
                                                  "or other conditions), not derived from the policy text")
    pairs = [x for t in terms for g in t["roles"] for x in g]
    for t in terms:
        if t["roles"] and not t["conds"] and all(ok_for(g, name, user, inside) for g in t["roles"]):
            hit = [x for g in t["roles"] for x in g if ok_for([x], name, user, inside)]
            r = hit[0][0]
            how = "holds it" if user else "is that role" if r == name else f"inherits {r}"
            return out | dict(state="all", reason=f"{short} allows {either(hit)}; {name} {how} -> sees all rows"
                                                   + notes_for(hit))
    conds = [" AND ".join(t["conds"]) for t in terms if t["conds"] and all(ok_for(g, name, user, inside)
                                                                           for g in t["roles"])]
    if conds:
        cond = " OR ".join(conds)
        return out | dict(state="filtered", condition=cond,
                          reason=f"{short} lets {name} see only rows where {cond}" + notes_for(pairs))
    n = len(dict.fromkeys(r for r, _ in pairs))
    return out | dict(state="none", reason=f"{short} allows only {either(pairs)}; {name} {neither(n)} -> sees no rows"
                                           + notes_for(pairs))


def col_view(name, user, ps, inside):
    """A column for name: dict(state clear | masked | unknown, reason, policy, body); ps: its masking policies."""
    if not ps:
        return dict(state="clear", reason="no masking policy", policy=None, body=None)
    p = min(ps, key=lambda p: p["via"] is not None)  # a direct policy wins over a tag-based one
    short, c = p["name"].split(".")[-1], p["clear"]
    out = dict(policy=p["name"], body=p["body"])
    if c is None or not c[1]:
        return out | dict(state="unknown", reason=f"{short}: unknown, depends on policy logic (mapping table, function, "
                                                  "user or account checks), not derived from the policy text")
    pairs = list(c[0].items())
    hit = [x for x in pairs if ok_for([x], name, user, inside)]
    if hit:
        return out | dict(state="clear", reason=f"{short} shows the value to {either(hit)}; {name} holds it"
                                                 + notes_for(hit))
    if not pairs:
        return out | dict(state="masked", reason=f"{short} masks the value for every role")
    return out | dict(state="masked", reason=f"{short} shows the value only to {either(pairs)}; {name} "
                                             f"{neither(len(pairs))} -> masked" + notes_for(pairs))


def data_view(name, obj, user=None):
    """What name (a role used as primary role, or a user with any role they hold) sees of table/view obj, from the
    policy text (not evaluated; never more certain than the text). Returns dict(object, name, can_read (reaches
    SELECT or OWNERSHIP), tags [labels on the object, inherited ones included], columns [dict(column, tags, sensitive,
    state clear | masked | unknown, reason, policy, body)] for every tagged or masked column, rows dict(state all |
    filtered | none | unknown, reason, policy, body, condition), summary)."""
    user = kind_of(name) == "user" if user is None else user
    inside = {r for s in starts(name, user) for r in bfs(s)}
    ps, tg, sc = policies_of(obj), tags_of(obj), sensitive_cols(obj)
    cols = sorted(set(ps["columns"]) | {c for c, *_ in tg if c})
    columns = [dict(column=c, tags=[tag_label(t, v) for x, t, v, _ in tg if x == c], sensitive=c in sc,
                    **col_view(name, user, ps["columns"].get(c, []), inside)) for c in cols]
    rows = row_view(name, user, ps["rows"][0], inside) if ps["rows"] else \
        dict(state="all", reason="no row access policy", policy=None, body=None, condition=None)
    read = any(pv in READ_PRIVS and o == obj for r in inside for pv, k, o in granted.get(r, []))
    seen = {"all": "all rows", "filtered": "filtered rows", "none": "no rows", "unknown": "rows unknown"}[rows["state"]]
    bits = [seen] + [f"{c['column']} {c['state']}" for c in columns if c["state"] != "clear"]
    return dict(object=obj, name=name, can_read=read, tags=[f"{tag_label(t, v)} ({o})" for c, t, v, o in tg if not c],
                columns=columns, rows=rows,
                summary=("can read: " + ", ".join(bits)) if read else "cannot read it (no SELECT or OWNERSHIP)")


def data_views(name, user=None):
    """data_view() of every table/view name can read that has a tag or a policy (the per-role / per-user summary)."""
    out = []
    for o in objects:
        if is_data(kinds[o]) and (tags_of(o) or policies_of(o)["columns"] or policies_of(o)["rows"]):
            v = data_view(name, o, user)
            if v["can_read"]:
                out.append(v)
    return out


def policy_text(p):
    """One line for a policy card (pol() dict), e.g. "RAP_REGION: all rows for F_FINANCE (in session) or F_DEPLOY
    (primary role); everyone else: no rows"."""
    short = p["name"].split(".")[-1]
    if p["kind"] == "ROW_ACCESS_POLICY":
        terms = row_terms(p)
        if terms is None:
            return f"{short}: rows unknown for every role, depends on policy logic (not derived from the text)"
        parts = [(" and ".join(either(g) for g in t["roles"]) or "every role") + ": "
                 + (f"only rows where {' AND '.join(t['conds'])}" if t["conds"] else "all rows") for t in terms]
        rest = next((f"only rows where {' AND '.join(t['conds'])}" for t in terms if not t["roles"]), "no rows")
        return f"{short}: " + "; ".join(parts) + f"; everyone else: {rest}"
    c = p["clear"]
    if c is None or not c[1]:
        return f"{short}: masked or clear depends on policy logic (not derived from the text)"
    return f"{short}: clear for {either(c[0].items())}; everyone else: masked" if c[0] else f"{short}: masked for every role"


def governance_rows():
    """Tables and views with a tag or a policy. Row: object, kind, tags [object tags, inherited included],
    column_tags {column: [labels]}, masking {column: [policy names]}, row_policies [names], sensitive."""
    out = []
    for o in objects:
        if not is_data(kinds[o]):
            continue
        tg, ps = tags_of(o), policies_of(o)
        if tg or ps["columns"] or ps["rows"]:
            ct = {}
            for c, t, v, _ in tg:
                if c:
                    ct.setdefault(c, []).append(tag_label(t, v))
            out.append(dict(object=o, kind=kinds[o], tags=[tag_label(t, v) for c, t, v, _ in tg if not c],
                            column_tags=ct, masking={c: [x["name"] for x in v] for c, v in ps["columns"].items()},
                            row_policies=[x["name"] for x in ps["rows"]], sensitive=o in sens))
    return out


def governance_kpis():
    """Account KPIs: dict(row_tables, masked_columns, tagged_objects, text {label: "N tables" | "not used"})."""
    rows = len({p["OBJECT_NAME"] for p in policies if p["POLICY_KIND"] == "ROW_ACCESS_POLICY" and p["OBJECT_NAME"]})
    cols = sum(len(policies_of(o)["columns"]) for o in objects if is_data(kinds[o]))
    tagged = len({t["OBJECT_NAME"] for t in tags})
    text = {label: plural(n, word) if n else "not used" for label, n, word in [
        ("Row access policies used", rows, "table"), ("Masking", cols, "column"), ("Tags", tagged, "object")]}
    return dict(row_tables=rows, masked_columns=cols, tagged_objects=tagged, text=text)


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
    return set().union(*(ups(r)[1] for r, pv, k in on.get(obj, []) if pv in READ_PRIVS))


def read_roles(obj):
    """Roles that can read obj (READ_PRIVS, any path), the holders included."""
    return set().union(*(ups(r)[0] for r, pv, k in on.get(obj, []) if pv in READ_PRIVS))


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
                        roles=sorted(read_roles(o))))
    return sorted(out, key=lambda r: (-len(r["people"]) - len(r["disabled"]) - len(r["service"]), r["object"]))


PII_TAGS = re.compile(os.environ.get("PII_TAGS", "IDENTIFIER|PII|PERSONAL"), re.I)  # catalog filter "PII / identifiers"
CONF_TAGS = re.compile(os.environ.get("CONFIDENTIAL_TAGS", "CONFIDENTIAL|SECRET|RESTRICTED"), re.I)
PROTECTION = ("not", "partly", "protected", "whole")  # most exposed first


def protection(cols, k):
    """not (no sensitive column masked) | partly | protected | whole (tagged as a whole object, no columns)."""
    return "whole" if not cols else "not" if not k else "partly" if k < len(cols) else "protected"


def catalog():
    """Screen 8: sensitive_rank() rows with protection (status, columns [dict(column, masked, policies)], unmasked),
    labels (tag=value), groups (pii / confidential from the tag values) and readers (users who can read it, any
    path). Most exposed first: status, then unmasked columns, then readers."""
    out = []
    for r in sensitive_rank():
        ps = policies_of(r["object"])["columns"]
        cols = [dict(column=c, masked=c in ps, policies=[p["name"] for p in ps.get(c, [])]) for c in r["cols"]]
        labs = list(dict.fromkeys(tag_label(t, v) for _, t, v, _ in r["tags"]))
        out.append(r | dict(status=protection(r["cols"], r["masked"][0]), columns=cols,
                            unmasked=sum(not c["masked"] for c in cols), labels=labs, readers=len(r["users"]),
                            groups=[g for g, rx in (("pii", PII_TAGS), ("confidential", CONF_TAGS))
                                    if any(rx.search(x) for x in labs)]))
    return sorted(out, key=lambda r: (PROTECTION.index(r["status"]), -r["unmasked"], -r["readers"], r["object"]))


ADMIN_BOX = "Admin roles"  # flow: a user holding an admin role reaches every object through it
FLOW_WORD = dict(active="Active people", risky="Dormant or disabled", admin="Admins", service="Service users")


def flow_group(u, adm):
    """Flow column 1: admin | risky (dormant, disabled, never logged in) | service | active."""
    return "admin" if u in adm else "risky" if status(u) != "active" else "service" if is_service(u) else "active"


def sens_flow(max_roles=None):
    """Screen 16, where sensitive data flows: people (by flow_group) -> the role they were granted (first role on the
    path) -> sensitive object they read (READ_PRIVS). Admin users go through one ADMIN_BOX to every sensitive object.
    Over max_roles roles, those with the fewest users fold into "Other roles (N)". Returns dict(groups, roles,
    objects, links): nodes dict(id, label, users), roles also kind, objects also ns, status, unmasked, masked,
    row_policies; links dict(source, target, users): the users that flow over the link."""
    s, adm = sensitive(), admin_users()
    via = {}  # (granted role, object) -> users
    for o in s:
        for x, pv, p in who_can(o):
            if pv in READ_PRIVS and from_user(p) and x not in adm:
                via.setdefault((p[1], o), set()).add(x)
        if adm:
            via.setdefault((ADMIN_BOX, o), set()).update(adm)
    per = {}
    for (r, o), us in via.items():
        per.setdefault(r, set()).update(us)
    keep = sorted(per, key=lambda r: (r != ADMIN_BOX, -len(per[r]), r))
    other = set(keep[max_roles or MAX_OBJECTS:])
    box = lambda r: f"Other roles ({len(other)})" if r in other else r
    links, roles = {}, {}
    for (r, o), us in via.items():
        links.setdefault((box(r), o), set()).update(us)
    for r in keep:
        roles.setdefault(box(r), set()).update(per[r])
        for u in per[r]:
            links.setdefault((flow_group(u, adm), box(r)), set()).add(u)
    every = set().union(*per.values()) if per else set()
    cat = {r["object"]: r for r in catalog()}
    objs = [dict(id=o, label=split_name(o)[2] or o, ns=".".join(split_name(o)[:2]), status=cat[o]["status"],
                 unmasked=[c["column"] for c in cat[o]["columns"] if not c["masked"]],
                 masked=[c["column"] for c in cat[o]["columns"] if c["masked"]], row_policies=cat[o]["row_policies"],
                 users=sorted(set().union(*(us for (r, o2), us in via.items() if o2 == o))))
            for o in s]
    return dict(groups=[dict(id=g, label=w, users=sorted(u for u in every if flow_group(u, adm) == g))
                        for g, w in FLOW_WORD.items() if any(flow_group(u, adm) == g for u in every)],
                roles=[dict(id=r, label=r, users=sorted(us),
                            kind="admin" if r == ADMIN_BOX else "fold" if r not in per else role_kind(r))
                       for r, us in roles.items()],
                objects=sorted((o for o in objs if o["users"]), key=lambda o: (-len(o["users"]), o["id"])),
                links=[dict(source=x, target=y, users=sorted(us)) for (x, y), us in sorted(links.items())])


GRID_MAX = int(os.environ.get("GRID_MAX", "60"))  # review grid: object columns drawn, most-reached first


def grid_cell(rs, kind):
    """One review grid cell from [(privilege, path)]: level (highest obj_level), privileges, path (shortest)."""
    lv = lambda pv: OBJ_LEVELS.index(obj_level(pv, kind))
    pvs = sorted({pv for pv, _ in rs}, key=lambda pv: (-lv(pv), pv))
    return dict(level=obj_level(pvs[0], kind), privileges=pvs, path=min((p for _, p in rs), key=len))


def review_grid(scope="sensitive", db=None, obj=None, hide_usage=True, cap=GRID_MAX):
    """Screen 6: people x objects. scope sensitive (the sensitive objects), db (objects of database db) or all;
    obj: people x the privileges on that one object instead (columns = privileges). A cell: grid_cell(), path
    user->...->holder->object; a user holding an admin role has "admin" in every column. hide_usage drops USAGE
    (objects left without a cell drop out). Rows: user, type, status, days, admin (admin roles held), roles (granted
    roles on the paths: what a revoke takes away), cells {column id: cell}. Returns dict(columns, rows, total)."""
    adm, cells, roles = admin_users(), {}, {}
    if obj:
        k, got = kinds.get(obj, ""), {}
        for x, pv, p in who_can(obj):
            if from_user(p):
                got.setdefault(x, {}).setdefault(pv, []).append(p + [obj])
        pvs = sorted({pv for v in got.values() for pv in v}, key=lambda pv: (-OBJ_LEVELS.index(obj_level(pv, k)), pv))
        cols = [dict(id=pv, name=pv, ns=obj, note=obj_level(pv, k), sensitive=False) for pv in pvs]
        for x, v in got.items():
            cells[x] = {pv: dict(level=obj_level(pv, k), privileges=[pv], path=min(ps, key=len)) for pv, ps in v.items()}
            roles[x] = {p[1] for ps in v.values() for p in ps}
        total = len(cols)
    else:
        s, reach = sensitive(), {}
        objs = sorted(s) if scope == "sensitive" else \
            [o for o in objects if split_name(o)[0] and (scope != "db" or split_name(o)[0] == db)]
        for o in objs:
            got = {}
            for x, pv, p in who_can(o):
                if from_user(p) and not (hide_usage and pv == "USAGE"):
                    got.setdefault(x, []).append((pv, p + [o]))
            for x, rs in got.items():
                cells.setdefault(x, {})[o] = grid_cell(rs, kinds.get(o, ""))
                roles.setdefault(x, set()).update(p[1] for _, p in rs)
            if got:
                reach[o] = len(got)
        objs = sorted(reach, key=lambda o: (o not in s, -reach[o], o))
        total, objs = len(objs), set(objs[:cap])
        cols = [dict(id=o, name=split_name(o)[2] or o, ns=".".join(x for x in split_name(o)[:2] if x),
                     note=", ".join(sensitive_cols(o)) or ("whole object" if o in s else ""), sensitive=o in s)
                for o in sorted(objs, key=lambda o: (o not in s, -reach[o], o))]
        cells = {x: {o: v for o, v in cs.items() if o in objs} for x, cs in cells.items()}
    for u in adm:  # admin roles inherit every role: every column
        ps = admin_paths(u, True)
        cells[u] = {c["id"]: dict(level="admin", privileges=["ALL"], path=min(ps, key=len)) for c in cols}
        roles.setdefault(u, set()).update(q[1] for q in ps)
    rows = [dict(user=u, type=str((profile.get(u) or {}).get("TYPE") or "PERSON"), status=status(u), days=login_days(u),
                 admin=adm.get(u, []), roles=sorted(roles.get(u, set()) - {"PUBLIC"}), cells=cs)
            for u, cs in cells.items() if cs]
    rows.sort(key=lambda r: (not r["admin"], -max(OBJ_LEVELS.index(c["level"]) for c in r["cells"].values()),
                             -len(r["cells"]), r["user"]))
    return dict(columns=cols, rows=rows, total=total)


# ---------- page aggregations: plain lists of dicts ----------

def grants(name, user=False, default_only=False, limit=None):
    """User or role page (effective privileges, inherited included): one row per (privilege, type, object).
    Row: privilege, type, object, database, schema, name, cls (priv_class), holder, granted (depth-1 role: "Use role"),
    direct (held by the role itself), depth, path (shortest, name->...->holder->object), paths (shortest first, at
    most MAX_PATHS, see paths_note; shared between rows of one holder and object, do not change them), count (every
    path, counted without listing them), holders (every role holding the grant)."""
    sts, kids, cnt, hops = fast(name, user, default_only, limit)
    keys, best, per, done = {}, None, {}, {}
    for h in cnt:
        for pv, k, o in granted.get(h, []):
            keys.setdefault((pv, k, o), {}).setdefault(h, 0)
            keys[(pv, k, o)][h] += 1  # duplicate grant rows count twice, as in access_of()
    out = []
    for (pv, k, o), hs in sorted(keys.items(), key=lambda x: (x[0][2], x[0][0], x[0][1])):
        count = sum(cnt[h] * n for h, n in hs.items())
        ps = done.get((o, tuple(hs.items())))  # the privileges of one holder on one object share their path list
        if ps is None:
            if len(hs) == 1:
                h = next(iter(hs))
                if h not in per:
                    per[h] = listed(sts, kids, hops, {h})
                ps = [q + [o] for q in per[h] for _ in range(hs[h])][:MAX_PATHS]
            else:
                ps = [q + [o] for q in listed(sts, kids, hops, set(hs)) for _ in range(hs[q[-1]])][:MAX_PATHS]
            if count > len(ps):
                best = best or shortest(sts, kids, hops)
                ps = capped_paths(ps, count, min((best[h] for h in hs), key=len) + [o])
            else:
                ps = sorted(ps, key=len)
            done[(o, tuple(hs.items()))] = ps
        db, sc, nm = split_name(o, k)
        p = ps[0]
        out.append(dict(privilege=pv, type=k, object=o, database=db, schema=sc, name=nm, cls=priv_class(pv, k),
                        holder=p[-2], granted=p[1] if user else p[0], direct=len(p) == 2 and not user,
                        depth=depth(p[:-1], user), path=p, paths=ps, count=count, holders=sorted(hs)))
    return out


def reach(name, user=False, default_only=False, limit=None):
    """Roles a user or role reaches. Row: role, kind, depth (shortest, see depth()), direct (granted to name itself),
    path (shortest), paths (at most MAX_PATHS), count (every path)."""
    sts, kids, cnt, hops = fast(name, user, default_only, limit)
    best, out = shortest(sts, kids, hops), []
    for r, n in cnt.items():
        if user or r != name:
            ps = capped_paths(listed(sts, kids, hops, {r}), n, best[r])
            out.append(dict(role=r, kind=role_kind(r), depth=depth(ps[0], user), direct=len(ps[0]) == 2, path=ps[0],
                            paths=ps, count=n))
    return sorted(out, key=lambda x: (len(x["path"]), x["role"]))


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
    g = group(((node_name(p[-1]), from_user(p[::-1])), p[::-1]) for p in list(up([role], limit))[1:])
    out = []
    for (x, u), ps in sorted(g.items(), key=lambda x: (len(x[1][0]), x[0])):
        d = depth(ps[0], u)
        if limit is None or d <= limit:
            out.append(dict(grantee=x, kind="user" if u else role_kind(x), depth=d, direct=len(ps[0]) == 2, path=ps[0],
                            paths=ps,
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
    return dict(kind=role_kind(role), privileges=len(own), effective=len(grants(role)),
                future=sum(k.startswith("FUTURE") for _, k, _ in own),
                above=len(above), above_direct=sum(x["direct"] for x in above),
                users=len(us), users_direct=sum(x["direct"] for x in us),
                farthest=max((x["depth"] for x in h), default=0), holds_roles=sorted(holds.get(role, [])),
                sensitive=len(set(reads([role])) & set(sensitive())))


def grantees(obj, kind=None, limit=None):
    """Object page, all grantees: one row per (grantee, privilege). Row: grantee, kind, privilege, cls,
    depth (see depth(): grant holder = 1, ANALYST_01 on TBL_CUSTOMER = 3), path (shortest, grantee->...->holder->object),
    paths, count."""
    g = group(((x, from_user(p), pv), p + [obj]) for x, pv, p in who_can(obj, kind, limit))
    k0 = kind or kinds.get(obj)
    return [dict(grantee=x, kind="user" if u else role_kind(x), privilege=pv, cls=priv_class(pv, k0),
                 depth=depth(ps[0][:-1], u), path=ps[0], paths=ps, count=len(ps))
            for (x, u, pv), ps in sorted(g.items(), key=lambda x: (len(x[1][0]), x[0]))]


STANDARD = {"TABLE": {"SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES"}, "VIEW": {"SELECT", "REFERENCES"},
            "WAREHOUSE": {"USAGE", "OPERATE", "MODIFY", "MONITOR"}, "PROCEDURE": {"USAGE"}, "FUNCTION": {"USAGE"},
            "TASK": {"OPERATE", "MONITOR"}, "STREAM": {"SELECT"}, "STAGE": {"USAGE", "READ", "WRITE"},
            "SEQUENCE": {"USAGE"}, "PIPE": {"OPERATE", "MONITOR"}, "DYNAMIC TABLE": {"SELECT", "OPERATE", "MONITOR"},
            "SCHEMA": {"USAGE", "MONITOR", "CREATE TABLE", "CREATE VIEW"}, "DATABASE": {"USAGE", "MONITOR", "CREATE SCHEMA"}}


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
    ps = group((x, p) for x, p in admin_holders() if from_user(p))
    acct = {u: [(pv, p) for pv, p in account_privs(u, True) if not (p[-1] == "PUBLIC" and pv in DEFAULT_PUBLIC)]
            for u in users}  # Snowflake's defaults on PUBLIC: every user has them
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


# ---------- has / lacks ----------

def has_lacks(name, obj, user=False):
    """The privileges of obj's type (valid_privs) that name reaches on obj, directly or inherited, and the rest
    (OWNERSHIP left out):
    dict(type, has, lacks, implied (the rest when OWNERSHIP is held: it implies them), text, e.g.
    "SELECT, INSERT, UPDATE but not DELETE, TRUNCATE")."""
    k = kinds.get(obj, "")
    got = privs_on(name, user).get(obj, set())
    valid = valid_privs(k)
    has = [p for p in valid if p in got] + sorted(got - set(valid))
    rest = [p for p in valid if p not in got and p != "OWNERSHIP"]  # not owning is normal, not a gap
    lacks, implied = ([], rest) if "OWNERSHIP" in got else (rest, [])
    text = ", ".join(has) or "nothing"
    text += f" (OWNERSHIP implies {', '.join(implied)})" if implied else f" but not {', '.join(lacks)}" if has and lacks else ""
    return dict(type=k, has=has, lacks=lacks, implied=implied, text=text)


def privs_on(name, user=False):
    """{object: privileges name reaches on it, directly or inherited}, once per data set."""
    def make():
        got = {}
        for r in best_paths(name, user):
            for pv, k, o in granted.get(r, []):
                got.setdefault(o, set()).add(pv)
        return got
    return cached(("privs_on", name, user), make)


def has_lacks_summary(name, user=False):
    """Per role (or user): objects grouped by type and privilege set, largest group first.
    Row: type, has, lacks, implied, text, objects (names), count."""
    out = {}
    for o in sorted(o for o in privs_on(name, user) if kinds.get(o, "ACCOUNT") != "ACCOUNT"
                    and not kinds[o].startswith("FUTURE")):
        x = has_lacks(name, o, user)
        out.setdefault((x["type"], tuple(x["has"])), x | dict(objects=[]))["objects"].append(o)
    return sorted((x | dict(count=len(x["objects"])) for x in out.values()), key=lambda x: (-x["count"], x["type"]))


# ---------- big accounts: objects rolled up to schema / database ----------

CLS_ORDER = ["read", "write", "own", "use", "manage", "admin"]


def group_key(r, level):
    """Group of a grants() row: "DB.SCHEMA" (level schema) or "DB" (level database); an object outside any schema
    (level schema: a database grant such as CREATE SCHEMA) or outside any database (a warehouse) stays itself."""
    db, sc = r["database"], r["schema"]
    if level == "database":
        return db or r["object"]
    return f"{db}.{sc}" if sc else r["object"]


def in_scope(r, scope):
    """A grants() / holds_of() row inside scope ("DB.SCHEMA", or a database name); no scope: every row."""
    return not scope or r["database"] == scope or (bool(r["schema"]) and f'{r["database"]}.{r["schema"]}' == scope)


def scopes(rows):
    """Valid scopes (?schema=) of rows: their schemas and databases."""
    return {f'{r["database"]}.{r["schema"]}' for r in rows if r["schema"]} | {r["database"] for r in rows if r["database"]}


def finding_index():
    """Where the findings sit: ({graph node id: {finding index}}, {(from node id, to, privilege): {finding index}},
    findings list)."""
    def make():
        fs, nodes, edges = cached("findings", findings), {}, {}
        for i, f in enumerate(fs):  # keyed by graph node id (uid): a user's findings never land on a role of its name
            for n in {uid(f["grantee"], f["user"])} | ({f["path"][-1]} if len(f["path"]) > 1 else set()):
                nodes.setdefault(n, set()).add(i)
            if f["edge"]:
                x, y, pv = f["edge"]
                edges.setdefault((uid(x, f["user"] and x == f["grantee"]), y, pv), set()).add(i)
        return nodes, edges, fs
    return cached("findex", make)


def rules_of(ids):
    """[(num, severity, title)] of findings by index, one per rule, in rule order."""
    fs = finding_index()[2]
    nums = sorted({fs[i]["num"] for i in ids}, key=int)
    return [(n, SEVERITY.get(n, "Low"), RULES[n][0]) for n in nums]


def group_objects(rows, level="schema"):
    """grants() rows rolled up to schema ("DB.SCHEMA") or database: one row per group, most objects first.
    Row: group, level (schema | database | object for account-level objects), database, schema, objects (count),
    names, classes (read/write/own/use/manage/admin), sensitive (objects), findings (findings on its objects),
    holders (grant holder roles)."""
    out, fi, s = {}, finding_index()[0], sensitive()
    for r in rows:
        key = group_key(r, level)
        lv = ("schema" if level == "schema" and r["schema"] else "database" if level == "database" and r["database"]
              else "object")
        g = out.setdefault(key, dict(group=key, level=lv, database=r["database"],
                                     schema=r["schema"] if lv == "schema" else "", names=set(), classes=set(),
                                     holders=set()))
        g["names"].add(r["object"])
        g["classes"].add(r["cls"])
        g["holders"].update(r["holders"])
    res = []
    for g in out.values():
        names = sorted(g["names"])
        res.append(g | dict(objects=len(names), names=names, holders=sorted(g["holders"]),
                            classes=[c for c in CLS_ORDER if c in g["classes"]],
                            sensitive=sum(o in s for o in names),
                            findings=len({i for o in names for i in fi.get(o, ())})))
    return sorted(res, key=lambda g: (-g["objects"], g["group"]))


MAX_OBJECTS = 12  # objects drawn one by one; more roll up into groups (ui.lane_graph shows 12 boxes per lane)


def graph_input(start, schema=None, max_objects=MAX_OBJECTS, default_only=False, limit=None, user=None, otype=None,
                cat=None):
    """User / role graph for any account size: grants() of start (USAGE on databases and schemas left out). Over
    max_objects objects, objects become schema nodes, or database nodes when there are more schemas than that; an
    object outside a schema (a database grant, a warehouse) stays an object node. schema="DB.SCHEMA" (or a database
    name, see in_scope): only that scope's objects and the roles that reach them (grouped by schema, else by object
    type, if still over). user: start is a user (None: kind_of). None when nothing is reached. Returns dict(lanes,
    edges [(a, b) role links, (holder, object, cls, privilege), (holder, group, cls, privilege, objects)], notes (see
    notes()), info (graph_info() plus {group: count, noun, sensitive, findings}), kinds {group node: schema | database
    | type-group}, header e.g. "1,234 objects, grouped by schema", level (object | schema | database | type), shown,
    total, groups (group_objects() when grouped by schema or database), types {type-group: object type}).
    default_only, limit: as grants(). otype: only objects of this type ("TABLE"), drawn one by one. cat: only the
    privileges of this priv_cat() (a Privileges tab; "usage" keeps database and schema USAGE), no role without one."""
    user = kind_of(start) == "user" if user is None else user
    sid = uid(start, user)
    every = [r for r in grants(start, user, default_only, limit)
             if (priv_cat(r["privilege"], r["type"]) == cat if cat else
                 not (r["privilege"] == "USAGE" and r["type"] in ("DATABASE", "SCHEMA")))]
    rows = [r for r in every if in_scope(r, schema) and otype in (None, r["type"])]
    if not rows:
        return None
    objs = list(dict.fromkeys(r["object"] for r in rows))
    n_schemas = len({group_key(r, "schema") for r in rows})
    if len(objs) <= max_objects or otype:
        level = "object"
    elif schema and "." not in schema and n_schemas > 1:  # a database: its schemas
        level = "schema"
    elif schema:
        level = "type"
    else:
        level = "schema" if n_schemas <= max_objects else "database"

    def grouped(r):
        return level == "type" or bool(r["schema"] if level == "schema" else level == "database" and r["database"])

    def key(r):
        if not grouped(r):
            return r["object"]
        return f"{schema} · {r['type']}" if level == "type" else group_key(r, level)

    sts, kids, _, hops = fast(start, user, default_only, limit)
    if level == "object":
        part = [x[:-1] for r in rows for x in r["paths"]]
    else:  # one listing per holder, not per object: thousands of objects share a few hundred holders
        part = [p for h in sorted({h for r in rows for h in r["holders"]}) for p in listed(sts, kids, hops, {h})]
    if schema is None and not cat:  # roles that lead to no object still show
        part += list(shortest(sts, kids, hops).values())
    part = [[sid] + p[1:] for p in part]
    ch = chains(part)
    d = {n: min(v) for n, v in ch.items()}
    nodes = set(d) - {sid}
    ends = list(dict.fromkeys(key(r) for r in rows))
    word = {"object": "Object" if len(ends) == 1 else "Objects", "schema": "Schemas", "database": "Databases",
            "type": "Object types"}[level]
    lanes = ([("User" if user else "Role", [sid])]
             + by_depth(nodes, d, "Depth {}", range(1 if user else 2, max([d[n] for n in nodes] + [0]) + 1))
             + [(word, ends)])
    edges, per, members, okey = role_links(part), {}, {}, {}
    for r in rows:
        k = key(r)
        if grouped(r):
            members.setdefault(k, set()).add(r["object"])
            okey[r["object"]] = k
            for h in r["holders"]:
                per.setdefault((h, k, r["cls"], r["privilege"]), set()).add(r["object"])
    edges += priv_links([r for r in rows if not grouped(r)])
    edges += [(a, b, c, pv, len(o)) for (a, b, c, pv), o in per.items()]
    bi = builtin_info() if schema is None and not otype else None
    if bi and "PUBLIC" in nodes | {sid}:  # Snowflake's own grants: one fold box under PUBLIC
        lanes[-1] = (lanes[-1][0], lanes[-1][1] + [BUILTIN_NODE])
        edges.append(("PUBLIC", BUILTIN_NODE, "use", "USAGE", bi["objects"]))
    info, fi, sens = graph_info(lanes, edges, okey), finding_index()[0], sensitive()
    for g, os_ in members.items():
        info.setdefault(g, {}).update(count=len(os_), noun="object" if len(os_) == 1 else "objects",
                                      sensitive=sum(o in sens for o in os_),
                                      findings=len({i for o in os_ for i in fi.get(o, ())}))
    how = {"schema": ", grouped by schema", "database": ", grouped by database", "type": ", grouped by object type"}
    header = (f"{len(objs):,} {otype.lower() + ' ' if otype else ''}object{'s' * (len(objs) != 1)}"
              + (f" in {schema}" if schema else "")
              + how.get(level, ""))
    kinds_ = {g: "type-group" if level == "type" else level for g in members}
    nts = notes(ch, nodes)
    if bi and BUILTIN_NODE in lanes[-1][1]:
        kinds_[BUILTIN_NODE] = "fold"
        info[BUILTIN_NODE] = dict(count=bi["grants"], noun="built-in grants")
        nts[BUILTIN_NODE] = ("hidden", f"{bi['grants']} grants Snowflake makes to every account through PUBLIC, "
                                       f"{bi['objects']} objects: {', '.join(bi['roles'])}\nShow built-in draws them")
    return dict(lanes=lanes, edges=edges, notes=nts, info=info, kinds=kinds_, header=header, level=level,
                shown=len(objs), total=len({r["object"] for r in every}),
                groups=group_objects(rows, level) if level in ("schema", "database") else [],
                types={key(r): r["type"] for r in rows} if level == "type" else {})


SUMMARY_ROLES, SUMMARY_LANES = 30, 6  # over this many role boxes or role lanes a graph is drawn as a summary


def too_big(g):
    """Does a graph_input() graph need the summary? Role lanes counted as ui.fold_chain draws them: a run of 3+
    lanes of one role each is one lane."""
    sizes = [len(ns) for _, ns in g["lanes"][1:-1]]
    n, i = 0, 0
    while i < len(sizes):
        j = i
        while j < len(sizes) and sizes[j] == 1:
            j += 1
        i = j if j - i >= 3 else i + 1
        n += 1
    return sum(sizes) > SUMMARY_ROLES or n > SUMMARY_LANES


def summary(g):
    """A big graph_input() graph as start -> roles granted directly -> one "⋯ N roles ⋯" box per granted role (the
    roles between it and its grant holders) -> grant holders -> objects / groups. Granted roles and holders ranked by
    objects reached (ui.lane_graph shows the first 12, then "+N more"); no also-deeper links. Returns a copy of g with
    kinds[fold box] = "fold" and folded = the number of roles hidden in fold boxes."""
    lanes, edges = g["lanes"], g["edges"]
    sid, ends = lanes[0][1][0], lanes[-1][1]
    depth = {n: int(lab.split()[-1]) for lab, ns in lanes[1:-1] for n in ns}
    kids, objs = {}, {}
    for e in edges:
        if len(e) == 2:
            kids.setdefault(e[0], []).append(e[1])
        else:  # objects a holder grants on; a group counts its objects (the most of any privilege)
            t = objs.setdefault(e[0], {})
            t[e[1]] = max(t.get(e[1], 0), e[4] if len(e) > 4 else 1)
    objs = {h: sum(t.values()) for h, t in objs.items()}
    direct = lanes[1][1]
    below = {}
    for r in direct:
        seen, todo = set(), list(kids.get(r, []))
        while todo:
            x = todo.pop()
            if x not in seen and x != r:
                seen.add(x)
                todo += kids.get(x, [])
        below[r] = seen
    rank = lambda xs, n: sorted(xs, key=lambda x: (-n(x), x))
    reached = lambda r: sum(objs.get(h, 0) for h in below[r] | {r})
    direct = rank(direct, reached)
    by_end = {}
    for e in edges:
        if len(e) > 2 and e[0] not in direct:
            by_end.setdefault(e[1], set()).add(e[0])
    # the best holder of every object / group first, then the second best of each: no group is left without a line
    queues = [rank(hs, objs.get) for hs in by_end.values()]
    holders = list(dict.fromkeys(q[i] for i in range(max(map(len, queues), default=0)) for q in queues if i < len(q)))
    out, folds, notes, hidden = [(sid, r) for r in direct], [], {}, set()
    for i, r in enumerate(direct[:12]):  # lane_graph shows 12: no fold box for a granted role behind "+N more"
        mids = {x for x in below[r] if x not in objs and x not in direct}
        word = f"{len(mids)} role" + "s" * (len(mids) != 1)
        fid = f"⋯ {word} ⋯" + " " * i  # unique when two boxes fold as many roles
        if mids:
            folds.append(fid)
            hidden |= mids
            deep = max(depth.get(x, 0) for x in mids)
            notes[fid] = (f"down to D{deep}", f"{word} between {r} and its grant holders, the deepest at "
                                             f"depth {deep}\nShow full chain draws them")
            out.append((r, fid))
        for h in sorted(below[r] & set(holders)):
            out.append((r, h) if h in kids.get(r, []) or not mids else (fid, h))
    out += [e for e in edges if len(e) > 2]
    keep = set(direct) | set(holders) | {sid}
    new = [lanes[0], ("Granted roles", direct)] + [("Roles between", folds)] * bool(folds) \
        + [("Grant holders", holders)] * bool(holders) + [lanes[-1]]
    return g | dict(lanes=new, edges=out, notes={n: v for n, v in g["notes"].items() if n in keep} | notes,
                    kinds=g["kinds"] | {f: "fold" for f in folds}, folded=len(hidden))


def graph_info(lanes, edges, okey=None):
    """Rule hits and Has / Lacks of any graph (ui.lane_graph info): {node: {rules}} for the drawn nodes with
    findings, {(a, b, cls): {rules, has, lacks}} for the drawn edges a finding applies to, Has / Lacks on arrows into
    single objects. okey: {object: its group node} when objects are grouped (their findings go to the group)."""
    fi, fe, _ = finding_index()
    okey, info = okey or {}, {}
    drawn_nodes = {n for _, ns in lanes for n in ns}
    hit = {n: set(fi.get(n, ())) for n in drawn_nodes}
    for o, g in okey.items():
        hit[g] = hit.get(g, set()) | set(fi.get(o, ()))
    for n, ids in hit.items():
        if ids:
            info[n] = dict(rules=rules_of(ids))
    drawn = {e[:3] if len(e) > 2 else (e[0], e[1], "inherit"): e for e in edges}
    for (a, b, pv), ids in fe.items():
        k = (a, okey.get(b, b), priv_class(pv, kinds.get(b, ""))) if pv else (a, b, "inherit")
        if k in drawn:
            x = info.setdefault(k, {})
            x["rules"] = sorted(set(x.get("rules", [])) | set(rules_of(ids)), key=lambda t: int(t[0]))
    for k, e in drawn.items():
        if len(e) == 4 and e[1] in kinds:
            x = has_lacks(node_name(e[0]), e[1], node_kind(e[0]) == "user")
            info.setdefault(k, {}).update(has=x["has"], lacks=x["lacks"])
    return info


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


def role_sql(n):
    """ROLE R, or DATABASE ROLE DB.R for a database role, in GRANT / REVOKE."""
    return f"DATABASE ROLE {sql_obj(n)}" if role_kind(n) == "database" else f"ROLE {sql_name(n)}"


def revoke(e, pvs=None):
    """(infrastructure-as-code text, equivalent SQL) to remove one grant edge; pvs: several privileges of the same role
    on the same object, in one statement. OWNERSHIP can't be revoked in Snowflake, only transferred."""
    g, x, k = e["grantee"], e["to"], e["kind"]
    if e["priv"] is None:
        who = "USER" if e["user"] else "ROLE"
        return (f"Remove in the infrastructure-as-code repo: role {x} granted to {who.lower()} {g}",
                f"REVOKE {role_sql(x)} FROM {'USER ' + sql_name(g) if e['user'] else role_sql(g)};")
    pv, k = ", ".join(pvs or [e["priv"]]), k.replace("_", " ")  # DATABASE_ROLE -> DATABASE ROLE in SQL
    if k == "ACCOUNT":
        return (f"Remove in the infrastructure-as-code repo: {pv} on account granted to role {g}",
                f"REVOKE {pv} ON ACCOUNT FROM {role_sql(g)};")
    if k.startswith("FUTURE"):
        kk, where = k.replace("FUTURE ", "") + "S", x.rsplit(".", 1)[0]
        place = "SCHEMA " if "." in where else "DATABASE "
        return (f"Remove in the infrastructure-as-code repo: {pv} on future {kk.lower()} in {place.lower()}{where} "
                f"granted to role {g}", f"REVOKE {pv} ON FUTURE {kk} IN {place}{sql_obj(where)} FROM {role_sql(g)};")
    if pv == "OWNERSHIP":
        return (f"Transfer ownership in the infrastructure-as-code repo: {k.lower()} {x}, now owned by role {g}",
                f"GRANT OWNERSHIP ON {k} {sql_obj(x)} TO ROLE <new owner role> COPY CURRENT GRANTS;")
    return (f"Remove in the infrastructure-as-code repo: {pv} on {k.lower()} {x} granted to role {g}",
            f"REVOKE {pv} ON {k} {sql_obj(x)} FROM {role_sql(g)};")


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
    reach the role; a privilege edge -> users who no longer hold that privilege on the object. Once per edge."""
    return cached(("lose",) + tuple(e.values()), lambda: losing(e))


def losing(e):
    g, x, out = e["grantee"], e["to"], set()
    hs = {r for r, pv, k in on.get(x, []) if pv == e["priv"]} - {g}  # other holders of the privilege
    for v in users_through(g, e.get("user")):
        sts, kids, cnt, _ = cached(("walk", v), lambda: fast(v, True))  # counted, not listed: big accounts stay fast
        if e["priv"] is None:  # every path to x uses the link g -> x
            via = sum(s == [v, x] for s in sts) if e.get("user") else cnt.get(g, 0) * kids.get(g, []).count(x)
            if via == cnt.get(x, 0):
                out.add(v)
        elif not any(h in cnt for h in hs):
            out.add(v)
    return out


def losers(edges, priv, obj):
    """Users who no longer hold priv on obj once every edge in edges is cut (each of their paths uses one)."""
    gone = {(e["grantee"], e["to"]) for e in edges}
    us = set().union(*(users_through(e["grantee"], e.get("user")) for e in edges))
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
        if (pv == priv and not from_user(p) and role_kind(x) == "functional" and (x not in out or len(p) < len(out[x]))
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
        if len(p) > 3 and role_kind(p[-3]) in ("technical", "database"):
            how = f"inherited through {role_kind(p[-3])} role {p[-3]}"
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


def lanes(paths):
    """Can they? path lanes from can() paths (with privilege): one per distinct route user->...->holder->object with
    the privileges it carries, shortest first; and the roles on every lane (a place to cut; never PUBLIC)."""
    by = {}
    for q in paths:
        by.setdefault(tuple(q["path"]), []).append(q["privilege"])
    ls = sorted((dict(path=list(p), privileges=list(dict.fromkeys(v))) for p, v in by.items()),
                key=lambda x: (len(x["path"]), x["path"]))
    cut = [r for r in ls[0]["path"][1:-1] if r != "PUBLIC" and all(r in x["path"] for x in ls)] if ls else []
    return ls, cut


def cut_points(user, privs, obj):
    """Where to cut (Can they? Yes): one entry per grant link on every path from user to any of privs on obj, fewest
    side effects first. Entry: edges, iac, sql, people (users who lose one of privs on obj, net of their other paths),
    lost (the user's other privileges whose every path uses the link). OWNERSHIP held: transfer text, not a revoke."""
    acc = access_of(user, True)
    ps = [p + [obj] for pv, k, o, p in acc if pv in privs and o == obj]
    if not ps:
        return []
    pairs = [set(zip(p, p[1:])) for p in ps]
    by = {}
    for pv, k, o, p in acc:
        if o != obj:
            by.setdefault((pv, o), []).append(set(zip(p, p[1:])))
    out = []
    for i, (x, y) in enumerate(zip(ps[0], ps[0][1:])):
        if y == "PUBLIC" or x == "PUBLIC" or not all((x, y) in s for s in pairs):  # every user holds PUBLIC
            continue
        es = [holder_edge(x, pv, obj) for pv in privs if any(q == pv and o == obj for q, _, o in granted.get(x, []))] \
            if y == obj else [role_edge(x, y, i == 0)]
        iac, sql = fix_text(es)
        us = set().union(*(losers(es, pv, obj) for pv in privs))
        lost = 0 if y == obj else sum(all((x, y) in s for s in ss) for ss in by.values())
        out.append(dict(edges=es, iac=iac, sql=sql, people=sorted(us), lost=lost, order=i))
    return sorted(out, key=lambda r: (len(r["people"]), r["lost"], -r["order"]))


def reverse(obj, priv):
    """Reverse BFS from obj over the roles holding priv on it, up the role graph: {role: shortest path
    role->...->holder}."""
    best = {r: [r] for r, pv, k in on.get(obj, []) if pv == priv}
    todo = list(best)
    while todo:
        nxt = []
        for r in todo:
            for g in held_by.get(r, []):
                if g not in best:
                    best[g] = [g] + best[r]
                    nxt.append(g)
        todo = nxt
    return best


def brings(role, obj):
    """What else a role brings besides obj: extra (privilege rows), also [dict(level, count, where)] (other data objects
    per schema at their highest step, most first)."""
    def make():
        rows = grants(role)
        os_ = [x for x in access_objects([r for r in rows if r["object"] != obj]) if x["category"] == "data" and x["level"]]
        g = {}
        for x in os_:
            k = (x["level"], f"{x['database']}.{x['schema']}" if x["schema"] else x["database"] or x["object"])
            g[k] = g.get(k, 0) + 1
        also = sorted((dict(level=lv, count=n, where=w) for (lv, w), n in g.items()),
                      key=lambda e: (-e["count"], -LEVELS.index(e["level"]), e["where"]))
        return dict(extra=sum(r["object"] != obj for r in rows), also=also[:4])
    return cached(("brings", role, obj), make)


def suggestable(r):
    return r not in ADMIN and r != "PUBLIC" and not any(fnmatch.fnmatch(r, b) for b in BUILD) and not reaches_admin(r)


BROAD = int(os.environ.get("BROAD_PEOPLE", "1"))  # a nearest way that also gives the access to more people: a warning


def nearest(user, priv, obj, limit=5):
    """Can they? No: the nearest ways in. For each role R reaching priv on obj (reverse()) that the user does not reach
    (no admin, build or admin-reaching role, not PUBLIC): grant R to the user (1 grant; a database role can't be
    granted to a user: a new account role between, 2 grants) or to a role the user is granted directly (1 grant, but
    everyone holding that role gets it too). Ranked by grants needed, then people who would also get it, then what else
    R brings. Option: path (user[, via], R, ..., holder, obj), missing (index i: the link path[i] -> path[i+1] is
    missing), role, to, to_user, cost, people (others who would get it), holders (users holding R today), extra, also,
    rule1 (a technical role on a user or group role), broad (warning or None)."""
    have = set(best_paths(user, True))
    rev = {r: p for r, p in reverse(obj, priv).items() if r not in have and suggestable(r)}
    if not rev:
        return []
    already = set().union(*(ups(r)[1] for r, pv, k in on.get(obj, []) if pv == priv), {user})
    direct = [h for h in roles_of.get(user, []) if h != "PUBLIC" and role_kind(h) != "database"]
    out = []
    for r, p in rev.items():
        b, k = brings(r, obj), role_kind(r)
        base = dict(role=r, holders=len(ups(r)[1]), extra=b["extra"], also=b["also"])
        if k == "database":
            out.append(base | dict(path=[user, "<NEW_ROLE>"] + p + [obj], missing=0, to=user, to_user=True, cost=2,
                                   people=0, rule1=False, broad=None))
        else:
            out.append(base | dict(path=[user] + p + [obj], missing=0, to=user, to_user=True, cost=1, people=0,
                                   rule1=k == "technical", broad=None))
        for h in direct:
            n = len(ups(h)[1] - already)
            out.append(base | dict(path=[user, h] + p + [obj], missing=1, to=h, to_user=False, cost=1, people=n,
                                   rule1=k == "technical" and role_kind(h) == "group",
                                   broad=f"gives it to all {n} other people holding {h}" if n >= BROAD else None))
    out.sort(key=lambda o: (o["cost"], o["people"], o["rule1"], o["extra"], len(o["path"]), o["role"], o["to"]))
    return out[:limit]


def basic_priv(kind):
    """The privilege Can they? asks about when none is picked: read for data, else use."""
    return next((p for p in ("SELECT", "USAGE", "READ", "OPERATE", "MONITOR") if p in valid_privs(kind)), "OWNERSHIP")


def need_privs(kind, need):
    """Privileges a request needs: read (one read privilege), change (INSERT and UPDATE on a table, else the type's
    change privileges), own (OWNERSHIP)."""
    vs = valid_privs(kind)
    if need == "own":
        return ["OWNERSHIP"]
    if need == "change":
        return [p for p in ("INSERT", "UPDATE") if p in vs] or [p for p in vs if obj_level(p, kind) == "change"][:2] \
            or ["OWNERSHIP"]
    return [basic_priv(kind)]


OWNER_TAGS = os.environ.get("OWNER_TAGS", "OWNER,DATA_OWNER").upper().split(",")


def approver(obj):
    """The approver of an access request: the value of an owner tag on obj (inherited ones included), else None."""
    return next((v for c, t, v, _ in tags_of(obj) if not c and t.split(".")[-1].upper() in OWNER_TAGS), None)


def suggest(privs, obj, user=None, limit=5):
    """Request access: existing functional roles that reach every one of privs on obj (no build role, nothing reaching
    an admin role), smallest first (fewest other privileges), the ones the user already reaches left out. Entry: role,
    path (role->...->holder->obj), holders (users holding it), extra, also, unmasked (sensitive columns of obj the role
    sees in clear)."""
    have = set(best_paths(user, True)) if user else set()
    revs = [reverse(obj, pv) for pv in privs]
    rs = [r for r in revs[0] if all(r in x for x in revs) and r not in have and role_kind(r) == "functional"
          and suggestable(r)]
    out = []
    for r in rs:
        b = brings(r, obj)
        v = data_view(r, obj, False) if is_data(kinds.get(obj, "")) else None
        out.append(dict(role=r, path=revs[0][r] + [obj], holders=len(ups(r)[1]), extra=b["extra"], also=b["also"],
                        unmasked=[c["column"] for c in (v["columns"] if v else []) if c["sensitive"] and c["state"] == "clear"]))
    return sorted(out, key=lambda e: (e["extra"], len(e["path"]), e["role"]))[:limit]


# ---------- screen 4: access graph ----------

LV_CLS = {"names": "use", "use": "use", "read": "read", "change": "write", "own": "own", "admin": "admin"}
EVERY = "Every object (admin)"  # an admin role reaches every object without a grant: one box


def top(levels):
    """Highest step of OBJ_LEVELS among levels (None when there is none)."""
    return max((x for x in levels if x), key=OBJ_LEVELS.index, default=None)


def step_of(pv, kind):
    """obj_level, and "admin" for an account privilege (Snowflake's defaults on PUBLIC excepted: "use")."""
    return ("use" if pv in DEFAULT_PUBLIC else "admin") if kind == "ACCOUNT" else obj_level(pv, kind)


def flow(own, links):
    """Highest step each node leads to over links [(a, b)]: its own (own) or that of any node below it. A step only
    rises, so a loop ends."""
    lv, par = dict(own), {}
    for x, y in links:
        par.setdefault(y, []).append(x)
    todo = list(lv)
    while todo:
        n = todo.pop()
        for p in par.get(n, []):
            if lv.get(p) is None or OBJ_LEVELS.index(lv[n]) > OBJ_LEVELS.index(lv[p]):
                lv[p] = lv[n]
                todo.append(p)
    return lv


def steps(srcs, links, first=1):
    """Shortest step of every node from srcs (at first) over links [(a, b)]: {node: step}."""
    kids = {}
    for x, y in links:
        kids.setdefault(x, []).append(y)
    lane, todo = {s: first for s in srcs}, list(srcs)
    while todo:
        nxt = []
        for n in todo:
            for c in kids.get(n, []):
                if c not in lane:
                    lane[c] = lane[n] + 1
                    nxt.append(c)
        todo = nxt
    return lane


def grants_out(rs):
    """Object lines of the roles rs: [(role, object, privilege, kind)]; names (USAGE on a database or schema) and
    roles held left out."""
    return [(r, o, pv, k) for r in rs for pv, k, o in granted.get(r, []) if category(pv, k) not in ("names", "hold")]


def access_graph(start, name, same=True, admin=True):
    """Screen 4, the access graph from an object (start "object"), a role or a user. Columns by shortest step; every
    line carries the step it ends up granting (cls read / write / own / use; admin = an admin role's bypass, no grant
    needed); people with the same lines stacked in one box (same); people holding an admin role and those roles
    (admin, from an object or a role); PUBLIC's hidden built-ins as one fold box. Returns dict(start (node id), lanes
    [(label, [ids])], edges [(a, b, cls, privilege, people)], kinds {id: stack | every | fold}, stacks {id: [users]},
    levels {id: step}, people {id: [users through it]}, leads {id: [objects it leads to]}, risky {(a, b): why},
    risky_nodes {id: why}; why: admin | public | writes). ValueError for an unknown name."""
    adm = admin_users() if admin and start != "user" else {}
    if start == "object":
        if name not in kinds:
            raise ValueError(f"{name} is not in this snapshot")
        hold = [(r, pv) for r, pv, k in on.get(name, [])]
        rs = set().union(*(ups(h)[0] for h, _ in hold)) if hold else set()
        links = [(p, r) for r in sorted(rs) for p in held_by.get(r, []) if p in rs]
        ues = [(u, r) for r in sorted(rs) for u in (users if r == "PUBLIC" else users_of.get(r, []))]
        oes = [(r, name, pv, kinds[name]) for r, pv in hold]
        lane = steps([r for r in rs if r == "PUBLIC" or users_of.get(r) or not any(p in rs for p in held_by.get(r, []))],
                     links)
        sid, at = name, name
    elif start == "role":
        if name not in roles:
            raise ValueError(f"{name} is not in this snapshot")
        up_, dn = ups(name)[0], bfs([name])
        rs = set(up_) | set(dn)
        above = [(p, r) for r in sorted(up_) for p in held_by.get(r, []) if p in up_]
        links = above + [(r, c) for r in sorted(dn) for c in holds.get(r, [])]
        ues = [(u, r) for r in sorted(up_) for u in (users if r == "PUBLIC" else users_of.get(r, []))]
        oes = grants_out(sorted(dn))
        far = steps([name], [(y, x) for x, y in above], 0)
        u0 = max(list(far.values()) + [1 if adm else 0])
        lane = {r: u0 + 1 - d for r, d in far.items()} | {r: u0 + len(p) for r, p in dn.items()}
        sid, at = name, name
    else:
        if name not in users:
            raise ValueError(f"{name} is not in this snapshot")
        best = best_paths(name, True)
        rs = set(best)
        links = [(r, c) for r in sorted(rs) for c in holds.get(r, [])]
        ues = [(name, p[1]) for p in starts(name, True)]
        oes = grants_out(sorted(rs))
        lane = {r: len(p) - 1 for r, p in best.items()}
        sid, at = uid(name, True), None
    objs = [name] if start == "object" else list(dict.fromkeys(o for _, o, _, _ in oes))
    own = {}
    for r, o, pv, k in oes:
        if k != "ACCOUNT":  # an account privilege is its own red line, not a step on the objects
            own[r] = top([own.get(r), step_of(pv, k)])
    for r in rs & ADMIN:
        own[r] = "admin"
    lv = flow(own, links)
    kinds_, adm_roles = {}, {}
    for u, ars in adm.items():
        for ar in ars:
            if ar != at:
                adm_roles.setdefault(ar, []).append(u)
    for ar in adm_roles:
        lane.setdefault(ar, lane[at] - 1 if start == "role" else 1)
    every = sorted(rs & ADMIN) if start != "object" else []
    if every:
        objs.append(EVERY)
        kinds_[EVERY] = "every"
    fold = "PUBLIC" in rs and bool(hidden) and start != "object"
    if fold:
        objs.append(BUILTIN_NODE)
        kinds_[BUILTIN_NODE] = "fold"
    # who comes through each node: users drawn that reach it
    drawn = {u for u, _ in ues} | set(adm)
    people = {uid(u, True): [u] for u in drawn}
    for r in rs | set(adm_roles):
        people[r] = sorted((set(ups(r)[1]) & drawn) | set(adm_roles.get(r, []))) if start != "user" else [name]
    for o in objs:
        src = {r for r, x, _, _ in oes if x == o} | set(every if o == EVERY else ["PUBLIC"] if o == BUILTIN_NODE else [])
        src |= set(adm_roles) if o == at else set()
        people[o] = sorted(set().union(*(people.get(r, []) for r in src)))
    cls = lambda n: LV_CLS[lv[n]] if lv.get(n) else "inherit"
    # user lines, people with the same lines stacked into one box
    outs = {}
    for u, r in ues:
        outs.setdefault(u, set()).add((r, cls(r)))
    for u, ars in adm.items():
        outs.setdefault(u, set()).update((ar, "admin") for ar in ars)
    by, stacks, edges, ucol = {}, {}, [], []
    for u, xs in sorted(outs.items()):
        by.setdefault(tuple(sorted(xs)), []).append(u)
    for key, us in by.items():
        if same and len(us) > 1:
            s = "people:" + "|".join(f"{r}/{c}" for r, c in key)
            stacks[s], kinds_[s], people[s] = us, "stack", us
            edges += [(s, r, c, None, len(us)) for r, c in key]
            ucol.append(s)
        else:
            edges += [(uid(u, True), r, c, None, 1) for u in us for r, c in key]
            ucol += [uid(u, True) for u in us]
    edges += [(p, c, cls(c), None, len(people.get(p, []))) for p, c in links]
    best_on = {}
    for r, o, pv, k in oes:
        best_on[(r, o)] = top([best_on.get((r, o)), step_of(pv, k)])
    edges += [(r, o, LV_CLS[best_on[(r, o)]], pv, len(people.get(r, []))) for r, o, pv, k in oes]
    edges += [(ar, at, "admin", None, len(us)) for ar, us in adm_roles.items()]
    edges += [(ar, EVERY, "admin", None, len(people.get(ar, []))) for ar in every]
    if fold:
        edges.append(("PUBLIC", BUILTIN_NODE, "use", "USAGE", len(people.get("PUBLIC", []))))
    # columns: people, roles by step, then the objects
    last = max(list(lane.values()) + [0]) + 1
    col = {n: lane[n] for n in rs | set(adm_roles)} | {n: 0 for n in ucol} | {o: last for o in objs}
    if start == "role":
        word = lambda i: ("Held by" if i == 0 else "Role" if i == lane[name] else "Reaches" if i == last
                          else f"{lane[name] - i} up" if i < lane[name] else f"Step {i - lane[name]}")
    elif start == "user":
        word = lambda i: "Person" if i == 0 else "Roles held" if i == 1 else "Reaches" if i == last else f"Step {i}"
    else:
        word = lambda i: "People" if i == 0 else kinds[name].title() if i == last else f"Step {i}"
    lanes = [(word(i), sorted(n for n, c in col.items() if c == i)) for i in range(last + 1)]
    # what each node leads to, and the risky lines
    kids = {}
    for e in edges:
        kids.setdefault(e[0], set()).add(e[1])
    oset, leads = set(objs), {}
    for n in col:
        seen_, todo = set(), [n]
        while todo:
            for c in kids.get(todo.pop(), ()):
                if c not in seen_:
                    seen_.add(c)
                    todo.append(c)
        leads[n] = sorted(seen_ & oset)
    radm = lambda r: r in ADMIN or (r in roles and cached(("radm", r), lambda: reaches_admin(r)))
    pub = set(bfs(["PUBLIC"])) if "PUBLIC" in rs else set()
    risky, rnodes = {}, {}
    for x, y, c, *_ in edges:
        if c == "admin" or (y in rs and radm(y)):
            risky[(x, y)] = "admin"
        elif x in pub or y == "PUBLIC":
            risky[(x, y)] = "public"
    for r in rs | set(adm_roles):
        if radm(r):
            rnodes[r] = "admin"
        elif r in pub:
            rnodes[r] = "public"
    pairs = {(e[0], e[1]) for e in edges}
    for x in cached("rw", readonly_writes):
        if x["role"] in rs and x["object"] in oset:
            rnodes[x["role"]] = "writes"
            for ab in zip(x["path"], x["path"][1:]):
                if ab in pairs:
                    risky[ab] = "writes"
    return dict(start=sid, lanes=[x for x in lanes if x[1]], edges=edges, kinds=kinds_, stacks=stacks,
                levels={n: v for n, v in lv.items() if v}, people=people, leads=leads, risky=risky, risky_nodes=rnodes)


# ---------- screen 7: what they see ----------

def seen(name, user=None):
    """Screen 7, what name sees when it queries: one card per table / view it can read with a tag or a policy
    (data_views), sensitive ones first. Card: object, type, sensitive, rows dict(state, reason, policy), columns
    [dict(column, sensitive, state, reason, policy, fix)] (fix: sensitive, in clear and no masking policy at all).
    counts: objects, sensitive (objects), columns (sensitive ones), clear, masked, unknown, unprotected (fix), rows
    (objects whose row policy does not show every row)."""
    cards = []
    for v in data_views(name, user):
        cols = [dict(column=c["column"], sensitive=c["sensitive"], state=c["state"], reason=c["reason"], policy=c["policy"],
                     fix=c["sensitive"] and c["state"] == "clear" and not c["policy"]) for c in v["columns"]]
        cards.append(dict(object=v["object"], type=kinds.get(v["object"], ""),
                          sensitive=v["object"] in sens or any(c["sensitive"] for c in cols),
                          rows=dict(state=v["rows"]["state"], reason=v["rows"]["reason"], policy=v["rows"]["policy"]),
                          columns=sorted(cols, key=lambda c: (not c["sensitive"], c["column"]))))
    cards.sort(key=lambda x: (not x["sensitive"], -sum(c["fix"] for c in x["columns"]), x["object"]))
    sc = [c for x in cards if x["sensitive"] for c in x["columns"] if c["sensitive"]]
    n = lambda s: sum(c["state"] == s for c in sc)
    return dict(cards=cards, counts=dict(objects=len(cards), sensitive=sum(x["sensitive"] for x in cards), columns=len(sc),
                                         clear=n("clear"), masked=n("masked"), unknown=n("unknown"),
                                         unprotected=sum(c["fix"] for c in sc),
                                         rows=sum(x["rows"]["state"] != "all" for x in cards)))


# ---------- screen 9: compare two people or roles ----------

DIFF = ("only_a", "only_b", "different", "same")
ROWS_TEXT = {"all": "all rows", "filtered": "filtered rows", "none": "no rows", "unknown": "rows unknown"}


def sees_text(name, obj, user=False):
    """What name sees of a table or view in one line: "EMAIL masked · PHONE clear · no rows (RAP_REGION)"; "whole
    object, clear" for a sensitive object without policies, else ""."""
    v = data_view(name, obj, user)
    m = [f'{c["column"]} {c["state"]}' for c in v["columns"] if c["sensitive"] or c["policy"]]
    p = v["rows"]["policy"]
    m += [f'{ROWS_TEXT[v["rows"]["state"]]} ({p.split(".")[-1]})'] if p else []
    return " · ".join(m) or ("whole object, clear" if obj in sens else "")


def compare(x, xu, y, yu, scope="sensitive", db=None):
    """Screen 9, A (x, a user when xu) against B (y, yu): one row per object either reaches in scope (sensitive
    objects; "all" data and runnable objects; "db" those in database db), differences first. Row: object, type,
    database, schema, name, diff (only_a | only_b | different | same), a / b dict(level, privileges, sees) or None,
    extra_a / extra_b (privileges only that side has). counts per diff. match: the changes that give B what only A
    has (B a user: the role A starts the path with, or A itself; B a role: the grant holder role, or the privilege
    when A holds it itself); extras: the changes that take A's extras away (the first link of A's path, or A's own
    grant). A side holding an admin role reaches every object without a grant (level admin, no extras against it).
    A change: op, role | privilege + objectType + object, to, toUser. Text only: nothing runs."""
    def side(n, u):
        rows = grants(n, u)
        objs = {o["object"]: o for o in access_objects(rows, u) if o["category"] in ("data", "runnable")}
        best = {}
        for r in rows:
            k = (r["privilege"], r["object"])
            if k not in best or len(r["path"]) < len(best[k]):
                best[k] = r["path"]
        return objs, best
    (ax, ap), (bx, _) = side(x, xu), side(y, yu)
    boss = {n: (n in admin_users()) if u else (n in ADMIN or reaches_admin(n)) for n, u in ((x, xu), (y, yu))}
    god = dict(level="admin", privileges=[], sees="every object, through an admin role")
    keep = {"sensitive": lambda o: o in sens, "db": lambda o: split_name(o, kinds.get(o))[0] == db}.get(scope, lambda o: True)
    out = []
    for o in sorted(set(ax) | set(bx)):
        if not keep(o):
            continue
        ea, eb = ax.get(o), bx.get(o)
        data = is_data(kinds.get(o, ""))
        va = dict(level=ea["level"], privileges=ea["privileges"], sees=sees_text(x, o, xu) if data else "") if ea             else god if boss[x] else None
        vb = dict(level=eb["level"], privileges=eb["privileges"], sees=sees_text(y, o, yu) if data else "") if eb             else god if boss[y] else None
        pa, pb = set(ea["privileges"]) if ea else set(), set(eb["privileges"]) if eb else set()
        ea, eb = va, vb
        d = "only_a" if not eb else "only_b" if not ea else "same" if va == vb else "different"
        db_, sc, nm = split_name(o, kinds.get(o))
        out.append(dict(object=o, type=kinds.get(o, ""), database=db_, schema=sc, name=nm, diff=d, a=va, b=vb,
                        extra_a=[] if boss[y] else sorted(pa - pb), extra_b=[] if boss[x] else sorted(pb - pa)))
    out.sort(key=lambda r: (DIFF.index(r["diff"]), r["object"]))
    match, extras = [], []
    for r in out:
        for pv in r["extra_a"]:
            p = ap[(pv, r["object"])]
            if yu:
                c = dict(op="grant", role=p[1] if xu else x, to=y, toUser=True)
            elif p[-2] == x:
                c = dict(op="grant", privilege=pv, objectType=r["type"], object=r["object"], to=y, toUser=False)
            else:
                c = dict(op="grant", role=p[-2], to=y, toUser=False)
            if c not in match and c.get("role") != "PUBLIC":  # every user holds PUBLIC
                match.append(c)
            c = dict(op="revoke", privilege=pv, objectType=r["type"], object=r["object"], to=x, toUser=False) \
                if len(p) == 2 and not xu else dict(op="revoke", role=p[1], to=x, toUser=xu)
            if c not in extras and c.get("role") != "PUBLIC":
                extras.append(c)
    return dict(rows=out, counts={d: sum(r["diff"] == d for r in out) for d in DIFF}, match=match, extras=extras)


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
                            granted=", ".join(sorted({p[1] for p in ps})), path=" > ".join([x] + ps[0][1:] + [o]),
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


# ---------- what if: grants removed in memory, before / after diff (read-only: prints the IaC / REVOKE text) ----------

WHAT_IF_OPS = ("revoke_role_from_user", "revoke_role_from_role", "revoke_priv", "drop_role", "empty_public")
REBOUND = ("roles", "users", "objects", "run")  # build() binds these anew; it refills the other lookups in place
STATE = REBOUND + ("role_grants", "user_grants", "privs", "holds", "held_by", "users_of", "roles_of", "profile", "used",
                   "granted", "on", "kinds", "tags", "policies", "sens", "streams", "capped", "db_roles", "memo",
                   "hidden", "source", "obj_use")


def changes_of(changes):
    """what_if() changes checked against the loaded grants: (cut, [dict(change, label, iac, sql)]). cut: dict(user
    {(user, role)}, link {(role, grantee role)}, priv {(role, privilege, object)}, drop {role}, public). ValueError
    for an unknown op or a grant that is not there."""
    cut, out = dict(user=set(), link=set(), priv=set(), drop=set(), public=False), []
    for c in changes:
        op, r = c.get("op"), c.get("role")
        if op in ("revoke_role_from_user", "revoke_role_from_role"):
            user = op == "revoke_role_from_user"
            g = c.get("user" if user else "grantee")
            direct = r in (roles_of if user else holds).get(g, [])
            # held further down: cut r where it is granted, at every role on g's paths that holds it directly
            via = sorted(h for h in dict.fromkeys(held_by.get(r, [])) if h != g and (g in ups(h)[1] if user else g in ups(h)[0]))
            if not direct and not via:
                raise ValueError(f"{'User' if user else 'Role'} {g} does not reach role {r}")
            if direct:
                cut["user" if user else "link"].add((g, r) if user else (r, g))
            cut["link"].update((r, h) for h in via)
            edges = ([role_edge(g, r, user)] if direct else []) + [role_edge(h, r) for h in via]
            label = f"Revoke role {r} from {'user' if user else 'role'} {g}" + (
                f" (held through {', '.join(via)}: revoked there too, so their other holders lose it as well)" if via and direct else
                f" (held through {', '.join(via)}: revoked there, so their other holders lose it as well)" if via else "")
            iac, sql = fix_text(edges)
        elif op == "revoke_priv":
            pv, o = c.get("privilege"), c.get("object")
            ks = sorted({k for p, k, x in granted.get(r, []) if p == pv and x == o})
            if not ks:
                raise ValueError(f"Role {r} holds no {pv} on {o}")
            cut["priv"].add((r, pv, o))
            label, (iac, sql) = f"Revoke {pv} on {o} from role {r}", fix_text([priv_edge(r, pv, k, o) for k in ks])
        elif op == "drop_role":
            if r not in roles or r == "PUBLIC" or r in ADMIN:  # PUBLIC and the system roles can't be dropped
                raise ValueError(f"Role {r} can't be dropped" if r in roles else f"No role {r}")
            cut["drop"].add(r)
            label, iac, sql = (f"Drop role {r}", f"Remove in the infrastructure-as-code repo: role {r}, with every "
                                                 "grant to and from it", f"DROP {role_sql(r)};")
        elif op == "empty_public":  # PUBLIC itself can't be revoked: every user holds it
            cut["public"] = True
            edges = [priv_edge("PUBLIC", pv, k, o) for pv, k, o in granted.get("PUBLIC", [])]
            edges += [role_edge("PUBLIC", x) for x in dict.fromkeys(holds.get("PUBLIC", []))]
            label, (iac, sql) = "Remove every grant to PUBLIC", fix_text(edges) if edges else ("PUBLIC holds nothing", "")
        else:
            raise ValueError(f"Unknown op {op!r}; ops: {', '.join(WHAT_IF_OPS)}")
        out.append(dict(change=c, label=label, iac=iac, sql=sql))
    return cut, out


def without_cuts(d, cut):
    """d without the GRANT / USER_ROLE rows the cut removes."""
    def gone(g):
        r, o, link = g["GRANTEE_ROLE"], g["OBJECT_NAME"], g["GRANTED_ON"] in ROLE_ON
        return (r in cut["drop"] or (link and o in cut["drop"]) or (cut["public"] and r == "PUBLIC")
                or ((o, r) in cut["link"] if link and g["PRIVILEGE"] == "USAGE" else (r, g["PRIVILEGE"], o) in cut["priv"]))
    return d | dict(GRANT=[g for g in d["GRANT"] if not gone(g)],
                    USER_ROLE=[x for x in d["USER_ROLE"] if (x["USER_NAME"], x["ROLE_NAME"]) not in cut["user"]
                               and x["ROLE_NAME"] not in cut["drop"]])


def paths_from(sts):
    """Shortest path from the start paths to every role they reach (BFS, no hop cap): {role: path}."""
    best, todo = {}, sorted(sts, key=len)
    while todo:
        nxt = []
        for p in todo:
            if p[-1] not in best:
                best[p[-1]] = p
                nxt += [p + [r] for r in holds.get(p[-1], []) if r not in best]
        todo = nxt
    return best


def reached_roles():
    """Roles some user reaches (PUBLIC too when there are users), once per data set."""
    def make():
        todo = list({r for rs in roles_of.values() for r in rs} | ({"PUBLIC"} if users else set()))
        seen = set(todo)
        while todo:
            for r in holds.get(todo.pop(), []):
                if r not in seen:
                    seen.add(r)
                    todo.append(r)
        return seen
    return cached("reached", make)


def what_if(changes, cap=MAX_PATHS):
    """The access lost when grants go, simulated on a copy: the loaded lookups are rebuilt without the changes and put
    back after; the rules recheck only the users and roles a change can touch. changes: [dict(op, ...)]:
    revoke_role_from_user (role, user), revoke_role_from_role (role, grantee), revoke_priv (role, privilege, object),
    drop_role (role), empty_public (every grant to PUBLIC). cap: objects / roles listed per user (None: all; counts
    are always exact). Returns dict(changes [dict(change, label, iac, sql)], summary, counts, users [dict(user, status,
    lost (privileges), objects (lost), lost_rows [dict(object, type, privileges, classes, path)], kept (privileges
    still reached through another path), kept_rows [... + via (the path left), through (its first role the old path
    did not use)], kept_roles [dict(role, path, via, through)]: roles right under a cut still reached)],
    objects [dict(object, type, sensitive, unreached, ownerless)], roles [dict(role, kind, orphan, unreached)],
    findings [dict(num, title, severity, grantee, kind, detail, path, status fixed | new, changed: the rule still
    fires on that grantee)], iac, sql, csv [rows: section, name, privilege, type, object, cls, status, path, detail])."""
    cut, steps = changes_of(changes)
    pub = list(dict.fromkeys(holds.get("PUBLIC", []))) if cut["public"] else []
    # cut points: (users who reach it, role, the roles right under the cut)
    pts = [({u}, r, {r}) for u, r in cut["user"]] + [(ups(g)[1], r, {r}) for r, g in cut["link"]]
    pts += [(ups(r)[1], r, set(holds.get(r, []))) for r in cut["drop"]]
    below, touched, heads, pcut = {}, {}, {}, {}  # roles under each cut point; per user: what it may lose
    for us, r, hs in pts:
        below.setdefault(r, set(bfs([r])))
        for u in us:
            touched.setdefault(u, set()).update(below[r])
            heads.setdefault(u, set()).update(hs)
    for r, pv, o in cut["priv"]:
        for u in ups(r)[1]:
            pcut.setdefault(u, set()).add((r, pv, o))
    every_t = set()  # empty PUBLIC: every user may lose the roles under PUBLIC and its grants
    for r in pub:
        every_t |= below.setdefault(r, set(bfs([r])))
    every_p = {("PUBLIC", pv, o) for pv, _, o in granted.get("PUBLIC", [])} if cut["public"] else set()
    before = {}  # user -> (shortest paths, roles under a cut it reaches, grants cut that it reaches)
    for u in set(users) if every_t or every_p else set(touched) | set(pcut):
        reach = paths_from(starts(u, True))
        t = (touched.get(u, set()) | every_t) & reach.keys()
        p = [x for x in pcut.get(u, set()) | every_p if x[0] in reach]
        if t or p:
            before[u] = (reach, t, p, (heads.get(u, set()) | set(pub)) & t)
    under = set().union(*below.values())
    tops = {x for r, g in cut["link"] for x in ups(g)[0]} | {x for r in cut["drop"] for x in ups(r)[0]}
    tops |= {x for r, _, _ in cut["priv"] for x in ups(r)[0]} | {"PUBLIC"}
    # what the per-grantee rules recheck: who had a finding below or above a cut, and every role above one for the
    # rules a removed grant can start (GROW)
    fb = cached("findings", findings)
    only = {n: set(tops) if n in GROW else set() for n in SCOPED}
    for f in fb:
        if f["num"] in SCOPED and (f["grantee"] in before or f["grantee"] in tops):
            only[f["num"]].add(f["grantee"])
    fb = [f for f in fb if f["num"] not in SCOPED or f["grantee"] in only[f["num"]]]
    objs = {o for r in under for _, _, o in granted.get(r, [])} | {o for _, _, o in cut["priv"] | every_p}
    b_live = reached_roles()
    b_obj = {o: (any(r in b_live for r, _, _ in on.get(o, [])), any(pv == "OWNERSHIP" for _, pv, _ in on.get(o, [])))
             for o in objs}
    cands = {r for _, r in cut["user"]} | {r for r, _ in cut["link"]} | set(pub)  # may lose their last holder
    cands |= {x for r in cut["drop"] for x in holds.get(r, [])}
    b_role = {r: bool(users_of.get(r) or held_by.get(r)) for r in cands}
    saved = state()
    old = saved["granted"]
    try:
        build(without_cuts(source["data"], cut), builtin=source["builtin"])
        groups, after = {}, {}

        def split(r):  # r's grants (before), grouped by the roles holding the same privilege on the object after
            if r not in groups:
                by = {}
                for pv, k, o in old.get(r, []):
                    by.setdefault(frozenset(h for h, p2, _ in on.get(o, []) if p2 == pv), []).append((pv, k, o))
                groups[r] = list(by.items())
            return groups[r]

        def best(hs, reach):
            return reach[min(hs, key=lambda x: (len(reach[x]), x))]

        for u, (b_reach, t, p, hs) in before.items():
            reach = paths_from(starts(u, True))
            lost, kept = {}, {}  # (privilege, object) -> (type, holder before[, path to a holder after])
            for r in t - reach.keys():
                for hs, items in split(r):
                    left = hs & reach.keys()
                    via = best(left, reach) if left else None
                    for pv, k, o in items:
                        if via:
                            kept.setdefault((pv, o), (k, r, via))
                        else:
                            lost.setdefault((pv, o), (k, r))
            for r, pv, o in p:
                k = next(k for p2, k, x in old[r] if p2 == pv and x == o)
                left = {h for h, p2, _ in on.get(o, []) if p2 == pv} & reach.keys()
                if left:
                    kept.setdefault((pv, o), (k, r, best(left, reach)))
                else:
                    lost.setdefault((pv, o), (k, r))
            after[u] = (lost, kept, {r: reach[r] for r in hs & reach.keys()})
        a_live = reached_roles()
        a_obj = {o: (any(r in a_live for r, _, _ in on.get(o, [])), any(pv == "OWNERSHIP" for _, pv, _ in on.get(o, [])))
                 for o in objs}
        orphan = {r for r, had in b_role.items() if had and r not in cut["drop"] and r != "PUBLIC"
                  and not (users_of.get(r) or held_by.get(r))}
        gone = (b_live & under) - a_live - cut["drop"]
        fa = [f for f in findings(only) if f["num"] not in SCOPED or f["grantee"] in only[f["num"]]]
    finally:
        restore(saved)

    def rows(got, b_reach):  # one row per object, at most cap
        keep = set(sorted({o for _, o in got})[:cap])
        per = {}
        for (pv, o), x in got.items():
            if o in keep:
                per.setdefault(o, []).append((pv,) + x)
        out = []
        for o in sorted(per):
            xs = sorted(per[o], key=lambda x: x[0])
            row = dict(object=o, type=xs[0][1], privileges=[x[0] for x in xs], path=b_reach[xs[0][2]] + [o],
                       classes=sorted({priv_class(x[0], x[1]) for x in xs}, key=CLS_ORDER.index))
            out.append(row | dict(via=xs[0][3] + [o], through=through(row["path"], xs[0][3])) if len(xs[0]) > 3 else row)
        return out

    def through(old, new):  # the first role of the path left that the old path did not use
        return next((r for r in new[1:] if r not in old), new[1] if len(new) > 1 else new[0])

    us = []
    for u, (lost, kept, moved) in after.items():  # moved: roles under a cut still reached, another way
        b_reach = before[u][0]
        if lost or kept or moved:
            us.append(dict(user=u, status=status(u), lost=len(lost), objects=len({o for _, o in lost}),
                           lost_rows=rows(lost, b_reach), kept=len(kept), kept_rows=rows(kept, b_reach),
                           kept_roles=[dict(role=r, path=b_reach[r], via=p, through=through(b_reach[r], p))
                                       for r, p in sorted(moved.items())][:cap]))
    us.sort(key=lambda x: (-x["objects"], -x["lost"], x["user"]))
    key, k3 = (lambda f: (f["num"], f["grantee"], f["user"], f["detail"])), (lambda f: (f["num"], f["grantee"], f["user"]))
    bk, ak = {key(f): f for f in fb}, {key(f): f for f in fa}
    b3, a3 = {k3(f) for f in fb}, {k3(f) for f in fa}
    fnd = [dict(num=f["num"], title=RULES[f["num"]][0], severity=SEVERITY.get(f["num"], "Low"), grantee=f["grantee"],
                kind="user" if f["user"] else role_kind(f["grantee"]), detail=f["detail"], path=f["path"], status=st,
                changed=k3(f) in other)
           for st, mine_, theirs, other in (("fixed", bk, ak, a3), ("new", ak, bk, b3))
           for k, f in sorted(mine_.items(), key=lambda x: (int(x[0][0]), x[0][1])) if k not in theirs]
    ob = [dict(object=o, type=kinds.get(o, ""), sensitive=o in sens, unreached=b[0] and not a_obj[o][0],
               ownerless=b[1] and not a_obj[o][1]) for o, b in sorted(b_obj.items())]
    ob = [x for x in ob if x["unreached"] or x["ownerless"]]
    rs = [dict(role=r, kind=role_kind(r), orphan=r in orphan, unreached=r in gone) for r in sorted(orphan | gone)]
    n = dict(users=sum(bool(x["lost"]) for x in us), objects=len({o for lost, _, _ in after.values() for _, o in lost}),
             kept=sum(bool(x["kept"] or x["kept_roles"]) for x in us), unreached=sum(x["unreached"] for x in ob),
             ownerless=sum(x["ownerless"] for x in ob), orphans=len(orphan), unreached_roles=len(gone),
             fixed=sum(f["status"] == "fixed" and not f["changed"] for f in fnd),
             new=sum(f["status"] == "new" and not f["changed"] for f in fnd),
             changed=len({(f["num"], f["grantee"]) for f in fnd if f["changed"]}))
    via = {}
    for x in us:
        for r in {y["through"] for y in x["kept_rows"] + x["kept_roles"]}:
            via[r] = via.get(r, 0) + 1
    top = max(via, key=lambda r: (via[r], r)) if via else ""
    parts = [f"{plural(n['users'], 'user')} lose{'s' * (n['users'] == 1)} access to {plural(n['objects'], 'object')}"
             if n["users"] else "Nobody loses access"]
    parts += [f"{n['kept']} keep{'s' * (n['kept'] == 1)} access through another path (most via {top})"] * bool(top)
    parts += [f"{plural(n['unreached'], 'object')} nobody reaches any more"] * bool(n["unreached"])
    parts += [f"{plural(n['ownerless'], 'object')} without an owner"] * bool(n["ownerless"])
    parts += [f"{plural(n['orphans'], 'role')} left without users or parent roles"] * bool(n["orphans"])
    parts += [f"{plural(n['fixed'], 'finding')} fixed, {n['new']} new"
              + (f", {n['changed']} changed" if n["changed"] else "")]
    csv = [dict(section="change", name=s["label"], privilege="", type="", object="", cls="", status="", path="",
                detail=s["sql"] or s["iac"]) for s in steps]
    for x in us:
        for st, ys in (("lost", x["lost_rows"]), ("kept", x["kept_rows"])):
            csv += [dict(section="user", name=x["user"], privilege=", ".join(y["privileges"]), type=y["type"],
                         object=y["object"], cls=", ".join(y["classes"]), status=st,
                         path=" > ".join(y.get("via") or y["path"]), detail="") for y in ys]
        csv += [dict(section="user", name=x["user"], privilege="", type="ROLE", object=y["role"], cls="",
                     status="kept role", path=" > ".join(y["via"]), detail="") for y in x["kept_roles"]]
    csv += [dict(section="object", name=x["object"], privilege="", type=x["type"], object=x["object"], cls="",
                 status=", ".join(k for k in ("unreached", "ownerless") if x[k]), path="",
                 detail="sensitive" if x["sensitive"] else "") for x in ob]
    csv += [dict(section="role", name=x["role"], privilege="", type="", object="", cls="",
                 status=", ".join(k for k in ("orphan", "unreached") if x[k]), path="", detail=x["kind"]) for x in rs]
    csv += [dict(section="finding", name=f["grantee"], privilege="", type="", object="", cls="", status=f["status"],
                 path=" > ".join(f["path"]), detail=f"Rule {f['num']} {f['title']}: {f['detail']}") for f in fnd]
    return dict(changes=steps, summary="; ".join(parts), counts=n, users=us, objects=ob, roles=rs, findings=fnd,
                iac="\n".join(s["iac"] for s in steps), sql="\n".join(s["sql"] for s in steps if s["sql"]), csv=csv)


# ---------- granted vs used (ACCESS_HISTORY) ----------

WRITE_PRIVS = {"INSERT", "UPDATE", "DELETE", "TRUNCATE"}
PERIODS = (30, 90, 180)  # Granted vs used: days to look back


def use_state():
    """(ok, reason): whether the loaded data has object usage (ACCESS_HISTORY) to set grants against."""
    if obj_use or (run.get("SOURCES") or {}).get("object_use") == "ACCOUNT_USAGE":
        return True, None
    if (source.get("data") or {}).get("OBJECT_USE") is None:
        return False, ("This data has no object usage: it was read before the app read ACCESS_HISTORY, or the snapshot "
                       "tables predate TBL_ACCESS_OBJECT_USE (run sql/1_setup.sql again, then rebuild the snapshot).")
    return False, (run.get("NOTES") or {}).get("object_use") or "ACCESS_HISTORY has no queries on these objects."


def weeks_of(days):
    return -(-days // 7)


def used_on(names, days):
    """Object usage of these users in the last days: {object: dict(read, write (queries), weeks (queries per week,
    oldest first), last, users)}. Whole ISO weeks, counted back from the snapshot's week."""
    n, w0, out = weeks_of(days), monday(ref_time()), {}
    for u in names:
        for x in obj_use.get(u, []):
            i = (w0 - monday(x["WEEK"])).days // 7
            if not 0 <= i < n:
                continue
            o = out.setdefault(x["OBJECT_NAME"], dict(read=0, write=0, weeks=[0] * n, last=None, users=set()))
            q = int(x["QUERIES"] or 0)
            o["write" if x["ACTION"] == "WRITE" else "read"] += q
            o["weeks"][n - 1 - i] += q
            o["last"] = max(filter(None, (o["last"], when(x["LAST_USED"]))), default=None)
            o["users"].add(u)
    return out


def granted_used(name, user=True, days=90):
    """Screen 13: every table and view name reaches, at its granted step next to the step used in the last days (by
    name; for a role, by anyone who reaches it), weekly queries, last use and a suggestion: keep, trim (write or
    ownership never used) or drop (not used at all). changes: what_if() revokes of the unused privileges where they are
    granted (OWNERSHIP is transferred, not revoked: left out), so the change plan shows who else loses them."""
    rows, hold = grants(name, user), {}
    for r in rows:
        hold.setdefault((r["object"], r["privilege"]), set()).update(r["holders"])
    who = {name} if user else ups(name)[1]
    use, n, out = used_on(who, days), weeks_of(days), []
    for x in access_objects(rows, user):
        if x["category"] != "data" or not x["level"] or not is_data(x["type"]):
            continue
        u = use.get(x["object"])
        # a role's people may write through another role: used "change" only where this grant lets them
        used = ("change" if u["write"] and LEVELS.index(x["level"]) >= LEVELS.index("change") else "read") if u else None
        unused = [p for p in x["privileges"] if level_of(p, x["type"]) and (
            used is None or p == "OWNERSHIP" or (p in WRITE_PRIVS and used == "read"))]
        cut = [p for p in unused if p != "OWNERSHIP"]
        if used is None:
            kind, text = "drop", f"Remove all · not used in {days} days"
        elif cut:
            kind, text = "trim", f"Remove {', '.join(cut)} · never used" + " · ownership unused" * ("OWNERSHIP" in unused)
        elif unused:
            kind, text = "trim", f"Keep {'read' if used == 'read' else 'read + change'} · ownership unused"
        else:
            kind, text = "keep", "Keep"
        out.append(dict(object=x["object"], type=x["type"], database=x["database"], schema=x["schema"],
                        sensitive=x["object"] in sens, level=x["level"], used=used, privileges=x["privileges"],
                        unused=unused, weeks=u["weeks"] if u else [0] * n, reads=u["read"] if u else 0,
                        writes=u["write"] if u else 0, last=str(u["last"])[:16] if u and u["last"] else None,
                        people=sorted(u["users"]) if u else [], holder=x["holder"], suggest=kind, text=text,
                        changes=[dict(op="revoke_priv", role=h, privilege=p, object=x["object"])
                                 for p in cut for h in sorted(hold.get((x["object"], p), ()))]))
    out.sort(key=lambda r: (("drop", "trim", "keep").index(r["suggest"]), not r["sensitive"], r["object"]))
    w0 = monday(ref_time())
    changes = [c for r in out for c in r["changes"]]
    counts = dict(objects=len(out), used=sum(bool(r["used"]) for r in out), drop=sum(r["suggest"] == "drop" for r in out),
                  trim=sum(r["suggest"] == "trim" for r in out), keep=sum(r["suggest"] == "keep" for r in out),
                  write_unused=sum(r["used"] == "read" and any(p in WRITE_PRIVS for p in r["unused"]) for r in out),
                  changes=len(changes))
    return dict(days=days, weeks=[(w0 - timedelta(weeks=n - 1 - i)).isoformat() for i in range(n)], rows=out,
                counts=counts, changes=changes, people=len(who))


# ---------- what changed (two snapshots) ----------

def state():
    """A copy of every lookup build() fills, for restore()."""
    g = globals()
    return {n: g[n] if n in REBOUND else g[n].copy() for n in STATE}


def restore(saved):
    g = globals()
    for n, v in saved.items():
        if n in REBOUND:
            g[n] = v
        else:
            g[n].clear()
            if isinstance(v, list):
                g[n].extend(v)
            else:
                g[n].update(v)


@contextmanager
def loaded(d):
    """The lookups of data set d inside the block; the loaded ones, with their cached results, are put back after."""
    saved = state()
    try:
        build(d, builtin=source.get("builtin", False))
        yield
    finally:
        restore(saved)


def facts():
    """What a diff compares, once per data set: access {(user, object): (step, privileges)} on tables and views, grants
    {(grantee, privilege, granted on, object): granted_by} (role links to admin roles left out, as build() does),
    user_roles {(role, user): granted_by}, findings {key: finding}, status {user: status}, sensitive objects, run."""
    def make():
        acc = {(u, x["object"]): (x["level"], x["privileges"]) for u in users for x in access_objects(grants(u, True), True)
               if x["category"] == "data" and x["level"] and is_data(x["type"])}
        d = source["data"]
        gs = {(g["GRANTEE_ROLE"], g["PRIVILEGE"], g["GRANTED_ON"], g["OBJECT_NAME"]): g.get("GRANTED_BY") for g in d["GRANT"]
              if (source["builtin"] or not builtin_grant(g)) and not (g["GRANTED_ON"] in ROLE_ON and g["GRANTEE_ROLE"] in ADMIN)}
        return dict(access=acc, grants=gs,
                    user_roles={(x["ROLE_NAME"], x["USER_NAME"]): x.get("GRANTED_BY") for x in d["USER_ROLE"]},
                    findings={(f["num"], f["grantee"], f["user"], f["detail"]): f for f in cached("findings", findings)},
                    status={u: status(u) for u in users}, sens=set(sens), run=dict(run))
    return cached("facts", make)


VERB = {"names": "see", "read": "read", "change": "change", "own": "own", "admin": "reach as admin"}


def names_text(xs):
    xs = sorted(xs)
    return ", ".join(xs) if len(xs) <= 2 else f"{xs[0]}, {xs[1]} and {plural(len(xs) - 2, 'other')}"


def impact_text(pairs, top, gain, sensitive):
    """'ANALYST_01, ANALYST_02 can now read SALES.MART.VW_CUSTOMER', from the (user, object) pairs that changed."""
    if not pairs:
        return ("Nobody gains new access: everyone it reaches had it another way" if gain else
                "Nobody loses access: they keep it another way")
    us, objs = {u for u, _ in pairs}, {o for _, o in pairs}
    k = sum(o in sensitive for o in objs)
    what = next(iter(objs)) if len(objs) == 1 else f"{len(objs)} objects" + f" ({k} sensitive)" * bool(k)
    return f"{names_text(us)} {'can now' if gain else 'can no longer'} {VERB[top]} {what}"


def grant_events(keys, links, gain, pairs, fs, by):
    """One event per grant added (gain) or removed, on the lookups of the data set that has it: the (user, object)
    pairs that changed through it and the findings it started (gain) or ended (fs). links: keys are (role, user)."""
    out = []
    for key in keys:
        if links:
            role, u = key
            us, objs = {u}, {x for r in bfs([role]) for _, _, x in granted.get(r, [])}
            text = f"{u} was granted role {role}" if gain else f"Role {role} was revoked from {u}"
            edge, subj = (u, role, None), [u, role]
        else:
            r, pv, on_, o = key
            link = on_ in ROLE_ON and pv == "USAGE"
            us = ups(r)[1]
            objs = {x for q in bfs([o]) for _, _, x in granted.get(q, [])} if link else {o}
            text = (f"{r} was granted role {o}" if link else f"{r} was granted {pv} on {o}") if gain else \
                (f"Role {o} was revoked from {r}" if link else f"{pv} on {o} was revoked from {r}")
            edge, subj = (r, o, None if link else pv), [r, o]
        fx = [f for f in fs if f["edge"] == edge or any((e["grantee"], e["to"], e["priv"]) == edge for e in f["edges"])]
        out.append(dict(edge=edge, pairs=[(u, o) for u, o in pairs if u in us and o in objs], subjects=subj,
                        by=by.get(key), findings=fx, text=text))
    return out


def event_counts(events):
    """Events per filter of What changed: all, gain, lose, risk (a new finding on it), sensitive."""
    return dict(all=len(events), gain=sum(e["kind"] == "gain" for e in events), lose=sum(e["kind"] == "lose" for e in events),
                risk=sum(any(not f["fixed"] for f in e["findings"]) for e in events),
                sensitive=sum(e["sensitive"] for e in events))


SENS_RULES = {"6", "7", "10", "11", "15", "22"}  # rules about sensitive data


def side_objects(side):
    return {o for _, o in side["access"]} | {k[3] for k in side["grants"] if k[2] not in ROLE_ON}


def diff(prev):
    """Screen 14: what changed from data set prev to the loaded one. events [dict(id, kind gain | lose | user | risk |
    fixed, text, impact, by (GRANTED_BY, when known), sensitive, findings [dict(num, severity, title, fixed)], link
    (page, params), subjects (every name it is about), people, objects)], counts per filter, new / fixed / high
    findings, gained and lost (user, object) pairs, people who gained a sensitive object, and the two run times."""
    now = facts()
    rank = LEVELS.index
    with loaded(prev):
        old = facts()
        gained = [(u, o) for (u, o), (lv, _) in now["access"].items()
                  if (u, o) not in old["access"] or rank(lv) > rank(old["access"][(u, o)][0])]
        lost = [(u, o) for (u, o), (lv, _) in old["access"].items()
                if (u, o) not in now["access"] or rank(lv) > rank(now["access"][(u, o)][0])]
        n3, o3 = {k[:3] for k in now["findings"]}, {k[:3] for k in old["findings"]}  # same rule, grantee: same finding
        fixed = [f for k, f in old["findings"].items() if k not in now["findings"] and k[:3] not in n3]
        new = [f for k, f in now["findings"].items() if k not in old["findings"] and k[:3] not in o3]
        removed = grant_events([k for k in old["grants"] if k not in now["grants"]], False, False, lost, fixed, old["grants"])
        removed += grant_events([k for k in old["user_roles"] if k not in now["user_roles"]], True, False, lost, fixed,
                                old["user_roles"])
    added = grant_events([k for k in now["grants"] if k not in old["grants"]], False, True, gained, new, now["grants"])
    added += grant_events([k for k in now["user_roles"] if k not in old["user_roles"]], True, True, gained, new,
                          now["user_roles"])

    def chip(f, gain):
        return dict(num=f["num"], severity=SEVERITY.get(f["num"], "Low"), title=RULES[f["num"]][0], fixed=not gain)

    events, told = [], set()
    for gain, xs in ((True, added), (False, removed)):
        side = now if gain else old
        for x in xs:
            told.update(id(f) for f in x["findings"])
            objs, target = sorted({o for _, o in x["pairs"]}), x["edge"][1]
            top = max((side["access"][p][0] for p in x["pairs"]), key=rank, default="read")
            events.append(dict(kind="gain" if gain else "lose", text=x["text"], by=x["by"],
                               impact=impact_text(x["pairs"], top, gain, side["sens"]),
                               sensitive=target in side["sens"] or any(o in side["sens"] for o in objs),
                               findings=list({f["num"]: chip(f, gain) for f in x["findings"]}.values()),
                               link=dict(page="object", params=dict(name=target)) if target in side_objects(side) else
                               dict(page="access", params=dict(role=target)),
                               subjects=sorted(set(x["subjects"]) | {u for u, _ in x["pairs"]} | set(objs)),
                               people=sorted({u for u, _ in x["pairs"]}), objects=objs))
    for u in sorted(set(now["status"]) | set(old["status"])):
        was, st = old["status"].get(u), now["status"].get(u)
        if was == st:
            continue
        reads = sorted({o for (v, o) in now["access"] if v == u and o in now["sens"]})
        text = (f"New user {u}" if was is None else f"User {u} is gone" if st is None else
                f"{u} became dormant (no login for {DORMANT_DAYS} days)" if st == "dormant" else
                f"{u} was disabled" if st == "disabled" else f"{u} is {st} now (was {was})")
        events.append(dict(kind="user", text=text, by=None, sensitive=bool(reads), findings=[], people=[u], objects=reads,
                           impact=f"Still reads {plural(len(reads), 'sensitive object')}" if reads and st != "active" else "",
                           link=dict(page="access", params=dict(user=u)), subjects=[u] + reads))
    for gain, fs in ((True, new), (False, fixed)):
        side = now if gain else old
        for f in fs:
            if id(f) in told:
                continue
            ps = [p for p in f.get("paths") or [f["path"]] if p]
            objs = sorted({n for p in ps for n in p if n in side["sens"]})
            events.append(dict(kind="risk" if gain else "fixed", by=None, sensitive=bool(objs) or f["num"] in SENS_RULES,
                               impact=f["detail"],
                               text=f"{'New' if gain else 'Fixed'} {SEVERITY.get(f['num'], 'Low').lower()} finding · "
                                    f"#{f['num']} {RULES[f['num']][0]}: {f['grantee']}",
                               findings=[chip(f, gain)], people=[f["grantee"]] if f["user"] else [], objects=objs,
                               link=dict(page="rules", params=dict(rule=f["num"])),
                               subjects=sorted({f["grantee"]} | {n for p in ps for n in p})))
    order = ("risk", "gain", "lose", "user", "fixed")
    events.sort(key=lambda e: (order.index(e["kind"]), not e["findings"], -len(e["people"]), e["text"]))
    for i, e in enumerate(events):
        e["id"] = str(i)
    return dict(events=events, counts=event_counts(events), new=len(new), fixed=len(fixed),
                high=sum(SEVERITY.get(f["num"]) in ("Critical", "High") for f in new), gained=gained, lost=lost,
                sens_gained=sorted({u for u, o in gained if o in now["sens"]}),
                runs=dict(before=str(old["run"].get("FINISHED_AT"))[:16], now=str(now["run"].get("FINISHED_AT"))[:16]))


# ---------- rules ----------

def plural(n, word):
    return f"{n} {word}{'s' * (n != 1)}"


def fix_changes(edges):
    """what_if() changes that remove these grant edges (a finding's fix, for the change plan), each once."""
    out = []
    for e in edges:
        c = (dict(op="revoke_priv", role=e["grantee"], privilege=e["priv"], object=e["to"]) if e["priv"] else
             dict(op="revoke_role_from_user", role=e["to"], user=e["grantee"]) if e["user"] else
             dict(op="revoke_role_from_role", role=e["to"], grantee=e["grantee"]))
        if c not in out:
            out.append(c)
    return out


def finding_objects(f):
    """Objects a rule_rows() finding is about: what its fix revokes on, the object itself, or where its paths end."""
    xs = [e["to"] for e in f["edges"] if e["priv"]] + [f["grantee"]] * (f["kind"] == "object")
    return list(dict.fromkeys(xs + [p[-1] for p in f["paths"] if p and p[-1] in kinds]))


def rule_rows():
    """Rule checks page. Row: rule ("1 ..."), num, title, why, severity (SEVERITY), grantee, kind, detail, path,
    paths, iac, sql (fix texts, "" when no SQL fits), affects (users who lose something when the fix is applied, net of
    their other paths; None when the fix revokes nothing), losers (those users), impact (affects as text: "3 users lose it", "5 readers
    exposed", "—"), same_fix (rule label of an earlier finding with the same fix), edges (grant edges the fix removes),
    edge ((from, to, privilege) the finding applies to, privilege None for a role link; None for an object finding)."""
    out, seen = [], {}
    for f in cached("findings", findings):
        iac, sql = f.get("fix") or fix_text(f["edges"])
        n, t = f["num"], RULES[f["num"]][0]
        affects, impact, who = f.get("affects"), f.get("impact"), []
        if f["edges"]:
            who = sorted(set().union(*(lose(e) for e in f["edges"])))
            affects = len(who)
            impact = plural(affects, "user") + " lose" + "s" * (affects == 1) + " access"
        out.append(dict(rule=f"{n} {t}", num=n, title=t, why=RULES[n][1], severity=SEVERITY.get(n, "Low"), edge=f["edge"],
                        grantee=f["grantee"], kind="user" if f["user"] else role_kind(f["grantee"]), detail=f["detail"], path=f["path"],
                        paths=f.get("paths", [f["path"]]), edges=f["edges"], iac=iac, sql=sql, affects=affects, losers=who,
                        impact=impact or "—", same_fix=seen.get(sql, "") if sql else ""))
        if sql:
            seen.setdefault(sql, f"Rule {n}")
    return out


def checks():
    """Rules broken by the grants: rows (num, title, grantee, detail, path)."""
    return [(f["num"], RULES[f["num"]][0], f["grantee"], f["detail"], f["path"]) for f in findings()]


def find(num, grantee, detail, path, edges=(), edge=None, user=False, **kw):
    """A finding; user: the grantee is a user (not a role of the same name); edge (from, to, privilege or None for a
    role link): the graph edge it applies to, by default the first grant edge of the fix, else the last link of path
    when that is a role link (an edge into an object needs its privilege)."""
    uniq = [dict(t) for t in dict.fromkeys(tuple(e.items()) for e in edges)]
    if edge is None and uniq:
        edge = (uniq[0]["grantee"], uniq[0]["to"], uniq[0]["priv"])
    elif edge is None and len(path) > 1 and role_kind(path[-1]) != "object":
        edge = (path[-2], path[-1], None)
    return dict(num=num, grantee=grantee, detail=detail, path=path, edges=uniq, edge=edge, user=user, **kw)


def is_build(r):
    return any(fnmatch.fnmatch(r, b) for b in BUILD)


def own_use(x):
    """x's own grants on data objects: {object: {read, write, own}}, once per data set."""
    def make():
        out = {}
        for pv, k, o in granted.get(x, []):
            c = priv_class(pv, k)
            if c in ("read", "write", "own") and is_data(k):
                out.setdefault(o, set()).add(c)
        return out
    return cached(("own", x), make)


def data_use(r):
    """What r reaches: ({role: shortest path r->...->role}, {data object: {read, write, own}})."""
    def make():
        best, cls = bfs([r]), {}
        for x in best:
            for o, c in own_use(x).items():
                cls.setdefault(o, set()).update(c)
        return best, cls
    return cached(("use", r), make)


def effective(r):
    """r's privileges, inherited included: [(privilege, type, object, path r->...->holder)]."""
    return [(pv, k, o, p) for x, p in data_use(r)[0].items() for pv, k, o in granted.get(x, [])]


def readonly_writes(role=None, only=None):
    """Rule 17, read-only roles that can write (role=None: every role but admin and BUILD roles).
    name heuristic: READ_ROLE_PATTERNS -> any write/own privilege; _EXECUTE -> write/own; _WRITE -> OWNERSHIP.
    behaviour heuristic: share of data objects it can only read >= READ_SHARE over >= READ_MIN_OBJECTS objects,
    but it writes/owns some. Row per (role, object): role, object, privileges, holder, path (role->...->holder->object),
    via {privilege: path role->...->holder}, inherited (holder is another role), how (name | behaviour | both),
    read_only, objects (counts for behaviour)."""
    out = []
    for r in [role] if role else roles:
        if r in ADMIN or r == "PUBLIC" or is_build(r) or not inside(only, r, "17"):
            continue
        cls = data_use(r)[1]
        bad = {"own"} if r.upper().endswith("_WRITE") else \
            {"write", "own"} if READ_ROLE_PATTERNS.search(r) or r.upper().endswith("_EXECUTE") else set()
        ro = [o for o, c in cls.items() if c == {"read"}]
        stray = {o for o, c in cls.items() if c & {"write", "own"}}
        beh = len(cls) >= READ_MIN_OBJECTS and stray and len(ro) / len(cls) >= READ_SHARE
        if not (bad or beh):
            continue
        eff = effective(r)
        by_name = {(pv, o): p for pv, k, o, p in eff if priv_class(pv, k) in bad}
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


SCOPED = {"3", "5", "7", "10", "11", "14", "17", "23"}  # rules whose findings(only) check only the names in only
GROW = {"14", "17", "23"}  # of those, the ones a removed grant can start (a longer shortest chain, a higher read share)


def inside(only, name, num):
    """findings(only): rule num checks name (only=None: everyone)."""
    return only is None or name in only.get(num, ())


def rules_model(only=None):
    """Rules 1-4, 13, 14: the layered role model."""
    out = []
    for role, user in user_grants:
        if role_kind(role) == "technical":
            out.append(find("1", user, role, [user, role], [role_edge(user, role, True)], user=True))
    for child, parent in role_grants:  # kinds, not prefixes: a database role DB.ROLE may start like one
        if role_kind(child) == "technical" and role_kind(parent) == "group":
            out.append(find("1", parent, child, [parent, child], [role_edge(parent, child)]))
    for r, pv, k, o in privs:
        if role_kind(r) == "functional":
            out.append(find("2", r, f"{pv} on ACCOUNT" if k == "ACCOUNT" else f"{pv} on {k} {o}", [r, o],
                            [priv_edge(r, pv, k, o)]))
    # rule 3 without parsing DB/schema from names: a consumer holds a technical ..._READ role directly and also through
    # another role it holds (READ inside WRITE); technical-to-technical links are the model's own, so not checked
    consumers = [(g, h, True) for g, h in roles_of.items()] + [(g, h, False) for g, h in holds.items()
                                                               if role_kind(g) != "technical"]
    for g, direct, u in consumers:  # one finding per (consumer, held role, READ role), shortest path
        for d in direct if inside(only, g, "3") else ():
            best = bfs([d])
            for t in dict.fromkeys(direct):
                p = best.get(t)
                if t != d and p and role_kind(t) == "technical" and t.endswith("_READ"):
                    out.append(find("3", g, t, [g] + p, [role_edge(g, t, u)], paths=[[g, t], [g] + p], user=u))
    for r in roles:
        if role_kind(r) == "technical" and r.endswith("_OWNER"):
            for g in users_of.get(r, []):
                out.append(find("4", g, r, [g, r], [role_edge(g, r, True)], user=True))
            for g in held_by.get(r, []):
                if role_kind(g) != "technical" and not is_build(g):
                    out.append(find("4", g, r, [g, r], [role_edge(g, r)]))
    for r in roles:  # 13; technical roles without holders are the model's unused capability roles, by design
        if (role_kind(r) in ("functional", "group") and r != "PUBLIC" and not is_builtin(r) and not users_of.get(r)
                and not held_by.get(r)):
            kids = sorted(holds.get(r, []))
            out.append(find("13", r, f"holds {plural(len(kids), 'role')}" + (f": {', '.join(kids)}" if kids else "")
                            + f"; {plural(len(granted.get(r, [])), 'privilege')} of its own", [r],
                            fix=(f"Remove in the infrastructure-as-code repo: role {r}", f"DROP ROLE {sql_name(r)};")))
    for r in sorted(x for x in users_of if inside(only, x, "14")):  # 14: per role granted to users, the deepest grant
        deep = None  # the first grant of the longest chain, a data object first; shorter chains can't win
        for x, p in sorted(bfs([r]).items(), key=lambda t: -len(t[1])):
            if deep and len(p) < deep[0]:
                break
            for pv, k, o in granted.get(x, []):
                if deep is None or (len(p), is_data(k)) > (deep[0], deep[4]):
                    deep = (len(p), pv, o, p, is_data(k))
        if deep and deep[0] > MAX_DEPTH_RULE:
            out.append(find("14", r, f"{deep[0]} roles deep to {deep[1]} on {deep[2]}; held by "
                                     f"{len(users_of[r])} users", deep[3] + [deep[2]], edge=(deep[3][-1], deep[2], deep[1]),
                            fix=("Shorten the chain in the infrastructure-as-code repo", "")))
    return out


def rules_admin(only=None):
    """Rules 5, 9, 12: admin roles, PUBLIC, admin default roles."""
    out = []
    near = set().union(*(ups(r)[1] for r in ADMIN if r in roles))  # reach only: skips the path walk for everyone else
    for u in users:  # 5: one finding per (person, admin role), shortest path; one below another admin role is not
        if u in near and not is_service(u) and inside(only, u, "5"):
            for r, ps in group((p[-1], p) for p in admin_paths(u, user=True)).items():
                p = ps[0]
                if not ADMIN & set(p[1:-1]):
                    out.append(find("5", u, r, p, [role_edge(p[-2], p[-1], len(p) == 2)], paths=ps, user=True))
    for r, pv, k, o in privs:
        if r == "PUBLIC" and not (k == "ACCOUNT" and pv in DEFAULT_PUBLIC) and not is_builtin(o):
            out.append(find("9", r, f"{pv} on {k} {o}", [r, o], [priv_edge(r, pv, k, o)]))
    for child, parent in role_grants:
        if parent == "PUBLIC" and not is_builtin(child):
            out.append(find("9", parent, f"role {child}", [parent, child], [role_edge(parent, child)]))
    for u in users:
        dr = (profile.get(u) or {}).get("DEFAULT_ROLE")
        if dr in ADMIN:
            out.append(find("12", u, f"default role {dr}", [u, dr], user=True, affects=1, impact="1 user", fix=(f"Change in the infrastructure-as-code repo: default role of "
                                                          f"user {u}", f"ALTER USER {sql_name(u)} SET DEFAULT_ROLE = "
                                                                       "<functional role>;")))
    return out


def rules_sensitive(only=None):
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
    read_by = {o: readers(o) for o in s}
    for u in users:  # 7
        if is_service(u) or not inside(only, u, "7"):
            continue
        objs = sorted(o for o, us in read_by.items() if u in us)
        if objs and (is_dormant(u) or is_disabled(u)):
            d = login_days(u)
            why = ("disabled; " if is_disabled(u) else "") + ("never logged in" if d is None else f"last login {d} days ago")
            out.append(find("7", u, f"{why}; reads {len(objs)} sensitive: {', '.join(objs)}", [u],
                            [role_edge(u, r, True) for r in roles_of.get(u, [])], user=True))
    writes = {}  # user -> {sensitive object: [(privilege, type, holder)]}: reach only, no path listing
    for o in s:
        for r, pv, k in on.get(o, []):
            if priv_class(pv, k) in ("write", "own"):
                for u in ups(r)[1]:
                    writes.setdefault(u, {}).setdefault(o, []).append((pv, k, r))
    for u in users:  # 10: one finding per person; the fix revokes every write grant it uses, on the holder
        got = writes.get(u)
        if got and not is_service(u) and inside(only, u, "10"):
            v = {o: sorted({pv for pv, _, _ in x}) for o, x in sorted(got.items())}
            edges = [priv_edge(r, pv, k, o) for o, x in sorted(got.items()) for pv, k, r in x]
            o0, best = next(iter(v)), best_paths(u, True)
            out.append(find("10", u, "; ".join(f"{', '.join(pv)} on {o}" for o, pv in v.items()),
                            min((best[r] for _, _, r in got[o0]), key=len) + [o0], edges, user=True))
    for r in roles:  # 11: the fix cuts every held role (and own grant) that leads to sensitive data
        if role_kind(r) == "group" and inside(only, r, "11"):
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
                            [role_edge(u, r, True) for r in roles_of[u]], user=True))
    for u in users:
        if not is_service(u) and not is_disabled(u) and roles_of.get(u) and is_dormant(u):
            d = login_days(u)
            out.append(find("16", u, ("never logged in" if d is None else f"last login {d} days ago") + "; holds "
                            + ", ".join(roles_of[u]), [u], [role_edge(u, r, True) for r in roles_of[u]], user=True))
    return out


def rule17(only=None):
    """Rule 17: read-only roles that can write. An inherited write on a role flagged by its name only, that is not
    mostly read either, gets a review hint instead of SQL (the name may just be a team name)."""
    out = []
    for x in cached("ro", readonly_writes) if only is None else readonly_writes(only=only):
        r, p = x["role"], x["path"]
        mostly = f"mostly read: {x['read_only']} of {x['objects']} objects read-only; " if x["how"] != "name" else ""
        src = f"via {x['holder']} (inherited)" if x["inherited"] else "direct"
        edges = [holder_edge(r, pv, x["object"]) if q[-1] == r else role_edge(r, q[1]) for pv, q in x["via"].items()]
        kw = {}
        if x["how"] == "name" and x["inherited"] and (not x["objects"] or x["read_only"] / x["objects"] < READ_SHARE):
            kw = dict(fix=(f"Check what {r} is for; if it is read-only, remove the write role it inherits in the "
                           "infrastructure-as-code repo", ""), edge=(x["holder"], x["object"], x["privileges"][0]))
            edges = []
        out.append(find("17", r, f"{mostly}{', '.join(x['privileges'])} on {x['object']} {src}; heuristic: {x['how']}",
                        p, edges, **kw))
    return out


def unusual(role=None):
    """Rule 18: privilege sets that differ from the role's capability (name suffix _READ, _WRITE, ... -> CAP_PRIVS),
    on objects inside a schema. extra: held directly, not in the standard set; missing: a partial set, some of the
    capability's own privileges (beyond READ's) held on the object and others of the type's standard ones not
    reached. Row per (role, object): role, cap, object, type, held, extra, missing."""
    out = []
    for r in [role] if role else roles:
        cap = next((c for c in CAP_PRIVS if r.upper().endswith("_" + c.upper())), None)
        held = {}
        for pv, k, o in granted.get(r, []) if cap else []:
            if k not in ("DATABASE", "SCHEMA", "ACCOUNT") and not k.startswith("FUTURE") and split_name(o, k)[1]:
                held.setdefault((k, o), set()).add(pv)
        if not held:
            continue
        eff = {}
        for x in bfs([r]):
            for pv, k, o in granted.get(x, []):
                eff.setdefault((k, o), set()).add(pv)
        std = CAP_PRIVS[cap]
        own = std - CAP_PRIVS.get("READ", set())
        for (k, o), h in sorted(held.items(), key=lambda x: (x[0][1], x[0][0])):
            need = own & STANDARD.get(k, set())
            extra, missing = h - std, (need - eff[(k, o)]) if h & need else set()
            if extra or missing:
                out.append(dict(role=r, cap=cap, object=o, type=k, held=sorted(h), extra=sorted(extra),
                                missing=sorted(missing)))
    return out


def rule18():
    out = []
    for x in cached("unusual", unusual):
        r, o, k = x["role"], x["object"], x["type"]
        std = sorted(CAP_PRIVS[x["cap"]], key=lambda p: (valid_privs(k) + [p]).index(p))
        bits = ([f"extra {', '.join(x['extra'])}"] if x["extra"] else []) + \
            ([f"missing {', '.join(x['missing'])}"] if x["missing"] else [])
        edges = [priv_edge(r, pv, k, o) for pv in x["extra"]]
        kw = {} if edges else dict(fix=(f"Grant {', '.join(x['missing'])} on {k.lower()} {o} to role {r} in the "
                                        "infrastructure-as-code repo, or move the partial grant to its own role", ""))
        out.append(find("18", r, f"{x['cap']} role holds {', '.join(x['held'])} on {k.lower()} {o}; standard "
                                 f"{x['cap']}: {', '.join(std) or 'none'}; " + "; ".join(bits), [r, o], edges,
                        edge=(r, o, (x["extra"] or x["held"])[0]), **kw))
    return out


def rule19():
    """Rule 19: EXECUTE TASK reaching a person (not a service user) or a consumer role (functional or group, not BUILD)."""
    out = []
    for h, pv, k, o in privs:
        if pv != "EXECUTE TASK" or k != "ACCOUNT":
            continue
        best = {}
        for p in up([h]):
            q, u = p[::-1], from_user(p[::-1])
            x = node_name(q[0])
            if (u and not is_service(x)) or (not u and role_kind(x) in ("functional", "group") and not is_build(x)):
                if (x, u) not in best or len(q) < len(best[(x, u)]):
                    best[(x, u)] = q
        for (x, u), q in sorted(best.items()):
            out.append(find("19", x, "EXECUTE TASK on ACCOUNT " + (f"via {' > '.join(q[1:])}" if len(q) > 1 else
                                                                   "granted directly"), [x] + q[1:] + [o],
                            [priv_edge(h, pv, k, o)], user=u))
    return out


def owner_side(r, o):
    """r is a build or admin role, or reaches OWNERSHIP of o (the owner or a role above it)."""
    return is_build(r) or r in ADMIN or any(pv == "OWNERSHIP" and x == o for y in bfs([r]) for pv, _, x in granted.get(y, []))


def rules_operate():
    """Rules 20, 21: OPERATE on a task, MODIFY or OPERATE on a warehouse, held outside owner/build roles."""
    out = []
    for r, pv, k, o in privs:
        num = "20" if k == "TASK" and pv == "OPERATE" else "21" if k == "WAREHOUSE" and pv in ("MODIFY", "OPERATE") else None
        if num and not owner_side(r, o):
            owners = ", ".join(sorted({x for x, p2, _ in on.get(o, []) if p2 == "OWNERSHIP"})) or "not in snapshot"
            n = len(users_through(r))
            what = f"runs as its owner {owners}" if num == "20" else f"owner {owners}"
            out.append(find(num, r, f"{pv} on {k.lower()} {o}; {what}; {plural(n, 'user')} reach{'es' * (n == 1)} it", [r, o],
                            [priv_edge(r, pv, k, o)]))
    return out


def rule22():
    """Rule 22: a consumer role (functional or group, not BUILD) reads a stream on a sensitive table it cannot read."""
    out, s = [], sensitive()
    for st, src in sorted(streams.items()):
        if src not in s:
            continue
        best = {}
        for x, pv, p in who_can(st):
            if (pv in READ_PRIVS and not from_user(p) and role_kind(x) in ("functional", "group") and not is_build(x)
                    and (x not in best or len(p) < len(best[x][1]))):
                best[x] = (pv, p)
        for x, (pv, p) in sorted(best.items()):
            if src not in reads([x]):
                out.append(find("22", x, f"reads stream {st} on sensitive {src}, but cannot read {src}", p + [st],
                                [holder_edge(p[-1], pv, st)]))
    return out


def rule23(only=None):
    """Rule 23: CREATE ... on a schema reached by a read-only role (rule 17's name or behaviour heuristic; behaviour
    here: share of data objects it only reads >= READ_SHARE over >= READ_MIN_OBJECTS objects)."""
    out = []
    for r in roles:
        if r in ADMIN or r == "PUBLIC" or is_build(r) or not inside(only, r, "23"):
            continue
        cls = data_use(r)[1]
        name = bool(READ_ROLE_PATTERNS.search(r))
        beh = len(cls) >= READ_MIN_OBJECTS and sum(c == {"read"} for c in cls.values()) / max(len(cls), 1) >= READ_SHARE
        if not (name or beh):
            continue
        made = {}
        for pv, k, o, p in effective(r):
            if k == "SCHEMA" and pv.startswith("CREATE "):
                made.setdefault(o, []).append((pv, p))
        if not made:
            continue
        how = "both" if name and beh else "name" if name else "behaviour"
        for o, v in sorted(made.items()):
            pv0, p = min(v, key=lambda t: len(t[1]))
            src = f"via {p[-1]} (inherited)" if p[-1] != r else "direct"
            out.append(find("23", r, f"{', '.join(sorted({pv for pv, _ in v}))} on schema {o} {src}; heuristic: {how}",
                            p + [o], [holder_edge(q[-1], pv, o) for pv, q in v], edge=(p[-1], o, pv0)))
    return out


def findings(only=None):
    """Every rule finding, in rule order: dict(num, grantee, detail, path, edges [grant edges the fix removes], edge
    (see find()), fix, paths, affects, impact). only: {rule: users and roles it checks} for the per-grantee rules
    (SCOPED), the other rules check everything (what_if: only what a change can touch)."""
    out = (rules_model(only) + rules_admin(only) + rules_sensitive(only) + rules_users() + rule17(only) + rule18()
           + rule19() + rules_operate() + rule22() + rule23(only))
    return sorted(out, key=lambda f: int(f["num"]))


LOADED = os.path.getmtime(__file__)  # app.fresh() reloads this module when the file is newer
