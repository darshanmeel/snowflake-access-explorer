// Object activity: every table, view, warehouse and Streamlit app by its last use (ACCESS_HISTORY, QUERY_HISTORY):
// what is not used, tables read but never written and the reverse. Counts and the chart come with the page; the
// table pages, sorts and searches on the server.
import { useApi } from "../api/client";
import type { ObjUsePage, ObjUseRow } from "../api/types";
import { AGE, AgeBars, Card, DataTable, EmptyState, FilterChips, Tabs } from "../components";
import { useApp } from "../ctx";
import { col, Controls, Load, Pick, Sel } from "./common";

const TABS = ["unused", "read_only", "write_only", "all"] as const;
const AGE_WORD = Object.fromEntries(AGE.map((a) => [a.key, a.label]));
const plural = (n: number, w: string) => `${n.toLocaleString()} ${w}${n === 1 ? "" : "s"}`;

export function ObjectUsePageView() {
  const c = useApp();
  const p = { view: c.view, tab: c.params.tab, days: c.params.days, type: c.params.type, scope: c.params.scope };
  const s = useApi<ObjUsePage>("objuse", { ...p, limit: "0" }); // counts only: the table asks for its rows
  return (
    <>
      <div className="ae-headrow"><h2 className="ae-h1">Object activity</h2></div>
      <Load s={s} wait="Reading the last use of every object">{(d) => <Body d={d} />}</Load>
    </>
  );
}

function Body({ d }: { d: ObjUsePage }) {
  const c = useApp();
  const tab = d.tab;
  const known = d.types.some((t) => t.buckets.nodata < t.total);
  if (!known) return (
    <Card title="No activity to show">
      <EmptyState title="Object activity needs ACCESS_HISTORY">{d.reason ?? d.notes.join(" ")}</EmptyState>
      <p className="ae-note">{d.enable}</p>
    </Card>
  );
  const types = [["", "Any type"], ...d.types.map((t) => [t.type, t.type.toLowerCase()])] as [string, string][];
  return (
    <>
      <p className="ae-answer">
        <b>{plural(d.tabs.unused, "object")}</b> not used in the last {d.days} days
        {d.tabs.read_only + d.tabs.write_only > 0 && <> · tables <b>read, never written</b>: {d.tabs.read_only.toLocaleString()} · <b>written, never read</b>: {d.tabs.write_only.toLocaleString()}</>}
        {d.new > 0 && <> · {plural(d.new, "object")} created or changed in the activity window</>}.
      </p>
      {!d.available && d.reason && <p className="ae-warn-word">{d.reason}</p>}
      {d.notes.map((n) => <p key={n} className="ae-muted">Not read: {n}</p>)}
      <Controls>
        <FilterChips label="Days" value={String(d.days)} onPick={(k) => c.set({ days: k === "90" ? null : k })}
          items={d.periods.map((x) => ({ key: String(x), label: `${x} days` }))} />
        <Sel label="Type" value={d.type} options={types} onPick={(v) => c.set({ type: v || null })} />
        <Pick label="Database or schema" value={d.scope} what="databases,objects" params={{ type: "SCHEMA" }} onPick={(v) => c.set({ scope: v })} />
        {d.scope && <button type="button" className="ae-chip ae-chip-plain" onClick={() => c.set({ scope: null })}>any database ×</button>}
      </Controls>
      <Tabs nav active={tab} onChange={(k) => c.set({ tab: k === "unused" ? null : k })} tabs={[
        { key: "unused", label: "Not used", count: d.tabs.unused },
        { key: "read_only", label: "Read, never written", count: d.tabs.read_only },
        { key: "write_only", label: "Written, never read", count: d.tabs.write_only },
        { key: "all", label: "All objects", count: d.tabs.all },
      ]} />
      {tab === "unused" && (
        <Card title="Last use per type" sub="Each object counted once, at its last read or write. A type picks the table below.">
          <AgeBars types={d.types} onPick={(t) => c.set({ type: t === d.type ? null : t })} />
        </Card>
      )}
      <Card title={TITLE[tab](d.days)} sub={SUB[tab]}>
        <Table d={d} />
        <p className="ae-muted ae-foot">
          Tables and views: ACCESS_HISTORY over {d.history.data} days, reads through a view count as reads{d.base_read ? "" : " (this snapshot has direct reads only)"}.
          {" "}Warehouses: queries run, QUERY_HISTORY over {d.history.warehouse} days. Streamlit apps: queries for their viewers over {d.history.app} days.
          {" "}Procedures, functions and tasks have no use in the snapshot: "no activity data", never "not used".
          {d.source === "demo values" && " These are demo values."}
        </p>
      </Card>
    </>
  );
}

