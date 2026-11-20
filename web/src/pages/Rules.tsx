import { useEffect, useState } from "react";
import { download, qs, useApi } from "../api/client";
import type { AdminPerson, FindingRow, Refs, FindingGroup, RulesPage, StalePerson } from "../api/types";
import { Banner, Card, DataTable, NameList, PathText, SEVERITIES, StackBar, Tabs, useCsv } from "../components";
import { apiParams, useApp, useOpen } from "../ctx";
import { rulesOff, rulesQuery, useSaved } from "./changeplan";
import { col, Head, Load, NameLink } from "./common";
import { PagedTable } from "./paged";
import { FindingFix, firstOf, GROUP_PAGE, GroupItems, RisksTab, RuleList, skipNote } from "./Risks";
import { changeOfPath, WhatIfButton } from "./Whatif";

type Filters = { q: string; area: string; people: boolean };
const NONE: Filters = { q: "", area: "", people: false };
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;

export function RulesPageView() {
  const c = useApp();
  const csvOn = useCsv();
  const off = useSaved(rulesOff);
  const [all, setAll] = useState(false); // Risks & change plan: also the findings of rules turned off
  const [f, setF] = useState(NONE); // Rule checks filters as typed; the search goes to the server after a pause
  const [q0, setQ0] = useState("");
  useEffect(() => { const t = setTimeout(() => setQ0(f.q), 300); return () => clearTimeout(t); }, [f.q]);
  const tab = c.params.part ?? "findings"; // part=: the Rule checks tab, linkable (the side menu opens admins and stale)
  const setTab = (k: string) => c.set({ part: k === "findings" ? null : k, show: null });
  const show = c.params.show === "fixes" || c.params.show === "list" ? c.params.show : "checks"; // the old page first
  const q = rulesQuery(apiParams(c), show, all ? [] : off, show === "checks" ? { ...f, q: q0 } : NONE);
  const s = useApi<RulesPage>("rules", q);
  return (
    <>
      <Head title="Risks & fixes" sub={c.view === "mine" ? "The rules run on your own slice of the data." : "Checks over the whole account."}
        right={csvOn && <button className="ae-btn" onClick={() => download("rules.csv", q, "findings.csv")}>Download CSV{s.data ? ` (${s.data.total.toLocaleString()} rows)` : ""}</button>} />
      <Load s={s}>{(d) => {
        const scope = [d.filters.rule && `rule ${d.filters.rule}`, d.filters.grantee && d.filters.grantee].filter(Boolean);
        const chips = scope.length > 0 && (
          <div className="ae-graph-open">
            Showing
            {d.filters.rule && <button className="ae-chip ae-chip-plain" onClick={() => c.set({ rule: null })}>rule {d.filters.rule} ×</button>}
            {d.filters.grantee && <button className="ae-chip ae-chip-plain" onClick={() => c.set({ grantee: null, of: null })}>{d.filters.grantee}{d.filters.of === "user" && " and its roles"} ×</button>}
          </div>
        );
        const unknown = d.rows_unknown;
        return (
          <>
            {unknown.length > 0 && <Banner tone="warn" title="Row policies could not be read: rows are unknown for">
              <NameList items={unknown} onOpen={(o) => c.nav("object", { name: o })} /></Banner>}
            <Tabs nav active={show} onChange={(k) => c.set({ show: k === "checks" ? null : k })} tabs={[
              { key: "checks", label: "Rule checks", count: Object.values(d.per_rule).reduce((n, x) => n + x, 0) },
              { key: "fixes", label: "Risks & change plan" },
              { key: "list", label: "Rules", count: c.meta.rules.length },
            ]} />
            {show !== "checks" && chips}
            {show === "fixes" && <RisksTab key={scope.join()} d={d} q={q} all={all} setAll={setAll} />}
            {show === "list" && <RuleList d={d} />}
            {show === "checks" && <>
            {/* in the page only: the side menu keeps three levels, and has these two as shortcuts of its own */}
            <Tabs active={tab} onChange={setTab} tabs={[
              { key: "findings", label: "Findings", count: d.total },
              { key: "admins", label: "Admin holders", count: d.admins_total, tone: d.admins_total ? "bad" : null },
              { key: "stale", label: "Dormant & disabled", count: d.stale_total, tone: d.stale_total ? "warn" : null },
            ]} />
            {tab === "findings" && (
              <Card>
                {d.filters.rule ? <RuleHead d={d} /> : chips}
                <FindingGroups key={scope.join()} d={d} q={q} f={f} setF={setF} />
                <p className="ae-muted">{d.counts.Passing} of {c.meta.rules.length} rules pass.{skipNote(d.skipped)}</p>
              </Card>
            )}
            {tab === "admins" && (
              <Card title="People with admin roles or account privileges" scroll
                right={<button className="ae-btn" onClick={() => c.nav("object", { preset: "admin" })}>Who holds each admin role</button>}>
                <AdminTable admins={d.admins} refs={d.refs} total={d.admins_total} />
              </Card>
            )}
            {tab === "stale" && (
              <Card title="Disabled, dormant or never logged in, still holding roles" scroll
                sub={`Rules 8 and 16, each person once. People who can read sensitive data (rule 7) come first. Dormant: no login for ${c.meta.limits.dormant_days} days.`}>
                <StaleTable d={d} />
              </Card>
            )}
            </>}
          </>
        );
      }}</Load>
    </>
  );
}

