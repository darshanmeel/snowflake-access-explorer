"""Walker tests on the fake data. Run: python test_access.py (no pytest needed)."""
import json
import os
import random
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter

os.environ["FAKE"] = "1"  # never Snowflake here, whatever .env says

import access as a
import cache
import ui

F, T = a.FUNC, a.TECH


def tiny(links, user_roles=(), pv=()):
    """A hand-made data set: links (granted role, grantee role), user_roles (role, user), pv (role, priv, type, obj)."""
    g = [dict(GRANTEE_ROLE=p, PRIVILEGE="USAGE", GRANTED_ON="ROLE", OBJECT_NAME=c, IS_FUTURE=False) for c, p in links]
    g += [dict(GRANTEE_ROLE=r, PRIVILEGE=p, GRANTED_ON=k, OBJECT_NAME=o, IS_FUTURE=False) for r, p, k, o in pv]
    return dict(run={}, GRANT=g, USER_ROLE=[dict(USER_NAME=u, ROLE_NAME=r) for r, u in user_roles],
                USER=[dict(USER_NAME=u) for _, u in user_roles], USAGE=[])


def test_user():
    g = a.grants("ANALYST_01", True)
    assert len(g) == 12 and sum(r["count"] for r in g) == 14  # + INSERT on TBL_LOGGING (rule 17), PUBLIC warehouse + lineage
    assert max(r["depth"] for r in g) == 3
    assert all(r["path"] == r["paths"][0] and len(r["path"]) == r["depth"] + 2 for r in g)
    reach = a.reach("ANALYST_01", True)
    assert {r["role"] for r in reach} == {"GRP_ANALYSTS", "PUBLIC", F + "ANALYST", T + "SALES_MART_READ",
                                          T + "SALES_CORE_READ", T + "SHARED_LOGGING_READ"}
    assert sum(r["depth"] == 1 for r in reach) == 2 == sum(r["direct"] for r in reach)  # GRP_ANALYSTS + PUBLIC
    assert a.admin_paths("ANALYST_01", True) == []
    assert max(r["depth"] for r in a.grants("FIN_01", True)) == 10
    assert a.profile["FIN_14"]["DISABLED"] and not a.profile["FIN_01"]["DISABLED"]
    assert a.admin_paths("ADMIN_01", True) and a.account_privs("ADMIN_01", True)


def test_depth_limit():
    one = a.grants("ANALYST_01", True, limit=1)  # depth 1: the granted roles themselves (PUBLIC's warehouse)
    assert [(r["privilege"], r["object"], r["holder"]) for r in one] == [("VIEW LINEAGE", "ACCOUNT", "PUBLIC"),
                                                                        ("USAGE", "WH_SALES_XS", "PUBLIC")]
    two = a.grants("ANALYST_01", True, limit=2)
    assert {r["depth"] for r in two} == {1, 2} and {r["holder"] for r in two} == {"PUBLIC", T + "SHARED_LOGGING_READ"}
    assert a.grants("GRP_ANALYSTS", limit=1) == []  # a role is depth 1 itself; GRP_ANALYSTS holds roles only
    assert {r["depth"] for r in a.grants("GRP_ANALYSTS", limit=2)} == {2}
    assert {r["role"] for r in a.reach("ANALYST_01", True, limit=1)} == {"GRP_ANALYSTS", "PUBLIC"}
    assert len(a.grants("ANALYST_01", True, limit=3)) == len(a.grants("ANALYST_01", True))
    assert {r["depth"] for r in a.grants("FIN_01", True, limit=8)} == {1}  # only PUBLIC's warehouse
    assert {r["depth"] for r in a.grants("FIN_01", True, limit=9)} == {1, 9}
    assert a.held(T + "SALES_CORE_READ", limit=1) == []  # no user holds it directly
    assert {r["depth"] for r in a.held(T + "SALES_CORE_READ", limit=2)} == {2}
    assert all(r["depth"] <= 2 for r in a.grantees("FINANCE.REPORT.TBL_REVENUE", limit=2))
    assert {r["grantee"] for r in a.grantees("FINANCE.REPORT.TBL_REVENUE", limit=2)} >= {"REPORT_01", "MARKETING_01"}
    assert not a.capped


def test_can():
    c = a.can("ENGINEER_01", "SELECT", "SALES.CORE.TBL_CUSTOMER")
    assert len(c["paths"]) == 3 and c["shortest"] == 2
    assert all(T + "SALES_CORE_READ" in p["path"] for p in c["paths"])
    assert c["choke"] == [T + "SALES_CORE_READ"] and c["closest"] is None and c["use_role"] == F + "ENGINEER"
    assert [(o["sql"], o["affects"]) for o in c["options"]] == [  # no single grant to the user: both granted roles
        (f"REVOKE ROLE {F}ENGINEER FROM USER ENGINEER_01; REVOKE ROLE {F}ANALYST FROM USER ENGINEER_01;", 1),
        (f"REVOKE SELECT ON TABLE SALES.CORE.TBL_CUSTOMER FROM ROLE {T}SALES_CORE_READ;", 5)]
    ro = a.can("ANALYST_01", "SELECT", "SALES.CORE.TBL_CUSTOMER")["options"]  # affects = users who really lose it
    assert next(o for o in ro if o["sql"] == f"REVOKE ROLE {T}SALES_CORE_READ FROM ROLE {F}ANALYST;")["affects"] == 2
    own = a.can("ENGINEER_01", "OWNERSHIP", "SALES.MART.VW_CUSTOMER")["options"][-1]  # OWNERSHIP is transferred
    assert own["sql"] == "GRANT OWNERSHIP ON VIEW SALES.MART.VW_CUSTOMER TO ROLE <new owner role> COPY CURRENT GRANTS;"
    assert a.revoke(a.role_edge("X; DROP DATABASE P", "R", True))[1] == 'REVOKE ROLE R FROM USER "X; DROP DATABASE P";'
    assert [x["role"] for x in a.ask_for("SELECT", "SALES.CLEAN.TBL_ORDER")] == [F + "MARKETING"]  # never the build role
    assert a.ask_for("INSERT", "FINANCE.REPORT.TBL_REVENUE")[0]["role"] == F + "FINANCE_EDITOR"  # closest on a tie
    hows = [p["how"] for p in c["paths"]]
    assert any("secondary" in h for h in hows) and any("technical role" in h for h in hows)
    assert len(a.can("ENGINEER_01", "SELECT", "SALES.CORE.TBL_CUSTOMER", default_only=True)["paths"]) == 2
    no = a.can("ANALYST_01", "INSERT", "SALES.CORE.TBL_CUSTOMER")
    assert no["paths"] == [] and no["shortest"] is None
    assert a.from_user(no["closest"]) and no["closest"][-1] == "SALES.CORE.TBL_CUSTOMER"
    assert [x["role"] for x in no["ask"]] == [F + "ENGINEER"] and no["use_role"] is None
    fin = a.can("FIN_14", "SELECT", "FINANCE.REPORT.TBL_REVENUE")
    assert fin["status"] == "disabled" and fin["warehouse"] == "WH_SALES_XS"  # default WH_FINANCE_XS is not granted
    opts = fin["options"]  # fewest affected users first: the grant closest to the user, the object side last
    assert opts[0]["sql"] == "REVOKE ROLE GRP_EMEA_ALL FROM USER FIN_14;" and opts[0]["affects"] == 1
    assert opts[0]["iac"] == "Remove in the infrastructure-as-code repo: role GRP_EMEA_ALL granted to user FIN_14"
    assert opts[-1]["sql"].startswith("REVOKE SELECT ON TABLE FINANCE.REPORT.TBL_REVENUE FROM ROLE")
    assert opts[-1]["affects"] == 16 and [o["affects"] for o in opts] == sorted(o["affects"] for o in opts)
    own = a.can("SVC_DEPLOY", "SELECT", "FINANCE.REPORT.TBL_REVENUE")
    assert own["paths"] == [] and own["owner"] and own["use_role"] == F + "DEPLOY"  # "Yes, via ownership"


def test_role():
    r = T + "SALES_CORE_READ"
    h = a.held(r)
    assert len(h) == 11 and sum(x["kind"] == "user" for x in h) == 5  # + REPORT_01, MARKETING_01 and their roles
    s = a.role_stats(r)
    assert s["farthest"] == 3 and s["users"] == 5 and s["above"] == 6 and s["future"] == 1 and s["sensitive"] == 1
    assert s["privileges"] == len(a.holds_of(r)) and s["above_direct"] == 5
    f = {x["grantee"]: x for x in a.held(T + "FINANCE_REPORT_READ")}
    assert f["FIN_01"]["depth"] == 10 and f["GRP_EMEA_ALL"]["depth"] == 10 and f[T + "FINANCE_REPORT_WRITE"]["depth"] == 2
    assert f["FIN_01"]["only_via"][:2] == ["GRP_EMEA_ALL", F + "EMEA"]
    g = a.grants("GRP_EMEA_ALL")  # role with no direct grants: effective privileges come from the roles it holds
    assert a.holds_of("GRP_EMEA_ALL") == [] and g and not any(x["direct"] for x in g)
    assert a.role_stats("GRP_EMEA_ALL")["holds_roles"] == [F + "EMEA"]
    assert all(x["direct"] and x["depth"] == 1 for x in a.grants(r))


def test_object():
    o = "FINANCE.REPORT.TBL_REVENUE"
    s = a.object_stats(o)
    assert s["users"] == 17 and s["admin_users"] == 2  # + REPORT_01, MARKETING_01; + OPS_01 (SYSADMIN)
    assert len(s["people"]) == 15 and s["disabled"] == ["FIN_14"] and s["service"] == ["SVC_DEPLOY"]
    assert s["admin"] == ["ADMIN_01", "OPS_01"]
    assert s["owners"] == [T + "FINANCE_REPORT_OWNER"] and s["deployers"] == ["SVC_DEPLOY"] and s["owner_note"] == ""
    ins = a.object_stats(o, "TABLE", "INSERT")  # owner stays, whatever the filter; OWNERSHIP implies INSERT
    assert ins["users"] == 15 and ins["deployers"] == ["SVC_DEPLOY"] and ins["longest"] == 9
    assert a.object_stats("FINANCE", "DATABASE", "USAGE")["owner_note"] == "no OWNERSHIP grant in snapshot"
    m = a.matrix(o)
    assert {x["user"] for x in m if not x["admin"]} == set(a.FIN_USERS) | {"SVC_DEPLOY", "REPORT_01", "MARKETING_01"}
    assert [x["user"] for x in m if x["admin"]] == ["ADMIN_01", "OPS_01"]
    assert m[0]["privs"]["SELECT"]["has"] and list(m[0]["privs"]) == [c for c in a.valid_privs("TABLE") if c != "REFERENCES"]
    mi = a.matrix(o, priv="INSERT")  # the privilege filter keeps holders, implied owners and admins
    assert {x["user"] for x in mi if not x["admin"]} == set(a.FIN_USERS) | {"SVC_DEPLOY"}
    svc = next(x for x in mi if x["user"] == "SVC_DEPLOY")["privs"]
    assert svc["INSERT"]["owner"] and not svc["INSERT"]["has"] and svc["INSERT"]["title"] == "implied by OWNERSHIP"
    e = next(x for x in a.matrix("SALES.CORE.TBL_CUSTOMER") if x["user"] == "ENGINEER_01")
    assert e["privs"]["INSERT"]["title"] == f"INSERT via {F}ENGINEER > {T}SALES_CORE_WRITE"
    assert e["via"]["write"] == [F + "ENGINEER"] and e["via"]["read"] == [F + "ANALYST", F + "ENGINEER"]
    users = {x["grantee"] for x in a.grantees(o) if x["kind"] == "user"}
    assert len(users) == 17  # more than 12 in one lane: the graph collapses it to "+N more"
    assert a.valid_privs("PROCEDURE") == ["OWNERSHIP", "USAGE"] and a.valid_privs("DATABASE")[0] == "OWNERSHIP"


def test_depth():
    """One depth everywhere: roles from the start to the grant holder, holder included (a user is not a role)."""
    g = {(r["privilege"], r["object"]): r for r in a.grants("ANALYST_01", True)}
    ge = {(r["grantee"], r["privilege"]): r["depth"] for r in a.grantees("SALES.CORE.TBL_CUSTOMER")}
    assert g[("SELECT", "SALES.CORE.TBL_CUSTOMER")]["depth"] == 3 == ge[("ANALYST_01", "SELECT")]
    assert ge[(T + "SALES_CORE_READ", "SELECT")] == 1 and ge[(F + "ANALYST", "SELECT")] == 2
    o = "FINANCE.REPORT.TBL_REVENUE"
    f = {(r["privilege"], r["object"]): r["depth"] for r in a.grants("FIN_01", True)}
    m = next(x for x in a.matrix(o) if x["user"] == "FIN_01")["privs"]
    fe = {(r["grantee"], r["privilege"]): r["depth"] for r in a.grantees(o)}
    assert f[("SELECT", o)] == m["SELECT"]["depth"] == fe[("FIN_01", "SELECT")] == 10
    assert f[("INSERT", o)] == m["INSERT"]["depth"] == fe[("FIN_01", "INSERT")] == 9
    assert a.object_stats(o)["longest"] == 10 == a.can("FIN_01", "SELECT", o)["shortest"]
    assert [(r["role"], r["depth"]) for r in a.reach("GRP_ANALYSTS") if r["direct"]] == \
        [(F + "ANALYST", 2), (T + "SHARED_LOGGING_READ", 2)]
    lanes = {n: min(d) for n, d in a.chains(a.walk("ANALYST_01", True)).items()}
    assert lanes["GRP_ANALYSTS"] == 1 and lanes[T + "SALES_CORE_READ"] == 3
    assert min(a.chains([p[::-1] for p in a.up([T + "SALES_CORE_READ"])], True)["ANALYST_01"]) == 3


def test_classes():
    c = a.priv_class
    assert [c("SELECT", "TABLE"), c("REFERENCES", "VIEW"), c("USAGE", "DATABASE"), c("USAGE", "SCHEMA")] == ["read"] * 4
    assert [c(p, "TABLE") for p in ("INSERT", "UPDATE", "DELETE", "TRUNCATE")] == ["write"] * 4
    assert c("OWNERSHIP", "TABLE") == "own" and c("CREATE SCHEMA", "DATABASE") == "manage"
    assert [c("USAGE", k) for k in ("PROCEDURE", "FUNCTION", "WAREHOUSE")] == ["use"] * 3
    assert c("MONITOR", "WAREHOUSE") == c("MONITOR", "TASK") == "use" and c("SELECT", "FUTURE TABLE") == "read"
    assert [c("OPERATE", "WAREHOUSE"), c("MODIFY", "WAREHOUSE"), c("OPERATE", "TASK"), c("CREATE TABLE", "SCHEMA"),
            c("APPLY MASKING POLICY", "TAG")] == ["manage"] * 5
    assert c("EXECUTE TASK", "ACCOUNT") == "admin" and c("SELECT", "STREAM") == "read"
    t = a.priv_cat
    assert [t("USAGE", "DATABASE"), t("USAGE", "SCHEMA"), t("USAGE", "WAREHOUSE"), t("MONITOR", "TASK")] == ["usage"] * 4
    assert [t("SELECT", "FUTURE TABLE"), t("READ", "STAGE"), t("INSERT", "TABLE"), t("WRITE", "STAGE")] == [
        "read", "read", "write", "write"]
    assert [t("USAGE", "PROCEDURE"), t("EXECUTE TASK", "ACCOUNT"), t("OPERATE", "TASK")] == ["execute"] * 3
    assert [t("OPERATE", "WAREHOUSE"), t("CREATE TABLE", "SCHEMA"), t("MANAGE GRANTS", "ACCOUNT")] == ["manage"] * 3
    assert t("OWNERSHIP", "TABLE") == "own" and t("USAGE", "DATABASE_ROLE") == "hold"
    assert {t(r["privilege"], r["type"]) for r in a.grants("ENGINEER_01", True)} <= set(a.CATS)
    assert {a.kinds[f"SALES.PIPELINE.{o}"] for o in a.SCHEMAS["SALES"]["PIPELINE"]} == {
        "TASK", "STREAM", "STAGE", "FUNCTION", "SEQUENCE", "PIPE", "DYNAMIC TABLE", "TABLE"}
    s = a.split_name
    assert s("SALES.CORE.TBL_CUSTOMER") == ("SALES", "CORE", "TBL_CUSTOMER") and s("FINANCE") == ("FINANCE", "", "FINANCE")
    assert s("WH_SALES_XS") == ("", "", "WH_SALES_XS") and s("SALES.CORE.<TABLE>", "FUTURE TABLE") == ("SALES", "CORE", "<TABLE>")
    assert s("ACCOUNT") == ("", "", "ACCOUNT") and s("SALES.CORE") == ("SALES", "CORE", "CORE")
    assert s("A.B_C", "ROLE") == ("", "", "A.B_C")  # role names are never split
    r = next(x for x in a.grants("ENGINEER_01", True) if x["privilege"] == "INSERT" and x["object"].endswith("CUSTOMER"))
    assert r["cls"] == "write" and r["database"] == "SALES" and r["schema"] == "CORE" and r["granted"] == F + "ENGINEER"


