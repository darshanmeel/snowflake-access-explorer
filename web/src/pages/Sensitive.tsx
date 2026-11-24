import { useEffect, useState } from "react";
import { useApi } from "../api/client";
import type { SensitivePage } from "../api/types";
import { Fold, Figs, Banner, Card, EmptyState, ListToolbar, MaskDots, MiniBar, Tabs, Waiting, type BarPart } from "../components";
import { apiParams, useApp } from "../ctx";
import { Catalog } from "./Catalog";
import { col, Controls, Head, Load, NameLink, pathCol, Sel, Tog, unread } from "./common";
import { PagedTable } from "./paged";

type O = SensitivePage["objects"][number];
type R = SensitivePage["readers"][number];
type T = SensitivePage["row_list"][number];
const LINKED = ["catalog", "rows"]; // tabs other pages open with show=

/** The people who can read an object, each once (the server counts them): active, dormant / disabled / never logged
 * in, service users, only through an admin role. */
export function readerParts(n: O["readers"]): BarPart[] {
  return [{ key: "active", label: "Active", value: n.active, cls: "active" }, { key: "dormant", label: "Dormant or disabled", value: n.dormant, cls: "dormant" },
    { key: "service", label: "Service users", value: n.service, cls: "service" }, { key: "admin", label: "Through an admin role", value: n.admin, cls: "admin" }];
}

const readersOf = (o: O) => o.readers.active + o.readers.dormant + o.readers.service + o.readers.admin;

/** A tag chip: the value ("CONFIDENTIAL"), the tag name and where it comes from on hover; never cut mid-word. */
const tagChip = (t: { label: string; origins: string[] }) => (
  <span key={t.label} className="ae-otag ae-sens-tag" title={`${t.label}\n${t.origins.join("; ")}`}>{t.label.split("=").pop()}</span>
);

const WHY: Record<string, string> = {
  mine: "Sensitive data is not shown in My access: it needs the shared snapshot, which reads tags and policies for the whole account.",
  unavailable: "Tags and policies cannot be read with this role, so sensitive data cannot be found.",
  no_tags: "No sensitivity tags are in use, so no object is marked sensitive.",
  none_sensitive: "Tags are in use, but no object carries a sensitive one.",
};

