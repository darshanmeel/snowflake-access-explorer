"""Synthetic twin of a big account: twin(scale, seed) returns the dict access.fake() returns, shaped like one real
account's profile (counts, histograms and ratios only, below; every name is made up), with findings for all 29 rules.

FAKE=twin loads it instead of access.fake() (FAKE_SCALE, default 1; python run.py --fake twin --scale 0.1), with
ROLE_PREFIXES=R_F_,R_T_ unless set. scale < 1 shrinks every count; the same scale and seed give the same data.
"""
import bisect
import os
import random
from datetime import datetime, timedelta

import access as a

END = datetime(2026, 11, 2, 7, 0)
# the profile at scale 1: (low, high) buckets -> count
USERS, SERVICE, WITH_ROLES, DISABLED_ROLES, DISABLED_LOGIN = 6017, 8, 3691, 47, 81
STATUS = dict(never=3083, disabled=2215, dormant=199)  # the other persons are active
LOGIN_ACTIVE = {(0, 7): 232, (8, 30): 181, (31, 89): 128}
LOGIN_OLD = {(91, 180): 90, (181, 365): 156, (366, 900): 17}
ROLES_PER_USER = {(1, 1): 3448, (2, 2): 157, (3, 4): 57, (5, 9): 29}
USERS_PER_ROLE = {(1, 1): 24, (2, 2): 7, (3, 4): 5, (5, 9): 9, (10, 19): 6, (20, 49): 6, (50, 99): 1, (100, 499): 2}
ADMINS = dict(ACCOUNTADMIN=6, ORGADMIN=3, SECURITYADMIN=5, SYSADMIN=14)
# the profile splits names on dots, so a user named like first.last@domain counts as a "schema" with one object and
# its first part as a "database": the 1-49 database buckets and the 1-object schemas are user names (NAME_SHARE)
BIG_DBS, MANAGED_DBS = 108, 100
SCHEMAS = {(1, 1): 18, (2, 2): 25, (3, 4): 34, (5, 9): 50, (10, 19): 1333, (20, 49): 537, (50, 99): 164,
           (100, 499): 386, (500, 999): 40}
MID_DBS = {(50, 99): 9, (100, 499): 18, (500, 999): 12}
NAME_SHARE = {(1, 1): 1933, (2, 2): 324, (3, 4): 255, (5, 9): 164, (10, 19): 66, (20, 49): 28}  # persons per first name
OBJECTS, SCHEMA_OBJECTS, FUTURE_SCHEMAS, MANAGED, NO_WRITE, EXECUTE = 198913, 2718, 2369, 1075, 3, 762
KINDS = {"TABLE": 50415, "PROCEDURE": 47444, "VIEW": 31180, "EXTERNAL TABLE": 26463, "STAGE": 4618, "FILE FORMAT": 545,
         "FUNCTION": 500, "DYNAMIC_TABLE": 540, "MATERIALIZED_VIEW": 450, "SECRET": 250, "EVENT_TABLE": 200,
         "ICEBERG_TABLE": 200, "TASK": 120}
PREFIX = {"TABLE": "TBL", "PROCEDURE": "SP", "VIEW": "VW", "EXTERNAL TABLE": "EXT", "STAGE": "STG", "FILE FORMAT": "FF",
          "FUNCTION": "FN", "DYNAMIC_TABLE": "DT", "MATERIALIZED_VIEW": "MV", "SECRET": "SEC", "EVENT_TABLE": "EVT",
          "ICEBERG_TABLE": "ICE", "TASK": "TSK", "STREAM": "STR", "STREAMLIT": "ST"}
READABLE = {"TABLE", "VIEW", "EXTERNAL TABLE", "DYNAMIC_TABLE", "MATERIALIZED_VIEW", "EVENT_TABLE", "ICEBERG_TABLE"}
FUTURE = ["TABLE", "VIEW", "EXTERNAL_TABLE", "FILE_FORMAT", "FUNCTION", "MATERIALIZED_VIEW", "PROCEDURE", "SEQUENCE",
          "STAGE", "STREAM", "TASK"]  # plus DYNAMIC_TABLE in 1671 of 2369 schemas
FUNCS = dict(READER=19, ENGINEER=18, STEWARD=18, USAGE=15, VIEWER=12, G=6, CO=5)  # functional roles by suffix
GROUPS, LEGACY, DB_ROLES, WAREHOUSES, INTEGRATIONS, APPS = 16, 6, 35, 60, 70, 5
OWNER_UPDATES, OWNER_TRUNCATES, SENS_SCHEMAS, SENS_OBJECTS, SENS_COLUMNS = 17058, 10000, 40, 374, 2068
TAG_SHAPES = {"GOVERNANCE.TAGS.DATA_DOMAIN_CODE": 5555, "GOV_TAG_HUB_DB.TAGS.DATA_OWNER_TEAM": 5552,
              "GOV_DB.TAGS.RETENTION_CLASS_CODE": 2259, "GOV_TAG_HUB_DB_2.TAGS.MASKING_GROUP_KEY": 2238,
              "GOV_TAG_DB.TAGS.SOURCE_SYSTEM_CODE": 2203, "GOV_DB2_TAGS.TAGS.REGION_ACCESS_KEY": 1111}
SCHEMA_TAGS, MASKED, ROW_POLICIES = 5, 16947, 8724
OWNER_READS = {(1, 1): 296, (2, 2): 568, (3, 4): 203, (5, 9): 49}  # READ roles of other schemas an owner holds
# account privileges -> holders (ACCOUNTADMIN first); PUBLIC holds the artifact ones Snowflake grants it
ACCOUNT = {"VIEW LINEAGE": 7, "CREATE DATABASE": 6, "MANAGE USER SUPPORT CASES": 5, "USE AI FUNCTIONS": 4,
           "CREATE WAREHOUSE": 4, "CREATE ROLE": 4, "EXECUTE TASK": 4, "MANAGE GRANTS": 4, "CREATE USER": 3,
           "CREATE INTEGRATION": 3, "CREATE NETWORK POLICY": 3, "BIND SERVICE ENDPOINT": 3, "MODIFY EVENT TABLE": 2,
           "MANAGE ACCESS ON FILE ARTIFACTS": 2, "MANAGE BILLING": 2, "PURCHASE DATA EXCHANGE LISTING": 2,
           "APPLY TAG": 2, "MANAGE ACCESS ON CHART ARTIFACTS": 2, "MONITOR USAGE": 2, "CREATE LISTING": 2,
           "MANAGE ARTIFACT PUBLICATION": 2, "MANAGE ACCESS ON THREAD ARTIFACTS": 2,
           "MANAGE ACCESS ON DASHBOARD ARTIFACTS": 2, "MANAGE ACCESS ON REPORT ARTIFACTS": 2,
           "APPLY MASKING POLICY": 2, "EXECUTE AGENT TASK": 2, "MANAGE ORGANIZATION SUPPORT CASES": 1,
           "MONITOR ROLE": 1, "CREATE MIGRATION": 1, "MONITOR SECURITY": 1, "MODIFY SESSION TRACE LEVEL": 1,
           "DELETE LINEAGE": 1, "EXECUTE AUTO CLASSIFICATION": 1, "CREATE SNOWFLAKE INTELLIGENCE": 1,
           "CREATE CATALOG INTEGRATION": 1, "MANAGE CALLER GRANTS": 1, "MODIFY LOG LEVEL": 1,
           "ALTER EVENT ROUTING TABLE": 1, "APPLY JOIN POLICY": 1, "MANAGE EVENT SHARING": 1}
