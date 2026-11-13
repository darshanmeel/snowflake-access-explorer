"""Checks a built graph against the repo: every tracked file mapped, every node path and edge path:line real, no
dangling edges, known edge types, no secret-looking text in the graph folder. Usage: validate.py [<repo> <graph>].
Prints one coverage line (problems listed under it); exit 1 when something is wrong."""
import json, os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
R = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(HERE))
G = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(HERE)
KG = 'snowflake-access-explorer-knowledge-graph'
ET = set('contains imports calls reads writes depends_on triggers exposes configures deploys grants implements documents part_of illustrates fk derived_from'.split())
SECRET = re.compile(r'(password\s*[:=]\s*[\'"]?[^\s\'"`|)]{4,}|BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{20,}|[a-z0-9-]+\.snowflakecomputing\.com|xox[bp]-|ghp_[A-Za-z0-9]{20,})', re.I)

load = lambda p: [json.loads(x) for x in open(os.path.join(G, p), encoding='utf8') if x.strip()]  # noqa: E731
nodes, edges = {n['id']: n for n in load('graph/nodes.jsonl')}, load('graph/edges.jsonl')
tracked = [f for f in subprocess.run(['git', '-C', R, 'ls-files', '--cached', '--others', '--exclude-standard'], capture_output=True,
                                     text=True).stdout.split('\n') if f and os.path.isfile(os.path.join(R, f)) and not f.startswith(KG + '/')]
size = {}


def nlines(p):
    if p not in size:
        fp = os.path.join(R, p)
        size[p] = len(open(fp, encoding='utf8', errors='replace').read().split('\n')) if os.path.isfile(fp) else None
    return size[p]


bad = []
for n in nodes.values():
    p = n.get('path')
    if 'stub' in (n.get('tags') or []) or not p:
        continue
    ln = nlines(p)
    if ln is None:
        if not os.path.isdir(os.path.join(R, p)):
            bad.append(f"node {n['id']}: path missing {p}")
    elif (n.get('line') is not None and not 1 <= n['line'] <= ln) or (isinstance(n.get('line_end'), int) and n['line_end'] > ln):
        bad.append(f"node {n['id']}: lines {n.get('line')}-{n.get('line_end')} outside {p} ({ln})")
for e in edges:
    w = f"edge {e['from']} -> {e['to']} {e['type']}"
    if e['type'] not in ET:
        bad.append(w + ': unknown type')
    if e['from'] not in nodes or e['to'] not in nodes:
        bad.append('dangling ' + w)
    m = re.match(r'^(.+?):(\d+)(?:-(\d+))?$', (e.get('evidence') or '').strip())
    if not m:
        bad.append(f"{w}: no path:line evidence")
        continue
    ln, a, b = nlines(m.group(1)), int(m.group(2)), int(m.group(3) or m.group(2))
    if ln is None or not 1 <= a <= b <= ln:
        bad.append(f"{w}: evidence {e['evidence']} outside the file")
hits = []
for root, _, fs in os.walk(G):
    for fn in fs:
        if fn.endswith(('.py', '.pyc')):
            continue
        for i, x in enumerate(open(os.path.join(root, fn), encoding='utf8', errors='replace'), 1):
            if SECRET.search(x):
                hits.append(f'{os.path.relpath(os.path.join(root, fn), G)}:{i}')
mapped = {n.get('path') for n in nodes.values()}
unm = [f for f in tracked if f not in mapped]
stubs = sum('stub' in (n.get('tags') or []) for n in nodes.values())
print(f"coverage: {len(tracked) - len(unm)}/{len(tracked)} files mapped · {len(nodes)} nodes ({stubs} stubs) · {len(edges)} edges · "
      f"{len(bad)} problems · {len(hits)} secret hits")
for x in (unm[:10] and [f'unmapped: {", ".join(unm[:10])}']) + bad[:20] + hits[:10]:
    print('  ' + x)
sys.exit(1 if bad or hits else 0)