def test_sensitive():
    s = a.sensitive()
    assert sorted(s) == ["FINANCE.REPORT.TBL_REVENUE", "FINANCE.REPORT.VW_REVENUE_MONTHLY", "SALES.CORE.TBL_CUSTOMER",
                         "SALES.MART.VW_CUSTOMER", "SHARED.LOGGING.TBL_LOGGING"]
    assert sum(len(a.sensitive_cols(o)) for o in s) == 5
    assert sorted(o for o in s if not a.sensitive_cols(o)) == ["FINANCE.REPORT.TBL_REVENUE",
                                                               "FINANCE.REPORT.VW_REVENUE_MONTHLY"]
    assert "SALES.RAW.TBL_ORDER_RAW" not in s and "SALES.CLEAN.TBL_ORDER" not in s
    assert s["FINANCE.REPORT.TBL_REVENUE"][0][3] == "inherited from database FINANCE"
    assert {t[3] for t in s["SALES.CORE.TBL_CUSTOMER"]} == {"on column"}
    assert a.tag_rules()["SENSITIVITY"] == {"PII", "CONFIDENTIAL"}
    e = {(r["role"], r["object"]): r for r in a.sensitive_reach("ENGINEER_01")}
    assert e[(F + "ENGINEER", "SHARED.LOGGING.TBL_LOGGING")]["path"]
    assert e[(F + "ANALYST", "SHARED.LOGGING.TBL_LOGGING")]["path"] is None
    assert e[(F + "ENGINEER", "SALES.CORE.TBL_CUSTOMER")]["masked"]["EMAIL"] == "clear"
    assert e[(F + "ANALYST", "SALES.CORE.TBL_CUSTOMER")]["masked"]["EMAIL"] == "masked"
    a2 = {}
    for r in a.sensitive_reach("ANALYST_02"):
        if r["path"]:
            a2.setdefault(r["role"], set()).add(r["object"])
    assert a2 == {T + "SALES_MART_READ": {"SALES.MART.VW_CUSTOMER"},
                  "GRP_ANALYSTS": {"SALES.MART.VW_CUSTOMER", "SALES.CORE.TBL_CUSTOMER", "SHARED.LOGGING.TBL_LOGGING"}}
    assert a.masked("ENGINEER_01", "SALES.CORE.TBL_CUSTOMER", "EMAIL") == "clear"
    assert a.masked("ANALYST_01", "SALES.CORE.TBL_CUSTOMER", "EMAIL") == "masked"
    assert a.masked("ANALYST_01", "SALES.CORE.TBL_CUSTOMER", "PHONE") == "clear"  # no policy
    a.policies.insert(0, dict(POLICY_NAME="X.Y.MP_TAG", POLICY_KIND="MASKING_POLICY", OBJECT_NAME=None, COLUMN_NAME=None,
                              ARG_COLUMNS=None, TAG_NAME="SNOWFLAKE.CORE.SEMANTIC_CATEGORY",
                              POLICY_BODY=f"IS_ROLE_IN_SESSION('{F}ANALYST')"))
    assert a.masked("ANALYST_01", "SALES.CORE.TBL_CUSTOMER", "EMAIL") == "masked"  # the direct policy wins over a tag one
    del a.policies[0]
    assert a.masked(F + "DEPLOY", "FINANCE.REPORT.TBL_REVENUE") == "clear"  # CURRENT_ROLE() = F_DEPLOY
    assert a.masked("REPORT_01", "FINANCE.REPORT.TBL_REVENUE") == "masked"  # row policy filters
    assert a.clear_for("CASE WHEN IS_ROLE_IN_SESSION('X') OR CURRENT_ROLE() IN ('Y', 'Z') THEN VAL END") == \
        ({"X": "session", "Y": "primary", "Z": "primary"}, True)
    assert a.clear_for("SELECT 1") is None and a.clear_for("DB.S.MY_UDF(VAL)") is None
    assert a.clear_for("ARRAY_CONTAINS(CURRENT_ROLE()::VARIANT, ARRAY_CONSTRUCT('A'))") is None
    assert a.clear_for("IS_DATABASE_ROLE_IN_SESSION('R')") is None
    assert a.clear_for("CURRENT_USER() = 'U' OR IS_ROLE_IN_SESSION('X')")[1] is False
    pl = {p["name"].split(".")[-1]: p for p in a.policy_list()}
    assert pl["MP_IP"]["clear"] is None and pl["MP_IP"]["note"].endswith("no tagged columns")
    assert a.policies_of("FINANCE.REPORT.TBL_REVENUE")["rows"][0]["args"] == "REGION"
    top = a.sensitive_rank()[:2]
    assert {x["object"] for x in top} == {"FINANCE.REPORT.TBL_REVENUE", "FINANCE.REPORT.VW_REVENUE_MONTHLY"}
    assert all(len(x["users"]) == 17 and x["admin"] == ["ADMIN_01", "OPS_01"] for x in top)
    c = next(x for x in a.sensitive_rank() if x["object"] == "SALES.CORE.TBL_CUSTOMER")
    assert c["masked"] == (1, 3) and c["database"] == "SALES" and c["schema"] == "CORE"


def test_users():
    assert {u for u in a.users if a.is_dormant(u)} == {"ANALYST_02", "FIN_12", "FIN_13", "FIN_14"}
    assert [a.status(u) for u in ("ANALYST_01", "ANALYST_02", "FIN_12", "FIN_14")] == ["active", "dormant", "never", "disabled"]
    assert a.login_days("FIN_12") is None and a.login_days("ENGINEER_01") == 0
    a.profile["FIN_12"]["LOGIN_UNKNOWN"] = True  # My access: no last login readable for yourself, not "never"
    assert a.status("FIN_12") == "active" and not a.is_dormant("FIN_12")
    a.profile["FIN_12"]["LOGIN_UNKNOWN"] = False
    ap = {x["user"]: x for x in a.admin_people()}  # ENGINEER_01: EXECUTE TASK, an account-level privilege
    assert list(ap) == ["ADMIN_01", "ENGINEER_01", "OPS_01"] and ap["ENGINEER_01"]["roles"] == []
    assert [pv for pv, _ in ap["ENGINEER_01"]["account"]] == ["EXECUTE TASK"]
    assert a.used_roles("ENGINEER_01")[F + "ANALYST"]["kind"] == "SECONDARY ROLE"
    assert a.search("REVENUE", a.objects + a.roles) == ["FINANCE.REPORT.VW_REVENUE_MONTHLY", "FINANCE.REPORT.TBL_REVENUE"]
    assert a.search("ANALYST_0", a.users)[:2] == ["ANALYST_01", "ANALYST_02"] and a.search("ANALYTS", a.users + a.roles)
    rv = a.review("FINANCE")
    assert {r["database"] for r in rv} == {"FINANCE"} and all(r["reviewer"] == "" for r in rv)
    assert any(r["user"] == "FIN_14" and r["status"] == "disabled" and r["object"] == "TBL_REVENUE" for r in rv)
    assert any(r["user"] == "OPS_01" and r["privileges"] == "ALL" for r in rv)


def test_rules():
    rows = a.rule_rows()
    n = {}
    for x in rows:
        n[x["num"]] = n.get(x["num"], 0) + 1
    # old 9 findings for rules 1-5, + F_MARKETING READ inside WRITE (3) and OPS_01 holding SYSADMIN (5)
    assert n == {"1": 2, "2": 2, "3": 3, "4": 1, "5": 3, "6": 3, "7": 4, "8": 1, "9": 1, "10": 17, "11": 2, "12": 1,
                 "13": 1, "14": 1, "15": 1, "16": 3, "17": 4, "18": 3, "19": 2, "20": 1, "21": 1, "22": 1, "23": 4}
    assert set(a.SEVERITY) == set(a.RULES) == {str(i) for i in range(1, 24)}
    assert all(x["severity"] == a.SEVERITY[x["num"]] for x in rows)
    assert a.BUILD == [F + "DEPLOY"] or "BUILD_ROLES" in os.environ
    by = lambda num: [x for x in rows if x["num"] == num]
    assert {x["detail"].split(":")[0] for x in by("6")} == {"column PHONE", "column BIRTH_DATE", "column CLIENT_IP"}
    assert {x["grantee"] for x in by("7")} == {"ANALYST_02", "FIN_12", "FIN_13", "FIN_14"}
    assert [x["grantee"] for x in by("8")] == ["FIN_14"] and by("8")[0]["same_fix"] == "Rule 7"
    assert by("9")[0]["sql"] == "REVOKE USAGE ON WAREHOUSE WH_SALES_XS FROM ROLE PUBLIC;"
    assert by("9")[0]["affects"] == len(a.users) - 3  # ANALYST_01, ANALYST_02, ENGINEER_01 keep it via F_ANALYST
    assert by("12")[0]["affects"] == 1 and by("13")[0]["affects"] is None and by("13")[0]["impact"] == "—"
    assert by("13")[0]["detail"] == f"holds 1 role: {T}SALES_MART_READ; 0 privileges of its own"
    assert [x["grantee"] for x in by("12")] == ["OPS_01"] and [x["grantee"] for x in by("13")] == [F + "LEGACY_REPORTING"]
    assert by("14")[0]["grantee"] == "GRP_EMEA_ALL" and by("14")[0]["detail"].startswith("10 roles deep")
    assert by("15")[0]["sql"] == f"REVOKE SELECT ON FUTURE TABLES IN SCHEMA SALES.CORE FROM ROLE {T}SALES_CORE_READ;"
    assert {x["grantee"] for x in by("16")} == {"ANALYST_02", "FIN_12", "FIN_13"}  # disabled FIN_14: rule 8
    assert {x["grantee"] for x in by("11")} == {"GRP_ANALYSTS", "GRP_EMEA_ALL"}
    w = {x["grantee"]: x for x in by("10")}
    assert w["ANALYST_01"]["sql"] == f"REVOKE INSERT ON TABLE SHARED.LOGGING.TBL_LOGGING FROM ROLE {T}SHARED_LOGGING_READ;"
    assert "SVC_DEPLOY" not in w and "OWNERSHIP on SALES.MART.VW_CUSTOMER" in w["ENGINEER_01"]["detail"]
    assert by("3")[0]["same_fix"] == "Rule 1" and len(by("3")[0]["paths"]) == 2
    assert all(x["why"] and x["iac"] for x in rows)
    acct = [x for x in rows if x["num"] == "2" and x["path"][-1] == "ACCOUNT"]
    assert acct and acct[0]["detail"] == "MANAGE GRANTS on ACCOUNT"
    assert acct[0]["sql"] == f"REVOKE MANAGE GRANTS ON ACCOUNT FROM ROLE {F}SECURITY;"
    assert len(a.checks()) == len(rows) and a.checks()[0][:3] == (rows[0]["num"], rows[0]["title"], rows[0]["grantee"])


def without(d, edges):
    """d with the grant edges of a fix removed (an OWNERSHIP transfer counts as removed)."""
    gone = {(e["grantee"], e["to"], e["priv"]) for e in edges}
    role = lambda g: g["GRANTED_ON"] == "ROLE" and g["PRIVILEGE"] == "USAGE"
    return d | dict(GRANT=[g for g in d["GRANT"] if (g["GRANTEE_ROLE"], g["OBJECT_NAME"],
                                                     None if role(g) else g["PRIVILEGE"]) not in gone],
                    USER_ROLE=[x for x in d["USER_ROLE"] if (x["USER_NAME"], x["ROLE_NAME"], None) not in gone])


def test_fixes_clear():
    """Applying a finding's fix removes that finding."""
    for num, g in [("10", "ENGINEER_01"), ("10", "FIN_01"), ("11", "GRP_ANALYSTS"), ("17", F + "REPORTING_RO"),
                   ("17", T + "SHARED_LOGGING_READ"), ("7", "ANALYST_02"), ("18", T + "SHARED_LOGGING_READ"),
                   ("19", F + "ENGINEER"), ("20", T + "SALES_PIPELINE_EXECUTE"), ("21", T + "SALES_CORE_EXECUTE"),
                   ("22", F + "SUPPORT"), ("23", F + "MARKETING")]:
        a.build(a.fake())
        f = next(x for x in a.rule_rows() if x["num"] == num and x["grantee"] == g)
        assert f["edges"], (num, g)
        a.build(without(a.fake(), f["edges"]))
        assert not any(x["num"] == num and x["grantee"] == g for x in a.rule_rows()), (num, g, f["sql"])


def test_readonly():
    r = {(x["role"], x["object"]): x for x in a.readonly_writes()}
    assert set(r) == {(F + "REPORTING_RO", "SALES.RAW.TBL_ORDER_RAW"), (F + "MARKETING", "SALES.CLEAN.TBL_ORDER"),
                      (T + "SHARED_LOGGING_READ", "SHARED.LOGGING.TBL_LOGGING"),
                      (F + "FINANCE_REPORTING", "FINANCE.REPORT.TBL_REVENUE")}  # "REPORTING" in the name
    ro = r[(F + "REPORTING_RO", "SALES.RAW.TBL_ORDER_RAW")]
    assert ro["how"] == "both" and ro["inherited"] and ro["holder"] == T + "SALES_RAW_WRITE"
    assert (ro["read_only"], ro["objects"]) == (4, 5) and "INSERT" in ro["privileges"]
    mk = r[(F + "MARKETING", "SALES.CLEAN.TBL_ORDER")]
    assert mk["how"] == "behaviour" and mk["holder"] == T + "SALES_CLEAN_WRITE"
    lg = r[(T + "SHARED_LOGGING_READ", "SHARED.LOGGING.TBL_LOGGING")]
    assert lg["how"] == "name" and not lg["inherited"] and lg["privileges"] == ["INSERT"]
    assert a.readonly_writes(F + "ANALYST") == [] and a.readonly_writes(F + "DEPLOY") == []  # BUILD role excluded
    d = next(x for x in a.rule_rows() if x["num"] == "17" and x["grantee"] == F + "REPORTING_RO")["detail"]
    assert d.startswith("mostly read: 4 of 5 objects read-only; ") and f"via {T}SALES_RAW_WRITE (inherited)" in d
    assert d.endswith("heuristic: both")
    writers = {x for x, pv, p in a.who_can("SHARED.LOGGING.TBL_LOGGING") if pv == "INSERT" and a.from_user(p)}
    assert {"ANALYST_01", "ENGINEER_01"} <= writers


def test_demo_db():
    """test_sql.write writes every table, TAG and POLICY included; snapshot() reads back what fake() holds."""
    import duckdb
    from test_sql import write
    con = duckdb.connect()
    d = a.fake()
    write(con, d)

    def query(sql):
        cur = con.execute(sql)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    s = a.snapshot(query, "main")
    assert s["run"]["RUN_ID"] == "run-2" and s["run"]["SOURCES"]["tags"] == "ACCOUNT_USAGE"
    for t in a.TABLES + a.OPTIONAL:
        assert [{k: v for k, v in x.items() if k != "RUN_ID"} for x in s[t]] == d[t], t
    con.execute("DROP TABLE TBL_ACCESS_OBJECT_USE")  # a setup from before the table: still loads, no usage
    assert a.snapshot(query, "main")["OBJECT_USE"] is None


