"""Structure extractor: git-tracked and untracked-not-ignored files -> graph/parts/structure.nodes.jsonl + structure.edges.jsonl.
Stdlib only, rerunnable: python snowflake-access-explorer-knowledge-graph/_scripts/extract.py
Every node/edge cites path:line taken from the source; validate() re-opens each cited line."""
import ast
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

KG = Path(__file__).resolve().parents[1]
ROOT = KG.parent
OUT = KG / "graph" / "parts"
REPO = ROOT.name

SKIP_PREFIX = ("web/dist", "docs/img", "snowflake-access-explorer-knowledge-graph/")
SKIP_FILES = {"web/package-lock.json"}
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".pkl", ".zip", ".pdf", ".duckdb"}

nodes = {}   # id -> node
edges = {}   # (from, to, type) -> edge
LINES = {}   # path -> list of lines


def add_node(id, type, name, path, line, line_end, summary, tags=(), status="verified"):
    if id in nodes:
        return id
    nodes[id] = dict(id=id, type=type, name=name, path=path, line=line, line_end=line_end,
                     summary=summary[:400], tags=list(tags), status=status)
    return id


def add_edge(a, b, type, path, line, status="verified"):
    k = (a, b, type)
    if k not in edges and a != b:
        edges[k] = {"from": a, "to": b, "type": type, "evidence": f"{path}:{line}", "status": status}


def tracked():
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.split("\n")
    keep = []
    for p in dict.fromkeys(out):
        if not p or p in SKIP_FILES or p.startswith(SKIP_PREFIX) or Path(p).suffix.lower() in BINARY_EXT:
            continue
        try:
            LINES[p] = (ROOT / p).read_text(encoding="utf-8").split("\n")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        if LINES[p] and LINES[p][-1] == "":
            LINES[p].pop()
        keep.append(p)
    return keep


def first_line(doc):
    return (doc or "").strip().split("\n")[0][:200]


# ---------- repo, folders, files ----------

def structure(files):
    rid = add_node(f"repo:{REPO}", "repo", REPO, ".", 1, 1, "Read-only app explaining Snowflake RBAC access (CLAUDE.md:1-3).", ["root"])
    for p in files:
        parts = p.split("/")
        parent = rid
        for i in range(1, len(parts)):
            d = "/".join(parts[:i])
            did = add_node(f"folder:{d}", "folder", parts[i - 1], d, 1, 1, f"Folder {d}", [])
            add_edge(parent, did, "contains", p, 1)
            parent = did
        n = len(LINES[p])
        ext = Path(p).suffix.lstrip(".") or "none"
        summ = f"{ext} file, {n} lines"
        if ext == "md":
            h = next((l for l in LINES[p] if l.startswith("#")), "")
            summ = f"{h.lstrip('# ').strip()} ({n} lines)" if h else summ
        fid = add_node(f"file:{p}", "file", parts[-1], p, 1, max(n, 1), summ, [ext])
        add_edge(parent, fid, "contains", p, 1)


# ---------- Python ----------

def py_module_of(modname, pyfiles, here=""):
    """Repo-root module, else one next to the importing file (access_queries/ puts its own folder on sys.path)."""
    f = modname.replace(".", "/") + ".py"
    for c in (f, (Path(here).parent / f).as_posix()):
        if c in pyfiles:
            return c
    return None


# test files whose checks are plain functions (no test_ prefix): these become test_case nodes
CHECKS = {"access_queries/test_queries.py": {"user_roles", "access", "holders", "object_users", "functions", "notebook"}}
PENDING = []  # (test_case, file, path, line): resolved to query task nodes after the SQL pass


