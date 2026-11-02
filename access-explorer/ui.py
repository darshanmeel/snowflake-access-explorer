"""Presentation kit: theme tokens, CSS, HTML components and the depth-lane graph. No data logic.

Every helper returns an HTML string on one line (no newlines, so st.markdown never turns indentation into code blocks).
Colors come from TOKENS only: css(theme) turns the active set into :root variables, lane_graph() inlines them.
"""
from html import escape
from urllib.parse import urlencode

KINDS = ["user", "functional", "technical", "group", "admin", "object"]
LABELS = {"user": "User", "functional": "Functional", "technical": "Technical", "group": "Group / other",
          "admin": "Admin", "object": "Object"}
SHAPE = {"user": ("999px", "solid"), "functional": ("6px", "solid"), "technical": ("6px", "solid"),
         "group": ("6px", "dashed"), "admin": ("6px", "solid"), "object": ("12px / 9px", "solid")}


def _kinds(rows):
    return {k: {"bg": bg, "border": bd, "text": ink, "radius": SHAPE[k][0], "dash": SHAPE[k][1]}
            for k, (bg, bd, ink) in zip(KINDS, rows)}


TOKENS = {
    "light": {
        "bg": "#F7F4EE", "side": "#EEE7DB", "panel": "#FFFDF8", "sunk": "#F2ECE2", "line": "#E2D8C8",
        "ink": "#1F1A14", "muted": "#675E53", "accent": "#975A16", "edge": "#A89B89",
        "warn_bg": "#F7EFCF", "warn_ink": "#634B0E", "warn_bd": "#E6D58A",
        "bad_bg": "#F9E2DE", "bad_ink": "#8C271D", "bad_bd": "#EDB9B1",
        "ok_bg": "#E3EFE4", "ok_ink": "#2B5A33", "ok_bd": "#B9D6BD",
        "low_bg": "#ECE8E1", "low_ink": "#5B544B", "low_bd": "#D3CBBF",
        "e_read": "#2F5D9E", "e_write": "#B8650A", "e_own": "#8A3B1E", "e_use": "#2E7A4C",
        "kind": _kinds([("#FFFFFF", "#2A241D", "#1F1A14"), ("#DFE9F6", "#30476B", "#1D2C44"),
                        ("#EEDDC8", "#8C5D34", "#4A2E14"), ("#FAEBCB", "#B07A1E", "#553806"),
                        ("#F9DCD6", "#B4362A", "#8C271D"), ("#ECE6DB", "#5E554A", "#2A241D")]),
    },
    "dark": {
        "bg": "#14110D", "side": "#1A1612", "panel": "#1F1A15", "sunk": "#28221B", "line": "#3A3128",
        "ink": "#F2ECE2", "muted": "#ADA294", "accent": "#E6A95C", "edge": "#75685A",
        "warn_bg": "#2C2610", "warn_ink": "#EBD27E", "warn_bd": "#4E4418",
        "bad_bg": "#371A17", "bad_ink": "#F4BDB4", "bad_bd": "#5E2A24",
        "ok_bg": "#18301D", "ok_ink": "#A6D9AE", "ok_bd": "#2D5235",
        "low_bg": "#2A251F", "low_ink": "#BDB3A6", "low_bd": "#463D33",
        "e_read": "#82AAE3", "e_write": "#EBA84E", "e_own": "#E58F6E", "e_use": "#7DC896",
        "kind": _kinds([("#1F1A15", "#E9E1D4", "#F2ECE2"), ("#1C2A3F", "#7EA3D6", "#D5E3F6"),
                        ("#35271A", "#C5926A", "#F1DCC5"), ("#352913", "#D7A443", "#F3DDAE"),
                        ("#3A1B18", "#E27A6B", "#F6C3BA"), ("#2A251F", "#A39684", "#EDE5D8")]),
    },
}
SEV_TONE = {"High": "bad", "Medium": "warn", "Low": "low"}
PCLASS = {"read": "Read", "write": "Write", "own": "Own", "use": "Use", "inherit": "Inherits"}

# plain-language definitions, shown as title tooltips (legend chips, KPI labels, table headers, D badges) and as a glossary
HELP = {
    "User": "A Snowflake login: a person, or a service user (TYPE = SERVICE) used by tools and pipelines.",
    "Functional": "Functional role: a job role (e.g. analyst, engineer) granted to users or group roles. "
                  "It holds technical roles, not objects.",
    "Technical": "Technical role: holds the privileges on one database or schema, as OWNER, READ, WRITE or EXECUTE.",
    "Group / other": "Any other role, e.g. a group role synced from the identity provider, or PUBLIC (every user has it).",
    "Admin": "ACCOUNTADMIN, SECURITYADMIN or SYSADMIN, or an account-level privilege: can change access itself.",
    "Object": "What a privilege is granted on: database, schema, table, view, warehouse, procedure or function.",
    "Path": "The chain that gives the access: the start, each role granted to the one before, then the object.",
    "Paths": "How many different chains give the same privilege. More than 1: removing one role may not remove access.",
    "Depth": "Dn = n roles in the chain from the start to the role that holds the grant, that role included. "
             "D1 = held by the first role.",
    "Future table": "A grant on every table created later in a schema (future grant). Existing tables need their own grant.",
    "Secondary roles": "All = every granted role is active in a session at once. None = only the role in use.",
    "Choke point": "A grant every path passes through: removing it removes the access.",
    "Read": "Read: SELECT, REFERENCES, or USAGE on a database or schema.",
    "Write": "Write: INSERT, UPDATE, DELETE or TRUNCATE. Changes data.",
    "Own": "Own: OWNERSHIP. Full control: can change, drop and grant the object.",
    "Use": "Use: USAGE on a warehouse, procedure or function, OPERATE or MONITOR.",
    "Inherits": "Role-to-role link: the role on the left is granted the one on the right and gets all it holds.",
    "Sensitive": "Tagged as personal or confidential data: on a column, on the object, or inherited from its schema or database.",
    "Masked": "A masking policy hides the value for this role. Read from the policy text, not evaluated by Snowflake.",
    "Dormant": "No login for the dormant period (default 90 days) before the snapshot, or never logged in.",
    "Disabled": "The user is disabled and can't log in, but its grants stay until revoked.",
}
GRAPH_HOW = ("Left to right: the start, then each role granted to the one before, then objects. Grey lines: a role "
             "inherits the next. Coloured lines: the privilege on the object (blue solid read, amber thick write, "
             "red-brown double own, green dashed use). Click a box to open it; hover for the full name.")

SERIF = "'Source Serif 4', Georgia, serif"
SANS = "'IBM Plex Sans', system-ui, sans-serif"
MONO = "'IBM Plex Mono', ui-monospace, monospace"
FONTS = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600"
         "&family=IBM+Plex+Sans:wght@400;500;600&family=Source+Serif+4:opsz,wght@8..60,500;8..60,600&display=swap")

ICON = {  # 24x24 stroke icons
    "warn": '<path d="M12 3 2 21h20L12 3z"/><path d="M12 10v5M12 18h.01"/>',
    "bad": '<circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16.5h.01"/>',
    "ok": '<path d="m5 12 5 5 9-10"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5h.01"/>',
    "no": '<path d="M6 6l12 12M18 6 6 18"/>',
    "chev": '<path d="m9 6 6 6-6 6"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "brand": '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="12" cy="18" r="2.5"/>'
             '<path d="M7.8 7.8 10.6 16M16.2 7.8 13.4 16"/>',
}