def au_grants(sql, plain):
    """A GRANTS_TO_ROLES SELECT (live() or SP_ACCESS_SNAPSHOT) run in DuckDB on rows shaped like the view (bare
    GRANTEE_NAME, NAME, TABLE_CATALOG, TABLE_SCHEMA), made from the GRANT rows plain: tests its qualification."""
    import duckdb
    import pandas as pd
    view = []
    for g in plain:
        o, k, r = g["OBJECT_NAME"], g["GRANTED_ON"], g["GRANTEE_ROLE"]
        p = o.split(".")
        cat, sch, name = (o, None, o) if k == "DATABASE" else p if len(p) == 3 else             (None, None, o) if len(p) == 1 else (p[0], None, p[1])
        view.append(dict(GRANTED_TO="DATABASE_ROLE" if "." in r else "ROLE", GRANTEE_NAME=r.split(".")[-1],
                         PRIVILEGE=g["PRIVILEGE"], GRANTED_ON=k, NAME=name, TABLE_CATALOG=cat, TABLE_SCHEMA=sch,
                         DELETED_ON=None, GRANT_OPTION=False, GRANTED_BY="X"))
    con = duckdb.connect()
    con.execute("CREATE MACRO IFF(c, x, y) AS CASE WHEN c THEN x ELSE y END")
    con.execute("CREATE MACRO ARRAY_CONSTRUCT_COMPACT(a, b, c) AS list_filter([a, b, c], lambda x: x IS NOT NULL)")
    con.register("v", pd.DataFrame(view))
    cur = con.execute(sql.replace("SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES", "v"))
    return [dict(zip([c[0] for c in cur.description], x)) for x in cur.fetchall()]


def fake_snowflake(d, au):
    """query(sql) answering live()'s SHOW commands from data set d; ACCOUNT_USAGE readable when au (canned rows).
    Database roles (DB.ROLE in d) only show up in SHOW DATABASE ROLES, never in SHOW ROLES."""
    plain = [g for g in d["GRANT"] if not g["IS_FUTURE"]]
    dbr = {g["OBJECT_NAME"] for g in plain if g["GRANTED_ON"] == "DATABASE_ROLE"} |         {g["GRANTEE_ROLE"] for g in plain if "." in g["GRANTEE_ROLE"]}
    roles = sorted(({g["GRANTEE_ROLE"] for g in d["GRANT"]} | {x["ROLE_NAME"] for x in d["USER_ROLE"]}) - dbr)
    dbs = sorted({g["OBJECT_NAME"].split(".")[0] for g in plain if g["GRANTED_ON"] not in ("ROLE", "ACCOUNT", "WAREHOUSE")})
    name = lambda sql: sql.split('"')[1]  # noqa: E731  the first quoted name
    qname = lambda sql: ".".join(sql.split('"')[1::2])  # noqa: E731  "DB"."ROLE" -> DB.ROLE
    calls = []

    def query(sql):
        calls.append(sql)
        s = " ".join(sql.split())
        if "ACCOUNT_USAGE" in s or "INFORMATION_SCHEMA" in s:
            if not au or "INFORMATION_SCHEMA" in s:
                raise RuntimeError("Object does not exist or not authorized.")
            if "LIMIT 1" in s:
                return [{"1": 1}]
            if "ACCOUNT_USAGE.GRANTS_TO_ROLES " in s + " ":
                return au_grants(s, plain)
            for view, rows in (("GRANTS_TO_USERS", d["USER_ROLE"]), ("USERS", d["USER"]),
                               ("QUERY_HISTORY", d["USAGE"]), ("TAG_REFERENCES", d["TAG"]), ("POLICY_REFERENCES", d["POLICY"]),
                               ("ACCESS_HISTORY", d["OBJECT_USE"])):
                if f"ACCOUNT_USAGE.{view} " in s + " ":
                    return [dict(x) for x in rows]
            raise AssertionError(s)
        if s.startswith("SELECT CURRENT_TIMESTAMP()"):
            return [{"T": "2026-11-03 10:00"}]
        if s.startswith("SELECT CURRENT_DATABASE()"):
            return [{"D": None}]
        if s == "USE SECONDARY ROLES ALL":
            return []
        if s == "SHOW ROLES":
            return [{"name": r} for r in roles]
        if s.startswith("SHOW GRANTS TO ROLE"):  # a database role comes back quoted, "DB"."ROLE"
            return [{"privilege": g["PRIVILEGE"], "granted_on": g["GRANTED_ON"], "granted_to": "ROLE", "grant_option": "false",
                     "name": '"' + g["OBJECT_NAME"].replace(".", '"."') + '"' if g["GRANTED_ON"] == "DATABASE_ROLE"
                     else g["OBJECT_NAME"]} for g in plain if g["GRANTEE_ROLE"] == name(s)]
        if s.startswith("SHOW DATABASE ROLES IN DATABASE"):
            return [{"name": r.split(".", 1)[1]} for r in sorted(dbr) if r.startswith(name(s) + ".")]
        if s.startswith("SHOW GRANTS TO DATABASE ROLE"):
            return [{"privilege": g["PRIVILEGE"], "granted_on": g["GRANTED_ON"], "name": g["OBJECT_NAME"],
                     "granted_to": "DATABASE_ROLE", "grant_option": "false"} for g in plain if g["GRANTEE_ROLE"] == qname(s)]
        if s.startswith("SHOW GRANTS OF ROLE"):
            return [{"grantee_name": x["USER_NAME"], "granted_to": "USER"} for x in d["USER_ROLE"] if x["ROLE_NAME"] == name(s)]
        if s == "SHOW DATABASES":
            return [{"name": x, "kind": "STANDARD"} for x in dbs] + [{"name": "SNOWFLAKE", "kind": "IMPORTED DATABASE"}]
        if s.startswith("SHOW SCHEMAS IN DATABASE"):
            return [{"name": x} for x in sorted({o.split(".")[1] for o in a_objects(plain) if o.startswith(name(s) + ".")})
                    ] + [{"name": "INFORMATION_SCHEMA"}]
        if s.startswith("SHOW FUTURE GRANTS IN SCHEMA"):
            where = ".".join(s.split('"')[1::2]) + "."
            return [{"grantee_name": g["GRANTEE_ROLE"], "privilege": g["PRIVILEGE"], "grant_on": g["GRANTED_ON"],
                     "name": g["OBJECT_NAME"], "grant_to": "ROLE"} for g in d["GRANT"]
                    if g["IS_FUTURE"] and g["OBJECT_NAME"].startswith(where)]
        if s.startswith("SHOW FUTURE GRANTS IN DATABASE"):
            return []
        if s == "SHOW USERS":
            return [{k.lower(): ("" if v is None else v) for k, v in x.items()} | {"name": x["USER_NAME"]} for x in d["USER"]]
        if s == "SHOW STREAMS IN ACCOUNT":
            return [dict(zip(("database_name", "schema_name", "name"), x["STREAM_NAME"].split(".")),
                         table_name=x["SOURCE_NAME"], source_type=x["SOURCE_TYPE"]) for x in d["STREAM"]]
        raise AssertionError(s)
    return query, calls


def a_objects(grants):
    return {g["OBJECT_NAME"] for g in grants if g["OBJECT_NAME"].count(".") >= 1 and g["GRANTED_ON"] not in a.ROLE_ON}


def test_each():
    """SHOW statements run SHOW_THREADS at a time, answers in order, a failure as its exception."""
    def query(sql):
        if sql == "bad":
            raise ValueError("no")
        return [{"sql": sql}]
    got = a.each(query, ["a", "bad", "c"] * 20)
    assert [g if isinstance(g, Exception) else g[0]["sql"] for g in got][:3] == ["a", got[1], "c"]
    assert isinstance(got[1], ValueError) and len(got) == 60


def test_live():
    """live() without ACCOUNT_USAGE (SHOW fallback) and with it gives the same lookups as the data it read; writes nothing."""
    d = a.fake()
    a.build(d)
    want = (sorted(a.role_grants), sorted(a.user_grants), sorted(a.privs), a.users[:], dict(a.profile))
    for au in (False, True):
        query, calls = fake_snowflake(d, au)
        s = a.live(query)
        assert not [c for c in calls if re.match(r"\s*(INSERT|CREATE|UPDATE|DELETE|MERGE|DROP|ALTER|GRANT|CALL)", c, re.I)]
        src = s["run"]["SOURCES"]
        assert src["grants"] == src["users"] == ("ACCOUNT_USAGE" if au else "SHOW") and src["future_grants"] == "SHOW"
        assert sum(g["IS_FUTURE"] for g in s["GRANT"]) == 1
        a.build(s)
        assert (sorted(a.role_grants), sorted(a.user_grants), sorted(a.privs), a.users, dict(a.profile)) == want, au
        assert a.role_kind("HR.SC_R_PEOPLE") == "database" and "HR.SC_R_PEOPLE" not in a.objects
        sql = " ".join(c for c in calls if "GRANTS_TO_ROLES" in c and "LIMIT 1" not in c)
        assert ("GRANTED_TO IN ('ROLE', 'DATABASE_ROLE')" in sql) == au  # the database role grantee qualified in SQL
        assert any(c.startswith('SHOW GRANTS TO DATABASE ROLE "HR"."SC_R_PEOPLE"') for c in calls) != au
        if not au:  # tags and policies: per-object INFORMATION_SCHEMA, every object skipped here, the run still loads
            assert src["tags"] == src["policies"] == "INFORMATION_SCHEMA" and "skipped" in s["run"]["NOTES"]["tags"]
            assert src["usage"] == "UNAVAILABLE" and s["STREAM"] == d["STREAM"]
        else:
            assert s["TAG"] == d["TAG"] and s["POLICY"] == d["POLICY"] and s["USAGE"] == d["USAGE"]
            assert s["OBJECT_USE"] == d["OBJECT_USE"] and src["object_use"] == "ACCOUNT_USAGE"
        assert au or (src["object_use"] == "UNAVAILABLE" and s["OBJECT_USE"] == [])  # no fallback: Granted vs used says why
    # SP_ACCESS_SNAPSHOT's copy of that SELECT (sql/1_setup.sql grants()) qualifies the same way
    setup = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sql", "1_setup.sql"), encoding="utf-8").read()
    sel = re.search(r"SELECT '\{run_id\}', (IFF\(GRANTED_TO = 'DATABASE_ROLE'.*?GRANTED_TO IN \('ROLE', 'DATABASE_ROLE'\))",
                    setup, re.S).group(1).replace("{AU}", a.AU)
    plain = [g for g in d["GRANT"] if not g["IS_FUTURE"]]
    got = au_grants("SELECT " + sel, plain)
    key = lambda x: tuple(x.values())[:4]  # noqa: E731  grantee, privilege, granted on, object
    assert sorted(map(key, got)) == sorted((g["GRANTEE_ROLE"], g["PRIVILEGE"], g["GRANTED_ON"], g["OBJECT_NAME"])
                                           for g in plain)


def test_db_roles():
    """A database role is a role that is held: role link, kind "database", its grants count for the user; mine()
    follows it with SHOW GRANTS TO DATABASE ROLE, recursively, and notes one it can't read."""
    w, r = "HR.SC_W_PEOPLE", "HR.SC_R_PEOPLE"
    assert (w, F + "ENGINEER") in a.role_grants and (r, w) in a.role_grants and w not in a.objects
    assert [a.kind_of(w), a.node_kind(r)] == ["database", "database"]
    reach = {x["role"]: x for x in a.reach("ENGINEER_01", True)}
    assert reach[w]["depth"] == 2 and reach[r]["depth"] == 3 and reach[r]["path"] == ["ENGINEER_01", F + "ENGINEER", w, r]
    got = {(x["privilege"], x["object"]) for x in a.grants("ENGINEER_01", True)}
    assert {("USAGE", "HR.PEOPLE"), ("SELECT", "HR.PEOPLE.TBL_EMPLOYEE"), ("INSERT", "HR.PEOPLE.TBL_EMPLOYEE")} <= got
    assert not [x for x in a.privs if x[2] == "DATABASE_ROLE"]  # USAGE on a database role is a link, not a privilege
    assert not [x for x in a.rule_rows() if x["kind"] == "database" and x["num"] in ("1", "2", "13")]
    assert a.revoke(a.role_edge(F + "ENGINEER", w))[1] == f"REVOKE DATABASE ROLE HR.SC_W_PEOPLE FROM ROLE {F}ENGINEER;"
    assert a.revoke(a.role_edge(w, r))[1] == "REVOKE DATABASE ROLE HR.SC_R_PEOPLE FROM DATABASE ROLE HR.SC_W_PEOPLE;"
    own = a.revoke(a.priv_edge(F + "ENGINEER", "OWNERSHIP", "DATABASE_ROLE", r))  # SQL keyword, not GRANTED_ON
    assert own[1].startswith(f"GRANT OWNERSHIP ON DATABASE ROLE {r} TO") and "database role " + r in own[0]
    d, want = a.fake(), sorted(x for x in got if "<" not in x[1])  # mine() reads no future grants
    mine_roles = [x["role"] for x in reach.values() if x["kind"] != "database"]
    for bad in (None, r):
        show, calls = fake_snowflake(d, False)

        def query(sql):
            if sql.startswith("SELECT CURRENT_USER()"):
                return [{"U": "ENGINEER_01"}]
            if sql.startswith("SELECT CURRENT_AVAILABLE_ROLES()"):
                return [{"R": json.dumps(mine_roles)}]
            if sql.startswith("SHOW GRANTS TO USER"):
                return [{"role": x} for x in a.roles_of["ENGINEER_01"]]
            if bad and sql == f'SHOW GRANTS TO DATABASE ROLE {a.db_ident(bad)}':
                raise RuntimeError("Insufficient privileges")
            return show(sql)

        m = a.mine(query, None)
        assert sum(c.startswith('SHOW GRANTS TO DATABASE ROLE "HR".') for c in calls) == (1 if bad else 2)  # each once
        a.build(m)
        assert a.kind_of(r) == "database" and r in {x["role"] for x in a.reach("ENGINEER_01", True)}
        mine_got = sorted({(x["privilege"], x["object"]) for x in a.grants("ENGINEER_01", True)})
        if bad:
            assert "HR.SC_R_PEOPLE (Insufficient" in m["run"]["NOTES"]["database_roles"]
            assert ("USAGE", "HR.PEOPLE") not in mine_got and ("INSERT", "HR.PEOPLE.TBL_EMPLOYEE") in mine_got
        else:
            assert mine_got == want and "database_roles" not in m["run"]["NOTES"]


def test_pages():
    """Every page renders without an exception on the fake data (one AppTest run each, no browser)."""
    from streamlit.testing.v1 import AppTest
    os.environ["FAKE"] = "1"  # never Snowflake here, whatever .env says
    os.environ["ST_REACT"] = "native"  # the plain Streamlit pages; the React app is checked in test_server
    app, c = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py"), "SALES.CORE.TBL_CUSTOMER"
    for q in (dict(page="user", name="ANALYST_01"), dict(page="role", name=T + "SALES_CORE_READ"),
              dict(page="object", name=c), dict(page="sensitive"), dict(page="check", name="ENGINEER_01", priv="SELECT", obj=c),
              dict(page="check", name="ANALYST_01", priv="INSERT", obj=c), dict(page="rules"), dict(page="review"),
              dict(page="user", data="mine"), dict(page="rules", data="mine"),
              dict(page="user", name="SVC_DEPLOY", schema="SALES.PIPELINE", otype="TASK"),
              dict(page="role", name=F + "DEPLOY", schema="SALES.PIPELINE", otype="TASK"),
              dict(page="user", name="HR_01", schema="HR.PAYROLL"), dict(page="role", name="HR.SC_R_PAYROLL"),
              dict(page="home"), dict(page="graph", table=c), dict(page="flow")):  # React-only screens: the User page
        at = AppTest.from_file(app, default_timeout=120)
        at.query_params.update(q)
        at.run()
        assert not at.exception, (q, [x.value for x in at.exception])
        md = " ".join(m.value for m in at.markdown)
        if q.get("page") in ("home", "graph", "flow"):
            assert "is in the React version only" in md, q
        elif q.get("page") == "user":
            assert "React version only" not in md
        if q == dict(page="user", name="ANALYST_01"):  # VIEW LINEAGE via PUBLIC, explained
            assert "Via PUBLIC (VIEW LINEAGE)" in md and "not a rule finding" in md
        if q == dict(page="rules", data="mine"):
            assert "Not checked here" in md
    at = AppTest.from_file(app, default_timeout=120)  # My access, loaded: its notes are explained
    at.query_params.update(dict(page="user", data="mine"))
    at.run()
    for b in at.button:
        if "Load" in b.label:
            b.click().run()
    md = " ".join(m.value for m in at.markdown)
    assert not at.exception and "Incomplete: role list fallback not readable" in md and "last 7 days only" in md
    at = AppTest.from_file(app, default_timeout=120)  # one Privileges tab, kept in the URL
    at.query_params.update(dict(page="user", name="HR_01", tab="read"))
    at.run()
    assert not at.exception and "Read privileges" in " ".join(m.value for m in at.markdown)