def py_pass1(p, tree):
    """Register function/class nodes; return per-file info."""
    info = dict(top={}, owners={})  # top: name -> id ; owners: id(ast node) -> node id
    doc = first_line(ast.get_docstring(tree))
    nodes[f"file:{p}"]["summary"] = (doc or nodes[f"file:{p}"]["summary"])[:400]
    nodes[f"file:{p}"]["tags"].append("python-module")
    is_test = Path(p).name.startswith("test_")

    def reg_func(fn, qual, nested=False):
        sig = f"{'async ' if isinstance(fn, ast.AsyncFunctionDef) else ''}def {fn.name}({ast.unparse(fn.args)})"
        ret = ast.unparse(fn.returns) if fn.returns else None
        if ret:
            sig += f" -> {ret}"
        tags = [f"params:{len(fn.args.args) + len(fn.args.kwonlyargs)}", f"lines:{fn.lineno}-{fn.end_lineno}"]
        if ret:
            tags.append(f"returns:{ret}")
        if nested:
            tags.append("nested")
        if is_test and (fn.name.startswith("test_") or qual in CHECKS.get(p, ())):
            nid = f"test_case:{p}:{qual}"
            add_node(nid, "test_case", qual, p, fn.lineno, fn.end_lineno, f"{first_line(ast.get_docstring(fn)) or 'Test'} ({sig})", tags + ["test"])
        else:
            nid = f"function:{p}:{qual}"
            if nid in nodes:
                nid += f"@{fn.lineno}"
            add_node(nid, "function", qual, p, fn.lineno, fn.end_lineno, f"{sig}. {first_line(ast.get_docstring(fn))}".strip(), tags)
        add_edge(f"file:{p}", nid, "contains", p, fn.lineno)
        info["owners"][id(fn)] = nid
        return nid

    def flat(body):
        for s in body:
            if isinstance(s, (ast.If, ast.Try, ast.With)):
                for b in (s.body, getattr(s, "orelse", []), *[h.body for h in getattr(s, "handlers", [])]):
                    yield from flat(b)
            else:
                yield s

    for s in flat(tree.body):
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info["top"].setdefault(s.name, reg_func(s, s.name))
        elif isinstance(s, ast.ClassDef):
            cid = add_node(f"class:{p}:{s.name}", "class", s.name, p, s.lineno, s.end_lineno,
                           f"class {s.name}. {first_line(ast.get_docstring(s))}".strip(), [f"lines:{s.lineno}-{s.end_lineno}"])
            add_edge(f"file:{p}", cid, "contains", p, s.lineno)
            for m in s.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    info["top"].setdefault(f"{s.name}.{m.name}", reg_func(m, f"{s.name}.{m.name}"))
    # nested route handlers (decorated with app.get/post): server.make_app
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and id(fn) not in info["owners"] and route_deco(fn):
            parent = next((q for q in ast.walk(tree) if isinstance(q, ast.FunctionDef) and fn in ast.walk(q) and q is not fn), None)
            reg_func(fn, f"{parent.name + '.' if parent else ''}{fn.name}", nested=True)
    return info


def route_deco(fn):
    for d in fn.decorator_list:
        if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and isinstance(d.func.value, ast.Name)
                and d.func.value.id == "app" and d.func.attr in ("get", "post") and d.args
                and isinstance(d.args[0], ast.Constant)):
            return d.func.attr.upper(), d.args[0].value
    return None


TBL_RE = re.compile(r"TBL_ACCESS_\w+|SNOWFLAKE\.ACCOUNT_USAGE\.\w+|ACCOUNT_USAGE\.\w+")
GRANT_RE = re.compile(r"GRANT\s+[\w ,]+\s+ON\s+(?:ALL\s+|FUTURE\s+)?(?:TABLES?\s+(?:IN\s+SCHEMA\s+)?)?$", re.I)
WRITE_RE = re.compile(r"(DROP\s+(?:TABLE|VIEW)(?:\s+IF\s+EXISTS)?|INSERT\s+(?:OVERWRITE\s+)?INTO|MERGE\s+INTO|DELETE\s+FROM|TRUNCATE\s+TABLE|TRUNCATE|UPDATE|CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP\w*\s+)?TABLE(?:\s+IF\s+NOT\s+EXISTS)?)\s+$", re.I)


def table_id(raw):
    raw = raw.upper()
    if raw.startswith("TBL_ACCESS_"):
        return f"table:{raw}"
    if raw.startswith("ACCOUNT_USAGE."):
        raw = "SNOWFLAKE." + raw
    return f"table:{raw}"


def ensure_table(tid, path, line, status="verified"):
    name = tid.split(":", 1)[1]
    if tid not in nodes:
        add_node(tid, "table", name, path, line, line, f"Table or view {name} (first literal use)", ["external" if "ACCOUNT_USAGE" in name else "snapshot"], status)