def icon(name, size=18, width=2):
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICON[name]}</svg>')


# ---------- CSS ----------

def css(theme):
    t = TOKENS[theme]
    v = [f"--{k.replace('_', '-')}:{c}" for k, c in t.items() if k != "kind"]
    v += [f"--k-{k}-{p}:{c[p]}" for k, c in t["kind"].items() for p in ("bg", "border", "text")]
    chips = "".join(f".ae-chip.k-{k}{{background:var(--k-{k}-bg);border:1px {s[1]} var(--k-{k}-border);"
                    f"color:var(--k-{k}-text);border-radius:{s[0]}}}" for k, s in SHAPE.items())
    tones = "".join(f".ae-tone-{x}{{background:var(--{x}-bg);color:var(--{x}-ink);border:1px solid var(--{x}-bd)}}"
                    f".ae-ink-{x}{{color:var(--{x}-ink)!important}}" for x in ("warn", "bad", "ok", "low"))
    root = ";".join(v) + f";color-scheme:{theme}"
    mag = (f"<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' "
           f"stroke='{t['muted']}' stroke-width='2' stroke-linecap='round'><circle cx='11' cy='11' r='7'/>"
           f"<path d='m20 20-3.5-3.5'/></svg>")
    search = 'url("data:image/svg+xml,' + mag.replace("#", "%23").replace("<", "%3C").replace(">", "%3E") + '")'
    return f"""<style>
@import url('{FONTS}');
:root{{{root}}}
html,body,.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"],[data-testid="stHeader"],[data-testid="stBottomBlockContainer"]{{background:var(--bg)!important;color:var(--ink)}}
.stApp,.stApp p,.stApp label,.stApp input,.stApp button,.stApp li,.stApp td,.stApp th,.stApp textarea{{font-family:{SANS}}}
:where(.stApp) :is(p,li,span,label){{color:inherit}}
[data-testid="stHeader"]{{background:transparent!important}}
[data-testid="stDecoration"]{{display:none}}
/* the toolbar stays: on phones it holds the sidebar expand button; only its menu and actions are hidden */
[data-testid="stToolbarActions"],[data-testid="stMainMenu"],[data-testid="stAppDeployButton"]{{display:none}}
[data-testid="stMainBlockContainer"],.block-container{{max-width:1228px;padding:24px clamp(16px,3vw,44px) 72px!important}}
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"]{{gap:24px!important}}
[data-testid="stMarkdownContainer"]:has(.ae){{margin-bottom:0!important}}  /* Streamlit pulls markdown up by 1rem */
[data-testid="stSidebar"]{{background:var(--side)!important;border-right:1px solid var(--line);width:248px!important;min-width:248px!important;max-width:248px!important}}
[data-testid="stSidebar"]>div,[data-testid="stSidebarContent"]{{background:var(--side)!important}}
[data-testid="stSidebarContent"]{{padding:0 2px}}
[data-testid="stSidebarHeader"]{{height:8px;min-height:8px;padding:0}}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{{gap:14px!important}}
[data-testid="stSidebar"] [role="radiogroup"]{{gap:10px}}
[data-testid="stSidebarCollapseButton"] button,[data-testid="stExpandSidebarButton"],[data-testid="stSidebarCollapsedControl"] button{{color:var(--muted)!important;background:transparent!important}}
[data-testid="stWidgetLabel"] p,[data-testid="stWidgetLabel"] label{{font-size:13px!important;font-weight:500;color:var(--ink)!important}}
[data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] p{{color:var(--muted)!important;font-size:12.5px}}
.stApp a{{color:var(--accent)}}
.stApp hr{{border-color:var(--line)}}
/* selects, inputs, radio, checkbox (react-aria widgets in Streamlit 1.66) */
[data-testid="stSelectbox"] [role="group"],.stTextInput input,.stNumberInput input,.stTextArea textarea{{background:var(--sunk)!important;border:1px solid var(--line)!important;color:var(--ink)!important;border-radius:8px!important}}
[data-testid="stSelectbox"] [role="group"]{{min-height:42px}}
[data-testid="stSelectbox"] [role="group"]:focus-within{{border-color:var(--accent)!important;box-shadow:none!important}}
[data-testid="stSelectbox"] input{{color:var(--ink)!important;-webkit-text-fill-color:var(--ink);font-size:14px}}
[data-testid="stSelectbox"] input::placeholder{{color:var(--muted)!important;-webkit-text-fill-color:var(--muted)}}
[data-testid="stSelectbox"] button,[data-testid="stSelectbox"] svg{{color:var(--muted)!important;background:transparent!important}}
[data-testid="stSelectboxVirtualDropdown"]{{background:var(--panel)!important;border:1px solid var(--line)!important}}
[role="listbox"],[role="option"]{{background:var(--panel)!important;color:var(--ink)!important}}
[role="option"][data-hovered="true"],[role="option"][data-focused="true"],[role="option"][aria-selected="true"]{{background:var(--sunk)!important}}
[class*="st-key-pick"] [data-testid="stSelectbox"] [role="group"]{{border:1.5px solid var(--accent)!important}}
[class*="st-key-pick"] input{{font-family:{MONO}!important}}
.stRadio label,.stCheckbox label{{color:var(--ink)!important}}
[data-testid="stRadioOption"]>div>div:first-child{{background:var(--panel)!important;border-color:var(--edge)!important}}
[data-testid="stRadioOption"][data-selected="true"]>div>div:first-child{{background:var(--accent)!important;border-color:var(--accent)!important}}
[data-testid="stRadioOption"][data-selected="true"]>div>div:first-child>div{{background:var(--panel)!important}}
[data-testid="stCheckbox"] label>div:first-of-type{{background:var(--sunk)!important;border-color:var(--edge)!important}}
[data-testid="stCheckbox"] label:has(input:checked)>div:first-of-type{{background:var(--accent)!important;border-color:var(--accent)!important;color:var(--bg)!important}}
[role="radiogroup"][aria-orientation="horizontal"]{{gap:4px}}
[data-testid="stMain"] [data-testid="stRadioGroup"][aria-orientation="horizontal"]{{background:var(--sunk);padding:4px;border-radius:9px;gap:4px!important;width:fit-content;max-width:100%;flex-wrap:wrap}}
[data-testid="stMain"] [data-testid="stRadioGroup"][aria-orientation="horizontal"] [data-testid="stRadioOption"]{{min-height:36px;padding:0 12px;border-radius:7px;align-items:center;margin:0!important}}
[data-testid="stMain"] [data-testid="stRadioGroup"][aria-orientation="horizontal"] [data-testid="stRadioOption"][data-selected="true"]{{background:var(--panel);box-shadow:0 0 0 1px var(--line)}}
[data-testid="stMain"] [data-testid="stRadioGroup"][aria-orientation="horizontal"] [data-testid="stRadioOption"] p{{font-size:13px}}
[data-testid="stMain"] [data-testid="stRadioGroup"][aria-orientation="horizontal"] [data-testid="stRadioOption"][data-selected="true"] p{{font-weight:600}}
/* segmented control: one grey pill group, the picked item a raised white pill */
[data-testid="stButtonGroup"]>div{{background:var(--sunk);padding:4px;border-radius:10px;gap:0!important;width:fit-content;max-width:100%;flex-wrap:wrap}}
[data-testid="stButtonGroup"] button{{background:transparent!important;color:var(--muted)!important;border:0!important;border-radius:7px!important;min-height:32px;padding:0 12px;box-shadow:none!important}}
[data-testid="stButtonGroup"] button p{{font-family:{MONO};font-size:12px;letter-spacing:.02em;text-transform:uppercase}}
[data-testid="stButtonGroup"] button[aria-checked="true"],[data-testid="stButtonGroup"] button[kind$="Active"]{{background:var(--panel)!important;color:var(--ink)!important;box-shadow:0 0 0 1px var(--line)!important}}
[data-testid="stButtonGroup"] button[aria-checked="true"] p,[data-testid="stButtonGroup"] button[kind$="Active"] p{{font-weight:600}}
/* buttons */
.stButton button,.stDownloadButton button,.stFormSubmitButton button,.stLinkButton a{{background:var(--sunk)!important;color:var(--ink)!important;border:1px solid var(--line)!important;border-radius:8px!important;min-height:40px;font-size:13px;box-shadow:none!important}}
.stButton button:hover,.stDownloadButton button:hover{{border-color:var(--accent)!important;color:var(--accent)!important}}
.stButton button p,.stDownloadButton button p{{font-size:13px}}
.stButton button[kind="primary"],.st-key-refresh button{{background:transparent!important;color:var(--accent)!important;border:1px solid var(--accent)!important;font-weight:600}}
.st-key-refresh button p{{font-weight:600}}
.st-key-theme button{{width:44px;min-width:44px;padding:0;background:var(--panel)!important}}
/* global search: magnifier on the left, no chevron */
.st-key-find [data-testid="stSelectbox"] svg{{display:none}}
.st-key-find [data-testid="stSelectbox"] [role="group"]{{padding-left:34px;background:var(--sunk) {search} no-repeat 12px center!important}}
[data-testid="stExpander"] details{{background:var(--panel);border:1px solid var(--line)!important;border-radius:12px}}
[data-testid="stExpander"] summary{{color:var(--ink)!important}}
[data-testid="stAlert"]{{background:var(--sunk)!important;color:var(--ink)!important;border:1px solid var(--line);border-radius:10px}}
[data-testid="stSpinner"],[data-testid="stSpinner"] *{{color:var(--muted)!important}}
/* a Streamlit container with key card_* looks like a card (so widgets can sit inside one) */
[class*="st-key-card"]{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px}}
[class*="st-key-card"] [data-testid="stVerticalBlock"]{{gap:16px}}
[class*="st-key-card"] .ae-tablewrap{{margin:0 -20px -20px;border-top:1px solid var(--line)}}
[class*="st-key-csv"]{{align-self:flex-end}}
[data-testid="stMarkdownContainer"] .ae p{{margin:0}}
/* ---------- components ---------- */
.ae{{font-family:{SANS};color:var(--ink);font-size:14px;line-height:1.45}}
.ae *{{box-sizing:border-box}}
.ae-mono{{font-family:{MONO}!important}}
.ae-strong{{font-family:{MONO};font-weight:600}}
.ae-muted{{color:var(--muted)}}
.ae-small{{font-size:12px;color:var(--muted);letter-spacing:.03em}}
.ae-empty{{color:var(--muted);font-size:14px;padding:6px 0}}
.ae-crumb{{font-size:13px;color:var(--muted)}}.ae-crumb b{{color:var(--ink);font-weight:400}}
.ae-head{{display:flex;flex-direction:column;gap:8px}}
.ae-eyebrow{{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);font-weight:600}}
.ae-h1{{margin:0;font-family:{SERIF};font-weight:600;font-size:clamp(30px,3.4vw,42px);line-height:1.1;letter-spacing:-.01em;color:var(--ink)}}
.ae-lead{{margin:0;font-size:14px;color:var(--muted);max-width:760px}}
.ae-lead code{{font-family:{MONO};font-size:12.5px;background:none;color:var(--ink);padding:0}}
.ae-card{{display:flex;flex-direction:column;gap:14px;padding:20px;border-radius:14px;background:var(--panel);border:1px solid var(--line);min-width:0}}
.ae-card-head{{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:8px 12px}}
.ae-h2{{margin:0;font-family:{SERIF};font-weight:600;font-size:22px;line-height:1.25;color:var(--ink)}}
.ae-card-sub{{font-size:13px;color:var(--muted);margin-top:2px}}
.ae-card>.ae-tablewrap{{margin:0 -20px -20px;border-top:1px solid var(--line)}}
.ae-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,var(--min,170px)),1fr));gap:12px}}
.ae-two{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:20px;align-items:start}}
.ae-kpi{{padding:16px 18px;border-radius:12px;background:var(--panel);border:1px solid var(--line);display:flex;flex-direction:column;gap:2px;min-width:0}}
.ae-kpi-label{{font-size:12.5px;color:var(--muted)}}
.ae-kpi-value{{font-family:{SERIF};font-size:38px;font-weight:600;line-height:1.1;color:var(--ink)}}
.ae-kpi-value.t-accent{{color:var(--accent)}}.ae-kpi-value.t-ok{{color:var(--ok-ink)}}.ae-kpi-value.t-bad{{color:var(--bad-ink)}}
.ae-kpi-value .ae-chip{{margin:8px 0 4px}}
.ae-kpi-cap{{font-size:12px;color:var(--muted);overflow-wrap:anywhere}}
.ae-profile{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;background:var(--line);border:1px solid var(--line);border-radius:12px;overflow:hidden}}
.ae-profile>div{{background:var(--panel);padding:12px 16px;display:flex;flex-direction:column;gap:4px;align-items:flex-start;min-width:0}}
.ae-profile span:first-child{{font-size:12px;color:var(--muted)}}
.ae-profile span:last-child{{font-size:14px;font-weight:500;overflow-wrap:anywhere}}
.ae-profile .ae-mono{{font-size:13px;font-weight:400}}
.ae-banner{{display:flex;gap:10px;align-items:flex-start;padding:12px 16px;border-radius:10px;font-size:14px}}
.ae-banner svg{{flex:none;margin-top:1px}}
.ae-banner b{{font-weight:600}}
.ae-banner ul{{margin:8px 0 0;padding:0;list-style:none;display:flex;flex-direction:column;gap:6px}}
.ae-banner li{{display:flex;flex-wrap:wrap;align-items:center;gap:4px}}
.ae-tone-info{{background:var(--sunk);color:var(--ink);border:1px solid var(--line)}}
{tones}
.ae-chip{{display:inline-flex;align-items:center;white-space:nowrap;font-family:{MONO};font-weight:500;font-size:11.5px;line-height:1.5;padding:1px 8px;text-decoration:none!important}}
a.ae-chip:hover{{outline:1.5px solid var(--accent);outline-offset:1px}}
{chips}
.ae-path{{display:flex;flex-wrap:wrap;align-items:center;gap:4px;min-width:0}}
.ae-path svg{{color:var(--edge);flex:none}}
.ae-legend{{display:flex;flex-wrap:wrap;gap:8px;align-items:center}}
.ae-depth{{display:inline-flex;min-width:28px;justify-content:center;padding:1px 6px;border-radius:6px;background:var(--sunk);border:1px solid var(--line);font-family:{MONO};font-size:12px;color:var(--ink)}}
.ae-tablewrap{{overflow-x:auto}}
.ae-table{{width:100%;border-collapse:collapse;font-size:13px;color:var(--ink)}}
.ae-table th{{background:var(--sunk);color:var(--muted);text-align:left;font-weight:500;padding:10px 12px;white-space:nowrap;border:0}}
.ae-table td{{padding:10px 12px;border:0;border-top:1px solid var(--line);vertical-align:middle;background:transparent}}
.ae-table th:first-child,.ae-table td:first-child{{padding-left:20px}}
.ae-table th:last-child,.ae-table td:last-child{{padding-right:20px}}
.ae-table .num{{text-align:right;font-family:{MONO};white-space:nowrap}}
.ae-yes{{display:inline-flex;width:22px;height:22px;align-items:center;justify-content:center;border-radius:6px;background:var(--ok-bg);border:1px solid var(--ok-bd);color:var(--ok-ink)}}
.ae-yes.bad{{background:var(--bad-bg);border-color:var(--bad-bd);color:var(--bad-ink)}}
.ae-sev{{display:inline-flex;font-size:11px;font-weight:600;padding:1px 8px;border-radius:999px;line-height:1.5}}
.ae-dot{{display:inline-block;width:10px;height:10px;border-radius:50%;flex:none}}
.ae-dot.t-bad{{background:var(--bad-ink)}}.ae-dot.t-warn{{background:var(--warn-ink)}}.ae-dot.t-ok{{background:var(--ok-ink)}}.ae-dot.t-low{{background:var(--low-ink)}}
.ae-dot.t-warn{{border-radius:2px;transform:rotate(45deg) scale(.85)}}.ae-dot.t-low{{border-radius:2px}}  /* shape differs too, not colour only */
.ae-sevdot{{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;white-space:nowrap}}
.ae-rule{{display:flex;flex-direction:column;align-items:flex-start;gap:4px;padding:14px 16px;border-radius:12px;background:var(--panel);border:1px solid var(--line);color:var(--ink)!important;text-decoration:none!important;min-height:132px;min-width:0}}
.ae-rule:hover{{border-color:var(--edge)}}
.ae-rule.on{{border:1.5px solid var(--accent);box-shadow:0 0 0 3px var(--sunk)}}
.ae-rule-top{{display:flex;justify-content:space-between;align-items:center;gap:8px;width:100%;font-size:12px;color:var(--muted)}}
.ae-rule-count{{font-family:{SERIF};font-size:34px;font-weight:600;line-height:1.1}}
.ae-rule-title{{font-size:13px;line-height:1.35}}
.ae-answer{{display:flex;flex-wrap:wrap;align-items:center;gap:20px 28px;padding:24px 26px;border-radius:14px}}
.ae-answer-badge{{width:60px;height:60px;border-radius:50%;flex:none;display:flex;align-items:center;justify-content:center;background:var(--panel)}}
.ae-answer-text{{display:flex;flex-direction:column;gap:6px;flex:1 1 320px;min-width:0}}
.ae-answer-title{{font-family:{SERIF};font-size:30px;font-weight:600;line-height:1.15}}
.ae-answer-stats{{display:flex;gap:28px;flex-wrap:wrap}}
.ae-answer-stats div{{display:flex;flex-direction:column;font-size:12px}}
.ae-answer-stats b{{font-family:{SERIF};font-size:34px;font-weight:600;line-height:1.1}}
.ae-block{{display:flex;flex-direction:column;gap:10px;padding:14px;border-radius:10px;background:var(--sunk);border:1px solid var(--line)}}
.ae-block-head{{display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:13px;font-weight:600}}
.ae-graph{{overflow-x:auto;margin:0 -4px;padding-bottom:4px;border-radius:10px}}
.ae-graph.wide{{overflow-x:scroll;padding-bottom:8px}}
.ae-graph.fit{{overflow:hidden}}
.ae-graph svg a:hover rect,.ae-graph svg a:focus rect{{stroke:var(--accent);stroke-width:2.5}}
.ae-graph svg a:focus{{outline:none}}
.ae-graph svg path title{{pointer-events:none}}
.ae-graph::-webkit-scrollbar{{height:10px}}.ae-graph::-webkit-scrollbar-thumb{{background:var(--edge);border-radius:6px}}.ae-graph::-webkit-scrollbar-track{{background:var(--sunk);border-radius:6px}}
.ae-graph-hint{{align-self:flex-end;font-size:12px;color:var(--muted);margin-bottom:-6px}}
.ae-graph a{{text-decoration:none!important}}
/* help, privilege classes, markers */
.ae-tip{{text-decoration:underline dotted var(--edge);text-underline-offset:3px;cursor:help}}
.ae-how{{margin:0;font-size:12.5px;color:var(--muted)}}.ae-how b{{font-weight:600;color:var(--ink)}}
.ae-gloss{{margin:0;display:flex;flex-direction:column;gap:2px;font-size:12.5px}}
.ae-gloss dt{{font-weight:600;color:var(--ink);margin-top:8px}}.ae-gloss dd{{margin:0;color:var(--muted)}}
.ae-pc{{display:inline-flex;align-items:center;font-family:{MONO};font-size:11px;font-weight:600;letter-spacing:.03em;text-transform:uppercase;padding:0 7px;border-radius:5px;line-height:1.6;background:var(--panel);white-space:nowrap}}
.pc-read{{color:var(--e-read);border:1.5px solid var(--e-read)}}
.pc-write{{color:var(--e-write);border:2.5px solid var(--e-write)}}
.pc-own{{color:var(--e-own);border:3px double var(--e-own)}}
.pc-use{{color:var(--e-use);border:1.5px dashed var(--e-use)}}
.pc-inherit{{color:var(--muted);border:1.5px solid var(--edge)}}
.ae-leg-edge{{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--muted)}}
.ae-chip.off{{background:var(--sunk)!important;border:1px dashed var(--edge)!important;color:var(--muted)!important}}
.ae-sens{{display:inline-flex;margin-left:5px;color:var(--bad-ink)}}
/* sidebar */
.ae-brand{{display:flex;align-items:center;gap:10px;padding-top:16px}}
.ae-brand-mark{{width:34px;height:34px;border-radius:9px;background:var(--accent);display:flex;align-items:center;justify-content:center;color:var(--bg);flex:none}}
.ae-brand-name{{font-family:{SERIF};font-weight:600;font-size:19px;line-height:1.1;color:var(--ink)}}
.ae-brand-sub{{font-size:12px;color:var(--muted)}}
.ae-label{{font-size:11px!important;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)!important;margin:0 0 4px;opacity:1!important}}
.ae-nav{{display:flex;flex-direction:column;gap:4px}}
.ae-nav a{{display:flex;align-items:center;justify-content:space-between;min-height:40px;padding:0 12px;border-radius:8px;text-decoration:none!important;font-size:14px;color:var(--ink)!important}}
.ae-nav a:hover{{background:var(--sunk)}}
.ae-nav a.on{{background:var(--panel);font-weight:600;box-shadow:0 0 0 1px var(--line)}}
.ae-badge{{font-size:11px;font-weight:600;padding:1px 7px;border-radius:999px;background:var(--k-admin-bg);color:var(--k-admin-text)}}
.ae-snap{{display:flex;flex-direction:column;gap:10px;padding:14px;border-radius:10px;background:var(--panel);border:1px solid var(--line)}}
.ae-snap-head{{display:flex;justify-content:space-between;align-items:baseline;font-size:13px;font-weight:600}}
.ae-snap-head span{{font-family:{MONO};font-size:11px;color:var(--muted);font-weight:400}}
.ae-snap dl{{display:grid;grid-template-columns:auto 1fr;gap:4px 10px;font-size:11.5px;color:var(--muted);margin:0}}
[class*="st-key-card"] .ae-snap{{border:0;padding:0;background:none}}
[data-testid="stSidebar"] [class*="st-key-card"]{{padding:14px}}
.ae-snap dd{{margin:0;font-family:{MONO};overflow-wrap:anywhere}}
/* skeleton */
@keyframes ae-shimmer{{0%{{background-position:100% 0}}100%{{background-position:-100% 0}}}}
.ae-sk{{border-radius:8px;background:linear-gradient(90deg,var(--sunk) 25%,var(--line) 50%,var(--sunk) 75%);background-size:200% 100%;animation:ae-shimmer 1.4s linear infinite}}
.ae-sk-card{{padding:20px;border-radius:14px;background:var(--panel);border:1px solid var(--line);display:flex;flex-direction:column;gap:12px}}
/* responsive */
@media (max-width:1200px){{
/* sentence rows and filter rows wrap instead of clipping; a checkbox gets its own row */
[class*="st-key-card"] [data-testid="stHorizontalBlock"]{{flex-wrap:wrap}}
.st-key-card_can [data-testid="stColumn"]{{flex:1 1 100%!important;min-width:100%!important}}
[class*="st-key-card_filter"] [data-testid="stColumn"]{{flex:1 1 calc(50% - 1rem)!important;min-width:calc(50% - 1rem)!important}}
[class*="st-key-card"] [data-testid="stColumn"]:has([data-testid="stCheckbox"]){{flex:1 1 100%!important;min-width:100%!important}}
}}
@media (max-width:900px){{
.ae-h1{{font-size:28px}}
}}
@media (max-width:480px){{
.ae-card{{padding:16px}}
.ae-card>.ae-tablewrap{{margin:0 -16px -16px}}
.ae-kpi-value{{font-size:32px}}
.ae-answer{{padding:18px}}
.ae-answer-title{{font-size:24px}}
}}
</style>"""


