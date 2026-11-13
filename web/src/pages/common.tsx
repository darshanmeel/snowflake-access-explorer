// Pieces shared by the pages: pickers, load/error frame, graph card, findings, data views, usage.
import { useEffect, useState, type ReactNode } from "react";
import { clearCache, get, useApi, type ApiFail, type State } from "../api/client";
import type { Banner as B, DataView, ListItem, Finding, Graph as G, Refs, StateWhy, UsageCard } from "../api/types";
import { Banner, Card, Combo, copyText, DataTable, FindingList, Graph, PathText, type Column } from "../components";
import { useApp, useOpen } from "../ctx";
import { changeOfPath, WhatIfButton } from "./Whatif";

export function col<R>(key: string, label: string, get: Column<R>["get"], more: Partial<Column<R>> = {}): Column<R> {
  return { key, label, get, ...more };
}

/** Loading / error frame around a page's answer. */
export function Load<T>({ s, children }: { s: State<T>; children: (d: T) => ReactNode }) {
  if (s.error) return <ErrorBox e={s.error} />;
  if (!s.data) return <p className="ae-muted">Loading…</p>;
  return <div className={s.loading ? "ae-fade" : undefined}>{children(s.data)}</div>;
}

export function ErrorBox({ e }: { e: ApiFail }) {
  const c = useApp();
  if (e.detail === "mine_not_loaded") return <Banner tone="warn" title="My access is not loaded">Use "Load my access" in the top bar.</Banner>;
  if (e.detail === "shared_unreadable")
    return (
      <Banner tone="bad" title="The shared snapshot cannot be read" lines={[e.message]}>
        {c?.meta?.mine_available !== false && <p>You can still look at your own access: switch to "My access" in the top bar.</p>}
        <button className="ae-btn" onClick={clearCache}>Try again</button>
      </Banner>
    );
  return <Banner tone={e.status === 404 ? "warn" : "bad"} title={e.status === 404 ? "Not found" : "Something went wrong"} lines={[e.message]} />;
}

export function Banners({ list }: { list: B[] }) {
  const c = useApp();
  return (
    <>
      {list.map((b, i) => (
        <Banner key={i} tone={b.tone} title={b.title} lines={b.lines}>
          {b.links?.map((l) => (
            <button key={l.label} className="ae-link" onClick={() => c.nav(l.page, l.params)}>{l.label}</button>
          ))}
        </Banner>
      ))}
    </>
  );
}

const KIND_SHORT: Record<string, string> = { user: "user", functional: "functional", technical: "technical", group: "group role",
  database_role: "database role", admin: "admin role", object: "object" };

/** Pick one value from a long list: the server searches as you type (what= users / roles / objects or a comma list,
 * 50 hits a keystroke, never the whole account), or `options` when the list is already small (holders on What if).
 * onPick gets the item too: its kind tells a user from a role of the same name. */
export function Pick({ label, value, what, params, options, onPick, width = 240, user }: {
  label: string; value: string; what?: string; params?: Record<string, string | undefined>; options?: string[];
  onPick: (v: string, item: ListItem) => void; width?: number;
  user?: boolean; // the shown value is a user (true) or a role: users and roles share names, so the same id can be a new pick
}) {
  const c = useApp();
  const search = (q: string): Promise<ListItem[]> => options
    ? Promise.resolve(options.filter((o) => o.toLowerCase().includes(q.toLowerCase())).slice(0, 50).map((o) => ({ id: o, name: o, kind: null, type: null, status: null })))
    : get<{ items: ListItem[] }>("list", { what: what ?? "objects", q, limit: "50", view: c.view, ...params }).then((r) => r.items);
  return (
    <label className="ae-field">
      <span>{label}</span>
      <Combo<ListItem> label={label} value={value} width={width} placeholder="type to search" search={search} keyOf={(i) => i.id}
        onPick={(i) => { if (i.id !== value || (user !== undefined && (i.kind === "user") !== user)) onPick(i.id, i); }}
        render={(i) => <><span className="ae-mono">{i.id}</span>{(i.kind || i.type) && <span className="ae-muted">{i.kind && i.kind !== "object" ? KIND_SHORT[i.kind] ?? i.kind : (i.type ?? "").toLowerCase()}</span>}</>} />
    </label>
  );
}

