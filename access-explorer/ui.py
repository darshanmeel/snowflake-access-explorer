"""Presentation kit: theme tokens, CSS, HTML components and the depth-lane graph. No data logic.

Every helper returns an HTML string on one line (no newlines, so st.markdown never turns indentation into code blocks).
Colors come from TOKENS only: css(theme) turns the active set into :root variables, lane_graph() inlines them.
"""
import os
from html import escape
from itertools import combinations
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
PCLASS = {"read": "Read", "write": "Write", "own": "Own", "use": "Use", "admin": "Account", "inherit": "Inherits",
          "also": "Also deeper"}

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
    "Depth": "Dn = n roles from the user (or group) to the role that holds the grant, that role included. "
             "E.g. D3: you > GRP_ANALYSTS > F_ANALYST > T_SALES_CORE_READ. D1 = held by the first role.",
    "Also deeper": "The same role is also reached by a longer chain; the dotted line shows it.",
    "Use role": "The role granted to you that carries this privilege. With secondary roles ALL it is already active; "
                "otherwise run USE ROLE <it>.",
    "Future table": "A grant on every table created later in a schema (future grant). Existing tables need their own grant.",
    "Secondary roles": "All = every granted role is active in a session at once. None = only the role in use.",
    "Choke point": "A grant every path passes through: removing it removes the access.",
    "Read": "Read: SELECT, REFERENCES, or USAGE on a database or schema.",
    "Write": "Write: INSERT, UPDATE, DELETE or TRUNCATE. Changes data.",
    "Own": "Own: OWNERSHIP. Full control: can change, drop and grant the object.",
    "Use": "Use: USAGE on a warehouse, procedure or function, OPERATE or MONITOR.",
    "Account": "Account-level privilege (MANAGE GRANTS, CREATE ROLE, ...): can change access itself.",
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
/* the copy-link popover next to it: same look in both themes */
[data-testid="stPopover"] button{{width:44px;min-width:44px;min-height:40px;padding:0;background:var(--panel)!important;color:var(--ink)!important;border:1px solid var(--line)!important;border-radius:8px!important;box-shadow:none!important}}
[data-testid="stPopover"] button:hover,[data-testid="stPopover"] button:focus-visible{{border-color:var(--accent)!important;color:var(--accent)!important}}
[data-testid="stPopover"] button *{{color:inherit!important}}
[data-testid="stPopoverBody"]{{background:var(--panel)!important;color:var(--ink)!important;border:1px solid var(--line)!important}}
/* help "?" icons */
[data-testid="stTooltipIcon"],[data-testid="stTooltipIcon"] *,[data-testid="stTooltipHoverTarget"] svg{{color:var(--muted)!important;opacity:1!important}}
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
.ae-tablewrap{{overflow-x:auto;scrollbar-gutter:stable}}
.ae-tablewrap::-webkit-scrollbar{{height:10px}}.ae-tablewrap::-webkit-scrollbar-thumb{{background:var(--edge);border-radius:6px}}.ae-tablewrap::-webkit-scrollbar-track{{background:var(--sunk)}}
.ae-table td.nw{{white-space:nowrap}}
.ae-table tr.has-sub td{{padding-bottom:6px}}
.ae-table tr.sub td{{border-top:0;padding-top:0;padding-bottom:12px}}
.ae-fix{{display:inline-block;max-width:100%;padding:6px 10px;border-radius:8px;background:var(--sunk);border:1px solid var(--line);overflow-wrap:anywhere}}
.ae-wrap{{white-space:normal;overflow-wrap:anywhere}}
.ae-subline{{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-bottom:6px}}.ae-subline .ae-path{{display:inline-flex}}
.ae-table details summary{{cursor:pointer}}
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
.ae-strip{{display:flex;flex-wrap:wrap;gap:8px}}
.ae-strip a{{display:inline-flex;align-items:center;gap:8px;padding:8px 14px;border-radius:10px;background:var(--panel);border:1px solid var(--line);color:var(--ink)!important;text-decoration:none!important;font-size:13px}}
.ae-strip a b{{font-family:{SERIF};font-size:20px;font-weight:600}}
.ae-strip a.on{{border:1.5px solid var(--accent);box-shadow:0 0 0 3px var(--sunk)}}
.ae-map svg a:hover rect{{stroke:var(--accent);stroke-width:2.5}}
.ae-rgroup{{margin:6px 0 2px;font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:var(--muted)}}
.ae-rrow{{border:1px solid var(--line);border-radius:10px;background:var(--panel);margin:0 0 6px!important}}
.ae-rrow summary .cv{{display:flex;color:var(--muted);transition:transform .15s}}.ae-rrow[open] summary .cv{{transform:rotate(90deg)}}
.ae-map a{{text-decoration:none!important}}.ae-map{{overflow-x:auto}}.ae-map svg{{min-width:640px}}
.ae-rrow.on{{border:1.5px solid var(--accent)}}
.ae-rrow summary{{display:grid;grid-template-columns:96px minmax(180px,2.2fr) 120px minmax(160px,3fr) 14px;gap:12px;align-items:center;padding:9px 14px;cursor:pointer;list-style:none;font-size:13px}}
.ae-rrow summary::-webkit-details-marker{{display:none}}
.ae-rrow summary .t{{font-weight:600}}
.ae-rrow summary .m{{color:var(--muted);font-size:12.5px}}
.ae-rrow .bar{{display:flex;align-items:center;gap:8px;font-family:{MONO};font-size:12.5px}}
.ae-rrow .bar i{{display:block;height:6px;border-radius:3px;background:var(--edge);min-width:2px}}
.ae-rrow .body{{padding:2px 14px 12px 122px;font-size:13px;display:flex;flex-direction:column;gap:6px}}
.ae-rrow .body p{{margin:0}}.ae-rrow .body b{{font-weight:600}}
@media (max-width:900px){{.ae-rrow summary{{grid-template-columns:72px 1fr 48px 14px;gap:8px}}.ae-rrow summary .m{{grid-column:1/-1;order:9}}.ae-rrow .body{{padding-left:14px}}}}
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
.ae-graph.fit{{overflow-x:auto}}
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
.pc-admin{{color:var(--bad-ink);border:1.5px dotted var(--bad-ink)}}
.ae-leg-edge{{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--muted);white-space:nowrap}}
.ae-legend-lines{{margin-top:8px;gap:6px 14px}}
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
@media (max-width:640px){{
/* top bar: crumb on its own row, then search, link and theme buttons side by side */
[data-testid="stHorizontalBlock"]:has(.st-key-theme){{flex-direction:row!important;flex-wrap:wrap!important;gap:8px!important}}
[data-testid="stHorizontalBlock"]:has(.st-key-theme)>[data-testid="stColumn"]:first-child{{flex:1 1 100%!important;min-width:100%!important}}
[data-testid="stHorizontalBlock"]:has(.st-key-theme)>[data-testid="stColumn"]:nth-child(2){{flex:1 1 0!important;min-width:0!important;width:auto!important}}
[data-testid="stHorizontalBlock"]:has(.st-key-theme)>[data-testid="stColumn"]:nth-child(n+3){{flex:0 0 44px!important;min-width:44px!important;width:44px!important}}
}}
@media (max-width:480px){{
[class*="st-key-card_filter"] [data-testid="stColumn"]{{flex:1 1 100%!important;min-width:100%!important}}
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


def chip(name, kind, href=None, sensitive=False, disabled=False, title="", label=None):
    """sensitive adds a lock marker; disabled draws the chip dashed grey (a disabled user); label: text shown instead
    of the name."""
    n = escape(str(label or name))
    cls = f"ae-chip k-{kind}" + (" off" if disabled else "")
    extra = [title] if title else []
    extra += ["disabled"] * disabled + ["sensitive data"] * sensitive
    if sensitive:
        n += f'<span class="ae-sens" aria-label="sensitive">{icon("lock", 11, 2.4)}</span>'
    t = _title(" · ".join(extra))
    if href:
        return f'<a class="{cls}" href="{escape(href)}" target="_self"{t}>{n}</a>'
    return f'<span class="{cls}"{t}>{n}</span>'


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


def legend(edges=False, marks=False, extra=()):
    """Node kinds; edges=True adds the line styles (inherits, read, write, own, use; account only when in extra) on a
    row of their own; marks=True adds the disabled-user and sensitive markers. Every entry has a tooltip from HELP."""
    out = [chip(LABELS[k], k, title=tip(LABELS[k])) for k in KINDS]
    if marks:
        out += [chip("Disabled", "user", disabled=True, title=tip("Disabled")),
                chip("Sensitive", "object", sensitive=True, title=tip("Sensitive"))]
    lines = ""
    if edges:
        lines = '<div class="ae-legend ae-legend-lines">' + "".join(
            f'<span class="ae-leg-edge"{_title(tip(PCLASS[c]))}>{edge_sample(c)}{PCLASS[c]}</span>' for c in EDGE
            if c != "admin" or c in extra) + '</div>'
    return '<div class="ae-legend">' + "".join(out) + '</div>' + lines


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


def table(columns, rows, numeric_cols=(), min_width=640, tips=None, nowrap=(), subs=None):
    """rows: lists of cell HTML. numeric_cols: column names or indexes right-aligned in mono. nowrap: column names kept
    on one line. subs: per row an HTML line shown full width under it ("" for none), e.g. a long fix text.
    Headers named in HELP (Depth, Paths, Path, ...) or in tips {column: text} get a tooltip."""
    num = {i for i, c in enumerate(columns) if c in numeric_cols or i in numeric_cols}
    nw = {i for i, c in enumerate(columns) if c in nowrap}
    tt = {c: (tips or {}).get(c) or HELP.get(c, "") for c in columns}
    th = "".join(f'<th{" class=num" if i in num else ""} scope="col"{_title(tt[c])}>'
                 f'{f"<span class=ae-tip>{escape(c)}</span>" if tt[c] else escape(c)}</th>' for i, c in enumerate(columns))

    def td(i, c):
        cls = " ".join(["num"] * (i in num) + ["nw"] * (i in nw))
        return f'<td class="{cls}">{c}</td>' if cls else f"<td>{c}</td>"

    trs = []
    for row, sub in zip(rows, subs or [""] * len(rows)):
        trs.append(f'<tr{" class=has-sub" if sub else ""}>' + "".join(td(i, c) for i, c in enumerate(row)) + "</tr>")
        if sub:
            trs.append(f'<tr class="sub"><td colspan="{len(columns)}">{sub}</td></tr>')
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


def strip(items):
    """Severity strip: items [(html label, count, href, on)], each part a filter link."""
    return '<div class="ae ae-strip">' + "".join(
        f'<a class="{"on" if on else ""}" href="{escape(h)}" target="_self">{lab}<b>{n}</b></a>'
        for lab, n, h, on in items) + '</div>'


def rule_row(num, level, title, count, top, meaning, body, on=False, open_=False):
    """One rule as an expandable row: severity, number + title, count with a bar (top = largest count), meaning.
    body: HTML shown when opened."""
    w = 0 if not top else max(2, round(70 * count / top))
    bar = f'<span class="bar"><i style="width:{w}px"></i>{count}</span>'
    return (f'<details class="ae ae-rrow{" on" if on else ""}"{" open" if open_ else ""}><summary>{dot(level, True)}'
            f'<span class="t">{escape(num)} · {escape(title)}</span>{bar}<span class="m">{escape(meaning)}</span>'
            f'<span class="cv">{icon("chev", 14, 2.4)}</span></summary><div class="body">{body}</div></details>')


# rule map: the role model drawn once; rules sit as badges on the box or arrow they check
MAP_BOX = {  # spot -> (x, y, w, h, label, caption, kind)
    "user": (20, 110, 140, 44, "User", "person · service", "user"),
    "group": (230, 110, 130, 44, "Group role", "identity provider", "group"),
    "func": (430, 110, 130, 44, "Functional", "job role", "functional"),
    "tech": (630, 110, 130, 44, "Technical", "READ·WRITE·OWNER", "technical"),
    "object": (850, 110, 130, 44, "Object", "table · view · ...", "object"),
    "admin": (230, 226, 130, 40, "Admin roles", "inherit every role", "admin"),
    "public": (630, 226, 130, 40, "PUBLIC", "every user", "group"),
}
MAP_SPOT = {  # spot -> (x, y, align): box spots are a row above the box, arrow spots sit on the arrow
    "user": (20, 94, "left"), "group": (230, 94, "left"), "func": (430, 94, "left"), "object": (850, 94, "left"),
    "tech": (630, 94, "left"), "shortcut": (450, 50, "center"), "loop": (695, 92, "center"),
    "func-tech": (595, 132, "center"), "write": (805, 168, "center"), "func-object": (730, 198, "center"),
    "admin": (370, 246, "left"), "public": (845, 246, "center"),
}
MAP_HOW = ("Boxes: the role model, left to right as access flows. Grey arrows: granted to (dashed: a shortcut the "
           "model forbids). Blue: read on objects; amber: write; green dashed: use. Badges: rule number · findings, "
           "coloured by severity (grey outline: passing). Click a badge to filter.")


def rule_map(items, theme, selected=""):
    """items: [(num, spot, level, count, href, tip)], spot a MAP_SPOT key. One SVG, scales to the card width."""
    t = TOKENS[theme]
    W, H = 1000, 286
    out = []

    def arrow(d, tok="edge", sw=1.5, dash=""):
        da = f' stroke-dasharray="{dash}"' if dash else ""
        out.append(f'<path d="{d}" stroke="{t[tok]}" stroke-width="{sw}" fill="none"{da} marker-end="url(#ah-{tok})"/>')

    arrow("M160 132H226")
    arrow("M360 132H426")
    arrow("M560 132H626")
    arrow("M760 124H846", "e_read", 1.8)
    arrow("M760 142H846", "e_write", 3)
    arrow("M160 120H195V50H745V106", "edge", 1.5, "5 4")  # user straight to a technical role
    arrow("M660 110V92H730V106")  # technical role holding another technical role
    arrow("M545 154V198H900V158", "edge", 1.5, "5 4")  # functional role with a direct privilege
    arrow("M60 154V246H226")
    arrow("M760 246H930V158", "e_use", 1.8, "5 4")
    for x, y, w, h, lab, cap, k in MAP_BOX.values():
        c = t["kind"][k]
        dash = ' stroke-dasharray="5 3"' if c["dash"] == "dashed" else ""
        rx = h / 2 if k == "user" else 8
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{c["bg"]}" stroke="{c["border"]}" '
                   f'stroke-width="1.5"{dash}/><text x="{x + w / 2}" y="{y + h / 2 - 7}" fill="{c["text"]}" '
                   f'font-family="{SANS}" font-weight="600" font-size="13">{escape(lab)}</text>'
                   f'<text x="{x + w / 2}" y="{y + h / 2 + 9}" fill="{c["text"]}" font-size="10" opacity=".75">'
                   f'{escape(cap)}</text>')
    by = {}
    for it in items:
        by.setdefault(it[1], []).append(it)
    for spot, its in by.items():
        x, y, align = MAP_SPOT[spot]
        ws = [len(f"{n}·{c}") * 7 + 14 for n, _, _, c, _, _ in its]
        x0 = x if align == "left" else x - (sum(ws) + 4 * (len(ws) - 1)) / 2
        for (n, _, level, c, href, tip), w in zip(its, ws):
            tone = SEV_TONE[level]
            bg, ink, bd = (t[f"{tone}_bg"], t[f"{tone}_ink"], t[f"{tone}_bd"]) if c else (t["panel"], t["muted"], t["edge"])
            sw, bd = (2.5, t["accent"]) if n == selected else (1.2, bd)
            out.append(f'<a href="{escape(href)}" target="_self"><title>{escape(tip)}</title>'
                       f'<rect x="{x0:.1f}" y="{y - 10}" width="{w}" height="20" rx="10" fill="{bg}" stroke="{bd}" '
                       f'stroke-width="{sw}"/><text x="{x0 + w / 2:.1f}" y="{y + .5}" fill="{ink}" font-weight="600">'
                       f'{escape(n)}<tspan font-weight="400">·{c}</tspan></text></a>')
            x0 += w + 4
    marks = "".join(f'<marker id="ah-{k}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="9" markerHeight="9" '
                    f'markerUnits="userSpaceOnUse" '
                    f'orient="auto-start-reverse"><path d="M0 0L8 4L0 8z" fill="{t[k]}"/></marker>'
                    for k in ("edge", "e_read", "e_write", "e_use"))
    return (f'<div class="ae ae-map"><svg viewBox="0 0 {W} {H}" width="100%" style="max-width:{W}px;height:auto;'
            f'display:block" role="img" aria-label="Rule map"><defs>{marks}</defs><g font-family="{MONO}" '
            f'font-size="11.5" text-anchor="middle" dominant-baseline="central">{"".join(out)}</g></svg></div>')


# ---------- depth-lane graph ----------


# edge class -> (colour token, stroke width, dash, double line). Role-to-role links are "inherit"; "also" is a link
# from a deeper parent to a role already shown at a shallower depth (dotted, enters the box from the left).
EDGE = {"inherit": ("edge", 1.5, "", False), "also": ("edge", 1.5, "2 3", False), "read": ("e_read", 1.8, "", False),
        "write": ("e_write", 3, "", False), "own": ("e_own", 4.5, "", True), "use": ("e_use", 1.8, "5 4", False),
        "admin": ("bad_ink", 2, "1 3", False)}
CLS = ["inherit", "read", "write", "own", "use", "admin"]  # order of parallel edges and ports
CH, CH2, CHL = 7.2, 6.0, 6.4  # mono char width at 12px / 10px / 10.5px
TOP, PADX = 40, 12  # room for lane labels, node inner padding
LH = 16  # edge label height; ports of a node with labels are LH + 2 apart, so stacked labels never touch
CLEAR = 12  # room kept between a node and an edge passing it
LOCK = 28  # extra box width for the lock of a sensitive object (drawn inside the box)
WIDE = 1060  # a scroll-mode graph wider than this gets a hint


def wrap(s, cap, n):
    """Up to n lines of about cap chars, broken only after '_' or '.'; never cut: a part with no break point stays
    whole, the last line takes the rest (the box grows; the full name is in its title anyway)."""
    out = []
    while len(s) > cap and len(out) < n - 1:
        cut = max(s.rfind("_", 0, cap + 1), s.rfind(".", 0, cap + 1)) + 1
        if cut <= 0:  # no break point within cap: the first one after it
            cut = min([i + 1 for i in (s.find("_", cap), s.find(".", cap)) if i > 0] or [len(s)])
        if cut >= len(s):
            break
        out.append(s[:cut])
        s = s[cut:]
    return out + [s]


def _norm(e):
    """(a, b) | (a, b, cls) | (a, b, cls, label) -> (a, b, cls, label)."""
    c = (e[2] if len(e) > 2 else "") or "inherit"
    lab = e[3] if len(e) > 3 and e[3] else ("" if c == "inherit" else c)
    return e[0], e[1], c, lab


PRIVS = ["SELECT", "REFERENCES", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "OWNERSHIP", "USAGE", "OPERATE", "MONITOR"]


def plabel(privs):
    """Edge label, never cut silently: 'SELECT', 'INSERT · UPDATE', 'INSERT · UPDATE +2' (the title has all)."""
    privs = sorted(privs, key=lambda p: (PRIVS.index(p) if p in PRIVS else 99, p))
    return " · ".join(privs[:2]) + (f" +{len(privs) - 2}" if len(privs) > 2 else "")


def place(want, sep, lo, hi):
    """Positions in the given order, each near its wish, at least sep[j] after the one before, within lo..hi."""
    out = []
    for j, w in enumerate(want):
        out.append(max(w, out[-1] + sep[j] if out else lo))
    for j in range(len(out) - 1, -1, -1):
        out[j] = min(out[j], hi if j == len(out) - 1 else out[j + 1] - sep[j + 1])
    return out


def crossings(order, nxt):
    k = 0
    for i in range(len(order) - 1):
        at = {x: j for j, x in enumerate(order[i + 1])}
        segs = [(j, at[q]) for j, p in enumerate(order[i]) for q in nxt.get(p, ()) if q in at]
        k += sum((p1 - p2) * (q1 - q2) < 0 for (p1, q1), (p2, q2) in combinations(segs, 2))
    return k


def sweep(order, prv, nxt, rounds=8):
    """Barycentre ordering (layered graph, long edges as dummy nodes): sweep down then up, each lane sorted by the
    mean position of its neighbours in the lane before (after); keep the order with the fewest crossings."""
    best, low = [list(c) for c in order], crossings(order, nxt)
    for k in range(rounds):
        down = k % 2 == 0
        for i in (range(1, len(order)) if down else range(len(order) - 2, -1, -1)):
            ref = {x: j for j, x in enumerate(order[i - 1 if down else i + 1])}
            cur = {x: j for j, x in enumerate(order[i])}
            nb = prv if down else nxt
            ys = {x: [ref[m] for m in nb.get(x, ()) if m in ref] for x in order[i]}
            order[i].sort(key=lambda x: sum(ys[x]) / len(ys[x]) if ys[x] else cur[x])
        c = crossings(order, nxt)
        if c < low:
            best, low = [list(o) for o in order], c
    return best


def is_dummy(x):
    return isinstance(x, tuple) and x[0] == "d"


def lane_graph(lanes, edges, kind_of, theme, href_of, selected_lane=None, max_per_lane=12, expand="", query=None,
               fit=False, marks=None, notes=None, edge_tip=None, node_tip=None, label=None):
    """One SVG: lanes left to right, nodes are links, every edge runs left to right.
    lanes: [(label, [names])]; a name is drawn once, in the first lane that has it.
    edges: [(a, b)] or [(a, b, cls, label)], cls one of CLS (default "inherit"); one line per (a, b, cls), labels of
    one class merged. An edge whose target sits in the same or an earlier lane (a role also reached deeper) is drawn
    dotted: out of the source's top or bottom, around the nodes, into the target's left side, with an arrowhead.
    kind_of(name) -> kind; href_of(name) -> link. marks: {name: {"disabled", "sensitive", "bad"}}; label(name) ->
    (big text, small text) for a box, or None for the default (e.g. "future tables" / "SALES.CORE").
    notes: {name: (badge, tooltip)}, e.g. ("D2 · also D3", "D2: U > F > T" + newline + "D3: ..."); the badge is a
    small line in the box. fit: a compact layout scaled into the card width, never below 85% (then it scrolls), else
    full size, scroll sideways. A lane over max_per_lane shows its
    first N plus a "+K more" node (no edges) linking to query + expand=<lanes>; an expanded lane ends with a
    "Show fewer" node. edge_tip(a, b, cls, privs, back) -> hover text of an edge (a wide invisible stroke carries it);
    node_tip: {name: extra hover lines}."""
    t, marks, notes = TOKENS[theme], marks or {}, notes or {}
    opened = {int(x) for x in (expand or "").split(",") if x.isdigit()}

    def again(lanes_open):
        q = dict(query or {})
        q.pop("expand", None)
        if lanes_open:
            q["expand"] = ",".join(str(e) for e in sorted(lanes_open))
        return "?" + urlencode(q)

    cols, alias, seen = [], {}, set()
    for i, (_, names) in enumerate(lanes):
        names = [x for x in dict.fromkeys(names) if x not in seen]
        seen.update(names)
        if len(names) > max_per_lane and i not in opened:
            more = ("more", i, len(names) - max_per_lane)
            alias.update((x, more) for x in names[max_per_lane:])
            names = names[:max_per_lane] + [more]
        elif len(names) > max_per_lane:
            names = names + [("less", i, 0)]
        cols.append(names)
    n = len(cols)
    lane_of = {x: i for i, c in enumerate(cols) for x in c}
    links = {}  # (a, b, cls) -> [labels]
    for e in edges:
        a, b, c, lab = _norm(e)
        a, b = alias.get(a, a), alias.get(b, b)
        if a == b or isinstance(a, tuple) or isinstance(b, tuple) or a not in lane_of or b not in lane_of:
            continue  # "+K more" draws no edges: one hidden node's edge would look like all of them
        labs = links.setdefault((a, b, c), [])
        if lab and lab not in labs:
            labs.append(lab)
    fwd = [k for k in links if lane_of[k[0]] < lane_of[k[1]]]
    back = [k for k in links if lane_of[k[0]] >= lane_of[k[1]]]

    # order: a long edge gets a dummy node in every lane it crosses, then barycentre sweeps
    order = [[x for x in c if not isinstance(x, tuple)] for c in cols]
    tails = [[x for x in c if isinstance(x, tuple)] for c in cols]
    route, prv, nxt, near = {}, {}, {}, {}
    for a, b in dict.fromkeys((a, b) for a, b, _ in fwd):
        route[(a, b)] = ds = [("d", a, b, i) for i in range(lane_of[a] + 1, lane_of[b])]
        for d in ds:
            order[d[3]].append(d)
        hops = [a] + ds + [b]
        for p, q in zip(hops, hops[1:]):
            nxt.setdefault(p, []).append(q)
            prv.setdefault(q, []).append(p)
        near.setdefault(a, []).append(b)
        near.setdefault(b, []).append(a)
    order = sweep(order, prv, nxt)
    real = [[x for x in o if not isinstance(x, tuple)] for o in order]

    # node sizes; a node with many edges grows so every edge gets its own port
    many = n > 6
    cap, nl = (12, 3) if fit and many else (16, 3) if fit else (20, 2) if many else (40, 2)
    gap = 22 if fit and many else 40 if fit else 48 if many else 64
    k_in, k_out, labelled = {}, {}, set()
    for a, b, c in links:
        k_in[b] = k_in.get(b, 0) + 1
        if c != "inherit":
            labelled.add(b)
    for a, b, c in fwd:
        k_out[a] = k_out.get(a, 0) + 1
    size = {}  # name -> (w, h, big lines, small line)
    for c in cols:
        for x in c:
            own = None if isinstance(x, tuple) or not label else label(x)
            if isinstance(x, tuple):
                big, small = [f"+{x[2]} more" if x[0] == "more" else "Show fewer"], ""
            elif own:
                big, small = wrap(own[0], cap, max(nl - 1, 1)), own[1]
            elif kind_of(x) == "object" and "." in x:
                head, last = x.rsplit(".", 1)  # last part big, DB.SCHEMA small under it
                big, small = wrap(last, cap, max(nl - 1, 1)), head
            else:
                big, small = wrap(str(x), cap, nl), notes.get(x, ("", ""))[0]
            sens = LOCK if "sensitive" in marks.get(x, ()) else 0
            w = max([len(s) * CH for s in big] + [len(small) * CH2]) + 2 * PADX + sens
            sp = LH + 2 if x in labelled else 6
            h = max(14 * len(big) + (12 if small else 0) + 16, (k_in.get(x, 1) - 1) * sp + 22,
                    (k_out.get(x, 1) - 1) * 5 + 14)
            size[x] = (w, h, big, small)

    # rows: one integer row per real node, near the mean row of its neighbours; a run of dummies between two nodes
    # leaves extra room. All lanes share the rows, so the band between two rows is free in every lane.
    sep, spare, R = [], [], 1
    for i in range(n):
        runs, k = [], 0
        for x in order[i]:
            if is_dummy(x):
                k += 1
            else:
                runs.append(k)
                k = 0
        # an edge passing above the first or below the last node gets an empty row, not the margin under the labels
        s = [(r + 2) // 3 for r in runs[:1]] + [1 + (r + 1) // 3 for r in runs[1:]]
        sep.append(s)
        spare.append((k + 2) // 3 + len(tails[i]))  # rows kept free below the last node
        R = max(R, sum(s) + (1 if s else 0) + spare[i])
    row = {}
    for i in range(n):
        if real[i]:
            want = [(R - sum(sep[i]) - 1 - spare[i]) // 2 + sum(sep[i][:j + 1]) for j in range(len(real[i]))]
            row.update(zip(real[i], place(want, sep[i], sep[i][0], R - 1 - spare[i])))
    for k in range(6):
        for i in (range(n) if k % 2 == 0 else range(n - 1, -1, -1)):
            if real[i]:
                want = [sum(row[m] for m in near[x]) / len(near[x]) if near.get(x) else row[x] for x in real[i]]
                if i == 0 and len(real[0]) > 1:  # the start lane (users) evenly spaced, centred on its targets
                    span = sum(sep[0][1:])
                    first = min(max(round(sum(want) / len(want) - span / 2), sep[0][0]), R - 1 - spare[0] - span)
                    pos = [first + sum(sep[0][1:j + 1]) for j in range(len(real[0]))]
                else:
                    pos = place([round(w) for w in want], sep[i], sep[i][0], R - 1 - spare[i])
                row.update(zip(real[i], pos))
    for i in range(n):
        last = max([row[x] for x in real[i]], default=-1) + 1 + spare[i] - len(tails[i])
        row.update((x, last + j) for j, x in enumerate(tails[i]))
    rh = [30] * (max(row.values(), default=0) + 1)
    for x, r in row.items():
        rh[r] = max(rh[r], size[x][1] + (18 if fit else 24))
    ry, y = [], TOP
    for h in rh:
        ry.append(y + h / 2)
        y += h
    bottom = y
    cy = {x: ry[r] for x, r in row.items()}

    # columns: before each lane a curve zone (gap) and a strip for the labels of the edges entering it
    text = {k: plabel(links[k]) for k in fwd if k[2] != "inherit"}
    strip = [8] * n
    for k, s in text.items():
        strip[lane_of[k[1]]] = max(strip[lane_of[k[1]]], len(s) * CHL + 8 + 14)
    colw = [max([size[x][0] for x in c] + [len(lb) * 7.6 + 8]) for (lb, _), c in zip(lanes, cols)]
    xl, x = [], 16
    for i in range(n):
        x += strip[i]
        xl.append(x)
        x += colw[i] + gap
    W = x - gap + 16 + 24  # right margin: the last boxes never touch the card edge
    xr = [xl[i] + colw[i] for i in range(n)]
    xs = [xl[i] - strip[i] for i in range(n)]
    cx = {x: xl[lane_of[x]] + colw[lane_of[x]] / 2 for x in lane_of}

    def box(x):
        w, h = size[x][:2]
        return cx[x] - w / 2, cy[x] - h / 2, cx[x] + w / 2, cy[x] + h / 2

    stack = [sorted((box(x)[1], box(x)[3]) for x in c) for c in cols]

    # dummy nodes: a height in the free band of their lane, near the straight line, in sweep order
    dy = {}

    def dummies(yo, yi):
        for i in range(n):
            items, j = order[i] + tails[i], 0
            while j < len(items):
                if not is_dummy(items[j]):
                    j += 1
                    continue
                k = j
                while k < len(items) and is_dummy(items[k]):
                    k += 1
                run = items[j:k]
                lo = box(items[j - 1])[3] + CLEAR if j else TOP - 2
                hi = box(items[k])[1] - CLEAR if k < len(items) else bottom + 2
                if hi - lo < 6 * (len(run) - 1):
                    ys = [lo + (m + 1) * (hi - lo) / (len(run) + 1) for m in range(len(run))]
                else:
                    want = []
                    for d in run:
                        a, b = d[1], d[2]
                        f = (i - lane_of[a]) / (lane_of[b] - lane_of[a])  # level with the source, then the target:
                        want.append(min(max(yo(a, b) if f < .5 else yi(a, b), lo), hi))  # one bend, no stairs
                    ys = place(want, [0] + [6] * (len(run) - 1), lo, hi)
                dy.update(zip(run, ys))
                j = k

    dummies(lambda a, b: cy[a], lambda a, b: cy[b])

    # ports: every edge leaves / enters at its own height, ordered by where it comes from / goes to
    pairs, ins, outs, py = {}, {}, {}, {}
    for a, b, c in fwd:
        pairs.setdefault((a, b), []).append(c)
        outs.setdefault(a, []).append((a, b, c))
    for k in fwd + back:
        ins.setdefault(k[1], []).append(k)
    for cs in pairs.values():
        cs.sort(key=lambda c: CLS.index(c) if c in CLS else 9)

    def before(k):
        ds = route.get(k[:2])
        return dy[ds[-1]] if ds else cy[k[0]]

    def after(k):
        ds = route[k[:2]]
        return dy[ds[0]] if ds else cy[k[1]]

    def rank(c):
        return CLS.index(c) if c in CLS else 9

    for x, ks in ins.items():
        sp = LH + 2 if x in labelled else 6
        ks.sort(key=lambda k: (before(k), rank(k[2]), k[0]))
        py.update(((k, 1), cy[x] + (j - (len(ks) - 1) / 2) * sp) for j, k in enumerate(ks))
    for x, ks in outs.items():
        ks.sort(key=lambda k: (after(k), rank(k[2]), k[1]))
        py.update(((k, 0), cy[x] + (j - (len(ks) - 1) / 2) * 5) for j, k in enumerate(ks))

    def port(a, b, end):
        ys = [py[((a, b, c), end)] for c in pairs[(a, b)]]
        return sum(ys) / len(ys)

    dummies(lambda a, b: port(a, b, 0), lambda a, b: port(a, b, 1))

    paths, labels, heads, hits = [], [], [], []

    def draw(k, d, tok, sw, dash, double, tip, back_edge=False):
        a, b, c = k
        if edge_tip:
            tip = edge_tip(a, b, c, links[k], back_edge) or tip
        hits.append(f'<path d="{d}" stroke="transparent" stroke-width="12" pointer-events="stroke">'
                    f'<title>{escape(tip)}</title></path>')
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        mark = ' data-back="1"' if back_edge else ""
        paths.append(f'<path d="{d}" stroke="{t[tok]}" stroke-width="{sw}"{extra} data-a="{escape(a)}" '
                     f'data-b="{escape(b)}" data-c="{c}"{mark}><title>{escape(tip)}</title></path>')
        if double:
            paths.append(f'<path d="{d}" stroke="{t["panel"]}" stroke-width="1.6"/>')

    for k in sorted(fwd, key=lambda k: k[2] != "inherit"):  # class edges on top
        a, b, c = k
        cs = pairs[(a, b)]
        off = (cs.index(c) - (len(cs) - 1) / 2) * 3  # two classes on one pair: parallel lines through the gaps
        la, lb = lane_of[a], lane_of[b]
        segs = [(box(a)[2], xr[la], py[(k, 0)])]
        segs += [(xs[d[3]], xr[d[3]], dy[d] + off) for d in route[(a, b)]]
        segs.append((xs[lb], box(b)[0], py[(k, 1)]))
        d = f"M{segs[0][0]:.1f} {segs[0][2]:.1f}H{segs[0][1]:.1f}"
        for (_, x0, y0), (x1, x2, y1) in zip(segs, segs[1:]):
            m = (x0 + x1) / 2  # S-curves only in the gaps between lanes, straight runs through the lanes
            d += f"C{m:.1f} {y0:.1f} {m:.1f} {y1:.1f} {x1:.1f} {y1:.1f}H{x2:.1f}"
        tok, sw, dash, double = EDGE.get(c, EDGE["inherit"])
        full = ", ".join(sorted(links[k], key=lambda p: (PRIVS.index(p) if p in PRIVS else 99, p)))
        draw(k, d, tok, sw, dash, double, f"{a} → {b}: {full}" if c != "inherit" else f"{a} → {b} (inherits)")
        if k in text:  # on the edge's own last straight run, just before the target
            s, ly = text[k], py[(k, 1)]
            lw = len(s) * CHL + 8
            labels.append(f'<g data-a="{escape(a)}" data-b="{escape(b)}" data-c="{c}"><title>{escape(full)}</title>'
                          f'<rect x="{xl[lb] - 6 - lw:.1f}" y="{ly - LH / 2:.1f}" width="{lw:.1f}" height="{LH}" '
                          f'rx="3" fill="{t["panel"]}" stroke="{t[tok]}" stroke-width=".8"/>'
                          f'<text x="{xl[lb] - 6 - lw / 2:.1f}" y="{ly + .5:.1f}" fill="{t[tok]}">{escape(s)}</text></g>')

    def free(y, i):
        return all(not (y0 - 6 < y < y1 + 6) for y0, y1 in stack[i])

    from_src, into_lane, low = {}, {}, bottom
    for k in back:
        a, b, c = k
        la, lb = lane_of[a], lane_of[b]
        ty, (x0, y0, x1, y1) = py[(k, 1)], box(a)
        j = from_src[a] = from_src.get(a, -1) + 1
        sx = cx[a] + max(min((0, 10, -10, 20, -20)[j % 5], (x1 - x0) / 2 - 8), 8 - (x1 - x0) / 2)
        ends = [v for pair in stack[la] for v in pair]
        if ty >= cy[a]:  # out of the bottom (top) into the free band right below (above) the source
            lo, hi, sy = y1 + 6, min([v for v in ends if v > y1 + 1] + [bottom + 4]) - 6, y1
        else:
            lo, hi, sy = max([v for v in ends if v < y0 - 1] + [TOP - 4]) + 6, y0 - 6, y0
        mid = (lo + hi) / 2
        ok = [v for v in sorted((lo + 2 * m for m in range(int((hi - lo) / 2) + 1)), key=lambda v: abs(v - mid))
              if all(free(v, i) for i in range(lb, la + 1))]
        g = into_lane[lb] = into_lane.get(lb, -1) + 1
        xg = max(xs[lb] - 10 - 6 * g, (xr[lb - 1] if lb else 0) + 4)
        if ok:
            d = f"M{sx:.1f} {sy:.1f}V{ok[0]:.1f}H{xg:.1f}V{ty:.1f}H{box(b)[0]:.1f}"
        else:  # no height free in every lane between: into the curve zone, then round below every node
            low += 8
            xc = max(xs[la] - 10 - 6 * j, xr[la - 1] + 4)
            d = f"M{sx:.1f} {sy:.1f}V{mid:.1f}H{xc:.1f}V{low:.1f}H{xg:.1f}V{ty:.1f}H{box(b)[0]:.1f}"
        tok = EDGE.get(c, EDGE["inherit"])[0]
        draw(k, d, tok, 1.5, EDGE["also"][2], False, f"{a} → {b} (inherits; {b} is drawn once, at its shortest depth)", True)
        bx = box(b)[0]
        heads.append(f'<path d="M{bx - 9:.1f} {ty - 5:.1f}l9 5l-9 5z" fill="{t[tok]}" stroke="none"/>')
    H = max(bottom, low + 8) + 12

    band, lanes_txt, nodes = "", [], []
    for i, ((lb, _), c) in enumerate(zip(lanes, cols)):
        if i == selected_lane:
            band = (f'<rect x="{xl[i] - gap / 3:.1f}" y="2" width="{colw[i] + gap * 2 / 3:.1f}" height="{H - 4:.0f}" '
                    f'rx="10" fill="{t["sunk"]}" stroke="{t["line"]}" stroke-dasharray="4 3"/>')
        lanes_txt.append(f'<text x="{xl[i] + colw[i] / 2:.1f}" y="22" text-anchor="middle">{escape(lb.upper())}</text>')
        for x in c:
            w, h, big, small = size[x]
            x0, y0 = cx[x] - w / 2, cy[x] - h / 2
            badge = False
            if isinstance(x, tuple):
                more = x[0] == "more"
                href = again(opened | {i} if more else opened - {i})
                tip, key = ("Show all" if more else f"Show the first {max_per_lane}"), f"+{x[0]}{i}"
                k = {"bg": t["panel"], "border": t["edge"], "text": t["accent"], "dash": "dashed"}
                rx, flags = 10, ()
            else:
                href, flags, key = href_of(x), marks.get(x, ()), x
                k = dict(t["kind"][kind_of(x)])
                if "disabled" in flags:
                    k.update(bg=t["sunk"], border=t["edge"], text=t["muted"], dash="dashed")
                if "bad" in flags:
                    k.update(border=t["bad_ink"])
                rx = h / 2 if kind_of(x) == "user" else 9
                tip = x + "".join(f" · {f}" for f in ("disabled", "sensitive") if f in flags)
                tip += "\n" + node_tip[x] if node_tip and node_tip.get(x) else ""
                tip += "\n" + notes[x][1] if notes.get(x, ("", ""))[1] else ""
                badge = kind_of(x) != "object"
            dash = ' stroke-dasharray="5 3"' if k["dash"] == "dashed" else ""
            weight = 600 if isinstance(x, tuple) else 500
            top = cy[x] - (14 * len(big) + (12 if small else 0)) / 2  # text block centred in a grown box
            txt = "".join(f'<text x="{cx[x]:.1f}" y="{top + 7 + 14 * j:.1f}" fill="{k["text"]}" '
                          f'font-weight="{weight}">{escape(s)}</text>' for j, s in enumerate(big))
            if small:
                txt += (f'<text x="{cx[x]:.1f}" y="{top + 6 + 14 * len(big):.1f}" '
                        f'fill="{t["accent"] if badge else k["text"]}" font-size="10" '
                        f'opacity="{1 if badge else .75}">{escape(small)}</text>')
            if "sensitive" in flags:  # lock inside the box, right of the first line
                txt += (f'<g transform="translate({x0 + w - PADX - 11:.1f},{top + 1:.1f}) scale(.46)" fill="none" '
                        f'stroke="{t["bad_ink"]}" stroke-width="2.6" stroke-linecap="round">{ICON["lock"]}</g>')
            nodes.append(f'<a href="{escape(href)}" target="_self" data-n="{escape(key)}"><title>{escape(tip)}</title>'
                         f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx:.1f}" '
                         f'fill="{k["bg"]}" stroke="{k["border"]}" stroke-width="{2.5 if "bad" in flags else 1.5}"'
                         f'{dash}/>{txt}</a>')
    size_attr = (f'width="100%" style="min-width:{W * .85:.0f}px;max-width:{W:.0f}px;height:auto;display:block"' if fit
                 else f'width="{W:.0f}" height="{H:.0f}" style="display:block"')
    # band, lane labels, edges, arrowheads, edge labels, then nodes on top
    svg = (f'<svg viewBox="0 0 {W:.0f} {H:.0f}" {size_attr} role="group" aria-label="Access graph, {n} lanes">'
           f'{band}<g font-family="{SANS}" font-size="11" font-weight="500" letter-spacing="1" fill="{t["muted"]}">'
           f'{"".join(lanes_txt)}</g><g fill="none">{"".join(paths)}</g><g>{"".join(heads)}</g>'
           f'<g fill="none" class="ae-hit">{"".join(hits)}</g>'
           f'<g font-family="{MONO}" font-size="10.5" font-weight="600" text-anchor="middle" '
           f'dominant-baseline="central">{"".join(labels)}</g>'
           f'<g font-family="{MONO}" font-size="12" text-anchor="middle" dominant-baseline="central">'
           f'{"".join(nodes)}</g></svg>')
    wide = W * (.85 if fit else 1) > WIDE
    hint = f'<div class="ae-graph-hint">{n} lanes · scroll sideways for all →</div>' if wide else ""
    return (f'{hint}<div class="ae-graph{" fit" if fit else ""}{" wide" if wide else ""}" style="background-image:'
            f'radial-gradient({t["line"]} 1px,transparent 1px);background-size:18px 18px">{svg}</div>')


LOADED = os.path.getmtime(__file__)  # app.fresh() reloads this module when the file is newer
