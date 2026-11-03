// Pieces shared by the pages: pickers, load/error frame, graph card, findings, data views, usage.
import { useId, type ReactNode } from "react";
import type { ApiFail, State } from "../api/client";
import type { Banner as B, DataView, FindingLine, Graph as G, Refs, StateWhy, UsageCard } from "../api/types";
import { Banner, Card, DataTable, Graph, PathText, type Column } from "../components";
import { useApp, useOpen } from "../ctx";

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
        <p>You can still look at your own access: switch to "My access" in the top bar.</p>
        <button className="ae-btn" onClick={() => c.nav("user", {})}>Try again</button>
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

/** Pick one value from a long list: type to narrow, commit when the text matches an option. */
export function Pick({ label, value, options, onPick, width = 240 }: {
  label: string; value: string; options: string[]; onPick: (v: string) => void; width?: number;
}) {
  const id = useId();
  return (
    <label className="ae-field">
      <span>{label}</span>
      <input className="ae-input" style={{ width }} list={id} defaultValue={value} key={value} placeholder="type to search"
        onChange={(e) => { if (options.includes(e.target.value) && e.target.value !== value) onPick(e.target.value); }}
        onFocus={(e) => e.target.select()} />
      <datalist id={id}>{options.slice(0, 2000).map((o) => <option key={o} value={o} />)}</datalist>
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

export const DEPTHS: [string, string][] = [["", "No limit"], ["1", "1"], ["3", "3"], ["5", "5"], ["10", "10"]];

export const Controls = ({ children }: { children: ReactNode }) => <div className="ae-controls">{children}</div>;

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
      <Graph graph={g} theme={c.theme} onNodeClick={o.node} />
    </Card>
  );
}

export function PathCell({ path, refs }: { path: string[]; refs: Refs }) {
  const o = useOpen(refs);
  return <PathText path={path} kinds={refs.kinds} onOpen={o.open} />;
}

export const pathCol = <R extends { path?: string[] | null }>(refs: Refs, label = "Path"): Column<R> =>
  col<R>("path", label, (r) => (r.path ?? []).join(" > "), { render: (r) => (r.path ? <PathCell path={r.path} refs={refs} /> : null), wrap: "wrap", width: 420 });

export function NameLink({ id, refs, label }: { id: string; refs: Refs; label?: string }) {
  const o = useOpen(refs);
  const k = refs.kinds[id] ?? "plain";
  return <button className={`ae-link ae-k-${k}`} onClick={() => o.open(id)} title={id}>{label ?? id}</button>;
}

const SEV = { High: "bad", Medium: "warn", Low: null } as const;

export function Findings({ list, total, refs, title = "Rule findings" }: { list: FindingLine[]; total: number; refs: Refs; title?: string }) {
  const c = useApp();
  if (!list.length) return null;
  return (
    <Card title={title} sub={`${total} finding${total === 1 ? "" : "s"}`}
      right={<button className="ae-btn" onClick={() => c.nav("rules", {})}>All rule checks</button>}>
      <DataTable csv={null} filter={false} rows={list} maxHeight={320}
        rowTone={(f) => SEV[f.severity] ?? null}
        columns={[
          col("num", "Rule", (f: FindingLine) => f.num, { width: 60 }),
          col("sev", "Severity", (f: FindingLine) => f.severity, { width: 80 }),
          col("title", "Finding", (f: FindingLine) => f.title, { wrap: "wrap" }),
          col("who", "Holder", (f: FindingLine) => f.grantee, { render: (f: FindingLine) => <NameLink id={f.grantee} refs={refs} /> }),
          col("d", "Details", (f: FindingLine) => f.details.join(" · "), { wrap: "wrap" }),
        ]} />
    </Card>
  );
}

const tone = (s: string) => (s === "masked" || s === "none" ? "ae-st-masked" : s === "clear" || s === "all" ? "ae-st-clear" : "ae-st-unknown");

/** A state chip (clear / masked / all / filtered / unknown) with its reason on hover. */
export const StateTag = (x: StateWhy<string>) => <span className={`ae-st ${tone(x.state)}`} title={x.reason}>{x.state}</span>;

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

export function Usage({ u }: { u: UsageCard }) {
  return (
    <Card title="Role usage" sub={`Query history, last ${u.days} days · ${u.source}`}>
      {!u.readable ? <p className="ae-muted">Query history is not readable with this role, so use is unknown.</p> : (
        <DataTable csv={null} rows={u.rows} maxHeight={260} empty="No queries in this period."
          columns={[col("k", "Kind", (r: UsageCard["rows"][number]) => r.kind), col("n", "Name", (r: UsageCard["rows"][number]) => r.name),
            col("q", "Queries", (r: UsageCard["rows"][number]) => r.queries, { num: true }), col("l", "Last used", (r: UsageCard["rows"][number]) => r.last_used)]} />
      )}
    </Card>
  );
}
