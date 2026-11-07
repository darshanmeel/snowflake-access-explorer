"""Fill the generated parts of README.html between <!--map:NAME--> markers.
    python docs/make_readme.py
overview, flow: boxes on a fixed canvas plus one SVG arrow layer (straight arrows only, never through a box).
rules: titles and severities from access.py, areas from server.RULE_INFO. The rest of README.html is plain HTML."""
import pathlib
import re
import sys
from html import escape

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import access as a  # noqa: E402
import server  # noqa: E402

# L0 overview: 1080 x 440 canvas (fits the 1084 px card), 20 px grid, 120 px between boxes
C0, R0 = [0, 300, 600, 900], [40, 180, 340]
# id: (kind, x, y, w, h, eyebrow, name, sub)
OVERVIEW = {
    "dev": ("actor", C0[1], R0[0], 180, 60, "", "Developer or app user", "CALL or Rebuild button"),
    "sf": ("data", C0[0], R0[1], 180, 80, "DATA", "Snowflake", "ACCOUNT_USAGE · SHOW"),
    "sp": ("code", C0[1], R0[1], 180, 80, "PROCEDURE", "SP_ACCESS_SNAPSHOT", "owner's rights"),
    "tbl": ("data", C0[2], R0[1], 180, 80, "DATA", "TBL_ACCESS_*", "8 tables · one run per CALL"),
    "app": ("entry", C0[3], R0[1], 180, 80, "ENTRY", "Streamlit app", "7 pages · read-only"),
    "tf": ("code", C0[2], R0[2], 180, 80, "SQL FUNCTIONS", "TF_ACCESS_OF", "TF_WHO_CAN · TF_CAN"),
    "user": ("actor", C0[3], R0[2], 180, 80, "", "Viewer · auditor", "browser or worksheet"),
}
# (from, side, to, side, dashed, label)
OVERVIEW_ARROWS = [
    ("dev", "bottom", "sp", "top", False, "1 CALL"),
    ("sf", "right", "sp", "left", True, "2 read grants"),
    ("sp", "right", "tbl", "left", True, "3 write run"),
    ("user", "top", "app", "bottom", False, "4 open"),
    ("tbl", "right", "app", "left", True, "5 last OK run"),
    ("user", "left", "tf", "right", False, "6 SQL"),
    ("tbl", "bottom", "tf", "top", True, "7 last OK run"),
]

# L1 flow: 1080 x 640 canvas, lane labels in the first 120 px, 140 px boxes 60 px apart
C1 = [140, 340, 540, 740, 940]
LANES = [("DEVELOPER", 0, 120), ("SNOWFLAKE", 120, 260), ("APP", 380, 140), ("VIEWER", 520, 120)]  # name, top, height