def scan_sql_text(text, base_line, path, owner, lines_hint=None, status="verified"):
    """Literal table names in a text; classify read/write/grants by the keyword before the name."""
    L = LINES[path]
    for m in TBL_RE.finditer(text):
        raw = m.group(0)
        before = text[max(0, m.start() - 140):m.start()]
        before = re.sub(r"(&?\w+|\{[^}]*\})\.(?:(&?\w+|\{[^}]*\})\.)?$", "", before)  # db.schema. prefix
        b = before.rstrip() + " "
        kind = "writes" if WRITE_RE.search(b) else "grants" if GRANT_RE.search(b) else "reads"
        line = base_line + text.count("\n", 0, m.start())
        tail = raw.split(".")[-1]
        if lines_hint:
            lo, hi = lines_hint
            if not (1 <= line <= len(L) and tail in L[line - 1]):
                line = next((i for i in range(lo, hi + 1) if tail in L[i - 1]), min(max(line, lo), hi))
        tid = table_id(raw)
        ensure_table(tid, path, line)
        add_edge(owner, tid, kind, path, line, status)
    for m in re.finditer(r"TBL_ACCESS_\{", text):  # dynamic names such as TBL_ACCESS_{t}
        line = base_line + text.count("\n", 0, m.start())
        ensure_table("table:TBL_ACCESS_*", path, line, "inferred")
        add_edge(owner, "table:TBL_ACCESS_*", "reads", path, line, "inferred")


SQLISH = re.compile(r"\b(SELECT|FROM|JOIN|INSERT|MERGE|UPDATE|DELETE|DROP|CREATE|SHOW|DESCRIBE)\b")


def fstring_text(node, consts):
    out, via = [], False
    for v in node.values:
        if isinstance(v, ast.Constant):
            out.append(str(v.value))
        elif isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name) and v.value.id in consts:
            out.append(consts[v.value.id]); via = True
        else:
            out.append("{" + ast.unparse(v.value) + "}")
    return "".join(out), via


def scan_string_node(ch, p, owner, consts, off=0):
    """ch: Constant str or JoinedStr; off: line offset when the code is embedded in another file."""
    if isinstance(ch, ast.Constant):
        text, via = ch.value, False
    else:
        text, via = fstring_text(ch, consts)
    if (TBL_RE.search(text) or "TBL_ACCESS_{" in text) and SQLISH.search(text):  # messages and notes are not queries
        scan_sql_text(text, ch.lineno + off, p, owner, (ch.lineno + off, ch.end_lineno + off), "inferred" if via else "verified")


def module_consts(tree):
    return {s.targets[0].id: s.value.value for s in tree.body if isinstance(s, ast.Assign) and isinstance(s.targets[0], ast.Name)
            and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str)}


def is_doc_or_const(ch, parent):
    """Docstrings and module-level NAME = "text" bindings are not queries."""
    if isinstance(ch, ast.Expr) and isinstance(ch.value, ast.Constant) and isinstance(ch.value.value, str):
        return True
    return isinstance(parent, ast.Module) and isinstance(ch, ast.Assign) and isinstance(ch.value, ast.Constant) and isinstance(ch.value.value, str)


def scan_strings(node, p, owner, consts, off=0):
    """All string literals below node (f-strings as one text), attributed to one owner."""
    for ch in ast.iter_child_nodes(node):
        if is_doc_or_const(ch, node):
            continue
        if isinstance(ch, ast.JoinedStr):
            scan_string_node(ch, p, owner, consts, off)
            for v in ch.values:
                if isinstance(v, ast.FormattedValue):
                    scan_strings(ast.Module(body=[ast.Expr(value=v.value)], type_ignores=[]), p, owner, consts, off)
        elif isinstance(ch, ast.Constant) and isinstance(ch.value, str):
            scan_string_node(ch, p, owner, consts, off)
        else:
            scan_strings(ch, p, owner, consts, off)