def test_kinds():
    assert {"USERADMIN", "ORGADMIN", "ACCOUNTADMIN"} <= a.ADMIN
    k = a.kind_of
    assert [k("ANALYST_01"), k("SYSADMIN"), k(F + "ANALYST"), k(T + "SALES_CORE_READ"), k("PUBLIC"), k("GRP_ANALYSTS"),
            k("SALES.CORE.TBL_CUSTOMER"), k("ACCOUNT")] == \
        ["user", "admin", "functional", "technical", "group", "group", "object", "object"]


def test_cycle():
    a.build(tiny([("A", "B"), ("B", "A")], [("A", "U")], [("B", "SELECT", "TABLE", "DB.S.T")]))
    assert sorted(a.walk("U", True)) == [["U", "A"], ["U", "A", "B"], ["U", "PUBLIC"]]
    assert len(a.held("A")) == 2 and not a.capped
    assert set(a.bfs(["A"])) == {"A", "B"}


def test_public():
    a.build(tiny([], [("R1", "U1"), ("R2", "U2")], [("PUBLIC", "SELECT", "TABLE", "DB.S.T")]))
    assert len(a.can("U1", "SELECT", "DB.S.T")["paths"]) == 1
    assert a.object_stats("DB.S.T")["users"] == 2 and len(a.matrix("DB.S.T")) == 2
    assert a.role_stats("PUBLIC")["users"] == 2
    assert a.can("U1", "SELECT", "DB.S.T")["options"][0]["affects"] == 2  # only the PUBLIC grant can be revoked
    # Snowflake's defaults on PUBLIC (account privileges, SNOWFLAKE.* database roles) are not rule 9
    a.build(tiny([("SNOWFLAKE.CORTEX_USER", "PUBLIC")], [("R1", "U1")],
                 [("PUBLIC", "VIEW LINEAGE", "ACCOUNT", "ACCOUNT"), ("PUBLIC", "SELECT", "TABLE", "DB.S.T")]))
    assert [x["detail"] for x in a.rules_admin() if x["num"] == "9"] == ["SELECT on TABLE DB.S.T"]
    assert not a.admin_people() and a.account_privs("U1", True)


def test_graph():
    html = ui.lane_graph([("U", [f"U{i}" for i in range(15)] + ["<x>"])], [], lambda n: "user", "light",
                         lambda n: "?n=" + n)
    assert "+4 more" in html and "expand=0" in html and "<x>" not in html


def test_cap():
    chain = [f"R{i:02}" for i in range(60)]
    a.build(tiny(list(zip(chain[1:], chain)), [("R00", "U")], [("R59", "SELECT", "TABLE", "DB.S.T")]))
    deepest = max(len(p) - 1 for p in a.walk("U", True))
    assert deepest == a.MAX_HOPS and a.capped == {"U"}
    assert a.grants("U", True) == []  # R59 is beyond the cap
    a.capped.clear()
    a.walk("U", True, limit=10)
    assert not a.capped  # a depth limit is not the safety cap


def test_new_rules():
    rows = a.rule_rows()
    by = lambda num: {x["grantee"]: x for x in rows if x["num"] == num}
    assert all("edge" in x for x in rows) and all(x["edge"] for x in rows if int(x["num"]) >= 18)
    r18 = by("18")
    assert set(r18) == {T + "SHARED_LOGGING_READ", T + "SALES_PIPELINE_EXECUTE", T + "SALES_PIPELINE_WRITE"}
    assert r18[T + "SALES_PIPELINE_WRITE"]["detail"].endswith("missing DELETE, TRUNCATE")
    assert r18[T + "SALES_PIPELINE_WRITE"]["sql"] == "" and r18[T + "SHARED_LOGGING_READ"]["edge"] == \
        (T + "SHARED_LOGGING_READ", "SHARED.LOGGING.TBL_LOGGING", "INSERT")
    assert set(by("19")) == {F + "ENGINEER", "ENGINEER_01"}  # SVC_DEPLOY (service) and F_DEPLOY (build) are fine
    assert by("19")["ENGINEER_01"]["edge"] == (T + "SALES_PIPELINE_EXECUTE", "ACCOUNT", "EXECUTE TASK")
    t = by("20")[T + "SALES_PIPELINE_EXECUTE"]
    assert "runs as its owner " + T + "SALES_PIPELINE_OWNER" in t["detail"] and t["severity"] == "High"
    assert list(by("21")) == [T + "SALES_CORE_EXECUTE"]  # MODIFY by the owner role is fine
    assert by("21")[T + "SALES_CORE_EXECUTE"]["sql"] == f"REVOKE OPERATE ON WAREHOUSE WH_SALES_XS FROM ROLE {T}SALES_CORE_EXECUTE;"
    s = by("22")[F + "SUPPORT"]
    assert s["edge"] == (T + "SALES_PIPELINE_READ", "SALES.PIPELINE.STR_CUSTOMER", "SELECT") and s["path"][-1] == \
        "SALES.PIPELINE.STR_CUSTOMER"
    r23 = by("23")
    assert set(r23) == {T + "FINANCE_REPORT_READ", F + "REPORTING_RO", F + "FINANCE_REPORTING", F + "MARKETING"}
    assert r23[F + "MARKETING"]["detail"].endswith("heuristic: behaviour") and r23[F + "REPORTING_RO"]["detail"].endswith("both")
    assert all(x["edge"] == (T + "FINANCE_REPORT_READ", "FINANCE.REPORT", "CREATE VIEW") for x in r23.values())
    assert by("6")["SALES.CORE.TBL_CUSTOMER"]["edge"] is None  # object finding: no edge
    assert by("14")["GRP_EMEA_ALL"]["edge"][1:] == ("FINANCE.REPORT.TBL_REVENUE", "SELECT")
    # CAP_PRIVS is a setting: READ may INSERT too, no EXECUTE / OWNER sets -> only the partial write set is left
    env = dict(os.environ, CAP_PRIVS='{"READ": ["SELECT", "USAGE", "INSERT"], "WRITE": ["INSERT", "UPDATE", "DELETE", '
                                     '"TRUNCATE"]}')
    out = subprocess.run([sys.executable, "-c", "import access as a; a.build(a.fake()); "
                          "print(sorted(x['grantee'] for x in a.rule_rows() if x['num'] == '18'))"],
                         env=env, capture_output=True, text=True, check=True).stdout
    assert out.strip() == f"['{T}SALES_PIPELINE_WRITE']"
    # a stage's own privileges are READ and WRITE: standard for READ / WRITE roles, no rule 18
    a.build(tiny([], [], [(T + "D_S_READ", "USAGE", "STAGE", "D.S.STG"), (T + "D_S_READ", "READ", "STAGE", "D.S.STG"),
                          (T + "D_S_WRITE", "READ", "STAGE", "D.S.STG"), (T + "D_S_WRITE", "WRITE", "STAGE", "D.S.STG")]))
    assert a.unusual() == []
    # rule 17 review hint: no fix edges, but its edge is still the write arrow (holder, object, privilege)
    a.build(a.fake())
    r17 = [x for x in a.rule_rows() if x["num"] == "17" and not x["edges"]]
    assert r17 and all(x["edge"][2] and a.role_kind(x["edge"][1]) == "object" for x in r17)


def test_fast():
    """Counted paths and lazily listed chains equal the full enumeration on the fake data."""
    for n, user in [(u, True) for u in a.users] + [(r, False) for r in a.roles]:
        for lim in (None, 1, 2, 3, 5):
            for only in ([False, True] if user else [False]):
                slow = a.group(((pv, k, o), p + [o]) for pv, k, o, p in a.access_of(n, user, only, lim))
                fast = {(r["privilege"], r["type"], r["object"]): r for r in a.grants(n, user, only, lim)}
                assert set(slow) == set(fast), (n, lim)
                assert all(fast[k]["paths"] == ps and fast[k]["count"] == len(ps) for k, ps in slow.items()), (n, lim)
                slow = a.group((p[-1], p) for p in a.walk(n, user, only, lim) if len(p) > 1)
                fast = {r["role"]: r for r in a.reach(n, user, only, lim)}
                assert set(slow) == set(fast) and all(fast[r]["paths"] == ps for r, ps in slow.items()), (n, lim)
    assert a.paths_note(a.grants("FIN_01", True)[0]) == ""
    a.MAX_PATHS = 1  # cut lists: counts stay exact, the shortest path is kept
    try:
        r = next(x for x in a.grants("ENGINEER_01", True) if x["privilege"] == "SELECT"
                 and x["object"] == "SALES.CORE.TBL_CUSTOMER")
        assert r["count"] == 3 and len(r["paths"]) == 1 and len(r["path"]) == 4 and a.paths_note(r) == "first 1 of 3"
    finally:
        a.MAX_PATHS = int(os.environ.get("MAX_PATHS", "200"))
    a.build(tiny([("B", "A"), ("C", "B"), ("C", "A"), ("A", "C")], [("A", "U")], [("C", "SELECT", "TABLE", "D.S.T")]))
    r = a.grants("U", True)[0]  # the loop C -> A is cut, both ways to C count
    assert r["count"] == 2 and r["paths"] == [["U", "A", "C", "D.S.T"], ["U", "A", "B", "C", "D.S.T"]] and not a.capped


def test_builtin():
    """Snowflake's built-in grants through PUBLIC: left out by default (one fold box in graphs), never rule 9 or 13;
    the database with 18 database roles held by two group roles."""
    info, rules = a.builtin_info(), Counter(c[0] for c in a.checks())
    assert info["grants"] == len(a.hidden) > 300 and {"SNOWFLAKE.CORTEX_USER", "SNOWFLAKE.PUBLIC"} <= set(info["roles"])
    assert not [n for n in a.roles + a.objects if a.is_builtin(n)]
    assert a.is_builtin("SYSTEM$STREAMLIT_NOTEBOOK_WH") and a.is_builtin("SYSTEM_COMPUTE_POOL_GPU") and not a.is_builtin("SNOWFLAKE")
    g = a.graph_input("ANALYST_01")
    assert g["lanes"][-1][1][-1] == a.BUILTIN_NODE and g["kinds"][a.BUILTIN_NODE] == "fold"
    assert ("PUBLIC", a.BUILTIN_NODE, "use", "USAGE", info["objects"]) in g["edges"]
    assert a.BUILTIN_NODE in a.role_graph("PUBLIC", a.held("PUBLIC"))[0][-1][1]
    n, extra = len(a.grants("ANALYST_01", True)), len({(x["PRIVILEGE"], x["OBJECT_NAME"]) for x in a.hidden
                                                         if x["GRANTED_ON"] not in a.ROLE_ON})
    dw = [r for r in a.roles if r.startswith("DW.")]
    assert len(dw) == 18 and {a.role_kind(r) for r in dw} == {"database"}
    assert {p for r in dw for p in a.held_by[r] if p not in dw} == {"GRP_DW_ENGINEERS", "GRP_DW_READERS"}
    reach = {x["role"]: x["path"] for x in a.reach("DW_DEV_01", True)}
    assert reach["DW.SC_R_ODS"] == ["DW_DEV_01", "GRP_DW_ENGINEERS", "DW.SC_M_ODS", "DW.SC_W_ODS", "DW.SC_R_ODS"]
    assert not [r for r in a.grants("DW_BI_01", True) if r["cls"] == "write"]
    a.build(a.fake(), builtin=True)
    assert a.builtin_info() is None and len(a.grants("ANALYST_01", True)) == n + extra
    assert sum(o.startswith("SNOWFLAKE.CORE.FN_") for o in a.objects) >= 200
    assert a.role_kind("SNOWFLAKE.CORTEX_USER") == "database" and "SNOWFLAKE.CORTEX_USER" in {
        x["role"] for x in a.reach("ANALYST_01", True)}
    assert Counter(c[0] for c in a.checks()) == rules  # the same findings: no rule 9 on them, no orphan learning role


def test_whatif_indirect():
    """A role held further down can be taken away: cut where it is granted, on the grantee's paths; then unreached."""
    r, g = next((r, g) for r in sorted(a.roles) for g in sorted(a.ups(r)[0] - {r})
                if r not in a.holds.get(g, []) and g != "PUBLIC" and not any(x in a.ADMIN for x in a.ups(r)[0]))
    via = {h for h in a.held_by[r] if g in a.ups(h)[0]}
    w = a.what_if([dict(op="revoke_role_from_role", role=r, grantee=g)])
    assert "held through" in w["changes"][0]["label"] and all(h in w["sql"] for h in via), w["changes"][0]
    cut, _ = a.changes_of([dict(op="revoke_role_from_role", role=r, grantee=g)])
    assert cut["link"] == {(r, h) for h in via}
    u = next(u for u in sorted(a.users) if a.roles_of.get(u) and r not in a.roles_of[u] and u in a.ups(r)[1]
             and "PUBLIC" not in a.held_by.get(r, []))
    cut, _ = a.changes_of([dict(op="revoke_role_from_user", role=r, user=u)])
    assert cut["link"] and not cut["user"]
    try:
        a.changes_of([dict(op="revoke_role_from_role", role=r, grantee=r + "_NOPE")])
        raise AssertionError("no error")
    except ValueError as x:
        assert "does not reach" in str(x)


