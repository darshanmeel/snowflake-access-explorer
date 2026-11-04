import json
"""server.py on the fake data: every endpoint answers 200 with the keys of web/API.md. Run: python test_server.py"""
import os

os.environ["FAKE"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

c = TestClient(server.make_app())
a = server.a

USER = {"view", "user", "filters", "banners", "findings", "findings_total", "kpis", "account", "graph", "tabs", "privileges",
        "roles", "multi", "can_read", "sensitive", "granted", "usage", "capped", "refs"}
ROLE = {"view", "role", "filters", "kpis", "scope_kpis", "banners", "findings", "readonly_writes", "account", "graph", "held_by",
        "holds", "tabs", "privileges", "roles", "can_read", "capped", "refs"}
OBJECT = {"view", "object", "filters", "kpis", "admin_paths", "sensitivity", "matrix", "graph", "sees", "tabs", "grantees",
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
        assert gid in ids and x["nodes"] and x["count"] >= len(x["nodes"]) - x["truncated"], gid


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
    assert {r["tab"] for r in d["privileges"]} <= set(keys)
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


def test_role():
    d = js("/api/role?name=F_ENGINEER", ROLE)
    graph_ok(d["graph"])
    assert d["held_by"]["rows"] and d["kpis"]["effective"]
    t = js("/api/role?name=T_SALES_CORE_READ", ROLE)
    assert t["holds"]["types"] and t["holds"]["types"][0]["rows"][0]["cells"]
    assert js(f"/api/role?name=F_ENGINEER&cut={d['filters']['cuts'][0]}")["held_by"]["revoke"]
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
    graph_ok(d["graph"])
    assert d["tabs"][-1]["key"] == "all"
    js(f"/api/object?name={t}&priv=SELECT&users=1&active=1", OBJECT)
    get("/api/object?name=NOPE", 404)


def test_check():
    d = js("/api/check", ["answer", "paths", "graph", "privileges", "refs", "options", "ask"])
    assert d["answer"]["yes"] and d["paths"]
    graph_ok(d["graph"])
    no = js("/api/check?name=ANALYST_01&obj=HR.PEOPLE.TBL_EMPLOYEE&priv=DELETE")
    assert no["answer"]["how"] in ("none", "paths", "owner", "admin")
    for u in a.users:
        js(f"/api/check?name={u}")
    get("/api/check?name=NOPE", 404)


def test_sensitive_rules_review():
    d = js("/api/sensitive", ["state", "kpis", "objects", "readers", "compare", "filters", "refs"])
    assert d["state"] == "ok" and d["objects"] and d["readers"]
    js(f"/api/sensitive?people=1&db={d['filters']['dbs'][0]}")
    r = js("/api/rules", ["counts", "per_rule", "findings", "total", "admins", "rows_unknown", "refs"])
    assert r["total"] and r["admins"] and r["counts"]["High"]
    assert len(r["per_rule"]) == len(a.RULES) and {f["num"] for f in r["findings"]} == {k for k, v in r["per_rule"].items() if v}
    js("/api/rules?sev=High&rule=4")
    f = r["findings"][0]
    assert f["grantee"] and {"num", "severity", "what", "impact", "paths", "iac", "sql"} <= set(f)
    csv = get("/api/rules.csv")
    assert csv.headers["content-type"].startswith("text/csv") and "Rule checks" in csv.text
    rv = js("/api/review?db=*", ["filters", "kpis", "rows", "refs"])
    assert rv["rows"] and rv["kpis"]["rows"] == len(rv["rows"])
    db = rv["filters"]["dbs"][0]
    assert js(f"/api/review?db={db}&hideusage=0")["kpis"]["hidden_usage"] == 0
    cv = get(f"/api/review.csv?db={db}")
    assert "access_review_" in cv.headers["content-disposition"] and "Keep/Revoke" in cv.text
    get("/api/review?db=NOPE", 404)


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
    other = TestClient(server.make_app())  # another browser: nothing loaded
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
    assert ans("/api/review.csv?db=*")[1].startswith(c.get("/api/review.csv?db=*").text[:40])
    assert ans("/api/reload", {"what": "page"})[1]["ok"]
    st, mine, sid = ans("/api/mine/load", {})
    assert st == 200 and sid and ans("/api/mine", sid=sid)[1]["loaded"]


def test_whatif():
    from urllib.parse import quote
    ch = quote(json.dumps([{"op": "drop_role", "role": a.FUNC + "ANALYST"}]))
    d = js(f"/api/whatif?changes={ch}", ["changes", "summary", "counts", "users", "objects", "roles", "findings", "iac", "sql", "refs"])
    assert d["counts"]["users"] and d["users"][0]["lost_rows"] and "DROP ROLE" in d["sql"]
    assert "What if" in get(f"/api/whatif.csv?changes={ch}").text
    get("/api/whatif?changes=nope", 400)
    get("/api/whatif?changes=" + quote(json.dumps([{"op": "drop_role", "role": "NOPE"}])), 400)


def test_read_only():  # the only write-like statement is the snapshot CALL
    src = open(server.__file__, encoding="utf-8").read()
    assert "SP_ACCESS_SNAPSHOT" in src and not any(w in src for w in ("cur.execute(f\"GRANT", "REVOKE ROLE"))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("test_server green")