def py_pass2(p, tree, info, pyfiles, allinfo):
    # imports
    alias = {}      # local alias -> py file
    fromimp = {}    # local name -> (py file, original name)
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for al in n.names:
                f = py_module_of(al.name, pyfiles, p)
                if f:
                    alias[al.asname or al.name] = f
                    add_edge(f"file:{p}", f"file:{f}", "imports", p, n.lineno)
        elif isinstance(n, ast.ImportFrom) and n.module:
            f = py_module_of(n.module, pyfiles, p)
            if f:
                add_edge(f"file:{p}", f"file:{f}", "imports", p, n.lineno)
                for al in n.names:
                    fromimp[al.asname or al.name] = (f, al.name)
    top = info["top"]

    def resolve(call):
        f = call.func
        if isinstance(f, ast.Name):
            if f.id in top:
                return top[f.id]
            if f.id in fromimp:
                fi, orig = fromimp[f.id]
                return allinfo[fi]["top"].get(orig)
        elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in alias:
            return allinfo[alias[f.value.id]]["top"].get(f.attr)
        return None

    consts = module_consts(tree)

    def visit(node, owner):
        for ch in ast.iter_child_nodes(node):
            if is_doc_or_const(ch, node):
                continue
            o = owner
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)) and id(ch) in info["owners"]:
                o = info["owners"][id(ch)]
            elif isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)) and owner.startswith("test_case:"):
                o = owner
            if isinstance(ch, ast.Call):
                tgt = resolve(ch)
                if tgt and tgt != o:
                    if o.startswith("test_case:"):
                        if tgt.split(":")[1] != p:
                            add_edge(o, tgt, "illustrates", p, ch.lineno)
                    else:
                        add_edge(o, tgt, "calls", p, ch.lineno)
                if (p == "access.py" and isinstance(ch.func, ast.Name) and ch.func.id == "find" and ch.args
                        and isinstance(ch.args[0], ast.Constant) and isinstance(ch.args[0].value, str)):
                    add_edge(o, f"business_rule:rule_{ch.args[0].value}", "implements", p, ch.lineno)
            if isinstance(ch, ast.Constant) and isinstance(ch.value, str):
                scan_string_node(ch, p, o, consts)
                if o.startswith("test_case:"):  # a query file or notebook the check runs or reads
                    for fm in re.finditer(r"[\w.]+\.(?:sql|ipynb)\b", ch.value):
                        PENDING.append((o, (Path(p).parent / fm.group(0)).as_posix(), p, ch.lineno))
            if isinstance(ch, ast.JoinedStr):
                scan_string_node(ch, p, o, consts)
                for v in ch.values:
                    if isinstance(v, ast.FormattedValue):
                        visit(ast.Module(body=[ast.Expr(value=v.value)], type_ignores=[]), o)
                continue
            visit(ch, o)

    visit(tree, f"file:{p}")


def py_extras(p, tree):
    """access.py: RULES -> business_rule nodes; server.py: PAGES, routes."""
    if p == "access.py":
        sev = {}
        for s in tree.body:
            if isinstance(s, ast.Assign) and isinstance(s.targets[0], ast.Name) and s.targets[0].id == "SEVERITY" and isinstance(s.value, ast.Dict):
                sev = {k.value: (v.value, k.lineno) for k, v in zip(s.value.keys, s.value.values)}
        for s in tree.body:
            if isinstance(s, ast.Assign) and isinstance(s.targets[0], ast.Name) and s.targets[0].id == "RULES" and isinstance(s.value, ast.Dict):
                for k, v in zip(s.value.keys, s.value.values):
                    title, why = (e.value if isinstance(e, ast.Constant) else ast.unparse(e) for e in v.elts)
                    sv = sev.get(k.value, ("unclear", 0))[0]
                    bid = add_node(f"business_rule:rule_{k.value}", "business_rule", f"Rule {k.value}: {title}", p, k.lineno, v.end_lineno,
                                   f"{title}. Why: {why} Severity {sv} (access.py:{sev[k.value][1] if k.value in sev else '?'}).", [f"severity:{sv}", "rule"])
                    add_edge(f"file:{p}", bid, "contains", p, k.lineno)


def server_extras(p, tree, info):
    consts = {}
    for s in tree.body:
        if isinstance(s, ast.Assign) and isinstance(s.targets[0], ast.Name):
            consts[s.targets[0].id] = s
    sid = f"file:{p}"
    ep_ids = {}  # path -> endpoint id

    def endpoint(method, path, line, handler=None, summary=""):
        eid = add_node(f"endpoint:{method} {path}", "endpoint", f"{method} {path}", p, line, line, summary or f"{method} {path}", [method.lower()])
        ep_ids[path] = eid
        add_edge(sid, eid, "exposes", p, line)
        if handler:
            add_edge(eid, handler, "calls", p, line)
        return eid

    routes = {}  # route name -> handler function id
    d = consts["ROUTES"].value
    for k, v in zip(d.keys, d.values):
        routes[k.value] = (info["top"].get(v.id), k.lineno)
    csv = {}
    d = consts["CSV"].value
    for k, v in zip(d.keys, d.values):
        csv[k.value] = (info["top"].get(v.id), k.lineno)
    # decorated nested routes
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            r = route_deco(fn)
            if r:
                method, path = r
                nid = info["owners"].get(id(fn))
                endpoint(method, path, fn.lineno, nid, f"{method} {path} handled by {fn.name}")
    # loops: for n in (...): app.get(f"/api/{n}")(route(n))  /  for n in CSV
    loop_names = None
    csv_loop = False
    for fn in ast.walk(tree):
        if isinstance(fn, ast.For) and isinstance(fn.target, ast.Name):
            src = ast.unparse(fn.body[0]) if fn.body else ""
            if "/api/{n}.csv" in src and isinstance(fn.iter, ast.Name) and fn.iter.id == "CSV":
                csv_loop = fn.lineno
            elif "/api/{n}" in src and isinstance(fn.iter, ast.Tuple):
                loop_names = ([e.value for e in fn.iter.elts], fn.lineno)
    if loop_names:
        names, line = loop_names
        for n in names:
            h, hl = routes.get(n, (None, line))
            endpoint("GET", f"/api/{n}", line, h, f"JSON answer of page handler {n} via serve('{n}') (route table server.py:{hl})")
        missing = set(routes) - set(names)
        if missing:
            print("note: ROUTES keys not in loop tuple:", missing)
    if csv_loop:
        for n, (h, hl) in csv.items():
            endpoint("GET", f"/api/{n}.csv", csv_loop, h, f"CSV download of {n} (route table server.py:{hl})")
    # PAGES -> ui_screen
    pages = consts["PAGES"]
    group = {k.value: v.value for k, v in zip(consts["GROUP"].value.keys, consts["GROUP"].value.values)}
    shared_only = {e.value for e in consts["SHARED_ONLY"].value.elts}
    for k, v in zip(pages.value.keys, pages.value.values):
        uid = add_node(f"ui_screen:{k.value}", "ui_screen", v.value, p, k.lineno, k.lineno,
                       f"Page '{v.value}' (key {k.value}), side-nav group {group.get(k.value, 'unclear')}"
                       f"{'; shared view only' if k.value in shared_only else ''}.",
                       [f"group:{group.get(k.value, 'unclear')}"] + (["shared-only"] if k.value in shared_only else []))
        add_edge(sid, uid, "contains", p, k.lineno)
        ep = ep_ids.get(f"/api/{k.value}")
        if ep:
            add_edge(uid, ep, "calls", p, k.lineno, "inferred")
    return ep_ids