def test_whatif():
    """What if: revokes simulated in memory, the loaded lookups untouched; the scoped rule recheck equals a rebuild."""
    keep = (a.roles, list(a.privs), list(a.role_grants), dict(a.holds), a.cached("findings", a.findings))
    nine = next(x for x in a.rule_rows() if x["num"] == "9")
    pub = a.what_if([dict(op="empty_public")])
    lost = {x["user"] for x in pub["users"] if "WH_SALES_XS" in {r["object"] for r in x["lost_rows"]}}
    assert len(lost) == nine["affects"] == len(a.users) - 3 and pub["counts"]["users"] == len(a.users)  # VIEW LINEAGE
    kept = {x["user"]: x["kept_rows"][0] for x in pub["users"] if x["kept_rows"]}
    assert set(kept) == {"ANALYST_01", "ANALYST_02", "ENGINEER_01"} and {x["via"][-2] for x in kept.values()} == {F + "ANALYST"}
    assert pub["sql"] == "REVOKE USAGE ON WAREHOUSE WH_SALES_XS FROM ROLE PUBLIC; REVOKE VIEW LINEAGE ON ACCOUNT FROM ROLE PUBLIC;"
    assert [(f["num"], f["status"]) for f in pub["findings"]] == [("9", "fixed")]
    assert pub["summary"].startswith(f"{len(a.users)} users lose access to 2 objects; 3 keep access")
    w = a.what_if([dict(op="revoke_role_from_role", role=T + "SALES_CORE_READ", grantee=F + "ANALYST")])
    u = {x["user"]: x for x in w["users"]}
    assert set(u) == {"ANALYST_01", "ANALYST_02", "ENGINEER_01"} and w["sql"] == f"REVOKE ROLE {T}SALES_CORE_READ FROM ROLE {F}ANALYST;"
    assert "SALES.CORE.TBL_CUSTOMER" in {r["object"] for r in u["ANALYST_01"]["lost_rows"]}
    assert u["ENGINEER_01"]["lost"] == 0 and u["ENGINEER_01"]["kept_roles"][0]["through"] == F + "ENGINEER"
    w = a.what_if([dict(op="revoke_role_from_user", role="GRP_ANALYSTS", user="ANALYST_01")])
    assert {(pv, r["object"]) for r in w["users"][0]["lost_rows"] for pv in r["privileges"]} == set(
        a.loses("ANALYST_01", "ANALYST_01", "GRP_ANALYSTS"))
    assert ("10", "ANALYST_01", "fixed", False) in {(f["num"], f["grantee"], f["status"], f["changed"]) for f in w["findings"]}
    w = a.what_if([dict(op="revoke_priv", role=T + "SALES_MART_OWNER", privilege="OWNERSHIP", object="SALES.MART.VW_CUSTOMER")])
    assert w["objects"] == [dict(object="SALES.MART.VW_CUSTOMER", type="VIEW", sensitive=True, unreached=False, ownerless=True)]
    assert w["sql"].startswith("GRANT OWNERSHIP ON VIEW SALES.MART.VW_CUSTOMER TO ROLE <new owner role>")
    w = a.what_if([dict(op="drop_role", role=F + "ENGINEER")])
    fixed = {(f["num"], f["grantee"]) for f in w["findings"] if f["status"] == "fixed" and not f["changed"]}
    assert {("4", F + "ENGINEER"), ("19", F + "ENGINEER")} <= fixed and w["sql"] == f"DROP ROLE {F}ENGINEER;"
    assert T + "SALES_CORE_WRITE" in {r["role"] for r in w["roles"] if r["orphan"]}
    assert "HR.PEOPLE.TBL_EMPLOYEE" in {x["object"] for x in w["objects"] if x["unreached"]}
    assert w["csv"][0] == dict(section="change", name=f"Drop role {F}ENGINEER", privilege="", type="", object="", cls="",
                               status="", path="", detail=f"DROP ROLE {F}ENGINEER;")
    assert (a.roles, a.privs, a.role_grants, a.holds) == keep[:4] and a.roles is keep[0]
    assert a.cached("findings", a.findings) is keep[4]  # the memo is back too
    for bad in ([dict(op="grant_role")], [dict(op="drop_role", role="PUBLIC")], [dict(op="drop_role", role="SYSADMIN")],
                [dict(op="revoke_role_from_user", role=F + "ENGINEER", user="ANALYST_01")],
                [dict(op="revoke_priv", role=F + "ANALYST", privilege="SELECT", object="NO.SUCH.TABLE")]):
        try:
            a.what_if(bad)
            raise AssertionError(bad)
        except ValueError:
            pass
    for ch in ([dict(op="empty_public")], [dict(op="drop_role", role=F + "ENGINEER")],
               [dict(op="revoke_role_from_user", role="GRP_ANALYSTS", user="ANALYST_02")],
               [dict(op="revoke_role_from_role", role=F + "FINANCE_EDITOR", grantee=F + "FINANCE_REPORTING")],
               [dict(op="revoke_priv", role=T + "SHARED_LOGGING_READ", privilege="INSERT", object="SHARED.LOGGING.TBL_LOGGING"),
                dict(op="drop_role", role="GRP_DW_READERS")]):
        w = a.what_if(ch)
        b3 = {(f["num"], f["grantee"], f["user"]) for f in a.findings()}
        a.build(a.without_cuts(a.fake(), a.changes_of(ch)[0]))
        a3 = {(f["num"], f["grantee"], f["user"]) for f in a.findings()}
        a.build(a.fake())
        got = lambda st: {(f["num"], f["grantee"], f["kind"] == "user") for f in w["findings"]  # noqa: E731
                          if f["status"] == st and not f["changed"]}
        assert got("fixed") == b3 - a3 and got("new") == a3 - b3, ch


def big():
    """2,000 objects (5 databases x 10 schemas x 40 tables), 300 roles (200 technical, 100 functional nested into
    earlier ones, so paths fan out), 500 users; BIG_01 holds the 10 last functional roles."""
    rnd, g = random.Random(7), []

    def grant(r, pv, k, o):
        g.append(dict(GRANTEE_ROLE=r, PRIVILEGE=pv, GRANTED_ON=k, OBJECT_NAME=o, IS_FUTURE=False))

    techs = []
    for d in range(5):
        for s in range(10):
            base = f"{T}DB{d}_S{s}"
            techs += [f"{base}_READ", f"{base}_WRITE", f"{base}_OWNER", f"{base}_EXECUTE"]
            grant(f"{base}_WRITE", "USAGE", "ROLE", f"{base}_READ")
            for i in range(40):
                o = f"DB{d}.S{s}.TBL_{i:02}"
                grant(f"{base}_OWNER", "OWNERSHIP", "TABLE", o)
                grant(f"{base}_READ", "SELECT", "TABLE", o)
                for pv in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                    grant(f"{base}_WRITE", pv, "TABLE", o)
    funcs = [f"{F}TEAM_{i:03}" for i in range(100)]
    for i, f in enumerate(funcs):
        for t in rnd.sample(techs, 6):
            grant(f, "USAGE", "ROLE", t)
        for j in rnd.sample(range(i), min(i, 3)):
            grant(f, "USAGE", "ROLE", funcs[j])
    users = [f"U_{i:03}" for i in range(499)] + ["BIG_01"]
    ur = [(u, f) for u in users[:-1] for f in rnd.sample(funcs, 2)] + [("BIG_01", f) for f in funcs[-10:]]
    pc = "SNOWFLAKE.CORE.PRIVACY_CATEGORY"  # some sensitive columns and a row policy, so the sensitive rules work too
    tags = [dict(OBJECT_NAME=f"DB{d}.S0.TBL_{i:02}", DOMAIN="COLUMN", COLUMN_NAME="EMAIL", TAG_NAME=pc,
                 TAG_VALUE="IDENTIFIER", APPLY_METHOD="CLASSIFIED") for d in range(5) for i in range(10)]
    pol = [dict(POLICY_NAME="D.S.RAP", POLICY_KIND="ROW_ACCESS_POLICY", OBJECT_NAME="DB0.S0.TBL_00", COLUMN_NAME=None,
                ARG_COLUMNS="REGION", TAG_NAME=None, POLICY_BODY=f"IS_ROLE_IN_SESSION('{funcs[0]}')")]
    return dict(run={}, GRANT=g, USER_ROLE=[dict(USER_NAME=u, ROLE_NAME=r) for u, r in ur],
                USER=[dict(USER_NAME=u) for u in users], USAGE=[], TAG=tags, POLICY=pol)


def timed(f, budget, reset=None):
    """f() under budget seconds, best of up to 3 runs (reset() untimed before a retry, so caches start empty again):
    one slow run on a busy machine is not a regression."""
    took = []
    while len(took) < 3 and (not took or min(took) >= budget):
        if took and reset:
            reset()
        t = time.perf_counter()
        f()
        took.append(time.perf_counter() - t)
    assert min(took) < budget, f"{min(took):.1f} s"


def test_perf():
    d, got = big(), {}

    def first():
        a.build(d)
        got["rows"] = a.grants("BIG_01", True)
        got["groups"] = a.group_objects(got["rows"], "schema")
    timed(first, 3)
    rows, groups = got["rows"], got["groups"]
    assert len(a.objects) == 2000 and len(a.roles) >= 299 and len(a.users) == 500
    assert len({r["object"] for r in rows}) > 1000 and max(r["count"] for r in rows) > a.MAX_PATHS
    assert sum(g["objects"] for g in groups) == len({r["object"] for r in rows})

    def second():  # the graph, the rule checks, the summary and one busy object
        got["g"] = a.graph_input("BIG_01")
        a.rule_rows()
        a.has_lacks_summary("BIG_01", True)
        a.grantees("DB0.S0.TBL_00")
        a.data_view("BIG_01", "DB0.S0.TBL_00", True)
    timed(second, 8, lambda: a.build(d))
    g, n = got["g"], len({r["object"] for r in rows})
    assert g["header"] == f"{n:,} objects, grouped by {g['level']}" and g["level"] != "object"
    g = a.graph_input("BIG_01", groups[0]["group"])  # 40 tables in one schema: one type group
    assert g["level"] == "type" and g["lanes"][-1][1] == [groups[0]["group"] + " · TABLE"]
    for ch in ([dict(op="revoke_role_from_role", role=F + "TEAM_005", grantee=a.held_by[F + "TEAM_005"][0])],
               [dict(op="drop_role", role=F + "TEAM_010")]):  # what if: hundreds of users lose or keep access
        timed(lambda: got.update(w=a.what_if(ch)), 3, lambda: a.build(d))  # 1.5 - 2 s on a laptop
        assert got["w"]["counts"]["users"] > 10


def test_group_graph():
    rows = a.grants("SVC_DEPLOY", True)
    gs = {g["group"]: g for g in a.group_objects(rows, "schema")}
    p = gs["SALES.PIPELINE"]
    assert p["objects"] == 9 and p["classes"] == ["own"] and p["holders"] == [T + "SALES_PIPELINE_OWNER"]
    assert gs["FINANCE.REPORT"]["sensitive"] == 2 and gs["FINANCE.REPORT"]["findings"] > 0
    # CREATE SCHEMA on database SALES: an object of its own at schema level, not a "SALES" group of 1
    assert gs["WH_SALES_XS"]["level"] == "object" and gs["SALES"]["level"] == "object"
    assert {g["group"] for g in a.group_objects(rows, "database")} == {"SALES", "SHARED", "FINANCE", "WH_SALES_XS",
                                                                      "WH_FINANCE_XS", "ACCOUNT"}
    holders = {h for r in a.grants("ANALYST_01", True) if r["database"] == "SALES" for h in r["holders"]}
    assert set(next(g for g in a.group_objects(a.grants("ANALYST_01", True), "database")
                    if g["group"] == "SALES")["holders"]) == holders  # every holder, not one per row
    g = a.graph_input("SVC_DEPLOY", max_objects=40)
    assert g["level"] == "object" and g["header"] == "33 objects" and g["kinds"] == {a.BUILTIN_NODE: "fold"}
    g = a.graph_input("SVC_DEPLOY", max_objects=20)  # over the cap: grouped by schema (14 groups, under 20)
    assert g["header"] == "33 objects, grouped by schema" and g["lanes"][-1][0] == "Schemas"
    assert g["kinds"]["SALES.PIPELINE"] == "schema" and "SALES" not in g["kinds"] and "WH_SALES_XS" not in g["kinds"]
    assert (T + "SALES_PIPELINE_OWNER", "SALES.PIPELINE", "own", "OWNERSHIP", 9) in g["edges"]
    assert g["info"]["SALES.PIPELINE"]["count"] == 9 and "count" not in g["info"].get("SALES", {})
    g = a.graph_input("SVC_DEPLOY")  # over a lane's 12, and 14 schema groups: grouped by database
    assert g["header"] == "33 objects, grouped by database" and g["kinds"]["SALES"] == "database"
    assert g["info"]["SALES"]["count"] == 19 and g["info"]["SALES"]["noun"] == "objects"
    d = a.graph_input("SVC_DEPLOY", "SALES")  # a database: its schemas, its own grants as objects
    assert d["level"] == "schema" and "SALES" in d["lanes"][-1][1] and "SALES" not in d["kinds"]
    g = a.graph_input("SVC_DEPLOY", "SALES.PIPELINE", max_objects=3)
    assert g["header"] == "9 objects in SALES.PIPELINE, grouped by object type"
    assert [n for _, ns in g["lanes"][1:-1] for n in ns] == [F + "DEPLOY", T + "SALES_OWNER", T + "SALES_PIPELINE_OWNER"]
    assert set(g["kinds"].values()) == {"type-group"} and "SALES.PIPELINE · TASK" in g["kinds"]
    assert g["types"]["SALES.PIPELINE · TASK"] == "TASK"  # a type box links to ?otype=TASK
    t = a.graph_input("SVC_DEPLOY", "SALES.PIPELINE", max_objects=3, otype="TASK")  # one type: its objects, one by one
    assert t["level"] == "object" and t["lanes"][-1][1] and all(a.kinds[o] == "TASK" for o in t["lanes"][-1][1])
    g = a.graph_input("SVC_DEPLOY", "SALES.PIPELINE")
    assert g["level"] == "object" and len(g["lanes"][-1][1]) == 9
    assert a.graph_input("SVC_DEPLOY", "NO.SUCH") is None
    h = a.graph_input("HR_01", "HR.PAYROLL")  # the fake data's own type boxes, at the default MAX_OBJECTS
    assert h["types"] == {"HR.PAYROLL · TABLE": "TABLE", "HR.PAYROLL · VIEW": "VIEW"}
    assert len(a.graph_input("HR_01", "HR.PAYROLL", otype="TABLE")["lanes"][-1][1]) == 13
    e = a.graph_input("ENGINEER_01")
    task = e["info"][(T + "SALES_PIPELINE_EXECUTE", "SALES.PIPELINE.TSK_LOAD_CUSTOMER", "manage")]
    assert [r[0] for r in task["rules"]] == ["18", "20"] and task["has"] == ["OPERATE"] and task["lacks"] == ["MONITOR"]
    assert e["info"][(F + "ENGINEER", T + "SALES_MART_OWNER", "inherit")]["rules"][0][:2] == ("4", "High")
    assert a.in_scope(dict(database="SALES", schema=""), "SALES") and not a.in_scope(dict(database="", schema=""), "X")
    assert a.scopes(a.grants("SVC_DEPLOY", True)) >= {"SALES", "SALES.PIPELINE"}


def test_has_lacks():
    x = a.has_lacks(T + "SALES_PIPELINE_WRITE", "SALES.PIPELINE.TBL_CUSTOMER_CHANGES")
    assert x["has"] == ["SELECT", "INSERT", "UPDATE"] and x["lacks"] == ["DELETE", "TRUNCATE", "REFERENCES"]
    assert x["text"] == "SELECT, INSERT, UPDATE but not DELETE, TRUNCATE, REFERENCES"
    o = a.has_lacks(F + "DEPLOY", "SALES.CORE.TBL_CUSTOMER")
    assert o["has"] == ["OWNERSHIP"] and o["lacks"] == [] and "INSERT" in o["implied"]
    assert a.has_lacks("ANALYST_01", "SALES.CORE.TBL_CUSTOMER", True)["has"] == ["SELECT"]
    s = a.has_lacks_summary(T + "SALES_CORE_READ")
    assert {(x["type"], x["text"]) for x in s} >= {("TABLE", "SELECT but not INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES")}
    assert sum(x["count"] for x in s) == len({o for _, k, o in a.granted[T + "SALES_CORE_READ"] if not k.startswith("FUTURE")})
    assert a.valid_privs("TASK") == ["OWNERSHIP", "MONITOR", "OPERATE"]