const TITLE: Record<(typeof TABS)[number], (days: number) => string> = {
  unused: (n) => `Not used in the last ${n} days`, read_only: (n) => `Tables read, never written in ${n} days`,
  write_only: (n) => `Tables written, never read in ${n} days`, all: (n) => `Every object, use in the last ${n} days`,
};
const SUB: Record<(typeof TABS)[number], string> = {
  unused: "Never used first, then the longest unused. A new or changed object is marked: it may simply be new.",
  read_only: "Read in the window, no inserts, updates or merges: a reference or a finished load. Views are never written, so they are left out.",
  write_only: "Loaded in the window but nobody read it: a load nobody needs, or one read only later.",
  all: "Every table, view, warehouse and Streamlit app.",
};
const SORT: Record<(typeof TABS)[number], { key: string; dir: 1 | -1 }> = {
  unused: { key: "days", dir: -1 }, read_only: { key: "read_q", dir: -1 }, write_only: { key: "write_q", dir: -1 }, all: { key: "object", dir: 1 },
};

function Table({ d }: { d: ObjUsePage }) {
  const c = useApp();
  const day = (v: string | null) => (v ? v.slice(0, 10) : "–");
  const cols = [
    col<ObjUseRow>("object", "Object", (r) => r.object, {
      render: (r) => <span>
        <button type="button" className="ae-link ae-mono" onClick={() => c.nav("object", { name: r.object })}>{r.object}</button>
        {r.new && <span className="ae-otag ae-otag-warn" title="DDL on it in the activity window: created or changed recently"> new or changed</span>}
        {r.sensitive && <span className="ae-sens-word"> · sensitive</span>}
      </span>,
    }),
    col<ObjUseRow>("type", "Type", (r) => r.type.toLowerCase()),
    col<ObjUseRow>("last_read", "Last read", (r) => day(r.last_read), { help: "Warehouses: last query run; apps: last opened" }),
    col<ObjUseRow>("last_write", "Last written", (r) => day(r.last_write)),
    col<ObjUseRow>("days", "Days since used", (r) => r.days_since ?? "never", { num: true }),
    col<ObjUseRow>("bucket", "Last used", (r) => AGE_WORD[r.bucket] ?? r.bucket),
    col<ObjUseRow>("read_q", "Read queries", (r) => r.read_q, { num: true, help: `In the last ${d.days} days; warehouses: queries run` }),
    col<ObjUseRow>("write_q", "Write queries", (r) => r.write_q, { num: true }),
    col<ObjUseRow>("readers", "Readers", (r) => r.readers, { num: true, help: "Distinct users in the window" }),
    col<ObjUseRow>("writers", "Writers", (r) => r.writers, { num: true }),
  ];
  return (
    <DataTable key={`${d.tab}|${d.days}`} columns={cols} rows={[]} sort={SORT[d.tab]} csv={`object_activity_${d.tab}_${d.days}d.csv`}
      empty={d.tab === "unused" ? "Everything here was used in this window." : "Nothing here: change the filters."}
      server={{ path: "objuse", params: { view: c.view, tab: d.tab, days: String(d.days), type: d.type || null, scope: d.scope || null } }} />
  );
}
