"""server.py on the fake data: every endpoint answers 200 with the keys of web/API.md. Run: python test_server.py"""
import importlib
from collections import Counter
import json
import os
import re
from contextlib import contextmanager
from urllib.parse import quote

os.environ["FAKE"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

c = TestClient(server.make_app(), base_url="http://localhost")
a = server.a
server.BACKGROUND = False  # a refresh answers when it is done; test_background runs it in its thread

USER = {"view", "user", "filters", "banners", "findings", "findings_total", "kpis", "account", "graph", "tabs",
        "roles", "multi", "can_read", "sensitive", "granted", "usage", "capped", "refs"}
ROLE = {"view", "role", "filters", "kpis", "scope_kpis", "banners", "findings", "readonly_writes", "account", "graph", "held_by",
        "holds", "tabs", "roles", "can_read", "capped", "refs"}
OBJECT = {"view", "object", "filters", "kpis", "admin_roles", "admin_users", "admin_total", "sensitivity", "matrix", "graph", "sees", "tabs", "grantees",
          "capped", "refs"}
GRAPH = {"title", "header", "level", "note", "full", "selected", "lanes", "nodes", "edges", "groups", "legend"}
NODE = {"id", "name", "label", "sub", "kind", "raw_kind", "type", "db", "schema", "lane", "depth", "badge", "tip", "marks",
        "rules", "action", "group"}
EDGE = {"id", "source", "target", "cls", "privs", "count", "back", "rules", "has", "lacks"}


def get(url, code=200):
    r = c.get(url)
    assert r.status_code == code, (url, r.status_code, r.text[:300])
    return r


def js(url, keys=()):
    d = get(url).json()
    assert set(keys) <= set(d), (url, set(keys) - set(d))
    return d


def graph_ok(g):
    assert GRAPH <= set(g), GRAPH - set(g)
    ids = {n["id"] for n in g["nodes"]}
    assert ids and all(NODE <= set(n) for n in g["nodes"])
    assert all(EDGE <= set(e) and e["source"] in ids and e["target"] in ids for e in g["edges"])
    assert all(n["lane"] < len(g["lanes"]) for n in g["nodes"])
    for gid, x in g["groups"].items():
        assert gid in ids and (x["nodes"] or x["lazy"]) and x["count"] >= len(x["nodes"]) - x["truncated"], gid
        assert not x["lazy"] or (g["src"] and not x["nodes"] and not x["edges"]), gid


def test_frame():
    m = js("/api/meta", ["mode", "source", "loaded", "run", "pages", "rules", "tokens", "limits", "type_icon", "mine", "mine_available"])
    assert m["mine_available"]
    assert m["loaded"] and m["source"] == "fake" and len(m["rules"]) == len(a.RULES)
    assert "database_role" in m["tokens"]["light"]["kind"]
    assert {p["key"] for p in m["pages"]} == set(server.PAGES)
    assert get("/api/mine").json()["loaded"] is False
    assert js("/api/meta?view=mine")["loaded"] is False
    get("/api/reload", 404)  # POST only
    assert c.post("/api/reload", json={"what": "page"}).json()["ok"]
    assert c.post("/api/reload", json={"what": "rebuild"}).json()["ok"] is False  # demo: no CALL
    f = js("/api/find?q=eng", ["items", "total"])
    assert f["items"] and {"id", "kind", "kind_label", "page", "sensitive"} <= set(f["items"][0])
    assert {x["kind"] for x in js("/api/find?q=SC_")["items"]} >= {"database_role"}
    for w in ("users", "roles", "objects", "types", "databases"):
        assert js(f"/api/list?what={w}")["items"], w
    get("/api/list?what=nope", 400)


def test_user():
    d = js("/api/user", USER)
    assert d["user"]["name"] == server.DEMO_USER and d["refs"]["kinds"]
    keys = [t["key"] for t in d["tabs"]]
    assert keys[-1] == "all" and {"granted", "database_roles", "usage", "warehouses", "read", "write"} <= set(keys), keys
    assert {"admin", "privileges", "public"} == set(d["account"])
    graph_ok(d["graph"])
    kinds = {n["kind"] for n in d["graph"]["nodes"]}
    assert {"user", "functional", "technical", "database_role", "object"} <= kinds, kinds
    assert "inherit_db" in {e["cls"] for e in d["graph"]["edges"]}
    assert any(x["rules"] for x in d["graph"]["nodes"])
    for t in keys:  # every tab has a small diagram
        g = js(f"/api/graph?of=user-tab&tab={t}")
        if g:
            graph_ok(g)
    js("/api/user?name=ADMIN_01&roles=default&depth=3&dataonly=0", USER)
    assert js("/api/user?name=ADMIN_01")["account"]["admin"]
    d = js("/api/user?name=SVC_DEPLOY", USER)  # many objects: combined boxes that expand
    assert d["graph"]["level"] in ("schema", "database") and d["graph"]["groups"]
    graph_ok(d["graph"])
    gid = next(iter(d["graph"]["groups"]))
    assert d["graph"]["groups"][gid]["drill"]["schema"] == gid
    graph_ok(js(f"/api/user?name=SVC_DEPLOY&schema={gid}")["graph"])
    big = js("/api/graph?of=user-tab&name=SVC_DEPLOY&tab=all")
    graph_ok(big)
    assert big["groups"] and all(x["kind"] == "database_group" for x in big["groups"].values())
    get("/api/user?name=NOPE", 404)


def test_paged():
    """Big users: privilege rows and Access entries a page at a time (CSV still complete), combined boxes sent empty
    and opened through graph?group=, the same members as sent whole."""
    whole = js("/api/graph?of=user&name=SVC_DEPLOY")
    server.LAZY = 0  # the fake data's boxes are small: every box lazy
    server.forget()
    try:
        lazy = js("/api/graph?of=user&name=SVC_DEPLOY")
        tab = js("/api/graph?of=user-tab&name=SVC_DEPLOY&tab=all")
        role = js(f"/api/role?name={a.FUNC}DEPLOY")["graph"]
        server.MAX_LANE = 2  # crowded role lanes fold into one lazy box each, its role names sent
        server.forget()
        lanes = js("/api/graph?of=user&name=SVC_DEPLOY")
        box = next(x for k, x in lanes["groups"].items() if k.startswith("lane:"))
        roles = js(f"/api/graph?of=user&name=SVC_DEPLOY&group=lane:{box['label'].split(':')[1]}")
        assert box["ids"] and [n["id"] for n in roles["nodes"]] == box["ids"] and box["count"] == len(box["ids"])
        drawn = {n["id"] for n in lanes["nodes"]}
        assert not drawn & set(box["ids"]) and all(e["source"] in drawn and e["target"] in drawn for e in lanes["edges"])
    finally:
        server.LAZY, server.MAX_LANE = 300, 24
        server.forget()
    for g in (lazy, tab, role):
        graph_ok(g)
        assert g["groups"] and all(x["lazy"] for x in g["groups"].values()) and g["src"]["name"]
        gid = next(iter(g["groups"]))
        x = js("/api/graph?" + "&".join(f"{k}={v}" for k, v in (g["src"] | {"group": gid}).items()))
        assert x["nodes"] and not x["lazy"] and x["count"] == g["groups"][gid]["count"], gid
    assert {k: [n["id"] for n in v["nodes"]] for k, v in whole["groups"].items()} == {
        k: [n["id"] for n in js(f"/api/graph?of=user&name=SVC_DEPLOY&group={k}")["nodes"]] for k in lazy["groups"]}
    get("/api/graph?of=user&name=SVC_DEPLOY&group=NOPE", 404)
    p = js("/api/privs?name=SVC_DEPLOY&tab=all&limit=5", ["rows", "total", "offset", "limit"])
    assert len(p["rows"]) == 5 < p["total"] and {"object", "access", "grants", "holder", "depth", "path", "more", "count"} <= set(p["rows"][0])
    nxt = js("/api/privs?name=SVC_DEPLOY&tab=all&limit=5&offset=5")["rows"]
    assert not {r["object"] for r in p["rows"]} & {r["object"] for r in nxt}
    srt = js("/api/privs?name=SVC_DEPLOY&tab=all&limit=500&sort=object&dir=-1")["rows"]
    assert [r["label"] for r in srt] == sorted((r["label"] for r in srt), reverse=True) and len(srt) == p["total"]
    q = js("/api/privs?name=SVC_DEPLOY&tab=all&q=finance")
    assert q["rows"] and q["total"] < p["total"] and all("finance" in str(r).lower() for r in q["rows"])
    csv_ = get("/api/privs.csv?name=SVC_DEPLOY&tab=all").text.strip().splitlines()
    assert csv_[0].startswith("Object,Type,Access") and len(csv_) == p["total"] + 1
    d = js("/api/access?user=SVC_DEPLOY&limit=3", ["objects", "total", "data", "offset", "limit", "runs", "powers"])
    assert len(d["objects"]) == 3 < d["total"] == d["data"]
    own = js("/api/access?user=SVC_DEPLOY&filter=own")
    assert own["total"] and all(o["level"] in ("own", "admin") for o in own["objects"])
    grp = js("/api/access?user=SVC_DEPLOY&group=schema")
    assert sum(grp["groups"].values()) == grp["total"]
    cv = get("/api/access.csv?user=SVC_DEPLOY&filter=own").text.strip().splitlines()
    assert len(cv) == own["total"] + 1 and "Findings" in cv[0]


def test_role():
    d = js("/api/role?name=F_ENGINEER", ROLE)
    graph_ok(d["graph"])
    assert d["held_by"]["rows"] and d["kpis"]["effective"]
    t = js("/api/role?name=T_SALES_CORE_READ", ROLE)
    assert t["holds"]["types"] and t["holds"]["types"][0]["rows"][0]["cells"]
    hs = js("/api/list?what=direct_holders&role=F_ENGINEER")["items"]  # the cut picker searches, no name list in the page
    assert "cuts" not in d["filters"] and len(hs) == d["filters"]["cuts_total"] and {i["kind"] for i in hs} >= {"user"}
    assert js(f"/api/role?name=F_ENGINEER&cut={hs[0]['id']}")["held_by"]["revoke"]
    assert js(f"/api/list?what=direct_holders&role=F_ENGINEER&q={hs[-1]['name']}&limit=5")["items"][0]["id"] == hs[-1]["id"]
    for r in a.roles:
        js(f"/api/role?name={r}", ROLE)
    dr = next(r for r in a.roles if a.role_kind(r) == "database")
    assert js(f"/api/role?name={dr}")["role"]["kind"] == "database_role"
    get("/api/role?name=NOPE", 404)
    graph_ok(js("/api/graph?of=role-tab&name=F_ENGINEER&tab=all"))


def test_object():
    for o in a.objects:
        js(f"/api/object?name={o}", OBJECT)
    t = next(x for x in a.objects if x in a.sensitive())
    d = js(f"/api/object?name={t}", OBJECT)
    assert d["sensitivity"] and d["matrix"]["rows"] and d["sees"] is not None
    m = d["matrix"]
    assert m["total"] == len(m["rows"]) and js(f"/api/object?name={t}&limit=1&m_offset=1")["matrix"]["rows"] == m["rows"][1:2]
    assert all(bool(r["admin_paths"]) == bool(r["admin"]) for r in m["rows"])
    g = d["admin_roles"]
    assert g and sum(x["total"] for x in g) == d["admin_total"] and all(x["paths"][0][-1] == x["role"] for x in g)
    assert [x["role"] for x in g] == sorted((x["role"] for x in g), key=lambda r: (server.ADMIN_ORDER + [r]).index(r))
    assert all(len(x["first"]) == min(3, x["users"]) and len(x["paths"]) <= server.MAX_ADMIN_PATHS for x in g)
    graph_ok(d["graph"])
    assert d["tabs"][-1]["key"] == "all"
    js(f"/api/object?name={t}&priv=SELECT&users=1&active=1", OBJECT)
    get("/api/object?name=NOPE", 404)


def test_object_admin_rows():
    """A user who reaches the object only through an admin role gets the privileges that role's real links give, with
    depth and shortest path; only cells worth a look are flagged."""
    o = "FINANCE.REPORT.TBL_REVENUE"
    rows = {r["user"]: r for r in js(f"/api/object?name={o}")["matrix"]["rows"]}
    r = rows["OPS_01"]
    assert r["admin"] == ["SYSADMIN"] and not r["real"] and r["depth"] == 2 and r["paths"] > 0
    assert r["path"][:3] == ["OPS_01", "SYSADMIN", a.TECH + "FINANCE_REPORT_OWNER"] and r["path"][-1] == o
    c = r["cells"]["SELECT"]
    assert c["has"] and c["admin"] == "SYSADMIN" and c["depth"] == 2 and "via SYSADMIN" in c["title"]
    assert set(r["flags"]) == {"OWNERSHIP", "INSERT", "UPDATE", "DELETE", "TRUNCATE"}  # a person writes sensitive data
    assert not rows["SVC_DEPLOY"]["flags"].keys() & {"OWNERSHIP", "INSERT"}  # a service user is not flagged
    assert rows["FIN_14"]["flags"]["status"].startswith("Disabled")  # disabled and can still read it
    assert all(not x["cells"][k]["admin"] for x in rows.values() if x["real"] for k in x["cells"])


def test_big_lanes():
    """Big accounts: the people lane of the Object, Role and Access graph pages folds into one lazy box opened through
    graph?group=; grantees, held by and role privileges page on the server (CSV complete); the map's objects roll up
    per database and a box drawn later gets its detail through node=."""
    t, r = "SALES.CORE.TBL_CUSTOMER", f"{a.FUNC}ENGINEER"
    server.LAZY, server.MAX_LANE = 0, 1
    server.forget()
    try:
        for url, of in ((f"/api/object?name={t}", f"of=object&name={t}"), ("/api/role?name=PUBLIC", "of=role&name=PUBLIC"),
                        (f"/api/map?table={t}&same=0", f"of=map&table={t}&same=0")):
            g = js(url)["graph"]
            graph_ok(g)
            box = g["groups"]["lane:0:people"]
            assert box["lazy"] and box["noun"] == "people" and box["count"] == len(box["ids"]) > 1, url
            assert not {n["id"] for n in g["nodes"]} & set(box["ids"])
            x = js(f"/api/graph?{of}&group=lane:0:people")
            assert sorted(n["id"] for n in x["nodes"]) == sorted(box["ids"]) and all(n["kind"] == "user" for n in x["nodes"])
        m = js("/api/map?role=PUBLIC&same=0")
        n = js(f"/api/map?role=PUBLIC&same=0&node={m['graph']['groups']['lane:0:people']['ids'][0]}")["detail"]
        assert len(n) == 1 and next(iter(n.values()))["leads_count"]
    finally:
        server.LAZY, server.MAX_LANE = 300, 24
        server.forget()
    u = js("/api/map?user=SVC_DEPLOY")["graph"]
    dbs = [x for x in u["groups"].values() if x["kind"] == "database_group"]
    assert dbs and sum(x["count"] for x in dbs) > a.MAX_OBJECTS
    o = js(f"/api/object?name={t}")
    rows = js(f"/api/grantees?name={t}&limit=2")
    assert len(rows["rows"]) == 2 and rows["total"] == o["grantees"]["total"] == o["tabs"][-1]["count"]
    assert js(f"/api/grantees?name={t}&limit=2&offset=2")["rows"][0] not in rows["rows"]
    gs = js(f"/api/grantees?name={t}&by=groups&limit=500")
    assert sum(x["count"] for x in gs["rows"]) == gs["users"] == o["grantees"]["users"] and gs["roles"] == o["grantees"]["roles"]
    assert len(get(f"/api/grantees.csv?name={t}").text.strip().splitlines()) == rows["total"] + 1
    d = js(f"/api/role?name={r}")
    h = js(f"/api/held?name={r}&tab=users&limit=1")
    assert len(h["rows"]) == 1 and h["total"] == d["held_by"]["users"] and h["rows"][0]["kind"] == "user"
    assert js(f"/api/held?name={r}")["total"] == d["held_by"]["total"] == d["held_by"]["users"] + d["held_by"]["roles"]
    assert len(get(f"/api/held.csv?name={r}").text.strip().splitlines()) == d["held_by"]["total"] + 1
    pv = js(f"/api/privs?name={r}&of=role&tab=all&limit=3")
    assert len(pv["rows"]) == 3 < pv["total"] and pv["total"] == len({x["object"] for x in a.grants(r)})
    assert len(get(f"/api/privs.csv?name={r}&of=role&tab=all").text.strip().splitlines()) == pv["total"] + 1


def test_crowded_lane():  # a lane over MAX_LANE people folds into one box even when the graph is small (276 users once)
    us = [f"PERSON_{i:03}" for i in range(server.MAX_LANE + 6)]
    g = server.build_graph("t", [("Users", us), ("Role", ["F_X"])], [(u, "F_X") for u in us], sizes=dict.fromkeys(us, 1),
                           selected="F_X")
    ids = [n["id"] for n in g["nodes"]]
    assert len(ids) < 5 and not set(us) & set(ids), ids  # the people box and the role, not 30 boxes


def test_access_type():  # Access list: object type filter, the types present with counts
    d = js("/api/access?user=ENGINEER_01")
    ts = {t["type"]: t["n"] for t in d["types"]}
    assert ts["VIEW"] >= 1 and sum(ts.values()) == d["total"]
    v = js("/api/access?user=ENGINEER_01&otype=VIEW")
    assert v["total"] == ts["VIEW"] and {o["type"] for o in v["objects"]} == {"VIEW"}


def test_check_narrow():  # No: a Streamlit app asks USAGE; the narrowest grant first, the ways to own it apart
    d = js("/api/check?name=ANALYST_01&obj=SALES.MART.ST_CUSTOMER_LOOKUP&near=1")
    assert d["verdict"] == "no" and d["ask_priv"] == "USAGE" and "USAGE" in d["privileges"]
    assert d["narrow"]["role"] == a.TECH + "SALES_MART_READ" and "GRANT USAGE ON STREAMLIT" in d["narrow"]["change"]["sql"]
    assert d["nearest_own"] and all(n["path"][-1] == d["object"] for n in d["nearest_own"])
    assert js("/api/check?name=ANALYST_01&obj=SALES.MART.ST_CUSTOMER_LOOKUP&priv=OWNERSHIP&near=1")["nearest_own"] is None


def test_check_inside():  # Can they? on a database or schema: each table and view inside, read / DML / DDL; USAGE chips
    t = js("/api/check?name=HR_01&obj=SALES.CORE.TBL_CUSTOMER")
    assert t["inside"] is None and [(u["type"], u["held"]) for u in t["usage"]] == [("DATABASE", False), ("SCHEMA", False)]
    d = js("/api/check?name=HR_01&obj=SALES")["inside"]  # no reach into SALES: every object cannot
    assert d["mode"] == "read" and d["total"] == d["cannot"] > 1 and d["can"] == 0 and all(not r["ok"] for r in d["rows"])
    e = js("/api/check?name=ENGINEER_01&obj=SALES.CORE&inside=dml&show_in=can")["inside"]
    assert e["can"] >= 1 and all(r["ok"] and not r["missing"] for r in e["rows"]) and "CREATE TABLE" in e["create"]
    o = js("/api/check?name=ENGINEER_01&obj=SALES.CORE&inside=ddl")["inside"]
    assert o["can"] < e["can"] or all(r["missing"] == ["OWNERSHIP"] for r in o["rows"] if not r["ok"])  # DDL needs ownership
    q = js("/api/check?name=HR_01&obj=SALES&in_q=zz_no_such")["inside"]
    assert q["matched"] == 0 and q["rows"] == [] and q["total"] == d["total"]


def test_check():
    d = js("/api/check", ["answer", "paths", "graph", "privileges", "refs", "options", "nearest"])
    assert d["answer"]["yes"] and d["paths"]
    graph_ok(d["graph"])
    no = js("/api/check?name=ANALYST_01&obj=HR.PEOPLE.TBL_EMPLOYEE&priv=DELETE")
    assert no["answer"]["how"] in ("none", "paths", "owner", "admin")
    for u in a.users:
        js(f"/api/check?name={u}", ["verdict", "held", "lanes", "cut", "cuts", "nearest", "layers", "roles_count"])
    get("/api/check?name=NOPE", 404)
    y = js("/api/check?name=ENGINEER_01&obj=HR.PEOPLE.TBL_EMPLOYEE")
    assert y["verdict"] == "yes" and y["lanes_total"] == 2 and y["cut"] == [a.FUNC + "ENGINEER", "HR.SC_W_PEOPLE"]
    assert len(y["cuts"]) == 2 and y["cuts"][0]["people"] == ["ENGINEER_01"] and y["cuts"][0]["lost"] < y["cuts"][1]["lost"]
    assert {x["privilege"] for x in y["held"] if x["held"]} == {"SELECT", "INSERT", "UPDATE"} and y["approver"] == "HR data owner"
    assert js("/api/check?name=FIN_09&obj=HR.PEOPLE.TBL_EMPLOYEE&do=read")["nearest"] is None  # the slow part: on its tab
    n = js("/api/check?name=FIN_09&obj=HR.PEOPLE.TBL_EMPLOYEE&do=read&near=1")
    assert n["verdict"] == "no" and n["priv"] == "SELECT" and n["nearest"] and not n["lanes"] and n["roles_count"] > 5
    assert not any(x["held"] for x in n["held"]) and n["nearest"][0]["path"][0] == "FIN_09"
    p = js("/api/check?name=MARKETING_01&obj=FINANCE.REPORT.TBL_REVENUE")
    assert p["verdict"] == "partly" and [x["step"] for x in p["layers"]] == ["Grant", "Rows", "Columns"]
    assert p["layers"][1]["result"] == "No rows" and "RAP_REGION" in p["layers"][1]["reason"]
    m, e = a.FUNC + "MARKETING", "HR.PEOPLE.TBL_EMPLOYEE"  # a role as the subject
    pr = js(f"/api/check?role={m}&obj=FINANCE.REPORT.TBL_REVENUE")  # the spec's mockup: Partly for F_MARKETING
    assert pr["verdict"] == "partly" and pr["subject"]["user"] is False and pr["layers"][1]["result"] == "No rows"
    assert pr["lanes"][0]["path"][0] == m and pr["use_role"] == m and pr["status"] is None and pr["cuts"]
    assert pr["cuts"][0]["people"] == ["MARKETING_01"] and "FROM ROLE " + m in pr["cuts"][0]["sql"]
    ry = js(f"/api/check?role={a.FUNC}ENGINEER&obj={e}")
    assert ry["verdict"] == "yes" and ry["paths"][0]["path"][0] == a.FUNC + "ENGINEER" and ry["graph"]
    rn = js(f"/api/check?role={a.FUNC}ANALYST&obj={e}&do=read&near=1")
    assert rn["verdict"] == "no" and rn["nearest"] and all(x["to"] == a.FUNC + "ANALYST" and not x["to_user"] for x in rn["nearest"])
    assert js(f"/api/check?name={m}&obj={e}")["subject"]["user"] is False  # Home's "can F_MARKETING read ..."
    assert js("/api/check?user=ENGINEER_01")["subject"]["user"] is True
    adm = js(f"/api/check?role=SYSADMIN&obj={e}")
    assert adm["answer"]["how"] in ("admin", "paths", "owner") and adm["verdict"] != "no"
    get("/api/check?role=NOPE", 404)
    sb = "DW.SANDBOX.TBL_SANDBOX_01"  # fake: the read role has no USAGE on its schema
    b = js(f"/api/check?name=DW_BI_01&obj={sb}&priv=SELECT", ["blocked", "unblock", "warehouses"])
    assert b["verdict"] == "blocked" and not b["answer"]["yes"] and b["answer"]["how"] == "blocked" and b["lanes_total"]
    assert b["answer"]["title"] == "Has SELECT, but no USAGE on schema DW.SANDBOX: blocked" and b["read"] is None
    assert b["blocked"] == [dict(type="SCHEMA", name="DW.SANDBOX")] and "GRANT USAGE ON SCHEMA DW.SANDBOX TO DATABASE ROLE DW.SC_R_SANDBOX;" == b["unblock"]["sql"]
    assert "WH_SALES_XS" in b["warehouses"]["names"] and b["warehouses"]["total"] >= 1 and not b["warehouses"]["admin"]
    assert js(f"/api/check?name=DW_BI_01&obj={sb}")["verdict"] == "blocked"  # every privilege held: blocked as well
    assert js(f"/api/check?role=GRP_DW_READERS&obj={sb}&priv=SELECT")["verdict"] == "blocked"
    ok = js(f"/api/check?name=DW_DEV_01&obj={sb}&priv=SELECT")
    assert ok["verdict"] == "yes" and ok["blocked"] == [] and ok["unblock"] is None
    assert js(f"/api/check?name=OPS_01&obj={sb}&priv=SELECT")["warehouses"]["admin"]
    for r in a.roles:
        js(f"/api/check?role={r}", ["verdict", "held", "lanes", "cuts", "nearest", "subject"])


def test_request():  # screen 15: suggested role, approver, read / change, already held, the role picked on Can they?
    keys = ["user", "object", "type", "need", "privileges", "level", "has", "asked", "suggestions", "approver", "owners", "refs"]
    d = js("/api/request?name=FIN_09&obj=SALES.CORE.TBL_CUSTOMER", keys)
    assert d["need"] == "read" and d["privileges"] == ["SELECT"] and not d["has"] and d["level"] is None
    assert d["suggestions"][0]["role"] == a.FUNC + "ANALYST" and d["suggestions"][0]["holders"] >= 1
    w = js("/api/request?name=FIN_09&obj=HR.PEOPLE.TBL_EMPLOYEE&need=change&role=HR.SC_R_PEOPLE&to=GRP_EMEA_ALL")
    assert w["privileges"] == ["INSERT", "UPDATE"] and w["approver"] == "HR data owner"
    assert {k: w["asked"][k] for k in ("role", "kind", "to")} == dict(role="HR.SC_R_PEOPLE", kind="database_role", to="GRP_EMEA_ALL")
    assert w["asked"]["people"] > 10 and w["asked"]["broad"] and w["subject"]["kind"] == "user"
    h = js("/api/request?name=ENGINEER_01&obj=HR.PEOPLE.TBL_EMPLOYEE")
    assert h["has"] and h["suggestions"] == [] and h["level"] == "change"
    assert js("/api/request?name=FIN_09&obj=SALES.CORE.TBL_CUSTOMER&role=NOPE")["asked"] is None
    assert js("/api/request?name=FIN_09")["object"] is None  # never a guessed object: the page asks for one
    js("/api/request?obj=SALES.CORE.TBL_CUSTOMER", keys)
    get("/api/request?name=NOPE", 404)
    get("/api/request?obj=NOPE", 404)
    m = a.FUNC + "MARKETING"  # a role as the subject: GRANT ROLE x TO ROLE y, everyone holding it gets it too
    r = js(f"/api/request?for_role={m}&obj=HR.PEOPLE.TBL_EMPLOYEE", keys)
    assert r["user"] == m and r["subject"] == dict(kind="functional", name=m, id=m, user=False, people=1, database=None) and not r["has"]
    assert r["database"] == "HR"
    dr = js("/api/request?for_role=DW.SC_C_CORE&obj=HR.PEOPLE.TBL_EMPLOYEE")  # a database role: its database, no suggestions
    assert dr["subject"]["database"] == "DW" and dr["subject"]["kind"] == "database_role" and dr["suggestions"] == []
    dc = js("/api/check?role=DW.SC_C_CORE&obj=DW")
    assert dc["verdict"] == "yes" and dc["use_role"] is None  # USE ROLE can't take a database role
    assert r["suggestions"] and all(x["role"] != m and m not in a.best_paths(x["role"]) for x in r["suggestions"])
    t = js(f"/api/request?for_role={m}&obj=HR.PEOPLE.TBL_EMPLOYEE&role={a.TECH}HR_PEOPLE_READ")
    assert t["asked"] is None or t["asked"]["to"] == m
    assert js(f"/api/request?name={m}&obj=HR.PEOPLE.TBL_EMPLOYEE")["subject"]["user"] is False  # Home's typed question
    get("/api/request?for_role=NOPE", 404)
    # the grant SQL comes from access.with_sql, with the role kinds: the page writes none
    assert d["suggestions"][0]["change"]["sql"].startswith(f"GRANT ROLE {a.FUNC}ANALYST TO USER FIN_09;")
    assert w["asked"]["change"]["sql"].startswith("GRANT DATABASE ROLE HR.SC_R_PEOPLE TO ROLE GRP_EMEA_ALL;") and w["asked"]["change"]["roleDb"]
    assert r["suggestions"][0]["change"]["sql"].startswith(f"GRANT ROLE {r['suggestions'][0]['role']} TO ROLE {m};")


def test_sensitive_rules_review():
    d = js("/api/sensitive", ["state", "kpis", "objects", "readers", "filters", "refs"])
    assert "compare" not in d  # Compare (scope=sensitive) does it, with pickers that search the server
    assert d["state"] == "ok" and d["objects"] and d["readers"]
    assert d["objects_total"] == len(d["objects"]) == d["kpis"]["objects"] and d["readers_total"] == len(d["readers"])
    p = js("/api/sensitive?limit=2&r_offset=2&o_offset=1")  # one page each; limit=0 every row (the CSV)
    assert len(p["readers"]) == 2 and p["readers"] == d["readers"][2:4] and p["objects"] == d["objects"][1:3]
    assert p["readers_offset"] == 2 and js("/api/sensitive?limit=0&r_offset=999")["readers"] == d["readers"]
    assert all(set(o["readers"]) == {"active", "dormant", "service", "admin"} for o in d["objects"])
    js(f"/api/sensitive?people=1&db={d['filters']['dbs'][0]}")
    r = js("/api/rules", ["counts", "per_rule", "findings", "total", "admins", "admins_total", "rows_unknown", "refs"])
    assert r["total"] and r["admins"] and r["counts"]["High"] and r["counts"]["Critical"] == 5 and r["admins_total"] == len(r["admins"])
    assert len(r["per_rule"]) == len(a.RULES) and r["filters"]["sev"] == "Critical"  # the worst severity by default
    every = js("/api/rules?sev=all")
    assert {f["num"] for f in every["findings"]} == {g["key"] for g in every["groups"]} == {k for k, v in r["per_rule"].items() if v}
    js("/api/rules?sev=High&rule=4")
    f = r["findings"][0]
    assert f["grantee"] and {"id", "num", "severity", "what", "impact", "paths", "people_total", "fix"} <= set(f) and "iac" not in f
    csv = get("/api/rules.csv")
    assert csv.headers["content-type"].startswith("text/csv") and "Rule checks" in csv.text
    rv = js("/api/review?db=*&part=all", ["filters", "kpis", "counts", "part", "total", "offset", "limit", "rows", "refs"])
    assert rv["rows"] and rv["kpis"]["rows"] == rv["counts"]["all"] == rv["total"] > rv["limit"] == len(rv["rows"])
    every = [r for k in range(0, rv["total"], 40) for r in js(f"/api/review?db=*&part=all&sort=u&offset={k}&limit=40")["rows"]]
    assert len(every) == rv["total"] and [r["user"].lower() for r in every] == sorted(r["user"].lower() for r in every)
    assert len({json.dumps(r, sort_keys=True) for r in every}) == rv["total"]  # paged: every row once
    full = lambda r: f'{r["database"]}.{r["schema"]}.{r["object"]}'.lower()
    back = js("/api/review?db=*&part=all&sort=o&dir=-1&limit=5")["rows"]
    assert [full(r) for r in back] == sorted(map(full, every))[::-1][:5]
    one = js("/api/review?db=*&part=all&q=analyst_01 customer&limit=1000")
    assert one["rows"] and one["total"] == len(one["rows"]) < rv["total"]
    assert all("ANALYST_01" in r["path"] and "CUSTOMER" in full(r).upper() for r in one["rows"])
    sens = js("/api/review?db=*")
    assert sens["part"] == "sens" and sens["total"] == sens["counts"]["sens"] and all(r["sensitive"] for r in sens["rows"])
    assert "dbs" not in rv["filters"]  # the database picker searches /api/list?what=databases
    db = js("/api/list?what=databases&limit=1")["items"][0]["id"]
    assert js(f"/api/review?db={db}&hideusage=0")["kpis"]["hidden_usage"] == 0
    cv = get(f"/api/review.csv?db={db}")
    assert "access_review_" in cv.headers["content-disposition"] and "Keep/Revoke" in cv.text
    n = js(f"/api/review?db={db}&part=all&hideusage=0")["total"]
    assert len(cv.text.strip().splitlines()) == n + 6  # every row, after 4 head lines, a blank one and the columns
    get("/api/review?db=NOPE", 404)


def test_load_on_click():
    """SOURCE=direct on Snowflake: no page reads the shared data until "Load shared data" (reload what=load)."""
    old, reads = (server.MODE, server.DIRECT, server.read_shared, server.cache.HOURS), []
    server.MODE, server.DIRECT = "snowflake", True
    server.read_shared = lambda: reads.append(1) or a.fake()
    server.cache.HOURS = 0  # memory only: a .cache/ file from an earlier run would count as loaded
    server.cache.MEM.pop(server.KEY, None)
    try:
        assert js("/api/meta")["error"]["detail"] == "shared_not_loaded" and not reads
        assert c.get("/api/user").json()["detail"] == "shared_not_loaded" and not reads
        assert c.post("/api/reload", json={"what": "load"}).json()["ok"] and reads == [1]
        assert js("/api/meta")["loaded"] and "error" not in js("/api/meta") and reads == [1]  # kept, not read again
    finally:
        server.MODE, server.DIRECT, server.read_shared, server.cache.HOURS = old
        server.cache.MEM.pop(server.KEY, None)


def test_mine():
    a.INSIDE = True  # inside Snowflake: the owner's rights, so no My access
    try:
        r = c.post("/api/mine/load")
        assert r.status_code == 409 and r.json()["detail"] == "mine_unavailable", r.text
        assert not js("/api/meta")["mine_available"]
    finally:
        a.INSIDE = False
    get("/api/user?view=mine", 409)
    assert c.get("/api/user?view=mine").json()["detail"] == "mine_not_loaded"
    r = c.post("/api/mine/load")
    assert r.status_code == 200 and r.json()["loaded"] and "ae_sid" in r.cookies
    assert "HttpOnly" in r.headers["set-cookie"] and "SameSite=strict" in r.headers["set-cookie"]
    assert get("/api/mine").json()["loaded"]
    d = js("/api/user?view=mine&name=ignored", USER)
    assert d["view"] == "mine" and d["user"]["name"] == server.DEMO_USER and d["can_read"] is None
    rules = js("/api/rules?view=mine", ["findings", "scope"])  # rule checks also in My access
    assert rules["scope"] == "mine"
    for u in ("role?name=F_ENGINEER", "object", "check", "sensitive", "find?q=e", "graph?of=user"):
        sep = "&" if "?" in u else "?"
        get(f"/api/{u}{sep}view=mine")
    get("/api/review?view=mine", 400)
    assert js("/api/meta?view=mine")["loaded"]
    other = TestClient(server.make_app(), base_url="http://localhost")  # another browser: nothing loaded
    assert other.get("/api/user?view=mine").status_code == 409


def test_spa():
    assert c.get("/api/nope").status_code == 404
    assert c.get("/some/page").status_code in (200, 404)


def test_streamlit_bridge():  # the React app inside Streamlit gets the same answers as over HTTP (st_react.app)
    import st_react
    ans = lambda url, body=None, sid=None: st_react.answer("POST" if body is not None else "GET", url, body, sid)
    st, m, _ = ans("/api/meta?view=shared")
    assert st == 200 and m["loaded"] and {p["key"] for p in m["pages"]} == set(server.PAGES)
    name = m["default_user"]
    assert ans(f"/api/user?name={name}")[1] == c.get(f"/api/user?name={name}").json()
    assert ans("/api/role?name=PUBLIC")[1]["role"]["name"] == "PUBLIC"
    assert ans("/api/nope")[0] == 404 and ans("/api/user?name=NOBODY_X")[0] == 404
    assert ans("/api/nope.csv")[0] == 404 == c.get("/api/nope.csv").status_code
    assert ans("/api/review.csv?db=*")[1].startswith(c.get("/api/review.csv?db=*").text[:40])
    assert ans("/api/reload", {"what": "page"})[1]["ok"]
    st, mine, sid = ans("/api/mine/load", {})
    assert st == 200 and sid and ans("/api/mine", sid=sid)[1]["loaded"]
    st, _, sid2 = ans("/api/mine/load", {}, sid)  # Load My access again: the previous data set is dropped, as locally
    assert st == 200 and sid2 != sid and sid not in server.MINE and sid2 in server.MINE


def test_find_lock_free():  # search as you type never waits for a slow page once a data set has its name index
    import threading
    import time
    first = js("/api/find?q=ANALYST")
    assert first["items"][0]["answer"] and all(not x["answer"] for x in first["items"][server.ANSWER_TOP:])
    hold, done = threading.Event(), threading.Event()

    def slow_page():
        with server.LOCK:
            hold.set()
            done.wait(20)
    t = threading.Thread(target=slow_page)
    t.start()
    hold.wait()
    t0 = time.time()
    try:
        r = server.serve("find", {"view": "shared", "q": "ENGINEER"})
    finally:
        done.set()
        t.join()
    assert time.time() - t0 < 5 and r["items"] and r["items"][0]["name"].startswith("ENGINEER") and r["partial"]
    again = server.serve("find", {"view": "shared", "q": "ENGINEER"})  # LOCK free: the answer lines come now
    assert "partial" not in again and again["items"][0]["answer"]
    assert a.search("ANALYTS_01", [f"N{i}" for i in range(a.FUZZY_MAX + 1)]) == []  # no fuzzy pass over a big account
    assert "ANALYST_01" in a.search("ANALYTS_01", a.users)  # a small one keeps it


def test_findings_link():  # a User / Role page's "All N on Risks & fixes" lists the same N
    for u in a.users:
        d = js(f"/api/user?name={u}")
        if d["findings_total"] > sum(x["grantee"] == u for x in server.S["rows"]):  # some come from its roles
            break
    r = js(f"/api/rules?grantee={u}&of=user&sev=all")
    assert r["findings_total"] == d["findings_total"] and r["filters"]["of"] == "user"
    role = next(x["grantee"] for x in server.S["rows"] if x["kind"] != "user")
    assert js(f"/api/rules?grantee={role}&of=role&sev=all")["findings_total"] == js(f"/api/role?name={role}")["findings_total"]


def test_review_csv_cap():  # every database of a big account is millions of rows: one database or schema instead
    d = js("/api/review?db=*")
    assert d["csv_max"] == server.REVIEW_CSV_MAX and get("/api/review.csv?db=*").text
    old, server.REVIEW_CSV_MAX = server.REVIEW_CSV_MAX, d["kpis"]["rows"] - 1
    try:
        assert "pick one database" in get("/api/review.csv?db=*", 400).json()["message"]
    finally:
        server.REVIEW_CSV_MAX = old


def test_whatif():
    from urllib.parse import quote
    ch = quote(json.dumps([{"op": "drop_role", "role": a.FUNC + "ANALYST"}]))
    d = js(f"/api/whatif?changes={ch}", ["changes", "summary", "counts", "users", "objects", "roles", "findings", "iac", "sql", "refs",
                                          "groups", "impact", "lost_privs", "kept_privs"])
    assert d["counts"]["users"] and "DROP ROLE" in d["sql"] and "lost_rows" not in d["users"][0]  # per person: counts only
    assert sum(g["n"] for g in d["groups"]) == d["users_total"] == len(d["users"]) and d["groups"][0]["text"]
    assert d["lost_privs"] == sum(u["lost"] for u in d["users"]) and d["impact"][0]["people"] >= d["impact"][-1]["people"]
    assert all(d[k + "_total"] >= len(d[k]) for k in ("findings", "objects", "roles", "impact", "groups", "users"))
    u = js(f"/api/whatif?changes={ch}&user={d['users'][0]['user']}")["user"]  # one person's rows, on open
    assert u["lost_rows"] and u["objects"] == d["users"][0]["objects"]
    get(f"/api/whatif?changes={ch}&user=NOPE", 404)
    long = json.dumps([{"op": "drop_role", "role": a.FUNC + "ANALYST"}] * 1500)  # a plan too long for a URL comes as a POST
    assert len(long) > 40000 and c.post("/api/whatif", json={"changes": long}).json()["counts"] == d["counts"]
    assert "What if" in c.post("/api/whatif.csv", json={"changes": long}).text
    assert c.post("/api/whatif", content="[]", headers={"Content-Type": "application/json"}).status_code == 400
    assert "What if" in get(f"/api/whatif.csv?changes={ch}").text
    get("/api/whatif?changes=nope", 400)
    hs = js(f"/api/list?what=role_holders&role={a.TECH}SALES_CORE_READ")["items"]
    assert hs and {i["type"] for i in hs} == {"direct", "inherited"} and hs[0]["type"] == "direct", hs[:3]
    us = js(f"/api/list?what=user_holders&role={a.TECH}SALES_CORE_READ")["items"]
    assert us and all(i["kind"] == "user" for i in us)
    get("/api/whatif?changes=" + quote(json.dumps([{"op": "drop_role", "role": "NOPE"}])), 400)


READ_ONLY = re.compile(r"^\s*(SELECT|WITH|SHOW|DESC(RIBE)?|USE SECONDARY ROLES ALL|CALL \S+\.SP_ACCESS_SNAPSHOT\()", re.I)


@contextmanager
def snowflake(answer, direct=False, where="D.S"):
    """server.py as on Snowflake, every statement through a recording connection (sf.rows) answered by answer(sql)."""
    sent = []

    class Cur:
        def execute(self, sql, **kw):  # kw: the STATEMENT_TIMEOUT statement parameter
            sent.append(sql)
            self.got = answer(sql)
            self.description = [(k,) for k in (self.got[0] if self.got else {})] or None

        def fetchall(self):
            return [tuple(r.values()) for r in self.got]

    conn = type("Conn", (), {"cursor": lambda self: Cur(), "close": lambda self: None})()
    old = server.MODE, server.DIRECT, server.WHERE, server.connect, server.cache.HOURS
    server.MODE, server.DIRECT, server.WHERE, server.connect = "snowflake", direct, where, lambda: conn
    server.cache.HOURS = 0  # memory only: no test file in .cache/
    server.cache.MEM.pop(server.KEY, None)
    server.cache.OLD.pop(server.KEY, None)
    try:
        yield sent
    finally:
        server.MODE, server.DIRECT, server.WHERE, server.connect, server.cache.HOURS = old
        server.cache.MEM.pop(server.KEY, None)
        server.cache.OLD.pop(server.KEY, None)


def test_read_only():
    """Every statement the app sends, recorded at the connection (sf.rows): reads only, plus the snapshot CALL. The fake
    answers every read, so each load runs to the end (200) and all its statements are checked."""
    import test_access
    d = a.fake()
    show, _ = test_access.fake_snowflake(d, True)
    me = d["USER_ROLE"][0]["USER_NAME"]
    mine = [x["ROLE_NAME"] for x in d["USER_ROLE"] if x["USER_NAME"] == me]
    table = re.compile(r"SELECT \* EXCLUDE \(RUN_ID\) FROM D\.S\.TBL_ACCESS_(\w+) WHERE")

    def answer(sql):
        if "SP_ACCESS_SNAPSHOT" in sql:
            return [{"R": json.dumps({"status": "OK", "notes": {}})}]
        if ".TBL_ACCESS_RUN " in sql:
            return [{"RUN_ID": "r1", "FINISHED_AT": "2026-11-03 10:00", "SOURCES": "{}", "NOTES": "{}"}]
        if table.match(sql):
            return [dict(x) for x in d.get(table.match(sql)[1]) or []]
        if sql.startswith("SELECT CURRENT_USER()"):
            return [{"U": me, "D": None, "R": json.dumps(mine)}]
        if sql.startswith("SHOW GRANTS TO USER"):
            return [{"role": x} for x in mine]
        try:
            return show(sql)
        except (AssertionError, RuntimeError):  # a view the fake does not know or refuses: no rows
            return []
    sent, old = [], os.environ.get("MY_ACCESS")
    os.environ["MY_ACCESS"] = "1"  # a key pair or ALLOWED_HOSTS in .env must not turn My access off here
    try:
        for direct in (True, False):
            with snowflake(answer, direct) as got:
                for url, body in (("/api/reload", {"what": "load"}), ("/api/reload", {"what": "rebuild"}),
                                  ("/api/mine/load?fresh=1", None)):
                    r = c.post(url, json=body)
                    assert r.status_code == 200, (direct, url, r.text[:300])
                assert any(s.startswith("SELECT CURRENT_USER()") for s in got)
                assert direct or any(table.match(s) for s in got)
                sent += got
    finally:
        os.environ.pop("MY_ACCESS") if old is None else os.environ.update(MY_ACCESS=old)
        for m in server.MINE.values():
            server.cache.MEM.pop(m["cache_key"], None)
        server.MINE.clear()
    assert any("SP_ACCESS_SNAPSHOT" in s for s in sent)
    assert all(READ_ONLY.match(s) for s in sent), [s for s in sent if not READ_ONLY.match(s)][:5]


def test_same_run():
    """Objects mode: a reload while the latest OK run is the one held keeps the held data after one small query, also
    memory only (CACHE_HOURS=0, as inside Snowflake); a new run reads every table again."""
    d, run = a.fake(), ["r1"]
    table = re.compile(r"SELECT \* EXCLUDE \(RUN_ID\) FROM D\.S\.TBL_ACCESS_(\w+) WHERE RUN_ID = '(\w+)'")

    def answer(sql):
        if ".TBL_ACCESS_RUN " in sql:
            return [{"RUN_ID": run[0], "FINISHED_AT": "2026-11-03 10:00", "SOURCES": "{}", "NOTES": "{}"}]
        m = table.match(sql)
        assert m and m[2] == run[0], sql
        return [dict(x) for x in d.get(m[1]) or []]
    with snowflake(answer) as sent:
        first = server.load_shared()
        assert sum(bool(table.match(s)) for s in sent) == len(a.TABLES + a.OPTIONAL)
        sent.clear()
        assert c.post("/api/reload", json={}).json()["ok"]
        assert server.load_shared() is first and len(sent) == 1 and ".TBL_ACCESS_RUN " in sent[0], sent
        sent.clear()
        run[0] = "r2"
        server.cache.drop(server.KEY)
        assert server.load_shared()["run"]["RUN_ID"] == "r2"
        assert sum(bool(table.match(s)) for s in sent) == len(a.TABLES + a.OPTIONAL)


def test_newer_run():
    """Objects mode with parts: the last OK run is asked every load, never kept as a part, so a newer snapshot run shows
    once the local copy is gone (CACHE_HOURS), and an unchanged run reads no table again."""
    import pathlib
    import tempfile
    cache, run, last = server.cache, ["r1"], server.cache.last
    table = re.compile(r"SELECT \* EXCLUDE \(RUN_ID\) FROM D\.S\.TBL_ACCESS_(\w+) WHERE RUN_ID = '(\w+)'")
    d = a.fake()

    def answer(sql):
        if ".TBL_ACCESS_RUN " in sql:
            return [{"RUN_ID": run[0], "FINISHED_AT": "2026-11-03 10:00", "SOURCES": "{}", "NOTES": "{}"}]
        m = table.match(sql)
        return [dict(x) for x in d.get(m[1]) or []] if m else []
    with snowflake(answer) as sent:
        cache.HOURS, old_dir = 24, cache.DIR
        cache.DIR = pathlib.Path(tempfile.mkdtemp())
        try:
            assert server.load_shared()["run"]["RUN_ID"] == "r1"
            run[0] = "r2"
            cache.MEM.pop(server.KEY)
            cache.file(server.KEY).unlink()  # the local copy expired
            sent.clear()
            assert server.load_shared()["run"]["RUN_ID"] == "r2"
            assert sum(bool(table.match(s)) for s in sent) == len(a.TABLES + a.OPTIONAL)
            cache.MEM.pop(server.KEY)
            cache.file(server.KEY).unlink()
            sent.clear()
            assert server.load_shared()["run"]["RUN_ID"] == "r2" and not any(table.match(s) for s in sent)
            names = [m.get("file") for m in cache.parts_of(server.KEY).values()]
            assert not any("r1" in str(n) for n in names) and len(names) == len(a.TABLES + a.OPTIONAL) + 1, names
            cache.MEM.pop(server.KEY)
            cache.file(server.KEY).unlink()
            cache.last = lambda key: None  # run.py --build without the local copy: the last run comes from its part
            server.OFFLINE, sent[:] = True, []
            d = server.load_shared()
            assert d["run"]["RUN_ID"] == "r2" and d["GRANT"] and not sent
        finally:
            cache.DIR, server.OFFLINE = old_dir, False
            cache.last = last


def test_lost_session():
    """Direct mode: a session lost halfway is no empty data set; the load stops with the message, nothing is kept.
    No warehouse (606) stops it too, with what to set, instead of minutes of SHOW fallbacks."""
    x = RuntimeError("000606 (57P03): No active warehouse selected in the current session.")
    assert a.lost(x) and "SNOWFLAKE_WAREHOUSE" in server.load_error(x)
    n = [0]

    def answer(sql):
        n[0] += 1
        if n[0] > 3:
            raise ConnectionError("session gone")
        return []
    with snowflake(answer, direct=True):
        try:
            server.load_shared()
            raise AssertionError("a lost session loaded")
        except server.ApiError as x:
            assert "session gone" in str(x.args) + str(vars(x)), vars(x)
        assert server.KEY not in server.cache.MEM


def test_rebuild_outcome():
    """Rebuild snapshot says what the procedure returned: FAILED or SKIPPED is no success, and the copy stays."""
    for res, ok, word in (({"status": "FAILED", "notes": {"error": "x broke"}}, False, "Snapshot failed: x broke"),
                          ({"status": "SKIPPED", "notes": {"error": "run 7 is still running"}}, False, "Snapshot skipped: run 7"),
                          ({"status": "OK", "notes": {}}, True, "Snapshot rebuilt.")):
        with snowflake(lambda sql, res=res: [{"R": json.dumps(res)}]):
            server.cache.MEM[server.KEY] = (a.fake(), 0)
            r = c.post("/api/reload", json={"what": "rebuild"}).json()
            kept = server.cache.MEM.get(server.KEY, (None,))[0]
            assert r["ok"] is ok and r["message"].startswith(word) and (kept is not None and kept["run"]["RUN_ID"] == "fake") is not ok, r

    def boom(sql):
        raise RuntimeError("Warehouse WH is suspended")
    with snowflake(boom):
        r = c.post("/api/reload", json={"what": "rebuild"})
        assert r.status_code == 503 and r.json()["detail"] == "rebuild_failed" and "suspended" in r.json()["message"]
        r = c.post("/api/mine/load")  # the real reason, not "Request failed (500)"
        assert r.status_code == 503 and r.json()["detail"] == "mine_unreadable" and "suspended" in r.json()["message"]


def test_mine_shared_server():
    """My access reads with the server's login: off on a shared server (HOST not loopback) and with a key pair."""
    def env(**kw):
        old = {k: os.environ.get(k) for k in kw}
        os.environ.update({k: v for k, v in kw.items() if v is not None})
        for k, v in kw.items():
            if v is None:
                os.environ.pop(k, None)
        return old
    for kw, mode, off in ((dict(HOST="0.0.0.0"), "fake", True), (dict(SNOWFLAKE_PRIVATE_KEY_FILE="k.p8"), "snowflake", True),
                          (dict(SNOWFLAKE_PRIVATE_KEY_FILE="k.p8", MY_ACCESS="1"), "snowflake", False),
                          (dict(MY_ACCESS="0"), "fake", True), (dict(HOST="127.0.0.1"), "fake", False),
                          (dict(ALLOWED_HOSTS="access.team.example"), "fake", True),  # behind a proxy or tunnel
                          (dict(ALLOWED_HOSTS="access.team.example", MY_ACCESS="1"), "fake", False),
                          (dict(ALLOWED_HOSTS="localhost, 127.0.0.1"), "fake", False)):
        old, m = env(**kw), server.MODE
        server.MODE = mode
        try:
            assert (server.mine_off() is not None) is off, kw
            if mode == "fake":
                r = c.post("/api/mine/load")
                assert (r.status_code == 409 and r.json()["detail"] == "mine_unavailable") is off, (kw, r.text)
                assert js("/api/meta")["mine_available"] is not off
        finally:
            server.MODE = m
            env(**old)


def test_same_site():
    """The local API answers only its own host names and refuses a POST from another site's page."""
    evil = TestClient(server.make_app(), base_url="http://attacker.example")
    assert evil.get("/api/meta").status_code == 400  # DNS rebinding: a foreign Host header
    r = c.post("/api/reload", json={"what": "page"}, headers={"Origin": "http://attacker.example"})
    assert r.status_code == 403 and r.json()["detail"] == "cross_site"
    assert c.post("/api/reload", content='{"what":"rebuild"}', headers={"Origin": "null", "Content-Type": "text/plain"}).status_code == 403
    assert c.post("/api/reload", json={"what": "page"}, headers={"Origin": "http://localhost"}).json()["ok"]
    # an <img> or link on another site's page must not start a Snowflake read (and the SSO login)
    for site, code in (("cross-site", 403), ("same-site", 403), ("same-origin", 200), ("none", 200)):
        assert c.get("/api/meta", headers={"Sec-Fetch-Site": site}).status_code == code, site
    assert c.get("/", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200  # the page itself may be linked
    old = {k: os.environ.get(k) for k in ("ALLOWED_HOSTS", "HOST")}
    os.environ["ALLOWED_HOSTS"] = "access.example"
    try:
        assert TestClient(server.make_app(), base_url="http://access.example").get("/api/mine").status_code == 200
        # behind a proxy that rewrites Host: Origin is checked against the served names, not the Host header
        proxied = TestClient(server.make_app(), base_url="http://127.0.0.1")
        assert proxied.post("/api/reload", json={"what": "page"}, headers={"Origin": "https://access.example"}).json()["ok"]
        assert proxied.post("/api/reload", json={"what": "page"}, headers={"Origin": "https://evil.example"}).status_code == 403
        os.environ["HOST"] = "0.0.0.0"
        import socket
        ips = set(socket.gethostbyname_ex(socket.gethostname())[2])
        assert ips <= server.allowed_hosts(), ips  # opened by IP address on a shared server
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def test_error_text():
    """An unexpected error answers JSON with its message, as the Streamlit version shows it."""
    old = server.ROUTES["home"]
    server.ROUTES["home"] = lambda p, view: 1 / 0
    try:
        r = TestClient(server.make_app(), base_url="http://localhost", raise_server_exceptions=False).get("/api/home")
        assert r.status_code == 500 and r.json() == {"detail": "error", "message": "ZeroDivisionError: division by zero"}
    finally:
        server.ROUTES["home"] = old


def test_bundles_fresh():
    """web/dist and web/dist-st were built from the web/src next to them (vite.config.ts writes src-hash.txt): a change
    in web/src needs npm run build and npm run build:st, both committed."""
    import hashlib
    import pathlib
    web = pathlib.Path(server.__file__).with_name("web")
    src = web / "src"
    h = hashlib.sha256()
    for f in sorted(p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file() and "node_modules" not in p.parts):
        if re.search(r"\.(tsx?|css)$", f) and not re.search(r"\.test\.tsx?$", f):
            h.update(f"{f}\n{(src / f).read_bytes().decode('utf-8').replace(chr(13), '')}\n".encode("utf-8"))
    for d in ("dist", "dist-st"):
        got = (web / d / "src-hash.txt").read_text().strip() if (web / d / "src-hash.txt").is_file() else None
        assert got == h.hexdigest(), f"web/{d} is older than web/src: cd web; npm run build; npm run build:st"


def test_review_check():
    """Can they? for a role: depth via ownership is the same as the path depth; role loops get a side note."""
    own = js(f"/api/check?role={a.TECH}SALES_RAW_OWNER&obj=SALES.RAW.TBL_ORDER_RAW&priv=SELECT")
    paths = js(f"/api/check?role={a.TECH}SALES_RAW_OWNER&obj=SALES.RAW.TBL_ORDER_RAW&priv=OWNERSHIP")
    assert own["answer"]["how"] == "owner" and dict(own["answer"]["stats"])["Shortest depth"] == 1 == paths["paths"][0]["depth"]
    cut = next(x for x in paths["cuts"] if any(e["priv"] == "OWNERSHIP" for e in x["edges"]))
    assert "COPY CURRENT GRANTS" in cut["sql"] and "REVOKE OWNERSHIP" not in cut["sql"]  # the text the page shows
    assert not [n for n in js("/api/meta")["notes"] if n["key"] == "role_loop"]
    import test_access
    a.build(test_access.tiny([("B", "A"), ("C", "B"), ("B", "C")], [("A", "U")]))
    assert [n["raw"] for n in server.loop_notes()] == ["B, C"]
    a.build(a.fake())


def test_who():  # screen 2: who has access to an object, the admin preset, warehouses grouped by route
    keys = ["object", "people", "roles", "groups", "counts", "columns", "default_user", "refs"]
    d = js("/api/who?name=SALES.CORE.TBL_CUSTOMER", keys)
    n = d["counts"]
    assert n["people"] == len(d["people"]) == sum(n["levels"].values()) and n["levels"]["admin"] == 2 and n["blocked"] == 0, n
    sb = js("/api/who?name=DW.SANDBOX.TBL_SANDBOX_01")  # readers without USAGE on the schema: blocked, not readers
    by = {x["name"]: x for x in sb["people"] + sb["roles"]}
    assert by["DW_BI_01"]["blocked"] == by["GRP_DW_READERS"]["blocked"] == "no schema USAGE" and by["DW_DEV_01"]["blocked"] is None
    c = sb["counts"]
    assert c["blocked"] == 2 and c["levels"]["read"] == 0 and sum(c["levels"].values()) + c["blocked"] == c["people"], c
    assert any(g["blocked"] for g in sb["groups"])
    assert "no schema USAGE" in get("/api/who.csv?name=DW.SANDBOX.TBL_SANDBOX_01").text
    assert d["object"]["columns"] == 3 and d["object"]["masking"] and d["object"]["owners"]
    e = next(x for x in d["people"] if x["name"] == "ENGINEER_01")
    assert e["level"] == "change" and e["columns"] and e["login"] and d["refs"]["kinds"][e["first"]] == "functional"
    assert {c["column"] for c in d["columns"]} >= {"EMAIL", "PHONE"}
    w = js("/api/who?name=WH_SALES_XS")
    assert w["groups"][0]["route"][0] == "PUBLIC" and not w["columns"]
    p = js("/api/who?preset=admin")
    assert p["object"]["preset"] == "admin" and {x["name"] for x in p["people"]} == {"ADMIN_01", "OPS_01"}
    for o in a.objects:
        js(f"/api/who?name={o}", keys)
    assert js("/api/who?view=mine")["people"] is not None
    assert js("/api/check?view=mine")["nearest"] == [] and js("/api/request?view=mine")["user"]  # Can they? / Request in mine
    get("/api/who?name=NOPE", 404)


def test_access_home():  # screens 0 and 1: one row per object at its highest level, counted once
    d = js("/api/access?user=ENGINEER_01", ["who", "counts", "objects", "heat", "why", "refs"])
    assert "findings" not in d  # the page lists findings per object only
    n = d["counts"]
    h = d["heat"]  # each object in one cell, riskiest schema first, as the filter chips count them
    assert sum(x["read"] + x["change"] + x["own"] for x in h) == n["read"] and [x["own"] + x["change"] + x["sensitive"] for x in h] == sorted((x["own"] + x["change"] + x["sensitive"] for x in h), reverse=True)
    for x in h:
        for k in ("read", "change", "own"):
            assert js(f"/api/access?user=ENGINEER_01&cell={x['schema']}&min={k}")["total"] == x[k], (x, k)
    assert sum(x["read"] for x in h) == js("/api/access?user=ENGINEER_01&filter=read")["total"]
    assert js("/api/access?user=ENGINEER_01&hq=zzz")["heat"] == [] and d["heat_total"] == len(h)
    assert all(len(r["kids"]) <= server.KIDS and r["kids_total"] >= len(r["kids"]) for r in d["why"])
    assert (n["read"], n["change"], n["own"], n["sensitive"], n["runnable"], n["usage"]) == (5, 5, 2, 3, 5, 8), n  # the future grant on SALES.CORE is not an object
    powers = {(x["privileges"][0], x["object"]) for x in d["powers"]}
    assert powers == {("EXECUTE TASK", "ACCOUNT"), ("VIEW LINEAGE", "ACCOUNT"), ("CREATE TABLE", "SALES.CORE")}, powers
    log = next(x for x in d["objects"] if x["object"] == "SHARED.LOGGING.TBL_LOGGING")
    assert log["findings"][0] == dict(num="17", severity="High", label="read role can write") and log["level"] == "change"
    wh = next(x for x in d["runs"] if x["object"] == "WH_SALES_XS")
    assert "2" in {f["num"] for f in wh["findings"]}
    data = [x["object"] for x in d["objects"]]
    assert len(data) == len(set(data))  # each object once
    assert d["why"][0]["note"] == "default" and d["who"]["secondary_all"]
    r = js(f"/api/access?role={a.FUNC}ENGINEER")
    assert r["who"]["held_by"]["users"] >= 1 and r["counts"]["read"] == 5
    get("/api/access?user=NOPE", 404)
    h = js("/api/home", ["me", "risks", "protection", "counts"])
    assert h["me"] is None and h["risks"]["High"] > 0 and h["protection"]["unmasked"] == 3  # shared: nobody until picked
    hm = js("/api/home?view=mine")
    assert hm["risks"] is None and hm["me"]["counts"]["read"] == 5 and hm["cards"] is None
    k = h["cards"]  # one card per area, counts that add up to what the other pages show
    side = js("/api/meta")["people"]
    assert k["admins"]["total"] == side["admins"] > 0 and k["stale"]["total"] == side["stale"] > 0
    assert sum(k["people"]["by_status"].values()) == h["counts"]["users"] and sum(k["roles"].values()) == h["counts"]["roles"]
    assert sum(t["n"] for t in k["objects"]["by_type"]) == h["counts"]["objects"] and k["activity"]["ok"] and k["activity"]["daily"]
    assert k["stale"]["of_status"] == k["people"]["by_status"]  # "<n> of <all with that status>"
    assert all(k["stale"]["by_status"][s] <= k["stale"]["of_status"][s] for s in k["stale"]["by_status"])
    dep = k["depth"]  # each counted once, at its deepest chain; rule 14 flags the deepest
    assert set(dep) == {"users", "objects", "schemas", "databases"} and all(dep.values())
    assert max(map(int, dep["users"])) == max(map(int, dep["objects"])) > a.MAX_DEPTH_RULE
    assert sum(dep["users"].values()) <= h["counts"]["users"] and sum(dep["databases"].values()) <= k["biggest"]["n_databases"]
    assert max(map(int, dep["databases"])) == max(map(int, dep["schemas"])) == max(map(int, dep["objects"]))
    b = k["biggest"]
    assert b["schemas"][0] == dict(name="HR.PAYROLL", n=15) and len(b["schemas"]) == server.TOP_BIG
    assert [x["n"] for x in b["databases"]] == sorted((x["n"] for x in b["databases"]), reverse=True) and b["n_schemas"] == 17
    r = js("/api/rules", ["stale", "stale_total", "stale_split"])
    assert k["stale"]["names"] == [x["user"] for x in r["stale"]][:server.NAMES] and r["stale_total"] == sum(r["stale_split"].values()) == side["stale"]
    assert [x["sensitive"] for x in r["stale"]] == sorted((x["sensitive"] for x in r["stale"]), reverse=True)  # rule 7 first
    assert r["admins_total"] == side["admins"]  # no one whose only account privileges come through PUBLIC
    assert js("/api/meta")["default_user"] is None and js("/api/meta?view=mine")["default_user"] == server.DEMO_USER
    g = {p["key"]: p["group"] for p in js("/api/meta")["pages"]}
    assert g["home"] == "home" and g["access"] == g["object"] == "access" and g["check"] == "ask" and g["rules"] == "risk"
    assert g["review"] == g["changes"] == "govern"


def test_graph_focus():  # focus=<box>: only the lines through it, on every graph; the access graph's filters
    ids = lambda g: {n["id"] for n in g["nodes"]}
    whole = js("/api/map")["graph"]
    assert whole.get("focus") is None
    f = js(f"/api/map?focus={a.FUNC}ANALYST")["graph"]
    graph_ok(f)
    assert f["focus"] == dict(id=f"{a.FUNC}ANALYST", label=f"{a.FUNC}ANALYST") and len(f["nodes"]) < len(whole["nodes"])
    assert {server.DEMO_USER, f"{a.FUNC}ANALYST", f"{a.TECH}SALES_CORE_READ"} <= ids(f) and f"{a.FUNC}ENGINEER" not in ids(f)
    assert all(e["source"] in ids(f) and e["target"] in ids(f) for e in f["edges"])
    box = next(n["id"] for n in whole["nodes"] if n["id"].startswith("SALES ·"))  # a database box opens into its objects
    b = js("/api/map?focus=" + quote(box))["graph"]
    graph_ok(b)
    objs = [n for n in b["nodes"] if n["kind"] == "object"]
    assert b["focus"]["label"] == "SALES" and box not in ids(b) and objs and all(n["id"].startswith("SALES.") for n in objs)
    assert "HR.PEOPLE.TBL_EMPLOYEE" not in ids(b) and len(b["nodes"]) < len(whole["nodes"]) + 9
    assert js("/api/map?node=" + quote(box))["detail"][box]["leads_count"] >= 3  # the side panel of a box
    miss = js("/api/map?focus=NOPE")["graph"]
    assert miss["focus"] is None and "not in this graph" in miss["note"] and len(miss["nodes"]) == len(whole["nodes"])
    lazy = js(f"/api/map?role={a.FUNC}ENGINEER&focus={a.TECH}SALES_CORE_READ")["graph"]
    assert f"{a.FUNC}ANALYST" not in ids(lazy) and {f"{a.FUNC}ENGINEER", f"{a.TECH}SALES_CORE_READ"} <= ids(lazy)
    hr = js("/api/map?schema=HR")["graph"]  # filters: a database, a type, the step a line carries
    assert all(n["id"].startswith("HR.") for n in hr["nodes"] if n["kind"] == "object") and len(hr["nodes"]) < len(whole["nodes"])
    assert server.DEMO_USER in ids(hr) and f"{a.FUNC}ANALYST" not in ids(hr)
    wh = js("/api/map?otype=WAREHOUSE")["graph"]
    assert [n["id"] for n in wh["nodes"] if n["kind"] == "object"] == ["WH_SALES_XS"]
    own = js("/api/map?access=own")["graph"]
    objs = {n["id"] for n in own["nodes"] if n["kind"] == "object"}
    assert objs and all(e["cls"] == "own" for e in own["edges"] if e["target"] in objs)
    assert ids(js("/api/map?schema=NOPE")["graph"]) == {server.DEMO_USER}  # nothing matches: the start alone
    get("/api/map?access=delete", 400)
    for url, key in (("/api/user?name=ENGINEER_01", f"{a.TECH}SALES_CORE_READ"), (f"/api/role?name={a.FUNC}ENGINEER", f"{a.TECH}SALES_CORE_READ"),
                     ("/api/object?name=SALES.CORE.TBL_CUSTOMER", f"{a.FUNC}ANALYST")):
        w, n = js(url)["graph"], js(f"{url}&focus={key}")["graph"]  # the same param on the User, Role and Object graphs
        graph_ok(n)
        assert n["focus"]["id"] == key and key in ids(n) and len(n["nodes"]) < len(w["nodes"]), url
    sc = js("/api/user?name=ENGINEER_01&focus=SALES.CORE")["graph"]  # a schema box: its objects, nothing else
    assert sc["focus"]["label"] == "SALES.CORE" and {n["id"] for n in sc["nodes"] if n["kind"] == "object"} and all(
        n["id"].startswith("SALES.CORE") for n in sc["nodes"] if n["kind"] == "object")
    t = js(f"/api/graph?of=user-tab&name=ENGINEER_01&tab=all&focus={a.TECH}SALES_CORE_READ")
    assert t["focus"]["id"] == f"{a.TECH}SALES_CORE_READ"
    assert js(f"/api/graph?of=user&name=ENGINEER_01&focus={a.FUNC}ANALYST")["focus"]["id"] == f"{a.FUNC}ANALYST"
    m = js("/api/map?focus=SALES.CORE")["graph"]  # a member of the SALES box (picked in the opened box): it alone
    assert m["focus"]["id"] == "SALES.CORE" and not m["note"] and "SALES.CORE" in ids(m) and len(m["nodes"]) < len(whole["nodes"])
    assert not any(n["id"].startswith("SALES.") and n["id"] != "SALES.CORE" for n in m["nodes"])
    e = js(f"/api/role?name={a.FUNC}ENGINEER&focus=HR.PEOPLE.TBL_EMPLOYEE")["graph"]
    assert e["focus"]["id"] == "HR.PEOPLE.TBL_EMPLOYEE" and "HR.PEOPLE.TBL_EMPLOYEE" in ids(e) and not e["note"]
    dw = js("/api/user?name=DW_DEV_01&focus=DW.SC_R_CORE")["graph"]  # what the role leads to, not its ancestors' grants
    assert [n["id"] for n in dw["groups"]["DW.CORE"]["nodes"]] == [f"DW.CORE.TBL_CORE_0{i}" for i in (1, 2, 3)]
    fold = next(n["id"] for n in whole["nodes"] if n["kind"] == "fold")  # the built-ins box: what PUBLIC brings
    assert js("/api/map?node=" + quote(fold))["detail"][fold]["leads_count"] > 0
    assert "With the filters: 3 roles, 1 object." in hr["header"]
    lanes = [("User", ["U"]), ("Granted roles", ["R"]), ("Roles between", ["F"]), ("Grant holders", ["H1", "H2"])]
    es, gx = [("U", "R"), ("R", "F"), ("F", "H1"), ("F", "H2")], {"F": dict(members=["X", "Y"], edges=[("R", "H1")])}
    for f in ("F", "X"):  # a summary fold whose lines miss its members: the box itself, never 3 boxes without lines
        ls, out, _, _, _, label, note = server.narrow(lanes, es, {}, {"F": "fold"}, gx, f)
        assert label == "F" and not note and {n for _, ns in ls for n in ns} == {"U", "R", "F", "H1", "H2"} and len(out) == 4


def test_graph_see_compare():  # screens 4, 7, 9
    d = js("/api/map?table=SALES.CORE.TBL_CUSTOMER", ["start", "name", "graph", "detail", "risky", "why", "refs"])
    graph_ok(d["graph"])
    st = next(n for n in d["graph"]["nodes"] if "stack" in n["marks"])
    assert st["kind"] == "user" and st["label"] == "2 people" and d["detail"][st["id"]]["members"] == ["ANALYST_01", "ANALYST_02"]
    assert d["detail"]["GRP_ANALYSTS"]["leads"] == ["SALES.CORE.TBL_CUSTOMER"] and "admin" in d["risky"].values()
    assert all(e in {x["id"] for x in d["graph"]["edges"]} for e in d["risky"])
    u = js("/api/map")
    graph_ok(u["graph"])
    assert u["start"] == "user" and u["id"] == server.DEMO_USER and any(n["kind"] == "fold" for n in u["graph"]["nodes"])
    assert not any(n["kind"] == "fold" for n in js("/api/map?builtin=1")["graph"]["nodes"])
    graph_ok(js(f"/api/map?role={a.FUNC}ENGINEER&same=0&admin=0")["graph"])
    assert js("/api/map?view=mine")["name"]
    get("/api/map?role=NOPE", 404)
    s = js("/api/see", ["who", "known", "cards", "counts", "can_read", "sensitive", "usage", "role_usage", "refs"])
    assert s["counts"]["unprotected"] == 3 and s["usage"]["roles"] and s["sensitive"]["rows"] and s["can_read"]
    r = js(f"/api/see?role={a.FUNC}ANALYST")
    assert r["who"]["kind"] == "functional" and r["role_usage"]["holders"] >= 1 and r["usage"] is None
    get("/api/see?user=NOPE", 404)
    c = js("/api/compare", ["a", "b", "scope", "rows", "counts", "match", "extras"])
    assert "old" not in c and "dbs" not in c  # one differences view; the database picker searches the server
    assert c["a"]["name"] == server.DEMO_USER and c["b"]["name"] != c["a"]["name"] and c["scope"] == "sensitive"
    assert all(ch["sql"] and "roleDb" in ch and "toDb" in ch for ch in c["match"] + c["extras"])  # SQL from access.with_sql
    assert sum(c["counts"].values()) == js("/api/compare?same=1&limit=0")["rows_total"] and c["rows"]
    assert all(r["diff"] != "same" for r in c["rows"]) and c["rows_total"] == sum(v for k, v in c["counts"].items() if k != "same")
    big = js(f"/api/compare?a={a.FUNC}DEPLOY&b={a.FUNC}MARKETING&scope=all&same=1&limit=2&c_offset=2")
    assert len(big["rows"]) == 2 and big["offset"] == 2 and big["rows_total"] > 4  # one page, never every row
    assert all(r["diff"] == "only_a" for r in js(f"/api/compare?a={a.FUNC}DEPLOY&b={a.FUNC}MARKETING&scope=all&f=only_a")["rows"])
    x = js(f"/api/compare?a={a.FUNC}DEPLOY&b={a.FUNC}MARKETING&scope=all")
    assert x["counts"]["only_a"] > 0 and x["match"] and x["extras"] and x["a"]["kind"] == "functional"
    assert js("/api/compare?a=ENGINEER_01&b=ANALYST_01&scope=db&db=HR")["rows"][0]["diff"] == "only_a"
    get("/api/compare?a=NOPE", 404)
    g = {p["key"]: p["group"] for p in js("/api/meta")["pages"]}
    assert g["graph"] == g["compare"] == "ask" and g["see"] == "access"


def test_rules_paged():
    """Risks & fixes on a big account: counts and groups cover every finding, findings come a page at a time (of one
    group when asked), the fix texts with /api/finding, and the side nav counts findings at the worst severity."""
    every = js("/api/rules?sev=all", ["sev_counts", "groups", "groups_total", "findings_total", "offset", "limit", "areas"])
    n = every["total"]
    assert n == every["findings_total"] == sum(every["per_rule"].values()) == sum(every["sev_counts"].values()) > 4
    p1, p2 = js("/api/rules?sev=all&limit=3"), js("/api/rules?sev=all&limit=3&offset=3")
    assert len(p1["findings"]) == len(p2["findings"]) == 3 and p1["findings_total"] == n
    assert not {f["id"] for f in p1["findings"]} & {f["id"] for f in p2["findings"]}
    assert js("/api/rules?sev=all&limit=x&offset=-1")["limit"] == server.FINDINGS_PAGE  # a bad number: the default
    g = every["groups"][0]
    one = js(f"/api/rules?sev=all&group={g['key']}")
    assert one["findings_total"] == g["findings"] and {f["num"] for f in one["findings"]} == {g["key"]} and "admins" not in one
    off = js(f"/api/rules?sev=all&off={g['key']}")
    assert off["total"] == n - g["findings"] and off["hidden_off"] == g["findings"] and off["per_rule"] == every["per_rule"]
    hit = every["findings"][0]
    q = js("/api/rules?sev=all&q=" + hit["grantee"].replace(" (user)", "").lower()[:6])
    assert 0 < q["total"] <= n and hit["id"] in {f["id"] for f in q["findings"]}
    for by in ("person", "object", "grid"):
        d = js(f"/api/rules?sev=all&by={by}")
        assert d["filters"]["by"] == by and d["groups"] and sum(x["findings"] for x in d["groups"]) >= (n if by == "grid" else 1)
    grid = js("/api/rules?sev=all&by=grid")["grid"]
    assert sum(r["total"] for r in grid["rows"]) == n and all(set(r["counts"]) <= set(grid["rules"]) for r in grid["rows"])
    full = js(f"/api/finding?id={hit['id']}", ["finding", "refs"])["finding"]
    assert full["id"] == hit["id"] and {"iac", "sql", "changes"} <= set(full) and full["num"] == hit["num"]
    get("/api/finding?id=99999", 404)
    get("/api/finding?id=x", 404)
    m = js("/api/meta")
    nav = {p["key"]: p for p in m["pages"]}["rules"]
    crit = js("/api/rules?sev=Critical&limit=500")["findings"]
    assert nav["badge"] == len(crit) and nav["severity"] == "Critical" and nav["title"].endswith(f"in {len({f['num'] for f in crit})} rules")
    # the side menu's Findings: per severity, then rule, every finding once
    assert {s: sum(v.values()) for s, v in m["rule_sev"].items()} == {s: k for s, k in every["sev_counts"].items() if k}
    assert m["rule_sev"]["Critical"] == {"7": 4, "26": 1} and {r["num"]: r["critical"] for r in m["rules"] if r["critical"]}.keys() == {"5", "9"}
    # a rule's findings: most people reached first
    r17 = [f["people_total"] for f in js("/api/rules?sev=all&group=17")["findings"]]
    assert len(set(r17)) > 1 and r17 == sorted(r17, reverse=True)
    # rule 17 per role: one example line without the heuristic, and why it counts as read-only as a tag
    for g in js("/api/rules?sev=all&rule=17&by=grantee")["groups"]:
        assert len(g["said"]) == 1 and g["said"][0]["findings"] is None and "heuristic" not in g["said"][0]["text"]
        assert g["tags"] and set(g["tags"]) <= set(server.RO_HOW.values()) and sum(g["sevs"].values()) == g["findings"]
    # Home: what to act on first (Critical, then High, fewest findings first) and people / roles per severity
    h = js("/api/home", ["act_first", "subjects", "rule_sev"])
    first = [(x["severity"], x["findings"]) for x in h["act_first"]]
    assert first == sorted(first, key=lambda t: (server.SEV_RANK[t[0]], t[1])) and first[0][0] == "Critical"
    assert len(h["act_first"]) == server.ACT_FIRST and all(x["names"] and x["subjects"] >= len(x["names"]) for x in h["act_first"])
    assert h["subjects"]["Critical"] == dict(people=5, roles=0) and h["rule_sev"] == m["rule_sev"]
    adm = js("/api/rules", ["admins"])["admins"]  # riskiest first: ACCOUNTADMIN / SECURITYADMIN holders
    top = [bool({"ACCOUNTADMIN", "SECURITYADMIN"} & set(x["roles"])) for x in adm]
    assert top == sorted(top, reverse=True) and js("/api/home")["cards"]["admins"]["names"][0]["user"] == adm[0]["user"]
    svc = js("/api/home")["cards"]["admins"]["service_names"]  # Home's admin card: service users with admin, riskiest first
    assert [x["user"] for x in svc] == [x["user"] for x in adm if x["service"]][:len(svc)] and all(x["role"] and x["login"] for x in svc)


def test_risks_plan():  # screens 5, 10, 11: findings carry their fix as What if changes; the plan runs as /api/whatif
    from urllib.parse import quote
    r = js("/api/rules?sev=all")
    assert all({"changes", "objects"} <= f.keys() for f in r["findings"])
    fx = [f for f in r["findings"] if f["changes"]]
    assert fx and any(not f["changes"] for f in r["findings"])
    w = js("/api/whatif?changes=" + quote(json.dumps([ch for f in fx[:3] for ch in f["changes"]])))
    assert w["counts"]["fixed"] >= 1 and w["sql"] and "REVOKE" in w["sql"]
    m = js("/api/meta")
    assert len(m["rules"]) == 29 and all(x["meaning"] and x["fix"] and x["area"] for x in m["rules"])
    assert {p["key"]: p["group"] for p in m["pages"]}["whatif"] == "ask"


def test_review_grid_catalog_flow():  # screens 6, 8, 16
    g = js("/api/grid", ["scope", "columns", "rows", "total", "counts", "dbs", "refs"])
    assert g["scope"] == "sensitive" and len(g["columns"]) == 5 and g["counts"]["stale"] >= 3 and g["counts"]["admin"] == 2
    fin = next(r for r in g["rows"] if r["user"] == "FIN_14")
    assert fin["suggest"] == "disabled" and fin["last_login"] and fin["cells"]
    assert js("/api/grid?scope=db&db=HR")["scope"] == "db"
    al = js("/api/grid?scope=all&hideusage=0")
    assert al["total"] > len(js("/api/grid?scope=all")["columns"]) - 1 and len(al["columns"]) <= al["cap"]
    o = js("/api/grid?object=SALES.CORE.TBL_CUSTOMER&columns=privileges")
    assert o["scope"] == "object" and "SELECT" in {x["id"] for x in o["columns"]}
    every, old = js("/api/grid?scope=all&people=0"), server.GRID_ROWS
    server.GRID_ROWS = 3  # people capped after the filters: admins and the highest access first
    try:
        few = js("/api/grid?scope=all&people=0&hideusage=1")  # another URL: answers are kept per URL
        assert [r["user"] for r in few["rows"]] == [r["user"] for r in every["rows"]][:3] and len(every["rows"]) > 3
        assert few["matched"] == len(every["rows"]) and few["counts"] == every["counts"]
    finally:
        server.GRID_ROWS = old
    assert any(a.is_service(r["user"]) for r in every["rows"]) and not any(a.is_service(r["user"]) for r in al["rows"])
    q = js("/api/grid?scope=all&q=analyst")
    assert q["rows"] and all("ANALYST" in " ".join([r["user"], *r["roles"]]) for r in q["rows"]) and q["matched"] < every["matched"]
    get("/api/grid?object=NOPE&columns=privileges", 404)
    get("/api/grid?scope=db&db=NOPE", 404)
    try:
        server.grid_page({}, "mine")
        assert False, "grid on My access"
    except server.ApiError as x:
        assert x.status == 400
    assert js("/api/sensitive")["catalog"] is None  # only for its tab
    s = js("/api/sensitive?show=catalog", ["catalog"])
    assert [r["status"] for r in s["catalog"]][:2] == ["not", "partly"] and s["catalog"][0]["columns"]
    assert len(js("/api/sensitive?db=FINANCE&show=catalog")["catalog"]) == 2 == js("/api/sensitive?db=FINANCE")["catalog_total"]
    k = s["kpis"]
    assert len(k["stale"]) <= server.NAMES and k["stale_total"] >= len(k["stale"])
    assert all(len(o["roles"]) <= server.ROLES_SHOWN <= o["roles_total"] or len(o["roles"]) == o["roles_total"] for o in s["objects"])
    assert all(len(o["roles"]) == o["roles_total"] for o in js("/api/sensitive?limit=0")["objects"])  # the CSV: every role
    t = js("/api/flow", ["state", "objects", "roles_all", "roles_total"])  # the tables: no links, no followed box
    assert t["links"] == [] and t["follow"] is None and t["roles_total"] == len(t["roles_all"]) > len(t["roles"]) - 1
    assert all(o["roles"] >= 1 for o in t["objects"]) and t["roles_all"][0]["count"] >= t["roles_all"][-1]["count"]
    f = js("/api/flow?show=graph", ["state", "groups", "roles", "objects", "links", "select", "refs"])
    assert f["state"] == "ok" and f["select"] == "risky" and f["roles"][0]["kind"] == "admin"
    assert f["follow"]["sel"] == "risky" and f["follow"]["users"] and "users" not in f["links"][0]
    assert js("/api/flow?show=graph&sel=none")["follow"]["lit"] is None
    assert js("/api/flow?show=graph&sel=admin")["follow"]["users"] == ["ADMIN_01", "OPS_01"]
    assert len(f["objects"]) <= server.FLOW_OBJECTS + 1
    assert server.flow_page({}, "mine")["state"] == "mine"
    m = {p["key"]: p["group"] for p in js("/api/meta")["pages"]}
    assert m["flow"] == m["sensitive"] == "risk" and m["review"] == "govern"
    assert "flow" not in {p["key"] for p in js("/api/meta?view=mine")["pages"]}


def test_rule_by_grantee():
    """One rule (the side menu's Findings): its findings per role or user, with their objects and what most say; the
    menu's counts per rule from meta."""
    n = js("/api/meta")["rule_counts"]
    assert n and all(v > 0 for v in n.values())
    r = js("/api/rules?rule=18&by=grantee&sev=all")
    assert r["filters"]["rule"] == "18" and r["total"] == n["18"] == sum(g["findings"] for g in r["groups"])
    g = r["groups"][0]
    assert g["said"] and g["said"][0]["findings"] <= g["findings"] and g["objects"] >= 1 and g["kind"]
    one = js(f"/api/rules?rule=18&by=grantee&sev=all&group={g['key']}")
    assert one["findings_total"] == g["findings"] and all(f["num"] == "18" for f in one["findings"])


def test_usage_changes():  # screens 13, 14
    u = js("/api/usage?user=ENGINEER_01", ["who", "days", "periods", "available", "rows", "weeks", "counts", "changes", "refs"])
    assert u["available"] and u["days"] == 90 and u["periods"] == [30, 90, 180] and u["source"] == "demo values"
    assert u["rows"][0]["suggest"] == "drop" and u["counts"]["changes"] == len(u["changes"]) > 0
    assert u["sql"].startswith("REVOKE ") and js("/api/usage?user=ENGINEER_01&days=30")["sql"]  # the trim, from access.py
    one = js("/api/usage?user=ENGINEER_01&limit=1&u_offset=1")  # one page; the filter, search and CSV (limit=0) on the server
    assert len(one["rows"]) == 1 and one["offset"] == 1 and one["rows_total"] == u["counts"]["objects"] and "changes" not in one["rows"][0]
    drop = js("/api/usage?user=ENGINEER_01&f=drop&limit=0")
    assert drop["rows_total"] == u["counts"]["drop"] == len(drop["rows"]) and all(r["suggest"] == "drop" for r in drop["rows"])
    q = u["rows"][0]["object"].split(".")[-1].lower()
    assert all(q in r["object"].lower() for r in js(f"/api/usage?user=ENGINEER_01&q={q}")["rows"])
    assert " on " in u["trim_text"] and not u["changes_capped"]
    assert len(js("/api/usage?user=ENGINEER_01&days=180")["weeks"]) == 26
    assert js(f"/api/usage?role={a.FUNC}ANALYST")["who"]["kind"] == "functional"
    get("/api/usage?days=7", 400)
    get("/api/usage?user=NOPE", 404)
    ch = js("/api/changes", ["available", "events", "counts", "text", "before", "now", "refs"])
    assert ch["available"] and ch["before"] == "2026-10-26 07:00" and ch["text"].startswith("Since the snapshot of 2026-10-26")
    assert {"gain", "lose", "user", "risk"} <= {e["kind"] for e in ch["events"]} and ch["counts"]["all"] == len(ch["events"])
    one = js("/api/changes?subject=SALES.CORE.TBL_CUSTOMER")
    assert 0 < len(one["events"]) < len(ch["events"]) and all("SALES.CORE.TBL_CUSTOMER" in e["subjects"] for e in one["events"])
    assert server.changes_page({}, "mine")["available"] is False
    mode, prev = server.MODE, server.cache.prev
    try:  # Snowflake with no earlier copy in .cache/: explained, nothing compared
        server.MODE, server.cache.prev = "snowflake", lambda key: None
        x = server.changes_page({}, "shared")
        assert x["available"] is False and ".cache/" in x["reason"]
    finally:
        server.MODE, server.cache.prev = mode, prev
    m = {p["key"]: p["group"] for p in js("/api/meta")["pages"]}
    assert m["usage"] == "risk" and m["changes"] == "govern" and "changes" not in {p["key"] for p in js("/api/meta?view=mine")["pages"]}


def test_activity():  # the Activity tab of an object, a person and a role; why there is none
    o = js("/api/activity?name=SALES.CORE.TBL_CUSTOMER", ["what", "days", "available", "daily", "by", "rows", "ddl", "findings"])
    assert o["what"] == "object" and o["available"] and len(o["daily"]) == o["days"] == a.ACTIVITY_DAYS
    assert [f["num"] for f in o["findings"]] == ["24"] and o["ddl"][0]["type"] == "ALTER_TABLE_ADD_COLUMN"
    assert {f["num"] for f in js("/api/activity?user=ENGINEER_01")["findings"]} == {"24", "27"}
    r = js("/api/activity?role=SYSADMIN")
    assert r["by"]["user"][0]["key"] == "OPS_01" and r["graph"] is None and r["gone"][0]["role"] == "SYSADMIN"
    assert o["graph"]["nodes"] and o["sensitive"][0]["people"] and o["mark"] is None and o["refs"]["kinds"]
    assert len(o["rows"][0]["daily"]) == len(o["by"]["user"][0]["daily"]) == a.ACTIVITY_DAYS and o["work"] == dict(start=7, end=19)
    assert "ACCESS_HISTORY" in o["query_sql"] and o["objects"]["SALES.CORE.TBL_CUSTOMER"] == dict(kind="table", sensitive=True)
    assert js("/api/activity?name=SALES.CORE")["what"] == "scope" and js("/api/activity?name=WH_SALES_XS")["what"] == "warehouse"
    assert js("/api/activity?name=SALES.MART.ST_CUSTOMER_LOOKUP")["app"]["saw"] == {"SUPPORT_01": ["SALES.MART.VW_CUSTOMER"]}
    assert "SET TAG" in js("/api/activity?name=SALES.CLEAN.TBL_ORDER")["mark"]["sql"]  # untagged: the text to tag it
    app = js("/api/activity?name=SALES.MART.ST_CUSTOMER_LOOKUP")  # a Streamlit app: the queries it ran for its viewers
    assert app["what"] == "app" and app["by"]["user"][0]["key"] == "SUPPORT_01" and app["graph"] is None
    assert js("/api/who?name=SALES.MART.ST_CUSTOMER_LOOKUP")["app"]["exposed"] == {"SUPPORT_01": ["SALES.MART.VW_CUSTOMER"]}
    one = js("/api/activity?name=SALES.CORE.TBL_CUSTOMER&as=ENGINEER_01")  # the "Access for" person only
    assert one["user"] == "ENGINEER_01" and {b["key"] for b in one["by"]["user"]} == {"ENGINEER_01"}
    assert [f["num"] for f in one["findings"]] == ["24"] and sum(one["daily"]) < sum(o["daily"])
    assert not js("/api/activity?name=SALES.CORE.TBL_CUSTOMER&as=HR_01")["rows"]  # granted or not: no use
    assert not js("/api/activity?name=SALES.CORE&as=HR_01")["rows"]  # a schema: only that person's use too
    assert {r["area"] for r in js("/api/meta")["rules"] if 24 <= int(r["num"]) <= 28} == {"Activity"}


def test_objuse():  # Object activity: counts per type and age, the tabs, server paging, filters, CSV, Home's card
    d = js("/api/objuse", ["available", "days", "periods", "tab", "types", "tabs", "patterns", "new", "rows", "total", "notes", "refs"])
    assert d["available"] and d["tab"] == "unused" and d["days"] == 90 and d["tabs"] == dict(unused=30, read_only=5, write_only=1, all=49)
    assert d["total"] == 30 and all(r["bucket"] in ("180", "none") for r in d["rows"]) and d["rows"][0]["days_since"] is None  # never used first
    assert d["unused_new"] == sum(r["new"] for r in d["rows"]) and all(r["history"] == 180 for r in d["rows"])
    t = {x["type"]: x["buckets"] for x in d["types"]}
    assert t["TABLE"]["180"] == 2 and t["DYNAMIC TABLE"]["90"] == 1 and t["PROCEDURE"]["nodata"] == 3
    ro = js("/api/objuse?tab=read_only&limit=0")
    assert ro["rows"] == [] and ro["total"] == 5  # limit=0: the counts only
    ro = js("/api/objuse?tab=read_only")["rows"]
    assert all(r["pattern"] == "read_only" and r["read_q"] and not r["write_q"] for r in ro) and ro[0]["read_q"] >= ro[-1]["read_q"]
    wo = js("/api/objuse?tab=write_only&days=180")["rows"]
    assert {r["object"] for r in wo} == {"SALES.CLEAN.TBL_ORDER", "SALES.PIPELINE.TBL_CUSTOMER_CHANGES"}
    one = js("/api/objuse?tab=all&limit=2&offset=2&sort=object&dir=1")
    assert one["total"] == 49 and len(one["rows"]) == 2 and one["offset"] == 2
    assert [r["object"] for r in one["rows"]] == sorted(r["object"] for r in js("/api/objuse?tab=all&limit=100&sort=object")["rows"])[2:4]
    sc = js("/api/objuse?tab=all&scope=SALES.PIPELINE&type=TABLE&q=changes")
    assert [r["object"] for r in sc["rows"]] == ["SALES.PIPELINE.TBL_CUSTOMER_CHANGES"] and sc["tabs"]["all"] < 49
    assert any(r["new"] for r in js("/api/objuse?tab=all&q=core.tbl_customer")["rows"])
    get("/api/objuse?days=7", 400)
    csv = get("/api/objuse.csv?tab=write_only&days=180").text.splitlines()
    assert csv[0].startswith("Object,Type,Last read") and len(csv) == 3 and "written" not in csv[1]
    h = js("/api/home")["cards"]["objuse"]
    assert h["ok"] and h["read_only"] == 5 and h["write_only"] == 1 and "PROCEDURE" in h["nodata"] and h["unused"] == d["tabs"]["unused"]
    assert h["unused_new"] == d["unused_new"]
    wh = {r["object"]: r for r in js("/api/objuse?tab=all&type=WAREHOUSE&days=180")["rows"]}
    assert wh["WH_SALES_XS"]["history"] == 30 and wh["WH_SALES_XS"]["read_q"] > 0
    assert {x["type"] for x in h["types"]} >= {"TABLE", "VIEW", "WAREHOUSE"}
    m = server.objuse_page({}, "mine")
    assert m["available"] is False and "shared" in m["reason"] and not m["rows"]
    assert {p["key"]: p["group"] for p in js("/api/meta")["pages"]}["objuse"] == "risk"


def test_sql_page():  # "SQL behind this page": commented, read-only, full names, the page's own name in the SET lines
    import re as _re
    cases = [("access", "user=ENGINEER_01", "SET USER_NAME = 'ENGINEER_01';"), ("access", "role=F_ANALYST", "SET ROLE_NAME = 'F_ANALYST';"),
             ("object", "name=SALES.CORE.TBL_CUSTOMER", "SET OBJECT_NAME = 'SALES.CORE.TBL_CUSTOMER';"),
             ("object", "name=SALES.CORE.TBL_CUSTOMER&show=activity", "SET FROM_DAY = "),
             ("object", "name=SALES.MART.ST_CUSTOMER_LOOKUP&show=activity", "SET APP_NAME = 'SALES.MART.ST_CUSTOMER_LOOKUP';"),
             ("object", "name=SALES.CORE&show=activity", "SET IN_SCOPE = 'SALES.CORE';"),
             ("object", "name=WH_SALES_XS&show=activity", "SET WAREHOUSE_NAME = 'WH_SALES_XS';"),
             ("access", "user=O'BRIEN&show=activity", "SET USER_NAME = 'O''BRIEN';"),
             # a line break or backslash from a link stays inside the string: no statement of its own
             ("access", "user=X%0AGRANT%20ROLE%20R%20TO%20USER%20U;%20--&show=activity", "SET USER_NAME = 'X GRANT ROLE R TO USER U; --';"),
             ("access", "user=X%5C'&show=activity", "SET USER_NAME = 'X\\\\''';"),
             ("usage", "user=ENGINEER_01", "USER_NAME = $USER_NAME"), ("rules", "", "GRANTEE_NAME = 'PUBLIC'"), ("home", "", "SNOWFLAKE.ACCOUNT_USAGE"),
             # names under any parameter: Can they? (a user and an object), Compare (two roles), Request (a role)
             ("check", "name=ENGINEER_01&obj=SALES.CORE.TBL_CUSTOMER", "SET USER_NAME = 'ENGINEER_01';"),
             ("check", "name=ENGINEER_01&obj=SALES.CORE.TBL_CUSTOMER", "SET OBJECT_NAME = 'SALES.CORE.TBL_CUSTOMER';"),
             ("compare", "a=F_ANALYST&b=F_MARKETING", "SET ROLE_NAME = 'F_MARKETING';"), ("request", "for_role=F_MARKETING", "SET ROLE_NAME = 'F_MARKETING';")]
    for page, q, want in cases:
        qs = js(f"/api/sql?page={page}&{q}")["queries"]
        assert qs and any(want in x["sql"] for x in qs), (page, q)
        for x in qs:
            code = chr(10).join(_re.sub(r"'[^']*'", "''", l).split("--")[0] for l in x["sql"].splitlines())  # no strings, no comments
            assert "SNOWFLAKE.ACCOUNT_USAGE." in code and not _re.search(r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|DROP|ALTER|GRANT|REVOKE|CALL)\b", code), x["title"]
            assert code.count("(") == code.count(")") and x["sql"].lstrip().startswith("--"), x["title"]
    sec = js("/api/activity?name=SALES.CORE.TBL_CUSTOMER")["section_sql"]
    assert set(sec) >= {"client", "kinds", "matrix", "type_day", "by_day", "who", "hours", "off", "touched", "ddl"} and "$TZ_HOURS" in sec["hours"]


API = {"graph": "map", "whatif": 'whatif?changes=[{"op":"empty_public"}]'}  # page key -> its endpoint, when they differ


def test_every_page():  # every page key: a label, a nav group, an endpoint that answers shared and (if not shared-only) mine
    assert set(server.PAGES) == set(server.GROUP) and set(server.GROUP.values()) == {"home", "access", "ask", "risk", "govern"}
    assert server.SHARED_ONLY <= set(server.PAGES) and all(server.GROUP[k] in ("risk", "govern") for k in server.SHARED_ONLY)
    assert c.post("/api/mine/load").status_code == 200
    mine = {p["key"] for p in js("/api/meta?view=mine")["pages"]}
    assert mine == set(server.PAGES) - server.SHARED_ONLY
    for k in server.PAGES:
        e = API.get(k, k)
        assert e.split("?")[0] in server.ROUTES and ("refs" in js(f"/api/{e}") or k == "home"), k
        if k in mine:
            get(f"/api/{e}{'&' if '?' in e else '?'}view=mine")


def test_pages_empty():
    """The rule on every page: missing, NULL or empty data answers empty plus a note in the Data from box, never a 500,
    shared and mine, CSVs included. Only a lost connection may stop a load (test_rebuild_outcome)."""
    import test_access
    urls = [f"/api/{API.get(k, k)}" for k in server.PAGES] + [
        f"/api/{u}" for u in ("user?name=ENGINEER_01", f"role?name={a.FUNC}ENGINEER", "object?name=SALES.CORE.TBL_CUSTOMER",
                              "check?name=ENGINEER_01&obj=HR.PEOPLE.TBL_EMPLOYEE", "usage?user=ENGINEER_01",
                              "activity?name=SALES.CORE.TBL_CUSTOMER", "activity?user=ENGINEER_01",
                              f"activity?role={a.FUNC}ENGINEER", "activity?name=SALES", "who?preset=admin",
                              "compare?a=ENGINEER_01&b=ANALYST_01", "rules.csv", "review.csv?db=*")]
    mine = {p["key"] for p in js("/api/meta?view=mine")["pages"]} if c.post("/api/mine/load").status_code == 200 else set()
    old = server.read_shared
    try:
        for name, d in test_access.none_variants(full=False):
            server.read_shared = lambda d=d: d
            server.cache.MEM.pop(server.KEY, None)
            server.forget()
            a.memo.clear()  # every variant has the same run, so the same key: built again, not taken from the last one
            a.built.clear()
            notes = {n["key"] for n in js("/api/meta")["notes"]}
            assert "missing_names" in notes or "None in one row" not in name, (name, notes)
            assert c.post("/api/mine/load").status_code == 200, name
            for u in urls + [f"/api/{API.get(k, k)}{'&' if '?' in API.get(k, k) else '?'}view=mine" for k in mine]:
                r = c.get(u)
                assert r.status_code < 500, (name, u, r.status_code, r.text[:300])
    finally:
        server.read_shared = old
        server.cache.MEM.pop(server.KEY, None)
        server.forget()
        server.MINE.clear()
        a.memo.clear()
        a.built.clear()
        a.build(a.fake())


def test_review_fixes():  # search answers, row policy list, defaults that exist, compare without users
    f = {i["id"]: i for i in js("/api/find?q=ENGINEER_01")["items"]}
    n = js(f"/api/access?user={server.DEMO_USER}")["counts"]  # shared Home has nobody until one is picked
    assert f[server.DEMO_USER]["answer"] == f"reads {n['read']} · changes {n['change']} · owns {n['own']}"
    wh = next(i for i in js("/api/find?q=WH_")["items"] if i["type"] == "WAREHOUSE")
    assert wh["answer"].endswith("admin holders") and wh["answer"][0].isdigit()  # as the Object page counts them
    s = js("/api/sensitive", ["row_list", "row_total", "row_offset"])  # Home sends only the count
    assert [r["object"] for r in s["row_list"]] == sorted(a.row_tables()) and s["row_total"] == js("/api/home")["protection"]["row_tables"]
    assert "row_list" not in js("/api/home")["protection"] and js("/api/sensitive?t_offset=1&limit=1")["row_list"][0]["object"] == sorted(a.row_tables())[1]
    assert js("/api/meta")["pages"] and {"home_summary", "rule_badge"} <= set(a.memo)  # Home and meta count the findings once per data set
    old = server.DEMO_USER
    try:
        server.DEMO_USER = "NOBODY_HERE"; server.forget()  # answers are kept per data set; this changes a setting
        assert js("/api/who?name=SALES.CORE.TBL_CUSTOMER")["default_user"] is None  # shared: nobody until one is picked
    finally:
        server.DEMO_USER = old
        server.forget()
    users = a.users
    try:
        a.users = []
        d = server.compare_page({}, "shared")
        assert d["a"]["name"] == a.roles[0] and d["a"]["kind"] != "user"
    finally:
        a.users = users
    r = a.FUNC + "ANALYST"
    ch = js(f"/api/changes?subject={r}")
    assert ch["events"] and all(r in e["subjects"] for e in ch["events"])
    u = js("/api/changes?subject=ANALYST_02")
    assert u["events"] and all("ANALYST_02" in e["subjects"] for e in u["events"])
    g = {x["user"]: x for x in js("/api/grid")["rows"]}
    assert all(bool(x["suggest"]) == a.stale(n) for n, x in g.items())


def test_step3():  # review 2026-11-09 step 3: server-side search for pickers, area bars, What changed edges, gzip
    full = js("/api/list?what=users,roles")
    assert full["total"] == len(full["items"]) == len(a.users) + len(a.roles)
    assert {i["kind"] for i in full["items"]} >= {"user", "functional"}
    hit = js(f"/api/list?what=roles&q={a.FUNC.lower()}&limit=3", ["items", "total"])
    assert len(hit["items"]) == 3 < hit["total"] and all(i["id"].startswith(a.FUNC) for i in hit["items"])
    assert js("/api/list?what=users&q=zzz_nobody")["total"] == 0
    h = js("/api/home", ["per_rule"])["per_rule"]
    assert sum(h.values()) == len(a.checks()) and set(h) <= {r["num"] for r in js("/api/meta")["rules"]}
    assert c.post("/api/mine/load").status_code == 200 and js("/api/home?view=mine").get("per_rule") is None
    assert js("/api/meta")["cache_hours"] == (server.cache.HOURS if server.cache.local() else 0)
    ch = js("/api/changes", ["severity"])
    assert sum(ch["severity"]["new"].values()) > 0 and set(ch["severity"]) == {"new", "fixed"}
    edges = [e["edge"] for e in ch["events"] if e.get("edge")]
    assert edges and all(set(e) == {"source", "source_kind", "target", "target_kind", "privilege", "added"} for e in edges)
    assert {e["added"] for e in edges} == {True, False} and {e["target_kind"] for e in edges} & {"object", "technical"}
    assert js("/api/changes?subject=SALES.CORE.TBL_CUSTOMER")["severity"] is None
    r = c.get("/api/list?what=objects", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers.get("content-encoding") == "gzip"



def test_step4():  # review 2026-11-09 step 4: where the DuckDB SQL copy is, in the "Data from" panel
    m = js("/api/meta", ["sql_copy", "inside"])
    q = m["sql_copy"]
    assert set(q) == {"on", "path", "schema", "note", "written_at"} and q["path"].endswith("access.duckdb")
    assert m["inside"] is False and (q["on"] or q["note"])  # demo data: off unless DUCKDB=1, and it says so
    mine = js("/api/meta?view=mine")["sql_copy"]
    assert mine["on"] is False and mine["schema"] is None


def test_run_address():
    """python run.py streamlit listens where HOST says (127.0.0.1 by default), as the web version does."""
    import run
    for env, want in (({}, "127.0.0.1"), ({"HOST": "0.0.0.0"}, "0.0.0.0")):
        cmd, _ = run.command(["streamlit"], env)
        assert cmd[cmd.index("--server.address") + 1] == want, cmd


def test_background():
    """Read Snowflake again runs in a thread: the pages keep the old data (and answer at once) until the new read is
    built, then switch; a failed read keeps the old data and says why in /api/progress."""
    import threading
    import time
    from datetime import datetime
    go, began = threading.Event(), threading.Event()

    def answer(sql):
        if sql.startswith("SELECT CURRENT_TIMESTAMP()"):
            return [{"T": datetime(2026, 11, 3, 10)}]
        if "GRANTS_TO_ROLES WHERE" in sql:
            began.set()
            go.wait(5)
        return []

    def boom(d):  # a load tolerates views it cannot read: the build is what fails here
        raise RuntimeError("Warehouse WH is suspended")
    built = server.built
    server.BACKGROUND = True
    try:
        for bad in (False, True):
            with snowflake(answer, direct=True):
                old = a.fake()
                server.cache.MEM[server.KEY] = (old, time.time())
                go.clear(), began.clear()
                server.built = boom if bad else built
                r = c.post("/api/reload", json={"what": "page"}).json()
                assert r["ok"] and r["started"], r
                assert began.wait(5)
                t0 = time.time()
                assert js("/api/meta")["run"]["run_id"] == "fake" and time.time() - t0 < 1  # old data, no wait
                assert js("/api/progress")["job"]["state"] == "running"
                assert c.post("/api/reload", json={"what": "page"}).json()["ok"] is False  # one at a time
                go.set()
                while js("/api/progress")["job"]["state"] == "running":
                    time.sleep(0.05)
                job = js("/api/progress")["job"]
                now = server.cache.MEM[server.KEY][0]
                if bad:
                    assert job["state"] == "failed" and "suspended" in job["message"] and now is old, job
                else:
                    assert job["state"] == "done" and now["run"]["RUN_ID"] == "direct", job
    finally:
        server.BACKGROUND, server.built = False, built
        server.JOB.clear()


def test_kept_rules():
    """After a restart the shared data's rule results come from .cache/ (not checked again) while the data, the
    settings and access.py are the same; another setting checks them again."""
    import pathlib
    import tempfile
    import time
    cache = server.cache
    old = cache.DIR, cache.HOURS, server.MODE, a.rule_rows
    cache.DIR, cache.HOURS, server.MODE = pathlib.Path(tempfile.mkdtemp()), 24, "snowflake"
    d = a.fake()
    try:
        cache.MEM[server.KEY] = (d, time.time())
        a.memo.clear(), a.built.clear(), server.forget()  # as after a start: nothing checked yet
        want = js("/api/rules")
        assert cache.file(server.KEY).with_suffix(".rules.pkl").is_file()

        def boom():
            raise AssertionError("checked again")
        a.memo.clear(), a.built.clear(), server.forget()
        a.rule_rows = boom
        assert js("/api/rules") == want  # a restart: kept
        a.memo.clear(), a.built.clear(), server.forget()
        os.environ["DORMANT_DAYS"] = "91"
        try:
            c.get("/api/rules")
            raise RuntimeError("kept after a settings change")
        except AssertionError as x:  # another setting: checked again
            assert "checked again" in str(x)
    finally:
        os.environ.pop("DORMANT_DAYS", None)
        cache.DIR, cache.HOURS, server.MODE, a.rule_rows = old
        cache.MEM.pop(server.KEY, None)
        a.memo.clear(), a.built.clear(), server.forget()


def test_built_ready():
    """A load does the first page's work too (rule 17, what each fix breaks, sensitive objects), with load-log lines,
    so the first page after "Ready" does not sit on Loading."""
    lines = []
    a.memo.clear(), a.built.clear(), server.forget()
    try:
        with a.progress(lines.append):
            server.built(a.fake())
        assert {"rows", "ro", "breaks", "sens"} <= a.memo.keys()
        assert any(x.startswith("Working out what each fix changes") for x in lines), lines
        assert any(x.startswith("Preparing the pages") for x in lines), lines
    finally:
        a.memo.clear(), a.built.clear(), server.forget()


def test_changes_kept():
    """A refresh compares the new data with the previous snapshot (compared): What changed answers from that, after a
    restart too (.cache/<key>.diff.pkl), with the page it gives without it; an event sends its first NAMES ids."""
    import pathlib
    import tempfile
    import time
    cache = server.cache
    old = cache.DIR, cache.HOURS, server.MODE, cache.prev, a.diff
    a.memo.clear(), a.built.clear(), server.forget()
    want = js("/api/changes", ["events_total", "offset", "f"])
    assert want["events_total"] == want["counts"]["all"] == len(want["events"]) and want["f"] == "all"
    g = js("/api/changes?f=gain&limit=1&offset=1")  # one filter, one page: the server pages a big change
    assert g["events_total"] == g["counts"]["gain"] == 2 and g["offset"] == 1 and [e["kind"] for e in g["events"]] == ["gain"]
    assert g["events"][0]["text"] == [e for e in want["events"] if e["kind"] == "gain"][1]["text"]
    cache.DIR, cache.HOURS, server.MODE =pathlib.Path(tempfile.mkdtemp()), 24, "snowflake"
    cache.prev = lambda key: (a.fake_previous(), 0)
    d = a.fake()

    def boom(*x):
        raise AssertionError("compared again")
    try:
        cache.MEM[server.KEY] = (d, time.time())
        a.memo.clear(), a.built.clear(), server.forget()
        server.built(d)
        a.diff = boom
        server.compared(d)  # the previous snapshot is not built (a same-run refresh kept an older one): left to the page
        assert not cache.file(server.KEY).with_suffix(".diff.pkl").exists()
        a.diff = old[4]
        server.built(a.fake_previous())  # a refresh: the replaced data set is still built
        server.built(d)
        server.compared(d)
        assert cache.file(server.KEY).with_suffix(".diff.pkl").is_file()
        a.memo.clear(), a.built.clear(), server.forget()  # a restart
        a.diff = boom
        got = js("/api/changes")
        assert got["events"] == want["events"] and got["text"] == want["text"] and got["counts"] == want["counts"]
        a.diff = old[4]
        big = dict(people=[f"U{i:03}" for i in range(50)], objects=[], subjects=[f"U{i:03}" for i in range(50)], capped=True)
        a.memo[("diff", cache.run_of(a.fake_previous()))]["events"].append(dict(got["events"][0], text="big", **big))
        server.forget()
        one = {e["text"]: e for e in js("/api/changes?subject=U040")["events"]}["big"]
        assert one["people"] == one["subjects"] == big["people"][:server.NAMES] + ["U040"]
        assert "Big changes name only" in js("/api/changes?subject=U040")["text"] and "Big" not in js("/api/changes")["text"]
        assert len({e["text"]: e for e in js("/api/changes")["events"]}["big"]["people"]) == server.NAMES
    finally:
        cache.DIR, cache.HOURS, server.MODE, cache.prev, a.diff = old
        cache.MEM.pop(server.KEY, None)
        a.memo.clear(), a.built.clear(), server.forget()


def test_parts():
    """Every read is kept as a part: the next load reads only the part that timed out (in a wave: only its timed-out
    statements), a wave's statements keep their own columns, --build reads nothing, a fresh export reads every part
    again; run.py hands the stage flags on."""
    import pathlib
    import tempfile
    import run
    cache, a = server.cache, server.a
    old = cache.DIR, cache.HOURS
    cache.DIR, cache.HOURS = pathlib.Path(tempfile.mkdtemp()), 24
    asked, slow = [], [True]
    rows, engine = [{"N": 3, "B": True, "F": 0.5, "S": "x", "__i": 0}], cache.engine
    for eng in ("pyarrow", "duckdb"):  # either writer reads back what it was given: an int stays an int
        try:
            importlib.import_module(eng + ".parquet" if eng == "pyarrow" else eng)
        except ImportError:  # e.g. pyarrow without its parquet DLL: engine() picks duckdb
            continue
        cache.engine = lambda: eng
        try:
            cache.write_part(cache.DIR / f"{eng}.parquet", rows)
            got = cache.read_part(cache.DIR / f"{eng}.parquet")
            assert got == rows and type(got[0]["N"]) is int, (eng, got)
            mix = [{"NAME": "a", "__i": 0}, {"name": "b", "__i": 1}]  # ACCOUNT_USAGE and SHOW in one wave: names differ in case
            cache.write_part(cache.DIR / f"{eng}2.parquet", mix)
            got = cache.read_part(cache.DIR / f"{eng}2.parquet")
            assert [{k: v for k, v in r.items() if v is not None} for r in got] == mix, (eng, got)
        finally:
            cache.engine = engine

    def query(sql):
        asked.append(sql)
        if sql in ("SELECT 3 FROM B", "SHOW 6 IN W") and slow[0]:
            raise TimeoutError("timeout")
        return [{"A": 1}] if sql == "SHOW 4 IN W" else [{"N": len(sql), "S": sql}]  # a wave of two shapes

    def load(offline=False):
        asked.clear()
        q = cache.parted(query, "k", offline)
        return (q("SELECT 1 FROM A"), a.each(q, ["SELECT 2 FROM B", "SELECT 3 FROM B"], what=["two", "three"]),
                a.each(q, ["SHOW 4 IN W", "SHOW 5 IN W", "SHOW 6 IN W"], what="SHOW W"))

    try:
        first = load()
        assert isinstance(first[1][1], TimeoutError) and isinstance(first[2][2], TimeoutError) and len(asked) == 6
        slow[0] = False
        second = load()
        assert asked == ["SELECT 3 FROM B", "SHOW 6 IN W"], asked
        assert second[0] == first[0] and second[1][0] == first[1][0] and second[1][1] == [{"N": 15, "S": "SELECT 3 FROM B"}]
        assert second[2][:2] == first[2][:2] == [[{"A": 1}], [{"N": 11, "S": "SHOW 5 IN W"}]], second[2]
        assert load(offline=True) == second and asked == []
        cache.clear_parts("k")
        assert load() == second and len(asked) == 6
    finally:
        cache.DIR, cache.HOURS = old
    assert run.command(["--export", "--fresh"], {})[0][1:] == ["server.py", "--export", "--fresh"]
    assert run.command(["--build"], {})[1]["BUILD_ONLY"] == "1"
    assert "BUILD_ONLY" not in run.command([], {})[1]
    assert os.path.isabs(run.command(["--cache-dir", "c"], {})[1]["CACHE_DIR"]) and "CACHE_DIR" not in run.command([], {})[1]


def test_cache_lock():
    """A memory hit and a read of another key never wait for a key's read, and a drop during a read of its key wins."""
    import threading
    import time
    cache, go, began = server.cache, threading.Event(), threading.Event()

    def slow():
        began.set()
        go.wait(5)
        return "old"
    cache.MEM["t_hit"] = ("hit", time.time())
    try:
        t = threading.Thread(target=cache.get, args=("t_slow", slow, False))
        t.start()
        began.wait(5)
        t0 = time.time()
        assert cache.get("t_hit", lambda: "read", False)[0] == "hit" and time.time() - t0 < 1
        assert cache.get("t_cold", lambda: "cold", False)[0] == "cold" and time.time() - t0 < 1  # nor another key's read
        dropper = threading.Thread(target=cache.drop, args=("t_slow",))
        dropper.start()  # while slow() still reads
        time.sleep(0.2)
        go.set()
        t.join(5)
        dropper.join(5)
        assert "t_slow" not in cache.MEM  # the older read is not kept after the drop
    finally:
        go.set()
        cache.MEM.pop("t_hit", None)
        cache.MEM.pop("t_slow", None)
        cache.OLD.pop("t_slow", None)
        cache.MEM.pop("t_cold", None)


def test_csv_formula():
    import server
    t = server.csv_text(["o", "n"], [["=HYPERLINK(1)", "-3"], ["@x", 5], ["T", "+1.5"]])
    assert t.splitlines()[1:] == ["'=HYPERLINK(1),-3", "'@x,5", "T,+1.5"], t
    assert get("/api/rules.csv?area=%3D1%2B1").text.splitlines()[0] == "Rule checks,'=1+1"  # a head row from the link



def test_csv_off():  # CSV=0: every CSV route refuses in both versions and meta tells the app to hide the buttons
    import st_react
    assert js("/api/meta")["csv"] is True and get("/api/rules.csv").status_code == 200
    os.environ["CSV"] = "0"
    try:
        assert js("/api/meta")["csv"] is False
        for n in server.CSV:
            assert get(f"/api/{n}.csv", 403).json()["detail"] == "csv_off"
            st, body, _ = st_react.answer("GET", f"/api/{n}.csv", None, None)
            assert st == 403 and body["detail"] == "csv_off", (n, st, body)
    finally:
        os.environ.pop("CSV")


def test_switches():
    """HIERARCHY=0: Risks & fixes lists the rules that walk role paths as skipped, not passing, in both versions (the
    same JSON); a statement past STATEMENT_TIMEOUT answers JSON naming the step and the longer setting."""
    import st_react

    def fresh():  # answers and built data sets are kept per data set; this changes a setting
        server.forget(), a.built.clear(), a.memo.clear()
    old = a.HIERARCHY_ON
    try:
        a.HIERARCHY_ON = False
        fresh()
        d = js("/api/rules", ["skipped", "per_rule"])
        assert d["skipped"] == {n: a.SKIP_HIERARCHY for n in sorted(a.WALKS, key=int)}
        assert not any(d["per_rule"][n] for n in a.WALKS)
        assert d["counts"]["Passing"] == sum(not d["per_rule"][n] and n not in a.WALKS for n in a.RULES)
        st, body, _ = st_react.answer("GET", "/api/rules", None, None)
        assert st == 200 and body["skipped"] == d["skipped"]
        assert js("/api/home", ["skipped"])["skipped"] == d["skipped"]  # Home says its counts leave them out
    finally:
        a.HIERARCHY_ON = old
        fresh()
    assert js("/api/rules")["skipped"] == {} and js("/api/home")["skipped"] == {}

    def slow(sql):
        raise RuntimeError("000630 (57014): Statement reached its statement or warehouse timeout of 300 second(s) and "
                           "was canceled.")
    t = a.STATEMENT_TIMEOUT
    a.STATEMENT_TIMEOUT = 300
    try:
        with snowflake(slow):
            r = c.post("/api/reload", json={"what": "rebuild"})
            assert r.status_code == 503 and r.json()["message"] == (
                "CALL D.S.SP_ACCESS_SNAPSHOT('AUTO'): stopped after 5 min by the warehouse or account "
                "STATEMENT_TIMEOUT_IN_SECONDS, not the app's STATEMENT_TIMEOUT: an admin can raise it"), r.text
    finally:
        a.STATEMENT_TIMEOUT = t


def test_progress():
    """GET /api/progress: the lines of the read from Snowflake running now (asked here from inside a direct load on a
    fake connection), none when idle; asking never starts a load; the same answer in Streamlit; the host and
    Sec-Fetch checks hold for it as for every /api/ route."""
    import st_react
    from datetime import datetime
    idle = {"running": False, "view": None, "lines": [], "job": None}
    server.PROGRESS.clear(), server.JOB.clear()
    assert js("/api/progress") == idle == st_react.answer("GET", "/api/progress", None, None)[1]
    seen = []

    def answer(sql):
        if sql.startswith("SELECT CURRENT_TIMESTAMP()"):
            return [{"T": datetime(2026, 11, 3, 10)}]
        if "GRANTS_TO_ROLES WHERE" in sql:  # the heavy read: the load is running, the page asks what it does
            seen.append(c.get("/api/progress").json())
        return []
    with snowflake(answer, direct=True) as sent:
        assert js("/api/progress") == idle and not sent  # idle with nothing loaded: asking reads nothing
        assert c.post("/api/reload", json={"what": "load"}).json()["ok"]
    p = seen[0]
    assert p["running"] and p["view"] == "shared", p
    texts = [x["text"] for x in p["lines"]]
    assert texts[0].startswith("Connected") and any("GRANTS_TO_ROLES…" in x for x in texts), texts
    assert all(isinstance(x["t"], float) for x in p["lines"])
    assert js("/api/progress") == idle  # done
    assert TestClient(server.make_app(), base_url="http://attacker.example").get("/api/progress").status_code == 400
    assert c.get("/api/progress", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403

    # Streamlit: Python is busy during the load, so st_react.shown() answers in a thread and writes the lines itself
    import time
    drawn = []
    box = type("Box", (), {"code": lambda self, t, language=None: drawn.append(t), "empty": lambda self: drawn.append("")})()

    def slow():
        a.say("step one")
        time.sleep(1.5)
        a.say("step two")
        time.sleep(1.2)
        return a.fake()
    old = server.read_shared
    server.read_shared = slow
    server.cache.drop(server.KEY)
    try:
        st, body, _ = st_react.shown(box, dict(id="p1", method="POST", url="/api/reload", body={"what": "load"}), None)
    finally:
        server.read_shared = old
        server.cache.drop(server.KEY)
    assert st == 200 and body["ok"] and drawn[-1] == "" and "step one" in drawn[0] and "step two" in drawn[-2], drawn


def test_not_read_and_caps():  # a source not read is "not read", never none; a list cut at a limit says how many
    m = js("/api/meta")
    assert m["run"]["at"] and m["mine_note"] is None and "fetched_ts" in m
    src, notes = a.run.get("SOURCES"), a.run.get("NOTES")
    try:
        a.run["SOURCES"] = {"activity": "UNAVAILABLE", "streams": "UNAVAILABLE"}
        a.run["NOTES"] = {"activity": "ACCESS_HISTORY: not authorized", "streams": "SHOW STREAMS: not authorized"}
        server.forget()  # the answers kept for this data set came before the change
        sk = a.skipped_rules()
        assert set(sk) == a.ACTIVITY_RULES | {"22"} and all(v.startswith("not read") for v in sk.values()), sk
        r = js("/api/rules")
        assert r["skipped"] == sk
        assert r["counts"]["Passing"] == sum(not r["per_rule"][n] and n not in sk for n in a.RULES)
        assert js("/api/home")["skipped"] == sk
    finally:
        a.run["SOURCES"], a.run["NOTES"] = src, notes
        server.forget()
    old = a.FUNC, a.TECH
    try:  # a big account named another way: rules 1 and 2 did not run, they do not pass
        a.FUNC, a.TECH = "QQF_", "QQT_"
        a.memo.pop("prefix_hit", None)
        assert len(a.roles) > 50 and {"1", "2"} <= set(a.skipped_rules()), a.skipped_rules()
    finally:
        a.FUNC, a.TECH = old
        a.memo.pop("prefix_hit", None)
    assert a.skipped_rules() == {}
    f = js("/api/find?q=TBL_CUSTOMER&limit=24")  # the Object page's people and admin holders, totals per Home group
    o = js("/api/object?name=SALES.CORE.TBL_CUSTOMER")["kpis"]
    hit = next(i for i in f["items"] if i["id"] == "SALES.CORE.TBL_CUSTOMER")
    assert hit["answer"] == f"{o['people']} people + {o['admin']} admin holders" and f["totals"] == {"object": f["total"]}, (hit, f["totals"])
    u = next(i for i in js("/api/find?q=ADMIN_01")["items"] if i["name"] == "ADMIN_01")
    assert u["admin"] and u["status"] == "active"
    ch = js("/api/check?name=ENGINEER_01&obj=SALES.CORE.TBL_CUSTOMER")
    assert ch["paths_total"] >= len(ch["paths"]) and "capped" in ch
    r = js("/api/rules?part=stale&limit=2&s_offset=1")
    assert r["stale_offset"] == 1 and len(r["stale"]) == 2 and r["stale_matched"] == r["stale_total"]
    assert js("/api/rules?sq=zzz")["stale_matched"] == 0
    assert len(js("/api/rules?limit=0")["stale"]) == r["stale_total"]  # the CSV: every one
    t = get("/api/flow.csv?sel=none").text  # every person of the box, not the first MAX_PATHS
    assert len(t.strip().splitlines()) - 5 == js("/api/flow?sel=none&show=graph")["follow"]["count"], t[:300]
    g, every = a.review_grid(cap=2), a.review_grid()  # people who reach only objects past the cap are rows too
    assert len(g["columns"]) == 2 and g["total"] > 2 and set(g["users"]) == set(every["users"])
    assert all(x["beyond"] >= 0 for x in g["rows"]) and sum(x["beyond"] for x in g["rows"]) > 0
    assert js("/api/home")["cards"]["changes"]["reason"] is None  # fake: a read before is kept, Changes compares on open
    js("/api/changes")
    assert js("/api/home")["cards"]["changes"]["counts"]
    assert js("/api/activity?user=ADMIN_01")["admin"]


def test_correct_answers():
    """Answers that read as safe or as a gap when they are not."""
    # admin subjects on Access: never a bare zero, the admin roles named, an admin role's own account powers listed
    adm = js("/api/access?user=ADMIN_01")
    assert adm["admin_roles"] == ["SECURITYADMIN", "SYSADMIN"]
    r = js("/api/access?role=SYSADMIN")
    assert "SYSADMIN" in r["admin_roles"] and r["counts"]["read"] == 0
    assert all(o["category"] == "account" for o in server.access_all("SYSADMIN", False, False)["objs"])
    assert js("/api/access?user=ANALYST_01")["admin_roles"] == []
    # future grants are not objects in the counts
    e = js("/api/access?user=ENGINEER_01")
    fut = [o for o in server.access_all("ENGINEER_01", True, False)["objs"] if o["label"] and o["category"] == "data"]
    assert fut and e["counts"]["future"] == len(fut) and all("<" not in h["schema"] for h in e["heat"])
    assert e["counts"]["read"] == sum(o["category"] == "data" and o["level"] and not o["label"]
                                      for o in server.access_all("ENGINEER_01", True, False)["objs"])
    assert not any(o["label"] for o in js("/api/access?user=ENGINEER_01&filter=read&limit=500")["objects"])
    # Request agrees with Can they? for an admin holder
    q = js("/api/request?name=ADMIN_01&obj=SALES.CORE.TBL_CUSTOMER")
    ch = js("/api/check?name=ADMIN_01&obj=SALES.CORE.TBL_CUSTOMER")
    assert ch["answer"]["how"] == "admin" and q["has"] and q["via_admin"] == ["SYSADMIN"] and not q["suggestions"]
    assert "SYSADMIN > " in ch["answer"]["text"] and ch["admin_paths"][0][-1] == "SALES.CORE.TBL_CUSTOMER"
    # admin roles reach only through their real links: DW's database roles sit below no admin role
    sb = "DW.SANDBOX.TBL_SANDBOX_01"
    q, ch = js(f"/api/request?name=OPS_01&obj={sb}"), js(f"/api/check?name=OPS_01&obj={sb}")
    assert not q["has"] and not q["via_admin"] and ch["verdict"] == "no" and not ch["admin_paths"]
    ch = js(f"/api/check?name=ADMIN_01&obj={sb}")
    assert ch["verdict"] == "no" and "SECURITYADMIN can grant itself anything (MANAGE GRANTS)" in ch["answer"]["text"]
    w = js(f"/api/who?name={sb}")
    assert not {"OPS_01", "ADMIN_01"} & {x["name"] for x in w["people"]}
    assert not js("/api/request?name=ANALYST_01&obj=SALES.CORE.TBL_CUSTOMER")["via_admin"]
    # Can they? No: one list of ways in (Nearest), no second disagreeing one
    no = js("/api/check?name=MARKETING_01&obj=SALES.CORE.TBL_CUSTOMER&priv=INSERT")
    assert no["verdict"] == "no" and "ask" not in no and "closest" not in no
    # typed names in any case
    lo = js("/api/check?name=engineer_01&obj=sales.core.tbl_customer")
    assert lo["user"] == "ENGINEER_01" and lo["object"] == "SALES.CORE.TBL_CUSTOMER"
    assert js(f"/api/check?name={a.FUNC.lower()}marketing&obj=sales.core.tbl_customer")["subject"]["user"] is False
    # Granted vs used: an orphan role suggests no revoke; nobody holds it
    u = js(f"/api/usage?role={a.FUNC}LEGACY_REPORTING")  # rule 13 on the fake data
    assert u["people"] == 0 and u["counts"]["changes"] == 0 and not u["changes"] and all(x["suggest"] == "none" for x in u["rows"])
    # Risks CSV: the screen's filters, the worst severity by default, a few paths per finding
    scr = js("/api/rules")
    rows = lambda t: [x for x in t.strip().splitlines()[4:] if x][1:]
    t = get("/api/rules.csv").text
    assert len(rows(t)) == scr["total"] and scr["filters"]["sev"] in t.splitlines()[0]
    hi = js("/api/rules?sev=High&q=analyst")
    assert len(rows(get("/api/rules.csv?sev=High&q=analyst").text)) == hi["total"] < js("/api/rules?sev=High")["total"]
    assert "Path count" in t.splitlines()[4]
    # Review: Hide USAGE rows hides them, tiles follow the search, the database with sensitive data first
    on, off = js("/api/review?db=*&part=all&limit=1000"), js("/api/review?db=*&part=all&hideusage=0&limit=1000")
    assert on["kpis"]["hidden_usage"] > 0 and on["total"] == off["total"] - on["kpis"]["hidden_usage"]
    assert not any(r["type"] in ("DATABASE", "SCHEMA") for r in on["rows"] if not r["admin"])
    assert on["kpis"]["rows"] == on["counts"]["all"] and on["kpis"]["csv_rows"] == off["kpis"]["rows"]
    s1 = js("/api/review?db=*&part=all&q=analyst_01")
    assert s1["kpis"]["rows"] == s1["counts"]["all"] < on["kpis"]["rows"] and s1["kpis"]["users"] <= 2
    d = js("/api/review")
    sens = Counter(a.split_name(o)[0] for o in server.S["sens"])
    assert sens[d["filters"]["db"]] == max(sens.values()) and d["part"] == "sens" and d["note"] is None
    plain = next(x for x in sorted({a.split_name(o)[0] for o in a.objects} - {""}) if not sens[x])
    p = js(f"/api/review?db={plain}&part=sens")
    assert p["part"] == "all" and plain in p["note"]
    # Sensitive data: who sees clear next to who can read; an admin-only reader has no object count
    sp = js("/api/sensitive?show=catalog")
    cat = {x["object"]: x for x in sp["catalog"]}
    v = cat["SALES.MART.VW_CUSTOMER"]
    assert v["status"] == "protected" and v["clear"] < v["readers"]
    assert all(x["clear"] == x["readers"] for x in sp["catalog"] if x["unmasked"] or x["status"] == "whole")
    assert all(o["clear"] == cat[o["object"]]["clear"] for o in sp["objects"])
    via = [x for x in js("/api/sensitive?limit=0")["readers"] if x["via_admin"]]
    n = js("/api/sensitive")["kpis"]["objects"]  # an admin reader counts what its admin roles reach, not every object
    assert via and all(0 < x["objects"] <= n and "SYSADMIN" in x["path"] for x in via)
    assert js("/api/sensitive?people=1")["kpis"] == js("/api/sensitive")["kpis"]



def test_answer_first():  # each screen's answer: the grant on Can they?, one reader count, row policy roles, who filters
    from urllib.parse import quote
    n = js("/api/check?name=FIN_09&obj=HR.PEOPLE.TBL_EMPLOYEE&do=read&near=1")["nearest"]
    one = [x for x in n if x["cost"] == 1]
    assert one and all(x["change"]["sql"].startswith("GRANT ") and x["role"] in x["change"]["sql"] for x in one)
    assert all(x["change"] is None for x in n if x["cost"] > 1)
    s = js("/api/sensitive")
    assert s["kpis"]["readers"] == s["readers_total"]  # the tile and the Who can read tab count the same users
    k = s["kpis"]
    assert k["readers"] == k["people"] + k["disabled"] + k["service"] + k["admin"]
    r = {x["object"]: x for x in s["row_list"]}
    assert r["FINANCE.REPORT.TBL_REVENUE"]["sensitive"] and r["FINANCE.REPORT.TBL_REVENUE"]["readers"] > 0
    assert r["SALES.CLEAN.TBL_ORDER"]["all_rows"] and r["SALES.CLEAN.TBL_ORDER"]["some_rows"] and not r["SALES.RAW.TBL_ORDER_RAW"]["known"]
    q = js("/api/sensitive?t_q=rap_region")
    assert [x["object"] for x in q["row_list"]] == ["FINANCE.REPORT.TBL_REVENUE"] and q["row_total"] == 1
    o = "SALES.CORE.TBL_CUSTOMER"
    w, d = js(f"/api/who?name={o}"), js(f"/api/object?name={o}")
    assert w["counts"]["people"] == sum(d["kpis"][x] for x in ("people", "disabled", "service", "admin")) == d["matrix"]["total"]
    assert sum(w["counts"]["states"].values()) == w["counts"]["people"]
    for st, n in w["counts"]["states"].items():
        f = js(f"/api/who?name={o}&st={st}")
        assert f["st"] == st and f["shown"]["people"] == n and all(x["state"] == st for x in f["people"])
    lv = [x["level"] for x in w["people"]]
    for l in set(lv):  # active first within a level
        xs = [x["status"] != "active" for x in w["people"] if x["level"] == l]
        assert xs == sorted(xs)
    ch = quote(json.dumps([{"op": "drop_role", "role": a.FUNC + "ENGINEER"}]))
    g = js(f"/api/whatif?changes={ch}")["groups"]
    assert g and all(x["where_total"] >= len(x["where"]) and len(x["text"]) < 120 for x in g)
    plan = [{"op": "drop_role", "role": a.FUNC + "ENGINEER"}]
    full, one = a.what_if(plan, None)["users"], a.what_if(plan, 1)["users"]  # places count every object, not the listed ones
    assert [u["lost_where"] for u in one] == [u["lost_where"] for u in full]
    assert all(sum(w["objects"] for w in u["lost_where"]) == u["objects"] for u in full)
    assert any(len(u["lost_rows"]) < u["objects"] for u in one)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("test_server green")