def test_data_view():
    rev, order, raw, cust = ("FINANCE.REPORT.TBL_REVENUE", "SALES.CLEAN.TBL_ORDER", "SALES.RAW.TBL_ORDER_RAW",
                             "SALES.CORE.TBL_CUSTOMER")
    v = a.data_view("MARKETING_01", rev)
    assert v["can_read"] and v["rows"]["state"] == "none" and v["summary"] == "can read: no rows"
    assert v["rows"]["reason"].startswith(f"RAP_REGION allows only {F}FINANCE (in session) or {F}DEPLOY (primary role); "
                                          "MARKETING_01 holds neither -> sees no rows")
    assert "IS_ROLE_IN_SESSION" in v["rows"]["body"] and a.masked("MARKETING_01", rev) == "masked"
    assert a.data_view("FIN_01", rev)["rows"]["state"] == "all"  # F_FINANCE is inherited: in session
    assert a.data_view(F + "DEPLOY", rev)["rows"]["state"] == "all"  # primary role
    assert a.data_view(F + "DEPLOY", order)["rows"]["state"] == "all"
    assert a.data_view(F + "FINANCE_EDITOR", rev)["rows"]["state"] == "none"  # holds F_FINANCE? no: F_FINANCE holds it
    f = a.data_view("MARKETING_01", order)["rows"]
    assert f["state"] == "filtered" and f["condition"] == "REGION = 'EU'" and "only rows where REGION = 'EU'" in f["reason"]
    assert a.data_view(F + "MARKETING", order)["rows"]["state"] == "filtered"
    assert a.data_view("REPORT_01", order)["rows"]["state"] == "none"
    u = a.data_view("REPORT_01", raw)
    assert u["rows"]["state"] == "unknown" and "depends on policy logic" in u["rows"]["reason"] and a.masked("REPORT_01", raw) == "?"
    c = {x["column"]: x for x in a.data_view("ENGINEER_01", cust)["columns"]}
    assert c["EMAIL"]["state"] == "clear" and c["PHONE"]["state"] == "clear" and c["PHONE"]["reason"] == "no masking policy"
    assert c["EMAIL"]["tags"] and c["PHONE"]["sensitive"]
    m = {x["column"]: x for x in a.data_view(F + "ANALYST", cust)["columns"]}
    assert m["EMAIL"]["state"] == "masked" and m["EMAIL"]["reason"].startswith(f"MP_EMAIL shows the value only to {F}ENGINEER")
    assert a.data_view("FIN_01", cust)["summary"] == "cannot read it (no SELECT or OWNERSHIP)"
    assert {v["object"] for v in a.data_views("MARKETING_01")} >= {rev, order, cust}
    t = {p["name"].split(".")[-1]: a.policy_text(p) for p in a.policy_list()}
    assert t["RAP_REGION"] == f"RAP_REGION: {F}FINANCE (in session): all rows; {F}DEPLOY (primary role): all rows; " \
                              "everyone else: no rows"
    assert "only rows where REGION = 'EU'" in t["RAP_ORDER_REGION"] and "unknown" in t["RAP_ORDER_MAP"]
    assert t["MP_EMAIL"] == f"MP_EMAIL: clear for {F}ENGINEER (in session); everyone else: masked"
    p = dict(name="X.Y.P", kind="ROW_ACCESS_POLICY", args='["REGION"]', clear=None, body=None)
    for body, want in [("CURRENT_ROLE() IN ('A', 'B')", ["A", "B"]), ("NOT IS_ROLE_IN_SESSION('A')", None),
                       ("IS_ROLE_IN_SESSION('A') AND CURRENT_USER() = 'U'", None), ("1 = 1", None),
                       ("(IS_ROLE_IN_SESSION('A') OR CURRENT_ROLE() = 'B') AND REGION = 'EU'", None)]:
        q = p | dict(body=body, clear=a.clear_for(body))
        got = a.row_terms(q)
        assert (got and [r for g in got[0]["roles"] for r, _ in g]) == want if want else got is None, body
    k = a.governance_kpis()
    assert (k["row_tables"], k["masked_columns"]) == (3, 2) and k["text"]["Masking"] == "2 columns"
    gr = {g["object"]: g for g in a.governance_rows()}
    assert gr[rev]["row_policies"] and gr[cust]["masking"]["EMAIL"] and "EMAIL" in gr[cust]["column_tags"]
    a.build(tiny([], [("R", "U")], [("R", "SELECT", "TABLE", "D.S.T")]))
    assert set(a.governance_kpis()["text"].values()) == {"not used"} and a.data_view("U", "D.S.T")["summary"] == \
        "can read: all rows"


def test_namespaces():
    """Users and roles are separate namespaces: user Z holds R9, R9 holds role Z, role Z reads D.S.Z; role X and
    user X both hold R2."""
    a.build(tiny([("Z", "R9"), ("R2", "X")], [("R9", "Z"), ("R2", "X")],
                 [("Z", "SELECT", "TABLE", "D.S.Z"), ("R2", "SELECT", "TABLE", "D.S.T")]))
    assert ["Z", "R9", "Z"] in a.walk("Z", True)  # down() does not block role Z under user Z
    g = a.grants("Z", True)
    assert [(r["object"], r["path"], r["depth"]) for r in g] == [("D.S.Z", ["Z", "R9", "Z", "D.S.Z"], 2)]
    assert {r["role"]: r["kind"] for r in a.reach("Z", True)}["Z"] == "group"  # the role, not the user
    ge = {(r["grantee"], r["kind"]): r for r in a.grantees("D.S.Z")}
    assert ge[("Z", "group")]["depth"] == 1 and ge[("Z", "user")]["depth"] == 2
    assert not a.from_user(["Z"]) and a.from_user(["Z" + a.UTAG, "R9", "Z"]) and not a.from_user(["Z", "R9"])
    assert {(r["grantee"], r["kind"]) for r in a.held("R9")} == {("Z", "user")}
    # user X and role X both hold R2: one row each, counted once each
    assert sorted((r["grantee"], r["kind"], r["count"]) for r in a.held("R2")) == [("X", "group", 1), ("X", "user", 1)]
    assert a.role_stats("R2")["users"] == 1 and a.role_stats("R2")["above"] == 1
    assert sorted((r["grantee"], r["kind"], r["depth"]) for r in a.grantees("D.S.T")) ==         [("R2", "group", 1), ("X", "group", 2), ("X", "user", 1)]
    assert a.object_stats("D.S.T")["users"] == 1 and a.object_stats("D.S.T")["roles"] == 2
    assert [m["user"] for m in a.matrix("D.S.T")] == ["X"] and [r["user"] for r in a.review() if r["object"] == "T"] == ["X"]
    a.build(tiny([("R2", "X")], [], [("R2", "SELECT", "TABLE", "D.S.T")]) | dict(USER=[dict(USER_NAME="X")]))
    assert not a.from_user(["X", "R2"])  # a user X exists, but only role X holds R2
    assert [(r["grantee"], r["kind"]) for r in a.grantees("D.S.T")] == [("R2", "group"), ("X", "group")]
    # role X (held by user Y) and user X both hold R2: cutting role X -> R2 takes it from Y, not from user X
    a.build(tiny([("X", "Y0"), ("R2", "X")], [("X", "Y"), ("R2", "X")], [("R2", "SELECT", "TABLE", "D.S.T")]))
    assert a.users_through("X") == {"Y"} and a.users_through("X", True) == {"X"}
    assert a.lose(a.role_edge("X", "R2")) == {"Y"} and a.lose(a.role_edge("X", "R2", True)) == {"X"}
    # rule 13 sees role Z although a user Z exists; rule 19 paths start at the plain user name
    a.build(tiny([], [("R9", "Z"), ("R2", "X")], [("Z", "SELECT", "TABLE", "D.S.T"), ("R9", "SELECT", "TABLE", "D.S.U"),
                                                  ("R2", "EXECUTE TASK", "ACCOUNT", "ACCT"), ("X", "SELECT", "TABLE", "D.S.T")]))
    assert {c[2] for c in a.checks() if c[0] == "13"} >= {"Z", "X"}
    assert ["X", "R2", "ACCT"] in [c[4] for c in a.checks() if c[0] == "19"]
    # graphs: user Z and role Z are two boxes; the role page walks the role, not the user
    a.build(tiny([("Z", "R9"), ("T2", "Z")], [("R9", "Z"), ("A", "Z")],
                 [("A", "SELECT", "TABLE", "D.S.T1"), ("T2", "SELECT", "TABLE", "D.S.T2")]))
    g = a.graph_input("Z", user=True)
    names = [n for _, ns in g["lanes"] for n in ns]
    assert names[0] == "Z" + a.UTAG and "Z" in names[1:] and a.node_kind(names[0]) == "user" and a.node_kind("Z") == "group"
    assert a.node_name(names[0]) == "Z" and ("Z" + a.UTAG, "R9") in g["edges"] and ("R9", "Z") in g["edges"]
    r = a.graph_input("Z", user=False)
    assert r["lanes"][-1][1] == ["D.S.T2"] and r["lanes"][0][1] == ["Z"]
    lanes, edges, _ = a.down_graph("Z", a.grants("Z", True), user=True)
    assert lanes[0][1] == ["Z" + a.UTAG] and "Z" in {n for _, ns in lanes[1:] for n in ns}


# ---------- graph geometry: every page graph of the fake data, parsed back from the SVG ----------

def polyline(d):
    """SVG path d (M, H, V, C) -> points; curves sampled."""
    pts = []
    for cmd, args in re.findall(r"([MHVC])([^MHVC]*)", d):
        v = [float(x) for x in args.split()]
        x, y = pts[-1] if pts else (0, 0)
        if cmd == "M":
            pts.append((v[0], v[1]))
        elif cmd == "H":
            pts.append((v[0], y))
        elif cmd == "V":
            pts.append((x, v[0]))
        else:
            for k in range(1, 17):
                s = k / 16
                pts.append(tuple((1 - s) ** 3 * p0 + 3 * (1 - s) ** 2 * s * p1 + 3 * (1 - s) * s * s * p2 + s ** 3 * p3
                                 for p0, p1, p2, p3 in zip((x, y), v[0:2], v[2:4], v[4:6])))
    return pts


def hits(p, q, b, m=0.5):
    """Does segment p-q enter the inside of box b = (x, y, w, h) shrunk by m? (Liang-Barsky clipping)"""
    x0, y0, x1, y1 = b[0] + m, b[1] + m, b[0] + b[2] - m, b[1] + b[3] - m
    lo, hi = 0.0, 1.0
    dx, dy = q[0] - p[0], q[1] - p[1]
    for d, a, c in ((-dx, p[0] - x0, 0), (dx, x1 - p[0], 0), (-dy, p[1] - y0, 0), (dy, y1 - p[1], 0)):
        if d == 0:
            if a < 0:
                return False
        else:
            t = a / d
            if d < 0:
                lo = max(lo, t)
            else:
                hi = min(hi, t)
    return lo < hi


def overlap(b, c):
    return b[0] < c[0] + c[2] and c[0] < b[0] + b[2] and b[1] < c[1] + c[3] and c[1] < b[1] + b[3]


def geometry(html, where):
    svg = ET.fromstring(html[html.index("<svg"):html.index("</svg>") + 6])
    boxes = {}
    for el in svg.iter("a"):
        r = el.find("rect")
        boxes.setdefault(el.get("data-n"), []).append(tuple(float(r.get(k)) for k in ("x", "y", "width", "height")))
    assert all(len(v) == 1 for v in boxes.values()), (where, "one box per node")
    boxes = {k: v[0] for k, v in boxes.items()}
    names = list(boxes)
    for i, x in enumerate(names):
        for y in names[i + 1:]:
            assert not overlap(boxes[x], boxes[y]), (where, "boxes overlap", x, y)
    edges = [(p.get("data-a"), p.get("data-b"), p.get("data-c"), p.get("data-back") == "1", polyline(p.get("d")))
             for p in svg.iter("path") if p.get("data-a")]
    for a_, b_, c, back, pts in edges:
        sa, sb = boxes[a_], boxes[b_]
        segs = list(zip(pts, pts[1:]))
        for name, bx in boxes.items():  # endpoints too: an edge touches their border, never their inside
            assert not any(hits(p, q, bx, 1 if name in (a_, b_) else 0.5) for p, q in segs), (where, a_, b_, c, "crosses", name)
        assert abs(pts[-1][0] - sb[0]) < .2 and sb[1] < pts[-1][1] < sb[1] + sb[3], (where, a_, b_, "ends at left side")
        assert pts[-2][1] == pts[-1][1] and pts[-2][0] < pts[-1][0], (where, a_, b_, "enters from the left")
        if back:  # out of the top or bottom of the source
            assert sa[0] < pts[0][0] < sa[0] + sa[2] and min(abs(pts[0][1] - sa[1]), abs(pts[0][1] - sa[1] - sa[3])) < .2
        else:
            assert abs(pts[0][0] - sa[0] - sa[2]) < .2, (where, a_, b_, "leaves from the right side")
            assert all(q[0] >= p[0] - .05 for p, q in segs), (where, a_, b_, c, "x goes back")
    labels = [(g.get("data-a"), g.get("data-b"), g.get("data-c"),
               tuple(float(g.find("rect").get(k)) for k in ("x", "y", "width", "height")))
              for g in svg.iter("g") if g.get("data-a")]
    for i, (a_, b_, c, r) in enumerate(labels):
        for x in labels[i + 1:]:
            assert not overlap(r, x[3]), (where, "labels overlap", a_, b_, x[:2])
        for name, bx in boxes.items():
            assert not overlap(r, bx), (where, "label on node", a_, b_, name)
        for e in edges:
            if e[:3] != (a_, b_, c):
                assert not any(hits(p, q, r, 0) for p, q in zip(e[4], e[4][1:])), (where, "label on edge", a_, b_, e[:3])
    return boxes, edges, labels


def page_graphs():
    """(where, (lanes, edges, notes), selected lane) for every graph the pages draw on the fake data."""
    rank = lambda k: 0 if a.is_data(k) else 1 if k == "WAREHOUSE" else 3 if k in ("DATABASE", "SCHEMA") else 2
    for u in a.users:
        for only in (False, True):
            rows = [r for r in a.grants(u, True, only) if not (r["privilege"] == "USAGE" and r["type"] in ("DATABASE", "SCHEMA"))]
            rows.sort(key=lambda r: (rank(r["type"]), r["object"], r["privilege"]))
            g = a.down_graph(u, rows, a.walk(u, True, only))
            if g:
                yield f"user {u} default_only={only}", g, None
    for r in a.roles:
        lanes, edges, notes, far = a.role_graph(r, a.held(r))
        yield f"role {r}", (lanes, edges, notes), far
    for o in a.objects:
        t = a.kinds[o]
        g = a.grantees(o, t)
        users = sorted({x["grantee"] for x in g if x["kind"] == "user" and a.from_user(x["path"])})
        shown = [x for x in g if x["kind"] != "user" or x["grantee"] in users]
        g = a.object_graph(o, t, shown, users)
        if g:
            yield f"object {o}", g, None


def test_graph_geometry():
    n, holders = 0, 0
    for where, (lanes, edges, notes), sel in page_graphs():
        for fit in (False, True):
            html = ui.lane_graph(lanes, edges, a.kind_of, "light", lambda x: "?n=" + x, sel, fit=fit, notes=notes)
            boxes, drawn, _ = geometry(html, (where, fit))
            n += 1
        if where.startswith("object "):  # lanes follow the chain: every line runs left to right
            lane = {x: i for i, (_, ns) in enumerate(lanes) for x in ns}
            assert all(lane[e[0]] < lane[e[1]] for e in edges), where
            holders += any("also grant holder" in b for b, _ in notes.values())
    assert n > 100 and holders
    # ENGINEER_01: T_SALES_CORE_READ once, at depth 2, also reached at depth 3 through the WRITE role (dotted, back edge)
    rows = a.grants("ENGINEER_01", True)
    lanes, edges, notes = a.down_graph("ENGINEER_01", rows, a.walk("ENGINEER_01", True))
    assert notes[T + "SALES_CORE_READ"][0] == "D2 · also D3"
    html = ui.lane_graph(lanes, edges, a.kind_of, "dark", lambda x: "?n=" + x, notes=notes)
    boxes, drawn, labels = geometry(html, "ENGINEER_01")
    back = [e for e in drawn if e[3]]
    assert [(e[0], e[1]) for e in back] == [(T + "SALES_CORE_WRITE", T + "SALES_CORE_READ")]
    assert "D3: ENGINEER_01 &gt; " + F + "ENGINEER &gt; " + T + "SALES_CORE_WRITE" in html
    assert ui.plabel(["INSERT", "UPDATE", "DELETE", "TRUNCATE"]) == "INSERT · UPDATE · DELETE +1"


# ---------- render kit: group nodes, rule hits, dotted also-deeper edges, long labels ----------

