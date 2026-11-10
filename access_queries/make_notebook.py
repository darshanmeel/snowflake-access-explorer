"""Builds access_examples.ipynb (a Snowflake Notebook) from the query files and functions.sql, so the notebook
never drifts: python access_queries/make_notebook.py. test_queries.py fails if the file on disk is out of date."""
import json
import pathlib
import re

HERE = pathlib.Path(__file__).parent
OUT = HERE / "access_examples.ipynb"
FN = "AQ_DB.AQ_SCHEMA."


def body(name):
    t = (HERE / name).read_text(encoding="utf-8")
    return t[t.index("WITH RECURSIVE"):].rstrip().rstrip(";")


def bare(name):  # the query without its last ORDER BY, to wrap it
    return re.sub(r"\nORDER BY [^\n]*$", "", body(name))


def wrap(name, where, order):
    return f"SELECT *\nFROM (\n{bare(name)}\n)\nWHERE {where}\nORDER BY {order};"


# (cell name, title, function call, plain query)
EXAMPLES = [
    ("roles_of_user", "1. Every role a user holds, direct and inherited",
     f"SELECT * FROM TABLE({FN}AQ_USER_ROLES($USER_NAME, $MAX_DEPTH)) ORDER BY DEPTH, ROLE_NAME;",
     body("1_user_roles.sql") + ";"),
    ("access_of_user", "2. Everything a user can finally do, and through which role",
     f"SELECT * FROM TABLE({FN}AQ_USER_ACCESS($USER_NAME, $MAX_DEPTH)) ORDER BY OBJECT_NAME, PRIVILEGE;",
     body("2_user_access.sql") + ";"),
    ("user_reaches_object", "3. Does the user reach this object, and how? (the user's access, filtered)",
     f"SELECT * FROM TABLE({FN}AQ_USER_ACCESS($USER_NAME, $MAX_DEPTH))\nWHERE OBJECT_NAME = $OBJECT_NAME ORDER BY PRIVILEGE;",
     wrap("2_user_access.sql", "OBJECT_NAME = $OBJECT_NAME", "PRIVILEGE")),
    ("access_of_role", "4. Everything a role grants, its own and that of every role below it",
     f"SELECT * FROM TABLE({FN}AQ_ROLE_ACCESS($ROLE_NAME, $MAX_DEPTH)) ORDER BY OBJECT_NAME, PRIVILEGE;",
     body("3_role_access.sql") + ";"),
    ("holders_of_role", "5. Who holds a role, upwards: the roles above it and the users at the end",
     f"SELECT * FROM TABLE({FN}AQ_ROLE_HOLDERS($ROLE_NAME, $MAX_DEPTH)) ORDER BY HOLDER_KIND DESC, DEPTH, HOLDER;",
     body("4_role_holders.sql") + ";"),
    ("users_of_object", "6. Which users can use this object with this privilege (set PRIVILEGE to '' for any)",
     f"SELECT * FROM TABLE({FN}AQ_OBJECT_USERS($OBJECT_NAME, $PRIVILEGE, $MAX_DEPTH))\n"
     "WHERE GRANTEE_KIND = 'USER' ORDER BY GRANTEE;",
     wrap("5_object_users.sql", "GRANTEE_KIND = 'USER'", "GRANTEE")),
    ("deep_users", "7. Users that reach the object through more than MIN_DEPTH roles",
     f"SELECT * FROM TABLE({FN}AQ_OBJECT_USERS($OBJECT_NAME, $PRIVILEGE, $MAX_DEPTH))\n"
     "WHERE GRANTEE_KIND = 'USER' AND DEPTH > $MIN_DEPTH ORDER BY DEPTH DESC, GRANTEE;",
     wrap("5_object_users.sql", "GRANTEE_KIND = 'USER' AND DEPTH > $MIN_DEPTH", "DEPTH DESC, GRANTEE")),
    ("access_summary", "8. A user's access summarized: objects per role and privilege",
     f"SELECT VIA_ROLE, PRIVILEGE, COUNT(*) AS OBJECTS\nFROM TABLE({FN}AQ_USER_ACCESS($USER_NAME, $MAX_DEPTH))\n"
     "GROUP BY VIA_ROLE, PRIVILEGE ORDER BY VIA_ROLE, PRIVILEGE;",
     f"SELECT VIA_ROLE, PRIVILEGE, COUNT(*) AS OBJECTS\nFROM (\n{bare('2_user_access.sql')}\n)\n"
     "GROUP BY VIA_ROLE, PRIVILEGE ORDER BY VIA_ROLE, PRIVILEGE;"),
]

