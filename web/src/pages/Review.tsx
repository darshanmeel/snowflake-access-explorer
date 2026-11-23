import { useEffect, useState } from "react";
import { download, useApi } from "../api/client";
import type { PrivClass, ReviewPage, ReviewRow } from "../api/types";
import { AccessTag, Banner, Card, DataTable, KpiRow, StatusDot, Tabs, useCsv } from "../components";
import { apiParams, useApp } from "../ctx";
import { col, Controls, Head, Load, NameLink, pathCol, Pick, Sel, Tog } from "./common";
import { ReviewGrid } from "./ReviewGrid";

const RANK = ["use", "read", "manage", "write", "own", "admin"];
const strongest = (cs: PrivClass[]): PrivClass => cs.reduce<PrivClass>((a, c) => (RANK.indexOf(c) > RANK.indexOf(a) ? c : a), cs[0] ?? "use");

export function ReviewPageView() {
  const c = useApp();
  const show = c.params.show === "rows" || (c.params.part && c.params.show !== "grid") ? "old" : "grid"; // the sign-off grid first; part=: an old link to the rows
  if (c.view === "mine") return <><Head title="Review & sign-off" /><Banner tone="info" title="Shared snapshot only" lines={["The review lists every user of an object, so it needs the shared snapshot."]} /></>;
  return (
    <>
      <Head title="Review & sign-off" sub="Who can reach what, ready for sign-off." />
      <Tabs nav active={show} onChange={(k) => c.set(k === "grid" ? { show: null, part: null } : { show: "rows", columns: null, object: null, scope: null })} tabs={[
        { key: "grid", label: "Review grid & sign-off" },
        { key: "old", label: "Rows / CSV" },
      ]} />
      {show === "old" ? <OldReview /> : <ReviewGrid />}
    </>
  );
}

function OldReview() {
  const c = useApp();
  const csvOn = useCsv();
  const [tab, setTab] = useState(c.params.part ?? "sens");
  const [pg, setPg] = useState({ at: 0, size: 50, by: { key: "o", dir: 1 as 1 | -1 } });
  const [typed, setTyped] = useState(""), [q, setQ] = useState("");
  useEffect(() => { const t = setTimeout(() => setQ(typed), 300); return () => clearTimeout(t); }, [typed]);
  const { db, schema, object, active, hideusage } = c.params;
  useEffect(() => setPg((x) => ({ ...x, at: 0 })), [db, schema, object, active, hideusage, q]);
  // the server filters, sorts and pages: a big database has millions of (user, object) rows
  const s = useApi<ReviewPage>("review", { ...apiParams(c), part: tab, q, sort: pg.by.key, dir: String(pg.by.dir),
    offset: String(pg.at * pg.size), limit: String(pg.size) });
  return (
    <>
      <Load s={s}>{(d) => {
        const f = d.filters, k = d.kpis;
        const big = k.csv_rows > d.csv_max;
        const t = d.part;
        const opt = (xs: string[], all: string): [string, string][] => [["", all], ...xs.map((x): [string, string] => [x, x])];
        return (
          <>
            {csvOn && <div className="ae-row ae-right">{big && <span className="ae-muted">Too many rows for one file: pick one database or schema.</span>}
              <button className="ae-btn" disabled={big} onClick={() => download("review.csv", apiParams(c), "access_review.csv")}>Download CSV ({k.csv_rows.toLocaleString()} rows, with reviewer columns)</button></div>}
            <Controls>
              <div className="ae-pick-all">
                <Pick label="Database" value={f.db === "*" ? "" : f.db} what="databases" width={200} onPick={(v) => c.set({ db: v, schema: null, object: null })} />
                {f.db !== "*" && <button type="button" className="ae-link" onClick={() => c.set({ db: "*", schema: null, object: null })}>All databases</button>}
              </div>
              <Sel label="Schema" value={f.schema} onPick={(v) => c.set({ schema: v, object: null })} options={opt(f.schemas, "All schemas")} />
              <Sel label="Object" value={f.object} onPick={(v) => c.set({ object: v })} options={opt(f.objects, "All objects")} />
              <Tog label="Active users only" on={f.active} onPick={(v) => c.set({ active: v ? "1" : null })} />
              <Tog label="Hide USAGE rows" on={f.hideusage} onPick={(v) => c.set({ hideusage: v ? null : "0" })} help="Screen only: the CSV always has every row" />
            </Controls>
            <KpiRow items={[
              { label: "Users", value: k.users, caption: k.hidden_usage ? `${k.hidden_usage} USAGE rows hidden` : undefined },
              { label: "Not active", value: k.not_active, tone: k.not_active ? "warn" : null },
              { label: "Admin rows", value: k.admin_rows, tone: k.admin_rows ? "bad" : null },
            ]} />
            {d.note && <Banner tone="info" title={d.note} />}
            <Tabs nav={2} active={t} onChange={(k) => { setTab(k); setPg((o) => ({ ...o, at: 0 })); }} tabs={[
              { key: "sens", label: "Sensitive", count: d.counts.sens, tone: "warn" },
              { key: "all", label: "All", count: d.counts.all },
            ]} />
            <Card scroll>
              <DataTable key={t} csv={null} rows={d.rows} maxHeight={640}
                paged={{ total: d.total, at: pg.at, size: pg.size, q: typed, by: pg.by,
                  onChange: (x) => { if (x.q !== undefined) setTyped(x.q); setPg((o) => ({ at: x.at, size: x.size ?? o.size, by: x.by ?? o.by })); } }}
                rowTone={(r: ReviewRow) => (r.admin ? "bad" : r.status !== "active" ? "warn" : null)}
                columns={[
                  col("o", "Object", (r: ReviewRow) => `${r.database}.${r.schema}.${r.object}`, { wrap: "nowrap", render: (r: ReviewRow) => (
                    <><NameLink id={`${r.database}.${r.schema}.${r.object}`} refs={d.refs} label={r.object} /> <span className="ae-badge">{r.type.toLowerCase()}</span>
                      {r.sensitive.length > 0 && <span className="ae-sens" title={`Sensitive: ${r.sensitive.join(", ")}`}>●</span>}</>) }),
                  col("db", "Schema", (r: ReviewRow) => `${r.database}.${r.schema}`, { wrap: "nowrap" }),
                  col("u", "User", (r: ReviewRow) => r.user, { wrap: "nowrap", render: (r: ReviewRow) => (
                    <><StatusDot s={r.status} /><NameLink id={r.user} refs={d.refs} /> <span className="ae-badge">{r.user_type.toLowerCase()}</span></>) }),
                  col("l", "Last login", (r: ReviewRow) => r.last_login ?? "never", { wrap: "nowrap" }),
                  col("p", "Access", (r: ReviewRow) => r.privileges.join(", "), { wrap: "nowrap", render: (r: ReviewRow) => (
                    <AccessTag cls={strongest(r.classes)} grants={r.privileges} />) }),
                  col("g", "Granted roles", (r: ReviewRow) => r.granted.join(", "), { wrap: "truncate" }),
                  pathCol<ReviewRow>(d.refs),
                ]} />
            </Card>
          </>
        );
      }}</Load>
    </>
  );
}
