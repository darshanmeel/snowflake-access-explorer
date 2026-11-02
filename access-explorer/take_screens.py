"""Screenshots of the running demo app (DuckDB), light and dark, into OUT; zipped to ZIP when given. Needs playwright + Edge.
    $env:DUCKDB="demo.duckdb"; streamlit run app.py --server.port 8599   (other terminal)
    python take_screens.py screens [zip path]"""
import sys
import time
import zipfile
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

import access as a

OUT = sys.argv[1]
ZIP = sys.argv[2] if len(sys.argv) > 2 else None
URL = "http://localhost:8599/?"
C = "SALES.CORE.TBL_CUSTOMER"
SCREENS = [  # name, what, query
    ("01_user", "User: access through a group role, depth lanes, paths", dict(page="user", name="ANALYST_01")),
    ("02_user_deep", "User: grant 10 role hops deep", dict(page="user", name="FIN_01")),
    ("03_user_admin", "User: red banner for admin roles and account-level privileges", dict(page="user", name="ADMIN_01")),
    ("04_role", "Role: who holds it (up) and what it holds (down)", dict(page="role", name=a.TECH + "SALES_CORE_READ")),
    ("05_object", "Object: who can touch a table, matrix, all grantees", dict(page="object", name=C)),
    ("06_object_collapsed", "Object: 15 users, lane collapsed to +N more", dict(page="object", name="FINANCE.REPORT.TBL_REVENUE")),
    ("07_object_expanded", "Object: the same lane expanded", dict(page="object", name="FINANCE.REPORT.TBL_REVENUE", expand="0")),
    ("08_can_yes", "Can they?: yes, every path, choke point", dict(page="check", name="ENGINEER_01", priv="SELECT", obj=C)),
    ("09_can_no", "Can they?: no, closest route", dict(page="check", name="ENGINEER_01", priv="OWNERSHIP", obj=C)),
    ("10_rules", "Rule checks: all findings", dict(page="rules")),
]
done = []


def settle(page):
    page.wait_for_selector("[data-testid='stApp']")
    time.sleep(1)
    page.wait_for_selector(".ae-sk", state="detached", timeout=30000)  # skeleton gone = page drawn
    time.sleep(1.5)


def shot(page, name, what):
    h = page.evaluate("document.querySelector('[data-testid=stMain]').scrollHeight")  # the app scrolls inside stMain
    page.set_viewport_size({"width": 1440, "height": h})
    time.sleep(1)
    page.screenshot(path=f"{OUT}/{name}.png", full_page=True)
    errs = page.locator("[data-testid='stException']").count()
    done.append((name, what, errs))
    print(name, "exceptions:", errs)
    page.set_viewport_size({"width": 1440, "height": 1000})


with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    for theme in ("light", "dark"):
        page = b.new_page(viewport={"width": 1440, "height": 1000})
        for name, what, query in SCREENS:
            page.goto(URL + urlencode(query | {"theme": theme}))
            settle(page)
            shot(page, f"{name}_{theme}", f"{what} ({theme})")
        page.goto(URL + urlencode({"page": "user", "theme": theme}))
        settle(page)
        page.get_by_text("My access (live, only me)", exact=True).click()
        time.sleep(2)
        page.get_by_role("button", name="Load my access").click()
        settle(page)
        shot(page, f"11_my_access_{theme}", f"My access: own roles only, nothing saved, no refresh ({theme})")
        page.close()
    page = b.new_page(viewport={"width": 390, "height": 844})  # phone: the page, not the sidebar, must show
    page.goto(URL + urlencode({"page": "user", "name": "ANALYST_01"}))
    settle(page)
    seen = page.evaluate("(() => { const h = document.querySelector('.ae-h1').getBoundingClientRect();"
                         " const el = document.elementFromPoint(h.left + 10, h.top + h.height / 2);"
                         " return !!el && !!el.closest('[data-testid=stMain]'); })()")
    wide = page.evaluate("document.documentElement.scrollWidth")
    page.screenshot(path=f"{OUT}/12_narrow_user.png")
    print("narrow: main content visible", seen, "page width", wide)
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
assert len(done) == 2 * (len(SCREENS) + 1) and not bad