# ---------- TypeScript ----------

TS_DECL = re.compile(r"^export\s+(?:default\s+)?(?:async\s+)?(function\*?|const|let|class|interface|type|enum)\s+(\w+)")
TS_START = re.compile(r"^(export|function|const|let|var|class|interface|type|enum|async|import|declare)\b")


def ts_symbols(p):
    lines = LINES[p]
    starts = [i for i, l in enumerate(lines) if TS_START.match(l)]
    syms = []
    for i in starts:
        m = TS_DECL.match(lines[i])
        if not m:
            continue
        nxt = next((j for j in starts if j > i), len(lines))
        e = nxt - 1
        while e > i and (not lines[e].strip() or re.match(r"^\s*(//|/\*|\*)", lines[e])):
            e -= 1
        kind, name = m.groups()
        decl = " ".join(lines[i:i + 3])
        isfun = kind.startswith("function") or (kind in ("const", "let") and ("=>" in decl or "forwardRef" in decl or "memo(" in decl))
        if kind in ("interface", "type", "enum"):
            t = "type"
        elif kind == "class":
            t = "class"
        elif isfun and name[0].isupper() and p.endswith(".tsx"):
            t = "component"
        elif isfun:
            t = "function"
        else:
            t = "const"
        syms.append((t, name, i + 1, e + 1, lines[i].strip()[:160]))
    return syms


def ts_resolve(p, spec, tsfiles):
    base = (Path(p).parent / spec).as_posix()
    parts = []
    for seg in base.split("/"):
        if seg == "..":
            parts.pop()
        elif seg != ".":
            parts.append(seg)
    b = "/".join(parts)
    for cand in (b, b + ".ts", b + ".tsx", b + "/index.ts", b + "/index.tsx"):
        if cand in tsfiles:
            return cand
    return None


def skip_generic(s, i):
    if s[i] != "<":
        return i
    d = 0
    while i < len(s):
        if s[i] == "<":
            d += 1
        elif s[i] == ">" and s[i - 1] != "=":
            d -= 1
            if d == 0:
                return i + 1
        i += 1
    return i


def first_arg(s, i):
    """s[i] == '('; text of the first argument."""
    d, j, q = 0, i, None
    while j < len(s):
        c = s[j]
        if q:
            if c == "\\":
                j += 1
            elif c == q:
                q = None
        elif c in "\"'`":
            q = c
        elif c in "([{":
            d += 1
        elif c in ")]}":
            d -= 1
            if d == 0:
                return s[i + 1:j]
        elif c == "," and d == 1:
            return s[i + 1:j]
        j += 1
    return s[i + 1:]


CALL_RE = re.compile(r"(?<![.\w])(useApi|get|post|download)\s*(?=[<(])")


