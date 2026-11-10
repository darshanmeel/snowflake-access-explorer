# Knowledge graph README

Markdown pages plus a JSON-lines graph of the access explorer repo; every fact cites `path:line`. Start at `index.md`.

## Use

- Read `index.md`, then the page for your question (flows / logic / modules / data / processes / documents).
- Query the graph: `graph/nodes.jsonl` (`id,type,name,path,line,line_end,summary,tags,status`) and `graph/edges.jsonl` (`from,to,type,evidence,status`). Open `evidence` to check any claim.
- `status`: `verified` (opened and checked), `inferred`, `unclear`.

## Rebuild

1. `.venv\Scripts\python snowflake-access-explorer-knowledge-graph\_scripts\extract.py` writes `graph/parts/structure.*` (script facts: Python, TypeScript, SQL `-- name:` statements, plain query files and `CREATE FUNCTION` blocks, notebook code cells).
2. `graph/parts/{data,logic,flows,modules,processes,access_queries}.*` and the markdown pages are model-written; edit them by hand or regenerate them with an agent.
3. `.venv\Scripts\python snowflake-access-explorer-knowledge-graph\_scripts\merge.py` merges parts into `graph/nodes.jsonl` / `edges.jsonl`, normalises ids, checks every path and line, spot-checks 20 evidence lines, scans for secrets; exit code 1 on any problem.
4. `.venv\Scripts\python snowflake-access-explorer-knowledge-graph\_scripts\meta.py <commit> <date>` writes `meta.json` (sha256 of each tracked file, counts). Both merge.py and meta.py skip listed files that are deleted on disk (unstaged deletes).

Stats (from `meta.json`): 1787 nodes, 5166 edges, 185 files mapped (tracked plus untracked, not ignored, that exist on disk); counts per type are in `meta.json`.

Last build: 2026-11-10, commit fe263bc plus the uncommitted fixes of the 2026-11-10 review (`reviews/review-2026-11-10-2027.html`). Files whose sha256 in `meta.json` differs from the repo are stale: update the pages that cite them.

## Notes

- The folder is git-ignored by its own `.gitignore` (`*`); the repo `.gitignore` is untouched.
- No credentials, account names or company names are stored (merge.py scans for them).