export function SensitivePageView() {
  const c = useApp();
  const s = useApi<SensitivePage>("sensitive", apiParams(c));
  const [part, setPart] = useState(LINKED.includes(c.params.show ?? "") ? c.params.show! : c.params.part ?? "objects"); // the old tables first
  const pol = unread(c.meta, "policies", true), polOff = c.meta.sources.policies === "UNAVAILABLE"; // off: masked is unknown
  return (
    <>
      <Head title="Sensitive data" quiet sub="Objects carrying a sensitive tag, and who can read them." />
      <Load s={s}>{(d) => {
        if (d.state !== "ok") return <><Banner tone="info" title="Nothing to show" lines={[WHY[d.state] ?? d.state]} />{d.row_total > 0 && <RowTables d={d} />}</>;
        const k = d.kpis;
        const most = Math.max(1, ...d.objects.map(readersOf));
        const first = { o_offset: null, r_offset: null }; // a new filter starts on page 1
        return (
          <>
            {part === "rows" ? <p className="ae-answer">{d.row_total.toLocaleString("en-US")} {d.row_total === 1 ? "table shows" : "tables show"} some roles fewer rows</p>
              : <><SensAnswer d={d} polOff={polOff} />
            <Figs items={[
              { key: "r", n: k.readers.toLocaleString("en-US"), text: "can read at least one", note: [`${k.people.toLocaleString("en-US")} people`, k.disabled && `${k.disabled.toLocaleString("en-US")} disabled`, k.service && `${k.service.toLocaleString("en-US")} service`, k.admin && `${k.admin.toLocaleString("en-US")} only through an admin role`].filter(Boolean).join(", ") },
              { key: "u", n: polOff ? "not read" : k.unmasked.toLocaleString("en-US"), text: "sensitive columns not masked", bad: !polOff && k.unmasked > 0 },
              { key: "o", n: k.objects.toLocaleString("en-US"), text: k.objects === 1 ? "sensitive object" : "sensitive objects", note: `${k.columns.toLocaleString("en-US")} columns tagged, ${k.whole.toLocaleString("en-US")} whole objects` },
            ]} /></>}
            {d.filters.people && <p className="ae-muted">Counts are every reader; People only filters the tables.</p>}
            <PolicyNote />
            <Tabs nav active={part} onChange={(k) => { setPart(k); c.set({ show: LINKED.includes(k) ? k : null }); }} tabs={[
              { key: "objects", label: "Sensitive objects", count: d.objects_total },
              { key: "readers", label: "Users who can read them", count: d.readers_total },
              { key: "catalog", label: "Catalog", count: d.catalog_total },
              ...(d.row_total || pol ? [{ key: "rows", label: "Row policies", count: d.row_total }] : []),
            ]} />
            {part === "catalog" && (d.catalog ? <Catalog rows={d.catalog} /> : <Waiting />)}
            {part === "rows" && (d.row_total || !pol ? <RowTables d={d} /> : <EmptyState title="Not read">{pol.title}: tables with row policies are not known.</EmptyState>)}
            {part === "objects" && <Card title="Sensitive objects" scroll>
              <PagedTable path="sensitive" at="o_offset" total={d.objects_total} offset={d.objects_offset} pick={(x: SensitivePage) => x.objects}
                csv="sensitive_objects.csv" rows={d.objects}
                columns={[
                  col("o", "Object", (r: O) => r.object, { render: (r: O) => <span className="ae-objcell"><NameLink id={r.object} refs={d.refs} /><span className="ae-muted ae-osub">{r.type.toLowerCase()}</span></span>, wrap: "wrap" }),
                  col("c", "Columns masked", (r: O) => (r.cols.length ? `${r.masked[0]} of ${r.masked[1]}: ${r.cols.join(", ")}` : "whole object"), { help: "One dot per sensitive column: filled = masked, open red ring = read in the clear", wrap: "wrap",
                    render: (r: O) => polOff && r.cols.length ? <span className="ae-muted">unknown: policies not read</span> : r.cols.length ? (
                      <span className="ae-maskcell"><MaskDots columns={r.columns.length ? r.columns : r.cols.map((x, i) => ({ column: x, masked: i < r.masked[0] }))} />
                        <span className={r.masked[0] < r.masked[1] ? "ae-bad" : "ae-muted"}>{r.masked[0]} of {r.masked[1]}</span>
                        <span className="ae-muted ae-maskcols">{r.cols.join(", ")}</span></span>) : <span className="ae-muted">whole object</span> }),
                  col("p", "Who can read", readersOf, { num: true, help: "People who can read it: active, dormant or disabled, service users, through an admin role",
                    render: (r: O) => <MiniBar of={most} parts={readerParts(r.readers)} /> }),
                  col("cl", "Sees clear", (r: O) => r.clear ?? "unknown", { num: true, help: "Readers who see a sensitive value unmasked: all of them when a column has no masking, else those a masking policy shows it to" }),
                  col("g", "Tags", (r: O) => r.tags.map((t) => t.label).join(", "), { render: (r: O) => <span className="ae-objtags0">{r.tags.map(tagChip)}</span>, wrap: "wrap" }),
                  col("rp", "Row policy", (r: O) => r.row_policies.join(", "), { wrap: "wrap" }),
                  col("ro", "Roles", (r: O) => r.roles.join(", ") + (r.roles_total > r.roles.length ? ` +${r.roles_total - r.roles.length} more` : ""), { wrap: "truncate" }),
                ]} />
              <div className="ae-bar-legend ae-mt">{readerParts({ active: 0, dormant: 0, service: 0, admin: 0 }).map((p) => <span key={p.key}><span className={`ae-dot2 ae-bar-${p.cls}`} />{p.label}</span>)}
                <span><span className="ae-dotm ae-dotm-ok" /> masked column</span><span><span className="ae-dotm ae-dotm-bad" /> not masked</span></div>
            </Card>}
            {part === "readers" && <Card title="Who can read them" sub="One row per user; the shortest path to a sensitive object" scroll>
              <PagedTable path="sensitive" at="r_offset" total={d.readers_total} offset={d.readers_offset} pick={(x: SensitivePage) => x.readers}
                csv="sensitive_readers.csv" rows={d.readers} rowTone={(r: R) => (r.via_admin ? "bad" : r.status !== "active" ? "warn" : null)}
                columns={[
                  col("u", "User", (r: R) => r.user, { render: (r: R) => <NameLink id={r.user} refs={d.refs} /> }),
                  col("t", "Type", (r: R) => r.type), col("s", "Status", (r: R) => r.status), col("l", "Last login", (r: R) => r.last_login_text),
                  col("ob", "Objects", (r: R) => r.objects ?? "through an admin role", { num: true }),
                  col("ro", "Via roles", (r: R) => r.roles.join(", "), { wrap: "truncate" }),
                  pathCol<R>(d.refs),
                ]} />
            </Card>}
            {part !== "rows" && <Fold label="Filter" on={!!d.filters.tag || !!d.filters.db || d.filters.people}>
            <Controls>
              <Sel label="Tag" value={d.filters.tag} onPick={(v) => c.set({ tag: v, ...first })} options={[["", "All tags"], ...d.filters.tags.map((t): [string, string] => [t, t])]} />
              <Sel label="Database" value={d.filters.db} onPick={(v) => c.set({ db: v, ...first })} options={[["", "All databases"], ...d.filters.dbs.map((t): [string, string] => [t, t])]} />
              <Tog label="People only" on={d.filters.people} onPick={(v) => c.set({ people: v ? "1" : null, ...first })} />
            </Controls>
            </Fold>}
          </>
        );
      }}</Load>
    </>
  );
}

