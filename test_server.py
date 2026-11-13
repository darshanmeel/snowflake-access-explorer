"""server.py on the fake data: every endpoint answers 200 with the keys of web/API.md. Run: python test_server.py"""
import json
import os
import re
from contextlib import contextmanager

os.environ["FAKE"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

c = TestClient(server.make_app(), base_url="http://localhost")
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
        js(f"/api/check?name={u}", ["verdict", "held", "lanes", "cut", "cuts", "nearest", "layers", "roles_count"])
    get("/api/check?name=NOPE", 404)
    y = js("/api/check?name=ENGINEER_01&obj=HR.PEOPLE.TBL_EMPLOYEE")
    assert y["verdict"] == "yes" and y["lanes_total"] == 2 and y["cut"] == [a.FUNC + "ENGINEER", "HR.SC_W_PEOPLE"]
    assert len(y["cuts"]) == 2 and y["cuts"][0]["people"] == ["ENGINEER_01"] and y["cuts"][0]["lost"] < y["cuts"][1]["lost"]
    assert {x["privilege"] for x in y["held"] if x["held"]} == {"SELECT", "INSERT", "UPDATE"} and y["approver"] == "HR data owner"
    n = js("/api/check?name=FIN_09&obj=HR.PEOPLE.TBL_EMPLOYEE&do=read")
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
    rn = js(f"/api/check?role={a.FUNC}ANALYST&obj={e}&do=read")
    assert rn["verdict"] == "no" and rn["nearest"] and all(x["to"] == a.FUNC + "ANALYST" and not x["to_user"] for x in rn["nearest"])
    assert js(f"/api/check?name={m}&obj={e}")["subject"]["user"] is False  # Home's "can F_MARKETING read ..."
    assert js("/api/check?user=ENGINEER_01")["subject"]["user"] is True
    adm = js(f"/api/check?role=SYSADMIN&obj={e}")
    assert adm["answer"]["how"] in ("admin", "paths", "owner") and adm["verdict"] != "no"
    get("/api/check?role=NOPE", 404)
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
    assert js("/api/request?name=FIN_09&role=NOPE")["asked"] is None
    js("/api/request", keys)
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


def test_whatif():
    from urllib.parse import quote
    ch = quote(json.dumps([{"op": "drop_role", "role": a.FUNC + "ANALYST"}]))
    d = js(f"/api/whatif?changes={ch}", ["changes", "summary", "counts", "users", "objects", "roles", "findings", "iac", "sql", "refs"])
    assert d["counts"]["users"] and d["users"][0]["lost_rows"] and "DROP ROLE" in d["sql"]
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
        def execute(self, sql):
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
    try:
        yield sent
    finally:
        server.MODE, server.DIRECT, server.WHERE, server.connect, server.cache.HOURS = old
        server.cache.MEM.pop(server.KEY, None)


def test_read_only():
    """Every statement the app sends, recorded at the connection (sf.rows): reads only, plus the snapshot CALL. The fake
    answers every read, so each load runs to the end (200) and all its statements are checked."""
    import test_access
    d = a.fake()
    show, _ = test_access.fake_snowflake(d, True)
    me = d["USER_ROLE"][0]["USER_NAME"]
    mine = [x["ROLE_NAME"] for x in d["USER_ROLE"] if x["USER_NAME"] == me]
    table = re.compile(r"SELECT \* FROM D\.S\.TBL_ACCESS_(\w+) WHERE")

    def answer(sql):
        if "SP_ACCESS_SNAPSHOT" in sql:
            return [{"R": json.dumps({"status": "OK", "notes": {}})}]
        if ".TBL_ACCESS_RUN " in sql:
            return [{"RUN_ID": "r1", "FINISHED_AT": "2026-11-03 10:00", "SOURCES": "{}", "NOTES": "{}"}]
        if table.match(sql):
            return [dict(x) for x in d.get(table.match(sql)[1]) or []]
        if sql.startswith("SELECT CURRENT_USER()"):
            return [{"U": me}]
        if sql.startswith("SELECT CURRENT_AVAILABLE_ROLES()"):
            return [{"R": json.dumps(mine)}]
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


def test_rebuild_outcome():
    """Rebuild snapshot says what the procedure returned: FAILED or SKIPPED is no success, and the copy stays."""
    for res, ok, word in (({"status": "FAILED", "notes": {"error": "x broke"}}, False, "Snapshot failed: x broke"),
                          ({"status": "SKIPPED", "notes": {"error": "run 7 is still running"}}, False, "Snapshot skipped: run 7"),
                          ({"status": "OK", "notes": {}}, True, "Snapshot rebuilt.")):
        with snowflake(lambda sql, res=res: [{"R": json.dumps(res)}]):
            server.cache.MEM[server.KEY] = (a.fake(), 0)
            r = c.post("/api/reload", json={"what": "rebuild"}).json()
            assert r["ok"] is ok and r["message"].startswith(word) and (server.KEY in server.cache.MEM) is not ok, r

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
    assert n["people"] == len(d["people"]) == sum(n["levels"].values()) and n["levels"]["admin"] == 2, n
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
    n = d["counts"]
    assert (n["read"], n["change"], n["own"], n["sensitive"], n["runnable"], n["usage"]) == (6, 5, 2, 3, 4, 8), n
    powers = {(x["privileges"][0], x["object"]) for x in d["objects"] if x["category"] == "account"}
    assert powers == {("EXECUTE TASK", "ACCOUNT"), ("VIEW LINEAGE", "ACCOUNT"), ("CREATE TABLE", "SALES.CORE")}, powers
    log = next(x for x in d["objects"] if x["object"] == "SHARED.LOGGING.TBL_LOGGING")
    assert log["findings"][0] == dict(num="17", severity="High", label="read role can write") and log["level"] == "change"
    wh = next(x for x in d["objects"] if x["object"] == "WH_SALES_XS")
    assert "2" in {f["num"] for f in wh["findings"]}
    data = [x["object"] for x in d["objects"] if x["category"] == "data"]
    assert len(data) == len(set(data))  # each object once
    assert d["why"][0]["note"] == "default" and d["who"]["secondary_all"]
    r = js(f"/api/access?role={a.FUNC}ENGINEER")
    assert r["who"]["held_by"]["users"] >= 1 and r["counts"]["read"] == 6
    get("/api/access?user=NOPE", 404)
    h = js("/api/home", ["me", "risks", "protection", "counts"])
    assert h["me"]["counts"]["read"] == 6 and h["risks"]["High"] > 0 and h["protection"]["unmasked"] == 3
    assert js("/api/home?view=mine")["risks"] is None
    g = {p["key"]: p["group"] for p in js("/api/meta")["pages"]}
    assert g["home"] == g["access"] == "answers" and g["rules"] == "admin"


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
    c = js("/api/compare", ["a", "b", "scope", "rows", "counts", "match", "extras", "old", "dbs"])
    assert c["a"]["name"] == server.DEMO_USER and c["b"]["name"] != c["a"]["name"] and c["scope"] == "sensitive"
    assert all(ch["sql"] and "roleDb" in ch and "toDb" in ch for ch in c["match"] + c["extras"])  # SQL from access.with_sql
    assert sum(c["counts"].values()) == len(c["rows"]) and c["old"]["rows"]
    x = js(f"/api/compare?a={a.FUNC}DEPLOY&b={a.FUNC}MARKETING&scope=all")
    assert x["counts"]["only_a"] > 0 and x["match"] and x["extras"] and x["a"]["kind"] == "functional"
    assert js("/api/compare?a=ENGINEER_01&b=ANALYST_01&scope=db&db=HR")["rows"][0]["diff"] == "only_a"
    get("/api/compare?a=NOPE", 404)
    g = {p["key"]: p["group"] for p in js("/api/meta")["pages"]}
    assert g["graph"] == g["see"] == g["compare"] == "answers"


def test_risks_plan():  # screens 5, 10, 11: findings carry their fix as What if changes; the plan runs as /api/whatif
    from urllib.parse import quote
    r = js("/api/rules")
    assert all({"changes", "objects"} <= f.keys() for f in r["findings"])
    fx = [f for f in r["findings"] if f["changes"]]
    assert fx and any(not f["changes"] for f in r["findings"])
    w = js("/api/whatif?changes=" + quote(json.dumps([ch for f in fx[:3] for ch in f["changes"]])))
    assert w["counts"]["fixed"] >= 1 and w["sql"] and "REVOKE" in w["sql"]
    m = js("/api/meta")
    assert len(m["rules"]) == 28 and all(x["meaning"] and x["fix"] and x["area"] for x in m["rules"])
    assert {p["key"]: p["group"] for p in m["pages"]}["whatif"] == "admin"


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
    get("/api/grid?object=NOPE&columns=privileges", 404)
    get("/api/grid?scope=db&db=NOPE", 404)
    try:
        server.grid_page({}, "mine")
        assert False, "grid on My access"
    except server.ApiError as x:
        assert x.status == 400
    s = js("/api/sensitive", ["catalog"])
    assert [r["status"] for r in s["catalog"]][:2] == ["not", "partly"] and s["catalog"][0]["columns"]
    assert len(js("/api/sensitive?db=FINANCE")["catalog"]) == 2
    f = js("/api/flow", ["state", "groups", "roles", "objects", "links", "select", "refs"])
    assert f["state"] == "ok" and f["select"] == "risky" and f["roles"][0]["kind"] == "admin"
    assert server.flow_page({}, "mine")["state"] == "mine"
    m = {p["key"]: p["group"] for p in js("/api/meta")["pages"]}
    assert m["flow"] == m["review"] == m["sensitive"] == "admin"
    assert "flow" not in {p["key"] for p in js("/api/meta?view=mine")["pages"]}


def test_usage_changes():  # screens 13, 14
    u = js("/api/usage?user=ENGINEER_01", ["who", "days", "periods", "available", "rows", "weeks", "counts", "changes", "refs"])
    assert u["available"] and u["days"] == 90 and u["periods"] == [30, 90, 180] and u["source"] == "demo values"
    assert u["rows"][0]["suggest"] == "drop" and u["counts"]["changes"] == len(u["changes"]) > 0
    assert u["sql"].startswith("REVOKE ") and js("/api/usage?user=ENGINEER_01&days=30")["sql"]  # the trim, from access.py
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
    assert m["usage"] == m["changes"] == "admin" and "changes" not in {p["key"] for p in js("/api/meta?view=mine")["pages"]}


def test_activity():  # the Activity tab of an object, a person and a role; why there is none
    o = js("/api/activity?name=SALES.CORE.TBL_CUSTOMER", ["what", "days", "available", "daily", "by", "rows", "ddl", "findings"])
    assert o["what"] == "object" and o["available"] and len(o["daily"]) == o["days"] == a.ACTIVITY_DAYS
    assert [f["num"] for f in o["findings"]] == ["24"] and o["ddl"][0]["type"] == "ALTER_TABLE_ADD_COLUMN"
    assert {f["num"] for f in js("/api/activity?user=ENGINEER_01")["findings"]} == {"24", "27"}
    assert js("/api/activity?role=SYSADMIN")["by"]["user"][0]["key"] == "OPS_01"
    assert {r["area"] for r in js("/api/meta")["rules"] if int(r["num"]) >= 24} == {"Activity"}


API = {"graph": "map", "whatif": 'whatif?changes=[{"op":"empty_public"}]'}  # page key -> its endpoint, when they differ


def test_every_page():  # every page key: a label, a nav group, an endpoint that answers shared and (if not shared-only) mine
    assert set(server.PAGES) == set(server.GROUP) and set(server.GROUP.values()) == {"answers", "admin", "detail"}
    assert server.SHARED_ONLY <= set(server.PAGES) and all(server.GROUP[k] == "admin" for k in server.SHARED_ONLY)
    assert c.post("/api/mine/load").status_code == 200
    mine = {p["key"] for p in js("/api/meta?view=mine")["pages"]}
    assert mine == set(server.PAGES) - server.SHARED_ONLY
    for k in server.PAGES:
        e = API.get(k, k)
        assert e.split("?")[0] in server.ROUTES and ("refs" in js(f"/api/{e}") or k == "home"), k
        if k in mine:
            get(f"/api/{e}{'&' if '?' in e else '?'}view=mine")


def test_review_fixes():  # search answers, row policy list, defaults that exist, compare without users
    f = {i["id"]: i for i in js("/api/find?q=ENGINEER_01")["items"]}
    me = js("/api/home")["me"]
    n = me["counts"]
    assert f[me["user"]]["answer"] == f"reads {n['read']} · changes {n['change']} · owns {n['own']}"
    wh = next(i for i in js("/api/find?q=WH_")["items"] if i["type"] == "WAREHOUSE")
    assert wh["answer"].endswith("access") and wh["answer"][0].isdigit()
    rl = js("/api/home")["protection"]["row_list"]
    assert [r["object"] for r in rl] == sorted(a.row_tables()) and len(rl) == js("/api/home")["protection"]["row_tables"]
    old = server.DEMO_USER
    try:
        server.DEMO_USER = "NOBODY_HERE"
        assert js("/api/who?name=SALES.CORE.TBL_CUSTOMER")["default_user"] == a.users[0]
    finally:
        server.DEMO_USER = old
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


def test_cache_lock():
    """A memory hit never waits for another key's read, and a drop during a read of its key wins."""
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


def test_csv_formula():
    import server
    t = server.csv_text(["o", "n"], [["=HYPERLINK(1)", "-3"], ["@x", 5], ["T", "+1.5"]])
    assert t.splitlines()[1:] == ["'=HYPERLINK(1),-3", "'@x,5", "T,+1.5"], t


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("test_server green")

