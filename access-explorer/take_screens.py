"""Screenshots of the running demo app (DuckDB), light and dark, into OUT; zipped to ZIP when given. Needs playwright + Edge.
    $env:DUCKDB="demo.duckdb"; streamlit run app.py --server.port 8599   (other terminal)
    python take_screens.py screens [zip path]
BIG=1 adds the big-account screens (grouped graph, drill-down) from a second app on port 8598:
    $env:BIG="1"; python make_demo_db.py; $env:DUCKDB="big.duckdb"; streamlit run app.py --server.port 8598"""
import os
import sys
import time
import zipfile
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

import access as a

OUT = sys.argv[1]
ZIP = sys.argv[2] if len(sys.argv) > 2 else None
URL = "http://localhost:8599/?"
BIG_URL = "http://localhost:8598/?" if os.environ.get("BIG") == "1" else None
C, R = "SALES.CORE.TBL_CUSTOMER", "FINANCE.REPORT.TBL_REVENUE"
SCREENS = [  # name, what, query, card to also capture on its own (container key) or None
    ("01_user", "User: access through a group role, depth lanes, paths", dict(page="user", name="ANALYST_01"), None),
    ("02_user_deep_fit", "User: grant 10 roles deep, graph fit to width",
     dict(page="user", name="FIN_01", fit="1"), "card_graph"),
    ("03_user_deep_scroll", "User: the same graph at full size, scroll sideways", dict(page="user", name="FIN_01"),
     "card_graph"),
    ("04_user_sensitive", "User: sensitive data by granted role, difference banner", dict(page="user", name="ENGINEER_01"),
     "card_sensitive"),
    ("05_user_admin", "User: red banner for admin roles and account-level privileges", dict(page="user", name="ADMIN_01"),
     None),
    ("06_role", "Role: who holds it (up) and what it holds (down)", dict(page="role", name=a.TECH + "SALES_CORE_READ"),
     None),
    ("07_role_group", "Role: a group role with no grants of its own, inherited privileges",
     dict(page="role", name="GRP_EMEA_ALL"), "card_effective"),
    ("08_object", "Object: sensitivity card, matrix, coloured privilege arrows", dict(page="object", name=C), "card_graph"),
    ("09_object_collapsed", "Object: 17 users, lane collapsed to +N more", dict(page="object", name=R), None),
    ("10_object_expanded", "Object: the same lane expanded", dict(page="object", name=R, expand="0"), None),
    ("11_can_yes", "Can they?: yes, every path, removal options",
     dict(page="check", name="ENGINEER_01", priv="SELECT", obj=C), None),
    ("12_can_no", "Can they?: no, roles to ask for", dict(page="check", name="ANALYST_01", priv="INSERT", obj=C), None),
    ("13_rules", "Rule checks: all rules and findings", dict(page="rules"), None),
    ("14_rules_high", "Rule checks: High findings only", dict(page="rules", sev="High"), None),
    ("15_sensitive", "Sensitive data: objects, readers, role comparison",
     dict(page="sensitive", a=a.FUNC + "ENGINEER", b=a.FUNC + "ANALYST"), "card_compare"),
    ("16_review", "Access review: SALES, for sign-off", dict(page="review", db="SALES"), None),
    ("19_user_schema", "User: schema drill-down, roles and objects of SALES.PIPELINE only",
     dict(page="user", name="SVC_DEPLOY", schema="SALES.PIPELINE"), "card_graph"),
    ("20_role_holds", "Role: has / lacks grid of a read role, arrows with Has / Lacks",
     dict(page="role", name=a.TECH + "SALES_CORE_READ"), "card_holds"),
    ("21_rule_hits", "Role: graph with rule breaks highlighted (read-only role writes)",
     dict(page="role", name=a.FUNC + "FINANCE_REPORTING"), "card_graph"),
    ("22_rules_23", "Rule checks: rule 22 open, 23 rules on the map", dict(page="rules", rule="22"), None),
    ("23_object_sees", "Object: what each role sees (rows, masked columns)",
     dict(page="object", name="FINANCE.REPORT.TBL_REVENUE"), "card_sees"),
    ("24_object_task", "Object: a task with OPERATE, new object type", dict(page="object", type="TASK"), "card_graph"),
    ("25_user_pipeline", "User: tasks, streams, stages and warehouses in the graph", dict(page="user", name="ENGINEER_01"),
     "card_graph"),
]
BIG = [  # big account (big.duckdb, port 8598)
    ("30_big_grouped", "Big account: 2,000 objects grouped by database", dict(page="user", name="BIG_01"), "card_graph"),
    ("31_big_database", "Big account: one database, grouped by schema", dict(page="user", name="BIG_01", schema="DB0"),
     "card_graph"),
    ("32_big_schema", "Big account: one schema drill-down", dict(page="user", name="BIG_01", schema="DB0.S1"),
     "card_graph"),
]
done = []