def mid(cx, cy, kind, eyebrow, name, sub, h=64):
    """Box centred on (cx, cy), 140 px wide."""
    return (kind, cx - 70, cy - h // 2, 140, h, eyebrow, name, sub)


FLOW = {
    "deploy": mid(C1[0] + 70, 60, "step", "", "Deploy", "run_sql.py 1_setup.sql"),
    "call": mid(C1[1] + 70, 60, "step", "", "CALL the procedure", "2_snapshot.sql"),
    "busy": mid(C1[1] + 70, 200, "dec", "", "Run RUNNING,", "under 1 h old?", 80),
    "skip": mid(C1[0] + 70, 200, "step", "", "Return SKIPPED", "nothing written"),
    "read": mid(C1[2] + 70, 200, "step", "", "Read sources", "ACCOUNT_USAGE or SHOW"),
    "ok": mid(C1[3] + 70, 200, "dec", "", "Every core", "dataset read?", 80),
    "fail": mid(C1[3] + 70, 320, "step", "", "FAILED run", "its rows deleted"),
    "run": mid(C1[4] + 70, 200, "data", "DATA", "OK run", "TBL_ACCESS_*"),
    "rebuild": mid(C1[1] + 70, 460, "step", "", "Rebuild snapshot", "button, any app user"),
    "reload": mid(C1[3] + 70, 460, "step", "", "Reload page data", "button: clears the cache"),
    "load": mid(C1[4] + 70, 460, "step", "", "Load last OK run", "cached 1 h"),
    "open": mid(C1[4] + 70, 580, "actor", "", "Open a page", "or a shared link"),
}
FLOW_ARROWS = [
    ("deploy", "right", "call", "left", False, "1"),
    ("call", "bottom", "busy", "top", False, "2 CALL"),
    ("rebuild", "top", "busy", "bottom", False, "2 or button"),
    ("busy", "left", "skip", "right", False, "yes"),
    ("busy", "right", "read", "left", False, "3 no"),
    ("read", "right", "ok", "left", False, "4"),
    ("ok", "bottom", "fail", "top", False, "no"),
    ("ok", "right", "run", "left", True, "5 yes"),
    ("run", "bottom", "load", "top", True, "6 last OK run"),
    ("reload", "right", "load", "left", False, ""),
    ("open", "top", "load", "bottom", False, "7 open"),
]


def side(box, where):
    """Middle of a box side: (x, y)."""
    _, x, y, w, h, *_ = box
    return {"top": (x + w // 2, y), "bottom": (x + w // 2, y + h), "left": (x, y + h // 2),
            "right": (x + w, y + h // 2)}[where]


def crosses(p, q, boxes, skip):
    """Does segment p-q pass through a box other than its two ends?"""
    lo_x, hi_x, lo_y, hi_y = min(p[0], q[0]), max(p[0], q[0]), min(p[1], q[1]), max(p[1], q[1])
    return any(lo_x < x + w and hi_x > x and lo_y < y + h and hi_y > y
               for b, (_, x, y, w, h, *_) in boxes.items() if b not in skip)


def box_html(kind, x, y, w, h, eyebrow, name, sub):
    top = f'<span class="eb">{escape(eyebrow)}</span>' if eyebrow else ""
    dia = (f'<svg class="dia" viewBox="0 0 {w} {h}" preserveAspectRatio="none"><polygon points="{w // 2},1 '
           f'{w - 1},{h // 2} {w // 2},{h - 1} 1,{h // 2}"/></svg>') if kind == "dec" else ""
    return (f'<div class="box {kind}" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px">{dia}{top}'
            f'<b>{escape(name)}</b><small>{escape(sub)}</small></div>')


def canvas(name, w, h, boxes, arrows, lanes=()):
    lines, labels = [], []
    for f, fs, t, ts, dashed, label in arrows:
        p, q = side(boxes[f], fs), side(boxes[t], ts)
        assert p[0] == q[0] or p[1] == q[1], (f, t)  # straight
        assert not crosses(p, q, boxes, {f, t}), (f, t)
        lines.append(f'<line x1="{p[0]}" y1="{p[1]}" x2="{q[0]}" y2="{q[1]}"'
                     + (' stroke-dasharray="5 4"' if dashed else "") + f' marker-end="url(#ah-{name})"/>')
        if p[1] == q[1]:  # horizontal: label above the middle
            lx, ly, anchor = (p[0] + q[0]) // 2, p[1] - 8, "middle"
        elif p[0] + 8 + 8 * len(label) <= w:  # vertical: label right of the middle (~8 px per mono character)
            lx, ly, anchor = p[0] + 8, (p[1] + q[1]) // 2 + 4, "start"
        else:  # vertical near the right edge: label left of it
            lx, ly, anchor = p[0] - 8, (p[1] + q[1]) // 2 + 4, "end"
        if label:
            labels.append(f'<text x="{lx}" y="{ly}" text-anchor="{anchor}">{escape(label)}</text>')
    svg = (f'<svg class="arrows" width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-hidden="true"><defs>'
           f'<marker id="ah-{name}" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="7" markerHeight="7" '
           'orient="auto"><path d="M0 0L10 5L0 10z" fill="#17191D"/></marker></defs><g class="ln">' + "".join(lines)
           + '</g><g class="lb">' + "".join(labels) + '</g></svg>')
    bands = "".join(f'<div class="lane" style="top:{top}px;height:{lh}px"><span>{escape(n)}</span></div>'
                    for n, top, lh in lanes)
    return (f'<div class="canvas" style="width:{w}px;height:{h}px">{bands}{svg}'
            + "".join(box_html(*b) for b in boxes.values()) + '</div>')


def rules():
    area = {n: v[1] for n, v in server.RULE_INFO.items()}
    areas = list(dict.fromkeys(area.values()))  # first-seen order of RULE_INFO
    assert set(area) == set(a.RULES)
    tone = {"High": "bad", "Medium": "warn", "Low": "low"}
    rows = []
    for ar in areas:
        rows.append(f'<tr class="grp"><td colspan="4">{escape(ar)}</td></tr>')
        for n in sorted((n for n in a.RULES if area[n] == ar), key=lambda n: (["High", "Medium", "Low"].index(
                a.SEVERITY[n]), int(n))):
            title, why = a.RULES[n]
            rows.append(f'<tr><td class="num">{n}</td><td><span class="sev {tone[a.SEVERITY[n]]}">{a.SEVERITY[n]}'
                        f'</span></td><td>{escape(title)}</td><td class="muted">{escape(why)}</td></tr>')
    return ('<table class="rules"><thead><tr><th>#</th><th>Severity</th><th>Rule</th><th>Why it matters</th></tr>'
            '</thead><tbody>' + "".join(rows) + '</tbody></table>')


def inject(html, name, body):
    pat = re.compile(f"(<!--map:{name}-->).*?(<!--/map:{name}-->)", re.S)
    assert pat.search(html), name
    return pat.sub(lambda m: m.group(1) + "\n" + body + "\n" + m.group(2), html)


if __name__ == "__main__":
    page = HERE / "README.html"
    html = page.read_text(encoding="utf-8")
    html = inject(html, "overview", canvas("overview", 1080, 440, OVERVIEW, OVERVIEW_ARROWS))
    html = inject(html, "flow", canvas("flow", 1080, 640, FLOW, FLOW_ARROWS, LANES))
    html = inject(html, "rules", rules())
    page.write_text(html, encoding="utf-8", newline="\n")
    print("README.html updated")
