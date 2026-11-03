import { qs, useApi } from "../api/client";
import type { ReviewPage, ReviewRow } from "../api/types";
import { Banner, Card, DataTable, KpiRow } from "../components";
import { apiParams, useApp } from "../ctx";
import { col, Controls, Head, Load, NameLink, pathCol, Sel, Tog } from "./common";

export function ReviewPageView() {
  const c = useApp();
  const s = useApi<ReviewPage>(c.view === "mine" ? null : "review", apiParams(c));
  if (c.view === "mine") return <><Head title="Access review" /><Banner tone="info" title="Shared snapshot only" lines={["The review lists every user of an object, so it needs the shared snapshot."]} /></>;
  const q = (extra: Record<string, string | undefined> = {}) => qs({ ...apiParams(c), ...extra });
  return (
    <>
      <Head title="Access review" sub="Who can reach what, one row per user and object, ready for sign-off."
        right={<a className="ae-btn" href={`/api/review.csv${q()}`}>Download CSV (every row, with reviewer columns)</a>} />
      <Load s={s}>{(d) => {
        const f = d.filters, k = d.kpis;
        const opt = (xs: string[], all: string): [string, string][] => [["", all], ...xs.map((x): [string, string] => [x, x])];
        return (
          <>
            <Controls>
              <Sel label="Database" value={f.db} onPick={(v) => c.set({ db: v, schema: null, object: null })} options={[["*", "All databases"], ...f.dbs.map((x): [string, string] => [x, x])]} />
              <Sel label="Schema" value={f.schema} onPick={(v) => c.set({ schema: v, object: null })} options={opt(f.schemas, "All schemas")} />
              <Sel label="Object" value={f.object} onPick={(v) => c.set({ object: v })} options={opt(f.objects, "All objects")} />
              <Tog label="Active users only" on={f.active} onPick={(v) => c.set({ active: v ? "1" : null })} />
              <Tog label="Hide USAGE rows" on={f.hideusage} onPick={(v) => c.set({ hideusage: v ? null : "0" })} help="Screen only: the CSV always has every row" />
            </Controls>
            <KpiRow items={[
              { label: "Objects", value: k.objects }, { label: "Users", value: k.users },
              { label: "Not active", value: k.not_active, tone: k.not_active ? "warn" : null },
              { label: "Rows", value: k.rows, caption: k.hidden_usage ? `${k.hidden_usage} USAGE rows hidden` : undefined },
              { label: "Admin rows", value: k.admin_rows, tone: k.admin_rows ? "bad" : null },
              { label: "Sensitive objects", value: k.sensitive, tone: k.sensitive ? "warn" : null },
            ]} />
            <Card title="Access" scroll>
              <DataTable csv={`access_review_${f.db === "*" ? "ALL" : f.db}.csv`} rows={d.rows} limit={400} maxHeight={640}
                rowTone={(r: ReviewRow) => (r.admin ? "bad" : r.status !== "active" ? "warn" : null)}
                columns={[
                  col("o", "Object", (r: ReviewRow) => `${r.database}.${r.schema}.${r.object}`, { wrap: "wrap", render: (r: ReviewRow) => (
                    <NameLink id={`${r.database}.${r.schema}.${r.object}`} refs={d.refs} label={r.object} />) }),
                  col("ty", "Type", (r: ReviewRow) => r.type), col("db", "Schema", (r: ReviewRow) => `${r.database}.${r.schema}`),
                  col("u", "User", (r: ReviewRow) => r.user, { render: (r: ReviewRow) => <NameLink id={r.user} refs={d.refs} /> }),
                  col("ut", "Type", (r: ReviewRow) => r.user_type), col("s", "Status", (r: ReviewRow) => r.status),
                  col("l", "Last login", (r: ReviewRow) => r.last_login ?? "never"),
                  col("p", "Privileges", (r: ReviewRow) => r.privileges.join(", "), { wrap: "wrap" }),
                  col("se", "Sensitive", (r: ReviewRow) => r.sensitive.join(", "), { wrap: "truncate" }),
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
