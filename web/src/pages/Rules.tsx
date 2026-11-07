import { useState } from "react";
import { download, useApi } from "../api/client";
import type { AdminPerson, Refs, RulesPage } from "../api/types";
import { Banner, Card, DataTable, FindingList, PathText, Tabs } from "../components";
import { apiParams, useApp, useOpen } from "../ctx";
import { col, Head, Load, NameLink } from "./common";
import { RisksTab, RuleList } from "./Risks";
import { changeOfPath, WhatIfButton } from "./Whatif";


export function RulesPageView() {
  const c = useApp();
  const s = useApi<RulesPage>("rules", apiParams(c));
  const [tab, setTab] = useState(c.params.part ?? "findings"); // part=: an old sub-tab, linkable
  const o = useOpen(s.data?.refs);
  type Rule = (typeof c.meta.rules)[number];
  const show = c.params.show === "fixes" || c.params.show === "list" ? c.params.show : "checks"; // the old page first
  return (
    <>
      <Head title="Risks & fixes" sub={c.view === "mine" ? "The rules run on your own slice of the data." : "Checks over the whole account."}
        right={<button className="ae-btn" onClick={() => download("rules.csv", apiParams(c), "findings.csv")}>Download CSV</button>} />
      <Load s={s}>{(d) => {
        const scope = [d.filters.rule && `rule ${d.filters.rule}`, d.filters.grantee && d.filters.grantee].filter(Boolean);
        return (
          <>
            {d.rows_unknown.length > 0 && <Banner tone="warn" title="Row policies could not be read" lines={[`Rows are unknown for ${d.rows_unknown.slice(0, 6).join(", ")}${d.rows_unknown.length > 6 ? " and more" : ""}.`]} />}
            <Tabs active={show} onChange={(k) => c.set({ show: k === "checks" ? null : k })} tabs={[
              { key: "checks", label: "Rule checks", count: d.total },
              { key: "fixes", label: "Risks & change plan" },
              { key: "list", label: "Rules", count: c.meta.rules.length },
            ]} />
            {scope.length > 0 && show !== "checks" && (
              <div className="ae-graph-open">
                Showing
                {d.filters.rule && <button className="ae-chip ae-chip-plain" onClick={() => c.set({ rule: null })}>rule {d.filters.rule} ×</button>}
                {d.filters.grantee && <button className="ae-chip ae-chip-plain" onClick={() => c.set({ grantee: null })}>{d.filters.grantee} ×</button>}
              </div>
            )}
            {show === "fixes" && <RisksTab key={scope.join()} d={d} />}
            {show === "list" && <RuleList d={d} />}
            {show === "checks" && <>
            <Tabs active={tab} onChange={setTab} tabs={[
              { key: "findings", label: "Findings", count: d.total },
              { key: "admins", label: "Admin holders", count: d.admins.length, tone: d.admins.length ? "bad" : null },
              { key: "rules", label: "Rules", count: c.meta.rules.length },
            ]} />
            {tab === "findings" && (
              <Card>
                {scope.length > 0 && (
                  <div className="ae-graph-open">
                    Showing
                    {d.filters.rule && <button className="ae-chip ae-chip-plain" onClick={() => c.set({ rule: null })}>rule {d.filters.rule} ×</button>}
                    {d.filters.grantee && <button className="ae-chip ae-chip-plain" onClick={() => c.set({ grantee: null })}>{d.filters.grantee} ×</button>}
                  </div>
                )}
                <FindingList key={scope.join()} list={d.findings} kinds={d.refs.kinds} onOpen={o.open} csvName="findings"
                  whatIf={(p) => { const ch = changeOfPath(p, d.refs.kinds); return ch && <WhatIfButton ch={[ch]} />; }} />
                <p className="ae-muted">{d.counts.Passing} of {c.meta.rules.length} rules pass.</p>
              </Card>
            )}
            {tab === "admins" && (
              <Card title="People with admin roles or account privileges" scroll
                right={<button className="ae-btn" onClick={() => c.nav("object", { preset: "admin" })}>Open as Who has access</button>}>
                <AdminTable admins={d.admins} refs={d.refs} />
              </Card>
            )}
            {tab === "rules" && (
              <Card title="What each rule checks">
                <DataTable csv="rules.csv" rows={c.meta.rules} maxHeight={640}
                  onRowClick={(r: Rule) => { c.set({ rule: r.num }); setTab("findings"); }}
                  columns={[col("n", "Rule", (r: Rule) => Number(r.num), { num: true, width: 50 }),
                    col("s", "Severity", (r: Rule) => r.severity, { wrap: "nowrap", render: (r: Rule) => <span className={`ae-sevpill ae-sev-${r.severity}`}>{r.severity}</span> }),
                    col("t", "Check", (r: Rule) => r.title, { wrap: "wrap" }), col("a", "Area", (r: Rule) => r.area, { wrap: "nowrap" }),
                    col("f", "Found", (r: Rule) => d.per_rule[r.num] ?? 0, { num: true }),
                    col("m", "Meaning", (r: Rule) => r.meaning, { wrap: "wrap" }), col("x", "Fix", (r: Rule) => r.fix, { wrap: "wrap" })]} />
              </Card>
            )}
            </>}
          </>
        );
      }}</Load>
    </>
  );
}

/** Users with an admin role or an account privilege, with their shortest path (Rule checks, Admin holders preset). */
export function AdminTable({ admins, refs }: { admins: AdminPerson[]; refs: Refs }) {
  const o = useOpen(refs);
  return (
    <DataTable csv="admin_people.csv" rows={admins} rowTone={() => "bad"}
      columns={[
        col("u", "User", (r: AdminPerson) => r.user, { wrap: "nowrap", render: (r: AdminPerson) => <NameLink id={r.user} refs={refs} /> }),
        col("t", "Type", (r: AdminPerson) => (r.service ? "service" : "person"), { wrap: "nowrap" }),
        col("s", "Status", (r: AdminPerson) => r.status, { wrap: "nowrap" }),
        col("r", "Admin roles", (r: AdminPerson) => r.roles.join(", "), { wrap: "wrap" }),
        col("a", "Account privileges", (r: AdminPerson) => r.account.join(", "), { wrap: "wrap" }),
        col("l", "Last login", (r: AdminPerson) => r.last_login ?? "never", { wrap: "nowrap" }),
        col("p", "Path", (r: AdminPerson) => r.paths.map((p) => p.join(" > ")).join(" | "), { wrap: "nowrap",
          render: (r: AdminPerson) => <PathText path={r.paths[0] ?? []} more={r.paths.slice(1)} kinds={refs.kinds} onOpen={o.open} /> }),
      ]} />
  );
}