def settle(page):
    page.wait_for_selector("[data-testid='stApp']")
    time.sleep(1)
    page.wait_for_selector(".ae-sk", state="detached", timeout=30000)  # skeleton gone = page drawn
    page.wait_for_selector(".ae-crumb", timeout=30000)  # the top bar comes after the data: a rerun is over
    time.sleep(1.5)


def shot(page, name, what, card=None):
    # the app scrolls inside an inner element: the tallest scrollHeight is the page height
    h = page.evaluate("[...document.querySelectorAll('*')].reduce((m, e) => Math.max(m, e.scrollHeight), 0)")
    page.set_viewport_size({"width": 1440, "height": min(h + 50, 16000)})
    time.sleep(1)
    page.wait_for_selector(".ae-crumb", timeout=30000)
    page.screenshot(path=f"{OUT}/{name}.png", full_page=True)
    if card:
        page.locator(f".st-key-{card}").first.screenshot(path=f"{OUT}/{name}_card.png")
    errs = page.locator("[data-testid='stException']").count()
    done.append((name, what, errs))
    print(name, "exceptions:", errs)
    page.set_viewport_size({"width": 1440, "height": 1000})


with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    for theme in ("light", "dark"):
        page = b.new_page(viewport={"width": 1440, "height": 1000})
        for name, what, query, card in SCREENS + ([(n, w, q | {"_big": 1}, c) for n, w, q, c in BIG] if BIG_URL else []):
            base = BIG_URL if query.pop("_big", None) else URL
            page.goto(base + urlencode(query | {"theme": theme}))
            settle(page)
            shot(page, f"{name}_{theme}", f"{what} ({theme})", card)
        page.goto(URL + urlencode({"page": "user", "theme": theme}))
        settle(page)
        page.get_by_text("My access (live, only me)", exact=True).click()
        time.sleep(2)
        page.get_by_role("button", name="Load my access").click()
        settle(page)
        shot(page, f"17_my_access_{theme}", f"My access: own roles only, nothing saved ({theme})")
        page.close()
    page = b.new_page(viewport={"width": 390, "height": 844})  # phone: the page, not the sidebar, must show
    page.goto(URL + urlencode({"page": "user", "name": "ANALYST_01"}))
    settle(page)
    seen = page.evaluate("(() => { const h = document.querySelector('.ae-h1').getBoundingClientRect();"
                         " const el = document.elementFromPoint(h.left + 10, h.top + h.height / 2);"
                         " return !!el && !!el.closest('[data-testid=stMain]'); })()")
    wide = page.evaluate("document.documentElement.scrollWidth")
    page.screenshot(path=f"{OUT}/18_narrow_user.png")
    errs = page.locator("[data-testid='stException']").count()
    done.append(("18_narrow_user", "Phone, 390 px", errs))
    print("narrow: main content visible", seen, "page width", wide, "exceptions:", errs)
    assert seen and wide <= 390, "phone view: sidebar covers the page or the page scrolls sideways"
    page.close()
    b.close()

if ZIP:
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for name, what, errs in done:
            z.write(f"{OUT}/{name}.png", f"access-explorer-screens/{name}.png")
        z.writestr("access-explorer-screens/README.txt",
                   "Snowflake access explorer: screenshots on fake data (DuckDB demo, same tables as Snowflake)\n\n"
                   + "\n".join(f"{n}.png  {w}" for n, w, _ in done) + "\n")
    print("zip:", ZIP)
bad = [n for n, _, errs in done if errs]
print(len(done), "screens; with exceptions:", bad)
assert len(done) == 2 * (len(SCREENS) + len(BIG) * bool(BIG_URL) + 1) + 1 and not bad