export function Sel({ label, value, options, onPick }: {
  label: string; value: string; options: [string, string][]; onPick: (v: string) => void;
}) {
  return (
    <label className="ae-field">
      <span>{label}</span>
      <select className="ae-input" value={value} onChange={(e) => onPick(e.target.value)}>
        {options.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
      </select>
    </label>
  );
}

export function Tog({ label, on, onPick, help }: { label: string; on: boolean; onPick: (v: boolean) => void; help?: string }) {
  return (
    <label className="ae-field ae-check" title={help}>
      <input type="checkbox" checked={on} onChange={(e) => onPick(e.target.checked)} /> {label}
    </label>
  );
}


export const Controls = ({ children }: { children: ReactNode }) => <div className="ae-controls">{children}</div>;

/** One query to copy and run in Snowflake yourself. */
export function SqlBox({ title, sql }: { title?: string; sql: string }) {
  const [done, setDone] = useState("");
  return (
    <div className="ae-sqlbox">
      <div className="ae-sqlbox-h">{title && <b>{title}</b>}
        <button type="button" className="ae-btn" onClick={() => copyText(sql).then((ok) => { setDone(ok ? "Copied" : "Select and copy"); setTimeout(() => setDone(""), 1500); })}>{done || "Copy SQL"}</button></div>
      <pre tabIndex={0}>{sql}</pre>
    </div>
  );
}

/** The SQL behind a page (top bar "SQL", or a right-click on the page): every query, commented, with the SET lines
 * filled in for what the page shows, to run in Snowflake with your own role. */
export function SqlPanel({ page, params, onClose, hint = "" }: { page: string; params: Record<string, string | undefined>; onClose: () => void; hint?: string }) {
  const s = useApi<{ page: string; queries: { title: string; sql: string }[] }>("sql", { ...params, page });
  // the card it was opened from leads: queries whose title or comment share the most words with the card's title
  const words = hint.toLowerCase().split(/[^a-z0-9_]+/).filter((w) => w.length > 3);
  const score = (q: { title: string; sql: string }) => { const t = (q.title + " " + q.sql.slice(0, 500)).toLowerCase(); return words.filter((w) => t.includes(w)).length; };
  useEffect(() => { const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); }; addEventListener("keydown", k); return () => removeEventListener("keydown", k); }, [onClose]);
  return (
    <div className="ae-sqlpanel" role="dialog" aria-label="SQL behind this page">
      <div className="ae-sqlpanel-h"><div><h2>SQL behind this page</h2>
        <p className="ae-muted">Read-only queries over SNOWFLAKE.ACCOUNT_USAGE. Change the SET lines and run them in a worksheet with your own role; without access Snowflake says so. The app never runs them.</p></div>
        <button type="button" className="ae-btn" onClick={onClose}>Close</button></div>
      {hint && <p className="ae-sqlpanel-for">For <b>{hint}</b>: the closest queries first.</p>}
      <Load s={s}>{(d) => <>{[...d.queries].map((q, i) => ({ q, i, n: score(q) })).sort((a, b) => b.n - a.n || a.i - b.i)
        .map(({ q }) => <SqlBox key={q.title} title={q.title} sql={q.sql} />)}</>}</Load>
    </div>
  );
}

export function Head({ title, sub, right }: { title: ReactNode; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="ae-pagehead">
      <div><h2>{title}</h2>{sub && <p className="ae-muted">{sub}</p>}</div>
      {right}
    </div>
  );
}

/** The page's main graph. Over-big summaries offer "draw all"; schema / type filters show as a removable chip row. */
export function GraphCard({ g, title, refs }: { g: G | null; title?: string; refs?: Refs }) {
  const c = useApp();
  const o = useOpen(refs);
  if (!g) return null;
  const filters = (["schema", "otype"] as const).filter((k) => c.params[k]);
  return (
    <Card title={title ?? g.title} sub={g.header}
      right={g.level === "summary" && !g.full ? <button className="ae-btn" onClick={() => c.set({ full: "1" })}>Draw all</button>
        : c.params.full ? <button className="ae-btn" onClick={() => c.set({ full: null })}>Fold again</button> : undefined}>
      {filters.length > 0 && (
        <div className="ae-graph-open">
          Showing
          {filters.map((k) => <button key={k} className="ae-chip ae-chip-plain" onClick={() => c.set({ [k]: null })}>{k} {c.params[k]} ×</button>)}
        </div>
      )}
      {g.note && <p className="ae-graph-note">{g.note}</p>}
      <Graph graph={g} theme={c.theme} onNodeClick={o.node} onRules={(id) => c.nav("rules", { grantee: id.replace(/ \(user\)$/, "") })} />
    </Card>
  );
}

export function PathCell({ path, refs }: { path: string[]; refs: Refs }) {
  const o = useOpen(refs);
  return <PathText path={path} kinds={refs.kinds} onOpen={o.open} />;
}

export const pathCol = <R extends { path?: string[] | null }>(refs: Refs, label = "Path"): Column<R> =>
  col<R>("path", label, (r) => (r.path ?? []).join(" > "), { render: (r) => (r.path ? <PathCell path={r.path} refs={refs} /> : null), wrap: "nowrap" });

export function NameLink({ id, refs, label }: { id: string; refs: Refs; label?: string }) {
  const o = useOpen(refs);
  const k = refs.kinds[id] ?? "plain";
  return <button className={`ae-link ae-k-${k}`} onClick={() => o.open(id)} title={id}>{label ?? id}</button>;
}

const SCOPE: [string, string][] = [["on", "object"], ["priv", "privilege"]]; // schema / otype: the graph card shows them