# ---------- small pieces ----------

def tip(key):
    """Tooltip text for a HELP key; other text passes through."""
    return HELP.get(key, key)


def _title(text):
    return f' title="{escape(text)}"' if text else ""


def chip(name, kind, href=None, sensitive=False, disabled=False, title=""):
    """sensitive adds a lock marker; disabled draws the chip dashed grey (a disabled user)."""
    n = escape(str(name))
    cls = f"ae-chip k-{kind}" + (" off" if disabled else "")
    extra = [title] if title else []
    extra += ["disabled"] * disabled + ["sensitive data"] * sensitive
    if sensitive:
        n += f'<span class="ae-sens" aria-label="sensitive">{icon("lock", 11, 2.4)}</span>'
    t = _title(" · ".join(extra))
    if href:
        return f'<a class="{cls}" href="{escape(href)}" target="_self"{t}>{n}</a>'
    return f'<span class="{cls}"{t}>{n}</span>'


def path(names, kinds, href_of=None):
    """Chips joined by chevrons; href_of(name) -> link (optional)."""
    sep = icon("chev", 12, 2.5)
    return '<div class="ae-path">' + sep.join(
        chip(n, k, href_of(n) if href_of else None) for n, k in zip(names, kinds)) + '</div>'


def depth(n):
    return f'<span class="ae-depth"{_title(f"D{n}: " + HELP["Depth"])}>D{n}</span>'