/** Rule checks > Findings: severity tabs and filters answered by the server, one group per rule (most people
 * affected first); an opened group loads its findings a page at a time, an opened finding its fix. */
function FindingGroups({ d, q, f, setF }: {
  d: RulesPage; q: Record<string, string | undefined>; f: Filters; setF: (f: Filters) => void;
}) {
  const c = useApp();
  const sev = d.filters.sev;
  const all = SEVERITIES.reduce((n, s) => n + (d.sev_counts[s] ?? 0), 0);
  const why = [f.area && `area = ${f.area}`, f.people && "people only", f.q.trim() && `search "${f.q.trim()}"`].filter(Boolean).join(", ");
  if (!all && !why) return null;
  return (
    <div className="ae-findings">
      <Tabs active={sev || "All"} onChange={(s) => c.set({ sev: s === "All" ? "all" : s })}
        tabs={[...SEVERITIES.filter((s) => d.sev_counts[s]).map((s) => ({ key: s, label: s, count: d.sev_counts[s], tone: s === "Medium" ? "warn" as const : s === "Low" ? null : "bad" as const })),
          { key: "All", label: "All", count: all }]} />
      <div className="ae-controls ae-fd-filter">
        {d.areas.length > 1 && (
          <select className="ae-input" value={f.area} onChange={(e) => setF({ ...f, area: e.target.value })} aria-label="Area">
            <option value="">Every area</option>{d.areas.map((a) => <option key={a}>{a}</option>)}
          </select>
        )}
        <input className="ae-input" placeholder="Search findings" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} aria-label="Search findings" />
        <label className="ae-check"><input type="checkbox" checked={f.people} onChange={(e) => setF({ ...f, people: e.target.checked })} /> People affected only</label>
      </div>
      {why && <p className="ae-muted ae-fd-hidden">{plural(d.total, "finding")} match {why}.</p>}
      {d.groups.map((g, i) => <Group key={`${sev}:${g.key}`} g={g} q={q} open={d.groups.length === 1 || (i === 0 && g.findings <= 5)} />)}
      {firstOf(d, d.filters.rule ? "roles and users" : "rules")}
      {!d.groups.length && <p className="ae-muted">Nothing here.</p>}
    </div>
  );
}

/** One rule picked (side menu or the list): what it checks, why, how to fix, its counts; its findings below, one line
 * per role or user. */
function RuleHead({ d }: { d: RulesPage }) {
  const c = useApp();
  const r = c.meta.rules.find((x) => x.num === d.filters.rule);
  if (!r) return null;
  return (
    <div className={`ae-rulehead ae-sev-${r.severity}`}>
      <div className="ae-rulehead-t">
        <span className={`ae-sevpill ae-sev-${r.severity}`}>{r.severity}</span>
        <span className="ae-fg-num">{r.num}</span>
        <h3>{r.title}</h3>
        <button type="button" className="ae-link" onClick={() => c.set({ rule: null, sev: null })}>Every rule</button>
      </div>
      <p>{r.why}{r.critical && <> <span className="ae-sevpill ae-sev-Critical">Critical</span> when {r.critical}.</>}</p>
      <dl className="ae-rulehead-n">
        <div><dt>Findings</dt><dd>{(d.per_rule[r.num] ?? 0).toLocaleString()}</dd></div>
        <div><dt>Roles and users</dt><dd>{d.groups_total.toLocaleString()}</dd></div>
        {r.area && <div><dt>Area</dt><dd>{r.area}</dd></div>}
      </dl>
      {r.meaning && <p><b>What it means.</b> {r.meaning}</p>}
      {r.fix && <p><b>How to fix.</b> {r.fix}</p>}
    </div>
  );
}