PUBLIC_PRIVS = ["VIEW LINEAGE", "USE AI FUNCTIONS", "BIND SERVICE ENDPOINT", "MANAGE ACCESS ON FILE ARTIFACTS",
                "MANAGE ACCESS ON CHART ARTIFACTS", "MANAGE ACCESS ON THREAD ARTIFACTS",
                "MANAGE ACCESS ON DASHBOARD ARTIFACTS", "MANAGE ACCESS ON REPORT ARTIFACTS", "MANAGE ARTIFACT PUBLICATION"]
ADMIN_ACCOUNT, CUSTOM_ACCOUNT = 142, 33  # account grants held by admin roles, by other roles (PUBLIC aside)
EXTRA = ["CREATE SHARE", "IMPORT SHARE", "CREATE ACCOUNT", "CREATE COMPUTE POOL", "CREATE DATA EXCHANGE LISTING",
         "CREATE APPLICATION", "CREATE APPLICATION PACKAGE", "CREATE CREDENTIAL", "CREATE EXTERNAL VOLUME",
         "CREATE FAILOVER GROUP", "CREATE REPLICATION GROUP", "CREATE ORGANIZATION LISTING", "EXECUTE MANAGED TASK",
         "EXECUTE ALERT", "IMPORT ORGANIZATION LISTING", "MONITOR EXECUTION", "OVERRIDE SHARE RESTRICTIONS",
         "RESOLVE ALL", "APPLY ROW ACCESS POLICY", "APPLY AGGREGATION POLICY", "APPLY PROJECTION POLICY",
         "APPLY SESSION POLICY", "APPLY PASSWORD POLICY", "APPLY AUTHENTICATION POLICY", "APPLY PACKAGES POLICY",
         "ATTACH POLICY", "AUDIT", "MANAGE ACCOUNT SUPPORT CASES", "EXECUTE MANAGED ALERT", "MANAGE WAREHOUSES",
         "MANAGE LISTING AUTO FULFILLMENT"]
# activity (ACCESS_HISTORY, 61 days) and object use (27 weeks)
ACT_ROWS, ACT_USERS, INFO_ROWS, APP_ROWS, PERSON_CHANGES, SPIKES = 629639, 569, 10817, 3792, 1008, 511
ROWS_PER_USER = {(1, 1): 21, (2, 2): 24, (3, 4): 72, (5, 9): 98, (10, 19): 180, (20, 49): 83, (50, 99): 28,
                 (100, 499): 30, (500, 999): 9, (1000, 20000): 24}
QUERIES_PER_ROW = {(1, 1): 459913, (2, 2): 69364, (3, 4): 36663, (5, 9): 26300, (10, 19): 10398, (20, 49): 15641,
                   (50, 99): 3475, (100, 499): 6144, (500, 999): 1100, (1000, 3000): 1043}  # 500-999 raised: spikes and the other buckets pull from it
# query type -> (queries in the profile, share logged as READ; the rest WRITE, or DDL for the CREATE / ALTER kind)
QTYPES = {"SELECT": (112206, 1), "INSERT": (107057, .4), "CREATE_VIEW": (84015, .4), "MERGE": (40108, .5),
          "CALL": (38552, .6), "DESCRIBE": (37583, 0), "EXTERNAL_TABLE_REFRESH": (37504, .5), "CREATE": (28851, 0),
          "TRUNCATE_TABLE": (26395, 0), "COPY": (26239, 0), "CREATE_TABLE": (23153, 0), "ALTER": (15565, 0),
          "CREATE_TABLE_AS_SELECT": (12863, .5), "UPDATE": (6377, 0), "CREATE_EXTERNAL_TABLE": (5952, 0)}
DDL = {"CREATE_VIEW", "DESCRIBE", "EXTERNAL_TABLE_REFRESH", "CREATE", "CREATE_TABLE", "ALTER", "CREATE_TABLE_AS_SELECT",
       "CREATE_EXTERNAL_TABLE"}
PAIR_DAYS = [1] * 10 + [2, 2, 3, 4, 6, 10, 20, 40]  # days a user uses one object
CLIENTS = {"Snowflake UI": 30, "JDBC": 20, "PythonConnector": 15, "ODBC": 10, "Go": 5, "JavaScript": 5, ".NET": 4,
           "SnowSQL": 4, "Snowflake CLI": 3, "Spark": 4}
USE_ROWS, USE_USERS, USE_WEEKS, USE_WRITE = 244405, 914, 27, 0.27
TEAMS = ["SALES", "FINANCE", "HR", "MARKETING", "RISK", "SUPPLY", "OPS", "PRODUCT", "CLAIMS", "PRICING", "FRAUD",
         "LOGISTICS", "BILLING", "CUSTOMER", "PAYMENTS", "TREASURY", "AUDIT", "LEGAL", "DATA", "PLATFORM", "QUALITY",
         "RESEARCH", "CREDIT", "SERVICE"]
LAYERS = ["RAW", "STAGE", "CLEAN", "CORE", "MART", "REPORT", "SANDBOX", "ARCHIVE", "LANDING", "CURATED", "PUBLISH",
          "AUDIT", "REF", "ODS", "EXPORT", "WORK"]
PII = [("EMAIL", "EMAIL", "IDENTIFIER"), ("PHONE", "PHONE_NUMBER", "IDENTIFIER"), ("BIRTH_DATE", "DATE_OF_BIRTH",
       "QUASI_IDENTIFIER"), ("LAST_NAME", "NAME", "IDENTIFIER"), ("POSTCODE", "POSTAL_CODE", "QUASI_IDENTIFIER"),
       ("IBAN", "BANK_ACCOUNT", "SENSITIVE"), ("NATIONAL_ID", "NATIONAL_IDENTIFIER", "IDENTIFIER"),
       ("CLIENT_IP", "IP_ADDRESS", "QUASI_IDENTIFIER"), ("SALARY", "SALARY", "SENSITIVE")]


