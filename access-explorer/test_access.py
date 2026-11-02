"""Walker tests on the fake data. Run: python test_access.py (no pytest needed)."""
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

import access as a
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
    assert len(g) == 11 and sum(r["count"] for r in g) == 13  # + INSERT on TBL_LOGGING (rule 17), PUBLIC warehouse
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
    assert [(r["privilege"], r["object"], r["holder"]) for r in one] == [("USAGE", "WH_SALES_XS", "PUBLIC")]
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
    assert m[0]["privs"]["SELECT"]["has"] and list(m[0]["privs"]) == a.valid_privs("TABLE")
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
    assert c("OWNERSHIP", "TABLE") == "own" and c("CREATE SCHEMA", "DATABASE") == "write"
    assert [c("USAGE", k) for k in ("PROCEDURE", "FUNCTION", "WAREHOUSE")] == ["use"] * 3
    assert c("OPERATE", "WAREHOUSE") == c("MONITOR", "WAREHOUSE") == "use" and c("SELECT", "FUTURE TABLE") == "read"
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
    assert [x["user"] for x in a.admin_people()] == ["ADMIN_01", "OPS_01"]
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
                 "13": 1, "14": 1, "15": 1, "16": 3, "17": 4}
    assert set(a.SEVERITY) == set(a.RULES) == {str(i) for i in range(1, 18)}
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
                   ("17", T + "SHARED_LOGGING_READ"), ("7", "ANALYST_02")]:
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
    """make_demo_db writes every table, TAG and POLICY included; snapshot() reads back what fake() holds."""
    import duckdb
    import make_demo_db
    con = duckdb.connect()
    d = a.fake()
    make_demo_db.write(con, d)

    def query(sql):
        cur = con.execute(sql)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    s = a.snapshot(query, "main")
    assert s["run"]["RUN_ID"] == "run-2" and s["run"]["SOURCES"]["tags"] == "ACCOUNT_USAGE"
    for t in a.TABLES:
        assert [{k: v for k, v in x.items() if k != "RUN_ID"} for x in s[t]] == d[t], t


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
    n = 0
    for where, (lanes, edges, notes), sel in page_graphs():
        for fit in (False, True):
            html = ui.lane_graph(lanes, edges, a.kind_of, "light", lambda x: "?n=" + x, sel, fit=fit, notes=notes)
            boxes, drawn, _ = geometry(html, (where, fit))
            n += 1
    assert n > 100
    # ENGINEER_01: T_SALES_CORE_READ once, at depth 2, also reached at depth 3 through the WRITE role (dotted, back edge)
    rows = a.grants("ENGINEER_01", True)
    lanes, edges, notes = a.down_graph("ENGINEER_01", rows, a.walk("ENGINEER_01", True))
    assert notes[T + "SALES_CORE_READ"][0] == "D2 · also D3"
    html = ui.lane_graph(lanes, edges, a.kind_of, "dark", lambda x: "?n=" + x, notes=notes)
    boxes, drawn, labels = geometry(html, "ENGINEER_01")
    back = [e for e in drawn if e[3]]
    assert [(e[0], e[1]) for e in back] == [(T + "SALES_CORE_WRITE", T + "SALES_CORE_READ")]
    assert "D3: ENGINEER_01 &gt; " + F + "ENGINEER &gt; " + T + "SALES_CORE_WRITE" in html
    assert ui.plabel(["INSERT", "UPDATE", "DELETE", "TRUNCATE"]) == "INSERT · UPDATE +2"


if __name__ == "__main__":
    for t in (test_user, test_depth_limit, test_can, test_role, test_object, test_depth, test_classes, test_sensitive,
              test_users, test_rules, test_fixes_clear, test_readonly, test_demo_db, test_kinds, test_cycle, test_public, test_graph,
              test_cap, test_graph_geometry):
        a.build(a.fake())
        t()
    if "ROLE_PREFIXES" not in os.environ:  # again with another naming: nothing may depend on F_/T_ literals
        env = {k: v for k, v in os.environ.items() if k != "BUILD_ROLES"} | {"ROLE_PREFIXES": "ZF_,ZT_"}
        subprocess.run([sys.executable, __file__], env=env, check=True)
    print("ok", os.environ.get("ROLE_PREFIXES", "F_,T_"))
