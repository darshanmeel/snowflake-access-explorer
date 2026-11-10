"""Merge graph/parts/*.jsonl into graph/nodes.jsonl + graph/edges.jsonl and validate."""
import json, glob, os, re, random, subprocess, collections, sys
G = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = os.path.dirname(G)


def load(p):
    return [json.loads(l) for l in open(p, encoding='utf8') if l.strip()]


def rich(n):
    return (n.get('status') == 'verified', len(n.get('summary') or ''), bool(n.get('line_end')))


tracked = [f for f in subprocess.run(['git', '-C', R, 'ls-files', '--cached', '--others', '--exclude-standard'], capture_output=True, text=True).stdout.split('\n') if f and os.path.isfile(os.path.join(R, f)) and not f.startswith('snowflake-access-explorer-knowledge-graph/')]
_lines = {}


def nlines(p):
    if p not in _lines:
        fp = os.path.join(R, p)
        _lines[p] = len(open(fp, encoding='utf8', errors='replace').read().split('\n')) if os.path.isfile(fp) else None
    return _lines[p]


nodes, edges = {}, {}
order = ['structure'] + sorted(os.path.basename(p).split('.')[0] for p in glob.glob(G + '/graph/parts/*.nodes.jsonl') if 'structure' not in p)
for k in order:
    for n in load(f'{G}/graph/parts/{k}.nodes.jsonl'):
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
    for e in load(f'{G}/graph/parts/{k}.edges.jsonl'):
        e['from'], e['to'] = norm(e['from']), norm(e['to'])
        key = (e['from'], e['to'], e['type'], e.get('evidence'))
        if key not in edges or e.get('status') == 'verified':
            edges[key] = e

KG = os.path.basename(G)


def fix_ev(ev):
    ev = (ev or '').split(';')[0].strip()
    m = re.match(r'^(.+?):(\d+(?:-\d+)?)(?:,.*)?$', ev)
    if m:
        return f'{m.group(1)}:{m.group(2)}'
    if os.path.isfile(os.path.join(G, ev)):
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

bad = []


def chk_ev(ev, who):
    m = re.match(r'^(.+?):(\d+)(?:-(\d+))?$', (ev or '').strip())
    if not m:
        bad.append(f'{who}: bad/missing evidence {ev!r}')
        return
    p, a, b = m.group(1), int(m.group(2)), int(m.group(3) or m.group(2))
    n = nlines(p)
    if n is None:
        bad.append(f'{who}: file missing {p}')
    elif a < 1 or b > n or a > b:
        bad.append(f'{who}: line out of range {ev} (len {n})')


noev = []
for n in nodes.values():
    if n['id'] in stubs:
        continue
    p = n.get('path')
    if not p:
        noev.append(n['id'])
        continue
    ln = nlines(p)
    if ln is None:
        if not os.path.isdir(os.path.join(R, p)):
            bad.append(f"node {n['id']}: path missing {p}")
        continue
    if n.get('line') is not None and not (1 <= n['line'] <= ln):
        bad.append(f"node {n['id']}: line {n['line']} > {ln}")
    if isinstance(n.get('line_end'), int) and n['line_end'] > ln:
        bad.append(f"node {n['id']}: line_end {n['line_end']} > {ln}")
for e in edges.values():
    w = f"edge {e['from']}->{e['to']} {e['type']}"
    if e['type'] not in ET:
        bad.append(w + ': bad type')
    if e['from'] not in nodes or e['to'] not in nodes:
        bad.append('dangling ' + w)
    chk_ev(e.get('evidence'), w)

random.seed(7)
print('--- spot check (20) ---')
for e in random.sample(list(edges.values()), 20):
    p, _, rng = (e.get('evidence') or ':0').rpartition(':')
    try:
        txt = open(os.path.join(R, p), encoding='utf8', errors='replace').read().split('\n')[int(rng.split('-')[0]) - 1].strip()[:100]
    except Exception as x:
        txt = str(x)
    print(f"{e['type']} {e['from'].split(':',1)[1][:38]} -> {e['to'].split(':',1)[1][:38]} | {e['evidence']} | {txt}")

pat = re.compile(r'(password\s*[:=]\s*[\'"]?[^\s\'"`|)]{4,}|BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{20,}|[a-z0-9-]+\.snowflakecomputing\.com|xox[bp]-|ghp_[A-Za-z0-9]{20,})', re.I)
hits = []
for root, _, fs in os.walk(G):
    for fn in fs:
        if fn.endswith('.pyc') or fn == 'merge.py':
            continue
        p = os.path.join(root, fn)
        for i, l in enumerate(open(p, encoding='utf8', errors='replace'), 1):
            m = pat.search(l)
            if m:
                hits.append(f'{os.path.relpath(p, G)}:{i}: {m.group(0)[:60]}')

mapped = {n.get('path') for n in nodes.values() if n.get('path')}
unm = [f for f in tracked if f not in mapped]
nt = collections.Counter(n['type'] for n in nodes.values())
et = collections.Counter(e['type'] for e in edges.values())
print('--- coverage ---')
print(f'tracked files mapped: {len(tracked)-len(unm)}/{len(tracked)}; unmapped: {unm[:40]}')
print('nodes', len(nodes), 'stubs', len(stubs), 'edges', len(edges), 'aliases', len(alias))
print('nodes without path:', len(noev), noev[:15])
print('node types', dict(nt))
print('edge types', dict(et))
print('stubs:', sorted(stubs)[:40])
print('--- problems:', len(bad))
print('\n'.join(bad[:40]))
print('--- secret hits:', len(hits))
print('\n'.join(hits[:20]))
json.dump({'tracked': tracked, 'unmapped': unm, 'noev': len(noev), 'stubs': len(stubs), 'ntypes': nt, 'etypes': et,
           'nodes': len(nodes), 'edges': len(edges), 'problems': len(bad), 'secrets': len(hits)}, open(G + '/graph/.stats.json', 'w'))
sys.exit(1 if bad or hits else 0)