def kit_graph():
    """A small graph with every render feature: (lanes, edges, kind_of, notes, info)."""
    f1, f2 = F + "KIT_ANALYST", F + "KIT_ENGINEER"
    tr, tw, tx, ty = T + "KIT_SALES_READ", T + "KIT_SALES_WRITE", T + "KIT_HUB_READ", T + "KIT_HUB_LINK"
    lanes = [("Start", ["KIT_USER"]), ("D1", [f1, f2]), ("D2", [tr, tw, tx]), ("D3", [ty]),
             ("Objects", ["KITDB.SALES", "KITDB.HUB", "KITDB.SALES.ORDERS", "KITDB"])]
    kinds = {"KIT_USER": "user", f1: "functional", f2: "functional", "KITDB.SALES": "schema", "KITDB.HUB": "schema",
             "KITDB.SALES.ORDERS": "object", "KITDB": "database"}
    edges = [("KIT_USER", f1), ("KIT_USER", f2), (f1, tr), (f2, tw), (f2, tx), (tx, ty),
             (tw, tr), (ty, tr),  # also deeper: dotted, back into tr's left side
             (tr, "KITDB.SALES", "read", "SELECT", 120), (tr, "KITDB.SALES", "read", "REFERENCES", 120),
             (tw, "KITDB.SALES", "write", "INSERT", 8), (tw, "KITDB.SALES", "write", "UPDATE", 8),
             (tw, "KITDB.SALES", "write", "DELETE", 3), (tw, "KITDB.SALES", "write", "TRUNCATE", 1),
             (tr, "KITDB.SALES.ORDERS", "read", "SELECT"),
             (tw, "KITDB.SALES.ORDERS", "write", "INSERT"), (tw, "KITDB.SALES.ORDERS", "write", "UPDATE"),
             (tw, "KITDB.SALES.ORDERS", "write", "DELETE"), (tw, "KITDB.SALES.ORDERS", "write", "TRUNCATE"),
             (tx, "KITDB.HUB", "read", "SELECT", 40), (ty, "KITDB", "use", "USAGE")]
    notes = {tr: ("D2 · also D3", "D2: KIT_USER > " + f1 + " > " + tr)}
    hit = [("17", "High", "Read-only role can write")]
    info = {"KITDB.SALES": {"count": 128, "noun": "objects", "sensitive": 3, "findings": 2},
            "KITDB.HUB": {"count": 40, "noun": "objects"}, "KITDB": {"count": 1, "noun": "database"},
            tw: {"rules": hit + [("4", "Medium", "Role with no users"), ("9", "Low", "Unused"), ("2", "Low", "x")]},
            (tw, "KITDB.SALES", "write"): {"rules": hit, "has": ["INSERT"], "lacks": ["SELECT"]},
            (ty, tr, "inherit"): {"rules": [("6", "Medium", "Technical role holds a technical role")]},
            (f2, tx, "inherit"): {"rules": [("5", "Low", "Cross-database link")]}}
    return lanes, edges, lambda x: kinds.get(x, "technical"), notes, info


def test_graph_kit():
    lanes, edges, kind_of, notes, info = kit_graph()
    n = 0
    for theme in ("light", "dark"):
        for fit in (False, True):
            html = ui.lane_graph(lanes, edges, kind_of, theme, lambda x: "?n=" + x, fit=fit, notes=notes, info=info)
            boxes, drawn, labels = geometry(html, ("kit", theme, fit))
            for a_, b_, c, back, pts in drawn:
                assert pts[-2][0] < pts[-1][0] and abs(pts[-1][0] - boxes[b_][0]) < .2, (a_, b_, "enters from the left")
                if back:  # dotted, and no detour: x never grows before the last run into the target
                    assert all(q[0] <= p[0] + .05 for p, q in zip(pts[:-1], pts[1:-1])), (a_, b_, "backward detour")
                else:
                    assert all(q[0] >= p[0] - .05 for p, q in zip(pts, pts[1:])), (a_, b_, "x goes back")
            n += 1
            svg = ET.fromstring(html[html.index("<svg"):html.index("</svg>") + 6])
            for p in svg.iter("path"):  # every drawn edge and its hit stroke has a title naming both ends
                if p.get("data-a"):
                    tip = p.find("title").text
                    assert p.get("data-a") in tip and p.get("data-b") in tip, tip
            back = [e for e in drawn if e[3]]
            assert sorted((e[0], e[1]) for e in back) == sorted([(T + "KIT_SALES_WRITE", T + "KIT_SALES_READ"),
                                                                 (T + "KIT_HUB_LINK", T + "KIT_SALES_READ")])
            assert 'stroke-dasharray="2 3"' in html and "128 objects" in html and "D2 · also D3" in html
            assert "Rule 17 (High): Read-only role can write" in html and "Has: INSERT" in html and "Lacks: SELECT" in html
            assert "INSERT ×8 · UPDATE ×8 · DELETE ×3 +1" in html  # at most 3 privileges, then +N
            assert "INSERT · UPDATE · DELETE +1" in html and "SELECT ×120 · REFERENCES ×120" in html
            assert "+1</text>" in html  # 4 rules on one node: 3 badges, then +1
            if fit:  # scaled into the card, but never below a readable size: then it scrolls
                tag = html[html.index("<svg"):html.index(">", html.index("<svg"))]
                w = float(re.search(r'viewBox="0 0 (\d+)', tag).group(1))
                assert f"min-width:{w * ui.MIN_SCALE:.0f}px" in tag and "scroll sideways" not in html
    assert n == 4
    # every page graph again with rule hits on every edge and node: badges never break the layout
    k = 0
    for where, (lanes, edges, notes), sel in page_graphs():
        k += 1
        if k % 7:
            continue
        rs = [("17", "High", "x"), ("4", "Medium", "y")]
        inf = {ui._norm(e)[:2] + (ui._norm(e)[2],): {"rules": rs} for e in edges}
        inf |= {x: {"rules": rs} for _, ns in lanes for x in ns}
        geometry(ui.lane_graph(lanes, edges, a.kind_of, "light", lambda x: "?n=" + x, sel, notes=notes, info=inf),
                 (where, "rules"))


def test_summary():
    """Big graphs are drawn as a summary (granted roles -> one fold box each -> grant holders -> groups) that fits the
    card; the fake data's graphs never are."""
    assert not [n for n in a.users + a.roles if (g := a.graph_input(n)) and a.too_big(g)]
    a.build(big())
    for scope in (None, "DB0", "DB0.S1"):
        g = a.graph_input("BIG_01", scope, user=True)
        assert a.too_big(g), scope
        s = a.summary(g)
        assert [lb for lb, _ in s["lanes"][1:-1]] == ["Granted roles", "Roles between", "Grant holders"], scope
        folds = [n for n, k in s["kinds"].items() if k == "fold"]
        assert folds and s["folded"] > 0 and all(s["notes"][f][0].startswith("down to D") for f in folds)
        assert s["lanes"][-1] == g["lanes"][-1]  # the same groups as the full graph
        kind = lambda n: s["kinds"].get(n) or a.node_kind(n)
        for fit in (False, True):
            html = ui.lane_graph(s["lanes"], s["edges"], kind, "light", lambda x: "?n=" + x, fit=fit, notes=s["notes"],
                                 info=s["info"])
            boxes, drawn, _ = geometry(html, ("summary", scope, fit))
            assert not [e for e in drawn if e[3]], "no also-deeper edges in a summary"
            w = float(re.search(r'viewBox="0 0 ([\d.]+)', html).group(1))
            assert all(b[0] >= 0 and b[0] + b[2] <= w for b in boxes.values()), (scope, "node outside the SVG")
            if fit:  # fits a 1440 px page's graph card without scrolling
                assert w * ui.MIN_SCALE <= ui.WIDE and "scroll sideways" not in html, (scope, w)
            assert sum(n.startswith("⋯") for n in boxes) == len(folds) and len(boxes) <= 1 + 3 * 13 + 13


def test_cache():
    import tempfile
    from pathlib import Path
    cache.DIR = Path(tempfile.mkdtemp())
    os.environ["SNOWFLAKE_ACCOUNT"] = "T"
    reads = []
    def read():
        reads.append(1)
        return a.fake()
    d, at = cache.get("k", read)
    assert len(reads) == 1 and cache.file("k").is_file()
    cache.MEM.clear()  # a new process: the local file answers
    d2, at2 = cache.get("k", read)
    assert len(reads) == 1 and d2["USER"] == d["USER"] and abs(at2 - at) < 5
    cache.drop("k")  # "read again": memory and file gone
    cache.get("k", read)
    assert len(reads) == 2
    assert cache.prev("k") is None  # the same run read again: not a previous snapshot
    newer = lambda: a.fake_previous() | dict(run=dict(a.fake()["run"], RUN_ID="newer"))  # noqa: E731
    cache.drop("k")
    cache.get("k", newer)
    assert cache.prev("k")[0]["run"]["RUN_ID"] == "fake" and cache.get("k", read)[0]["run"]["RUN_ID"] == "newer"
    cache.MEM.clear()
    cache.get("k", read)  # expired file: the next read keeps it as the previous one too
    assert cache.prev("k")[0]["run"]["RUN_ID"] == "fake"
    cache.HOURS = 0  # memory only: nothing written
    cache.drop("k")
    cache.get("k", read)
    assert not cache.file("k").exists()
    cache.HOURS = 24
    os.environ.pop("SNOWFLAKE_ACCOUNT")
    for env, err in (({"SOURCE": "objects"}, "ACCESS_SNAPSHOT"), ({"SOURCE": "x"}, "SOURCE must be")):
        try:
            cache.config(env)
        except ValueError as x:
            assert err in str(x)
        else:
            raise AssertionError(env)
    assert cache.config({"SOURCE": "objects", "SNOWFLAKE_DATABASE": "D", "SNOWFLAKE_SCHEMA": "S"}) == ("snowflake", "objects", "D.S")
    assert cache.config({"ACCESS_SNAPSHOT": "D.S"}) == ("snowflake", "objects", "D.S")  # backward compatible
    assert cache.config({}) == ("snowflake", "direct", "") and cache.config({"FAKE": "1"})[0] == "fake"


def test_ladder():  # access ladder: highest level per object, counts at or above a step, DW_DEV_01 groups by schema
    assert a.level_of("SELECT", "TABLE") == "read" and a.level_of("TRUNCATE", "TABLE") == "change"
    assert a.level_of("OWNERSHIP", "VIEW") == "own" and a.level_of("USAGE", "SCHEMA") == "names"
    assert a.category("USAGE", "WAREHOUSE") == "runnable" and a.category("OPERATE", "TASK") == "runnable"
    assert a.category("CREATE TABLE", "SCHEMA") == "account" and a.category("OWNERSHIP", "SCHEMA") == "data"
    assert a.category("USAGE", "DATABASE_ROLE") == "hold" and a.category("EXECUTE TASK", "ACCOUNT") == "account"
    o = a.access_objects(a.grants("ENGINEER_01", True), True)
    n = a.ladder_counts(o)
    assert (n["read"], n["change"], n["own"], n["runnable"], n["account"], n["usage"]) == (6, 5, 2, 4, 3, 8), n
    mart = next(x for x in o if x["object"] == "SALES.MART")
    assert mart["level"] == "own" and mart["privileges"][0] == "OWNERSHIP"  # its USAGE folds into the owned row
    cust = next(x for x in o if x["object"] == "SALES.CORE.TBL_CUSTOMER")
    assert cust["first"] == F + "ENGINEER" and cust["ways"] > 1 and cust["privileges"][-1] == "SELECT"
    dw = [x for x in a.access_objects(a.grants("DW_DEV_01", True), True) if x["category"] == "data" and x["level"] == "change"]
    assert len(dw) == 15 and len({(x["database"], x["schema"]) for x in dw}) == 5


def test_who_has():  # screen 2: one entry per user / role at its highest step, admins inherit, same routes grouped
    w = a.who_has("SALES.CORE.TBL_CUSTOMER")
    by = {x["name"]: x for x in w["people"]}
    assert by["ENGINEER_01"]["level"] == "change" and by["ENGINEER_01"]["first"] == F + "ENGINEER" and by["ENGINEER_01"]["ways"] > 1
    assert by["SVC_DEPLOY"]["level"] == "own" and by["ANALYST_01"]["privileges"] == ["SELECT"]
    assert by["OPS_01"]["level"] == "admin" and by["OPS_01"]["path"] == ["OPS_01", "SYSADMIN"] and by["OPS_01"]["first"] is None
    assert [x["level"] for x in w["people"]] == sorted((x["level"] for x in w["people"]), key=lambda l: -a.OBJ_LEVELS.index(l))
    assert {x["name"] for x in w["roles"]} >= {F + "ENGINEER", T + "SALES_CORE_READ"} and all(x["users"] >= 0 for x in w["roles"])
    assert a.obj_level("USAGE", "WAREHOUSE") == "use" and a.obj_level("OPERATE", "WAREHOUSE") == "change"
    g = a.same_paths(a.who_has("WH_SALES_XS")["people"])
    assert g[0]["route"][0] == "PUBLIC" and len(g[0]["names"]) > 10 and g[0]["level"] == "use", g[0]
    assert sum(len(x["names"]) for x in g) == len(a.who_has("WH_SALES_XS")["people"])
    adm = a.admin_access()
    assert {x["name"] for x in adm["people"]} == set(a.admin_users()) and all(x["level"] == "admin" for x in adm["people"])
    assert all(x["name"] not in a.ADMIN for x in adm["roles"])
    cols, seen = a.column_view("SALES.CORE.TBL_CUSTOMER", list(by))
    em = next(c for c in cols if c["column"] == "EMAIL")
    assert em["policies"] and em["masked"] and "ENGINEER_01" in em["clear"]
    assert next(c for c in seen["ANALYST_01"] if c["column"] == "EMAIL")["state"] == "masked"


def test_nearest():  # screens 3, 12, 15: lanes and cuts, nearest ways in, suggested role, approver
    o = "HR.PEOPLE.TBL_EMPLOYEE"
    r = a.can("ENGINEER_01", "SELECT", o)
    ls, cut = a.lanes([q | dict(privilege="SELECT") for q in r["paths"]])
    assert len(ls) == 1 and cut == [F + "ENGINEER", "HR.SC_W_PEOPLE", "HR.SC_R_PEOPLE"], (ls, cut)
    cs = a.cut_points("ENGINEER_01", ["SELECT", "INSERT", "UPDATE"], o)
    assert [c["people"] for c in cs] == [["ENGINEER_01"]] * 2 and cs[0]["lost"] < cs[1]["lost"], cs
    assert "HR.SC_W_PEOPLE FROM ROLE" in cs[0]["sql"] and "FROM USER ENGINEER_01" in cs[1]["sql"]
    pub = a.cut_points("ANALYST_01", ["USAGE"], "WH_SALES_XS")
    assert all("PUBLIC" not in (e["grantee"], e["to"]) for c in pub for e in c["edges"])
    n = a.nearest("FIN_09", "SELECT", o)
    assert n[0]["role"] == F + "ENGINEER" and n[0]["to_user"] and n[0]["cost"] == 1 and n[0]["people"] == 0, n[0]
    assert [x["cost"] for x in n] == sorted(x["cost"] for x in n)
    g = next(x for x in n if x["to"] == "GRP_EMEA_ALL" and x["role"] == "HR.SC_R_PEOPLE")
    assert g["missing"] == 1 and g["people"] > 10 and g["broad"] and g["path"][-1] == o
    assert any(x["path"][1] == "<NEW_ROLE>" and x["cost"] == 2 for x in n)  # a database role can't go to a user
    assert all(x["role"] not in a.ADMIN and not a.reaches_admin(x["role"]) and x["role"] != "PUBLIC" for x in n)
    s = a.suggest(["SELECT"], "SALES.CORE.TBL_CUSTOMER", "FIN_09")
    assert s[0]["role"] == F + "ANALYST" and [x["extra"] for x in s] == sorted(x["extra"] for x in s), s
    assert s[0]["holders"] >= 1 and "PHONE" in s[0]["unmasked"] and all(a.role_kind(x["role"]) == "functional" for x in s)
    assert not any(x["role"] == F + "ENGINEER" for x in a.suggest(["SELECT"], o, "ENGINEER_01"))  # already held
    assert a.suggest(["INSERT", "UPDATE"], o, "FIN_09")[0]["role"] == F + "ENGINEER"
    assert a.approver(o) == "HR data owner" and a.approver("SALES.CORE.TBL_CUSTOMER") is None
    assert a.need_privs("TABLE", "change") == ["INSERT", "UPDATE"] and a.need_privs("WAREHOUSE", "read") == ["USAGE"]
    assert a.basic_priv("VIEW") == "SELECT" and a.need_privs("TABLE", "own") == ["OWNERSHIP"]
    assert a.brings(F + "ENGINEER", o)["extra"] > 10


