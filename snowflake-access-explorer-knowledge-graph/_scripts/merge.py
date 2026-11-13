"""Merge <out>/graph/parts/structure.* (extract.py) and the hand-written _scripts/parts/*.jsonl into <out>/graph/nodes.jsonl +
edges.jsonl. Usage: merge.py [<repo> <out>]. Checks: validate.py."""
import json, glob, os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
R = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(HERE))
G = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(HERE)
KG = 'snowflake-access-explorer-knowledge-graph'


def load(p):
    return [json.loads(l) for l in open(p, encoding='utf8') if l.strip()]


def rich(n):
    return (n.get('status') == 'verified', len(n.get('summary') or ''), bool(n.get('line_end')))


tracked = [f for f in subprocess.run(['git', '-C', R, 'ls-files', '--cached', '--others', '--exclude-standard'], capture_output=True, text=True).stdout.split('\n') if f and os.path.isfile(os.path.join(R, f)) and not f.startswith('snowflake-access-explorer-knowledge-graph/')]


nodes, edges = {}, {}
order = ['structure'] + sorted(os.path.basename(p).split('.')[0] for p in glob.glob(HERE + '/parts/*.nodes.jsonl'))
part = lambda k, x: f'{G}/graph/parts/{k}.{x}.jsonl' if k == 'structure' else f'{HERE}/parts/{k}.{x}.jsonl'  # noqa: E731
for k in order:
    for n in load(part(k, 'nodes')):
        o = nodes.get(n['id'])
        if o is None:
            nodes[n['id']] = n
        else:
            keep, other = (n, o) if rich(n) > rich(o) else (o, n)
            for f in ('path', 'line', 'line_end'):
                if keep.get(f) is None and other.get(f) is not None:
                    keep[f] = other[f]
            keep['tags'] = sorted(set(keep.get('tags') or []) | set(other.get('tags') or []))
            nodes[n['id']] = keep

alias = {}


def norm(i):
    if i in nodes:
        return i
    if i in alias:
        return alias[i]
    t, _, rest = i.partition(':')
    c = []
    if t in ('module', 'doc', 'document', 'script'):
        c = ['file:' + rest, 'module:' + rest, 'document:' + rest, 'doc:' + rest, 'script:' + rest]
    if t == 'file':
        c = ['script:' + rest, 'module:' + rest]
    if t == 'table':
        c = ['table:' + rest.upper()]
    for x in c:
        if x in nodes:
            alias[i] = x
            return x
    return i


for k in order:
    for e in load(part(k, 'edges')):
        e['from'], e['to'] = norm(e['from']), norm(e['to'])
        key = (e['from'], e['to'], e['type'], e.get('evidence'))
        if key not in edges or e.get('status') == 'verified':
            edges[key] = e

def fix_ev(ev):
    ev = (ev or '').split(';')[0].strip()
    m = re.match(r'^(.+?):(\d+(?:-\d+)?)(?:,.*)?$', ev)
    if m:
        return f'{m.group(1)}:{m.group(2)}'
    if os.path.isfile(os.path.join(R, KG, ev)):
        return f'{KG}/{ev}:1'
    return ev


for e in edges.values():
    if e.get('evidence'):
        if fix_ev(e['evidence']) != e['evidence']:
            e['evidence_orig'] = e['evidence']
        e['evidence'] = fix_ev(e['evidence'])
# non-text tracked files (images, fonts, built bundles) become file nodes so every tracked file is mapped
have = {n.get('path') for n in nodes.values()}
for f in tracked:
    if f not in have:
        nodes['file:' + f] = {'id': 'file:' + f, 'type': 'file', 'name': os.path.basename(f), 'path': f, 'line': None, 'line_end': None,
                              'summary': 'tracked asset / build output / lock file, not parsed', 'tags': ['asset'], 'status': 'verified'}
stubs = set()
for e in edges.values():
    for x in (e['from'], e['to']):
        if x not in nodes:
            t, _, rest = x.partition(':')
            nodes[x] = {'id': x, 'type': t, 'name': rest, 'path': None, 'line': None, 'line_end': None,
                        'summary': 'stub: referenced by an edge but not defined in any part', 'tags': ['stub'], 'status': 'unclear'}
            stubs.add(x)
ET = set('contains imports calls reads writes depends_on triggers exposes configures deploys grants implements documents part_of illustrates fk derived_from'.split())
with open(G + '/graph/nodes.jsonl', 'w', encoding='utf8') as f:
    for n in sorted(nodes.values(), key=lambda n: n['id']):
        f.write(json.dumps(n, ensure_ascii=False) + '\n')
with open(G + '/graph/edges.jsonl', 'w', encoding='utf8') as f:
    for e in sorted(edges.values(), key=lambda e: (e['from'], e['to'], e['type'], e.get('evidence') or '')):
        f.write(json.dumps(e, ensure_ascii=False) + '\n')
print('merged:', len(nodes), 'nodes,', len(edges), 'edges,', len(stubs), 'stubs')