def pclass(cls, text=""):
    """Privilege class badge: read | write | own | use; text overrides the label (e.g. "INSERT")."""
    return (f'<span class="ae-pc pc-{cls}"{_title(HELP.get(PCLASS.get(cls, ""), ""))}>'
            f'{escape(text or PCLASS.get(cls, cls))}</span>')


def sev(level):
    return f'<span class="ae-sev ae-tone-{SEV_TONE[level]}">{escape(level)}</span>'


def dot(level, text=False):
    """Severity dot (High red circle, Medium amber diamond, Low grey square); text=True adds the word."""
    d = f'<span class="ae-dot t-{SEV_TONE[level]}" title="{escape(level)}"></span>'
    return f'<span class="ae-sevdot">{d}{escape(level)}</span>' if text else d


def mono(s):
    return f'<span class="ae-mono">{escape(str(s))}</span>'


def edge_sample(cls):
    """A short line in the graph style of an edge class, for legends."""
    c = f"var(--{EDGE[cls][0].replace('_', '-')})"
    w, dash, double = EDGE[cls][1:]
    line = f'<path d="M1 6H27" stroke="{c}" stroke-width="{w}"' + (f' stroke-dasharray="{dash}"' if dash else "") + "/>"
    if double:
        line += '<path d="M1 6H27" stroke="var(--panel)" stroke-width="1.6"/>'
    return f'<svg width="28" height="12" viewBox="0 0 28 12" fill="none" aria-hidden="true">{line}</svg>'


