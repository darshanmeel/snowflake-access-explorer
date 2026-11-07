"""Presentation constants of server.py, most sent to the React app in /api/meta: theme tokens and node styles, privilege
classes, object type icons, help texts and the privilege order. No data logic, no drawing: pages and graphs are the
React components in web/src/components."""

KINDS = ["user", "functional", "technical", "group", "database", "admin", "object"]
SHAPE = {"user": ("999px", "solid"), "functional": ("6px", "solid"), "technical": ("6px", "solid"),
         "group": ("6px", "dashed"), "database": ("6px", "dashed"), "admin": ("6px", "solid"),
         "object": ("12px / 9px", "solid")}


def _kinds(rows):
    return {k: {"bg": bg, "border": bd, "text": ink, "radius": SHAPE[k][0], "dash": SHAPE[k][1]}
            for k, (bg, bd, ink) in zip(KINDS, rows)}


TOKENS = {
    "light": {"bg": "#F6F7F9", "side": "#FFFFFF", "panel": "#FFFFFF", "sunk": "#F3F5F8", "line": "#E3E6EB", "line_strong": "#C9D2DE", "ink": "#14171C", "ink2": "#333A45", "muted": "#5B6472", "accent": "#1D5FD1", "accent_ink": "#123F91", "accent_soft": "#E4ECFB", "edge": "#A3ADBB", "warn_bg": "#FFF7EE", "warn_ink": "#8A4305", "warn_bd": "#F3D3AE", "bad_bg": "#FDECEA", "bad_ink": "#B42318", "bad_bd": "#F4C2BC", "ok_bg": "#E7F4EA", "ok_ink": "#1E6B32", "ok_bd": "#B8DEC2", "low_bg": "#F3F5F8", "low_ink": "#5B6472", "low_bd": "#D5DBE3", "e_read": "#7FA6E8", "e_write": "#3E78D9", "e_own": "#1D5FD1", "e_use": "#8792A2", "e_manage": "#0E2F6B", "lvl_names_bg": "#F3F5F8", "lvl_names_ink": "#5B6472", "lvl_read_bg": "#DCE8FB", "lvl_read_ink": "#1A4FA8", "lvl_change_bg": "#8FB3EE", "lvl_change_ink": "#0B2A5E", "lvl_own_bg": "#1D5FD1", "lvl_own_ink": "#FFFFFF", "lvl_admin_bg": "#0E2F6B", "lvl_admin_ink": "#FFFFFF", "sens_bg": "#FDEBD3", "sens_ink": "#8A4305",
        "kind": _kinds([("#FFFFFF", "#333A45", "#14171C"), ("#DFE9F6", "#30476B", "#1D2C44"), ("#EEDDC8", "#8C5D34", "#4A2E14"), ("#FAEBCB", "#B07A1E", "#553806"), ("#E6EBF2", "#56677F", "#24303F"), ("#FDECEA", "#B42318", "#8C271D"), ("#EEF1F5", "#5B6472", "#14171C")])},
    "dark": {"bg": "#0F1216", "side": "#171B21", "panel": "#171B21", "sunk": "#1C2129", "line": "#2A303A", "line_strong": "#3A4250", "ink": "#E8EBF0", "ink2": "#C9CED6", "muted": "#A3ABB8", "accent": "#6E9CF0", "accent_ink": "#A9C4F0", "accent_soft": "#1C2C47", "edge": "#5A6577", "warn_bg": "#2A2015", "warn_ink": "#F7B267", "warn_bd": "#5A3D1C", "bad_bg": "#3A1A18", "bad_ink": "#FF9B8F", "bad_bd": "#6A2A24", "ok_bg": "#16301E", "ok_ink": "#8FD3A1", "ok_bd": "#2D5235", "low_bg": "#222833", "low_ink": "#A3ABB8", "low_bd": "#3A4250", "e_read": "#6F8FC4", "e_write": "#6E9CF0", "e_own": "#A9C4F0", "e_use": "#7D8796", "e_manage": "#C9D9F5", "lvl_names_bg": "#222833", "lvl_names_ink": "#A3ABB8", "lvl_read_bg": "#1C2C47", "lvl_read_ink": "#A9C4F0", "lvl_change_bg": "#2E4F8C", "lvl_change_ink": "#E4ECFB", "lvl_own_bg": "#4C82E6", "lvl_own_ink": "#0B1220", "lvl_admin_bg": "#A9C4F0", "lvl_admin_ink": "#0B1B3A", "sens_bg": "#3A2612", "sens_ink": "#F7B267",
        "kind": _kinds([("#171B21", "#C9CED6", "#E8EBF0"), ("#1C2A3F", "#7EA3D6", "#D5E3F6"), ("#35271A", "#C5926A", "#F1DCC5"), ("#352913", "#D7A443", "#F3DDAE"), ("#1D232C", "#93A6C0", "#DCE4EE"), ("#3A1B18", "#E27A6B", "#F6C3BA"), ("#222833", "#8792A2", "#E8EBF0")])},
}
PCLASS = {"read": "Read", "write": "Write", "own": "Own", "use": "Use", "manage": "Manage", "admin": "Account",
          "inherit": "Inherits", "also": "Also deeper"}
