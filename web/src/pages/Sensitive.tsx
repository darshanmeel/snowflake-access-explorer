import { useEffect, useState } from "react";
import { useApi } from "../api/client";
import type { SensitivePage } from "../api/types";
import { Fold, Figs, Banner, Card, EmptyState, ListToolbar, Tabs, Waiting, type BarPart } from "../components";
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
        const first = { o_offset: null, r_offset: null }; // a new filter starts on page 1
        return (
          <>
            {part === "rows" ? <p className="ae-answer">{d.row_total.toLocaleString("en-US")} {d.row_total === 1 ? "table shows" : "tables show"} some roles fewer rows</p>
              : <><SensAnswer d={d} polOff={polOff} />
            <Figs items={[
              { key: "r", n: k.readers.toLocaleString("en-US"), text: "can read at least one", note: (k.by ? [`${k.by.active.toLocaleString("en-US")} active`, k.by.risky && `${k.by.risky.toLocaleString("en-US")} inactive`, k.by.admin && `${k.by.admin.toLocaleString("en-US")} admins`, k.by.service && `${k.by.service.toLocaleString("en-US")} service`]
                : [`${k.people.toLocaleString("en-US")} people`, k.disabled && `${k.disabled.toLocaleString("en-US")} disabled`, k.service && `${k.service.toLocaleString("en-US")} service`, k.admin && `${k.admin.toLocaleString("en-US")} admins`]).filter(Boolean).join(", ") },
              { key: "u", n: polOff ? "not read" : k.unmasked.toLocaleString("en-US"), text: "columns not masked", bad: !polOff && k.unmasked > 0, note: polOff ? undefined : [...new Set(d.objects.flatMap((o) => o.columns.filter((x) => !x.masked).map((x) => x.column)))].slice(0, 4).join(", ") || undefined },
              { key: "o", n: k.objects.toLocaleString("en-US"), text: k.objects === 1 ? "sensitive object" : "sensitive objects", note: `${k.columns.toLocaleString("en-US")} columns tagged, ${k.whole.toLocaleString("en-US")} whole objects` },
            ]} /></>}
            {d.filters.people && <p className="ae-muted">Counts are every reader; People only filters the tables.</p>}
            <PolicyNote />
            <Tabs nav active={part} onChange={(k) => { setPart(k); c.set({ show: LINKED.includes(k) ? k : null }); }} tabs={[
              { key: "objects", label: "Objects", count: d.objects_total },
              { key: "readers", label: "Who can read them", count: d.readers_total },
              { key: "catalog", label: "Catalog", count: d.catalog_total },
              ...(d.row_total || pol ? [{ key: "rows", label: "Row rules", count: d.row_total }] : []),
            ]} />
            {part === "catalog" && (d.catalog ? <Catalog rows={d.catalog} /> : <Waiting />)}
            {part === "rows" && (d.row_total || !pol ? <RowTables d={d} /> : <EmptyState title="Not read">{pol.title}: tables with row policies are not known.</EmptyState>)}
            {part === "objects" && <Card title={!polOff && d.objects[0]?.cols.length && !d.objects[0].masked[0] ? `${d.objects[0].name ?? d.objects[0].object.split(".").pop()} has no protection at all` : "Least protected first"}>
              <PagedTable path="sensitive" at="o_offset" total={d.objects_total} offset={d.objects_offset} pick={(x: SensitivePage) => x.objects}
                csv="sensitive_objects.csv" rows={d.objects}
                columns={[
                  col("o", "Object", (r: O) => r.object, { render: (r: O) => <><NameLink id={r.object} refs={d.refs} label={r.object} /><span className="ae-muted ae-osub"> {r.type.toLowerCase()}</span></>, wrap: "wrap" }),
                  col("c", "Protected", (r: O) => (r.cols.length ? `${r.masked[0]} of ${r.masked[1]} columns` : "whole object"), { wrap: "wrap",
                    render: (r: O) => <>{polOff && r.cols.length ? <span className="ae-muted">unknown</span> : r.cols.length ? <span className={r.masked[0] < r.masked[1] ? "ae-bad" : undefined}>{r.masked[0]} of {r.masked[1]} {r.masked[1] === 1 ? "column" : "columns"}</span> : "whole object"}
                      {r.row_policies.length > 0 && <span className="ae-muted" title={r.row_policies.join(", ")}>, rows limited by {r.row_policies.map((x) => x.split(".").pop()).join(", ")}</span>}<span className="ae-muted ae-osub" title={r.tags.map((t) => t.label).join(", ")}> {r.tags.map((t) => t.label.split("=").pop()).join(", ")}</span></> }),
                  col("p", "Who can read", readersOf, { wrap: "wrap", render: (r: O) => <>{readersOf(r).toLocaleString("en-US")}{r.readers.admin > 0 && <span className="ae-muted">, {r.readers.admin.toLocaleString("en-US")} as admin</span>}{r.readers.dormant > 0 && <span className="ae-bad">, {r.readers.dormant.toLocaleString("en-US")} inactive</span>}</> }),
                  col("cl", "See in clear", (r: O) => r.clear ?? "unknown", { wrap: "wrap", render: (r: O) => { const open = r.columns.filter((x) => !x.masked).map((x) => x.column); return <span className={open.length ? "ae-bad" : undefined}>{open.length > 0 && `${open.join(", ")}: `}{r.clear ?? "unknown"}</span>; } }),
                ]} />
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
    <Card title="Row policies">
      <Fold label="Search" on={!!q}><ListToolbar search={q} onSearch={setQ} /></Fold>
      <PagedTable path="sensitive" at="t_offset" total={d.row_total} offset={d.row_offset} pick={(x: SensitivePage) => x.row_list}
        csv="row_policy_tables.csv" rows={d.row_list}
        columns={[col("o", "Table", (r: T) => r.object, { render: (r: T) => <><NameLink id={r.object} refs={d.refs} label={r.object.split(".").pop()} />{r.sensitive && <span className="ae-sens-dot" title="sensitive" />}</>, wrap: "wrap" }),
          col("p", "Policy", (r: T) => r.policies.join(", "), { render: (r: T) => r.policies.map((x) => <div key={x} className="ae-mono" title={x}>{x.split(".").pop()}</div>), wrap: "wrap" }),
          col("a", "Every row", (r: T) => (r.known ? roles(r.all_rows) || "no role" : "unknown"), { wrap: "wrap", help: "Roles the policy text lets see every row",
            render: (r: T) => (r.known ? roles(r.all_rows) || <span className="ae-muted">no role</span> : <span className="ae-muted" title="The policy uses a mapping table, a function or other logic">unknown: open the table</span>) }),
          col("f", "Some rows", (r: T) => (r.known ? roles(r.some_rows) : "unknown"), { wrap: "wrap", help: "Roles the policy text lets see rows matching a condition; other readers see none",
            render: (r: T) => (r.known ? roles(r.some_rows) || <span className="ae-muted">none</span> : <span className="ae-muted">unknown</span>) }),
          col("r", "Read by", (r: T) => r.readers, { num: true })]} />
      {!d.row_list.length && q && <p className="ae-muted">No table or policy matches “{q}”.</p>}
    </Card>
  );
}