def legend(edges=False, marks=False):
    """Node kinds; edges=True adds the line styles (inherits, read, write, own, use);
    marks=True adds the disabled-user and sensitive markers. Every entry has a tooltip from HELP."""
    out = [chip(LABELS[k], k, title=tip(LABELS[k])) for k in KINDS]
    if marks:
        out += [chip("Disabled", "user", disabled=True, title=tip("Disabled")),
                chip("Sensitive", "object", sensitive=True, title=tip("Sensitive"))]
    if edges:
        out += [f'<span class="ae-leg-edge"{_title(tip(PCLASS[c]))}>{edge_sample(c)}{PCLASS[c]}</span>' for c in EDGE]
    return '<div class="ae-legend">' + "".join(out) + '</div>'


def how(text=GRAPH_HOW):
    """One-line "How to read this" caption under a graph or table."""
    return f'<p class="ae ae-how"><b>How to read this:</b> {escape(text)}</p>'


def glossary(keys=None):
    """Definitions from HELP as a list, e.g. in a sidebar expander."""
    return '<dl class="ae ae-gloss">' + "".join(
        f"<dt>{escape(k)}</dt><dd>{escape(HELP[k])}</dd>" for k in (keys or HELP)) + '</dl>'


def crumb(page):
    return f'<div class="ae ae-crumb">Explorer / <b>{escape(page)}</b></div>'


