import { useState } from "react";
import { useApi } from "../api/client";
import type { SensitivePage } from "../api/types";
import { Banner, Card, Chips, DataTable, KpiRow, Tabs } from "../components";
import { apiParams, useApp } from "../ctx";
import { Catalog } from "./Catalog";
import { col, Controls, Head, Load, NameLink, pathCol, Sel, Tog } from "./common";

type O = SensitivePage["objects"][number];
type R = SensitivePage["readers"][number];

const WHY: Record<string, string> = {
  mine: "Sensitive data is not shown in My access: it needs the shared snapshot, which reads tags and policies for the whole account.",
  unavailable: "Tags and policies cannot be read with this role, so sensitive data cannot be found.",
  no_tags: "No sensitivity tags are in use, so no object is marked sensitive.",
  none_sensitive: "Tags are in use, but no object carries a sensitive one.",
};

export function SensitivePageView() {
  const c = useApp();
  const s = useApi<SensitivePage>("sensitive", apiParams(c));
  const [part, setPart] = useState(c.params.show === "catalog" ? "catalog" : "objects"); // the old tables first
  return (
    <>
      <Head title="Sensitive data" sub="Objects carrying a sensitive tag, and who can read them."
        right={<div className="ae-row0"><button type="button" className="ae-btn" onClick={() => c.nav("flow", {})}>Data flow</button>
          <button type="button" className="ae-btn" onClick={() => c.nav("review", { show: "grid" })}>Review & sign-off</button></div>} />
      <Load s={s}>{(d) => {
        if (d.state !== "ok") return <Banner tone="info" title="Nothing to show" lines={[WHY[d.state] ?? d.state]} />;
        const k = d.kpis;
        return (
          <>
            <Controls>
              <Sel label="Tag" value={d.filters.tag} onPick={(v) => c.set({ tag: v })} options={[["", "All tags"], ...d.filters.tags.map((t): [string, string] => [t, t])]} />
              <Sel label="Database" value={d.filters.db} onPick={(v) => c.set({ db: v })} options={[["", "All databases"], ...d.filters.dbs.map((t): [string, string] => [t, t])]} />
              <Tog label="People only" on={d.filters.people} onPick={(v) => c.set({ people: v ? "1" : null })} />
            </Controls>
            <KpiRow items={[
              { label: "Sensitive objects", value: k.objects, caption: `${k.columns} columns, ${k.whole} whole-object` },
              { label: "People who can read", value: k.people, caption: `${k.service} service` },
              { label: "Admin readers", value: k.admin, tone: k.admin ? "bad" : null },
              { label: "Disabled readers", value: k.disabled, tone: k.disabled ? "warn" : null },
              { label: "Unmasked columns", value: k.unmasked, tone: k.unmasked ? "bad" : null },
            ]} />
            {k.stale.length > 0 && <Banner tone="warn" title="Disabled or dormant users still hold access" lines={[k.stale.join(", ")]} />}
            <Tabs active={part} onChange={(k) => { setPart(k); c.set({ show: k === "catalog" ? "catalog" : null }); }} tabs={[
              { key: "objects", label: "Sensitive objects", count: d.objects.length },
              { key: "readers", label: "Who can read them", count: d.readers.length },
              { key: "compare", label: "Compare two roles" },
              { key: "catalog", label: "Catalog", count: d.catalog.length },
            ]} />
            {part === "catalog" && <Catalog rows={d.catalog} />}
            {part === "objects" && <Card title="Sensitive objects" scroll>
              <DataTable csv="sensitive_objects.csv" rows={d.objects} limit={300}
                columns={[
                  col("o", "Object", (r: O) => r.object, { render: (r: O) => <NameLink id={r.object} refs={d.refs} />, wrap: "wrap" }),
                  col("t", "Type", (r: O) => r.type),
                  col("g", "Tags", (r: O) => r.tags.map((t) => t.label).join(", "), { render: (r: O) => <Chips items={r.tags.map((t) => ({ id: t.label, title: t.origins.join("; "), tone: "bad" as const }))} />, wrap: "wrap" }),
                  col("c", "Columns", (r: O) => r.cols.join(", "), { wrap: "wrap" }),
                  col("m", "Masked", (r: O) => (r.cols.length ? `${r.masked[0]} of ${r.masked[1]}` : ""), { help: "Columns with a masking policy",
                    render: (r: O) => (r.cols.length && r.masked[0] < r.masked[1] ? <span className="ae-bad">{r.masked[0]} of {r.masked[1]} · not protected</span> : r.cols.length ? `${r.masked[0]} of ${r.masked[1]}` : "") }),
                  col("rp", "Row policy", (r: O) => r.row_policies.join(", "), { wrap: "wrap" }),
                  col("p", "People", (r: O) => r.people.length, { num: true }), col("a", "Admin", (r: O) => r.admin.length, { num: true }),
                  col("ro", "Roles", (r: O) => r.roles.join(", "), { wrap: "truncate" }),
                ]} />
            </Card>}
            {part === "readers" && <Card title="Who can read them" sub="One row per user; the shortest path to a sensitive object" scroll>
              <DataTable csv="sensitive_readers.csv" rows={d.readers} limit={300} rowTone={(r: R) => (r.via_admin ? "bad" : r.status !== "active" ? "warn" : null)}
                columns={[
                  col("u", "User", (r: R) => r.user, { render: (r: R) => <NameLink id={r.user} refs={d.refs} /> }),
                  col("t", "Type", (r: R) => r.type), col("s", "Status", (r: R) => r.status), col("l", "Last login", (r: R) => r.last_login_text),
                  col("ob", "Objects", (r: R) => r.objects.length, { num: true }),
                  col("ro", "Via roles", (r: R) => r.roles.join(", "), { wrap: "truncate" }),
                  pathCol<R>(d.refs),
                ]} />
            </Card>}
            {part === "compare" && <Card title="Compare two roles" sub="What each sees in the sensitive objects">
              <Controls>
                <Sel label="Role A" value={d.compare.a} onPick={(v) => c.set({ a: v })} options={d.compare.roles.map((x): [string, string] => [x, x])} />
                <Sel label="Role B" value={d.compare.b} onPick={(v) => c.set({ b: v })} options={d.compare.roles.map((x): [string, string] => [x, x])} />
              </Controls>
              {d.compare.diff.length > 0 && <Banner tone="warn" title="They differ" lines={d.compare.diff} />}
              <DataTable csv="sensitive_compare.csv" rows={d.compare.rows}
                columns={[col("o", "Object", (r: SensitivePage["compare"]["rows"][number]) => r.object, { wrap: "wrap" }),
                  col("a", d.compare.a, (r: SensitivePage["compare"]["rows"][number]) => r.a ?? "no access", { wrap: "wrap" }),
                  col("b", d.compare.b, (r: SensitivePage["compare"]["rows"][number]) => r.b ?? "no access", { wrap: "wrap" })]} />
            </Card>}
          </>
        );
      }}</Load>
    </>
  );
}