/** A warning when the masking and row policies were not read, or only in part: masked / not masked is then unknown
 * (Sensitive data, Catalog, Flow). */
export function PolicyNote() {
  const c = useApp();
  const n = unread(c.meta, "policies", true);
  return n && <Banner tone="warn" title={c.meta.sources.policies === "UNAVAILABLE" ? "Policies not read: masked and unmasked are unknown" : n.title}
    lines={[n.meaning, ...(n.fix ? [`Fix: ${n.fix}`] : [])].filter(Boolean)} />;
}

/** The answer first: how many sensitive objects, how exposed, and who reads them; each part opens where it is acted on. */
function SensAnswer({ d, polOff }: { d: SensitivePage; polOff: boolean }) {
  const c = useApp();
  const k = d.kpis;
  const n = (x: number, w: string, ws = `${w}s`) => `${x.toLocaleString("en-US")} ${x === 1 ? w : ws}`;
  return (
    <p className="ae-answer">
      {n(k.objects, "sensitive object")}{polOff ? "" : <>, {n(k.unmasked, "column")} nobody masks</>}
      {k.stale_total > 0 && <>; <button type="button" className="ae-link" onClick={() => c.nav("rules", { part: "stale" })}>{n(k.stale_total, "inactive person", "inactive people")} can still read them</button></>}
    </p>
  );
}

/** Every table with a row access policy, sensitive or not, with which roles the policy text lets see every row or
 * some rows: one page at t_offset=, t_q= searches. */
function RowTables({ d }: { d: SensitivePage }) {
  const c = useApp();
  const [q, setQ] = useState(c.params.t_q ?? "");
  useEffect(() => {
    const t = setTimeout(() => { if (q !== (c.params.t_q ?? "")) c.set({ t_q: q || null, t_offset: null }); }, 300);
    return () => clearTimeout(t);
  }, [q]); // eslint-disable-line react-hooks/exhaustive-deps
  const roles = (xs: string[]) => (xs.length > 3 ? `${xs.slice(0, 3).join(", ")} +${xs.length - 3} more` : xs.join(", "));
  return (
    <Card title="Tables with row policies" sub="Which roles see every row, which see some; any other reader sees no rows. Open a table for the policy text." scroll>
      <ListToolbar search={q} onSearch={setQ} />
      <PagedTable path="sensitive" at="t_offset" total={d.row_total} offset={d.row_offset} pick={(x: SensitivePage) => x.row_list}
        csv="row_policy_tables.csv" rows={d.row_list}
        columns={[col("o", "Table", (r: T) => r.object, { render: (r: T) => <NameLink id={r.object} refs={d.refs} />, wrap: "wrap" }),
          col("s", "Sensitive", (r: T) => (r.sensitive ? "yes" : "no"), { render: (r: T) => (r.sensitive ? <span className="ae-otag ae-sens-tag">sensitive</span> : <span className="ae-muted">no</span>) }),
          col("p", "Row policies", (r: T) => r.policies.join(", "), { render: (r: T) => r.policies.map((x) => <div key={x} className="ae-mono">{x}</div>), wrap: "wrap" }),
          col("a", "Every row", (r: T) => (r.known ? roles(r.all_rows) || "no role" : "unknown"), { wrap: "wrap", help: "Roles the policy text lets see every row",
            render: (r: T) => (r.known ? roles(r.all_rows) || <span className="ae-muted">no role</span> : <span className="ae-muted" title="The policy uses a mapping table, a function or other logic">unknown: open the table</span>) }),
          col("f", "Some rows", (r: T) => (r.known ? roles(r.some_rows) : "unknown"), { wrap: "wrap", help: "Roles the policy text lets see rows matching a condition; other readers see none",
            render: (r: T) => (r.known ? roles(r.some_rows) || <span className="ae-muted">none</span> : <span className="ae-muted">unknown</span>) }),
          col("r", "Read by", (r: T) => r.readers, { num: true })]} />
      {!d.row_list.length && q && <p className="ae-muted">No table or policy matches “{q}”.</p>}
    </Card>
  );
}