/** The filters this page carries in its URL, as chips: × removes one. Keeps a picked object or schema from silently
 * narrowing other tabs. */
export function ScopeChips() {
  const c = useApp();
  const on = SCOPE.filter(([k]) => c.params[k]);
  if (!on.length) return null;
  return (
    <div className="ae-graph-open">
      Showing only
      {on.map(([k, w]) => <button key={k} className="ae-chip ae-chip-plain" onClick={() => c.set({ [k]: null })}>{w} {c.params[k]} ×</button>)}
      {on.length > 1 && <button className="ae-link" onClick={() => c.set(Object.fromEntries(on.map(([k]) => [k, null])))}>clear all</button>}
    </div>
  );
}

/** Rule findings of a user, role or object: compact "High 2 · Medium 1" that opens the severity tabs in place. */
export function Findings({ list, refs }: { list: Finding[]; total?: number; refs: Refs }) {
  const c = useApp();
  const o = useOpen(refs);
  if (!list.length) return null;
  return (
    <section className="ae-card ae-card-tight">
      <FindingList list={list} compact kinds={refs.kinds} onOpen={o.open} onRule={(num) => c.nav("rules", { rule: num })}
        whatIf={(p) => { const ch = changeOfPath(p, refs.kinds); return ch && <WhatIfButton ch={[ch]} />; }} />
    </section>
  );
}

const tone = (s: string) => (s === "masked" || s === "none" ? "ae-st-masked" : s === "clear" || s === "all" ? "ae-st-clear" : "ae-st-unknown");

/** A state chip (clear / masked / all / filtered / unknown) with its reason on hover. */
const WORD: Record<string, string> = { clear: "visible", masked: "masked", all: "all rows", filtered: "filtered rows", none: "no rows", unknown: "unknown" };
export const StateTag = (x: StateWhy<string>) => <span className={`ae-st ${tone(x.state)}`} title={x.reason}>{WORD[x.state] ?? x.state}</span>;

interface VRow { object: string; item: string; state: string; reason: string }

/** What a role or user sees in each object they can read: columns clear or masked, rows all or filtered. */
export function DataViews({ views, title = "What they see when they read" }: { views: DataView[] | null; title?: string }) {
  if (!views?.length) return null;
  const rows: VRow[] = views.flatMap((v) => [
    ...v.columns.map((x) => ({ object: v.object, item: x.column, state: x.state as string, reason: x.reason })),
    { object: v.object, item: "(rows)", state: v.rows.state as string, reason: v.rows.reason + (v.rows.condition ? ` · ${v.rows.condition}` : "") },
  ]);
  return (
    <Card title={title} sub="Only objects with sensitive columns or row policies">
      <DataTable csv="data_views.csv" rows={rows}
        columns={[
          col("o", "Object", (r: VRow) => r.object, { wrap: "wrap" }),
          col("i", "Column", (r: VRow) => r.item),
          col("s", "State", (r: VRow) => r.state, { render: (r: VRow) => StateTag(r) }),
          col("r", "Why", (r: VRow) => r.reason, { wrap: "wrap" }),
        ]} />
    </Card>
  );
}

const USE = { used: "used", secondary: "used as secondary", unused: "not used" } as const;

/** Every role granted to the user straight: held against used (bar = share of queries), unused first as candidates to
 * remove, with what removing it takes away; warehouses on one line. */
export function Usage({ u, refs }: { u: UsageCard; refs?: Refs }) {
  const o = useOpen(refs);
  const max = Math.max(1, ...u.roles.map((r) => r.queries));
  return (
    <Card title="Role usage" sub={u.source}>
      {!u.readable ? <p className="ae-muted">Query history is not readable with this role, so use is unknown.</p> : (
        <>
          <div className="ae-usage">
            {u.roles.map((r) => (
              <div key={r.role} className={`ae-use ae-use-${r.status}`}>
                <button className={`ae-chip ae-chip-${r.kind}`} onClick={() => o.open(r.role)}>{r.role}</button>
                <span className="ae-use-bar"><span style={{ width: `${(100 * r.queries) / max}%` }} /></span>
                <span className="ae-use-n">{r.queries ? `${r.queries} queries` : ""}</span>
                <span className="ae-muted">{r.last_used ? `last ${r.last_used.slice(0, 10)}` : ""}</span>
                <span className={`ae-tag ae-tag-${r.status === "unused" ? "warn" : "ok"}`}>
                  {r.status === "unused" ? `not used in ${u.days} days · candidate to remove` : USE[r.status]}{r.default ? " · default" : ""}
                </span>
                {r.takes != null && <span className="ae-muted">{r.takes ? `removing it takes away ${r.takes} object${r.takes === 1 ? "" : "s"}` : "removing it takes nothing away"}</span>}
              </div>
            ))}
          </div>
          {u.warehouses.length > 0 && <p className="ae-muted">Warehouses: {u.warehouses.map((w) => `${w.name} (${w.queries})`).join(" · ")}</p>}
        </>
      )}
    </Card>
  );
}