def spread(rng, hist, n):
    """n values drawn from a histogram {(low, high): count}: each bucket's share of n (largest remainders), shuffled."""
    total = sum(hist.values())
    want = {b: c * n / total for b, c in hist.items()}
    got = {b: int(v) for b, v in want.items()}
    for b in sorted(want, key=lambda b: got[b] - want[b])[:n - sum(got.values())]:
        got[b] += 1
    out = [rng.randint(lo, hi) for (lo, hi), c in got.items() for _ in range(c)]
    rng.shuffle(out)
    return out


def draw(rng, hist):
    """One value from a histogram."""
    lo, hi = rng.choices(list(hist), weights=list(hist.values()))[0]
    return rng.randint(lo, hi)


def stamp(t):
    return t.strftime("%Y-%m-%d %H:%M")


def twin(scale=1.0, seed=7):
    rng, F, T = random.Random(seed), a.FUNC, a.TECH
    n = lambda x: max(1, round(x * scale))  # noqa: E731
    pv = []  # (role, privilege, granted on, object, future)
    links, dbr = [], []  # (child, parent): role links, database role links
    # ---- databases, schemas, objects ----
    dbs = [f"DB_{i:04}" for i in range(1, n(BIG_DBS) + n(sum(MID_DBS.values())) + 1)]
    big, mid = dbs[:n(BIG_DBS)], dbs[n(BIG_DBS):]
    managed_dbs = big[:n(MANAGED_DBS)]
    users_n, whs_n = n(USERS), n(WAREHOUSES)
    # schema sizes count what the profile counts per schema: its objects, the schema itself and its future grants
    sizes = sorted(spread(rng, SCHEMAS, n(sum(SCHEMAS.values()))))
    small, large = [x for x in sizes if x < 10], [x for x in sizes if x >= 10]
    home = {d: [] for d in big + mid}
    j = 0
    for d, t in zip(mid, spread(rng, MID_DBS, len(mid))):  # a middle database: one big schema or a few small ones
        i = bisect.bisect_right(large, t - 1) - 1
        if t > 10 and i >= 0:
            home[d].append(large.pop(i))
        while j < len(small) and (not home[d] or sum(home[d]) < t):
            home[d].append(small[j])
            j += 1
    for i, x in enumerate(sorted(large + small[j:], reverse=True)):
        home[big[i % len(big)]].append(x)
    named = []  # (db, schema, size)
    for d, ss in home.items():
        seen = {}
        for x in ss:
            w = LAYERS[len(seen) % len(LAYERS)]
            seen[w] = seen.get(w, 0) + 1
            named.append((d, w if seen[w] == 1 else f"{w}_{seen[w]:02}", x))
    cand = [x for x in named if x[0] in managed_dbs and x[2] >= 10] or named[:1]
    managed = rng.sample(cand, min(n(MANAGED), len(cand)))
    for d in managed_dbs:  # every managed database has at least one managed schema
        if not any(x[0] == d for x in managed):
            managed.append(max((x for x in named if x[0] == d), key=lambda x: x[2]))
    mset = {(x[0], x[1]) for x in managed}
    fut = [x for x in managed if x[2] >= 11] + [x for x in named if (x[0], x[1]) not in mset and x[2] >= 11]
    # future grants per schema: they count as its objects, so a schema of 11 may hold only them
    fut = {(x[0], x[1]): FUTURE + ["DYNAMIC_TABLE"] * (x[2] > 11 and rng.random() < 1671 / 2369)
           for x in fut[:n(FUTURE_SCHEMAS)]}
    rest = [(x[0], x[1]) for x in named if (x[0], x[1]) not in mset and x[2] >= 2]
    with_schema = mset | set(rng.sample(rest, min(len(rest), max(0, n(SCHEMA_OBJECTS) - len(mset)))))
    kinds, weights = list(KINDS), list(KINDS.values())
    schemas, by = [], {}  # (db, schema, [(object, kind)])
    for d, sc, x in named:
        m = x - len(fut[(d, sc)]) if (d, sc) in fut else x  # its own objects
        objs = [(f"{d}.{sc}.{PREFIX[k]}_{i:04}", k) for i, k in enumerate(rng.choices(kinds, weights, k=m), 1)]
        schemas.append((d, sc, objs))
        by[(d, sc)] = objs
    managed = [(d, sc, by[(d, sc)]) for d, sc, _ in managed]
    caps = {}  # (db, schema) -> {cap: role}
    for i, (d, sc, _) in enumerate(managed):
        caps[(d, sc)] = {c: f"{T}{d}_{sc}_{c}" for c in ("OWNER", "READ", "WRITE", "EXECUTE")
                         if not (c == "WRITE" and i < n(NO_WRITE)) and not (c == "EXECUTE" and i >= n(EXECUTE))}
    sens_schemas = [x for x in managed if any(k in ("TABLE", "VIEW") for _, k in x[2])]  # with future grants first (rule 15)
    sens_schemas = sorted(sens_schemas, key=lambda x: (x[0], x[1]) not in fut)[:max(3, n(SENS_SCHEMAS))]
    sens_pool = [o for x in sens_schemas for o, k in x[2] if k in ("TABLE", "VIEW")]
    sens = rng.sample(sens_pool, min(n(SENS_OBJECTS), len(sens_pool)))
    sens += [next(o for o, k in x[2] if k in ("TABLE", "VIEW")) for x in sens_schemas]  # one at least in each
    sens = list(dict.fromkeys(sens))
    sset = {(x[0], x[1]) for x in sens_schemas}
    groups = [f"AAD_GRP_{TEAMS[i % len(TEAMS)]}_{i // len(TEAMS) + 1:02}" for i in range(n(GROUPS))]
    legacy = [f"LEGACY_{TEAMS[-1 - i % len(TEAMS)]}_ADMIN" for i in range(n(LEGACY))]
    db_owner = {d: f"{T}{d}_OWNER" if d in managed_dbs else rng.choice(["SYSADMIN"] + legacy) for d in dbs}
    for d in dbs:
        pv.append((db_owner[d], "OWNERSHIP", "DATABASE", d, False))
    for d in managed_dbs:
        links.append((f"{T}{d}_OWNER", F + "DEPLOY"))
    fut_sens, stages = 0, 0
    tables, owner_of = [], {}
    for d, sc, objs in schemas:
        key, name, c = (d, sc), f"{d}.{sc}", caps.get((d, sc), {})
        own = c.get("OWNER") or db_owner[d]
        rd, wr, ex = c.get("READ"), c.get("WRITE"), c.get("EXECUTE")
        if key in with_schema:
            pv.append((own, "OWNERSHIP", "SCHEMA", name, False))
        pv += [(r, "USAGE", p, x, False) for r in (rd, wr, ex) if r for p, x in (("SCHEMA", name), ("DATABASE", d))]
        for o, k in objs:
            owner_of[o] = own
            pv.append((own, "OWNERSHIP", k, o, False))
            if rd and k in READABLE and (k != "EXTERNAL TABLE" or rng.random() < .12):  # most are read by their pipeline only
                pv += [(r, "SELECT", k, o, False) for r in ((rd, wr, ex) if k == "DYNAMIC_TABLE" else (rd,)) if r]
            elif rd and k == "STAGE" and rng.random() < .2:
                stages += 1
                pv.append((rd, "READ" if stages <= n(41) else "USAGE", k, o, False))
                if wr and stages <= n(29):
                    pv.append((wr, "WRITE", k, o, False))
            elif ex and k == "SECRET":
                pv.append((ex, "USAGE", k, o, False))
            if wr and k == "TABLE":
                pv += [(wr, p, k, o, False) for p in ("INSERT", "UPDATE", "DELETE", "TRUNCATE")]
            if ex and k in ("PROCEDURE", "FUNCTION"):
                pv.append((ex, "USAGE", k, o, False))
            if k == "TABLE" and c:
                tables.append(o)
        if c:
            links.append((c["OWNER"], f"{T}{d}_OWNER"))
            if wr:
                links.append((rd, wr))
        if key in fut:
            fk = fut[key]
            pv += [(own, "OWNERSHIP", k, f"{name}.<{k}>", True) for k in fk]
            fut_sens += key in sset
            if rd and (key not in sset or fut_sens <= n(3)):  # rule 15 on a few
                pv += [(rd, "SELECT", k, f"{name}.<{k}>", True) for k in ("TABLE", "VIEW", "EXTERNAL_TABLE", "MATERIALIZED_VIEW")]
            if wr:
                pv += [(wr, p, "TABLE", f"{name}.<TABLE>", True) for p in ("INSERT", "UPDATE", "DELETE", "TRUNCATE")]
            if ex:
                pv += [(ex, "USAGE", k, f"{name}.<{k}>", True) for k in ("PROCEDURE", "FUNCTION")]
    for i, x in enumerate(managed):  # CREATE on schemas, some held by READ roles (rule 23)
        c = caps[(x[0], x[1])]
        if i < n(53):
            pv.append((c["READ"] if i < n(10) else c.get("WRITE", c["READ"]), "CREATE VIEW", "SCHEMA", f"{x[0]}.{x[1]}", False))
        if i < n(13):
            pv.append((c["READ"] if i % 3 == 0 else c["OWNER"], "CREATE TABLE", "SCHEMA", f"{x[0]}.{x[1]}", False))
    pv += [(f"{T}{d}_OWNER", "CREATE SCHEMA", "DATABASE", d, False) for d in managed_dbs[:n(42)]]
    allcaps = list(caps.values())
    reads = [c["READ"] for c in allcaps]
    writes = [c["WRITE"] for c in allcaps if "WRITE" in c]
    execs = [c["EXECUTE"] for c in allcaps if "EXECUTE" in c]
    owners = [c["OWNER"] for c in allcaps]
    sens_reads = [caps[(x[0], x[1])]["READ"] for x in sens_schemas]
    # an owner reads other schemas (lineage): most READ roles feed one or two owners, a few shared ones many
    slots = [o for o, c in zip(owners, spread(rng, OWNER_READS, len(owners))) for _ in range(c)]
    shared = reads[::-1][:n(90)]  # from the end: the first READ roles carry rule findings
    feed = [r for i, r in enumerate(shared) for _ in range(25 if i < n(30) else 12)]
    feed += [reads[i % max(1, len(reads) - n(90))] for i in range(max(0, len(slots) - len(feed)))]
    rng.shuffle(slots)
    rng.shuffle(feed)
    links += list(dict.fromkeys((r, o) for r, o in zip(feed, slots) if r[:-5] != o[:-6]))
    links += [(o, F + "DEPLOY") for o in owners if rng.random() < .85]  # the build holds the schema owners too
    upd = rng.sample(owners, max(1, len(owners) // 2))
    seen = set()
    for i in range(n(OWNER_UPDATES) * 2):  # rule 18: an OWNER role holds only UPDATE (and TRUNCATE) on tables it does not own
        if len(seen) >= n(OWNER_UPDATES) or not tables:
            break
        r, t = rng.choice(upd), rng.choice(tables)
        if owner_of[t] != r and (r, t) not in seen:
            seen.add((r, t))
            pv.append((r, "UPDATE", "TABLE", t, False))
            if len(seen) <= n(OWNER_TRUNCATES):
                pv.append((r, "TRUNCATE", "TABLE", t, False))
    # ---- functional roles ----
    func = {s: [f"{F}{TEAMS[i % len(TEAMS)]}" + (f"_{i // len(TEAMS) + 1:02}" if i >= len(TEAMS) else "") + f"_{s}"
                for i in range(n(c))] for s, c in FUNCS.items()}
    common, deploy, apps_role = F + "COMMON_USAGE", F + "DEPLOY", F + "APPS_USAGE"
    pick = lambda xs, lo, hi: rng.sample(xs, min(len(xs), rng.randint(lo, hi)))  # noqa: E731
    for r in func["READER"] + func["VIEWER"]:
        links += [(x, r) for x in pick(reads, 8, 35)]
    rv, sh = func["READER"] + func["VIEWER"], set(shared)
    links += [(x, rv[i % len(rv)]) for i, x in enumerate(reads) if x not in sh and rng.random() < .5]  # half: a consumer more
    for i, r in enumerate(func["READER"] + func["VIEWER"]):  # rule 17: read-only by name, with a few write roles
        if i < n(8):
            links += [(x, r) for x in pick(writes, 1, 5)]
    plain = [w for w in writes if w not in {caps[k].get("WRITE") for k in sset}] or writes
    for i, r in enumerate(func["ENGINEER"]):
        ws = pick(plain, 5, 15)  # sensitive schemas are written by the build (rule 10 on a few)
        links += [(x, r) for x in ws + pick(execs, 1, 5)]
        if i < n(5):  # rule 3: READ held directly and inside a WRITE role
            links.append((ws[0].rsplit("_", 1)[0] + "_READ", r))
    links.append((owners[-1], func["ENGINEER"][0]))  # rule 4: an OWNER role on a consumer
    for r in func["STEWARD"]:
        links += [(x, r) for x in pick(sens_reads, 3, 15) + pick(reads, 1, 10)]
    for r in func["USAGE"]:
        links += [(x, r) for x in pick(execs, 3, 15)]
    for r in func["G"]:
        links += [(x, r) for x in pick(reads, 2, 6) + pick(execs, 0, 3)]
    for r in func["CO"]:
        links += [(x, r) for x in pick(func["G"] + func["READER"], 2, 5) + pick(reads, 0, 4)]
    links += [(x, common) for x in pick(sens_reads, 2, 2) + pick(reads, 5, 12)]
    chain = [f"{F}ORG_L{i}" for i in range(1, 4 + n(4))]  # rule 14: users hold the top n(4) levels
    links += [(c, p) for p, c in zip(chain, chain[1:])] + [(writes[0], chain[-1])]
    for g in groups:
        links += [(x, g) for x in pick(func["READER"] + func["VIEWER"] + func["STEWARD"] + func["G"] + func["CO"]
                                       + func["ENGINEER"] + func["USAGE"], 1, 3)]
    links.append((reads[1 % len(reads)], groups[0]))  # rule 1: a technical role on a group role
    db_roles = []
    for i in range(n(DB_ROLES)):
        d = rng.choice([x[0] for x in schemas if x[0] not in managed_dbs] or dbs)
        r = f"{d}.{['ANALYTICS', 'INGEST', 'CURATED', 'EXPORT', 'CONSUMER', 'PUBLISHER'][i % 6]}{i // 6 or ''}"
        db_roles.append(r)
        pv.append((r, "USAGE", "DATABASE", d, False))
        objs = [(o, k) for x in schemas if x[0] == d for o, k in x[2] if k in READABLE]
        pv += [(r, "SELECT", k, o, False) for o, k in objs[:30]]
        dbr += [(r, x) for x in pick(sum(func.values(), []) + groups, 1, 12)]
    # rules 20, 22, 29: a pipeline schema with a task, a stream on a sensitive table and a Streamlit app
    pipe = next((x for x in managed if "EXECUTE" in caps[(x[0], x[1])] and (x[0], x[1]) not in sset), managed[0])
    pc, pname = caps[(pipe[0], pipe[1])], f"{pipe[0]}.{pipe[1]}"
    src = next((o for o in sens if not o.startswith(pname + ".")), sens[0])
    task, stream = f"{pname}.TSK_9001", f"{pname}.STR_9001"
    pv += [(pc["OWNER"], "OWNERSHIP", "TASK", task, False), (pc.get("EXECUTE", pc["READ"]), "OPERATE", "TASK", task, False),
           (pc["OWNER"], "OWNERSHIP", "STREAM", stream, False), (pc["READ"], "SELECT", "STREAM", stream, False)]
    appsch = next((x for x in sens_schemas if caps[(x[0], x[1])]["READ"] not in
                   {c for c, p in links if p == common}), sens_schemas[-1])
    ac = caps[(appsch[0], appsch[1])]
    apps = [f"{appsch[0]}.{appsch[1]}.ST_9001"] + [f"{x[0]}.{x[1]}.ST_{9001 + i}" for i, x in enumerate(managed[1:n(APPS)], 1)]
    for i, app in enumerate(apps):
        o = ac["OWNER"] if i == 0 else caps[tuple(app.split(".")[:2])]["OWNER"]
        pv += [(o, "OWNERSHIP", "STREAMLIT", app, False), (apps_role if i == 0 else o, "USAGE", "STREAMLIT", app, False)]
    links.append((pc["READ"], apps_role))
    # ---- account level: warehouses, integrations, account privileges, PUBLIC ----
    whs = [f"WH_{TEAMS[i % len(TEAMS)]}_{['XS', 'S', 'M', 'L', 'XL'][i // len(TEAMS) % 5]}" + (f"_{i // 120 + 1}" if i >= 120 else "")
           for i in range(whs_n)]
    consumers = sum(func.values(), []) + [common]
    for i, w in enumerate(whs):
        pv.append(("SYSADMIN", "OWNERSHIP", "WAREHOUSE", w, False))
        pv += [(r, "USAGE", "WAREHOUSE", w, False) for r in pick(consumers, 2, 2)]
    pv += [(rng.choice(execs), "MONITOR", "WAREHOUSE", rng.choice(whs), False) for _ in range(7)]
    pv += [(deploy, "OPERATE", "WAREHOUSE", w, False) for w in whs[:4]]
    pv += [(func["ENGINEER"][i % len(func["ENGINEER"])], "OPERATE", "WAREHOUSE", whs[-1 - i % len(whs)], False) for i in range(2)]  # rule 21
    for i in range(n(INTEGRATIONS)):
        x = f"INT_{['S3', 'AZURE', 'API', 'NOTIFY', 'GIT', 'OAUTH', 'SAML'][i % 7]}_{i:02}"
        pv += [("ACCOUNTADMIN", "OWNERSHIP", "INTEGRATION", x, False), (rng.choice(execs), "USAGE", "INTEGRATION", x, False)]
    acc = []
    others = ["SECURITYADMIN", "SYSADMIN", "USERADMIN", "ORGADMIN"]
    for p, c in ACCOUNT.items():
        hs = ["ACCOUNTADMIN"] + (["PUBLIC"] if p in PUBLIC_PRIVS else [])
        if p == "EXECUTE TASK":  # rule 19: reaches persons
            hs += func["ENGINEER"][:2]
        if p in ("CREATE DATABASE", "CREATE WAREHOUSE", "MONITOR USAGE"):
            hs.append(legacy[len(acc) % len(legacy)])
        hs += others[:max(0, c - len(hs))]
        acc += [(r, p) for r in hs[:max(c, len(hs))]]
    adm = max(0, ADMIN_ACCOUNT - sum(r in a.ADMIN for r, _ in acc))  # the rest on names held once or twice
    cus = max(0, CUSTOM_ACCOUNT - sum(r not in a.ADMIN and r != "PUBLIC" for r, _ in acc))
    acc += [(others[i // len(EXTRA) % len(others)], EXTRA[i % len(EXTRA)]) for i in range(adm)]
    acc += [((legacy + groups)[i % (len(legacy) + len(groups))], EXTRA[-1 - i % len(EXTRA)]) for i in range(cus)]
    pv += [(r, p, "ACCOUNT", "ACCOUNT", False) for r, p in acc]
    pv += [("PUBLIC", "USAGE", "WAREHOUSE", w, False) for w in whs[:2]] + \
          [("PUBLIC", "USAGE", "DATABASE", d, False) for d in (mid or dbs)[:2]]  # rule 9
    roles = sorted({r for x in links for r in x} | {r for r, *_ in pv} | set(db_roles) | set(chain) | {common, apps_role})
    links += [(r, "SYSADMIN") for r in roles if r.startswith((F, T))]  # every custom role -> SYSADMIN
    links += [("SYSADMIN", "ACCOUNTADMIN"), ("SECURITYADMIN", "ACCOUNTADMIN"), ("USERADMIN", "SECURITYADMIN")]
    pv += [("USERADMIN" if i % 3 else "SECURITYADMIN", "OWNERSHIP", "ROLE", r, False) for i, r in enumerate(roles)]
    # ---- users ----
    svc = [f"SVC_{['ETL', 'DBT', 'BI', 'LOAD', 'SYNC', 'API', 'ML', 'EXPORT'][i % 8]}_{i // 8 + 1:02}" for i in range(n(SERVICE))]
    first = [f"N{k:04}" for k, c in enumerate(spread(rng, NAME_SHARE, n(sum(NAME_SHARE.values())))) for _ in range(c)]
    rng.shuffle(first)  # persons log in with mail-like names (first.last@domain): dots in user names
    persons = [f"{first[i % len(first)]}.{['ANALYST', 'ENGINEER', 'PERSON', 'CONSULTANT'][i % 4]}_{i // 4 + 1:04}@EXAMPLE.TEST"
               for i in range(users_n - len(svc))]
    rng.shuffle(persons)
    k = {s: min(n(c), len(persons)) for s, c in STATUS.items()}
    disabled, never = persons[:k["disabled"]], persons[k["disabled"]:k["disabled"] + k["never"]]
    dormant = persons[len(disabled) + len(never):][:k["dormant"]]
    active = persons[len(disabled) + len(never) + len(dormant):]
    days = {}
    for u, x in zip(active, spread(rng, LOGIN_ACTIVE, len(active))):
        days[u] = x
    for u, x in zip(dormant, spread(rng, LOGIN_OLD, len(dormant))):
        days[u] = x
    for u in disabled[:n(DISABLED_LOGIN)]:
        days[u] = draw(rng, LOGIN_OLD | LOGIN_ACTIVE)
    for u in svc:
        days[u] = 0
    held = {}  # user -> [roles], in grant order
    facing = [common] + groups + rng.sample(consumers[:-1], min(len(consumers) - 1, max(0, n(50) - 1 - len(groups))))  # + admin, chain, build and app roles: 61
    size = dict(zip(facing[1:], spread(rng, USERS_PER_ROLE, len(facing) - 1)))
    holders = [u for u in active + dormant + never if u not in set(active[:n(40)])]  # n(40) active ones build (DEPLOY)
    holders = holders[:max(1, n(WITH_ROLES) - n(DISABLED_ROLES) - n(40) - len(svc))]
    counts = spread(rng, ROLES_PER_USER, len(holders))
    size[common] = max(1, sum(counts) - sum(size.values()))
    names = list(size)
    slots = [r for r in names for _ in range(size[r])]  # each role dealt to its size in users
    rng.shuffle(slots)
    for u, c in zip(holders, counts):
        got = []
        while len(got) < min(c, len(names)) and slots:
            r = slots.pop()
            if r not in got:
                got.append(r)
        held[u] = got or [common]
    for u in disabled[:n(DISABLED_ROLES)]:
        held[u] = [common]
    for u in svc + active[:n(40)]:
        held.setdefault(u, []).insert(0, deploy)
    admins = [u for u in active if u not in held or held[u][0] != deploy]
    adm_users = []
    for r, c in ADMINS.items():
        for u in rng.sample(admins[:60], min(n(c), len(admins[:60]))):
            held.setdefault(u, []).append(r)
            adm_users.append((u, r))
    for i, c in enumerate(chain[:n(4)]):
        for u in rng.sample(active[n(40):], min(2, len(active[n(40):]))):
            held.setdefault(u, []).append(c)
    busy = {u for u, rs in held.items() if set(rs) & ({*a.ADMIN, *chain})}
    viewers = [u for u in reversed(active[n(40):]) if u not in busy][:n(3) + 1] or persons[-1:]
    for u in viewers:  # they open the app and hold nothing else (rule 29)
        held[u] = [apps_role]
    held.setdefault(active[n(40)], []).append(reads[0])  # rule 1: a technical role on a user
    default = {u: rs[0] for u, rs in held.items()}
    for u, r in adm_users[:n(7)]:  # rule 12
        default[u] = r
    user_rows = []
    for u in persons + svc:
        last = None if u not in days else stamp(END - timedelta(days=days[u], hours=rng.randint(0, 12)))
        user_rows.append(dict(USER_NAME=u, TYPE="SERVICE" if u in svc else "PERSON", DISABLED=u in disabled,
                              DEFAULT_ROLE=default.get(u), DEFAULT_SECONDARY_ROLES='["ALL"]' if u in held else None,
                              DEFAULT_WAREHOUSE=rng.choice(whs), DEFAULT_NAMESPACE=None, LAST_SUCCESS_LOGIN=last))
    pv += [("USERADMIN", "OWNERSHIP", "USER", u, False) for u in persons + svc]
    user_role = [dict(USER_NAME=u, ROLE_NAME=r, GRANTED_BY="SECURITYADMIN") for u, rs in held.items() for r in rs]
    # ---- tags and policies ----
    tags, policies, cols = [], [], []
    sem, pcat = "SNOWFLAKE.CORE.SEMANTIC_CATEGORY", "SNOWFLAKE.CORE.PRIVACY_CATEGORY"
    for i in range(n(SENS_COLUMNS)):  # sensitive columns: classified, never masked (rule 6)
        o = sens[i % len(sens)]
        c, s, p = PII[i // len(sens) % len(PII)]
        c += f"_{i // (len(sens) * len(PII)) + 1}" if i >= len(sens) * len(PII) else ""
        tags += [dict(OBJECT_NAME=o, DOMAIN="COLUMN", COLUMN_NAME=c, TAG_NAME=sem, TAG_VALUE=s, APPLY_METHOD="CLASSIFIED"),
                 dict(OBJECT_NAME=o, DOMAIN="COLUMN", COLUMN_NAME=c, TAG_NAME=pcat, TAG_VALUE=p, APPLY_METHOD="CLASSIFIED")]
    data = [o for x in schemas for o, k in x[2] if k in ("TABLE", "VIEW", "EXTERNAL TABLE")]
    for t, c in TAG_SHAPES.items():
        for i in range(n(c)):
            o, col = rng.choice(data), f"C_{rng.randint(1, 60):03}"
            tags.append(dict(OBJECT_NAME=o, DOMAIN="COLUMN", COLUMN_NAME=col, TAG_NAME=t,
                             TAG_VALUE=f"{t.split('.')[-1][:4]}_{rng.randint(1, 40):02}", APPLY_METHOD="MANUAL"))
            cols.append((o, col))
    for x in rng.sample(schemas, min(n(SCHEMA_TAGS), len(schemas))):
        tags.append(dict(OBJECT_NAME=f"{x[0]}.{x[1]}", DOMAIN="SCHEMA", COLUMN_NAME=None, TAG_NAME="GOV_TAG_DB.TAGS.OWNER",
                         TAG_VALUE="data owner", APPLY_METHOD="MANUAL"))
    stewards = func["STEWARD"]
    for i, (o, col) in enumerate(cols[:n(MASKED)]):
        st = stewards[i % len(stewards)]
        policies.append(dict(POLICY_NAME=f"GOV_DB.POLICIES.MP_{i % 50:03}", POLICY_KIND="MASKING_POLICY", OBJECT_NAME=o,
                             COLUMN_NAME=col, ARG_COLUMNS=None, TAG_NAME=None,
                             POLICY_BODY=f"CASE WHEN IS_ROLE_IN_SESSION('{st}') THEN VAL ELSE '***MASKED***' END"))
    for i, o in enumerate(rng.sample(data, min(n(ROW_POLICIES), len(data)))):
        st = stewards[i % len(stewards)]
        policies.append(dict(POLICY_NAME=f"GOV_DB.POLICIES.RAP_{i % 30:03}", POLICY_KIND="ROW_ACCESS_POLICY",
                             OBJECT_NAME=o, COLUMN_NAME=None, ARG_COLUMNS="REGION", TAG_NAME=None,
                             POLICY_BODY=f"IS_ROLE_IN_SESSION('{st}') OR CURRENT_ROLE() = '{deploy}'"))
    # ---- usage, object use, activity ----
    act, use = activity(rng, n, held, svc, active, dormant, [u for u in persons if u in days], deploy, links, caps, schemas, adm_users, viewers,
                        apps[0], ac["OWNER"], sens, dbs)
    usage = []
    for u in active + svc:
        rs = held.get(u)
        if rs:
            q = rng.randint(1, 900)
            usage += [dict(USER_NAME=u, KIND="ROLE", NAME=rs[0], QUERIES=q, LAST_USED=stamp(END - timedelta(days=days[u]))),
                      dict(USER_NAME=u, KIND="WAREHOUSE", NAME=rng.choice(whs), QUERIES=q,
                           LAST_USED=stamp(END - timedelta(days=days[u])))]
            if len(rs) > 1 and rng.random() < .5:
                usage.append(dict(USER_NAME=u, KIND="SECONDARY ROLE", NAME=rs[1], QUERIES=q // 3,
                                  LAST_USED=stamp(END - timedelta(days=days[u]))))
    grants = [dict(GRANTEE_ROLE=p, PRIVILEGE="USAGE", GRANTED_ON="ROLE", OBJECT_NAME=c, IS_FUTURE=False,
                   GRANTED_BY="SECURITYADMIN") for c, p in dict.fromkeys(links)]
    grants += [dict(GRANTEE_ROLE=p, PRIVILEGE="USAGE", GRANTED_ON="DATABASE_ROLE", OBJECT_NAME=c, IS_FUTURE=False,
                    GRANTED_BY="SECURITYADMIN") for c, p in dict.fromkeys(dbr)]
    grants += [dict(GRANTEE_ROLE=r, PRIVILEGE=p, GRANTED_ON=k, OBJECT_NAME=o, IS_FUTURE=fu,
                    GRANTED_BY="SECURITYADMIN") for r, p, k, o, fu in dict.fromkeys(pv)]
    run = dict(RUN_ID="twin", FINISHED_AT=stamp(END), SOURCES={}, NOTES={})
    return dict(run=run, GRANT=grants, USER_ROLE=user_role, USER=user_rows, USAGE=usage, TAG=tags, POLICY=policies,
                STREAM=[dict(STREAM_NAME=stream, SOURCE_NAME=src, SOURCE_TYPE="Table")], OBJECT_USE=use, ACTIVITY=act)


def fill(rows, total):
    """Rows per user from a histogram, the open top bucket topped up (or cut) to total."""
    top = [i for i, x in enumerate(rows) if x >= 1000] or [0]
    f = max(0, total - sum(rows) + sum(rows[i] for i in top)) / max(1, sum(rows[i] for i in top))
    for i in top:
        rows[i] = max(1, round(rows[i] * f))
    return rows


def activity(rng, n, held, svc, active, dormant, logged, deploy, links, caps, schemas, adm_users, viewers, app, app_owner,
             sens, dbs):
    """(ACTIVITY rows, OBJECT_USE rows): builders (service users, DEPLOY holders) load and change their schemas, the
    others read what their roles reach; plus person changes (rule 24), spikes (28), admin roles (26), a service user
    in Snowsight (25) and the app's viewers (29)."""
    objs = {(d, sc): [o for o, k in x if k in READABLE] for d, sc, x in schemas}  # ACCESS_HISTORY names tables and views
    every = [o for v in objs.values() for o in v]
    built = [o for k in caps for o in objs[k]]
    kids = {}
    for c, p in links:
        kids.setdefault(p, []).append(c)
    where = {r: k for k, c in caps.items() for r in c.values()}

    def pool(u):
        seen, todo = {}, list(held.get(u, []))  # a dict: the same order every run
        for _ in range(3):  # three hops down is enough for a pool of objects
            todo = [c for r in todo if r not in seen and not seen.setdefault(r, 0) for c in kids.get(r, [])]
        got = [o for r in seen if r in where for o in objs[where[r]]]
        return got or every

    builders = [u for u in svc + active if deploy in held.get(u, [])]

    def cycle(xs):  # every object once before any twice: builders touch most of the account
        xs = xs[:]
        rng.shuffle(xs)
        while True:
            yield from xs

    ev, bt, ev2, bt2 = cycle(every), cycle(built), cycle(every), cycle(built)
    ops = {f"{d}.{sc}": c["OWNER"] for (d, sc), c in rng.sample(sorted(caps.items()), min(len(caps), n(50)))}
    readers = [u for u in active if u not in set(builders)]
    users = (builders + readers + dormant)[:n(ACT_USERS)]
    rows = fill(sorted(spread(rng, ROWS_PER_USER, len(users)), reverse=True), n(ACT_ROWS) - n(INFO_ROWS) - n(APP_ROWS))
    qmix = [(q, rd) for q, (c, rd) in QTYPES.items()]
    qw = [c for c, _ in QTYPES.values()]
    clients, cw = list(CLIENTS), list(CLIENTS.values())
    e, out, long, change = END.date(), [], [], []

    def add(u, r, cl, o, act, qt, day_list, base, app_name=None):
        got = []
        for i in day_list:
            d, h = e - timedelta(days=i), rng.randint(0, 23) if u in svc else rng.randint(7, 19)
            lo, hi = next((b for b in QUERIES_PER_ROW if b[0] <= base <= b[1]), (base, base))
            q = min(hi, max(lo, round(base * rng.uniform(.7, 1.3))))  # same bucket every day
            got.append(dict(DAY=d.isoformat(), USER_NAME=u, ROLE_NAME=r, CLIENT=cl, OBJECT_NAME=o, ACTION=act,
                            QUERY_TYPE=qt, QUERIES=q, LAST_USED=f"{d.isoformat()} {h:02}:15", HOURS={str(h): q},
                            APP=app_name))
        out.extend(got)
        return got

    for u, want in zip(users, rows):
        build = u in builders
        p = None if build else pool(u)
        p = p and (ev if p is every else cycle(p))  # no copy of every object per user
        rs = [r for r in held.get(u, []) if r not in a.ADMIN] or [deploy if build else a.FUNC + "COMMON_USAGE"]
        while want > 0:
            d = min(want, rng.choice(PAIR_DAYS))
            want -= d
            qt, rd = rng.choices(qmix, qw)[0] if build else (("DESCRIBE", 0) if rng.random() < .1 else ("SELECT", 1))
            act = "READ" if rng.random() < rd else "DDL" if qt in DDL else "WRITE"
            cl = rng.choice(["PythonConnector", "JDBC", "Spark"]) if u in svc else rng.choices(clients, cw)[0]
            if u in svc and cl in a.INTERACTIVE:
                cl = "PythonConnector"
            recent = d == 1 and rng.random() < .02  # new tables: a first use in the last week (rule 27)
            o = (next(ev) if act == "READ" else next(bt)) if build else next(p)  # builders change only what DEPLOY owns
            r = ops.get(o.rsplit(".", 1)[0], rs[0]) if build else rng.choice(rs)  # some build as the schema owner
            got = add(u, r, cl, o, act, qt,
                      [rng.randrange(7)] if recent else rng.sample(range(61), d),
                      draw(rng, QUERIES_PER_ROW))
            if d >= 5:
                long.append(got)
            elif not build and qt == "SELECT":
                change.append(got)
    for got in rng.sample(change, min(n(PERSON_CHANGES), len(change))):  # rule 24: a person changes a table
        for x in got:
            x.update(ACTION="WRITE", QUERY_TYPE="INSERT")
    for got in rng.sample(long, min(n(SPIKES), len(long))):  # rule 28: one day far above the usual
        x = got[0]
        x["QUERIES"] = max(60, 6 * max(y["QUERIES"] for y in got))
        x["HOURS"] = {next(iter(x["HOURS"])): x["QUERIES"]}
    for u, r in adm_users:  # rule 26: admin role used on data
        add(u, r, "Snowflake UI", rng.choice(every), "READ", "SELECT", rng.sample(range(61), 2), 3)
    add(svc[0], deploy, "Snowflake UI", rng.choice(built), "READ", "SELECT", [1, 2], 4)  # rule 25
    views = ["TABLES", "COLUMNS", "VIEWS", "SCHEMATA", "TABLE_PRIVILEGES"]
    tools = [u for u, x in zip(users, rows) if x >= 1000 and u not in svc] or users  # metadata reads come from tools
    for i in range(n(INFO_ROWS)):
        u = rng.choice(tools)
        add(u, (held.get(u) or [a.FUNC + "COMMON_USAGE"])[0], "JDBC", f"{rng.choice(dbs)}.INFORMATION_SCHEMA.{rng.choice(views)}",
            "READ", "SELECT", [rng.randrange(61)], 1)
    seen = [o for o in sens if o.startswith(app.rsplit(".", 1)[0] + ".")] or sens
    for i in range(n(APP_ROWS)):  # the app's queries run as its owner role (rule 29's viewers)
        add(viewers[i % len(viewers)], app_owner, "Snowflake UI", seen[i % len(seen)], "READ", "SELECT",
            [i % 61], 2, app)
    # object use: per user, object, week and READ / WRITE
    use, w0 = [], a.monday(END)
    users2 = list(dict.fromkeys(users + dormant + logged + list(held)))[:n(USE_USERS)]
    per = fill(sorted(spread(rng, ROWS_PER_USER, len(users2)), reverse=True), n(USE_ROWS))
    for u, want in zip(users2, per):
        build = u in builders
        p = None if build else pool(u)
        p = p and (ev2 if p is every else cycle(p))
        while want > 0:
            k = min(want, rng.choice([1] * 10 + [2, 3, 5, 10, 27]))
            want -= k
            act = "WRITE" if build and rng.random() < USE_WRITE * 1.1 else "READ"
            o = (next(bt2) if act == "WRITE" else next(ev2)) if build else next(p)
            for i in rng.sample(range(USE_WEEKS), k):
                wk = w0 - timedelta(weeks=i)
                use.append(dict(USER_NAME=u, OBJECT_NAME=o, WEEK=wk.isoformat(), ACTION=act, QUERIES=draw(rng, QUERIES_PER_ROW),
                                LAST_USED=f"{(wk + timedelta(days=min(4, (END.date() - wk).days))).isoformat()} 10:00"))
    return out, use


def previous(scale=1.0, seed=7):
    """The twin a week earlier (What changed): some grants not there yet, some role links removed since."""
    d, rng = twin(scale, seed), random.Random(seed + 1)
    g, fs = d["GRANT"], sorted({x["GRANTEE_ROLE"] for x in d["GRANT"] if x["GRANTEE_ROLE"].startswith(a.FUNC)})
    plain = [i for i, x in enumerate(g) if x["PRIVILEGE"] in ("SELECT", "INSERT", "UPDATE", "USAGE") and x["GRANTED_ON"] != "ROLE"]
    new = set(rng.sample(plain, min(len(plain), max(1, len(g) // 500))))  # object grants added this week
    gone = [dict(x, GRANTEE_ROLE=rng.choice(fs)) for x in g[:2000] if x["GRANTED_ON"] == "ROLE"][:max(1, len(g) // 2000)]
    run = dict(d["run"], RUN_ID="twin-previous", FINISHED_AT=stamp(END - timedelta(days=7)))
    return d | dict(GRANT=[x for i, x in enumerate(g) if i not in new] + gone, run=run)


def scale():
    return float(os.environ.get("FAKE_SCALE") or 1)


def data():
    """What FAKE= loads: the twin for FAKE=twin, else access.fake()."""
    return twin(scale()) if os.environ.get("FAKE") == "twin" else a.fake()


def data_previous():
    return previous(scale()) if os.environ.get("FAKE") == "twin" else a.fake_previous()