def test_graph_see_compare():  # screens 4, 7, 9: access graph, what they see, compare
    o = "SALES.CORE.TBL_CUSTOMER"
    g = a.access_graph("object", o)
    cls = {(e[0], e[1]): e[2] for e in g["edges"]}
    assert cls[(T + "SALES_CORE_READ", o)] == "read" and cls[(T + "SALES_CORE_WRITE", o)] == "write"
    assert cls[(F + "ENGINEER", T + "SALES_CORE_WRITE")] == "write" and cls[("SYSADMIN", o)] == "admin"
    assert [lab for lab, _ in g["lanes"]][0] == "People" and g["lanes"][-1] == ("Table", [o])
    st = next(s for s, us in g["stacks"].items() if "ANALYST_01" in us)
    assert set(g["stacks"][st]) == {"ANALYST_01", "ANALYST_02"} and (st, "GRP_ANALYSTS") in cls
    assert g["risky"][("OPS_01", "SYSADMIN")] == "admin" and g["people"][o] and g["leads"]["GRP_ANALYSTS"] == [o]
    lane = {n: i for i, (_, ns) in enumerate(g["lanes"]) for n in ns}
    assert lane["GRP_ANALYSTS"] == 1 and lane[F + "ANALYST"] == 1  # shortest step: ENGINEER_01 holds it directly
    assert not a.access_graph("object", o, same=False)["stacks"]
    assert not any(e[2] == "admin" for e in a.access_graph("object", o, admin=False)["edges"])
    u = a.access_graph("user", "ENGINEER_01")
    assert u["start"] == "ENGINEER_01" and a.BUILTIN_NODE in u["leads"]["PUBLIC"]
    assert u["risky"][(T + "SHARED_LOGGING_READ", "SHARED.LOGGING.TBL_LOGGING")] == "writes"
    assert u["risky_nodes"]["PUBLIC"] == "public" and u["levels"][F + "ENGINEER"] == "own"
    r = a.access_graph("role", F + "ENGINEER")
    lane = {n: i for i, (_, ns) in enumerate(r["lanes"]) for n in ns}
    assert lane["SYSADMIN"] < lane[F + "ENGINEER"] < lane[T + "SALES_CORE_READ"] and r["lanes"][-1][0] == "Reaches"
    assert ("SYSADMIN", F + "ENGINEER") in {(e[0], e[1]) for e in r["edges"]}
    for st, n in [("user", x) for x in a.users] + [("role", x) for x in a.roles] + [("object", x) for x in a.objects]:
        g = a.access_graph(st, n)
        ids = {x for _, ns in g["lanes"] for x in ns}
        assert all(e[0] in ids and e[1] in ids for e in g["edges"]), (st, n)
    try:
        a.access_graph("role", "NOPE")
        assert False
    except ValueError:
        pass
    s = a.seen("ENGINEER_01", True)
    assert s["counts"]["columns"] == 5 and s["counts"]["clear"] == 5 and s["counts"]["unprotected"] == 3, s["counts"]
    c = next(x for x in s["cards"] if x["object"] == o)
    assert {x["column"]: x["fix"] for x in c["columns"]} == {"BIRTH_DATE": True, "EMAIL": False, "PHONE": True}
    assert s["cards"][0]["sensitive"] and not s["cards"][-1]["sensitive"]
    m = a.seen(F + "ANALYST", False)["counts"]
    assert m["masked"] == 2 and m["clear"] == 2
    d = a.compare("ENGINEER_01", True, "ANALYST_01", True)
    assert d["counts"] == dict(only_a=0, only_b=0, different=2, same=1), d["counts"]
    assert [r["diff"] for r in d["rows"]] == ["different", "different", "same"]
    assert d["match"] == [dict(op="grant", role=F + "ENGINEER", to="ANALYST_01", toUser=True)]
    assert dict(op="revoke", role=F + "ENGINEER", to="ENGINEER_01", toUser=True) in d["extras"]
    x = a.compare(F + "DEPLOY", False, F + "MARKETING", False)
    assert x["counts"]["only_a"] == 2 and all(c["op"] == "grant" and not c["toUser"] for c in x["match"])
    assert a.compare("ENGINEER_01", True, "ADMIN_01", True)["counts"]["only_a"] == 0  # an admin reaches everything
    assert a.compare("ENGINEER_01", True, "ANALYST_01", True, "db", "HR")["rows"][0]["diff"] == "only_a"
    assert a.sees_text(F + "ANALYST", o) == "BIRTH_DATE clear · EMAIL masked · PHONE clear"


def test_plan():  # screens 5 and 11: every finding's fix as What if changes simulates and fixes that finding
    rows = a.rule_rows()
    for x in rows:
        ch = a.fix_changes(x["edges"])
        assert len(ch) == len({str(c) for c in ch}) and (bool(ch) == bool(x["edges"])), x["num"]
        if ch:
            r = a.what_if(ch)
            assert any(f["num"] == x["num"] and f["grantee"] == x["grantee"] and f["status"] == "fixed" for f in r["findings"]), x
    assert a.fix_changes([a.role_edge("U1", "R", True), a.role_edge("U1", "R", True), a.role_edge("R2", "R"),
                          a.priv_edge("R", "SELECT", "TABLE", "DB.S.T")]) == [
        dict(op="revoke_role_from_user", role="R", user="U1"), dict(op="revoke_role_from_role", role="R", grantee="R2"),
        dict(op="revoke_priv", role="R", privilege="SELECT", object="DB.S.T")]
    nine = next(x for x in rows if x["num"] == "9")
    assert a.finding_objects(nine) == ["WH_SALES_XS"]
    six = next(x for x in rows if x["num"] == "6")
    assert a.finding_objects(six) == [six["grantee"]] and not a.fix_changes(six["edges"])
    before = len(a.granted)
    a.what_if(a.fix_changes(nine["edges"]))
    assert len(a.granted) == before and any(pv == "USAGE" for pv, _, o in a.granted["PUBLIC"] if o == "WH_SALES_XS")


def test_review_catalog_flow():  # screens 6, 8, 16: review grid, sensitive catalog, sensitive data flow
    cat = {r["object"]: r for r in a.catalog()}
    assert [r["status"] for r in a.catalog()] == ["not", "partly", "protected", "whole", "whole"]
    c = cat["SALES.CORE.TBL_CUSTOMER"]
    assert c["unmasked"] == 2 and c["groups"] == ["pii"] and [x["column"] for x in c["columns"] if x["masked"]] == ["EMAIL"]
    assert cat["FINANCE.REPORT.TBL_REVENUE"]["groups"] == ["confidential"] and a.protection([], 0) == "whole"
    g = a.review_grid()
    assert {x["id"] for x in g["columns"]} == set(a.sensitive()) and g["total"] == 5
    rows = {r["user"]: r for r in g["rows"]}
    assert rows["ADMIN_01"]["admin"] and all(x["level"] == "admin" for x in rows["ADMIN_01"]["cells"].values())
    assert {q[1] for q in a.admin_paths("ADMIN_01", True)} <= set(rows["ADMIN_01"]["roles"])
    assert g["rows"][0]["admin"] and rows["FIN_14"]["status"] == "disabled" and "GRP_EMEA_ALL" in rows["FIN_14"]["roles"]
    cell = rows["ANALYST_01"]["cells"]["SALES.CORE.TBL_CUSTOMER"]
    assert cell["level"] == "read" and cell["path"][0] == "ANALYST_01" and cell["path"][-1] == "SALES.CORE.TBL_CUSTOMER"
    assert "PUBLIC" not in {r for x in g["rows"] for r in x["roles"]}
    al = a.review_grid("all", cap=10)
    assert len(al["columns"]) == 10 < al["total"] and al["columns"][0]["sensitive"]
    assert all(x["level"] != "names" for r in al["rows"] for x in r["cells"].values())
    assert any(x["level"] == "names" for r in a.review_grid("db", "HR", hide_usage=False)["rows"] for x in r["cells"].values())
    o = a.review_grid(obj="SALES.CORE.TBL_CUSTOMER")
    assert o["columns"][0]["id"] == "OWNERSHIP" and {x["id"] for x in o["columns"]} >= {"SELECT", "INSERT"}
    assert all(list(x["cells"]) for x in o["rows"])
    f = a.sens_flow()
    grp = {x["id"]: x["users"] for x in f["groups"]}
    assert set(grp["risky"]) == {"ANALYST_02", "FIN_12", "FIN_13", "FIN_14"} and grp["admin"] == ["ADMIN_01", "OPS_01"]
    assert grp["service"] == ["SVC_DEPLOY"] and f["roles"][0]["id"] == a.ADMIN_BOX
    ids = {x["id"] for x in f["groups"] + f["roles"] + f["objects"]}
    assert all(l["source"] in ids and l["target"] in ids and l["users"] for l in f["links"])
    risky = {l["target"] for l in f["links"] if l["source"] == "risky"}
    assert risky == {"GRP_EMEA_ALL", "GRP_ANALYSTS", a.TECH + "SALES_MART_READ"}  # ANALYST_02 holds it straight (rule 1)
    cu = next(x for x in f["objects"] if x["id"] == "SALES.CORE.TBL_CUSTOMER")
    assert cu["unmasked"] == ["BIRTH_DATE", "PHONE"] and cu["masked"] == ["EMAIL"]
    small = a.sens_flow(max_roles=3)
    assert len(small["roles"]) == 4 and small["roles"][-1]["kind"] == "fold" and small["roles"][-1]["id"].startswith("Other roles")


def test_usage_changes():  # screens 13, 14: granted vs used (ACCESS_HISTORY), what changed between two snapshots
    assert a.use_state() == (True, None) and a.monday("2026-11-04 10:00").isoformat() == "2026-11-02"
    g = a.granted_used("ENGINEER_01", True, 90)
    rows = {r["object"]: r for r in g["rows"]}
    assert len(g["weeks"]) == 13 == len(rows["SALES.CORE.TBL_CUSTOMER"]["weeks"]) and g["weeks"][-1] == "2026-11-02"
    emp, log = rows["HR.PEOPLE.TBL_EMPLOYEE"], rows["SHARED.LOGGING.TBL_LOGGING"]
    assert emp["used"] is None and emp["suggest"] == "drop" and {c["privilege"] for c in emp["changes"]} == {"SELECT", "INSERT", "UPDATE"}
    assert log["used"] == "read" and log["unused"] == ["INSERT"] and log["changes"] == [
        dict(op="revoke_priv", role=T + "SHARED_LOGGING_READ", privilege="INSERT", object="SHARED.LOGGING.TBL_LOGGING")]
    vw = rows["SALES.MART.VW_CUSTOMER"]
    assert vw["level"] == "own" and vw["suggest"] == "trim" and not vw["changes"]  # ownership is transferred, not revoked
    assert rows["SALES.CORE.TBL_CUSTOMER"]["suggest"] == "keep" and g["rows"][0]["suggest"] == "drop"
    assert g["counts"]["changes"] == len(g["changes"]) == 4 and g["counts"]["write_unused"] == 1
    assert {r["object"]: r["used"] for r in a.granted_used("ENGINEER_01", True, 180)["rows"]}["HR.PEOPLE.TBL_EMPLOYEE"] == "read"
    a.what_if(g["changes"])  # the trim simulates
    r = a.granted_used(F + "ANALYST", False, 30)
    assert r["people"] == 3 and {x["used"] for x in r["rows"]} == {"read"}
    d = a.diff(a.fake_previous())
    assert a.run["RUN_ID"] == "fake" and len(a.findings()) == len(a.cached("findings", a.findings))  # put back after
    ev = {e["text"]: e for e in d["events"]}
    ins = ev[f"{T}SHARED_LOGGING_READ was granted INSERT on SHARED.LOGGING.TBL_LOGGING"]
    assert ins["kind"] == "gain" and ins["by"] == F + "DEPLOY" and "17" in {f["num"] for f in ins["findings"]} and ins["sensitive"]
    grp = ev[f"GRP_ANALYSTS was granted role {F}ANALYST"]
    assert grp["people"] == ["ANALYST_01", "ANALYST_02"] and "can now read" in grp["impact"]
    lost = ev[f"Role {T}SALES_CORE_WRITE was revoked from {F}MARKETING"]
    assert lost["kind"] == "lose" and lost["impact"] == "MARKETING_01 can no longer change SALES.CORE.TBL_CUSTOMER"
    own = ev[f"Role {T}SALES_MART_OWNER was revoked from {F}ANALYST"]
    assert own["impact"].startswith("Nobody loses") and own["findings"][0] | dict() == dict(num="4", severity="High",
                                                                                         title=a.RULES["4"][0], fixed=True)
    assert ev["ANALYST_02 became dormant (no login for 90 days)"]["kind"] == "user"
    assert any(e["kind"] == "risk" and "#7" in e["text"] and "ANALYST_02" in e["subjects"] for e in d["events"])
    assert d["counts"]["all"] == len(d["events"]) and d["counts"]["gain"] == 2 and d["counts"]["lose"] == 2 and d["high"] >= 1
    assert ("ANALYST_01", "SALES.MART.VW_CUSTOMER") in d["gained"] and ("MARKETING_01", "SALES.CORE.TBL_CUSTOMER") in d["lost"]
    assert not a.diff(a.fake())["events"]  # the same data: nothing changed
    a.build(a.only(a.fake(), "ENGINEER_01"))
    assert a.use_state()[0] and a.granted_used("ENGINEER_01")["rows"]
    a.build(dict(a.fake(), OBJECT_USE=None))
    assert a.use_state()[0] is False


def test_review_fixes():  # service users are never dormant on the new screens, search answers, row policies, subjects
    d = a.fake()
    for x in d["USER"]:
        if x["USER_NAME"] == "SVC_DEPLOY":
            x["LAST_SUCCESS_LOGIN"] = None
    a.build(d)
    assert a.status("SVC_DEPLOY") == "never" and not a.stale("SVC_DEPLOY") and a.stale("FIN_14") and a.stale("ANALYST_02")
    assert a.flow_group("SVC_DEPLOY", a.admin_users()) == "service"
    assert "SVC_DEPLOY" not in {f["grantee"] for f in a.rules_users()}  # the same test as rule 16
    a.build(a.fake())
    for n, u in [(x, True) for x in a.users] + [(r, False) for r in a.roles]:
        full = a.ladder_counts(a.access_objects(a.grants(n, u), u))
        assert a.reach_counts(n, u) == {k: full[k] for k in ("read", "change", "own")}, n
    assert list(a.row_tables()) == sorted(a.row_tables()) and len(a.row_tables()) == a.governance_kpis()["row_tables"] == 3
    assert a.row_tables()["FINANCE.REPORT.TBL_REVENUE"] == ["SHARED.GOVERNANCE.RAP_REGION"]
    prev, now = a.fake_previous(), a.fake()  # a new user named like a role: its events never match the role's subject
    r = F + "ANALYST"
    now["USER"].append(dict(now["USER"][0], USER_NAME=r, LAST_SUCCESS_LOGIN="2026-11-01 08:00"))
    now["USER_ROLE"].append(dict(USER_NAME=r, ROLE_NAME=F + "MARKETING", GRANTED_BY="SECURITYADMIN"))
    a.build(now)
    ev = a.diff(prev)["events"]
    mine = [e for e in ev if r + a.UTAG in e["subjects"]]
    assert mine and all(r not in e["subjects"] for e in mine if e["kind"] == "user")
    assert any(e["text"] == f"New user {r}" for e in mine) and any(r in e["subjects"] and r + a.UTAG not in e["subjects"] for e in ev)


if __name__ == "__main__":
    for t in (test_cache, test_user, test_depth_limit, test_can, test_role, test_object, test_depth, test_classes, test_sensitive,
              test_users, test_rules, test_fixes_clear, test_readonly, test_demo_db, test_kinds, test_cycle, test_public, test_graph,
              test_cap, test_graph_geometry, test_new_rules, test_fast, test_perf, test_group_graph, test_has_lacks,
              test_data_view, test_namespaces, test_graph_kit, test_summary, test_each, test_live, test_db_roles, test_builtin,
              test_whatif, test_whatif_indirect, test_ladder, test_who_has, test_nearest, test_graph_see_compare, test_plan, test_review_catalog_flow,
              test_usage_changes, test_review_fixes, test_pages):
        a.build(a.fake())
        t()
    if "ROLE_PREFIXES" not in os.environ:  # again with another naming: nothing may depend on F_/T_ literals
        env = {k: v for k, v in os.environ.items() if k != "BUILD_ROLES"} | {"ROLE_PREFIXES": "ZF_,ZT_"}
        subprocess.run([sys.executable, __file__], env=env, check=True)
    print("ok", os.environ.get("ROLE_PREFIXES", "F_,T_"))