def ts_pass(p, tsfiles, ep_ids, symsmap):
    src = "\n".join(LINES[p])
    for m in re.finditer(r"""(?:^|\n)\s*(?:import|export)\b[^;]*?\bfrom\s+["'](\.[^"']*)["']""", src):
        t = ts_resolve(p, m.group(1), tsfiles)
        line = src.count("\n", 0, m.end(1)) + 1
        if t:
            add_edge(f"file:{p}", f"file:{t}", "imports", p, line)
    for m in re.finditer(r"""import\s+["'](\.[^"']*)["']""", src):  # side-effect css
        t = ts_resolve(p, m.group(1), tsfiles)
        if t:
            add_edge(f"file:{p}", f"file:{t}", "imports", p, src.count("\n", 0, m.start()) + 1)
    uses_dl = re.search(r"import\s*\{[^}]*\bdownload\b[^}]*\}\s*from\s*[\"'][./]*api/client[\"']", src)
    for m in CALL_RE.finditer(src):
        fn = m.group(1)
        if fn == "download" and not uses_dl:
            continue
        i = skip_generic(src, m.end())
        while i < len(src) and src[i].isspace():
            i += 1
        if i >= len(src) or src[i] != "(":
            continue
        arg = first_arg(src, i)
        line = src.count("\n", 0, m.start()) + 1
        found = []
        for sm in re.finditer(r"""(["'`])([^"'`$]*)""", arg):
            s = sm.group(2).split("?")[0].strip("/")
            if fn == "download":
                if s.endswith(".csv") and f"/api/{s}" in ep_ids:
                    found.append(s)
            elif s and re.fullmatch(r"[a-z/]+", s) and f"/api/{s}" in ep_ids:
                found.append(s)
        owner = next((sid for sid, a, b in symsmap.get(p, []) if a <= line <= b), f"file:{p}")
        for s in found:
            add_edge(owner, ep_ids[f"/api/{s}"], "calls", p, line)


# ---------- SQL ----------

NAME_RE = re.compile(r"^--\s*name:\s*(\w+)\s*(.*)$")
CREATE_RE = re.compile(r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(TABLE|VIEW|FUNCTION|PROCEDURE|STAGE|STREAMLIT|SCHEMA|DATABASE|WAREHOUSE|ROLE)\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w&.\"]+)", re.I)


def sql_file(p):
    lines = LINES[p]
    marks = [(i, NAME_RE.match(l)) for i, l in enumerate(lines) if NAME_RE.match(l)]
    fid = f"file:{p}"
    for k, (i, m) in enumerate(marks):
        end = (marks[k + 1][0] if k + 1 < len(marks) else len(lines)) - 1
        while end > i and not lines[end].strip():
            end -= 1
        name, flags = m.group(1), m.group(2)
        tags = ["sql", *re.findall(r"\((may fail|expect \d+)\)", flags)]
        body = lines[i + 1:end + 1]
        created = None
        for off, l in enumerate(body):
            c = CREATE_RE.match(l)
            if c:
                kind, ident = c.group(1).upper(), c.group(2).strip('"')
                ident = ident.split(".")[-1]
                typ = {"TABLE": "table", "VIEW": "table", "FUNCTION": "function", "PROCEDURE": "function"}.get(kind, "infra_object")
                oid = f"{'table' if typ == 'table' else 'function' if typ == 'function' else 'infra'}:{ident.upper()}"
                if typ == "function":
                    oid = f"function:sql:{ident.upper()}"
                # object range: from the CREATE line to the statement end (inferred end)
                add_node(oid, typ, ident.upper(), p, i + 2 + off, end + 1, f"{kind} {ident.upper()} created in task {name} ({p}:{i + 1}-{end + 1})",
                         [kind.lower(), "sql"] + (["snapshot"] if ident.upper().startswith("TBL_ACCESS_") else []))
                if created is None:
                    created = oid
                break
        tid = add_node(f"task:{p}:{name}", "task", name, p, i + 1, end + 1,
                       f"SQL statement '{name}' {' '.join(tags[1:])}".strip() + (f"; creates {created.split(':', 1)[1] if created else ''}" if created else ""), tags)
        add_edge(fid, tid, "contains", p, i + 1)
        if created:
            add_edge(tid, created, "writes", p, i + 1 + 1)
            add_edge(fid, created, "contains", p, i + 2)
        owner = created if (created and created.startswith("function:")) else tid
        # literal table names in the statement body
        text = "\n".join(body)
        dd = [k for k, l in enumerate(body) if l.strip() in ("$$", "$$;") or l.rstrip().endswith("AS $$")]
        pyb = None
        if created and created.startswith("function:") and "LANGUAGE PYTHON" in text.upper() and len(dd) >= 2:
            try:
                pyb = ast.parse("\n".join(body[dd[0] + 1:dd[1]]))
                off = i + 1 + dd[0] + 1  # file line of the body's line 1, minus 1
            except SyntaxError:
                pyb = None
        if pyb:
            nodes[created]["tags"].append("python-body")
            scan_strings(pyb, p, owner, module_consts(pyb), off)
        else:
            scan_sql_text(text, i + 2, p, owner, (i + 2, end + 1))
    if not marks:
        plain_sql(p)


