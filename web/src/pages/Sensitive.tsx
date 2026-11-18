import { useState } from "react";
import { useApi } from "../api/client";
import type { SensitivePage } from "../api/types";
import { Banner, Card, DataTable, KpiRow, MaskDots, MiniBar, NameList, Tabs, type BarPart } from "../components";
import { apiParams, useApp } from "../ctx";
import { Catalog } from "./Catalog";
import { col, Controls, Head, Load, NameLink, pathCol, Sel, Tog } from "./common";
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
  return (
    <>
      <Head title="Sensitive data" sub="Objects carrying a sensitive tag, and who can read them."
        right={<div className="ae-row0"><button type="button" className="ae-btn" onClick={() => c.nav("flow", {})}>Data flow</button>
          <button type="button" className="ae-btn" onClick={() => c.nav("review", { show: "grid" })}>Review & sign-off</button></div>} />
      <Load s={s}>{(d) => {
        if (d.state !== "ok") return <><Banner tone="info" title="Nothing to show" lines={[WHY[d.state] ?? d.state]} />{d.row_total > 0 && <RowTables d={d} />}</>;
        const k = d.kpis;
        const cols = new Map(d.catalog.map((r) => [r.object, r.columns]));
        const most = Math.max(1, ...d.objects.map(readersOf));
        const first = { o_offset: null, r_offset: null }; // a new filter starts on page 1
        return (
          <>
            <Controls>
              <Sel label="Tag" value={d.filters.tag} onPick={(v) => c.set({ tag: v, ...first })} options={[["", "All tags"], ...d.filters.tags.map((t): [string, string] => [t, t])]} />
              <Sel label="Database" value={d.filters.db} onPick={(v) => c.set({ db: v, ...first })} options={[["", "All databases"], ...d.filters.dbs.map((t): [string, string] => [t, t])]} />
              <Tog label="People only" on={d.filters.people} onPick={(v) => c.set({ people: v ? "1" : null, ...first })} />
            </Controls>
            <KpiRow items={[
              { label: "Sensitive objects", value: k.objects, caption: `${k.columns} columns, ${k.whole} whole-object` },
              { label: "People who can read", value: k.people, caption: `${k.service} service` },
              { label: "Admin readers", value: k.admin, tone: k.admin ? "bad" : null },
              { label: "Disabled readers", value: k.disabled, tone: k.disabled ? "warn" : null },
              { label: "Unmasked columns", value: k.unmasked, tone: k.unmasked ? "bad" : null },
            ]} />
            {k.stale.length > 0 && <Banner tone="warn" title={`Disabled or dormant users still hold access: ${k.stale.length.toLocaleString()}`}>
              <NameList items={k.stale} onOpen={(u) => c.nav("access", { user: u })} onMore={() => c.nav("rules", { rule: "7" })} /></Banner>}
            <p className="ae-muted"><button type="button" className="ae-link" onClick={() => c.nav("compare", { scope: "sensitive" })}>Compare two people or roles on sensitive data →</button></p>
            <Tabs nav active={part} onChange={(k) => { setPart(k); c.set({ show: LINKED.includes(k) ? k : null }); }} tabs={[
              { key: "objects", label: "Sensitive objects", count: d.objects_total },
              { key: "readers", label: "Who can read them", count: d.readers_total },
              { key: "catalog", label: "Catalog", count: d.catalog.length },
              ...(d.row_total ? [{ key: "rows", label: "Row policies", count: d.row_total }] : []),
            ]} />
            {part === "catalog" && <Catalog rows={d.catalog} />}
            {part === "rows" && <RowTables d={d} />}
            {part === "objects" && <Card title="Sensitive objects" scroll>
              <PagedTable path="sensitive" at="o_offset" total={d.objects_total} offset={d.objects_offset} pick={(x: SensitivePage) => x.objects}
                csv="sensitive_objects.csv" rows={d.objects}
                columns={[
                  col("o", "Object", (r: O) => r.object, { render: (r: O) => <span className="ae-objcell"><NameLink id={r.object} refs={d.refs} /><span className="ae-muted ae-osub">{r.type.toLowerCase()}</span></span>, wrap: "wrap" }),
                  col("g", "Tags", (r: O) => r.tags.map((t) => t.label).join(", "), { render: (r: O) => <span className="ae-objtags0">{r.tags.map(tagChip)}</span>, wrap: "wrap" }),
                  col("c", "Columns masked", (r: O) => (r.cols.length ? `${r.masked[0]} of ${r.masked[1]}: ${r.cols.join(", ")}` : "whole object"), { help: "One dot per sensitive column: filled = masked, open red ring = read in the clear", wrap: "wrap",
                    render: (r: O) => r.cols.length ? (
                      <span className="ae-maskcell"><MaskDots columns={cols.get(r.object) ?? r.cols.map((x, i) => ({ column: x, masked: i < r.masked[0] }))} />
                        <span className={r.masked[0] < r.masked[1] ? "ae-bad" : "ae-muted"}>{r.masked[0]} of {r.masked[1]}</span>
                        <span className="ae-muted ae-maskcols">{r.cols.join(", ")}</span></span>) : <span className="ae-muted">whole object</span> }),
                  col("rp", "Row policy", (r: O) => r.row_policies.join(", "), { wrap: "wrap" }),
                  col("p", "Who can read", readersOf, { num: true, help: "People who can read it: active, dormant or disabled, service users, through an admin role",
                    render: (r: O) => <MiniBar of={most} parts={readerParts(r.readers)} /> }),
                  col("ro", "Roles", (r: O) => r.roles.join(", "), { wrap: "truncate" }),
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
                  col("ob", "Objects", (r: R) => r.objects, { num: true }),
                  col("ro", "Via roles", (r: R) => r.roles.join(", "), { wrap: "truncate" }),
                  pathCol<R>(d.refs),
                ]} />
            </Card>}
          </>
        );
      }}</Load>
    </>
  );
}

/** Every table with a row access policy, sensitive or not: one page at t_offset=. */
function RowTables({ d }: { d: SensitivePage }) {
  return (
    <Card title="Tables with row policies" sub="Each row policy decides which rows a role sees. Open a table for who reads it." scroll>
      <PagedTable path="sensitive" at="t_offset" total={d.row_total} offset={d.row_offset} pick={(x: SensitivePage) => x.row_list}
        csv="row_policy_tables.csv" rows={d.row_list}
        columns={[col("o", "Table", (r: T) => r.object, { render: (r: T) => <NameLink id={r.object} refs={d.refs} />, wrap: "wrap" }),
          col("p", "Row policies", (r: T) => r.policies.join(", "), { render: (r: T) => r.policies.map((x) => <div key={x} className="ae-mono">{x}</div>), wrap: "wrap" })]} />
    </Card>
  );
}
