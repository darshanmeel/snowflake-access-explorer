"""Write meta.json (hashes of tracked and untracked-not-ignored files, counts) after merge.py. Usage: meta.py [commit] [date]"""
import json, os, sys, hashlib, subprocess, collections
G = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); R = os.path.dirname(G)
commit = sys.argv[1] if len(sys.argv) > 1 else subprocess.run(['git', '-C', R, 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
date = sys.argv[2] if len(sys.argv) > 2 else __import__('datetime').date.today().isoformat()
files = [f for f in subprocess.run(['git', '-C', R, 'ls-files', '--cached', '--others', '--exclude-standard'], capture_output=True, text=True).stdout.split('\n') if f and os.path.isfile(os.path.join(R, f)) and not f.startswith('snowflake-access-explorer-knowledge-graph/')]
load = lambda p: [json.loads(l) for l in open(os.path.join(G, p), encoding='utf8') if l.strip()]
nodes, edges = load('graph/nodes.jsonl'), load('graph/edges.jsonl')
old = json.load(open(os.path.join(G, 'meta.json'), encoding='utf8')) if os.path.isfile(os.path.join(G, 'meta.json')) else {}
meta = {**old, 'built_at': date, 'commit': commit,  # keeps update.py's keys (pending, scripts_hash, ...)
        'file_hashes': {f: hashlib.sha256(open(os.path.join(R, f), 'rb').read()).hexdigest() for f in files},
        'generated_by': {'flows/': 'model', 'logic/': 'model', 'processes/': 'model', 'documents/': 'model', 'modules/': 'model',
                         'data/model.json': 'model', 'graph/parts/structure.*': 'script'},
        'counts': {'nodes': len(nodes), 'edges': len(edges),
                   'node_types': dict(collections.Counter(n['type'] for n in nodes)),
                   'edge_types': dict(collections.Counter(e['type'] for e in edges))}}
json.dump(meta, open(os.path.join(G, 'meta.json'), 'w'), indent=1)
print('meta.json:', len(files), 'files,', len(nodes), 'nodes,', len(edges), 'edges')