def plain_sql(p):
    """No -- name: markers: each CREATE FUNCTION up to its $$; is a function node; else the query (first SET, WITH
    or SELECT line to the end) is one task node; table names are scanned inside them."""
    lines = LINES[p]
    fid = f"file:{p}"
    fns = [(i, c) for i, l in enumerate(lines) if (c := CREATE_RE.match(l)) and c.group(1).upper() == "FUNCTION"]
    for i, c in fns:
        end = next((j for j in range(i + 1, len(lines)) if lines[j].strip() == "$$;"), len(lines) - 1)
        name = c.group(2).split(".")[-1].upper()
        note = lines[i - 1].lstrip("- ").strip() if i and lines[i - 1].startswith("--") else ""
        oid = add_node(f"function:sql:{name}", "function", name, p, i + 1, end + 1,
                       f"Table function {name} ({p}:{i + 1}-{end + 1}). {note}".strip(), ["function", "sql", "udtf"])
        add_edge(fid, oid, "contains", p, i + 1)
        scan_sql_text("\n".join(lines[i:end + 1]), i + 1, p, oid, (i + 1, end + 1))
    if fns:
        return
    start = next((i for i, l in enumerate(lines) if re.match(r"(SET|WITH|SELECT)\b", l)), None)
    if start is None:
        scan_sql_text("\n".join(lines), 1, p, fid, (1, len(lines)))
        return
    head = lines[0].lstrip("- ").strip() if lines[0].startswith("--") else ""
    sets = re.findall(r"^SET (\w+)", "\n".join(lines), re.M)
    tid = add_node(f"task:{p}:{Path(p).stem}", "task", Path(p).stem, p, start + 1, len(lines),
                   f"Plain query: {head} Inputs: {', '.join(sets) or 'none'}.", ["sql", "query"])
    add_edge(fid, tid, "contains", p, start + 1)
    scan_sql_text("\n".join(lines[start:]), start + 1, p, tid, (start + 1, len(lines)))


# ---------- notebooks ----------

def notebook(p, pyfiles):
    """One task node per code cell (json indent=1: a cell runs from '  {' to '  }'). SQL cells: table names and AQ_
    function calls; any cell: repo imports and query file names (depends_on)."""
    lines = LINES[p]
    nb = json.loads("\n".join(lines))
    cells = nb["cells"]
    kernel = (nb.get("metadata", {}).get("kernelspec") or {}).get("language")
    starts = [i for i, l in enumerate(lines) if l == "  {"]
    ends = [i for i, l in enumerate(lines) if l in ("  }", "  },")]
    fid = f"file:{p}"
    nodes[fid]["tags"].append("notebook")
    for k, (c, a, b) in enumerate(zip(cells, starts, ends)):
        if c["cell_type"] != "code":
            continue
        md = c.get("metadata") or {}
        name = md.get("name") or c.get("id") or f"cell_{k}"
        lang = md.get("language") or kernel or "sql"  # no language: a Snowflake Notebook SQL cell
        first = next((s.strip() for s in c["source"] if s.strip() and not s.lstrip().startswith(("--", "#"))), "")[:120]
        tid = add_node(f"task:{p}:{name}", "task", name, p, a + 1, b + 1, f"Notebook {lang} cell '{name}': {first}",
                       ["notebook", lang])
        add_edge(fid, tid, "contains", p, a + 1)
        block = "\n".join(lines[a:b + 1])
        at = lambda m: a + 1 + block.count("\n", 0, m.start())
        if lang == "sql":
            scan_sql_text(block, a + 1, p, tid, (a + 1, b + 1))
            for m in re.finditer(r"\.(AQ_\w+)\(", block):
                if f"function:sql:{m.group(1)}" in nodes:
                    add_edge(tid, f"function:sql:{m.group(1)}", "calls", p, at(m))
        for m in re.finditer(r"\b(?:\d_\w+|functions)\.sql\b", block):
            f = (Path(p).parent / m.group(0)).as_posix()
            if f"file:{f}" in nodes:
                add_edge(tid, f"file:{f}", "depends_on", p, at(m))


# ---------- main ----------

