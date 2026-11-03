import { useState } from "react";
import { qs, useApi } from "../api/client";
import type { AdminPerson, FindingRow, RulesPage } from "../api/types";
import { Banner, Card, Chips, DataTable, KpiRow, PathText } from "../components";
import { apiParams, useApp, useOpen } from "../ctx";
import { col, Controls, Head, Load, NameLink, Sel } from "./common";

const TONE = { High: "bad", Medium: "warn", Low: null } as const;

function Detail({ f, d }: { f: FindingRow; d: RulesPage }) {
  const o = useOpen(d.refs);
  return (
    <div className="ae-detail">
      <p>{f.why}</p>
      {f.detail && <p className="ae-muted">{f.detail}{f.more > 0 ? ` (and ${f.more} more)` : ""}</p>}
      {f.paths.map((p, i) => <div key={i}><PathText path={p} kinds={d.refs.kinds} onOpen={o.open} /></div>)}
      {f.impact && <p><strong>If fixed:</strong> {f.impact}</p>}
      {f.same_fix && <p className="ae-muted">{f.same_fix}</p>}
      {(f.iac || f.sql) && <p className="ae-muted">Text to copy into your infrastructure as code. This app never runs it.</p>}
      {f.iac && <pre className="ae-code">{f.iac}</pre>}
      {f.sql && <pre className="ae-code">{f.sql}</pre>}
    </div>
  );
}

export function RulesPageView() {
  const c = useApp();
  const s = useApi<RulesPage>("rules", apiParams(c));
  const [open, setOpen] = useState<string | null>(null);
  return (
    <>
      <Head title="Rule checks" sub={c.view === "mine" ? "The rules run on your own slice of the data." : "Checks over the whole account."}
        right={<a className="ae-btn" href={`/api/rules.csv${qs({ ...apiParams(c) })}`}>Download CSV</a>} />
      <Load s={s}>{(d) => (
        <>
          <KpiRow items={[
            { label: "High", value: d.counts.High, tone: d.counts.High ? "bad" : null },
            { label: "Medium", value: d.counts.Medium, tone: d.counts.Medium ? "warn" : null },
            { label: "Low", value: d.counts.Low }, { label: "Rules passing", value: d.counts.Passing, tone: "ok" },
          ]} />
          {d.rows_unknown.length > 0 && <Banner tone="warn" title="Row policies could not be read" lines={[`Rows are unknown for ${d.rows_unknown.slice(0, 6).join(", ")}${d.rows_unknown.length > 6 ? " and more" : ""}.`]} />}
          <Controls>
            <Sel label="Severity" value={d.filters.sev} onPick={(v) => c.set({ sev: v })} options={[["", "All"], ["High", "High"], ["Medium", "Medium"], ["Low", "Low"], ["Passing", "Passing rules"]]} />
            <Sel label="Rule" value={d.filters.rule} onPick={(v) => c.set({ rule: v })}
              options={[["", "All rules"], ...c.meta.rules.map((r): [string, string] => [r.num, `${r.num} · ${r.title}${d.per_rule[r.num] ? ` (${d.per_rule[r.num]})` : ""}`])]} />
            {d.filters.grantee && <button className="ae-chip ae-chip-plain" onClick={() => c.set({ grantee: null })}>grantee {d.filters.grantee} ×</button>}
          </Controls>
          <Card title="Findings" sub={`${d.findings.length} shown of ${d.total}. Click a row for the explanation and the fix.`} scroll>
            <DataTable csv={null} rows={d.findings} maxHeight={640} rowTone={(f: FindingRow) => TONE[f.severity]}
              onRowClick={(f: FindingRow) => setOpen(open === f.num + f.title + f.grantees[0]?.id ? null : f.num + f.title + f.grantees[0]?.id)}
              columns={[
                col("n", "Rule", (f: FindingRow) => Number(f.num), { num: true, width: 56 }),
                col("s", "Severity", (f: FindingRow) => f.severity, { width: 80 }),
                col("t", "Finding", (f: FindingRow) => f.title, { wrap: "wrap", width: 260, render: (f: FindingRow) => (
                  <>{f.title}{open === f.num + f.title + f.grantees[0]?.id && <Detail f={f} d={d} />}</>) }),
                col("g", "Who", (f: FindingRow) => f.grantees.map((g) => g.id).join(" "), { wrap: "wrap", render: (f: FindingRow) => (
                  <Chips max={4} items={f.grantees.map((g) => ({ id: g.id, kind: g.kind }))} onClick={(ch) => c.set({ grantee: ch.id })} />) }),
                col("i", "Impact", (f: FindingRow) => f.impact, { wrap: "wrap" }),
              ]} />
          </Card>
          {d.admins.length > 0 && (
            <Card title="People with admin roles or account privileges" scroll>
              <DataTable csv="admin_people.csv" rows={d.admins} rowTone={() => "bad"}
                columns={[
                  col("u", "User", (r: AdminPerson) => r.user, { render: (r: AdminPerson) => <NameLink id={r.user} refs={d.refs} /> }),
                  col("t", "Type", (r: AdminPerson) => (r.service ? "service" : "person")), col("s", "Status", (r: AdminPerson) => r.status),
                  col("r", "Admin roles", (r: AdminPerson) => r.roles.join(", "), { wrap: "wrap" }),
                  col("a", "Account privileges", (r: AdminPerson) => r.account.join(", "), { wrap: "wrap" }),
                  col("l", "Last login", (r: AdminPerson) => r.last_login ?? "never"),
                  col("p", "Path", (r: AdminPerson) => r.paths.map((p) => p.join(" > ")).join(" | "), { wrap: "wrap", width: 360,
                    render: (r: AdminPerson) => <>{r.paths.slice(0, 3).map((p, i) => <div key={i}><PathText path={p} kinds={d.refs.kinds} /></div>)}</> }),
                ]} />
            </Card>
          )}
          <Card title="What each rule checks" sub="Rule catalogue">
            <DataTable csv="rules.csv" filter rows={c.meta.rules} maxHeight={420}
              columns={[col("n", "Rule", (r: (typeof c.meta.rules)[number]) => Number(r.num), { num: true }), col("s", "Severity", (r: (typeof c.meta.rules)[number]) => r.severity),
                col("t", "Check", (r: (typeof c.meta.rules)[number]) => r.title, { wrap: "wrap" }), col("a", "Area", (r: (typeof c.meta.rules)[number]) => r.area),
                col("m", "Meaning", (r: (typeof c.meta.rules)[number]) => r.meaning, { wrap: "wrap" }), col("f", "Fix", (r: (typeof c.meta.rules)[number]) => r.fix, { wrap: "wrap" })]} />
          </Card>
        </>
      )}</Load>
    </>
  );
}