function Group({ g, q, open }: { g: FindingGroup; q: Record<string, string | undefined>; open: boolean }) {
  const c = useApp();
  const [on, setOn] = useState(open);
  if (g.said) return (  // one rule, per role or user: what its findings say, not each of them
    <div className={`ae-fg ae-fg-who ae-sev-${g.severity}`}>
      <button className="ae-fg-head" onClick={() => setOn(!on)} aria-expanded={on}>
        <span className="ae-fg-caret">{on ? "▾" : "▸"}</span>
        <span className={`ae-chip ae-chip-${g.kind ?? "plain"}`}>{g.key.replace(/ \(user\)$/, "")}</span>
        <span className="ae-muted">{plural(g.findings, "finding")}{g.objects ? ` on ${plural(g.objects, "object")}` : ""}{g.people ? ` · ${g.people === 1 ? "1 person" : `${g.people} people`} affected` : ""}</span>
        {g.tags?.map((t) => <span key={t} className="ae-tag">{t}</span>)}
      </button>
      {!on && ( // open, the findings below say it
        <ul className="ae-fg-said">
          {g.said.map((x) => <li key={x.text}>{x.findings == null && g.findings > 1 && <span className="ae-muted">e.g. </span>}<span className="ae-mono">{x.text}</span>
            {x.findings != null && g.findings > 1 && <span className="ae-muted"> · {x.findings.toLocaleString()}×</span>}</li>)}
          {(g.said_total ?? 0) > g.said.length && <li className="ae-muted">and {plural(g.said_total! - g.said.length, "other pattern")}</li>}
        </ul>
      )}
      {on && (
        <GroupItems key={qs(q)} q={q} group={g.key}>{(list, refs, open) => (
          <ul className="ae-fd-list">{list.map((f) => <Line key={f.id} f={f} refs={refs} onOpen={open} view={c.view} />)}</ul>
        )}</GroupItems>
      )}
    </div>
  );
  return (
    <div className={`ae-fg ae-sev-${g.severity}`}>
      <button className="ae-fg-head" onClick={() => setOn(!on)} aria-expanded={on}>
        <span className="ae-fg-caret">{on ? "▾" : "▸"}</span>
        <span className="ae-fg-num">{g.key}</span>
        <span className="ae-fg-title">{g.title}</span>
        <span className="ae-muted">{plural(g.findings, "finding")}{g.people ? ` · ${g.people === 1 ? "1 person" : `${g.people} people`}` : ""}</span>
      </button>
      {on && (
        <>
          <p className="ae-muted ae-fg-note">
            {g.findings > GROUP_PAGE ? `${GROUP_PAGE} a page, ` : ""}most people affected first.{" "}
            <button type="button" className="ae-link" onClick={() => c.set({ rule: g.key })}>Per role / user</button>
          </p>
          <GroupItems key={qs(q)} q={q} group={g.key}>{(list, refs, open) => (
            <ul className="ae-fd-list">{list.map((f) => <Line key={f.id} f={f} refs={refs} onOpen={open} view={c.view} />)}</ul>
          )}</GroupItems>
        </>
      )}
    </div>
  );
}

function Line({ f, refs, onOpen, view }: { f: FindingRow; refs: Refs; onOpen: (id: string) => void; view: string }) {
  const [fix, setFix] = useState(false);
  const k = refs.kinds[f.grantee] ?? f.kind;
  return (
    <li className="ae-fd">
      <div className="ae-fd-line">
        <button className={`ae-chip ae-chip-${k}`} onClick={() => onOpen(f.grantee)} title={f.grantee}>{f.grantee.replace(/ \(user\)$/, "")}</button>
        {f.what && <span className="ae-fd-what" title={f.what}>{f.what}</span>}
        {f.impact && <span className={`ae-tag ae-tag-${f.impact.tone}`}>{f.impact.text}</span>}
        {(f.fix || f.paths_total > 0) && <button className="ae-btn ae-btn-s ae-fd-fix" aria-expanded={fix} onClick={() => setFix(!fix)}>{fix ? "Hide fix" : "Fix"}</button>}
      </div>
      {fix && <FindingFix id={f.id} view={view} whatIf={(p, kinds) => { const ch = changeOfPath(p, kinds); return ch && <WhatIfButton ch={[ch]} />; }} />}
    </li>
  );
}