def header(eyebrow, title, lead):
    """lead is HTML (may hold <code> names)."""
    return (f'<div class="ae ae-head"><span class="ae-eyebrow">{escape(eyebrow)}</span>'
            f'<div class="ae-h1" role="heading" aria-level="1">{escape(title)}</div><p class="ae-lead">{lead}</p></div>')


def banner(kind, title, lines=()):
    """kind: warn | bad | ok | info. title and lines are HTML."""
    body = f"<b>{title}</b>" if title else ""
    if lines:
        body += "<ul>" + "".join(f"<li>{x}</li>" for x in lines) + "</ul>"
    role = "alert" if kind == "bad" else "status"
    return (f'<div class="ae ae-banner ae-tone-{kind}" role="{role}">{icon("warn" if kind == "warn" else kind)}'
            f'<div style="min-width:0">{body}</div></div>')


def kpi(label, value, caption="", tone=None, help=""):
    """tone: None | accent | ok | bad. value may be HTML (e.g. a chip). help: HELP key or text, shown on hover."""
    cls = f" t-{tone}" if tone else ""
    h = tip(help) if help else HELP.get(label, "")
    return (f'<div class="ae-kpi"><span class="ae-kpi-label{" ae-tip" if h else ""}"{_title(h)}>{escape(label)}</span>'
            f'<span class="ae-kpi-value{cls}">{value}</span><span class="ae-kpi-cap">{caption}</span></div>')


def grid(items, min_px=170):
    """Auto-fit grid, e.g. grid([kpi(...), ...]) for KPI tiles or rule cards."""
    return f'<div class="ae ae-grid" style="--min:{min_px}px">' + "".join(items) + '</div>'


def profile(cells):
    """cells: [(label, value_html)]."""
    return '<div class="ae ae-profile">' + "".join(
        f'<div><span>{escape(k)}</span><span>{v}</span></div>' for k, v in cells) + '</div>'


def table(columns, rows, numeric_cols=(), min_width=640, tips=None):
    """rows: lists of cell HTML. numeric_cols: column names or indexes right-aligned in mono.
    Headers named in HELP (Depth, Paths, Path, ...) or in tips {column: text} get a tooltip."""
    num = {i for i, c in enumerate(columns) if c in numeric_cols or i in numeric_cols}
    tt = {c: (tips or {}).get(c) or HELP.get(c, "") for c in columns}
    th = "".join(f'<th{" class=num" if i in num else ""} scope="col"{_title(tt[c])}>'
                 f'{f"<span class=ae-tip>{escape(c)}</span>" if tt[c] else escape(c)}</th>' for i, c in enumerate(columns))
    trs = ["<tr>" + "".join(f'<td{" class=num" if i in num else ""}>{c}</td>' for i, c in enumerate(row)) + "</tr>"
           for row in rows]
    return (f'<div class="ae-tablewrap"><table class="ae-table" style="min-width:{min_width}px">'
            f'<thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>')


def title(text, sub=""):
    """Card title with an optional muted line under it."""
    s = f'<div class="ae-card-sub">{sub}</div>' if sub else ""
    return f'<div><div class="ae-h2">{escape(text)}</div>{s}</div>'


def card(text, sub="", body="", right=""):
    """A table as body sits flush under a divider. right: HTML at the top right (e.g. legend())."""
    return f'<section class="ae ae-card"><div class="ae-card-head">{title(text, sub)}{right}</div>{body}</section>'


def rule_card(label, level, count, title, href, on=False):
    badge = sev(level) if level else ""
    return (f'<a class="ae-rule{" on" if on else ""}" href="{escape(href)}" target="_self">'
            f'<span class="ae-rule-top"><span>{escape(label)}</span>{badge}</span>'
            f'<span class="ae-rule-count">{count}</span><span class="ae-rule-title">{escape(title)}</span></a>')


def answer(yes, title, text, stats=(), tone=None):
    """stats: [(label, value)]. tone: ok | warn | bad | low (default ok for yes, bad for no)."""
    tone = tone or ("ok" if yes else "bad")
    st = "".join(f"<div><span>{escape(k)}</span><b>{v}</b></div>" for k, v in stats)
    return (f'<section class="ae ae-answer ae-tone-{tone}" aria-live="polite">'
            f'<div class="ae-answer-badge" style="border:1.5px solid var(--{tone}-bd)">'
            f'{icon("ok" if yes else "no", 30, 2.6)}</div>'
            f'<div class="ae-answer-text"><span class="ae-answer-title">{escape(title)}</span>'
            f'<span>{text}</span></div><div class="ae-answer-stats">{st}</div></section>')


def block(title, right, body, note=""):
    """Inset block, e.g. one path on Can they?: title, right-hand tag, body HTML, muted note."""
    n = f'<span class="ae-muted" style="font-size:12.5px">{note}</span>' if note else ""
    return f'<div class="ae-block"><div class="ae-block-head"><span>{escape(title)}</span>{right}</div>{body}{n}</div>'


def brand():
    return ('<div class="ae ae-brand"><div class="ae-brand-mark">' + icon("brand") + '</div><div style="display:flex;'
            'flex-direction:column"><span class="ae-brand-name">Access explorer</span>'
            '<span class="ae-brand-sub">Snowflake RBAC</span></div></div>')


def nav(items, active):
    """items: [(label, href, badge or None)]."""
    out = []
    for label, href, badge in items:
        b = f'<span class="ae-badge">{badge}</span>' if badge else ""
        out.append(f'<a class="{"on" if label == active else ""}" href="{escape(href)}" target="_self">'
                   f'<span>{escape(label)}</span>{b}</a>')
    return '<nav class="ae ae-nav"><p class="ae-label">Explore</p>' + "".join(out) + '</nav>'


def snapshot_card(branch, when, sources):
    """sources: [(dataset, source)]."""
    dl = "".join(f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in sources)
    return (f'<div class="ae ae-snap"><div class="ae-snap-head">Snapshot<span>{escape(branch)}</span></div>'
            f'<span class="ae-mono" style="font-size:12px">{escape(when)}</span><dl>{dl}</dl></div>')


def skeleton():
    """Shimmer blocks in the shape of a page: filter card, KPI tiles, graph, table."""
    def bar(w, h=12):
        return f'<div class="ae-sk" style="width:{w};height:{h}px"></div>'

    tile = f'<div class="ae-kpi" style="gap:10px">{bar("60%")}{bar("40%", 34)}{bar("70%")}</div>'
    return ('<div class="ae" style="display:flex;flex-direction:column;gap:24px">'
            f'<div class="ae-sk-card">{bar("40%", 22)}{bar("100%", 42)}{bar("70%")}</div>' + grid([tile] * 5)
            + f'<div class="ae-sk-card">{bar("30%", 22)}<div class="ae-sk" style="height:300px"></div></div>'
            + '<div class="ae-sk-card">' + bar("35%", 22) + "".join(bar("100%", 18) for _ in range(6))
            + '</div></div>')


# ---------- depth-lane graph ----------

# edge class -> (colour token, stroke width, dash, double line). Role-to-role links are "inherit".
EDGE = {"inherit": ("edge", 1.5, "", False), "read": ("e_read", 1.8, "", False),
        "write": ("e_write", 3, "", False), "own": ("e_own", 4.5, "", True), "use": ("e_use", 1.8, "5 4", False)}