# object type -> (glyph, label) shown next to object names (text glyphs, no emoji)
TYPE_ICON = {"TABLE": ("▦", "table"), "VIEW": ("◫", "view"), "MATERIALIZED VIEW": ("◫", "materialized view"),
             "DYNAMIC TABLE": ("⟳", "dynamic table"), "EXTERNAL TABLE": ("▦", "external table"),
             "TASK": ("⏲", "task"), "STREAM": ("≋", "stream"), "STAGE": ("⇪", "stage"), "PIPE": ("⇢", "pipe"),
             "FUNCTION": ("ƒ", "function"), "PROCEDURE": ("ƒ", "procedure"), "SEQUENCE": ("#", "sequence"),
             "WAREHOUSE": ("⚙", "warehouse"), "SCHEMA": ("◇", "schema"), "DATABASE": ("◆", "database"),
             "ACCOUNT": ("!", "account")}

# plain-language definitions (meta.help): tooltips on legend chips, KPI labels, table headers and D badges
HELP = {
    "User": "A Snowflake login: a person, or a service user (TYPE = SERVICE) used by tools and pipelines.",
    "Functional": "Functional role: a job role (e.g. analyst, engineer) granted to users or group roles. "
                  "It holds technical roles, not objects.",
    "Technical": "Technical role: holds the privileges on one database or schema, as OWNER, READ, WRITE or EXECUTE.",
    "Group / other": "Any other role, e.g. a group role synced from the identity provider, or PUBLIC (every user has it).",
    "Database role": "A role inside one database, named DB.ROLE. Granted to an account role, which then holds it and "
                     "gets everything it holds (e.g. USAGE on a schema, SELECT on its tables). Never granted to users directly.",
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
    "Use": "Use: USAGE on a warehouse, procedure or function, or MONITOR.",
    "Manage": "Manage: CREATE ..., MODIFY, OPERATE or APPLY ...: changes, runs or resizes objects without touching data.",
    "Account": "Account-level privilege (MANAGE GRANTS, CREATE ROLE, ...): can change access itself.",
    "Inherits": "Role-to-role link: the role on the left is granted the one on the right and gets all it holds.",
    "Sensitive": "Tagged as personal or confidential data: on a column, on the object, or inherited from its schema or database.",
    "Masked": "A masking policy hides the value for this role. Read from the policy text, not evaluated by Snowflake.",
    "Dormant": "No login for the dormant period (default 90 days) before the snapshot, or never logged in.",
    "Disabled": "The user is disabled and can't log in, but its grants stay until revoked.",
}
PRIVS = ["SELECT", "REFERENCES", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "OWNERSHIP", "USAGE", "OPERATE", "MODIFY",
         "MONITOR"]


def psort(privs):
    """Privileges in a fixed order; 'SELECT ×120' sorts as SELECT."""
    key = lambda p: p.split(" ×")[0]
    return sorted(privs, key=lambda p: (PRIVS.index(key(p)) if key(p) in PRIVS else 99, p))