def validate():
    bad = 0
    ids = set(nodes)
    for e in list(edges.values()):
        for end in ("from", "to"):
            if e[end] not in ids:
                t = e[end]
                add_node(t, "unknown", t.split(":", 1)[-1], e["evidence"].rsplit(":", 1)[0], int(e["evidence"].rsplit(":", 1)[1]), int(e["evidence"].rsplit(":", 1)[1]),
                         "Stub node created because an edge points here; target not found as a node.", ["stub"], "unclear")
                ids.add(t)
                print("stub created:", t)
    for n in nodes.values():
        if n["path"] == ".":
            continue
        L = LINES.get(n["path"])
        if L is None:
            if not (ROOT / n["path"]).exists():
                print("BAD path", n["id"], n["path"]); bad += 1
            continue
        if not (1 <= n["line"] <= max(len(L), 1) and n["line"] <= n["line_end"] <= max(len(L), 1)):
            print("BAD range", n["id"], n["line"], n["line_end"], len(L)); bad += 1
    for e in edges.values():
        p, l = e["evidence"].rsplit(":", 1)
        L = LINES.get(p)
        if L is None or not (1 <= int(l) <= max(len(L), 1)):
            print("BAD evidence", e); bad += 1
    return bad


def main():
    files = tracked()
    structure(files)
    pyfiles = {f for f in files if f.endswith(".py")}
    trees = {f: ast.parse("\n".join(LINES[f])) for f in pyfiles}
    allinfo = {f: py_pass1(f, trees[f]) for f in sorted(pyfiles)}
    for f in sorted(pyfiles):
        py_extras(f, trees[f])
    ep_ids = server_extras("server.py", trees["server.py"], allinfo["server.py"])
    for f in sorted(pyfiles):
        py_pass2(f, trees[f], allinfo[f], pyfiles, allinfo)
    # TypeScript
    tsfiles = {f for f in files if re.search(r"\.(ts|tsx)$", f) and f.startswith("web/")}
    symsmap = {}
    for f in sorted(tsfiles):
        symsmap[f] = []
        for t, name, a, b, sig in ts_symbols(f):
            nid = add_node(f"{t}:{f}:{name}", t, name, f, a, b, f"{sig} (lines {a}-{b}, end line approximate)", [f"lines:{a}-{b}", "range-heuristic"])
            add_edge(f"file:{f}", nid, "contains", f, a)
            symsmap[f].append((nid, a, b))
    for f in sorted(tsfiles):
        ts_pass(f, tsfiles, ep_ids, symsmap)
    # App.tsx VIEWS: screen key -> component
    app = LINES["web/src/App.tsx"]
    start = next(i for i, l in enumerate(app) if l.startswith("const VIEWS"))
    for i in range(start + 1, len(app)):
        if app[i].startswith("}"):
            break
        for k, comp in re.findall(r"(\w+):\s*(\w+)", app[i]):
            cid = next((n for n in (f"component:web/src/pages/{x}.tsx:{comp}" for x in
                        ("Access", "Changes", "Check", "Compare", "Flow", "Map", "Home", "Object", "Request", "Review", "Role", "Rules", "See", "Sensitive", "Usage", "Whatif", "User")) if n in nodes), None)
            cid = cid or next((n for n in nodes if n.endswith(f":{comp}") and n.startswith(("component:", "function:")) and "web/" in n), None)
            if cid and f"ui_screen:{k}" in nodes:
                add_edge(cid, f"ui_screen:{k}", "implements", "web/src/App.tsx", i + 1)
    # SQL
    for f in sorted(files):
        if f.endswith(".sql"):
            sql_file(f)
    for f in sorted(files):
        if f.endswith(".ipynb"):
            notebook(f, pyfiles)
    for o, f, p, line in PENDING:
        task = f"task:{f}:{Path(f).stem}"
        if task in nodes or f"file:{f}" in nodes:
            add_edge(o, task if task in nodes else f"file:{f}", "illustrates", p, line)
    bad = validate()
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "structure.nodes.jsonl", "w", encoding="utf-8") as fh:
        for n in nodes.values():
            fh.write(json.dumps(n, ensure_ascii=False) + "\n")
    with open(OUT / "structure.edges.jsonl", "w", encoding="utf-8") as fh:
        for e in edges.values():
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    print("nodes", len(nodes), "edges", len(edges), "problems", bad)
    print("nodes by type:", dict(Counter(n["type"] for n in nodes.values())))
    print("edges by type:", dict(Counter(e["type"] for e in edges.values())))
    print("status:", dict(Counter(n["status"] for n in nodes.values())), dict(Counter(e["status"] for e in edges.values())))


if __name__ == "__main__":
    main()