CH, CH2 = 7.2, 6.0  # mono char width at 12px / 10px
TOP, PADX = 40, 12  # room for lane labels, node inner padding
WIDE = 1100  # a scroll-mode graph wider than this gets a hint


def short(name, cap):
    return name if len(name) <= cap else name[:cap - 1] + "…"


def wrap(s, cap, n):
    """Up to n lines of at most cap chars, broken after '_' or '.' when there is one."""
    out = []
    while len(s) > cap and len(out) < n - 1:
        cut = max(s.rfind("_", 0, cap), s.rfind(".", 0, cap)) + 1
        cut = cut if cut > cap // 3 else cap
        out.append(s[:cut])
        s = s[cut:]
    return out + [short(s, cap)]


def _norm(e):
    """(a, b) | (a, b, cls) | (a, b, cls, label) -> (a, b, cls, label)."""
    c = (e[2] if len(e) > 2 else "") or "inherit"
    lab = e[3] if len(e) > 3 and e[3] else ("" if c == "inherit" else c)
    return e[0], e[1], c, lab


def lane_graph(lanes, edges, kind_of, theme, href_of, selected_lane=None, max_per_lane=12, expand="", query=None,
               fit=False, marks=None):
    """One SVG: lanes left to right, nodes are links, edges routed through the gaps between nodes.
    lanes: [(label, [names])]. edges: [(a, b)] or [(a, b, cls, label)], cls one of EDGE (default "inherit");
    the same pair may come twice with different classes. kind_of(name) -> kind; href_of(name) -> link.
    marks: {name: {"disabled", "sensitive"}} (optional). fit: scale into the card width, else scroll sideways.
    A lane over max_per_lane shows its first N plus a "+K more" node (no edges) linking to query + expand=<lanes>;
    an expanded lane ends with a "Show fewer" node. Returns one HTML string."""
    t, marks = TOKENS[theme], marks or {}
    opened = {int(x) for x in (expand or "").split(",") if x.isdigit()}

    def again(lanes_open):
        q = dict(query or {})
        q.pop("expand", None)
        if lanes_open:
            q["expand"] = ",".join(str(e) for e in sorted(lanes_open))
        return "?" + urlencode(q)

    cols, alias = [], {}
    for i, (_, names) in enumerate(lanes):
        names = list(dict.fromkeys(names))
        if len(names) > max_per_lane and i not in opened:
            more = ("more", i, len(names) - max_per_lane)
            alias.update((n, more) for n in names[max_per_lane:])
            names = names[:max_per_lane] + [more]
        elif len(names) > max_per_lane:
            names = names + [("less", i, 0)]
        cols.append(names)
    lane_of = {}
    for i, c in enumerate(cols):
        for n in c:
            lane_of.setdefault(n, i)
    links = {}
    for e in edges:
        a, b, c, lab = _norm(e)
        a, b = alias.get(a, a), alias.get(b, b)
        if a == b or isinstance(a, tuple) or isinstance(b, tuple) or a not in lane_of or b not in lane_of:
            continue  # "+K more" draws no edges: one hidden node's edge would look like all of them
        old = links.get((a, b, c))
        links[(a, b, c)] = lab if not old or lab in old.split(", ") else old + ", " + lab
    near = {}
    for a, b, _ in links:
        near.setdefault(a, []).append(b)
        near.setdefault(b, []).append(a)
    rows = max([len(c) for c in cols] + [1])

    def rank(c):
        return {n: r + (rows - len(c)) / 2 for r, n in enumerate(c)}

    # one barycentre sweep each way: a lane sorted by the mean row of its neighbours in placed lanes, so few edges cross
    for todo, placed in ((range(1, len(cols)), lambda i: range(i)),
                         (range(len(cols) - 2, -1, -1), lambda i: range(i + 1, len(cols)))):
        for i in todo:
            y = {n: r for j in placed(i) for n, r in rank(cols[j]).items()}
            own = rank(cols[i])

            def key(n):
                ys = [y[m] for m in near.get(n, []) if m in y]
                return sum(ys) / len(ys) if ys else own[n]

            cols[i] = (sorted((n for n in cols[i] if not isinstance(n, tuple)), key=key)
                       + [n for n in cols[i] if isinstance(n, tuple)])

    many = len(lanes) > 6
    cap, nl = (10, 3) if fit and many else (16, 2) if fit else (20, 2) if many else (40, 2)
    gap = 30 if fit and many else 44 if many else 64
    size = {}  # name -> (w, h, big lines, small line)
    for c in cols:
        for n in c:
            if isinstance(n, tuple):
                big, small = [f"+{n[2]} more" if n[0] == "more" else "Show fewer"], ""
            elif kind_of(n) == "object" and "." in n:
                head, last = n.rsplit(".", 1)  # last part big, DB.SCHEMA small under it
                big, small = wrap(last, cap, max(nl - 1, 1)), short(head, int(cap * 1.2))
            else:
                big, small = wrap(str(n), cap, nl), ""
            sens = 8 if "sensitive" in marks.get(n, ()) else 0
            w = max([len(x) * CH for x in big] + [len(small) * CH2]) + 2 * PADX + sens
            size[n] = (w, 14 * len(big) + (12 if small else 0) + 16, big, small)
    row_h = max([s[1] for s in size.values()] + [32]) + (18 if fit else 22)
    colw = [max([size[n][0] for n in c] + [len(lb) * 7.6 + 8]) for (lb, _), c in zip(lanes, cols)]
    xl, x = [], 16
    for w in colw:
        xl.append(x)
        x += w + gap
    W, H = x - gap + 16, TOP + rows * row_h + 12
    pos = {}
    for i, c in enumerate(cols):
        for n, r in rank(c).items():
            pos[n] = (xl[i] + colw[i] / 2, TOP + r * row_h + row_h / 2)
    slots = {}  # gaps between nodes per lane, where routed edges cross that lane
    for i, c in enumerate(cols):
        ys = sorted(pos[n][1] for n in c)
        slots[i] = [ys[0] - row_h / 2] + [(p + q) / 2 for p, q in zip(ys, ys[1:])] + [ys[-1] + row_h / 2] if ys else []
    used, gaps = {}, {}

    def lane_y(i, want, pair):
        """A bend point for a long edge in lane i: the gap nearest to where the straight line would cross
        (the same gap for every class edge of one pair)."""
        if not slots[i]:
            return want
        g = gaps.setdefault((pair, i), min(slots[i], key=lambda s: abs(s - want)))
        k = used[(i, g)] = used.get((i, g), -1) + 1
        return g + (0, 4, -4, 8, -8, 12, -12)[k % 7]  # parallel edges in one gap side by side

    pairs = {}
    for a, b, c in links:
        pairs.setdefault((a, b), []).append(c)
    paths, labels, stack = [], [], {}  # stack: (node, side, x) -> {(label, colour token)}
    for (a, b, c), lab in sorted(links.items(), key=lambda kv: kv[0][2] != "inherit"):  # class edges on top
        both = pairs[(a, b)]
        off = (both.index(c) - (len(both) - 1) / 2) * 6  # two classes on one pair: two parallel lines
        (ax, ay), (bx, by), la, lb = pos[a], pos[b], lane_of[a], lane_of[b]
        ay, by = ay + off, by + off
        wa, wb = size[a][0] / 2, size[b][0] / 2
        if la == lb:  # same lane: loop out into the gap on the right
            xr = xl[la] + colw[la]
            bend = xr + gap * .7
            d = f"M{ax + wa:.1f} {ay:.1f}H{xr:.1f}C{bend:.1f} {ay:.1f} {bend:.1f} {by:.1f} {xr:.1f} {by:.1f}H{bx + wb:.1f}"
            lx, anchor, back = xr + 4, "start", True
        else:
            s = 1 if lb > la else -1

            def out(i):
                return xl[i] + colw[i] if s > 0 else xl[i]

            def into(i):
                return xl[i] if s > 0 else xl[i] + colw[i]

            # horizontal runs through each lane (in a gap), S-curves only between lanes, so no edge crosses a node
            segs = [(ax + s * wa, out(la), ay)]
            for i in range(la + s, lb, s):
                yi = lane_y(i, ay + (by - ay) * (i - la) / (lb - la), (a, b))
                segs.append((into(i), out(i), yi))
            segs.append((into(lb), bx - s * wb, by))
            d = f"M{segs[0][0]:.1f} {segs[0][2]:.1f}H{segs[0][1]:.1f}"
            for (_, x0, y0), (x1, x2, y1) in zip(segs, segs[1:]):
                m = (x0 + x1) / 2
                d += f"C{m:.1f} {y0:.1f} {m:.1f} {y1:.1f} {x1:.1f} {y1:.1f}H{x2:.1f}"
            lx, anchor, back = into(lb) - s * 4, "end" if s > 0 else "start", s < 0
        tok, sw, dash, double = EDGE.get(c, EDGE["inherit"])
        tip = f"{a} → {b}" + (f": {lab}" if lab else " (inherits)")
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        paths.append(f'<path d="{d}" stroke="{t[tok]}" stroke-width="{sw}"{extra}><title>{escape(tip)}</title></path>')
        if double:
            paths.append(f'<path d="{d}" stroke="{t["panel"]}" stroke-width="1.6"/>')
        if back:  # an edge that runs right to left (or within a lane) gets an arrowhead, so its direction is clear
            ex = bx + wb
            paths.append(f'<path d="M{ex:.1f} {by:.1f}l7 -4v8z" fill="{t[tok]}" stroke="none"/>')
        if lab:  # one label per text and class at each node side: two holders giving SELECT show one "SELECT"
            stack.setdefault((b, anchor, lx), {}).setdefault((short(lab, 14), tok), None)
    for (b, anchor, lx), texts in stack.items():
        for k, (text, tok) in enumerate(texts):  # alternate above / below the arriving lines
            y = pos[b][1] + (-5 - 11 * (k // 2) if k % 2 == 0 else 13 + 11 * (k // 2))
            labels.append(f'<text x="{lx:.1f}" y="{y:.1f}" text-anchor="{anchor}" fill="{t[tok]}" '
                          f'stroke="{t["panel"]}" stroke-width="3" paint-order="stroke">{escape(text)}</text>')
    band, heads, nodes = "", [], []
    for i, ((lb, _), c) in enumerate(zip(lanes, cols)):
        cx = xl[i] + colw[i] / 2
        if i == selected_lane:
            band = (f'<rect x="{xl[i] - gap / 3:.1f}" y="2" width="{colw[i] + gap * 2 / 3:.1f}" height="{H - 4:.0f}" '
                    f'rx="10" fill="{t["sunk"]}" stroke="{t["line"]}" stroke-dasharray="4 3"/>')
        heads.append(f'<text x="{cx:.1f}" y="22" text-anchor="middle">{escape(lb.upper())}</text>')
        for n in c:
            nx, ny = pos[n]
            w, h, big, small = size[n]
            x0, y0 = nx - w / 2, ny - h / 2
            if isinstance(n, tuple):
                more = n[0] == "more"
                href = again(opened | {i} if more else opened - {i})
                tip = "Show all" if more else f"Show the first {max_per_lane}"
                k = {"bg": t["panel"], "border": t["edge"], "text": t["accent"], "dash": "dashed"}
                rx, flags = 10, ()
            else:
                href, flags = href_of(n), marks.get(n, ())
                k = dict(t["kind"][kind_of(n)])
                if "disabled" in flags:
                    k.update(bg=t["sunk"], border=t["edge"], text=t["muted"], dash="dashed")
                rx = h / 2 if kind_of(n) == "user" else 9
                tip = n + "".join(f" · {f}" for f in ("disabled", "sensitive") if f in flags)
            dash = ' stroke-dasharray="5 3"' if k["dash"] == "dashed" else ""
            weight = 600 if isinstance(n, tuple) else 500
            txt = "".join(f'<text x="{nx:.1f}" y="{y0 + 15 + 14 * j:.1f}" fill="{k["text"]}" font-weight="{weight}">'
                          f'{escape(s)}</text>' for j, s in enumerate(big))
            if small:
                txt += (f'<text x="{nx:.1f}" y="{y0 + 14 + 14 * len(big):.1f}" fill="{k["text"]}" font-size="10" '
                        f'opacity=".75">{escape(small)}</text>')
            if "sensitive" in flags:  # lock badge on the top right corner
                txt += (f'<g transform="translate({x0 + w - 7:.1f},{y0 - 5:.1f})"><circle r="7" fill="{t["bad_bg"]}" '
                        f'stroke="{t["bad_ink"]}"/><g transform="translate(-4.2,-4.6) scale(.35)" fill="none" '
                        f'stroke="{t["bad_ink"]}" stroke-width="3">{ICON["lock"]}</g></g>')
            nodes.append(f'<a href="{escape(href)}" target="_self"><title>{escape(tip)}</title>'
                         f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx:.1f}" '
                         f'fill="{k["bg"]}" stroke="{k["border"]}" stroke-width="1.5"{dash}/>{txt}</a>')
    size_attr = (f'width="100%" style="max-width:{W:.0f}px;height:auto;display:block"' if fit
                 else f'width="{W:.0f}" height="{H:.0f}" style="display:block"')
    # band, lane labels, edges, edge labels, then nodes on top (opaque, so edges end at their borders)
    svg = (f'<svg viewBox="0 0 {W:.0f} {H:.0f}" {size_attr} role="group" aria-label="Access graph, {len(lanes)} lanes">'
           f'{band}<g font-family="{SANS}" font-size="11" font-weight="500" letter-spacing="1" fill="{t["muted"]}">'
           f'{"".join(heads)}</g><g fill="none">{"".join(paths)}</g>'
           f'<g font-family="{MONO}" font-size="9.5" font-weight="600">{"".join(labels)}</g>'
           f'<g font-family="{MONO}" font-size="12" text-anchor="middle" dominant-baseline="central">'
           f'{"".join(nodes)}</g></svg>')
    wide = not fit and W > WIDE
    hint = f'<div class="ae-graph-hint">{len(lanes)} lanes · scroll sideways for all →</div>' if wide else ""
    return (f'{hint}<div class="ae-graph{" fit" if fit else ""}{" wide" if wide else ""}" style="background-image:'
            f'radial-gradient({t["line"]} 1px,transparent 1px);background-size:18px 18px">{svg}</div>')