/** Users with an admin role or an account privilege, with their shortest path (Rule checks, Admin holders preset). */
/** Rule checks "Dormant & disabled": status split, then one row per person with what to look at first. */
function StaleTable({ d }: { d: RulesPage }) {
  const c = useApp();
  const n = (st: string) => d.stale_split[st] ?? 0;
  const [q, setQ] = useState(c.params.sq ?? "");
  useEffect(() => { const t = setTimeout(() => q !== (c.params.sq ?? "") && c.set({ sq: q || null, s_offset: null }), 300); return () => clearTimeout(t); }, [q]);
  if (!d.stale_total) return <p className="ae-muted">No disabled, dormant or never-logged-in person holds a role.</p>;
  return (
    <>
      <StackBar parts={[{ key: "disabled", label: "Disabled", value: n("disabled"), cls: "high" }, { key: "dormant", label: "Dormant", value: n("dormant"), cls: "medium" },
        { key: "never", label: "Never logged in", value: n("never"), cls: "low" }]} />
      <div className="ae-row"><input type="search" className="ae-input" aria-label="Find a person" placeholder="Find a person" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="ae-muted">{d.stale_matched < d.stale_total ? `${d.stale_matched.toLocaleString()} of ${d.stale_total.toLocaleString()} people match` : `${d.stale_total.toLocaleString()} people`}</span></div>
      <PagedTable path="rules" at="s_offset" total={d.stale_matched} offset={d.stale_offset} pick={(x: RulesPage) => x.stale} csv="stale_people.csv" rows={d.stale} rowTone={(r: StalePerson) => (r.sensitive ? "bad" : null)} onRowClick={(r: StalePerson) => c.nav("access", { user: r.user })}
        columns={[
          col("u", "User", (r: StalePerson) => r.user, { wrap: "nowrap", render: (r: StalePerson) => <span className="ae-mono">{r.user}</span> }),
          col("s", "Status", (r: StalePerson) => r.status, { wrap: "nowrap" }),
          col("t", "Type", (r: StalePerson) => (r.service ? "service" : "person"), { wrap: "nowrap" }),
          col("r", "Roles held", (r: StalePerson) => r.roles, { num: true }),
          col("f", "Findings", (r: StalePerson) => r.findings, { num: true }),
          col("x", "Reads sensitive", (r: StalePerson) => (r.sensitive ? "yes" : ""), { wrap: "nowrap" }),
          col("l", "Last login", (r: StalePerson) => r.last_login ?? "never", { wrap: "nowrap" }),
        ]} />
    </>
  );
}

/** One item per line, the strong ones in red; over 4 the rest fold into "+N more". */
const TOP_LINES = 3; // a cell lists this many, one per line, then "+N more"

/** A short bulleted list: the strong (red) ones first, TOP_LINES of them, each on one line, the rest behind +N more. */
function Lines({ items, strong }: { items: string[]; strong: string[] }) {
  const [all, setAll] = useState(false);
  const xs = [...items].sort((a, b) => Number(strong.includes(b)) - Number(strong.includes(a)));
  const shown = all ? xs : xs.slice(0, TOP_LINES);
  return (
    <ul className="ae-lines">
      {shown.map((x) => <li key={x} title={x} className={strong.includes(x) ? "ae-tone-bad" : "ae-plain"}>{x}</li>)}
      {xs.length > TOP_LINES && <li className="ae-lines-more"><button type="button" className="ae-link" onClick={() => setAll(!all)}>
        {all ? "show fewer" : `+${xs.length - TOP_LINES} more`}</button></li>}
    </ul>
  );
}

export function AdminTable({ admins, refs, total }: { admins: AdminPerson[]; refs: Refs; total?: number }) {
  const o = useOpen(refs);
  return (
    <>
      {total != null && total > admins.length && <p className="ae-muted">First {admins.length} of {total} people.</p>}
      <DataTable csv="admin_people.csv" rows={admins} rowTone={(r: AdminPerson) => (r.roles.length || r.strong.length ? "bad" : null)}
        columns={[
          col("u", "User", (r: AdminPerson) => r.user, { wrap: "nowrap", render: (r: AdminPerson) => <NameLink id={r.user} refs={refs} /> }),
          col("t", "Type", (r: AdminPerson) => (r.service ? "service" : "person"), { wrap: "nowrap" }),
          col("s", "Status", (r: AdminPerson) => r.status, { wrap: "nowrap" }),
          col("r", "Admin roles", (r: AdminPerson) => r.roles.join(", "), { wrap: "wrap", render: (r: AdminPerson) => <Lines items={r.roles} strong={r.roles} /> }),
          col("a", "Account privileges", (r: AdminPerson) => r.account.join(", "), { wrap: "wrap", render: (r: AdminPerson) => <Lines items={r.account} strong={r.strong} /> }),
          col("l", "Last login", (r: AdminPerson) => r.last_login ?? "never", { wrap: "nowrap" }),
          col("p", "Path", (r: AdminPerson) => r.paths.map((p) => p.join(" > ")).join(" | "), { wrap: "nowrap",
            render: (r: AdminPerson) => <PathText path={r.paths[0] ?? []} more={r.paths.slice(1)} kinds={refs.kinds} onOpen={o.open} /> }),
        ]} />
    </>
  );
}