INTRO = """# Who has what: access examples

Answers "which roles does a user hold", "what can a user finally do", "who holds a role", "who reaches an object"
from `SNOWFLAKE.ACCOUNT_USAGE`. Read-only: no business data, nothing written except the optional functions of path A.

**Needs:** read access to `SNOWFLAKE.ACCOUNT_USAGE` (`IMPORTED PRIVILEGES` on database `SNOWFLAKE`, or the database
role `SNOWFLAKE.SECURITY_VIEWER`) and a warehouse. The data lags up to about 2 hours.

**Choose one path:**
- **A. Create the table functions first** (needs `CREATE FUNCTION` on a schema), then call them in one line.
- **B. Run the queries directly**: nothing is created; each cell holds the full query.

Run the inputs cell, then either the cells of A or those of B. Both give the same rows."""

INPUTS = """-- Replace with yours. Used by every example below.
SET USER_NAME = 'ANALYST_01';
SET ROLE_NAME = 'F_ANALYST';
SET OBJECT_NAME = 'SALES.CORE.TBL_CUSTOMER';   -- DB, DB.SCHEMA or DB.SCHEMA.OBJECT
SET PRIVILEGE = 'SELECT';                       -- '' = any
SET MAX_DEPTH = 50;
SET MIN_DEPTH = 2;                              -- example 7: more than this many roles
SET SHOW_BUILTIN = FALSE;                       -- path B only"""

A_NOTE = """## Path A: create the functions

Replace `AQ_DB.AQ_SCHEMA` with a database and schema of yours in every cell below (find and replace), then run the five
`CREATE` cells. If one fails (a recursive query or ACCOUNT_USAGE not allowed in a function in your account), use path B.
A function reads ACCOUNT_USAGE with its owner's rights: grant `USAGE` on it only to roles that may see every grant."""

B_NOTE = """## Path B: run the queries directly

Same questions, no functions. Each query is the content of its file in `access_queries/`; the inputs cell supplies
the `$NAME` values."""


def cell(kind, name, text):
    c = {"cell_type": kind, "id": name, "metadata": {"name": name}, "source": text.splitlines(keepends=True)}
    if kind == "code":
        c["metadata"] |= {"language": "sql"}
        c |= {"execution_count": None, "outputs": []}
    return c


def notebook():
    md = lambda n, t: cell("markdown", n, t)
    cells = [md("intro", INTRO), cell("code", "inputs", INPUTS), md("path_a", A_NOTE)]
    fns = (HERE / "functions.sql").read_text(encoding="utf-8")
    for i, m in enumerate(re.finditer(r"CREATE OR REPLACE FUNCTION .*?\n\$\$;", fns, re.S)):
        cells.append(cell("code", f"create_{i + 1}", m.group(0)))
    for name, title, call, _ in EXAMPLES:
        cells += [md(f"a_{name}_md", f"### A. {title}"), cell("code", f"a_{name}", call)]
    cells.append(md("path_b", B_NOTE))
    for name, title, _, query in EXAMPLES:
        cells += [md(f"b_{name}_md", f"### B. {title}"), cell("code", f"b_{name}", query)]
    return {"cells": cells, "nbformat": 4, "nbformat_minor": 5,
            "metadata": {"kernelspec": {"display_name": "Streamlit Notebook", "name": "streamlit"}}}


def text():
    return json.dumps(notebook(), indent=1) + "\n"


if __name__ == "__main__":
    OUT.write_text(text(), encoding="utf-8")
    print("wrote", OUT.name)
