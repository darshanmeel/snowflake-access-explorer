// Screen 5, Risks & fixes: severity tiles as filters, findings by rule / person / object, each fix into the change plan
// (a simulation through access.what_if; its text is never run). Screen 10, Rules: the rule list by area with On/Off.
// The server groups and counts every finding; a group's findings come one page at a time, a fix text on open.
import { useEffect, useState, type ReactNode } from "react";
import { qs, useApi } from "../api/client";
import type { FindingPage, FindingRow, Refs, RulesPage, Severity, WhatIfPage } from "../api/types";
import { CodeOutput, copyText, EmptyState, FilterChips, MiniBar, Pager, PathText, SEVERITIES } from "../components";
import { useApp, useOpen } from "../ctx";
import { Load } from "./common";
import { changeText, findingKey, inPlan, muted, plan, planTexts, rulesOff, toggleFix, useSaved, visible } from "./changeplan";
import { LoseKeep, LossGroups } from "./Plan";
import { startOf } from "./screens";

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
const people = (n: number) => (n === 1 ? "1 person" : `${n} people`);
export const GROUP_PAGE = 50;

type Items = Pick<RulesPage, "findings" | "findings_total" | "refs">;

/** The findings of one group (group= of the page's rules query), a page at a time. */
export function GroupItems({ q, group, children }: { q: Record<string, string | undefined>; group: string; children: (list: FindingRow[], refs: Refs, open: (id: string) => void) => ReactNode }) {
  const [at, setAt] = useState(0);
  const s = useApi<Items>("rules", { ...q, group, offset: String(at * GROUP_PAGE), limit: String(GROUP_PAGE) });
  const o = useOpen(s.data?.refs); // the page's own refs: its names may not be in the groups answer
  return (
    <Load s={s}>{(d) => (
      <>
        {children(d.findings, d.refs, o.open)}
        {d.findings_total > GROUP_PAGE && <Pager at={at} size={GROUP_PAGE} total={d.findings_total} onPage={setAt} />}
      </>
    )}</Load>
  );
}

function CopyCode({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="ae-code-row"><pre className="ae-code">{text}</pre>
      <button type="button" className="ae-btn ae-btn-s" onClick={() => copyText(text).then((ok) => { setDone(ok); setTimeout(() => setDone(false), 1200); })}>{done ? "Copied" : "Copy"}</button>
    </div>
  );
}

/** An opened finding's fix (/api/finding): its paths, the infrastructure-as-code text and SQL. */
export function FindingFix({ id, view, whatIf }: { id: number; view: string; whatIf?: (path: string[], kinds: Record<string, string>) => ReactNode }) {
  const s = useApi<FindingPage>("finding", { id: String(id), view });
  const o = useOpen(s.data?.refs);
  return (
    <Load s={s}>{({ finding: f, refs }) => (
      <div className="ae-fd-panel">
        {f.paths.map((p, i) => <div key={i} className="ae-fd-path"><PathText path={p} kinds={refs.kinds} onOpen={o.open} />{whatIf?.(p, refs.kinds)}</div>)}
        {f.same_fix && <p className="ae-muted">Same fix as {f.same_fix}.</p>}
        {(f.iac || f.sql) && <p className="ae-muted">Text for your infrastructure as code. This app never runs it.</p>}
        {f.iac && <CopyCode text={f.iac} />}
        {f.sql && <CopyCode text={f.sql} />}
      </div>
    )}</Load>
  );
}

function Chain({ f, onOpen }: { f: FindingRow; onOpen: (id: string) => void }) {
  const p = f.paths[0] ?? [f.grantee];
  const shown = p.length > 4 ? [p[0], p[1], "…", p[p.length - 1]] : p;
  return (
    <span className="ae-pathchips">
      {shown.map((x, i) => (
        <span key={i} className="ae-chainstep">
          {i > 0 && <span className="ae-sep" aria-hidden>›</span>}
          {x === "…" ? <span className="ae-more">{p.length - 3} more</span>
            : <button type="button" className={`ae-pchip${i === 0 ? ` ae-pchip-${f.kind}` : ""}`} onClick={() => onOpen(x)} title={x}>{x.replace(/ \(user\)$/, "")}</button>}
        </span>
      ))}
    </span>
  );
}

function FixLine({ f, rule, onOpen, note }: { f: FindingRow; rule?: boolean; onOpen: (id: string) => void; note?: string }) {
  const c = useApp();
  const list = useSaved(plan);
  const [fix, setFix] = useState(false);
  const on = inPlan(list, f.changes);
  return (
    <div className="ae-rfix">
      <div className="ae-rfix-main">
        <div className="ae-rfix-line">
          {rule && <span className={`ae-sevpill ae-sev-${f.severity}`}>#{f.num}</span>}
          <Chain f={f} onOpen={onOpen} />
          <span className="ae-rfix-what">{f.what}</span>
        </div>
        <div className="ae-muted">{rule && `${f.title} · `}{f.impact?.text ?? (f.people_total ? `Reaches ${people(f.people_total)}` : "")}</div>
        {!f.changes.length && f.fix && <button type="button" className="ae-link" aria-expanded={fix} onClick={() => setFix(!fix)}>{fix ? "Hide fix" : "Show fix"}</button>}
        {fix && <FindingFix id={f.id} view={c.view} />}
        {note && <div className="ae-muted">Muted: {note} <button type="button" className="ae-link" onClick={() => { const m = { ...muted.get() }; delete m[findingKey(f)]; muted.set(m); }}>Unmute</button></div>}
      </div>
      {f.changes.length > 0
        ? <button type="button" className={`ae-btn ae-rfix-btn${on ? " on" : ""}`} aria-pressed={on} onClick={() => plan.set(toggleFix(plan.get(), f.changes))}>{on ? "In plan ✓" : "Add fix to plan"}</button>
        : <span className="ae-muted ae-rfix-btn" title="The fix is not a revoke: apply its text">No grant to revoke</span>}
    </div>
  );
}

function Mute({ items }: { items: FindingRow[] }) {
  const [open, setOpen] = useState(false);
  const [why, setWhy] = useState("");
  if (!items.length) return null;
  if (!open) return <button type="button" className="ae-link" onClick={() => setOpen(true)}>Mute with a reason</button>;
  return (
    <span className="ae-mute">
      <input className="ae-input" placeholder="Why it is accepted" value={why} onChange={(e) => setWhy(e.target.value)} aria-label="Reason" />
      <button type="button" className="ae-btn" disabled={!why.trim()} onClick={() => {
        muted.set({ ...muted.get(), ...Object.fromEntries(items.map((f) => [findingKey(f), why.trim()])) });
        setOpen(false);
      }}>Mute {plural(items.length, "finding")}{items.length > 1 ? " on this page" : ""}</button>
      <button type="button" className="ae-link" onClick={() => setOpen(false)}>Cancel</button>
      <span className="ae-muted">saved in this browser</span>
    </span>
  );
}

/** One group: a bar on a square-root scale, so thousands next to a few still shows both (the number is printed);
 * sevs: the bar split by severity (By person: which kind of findings, not only how many). */
function Row({ head, count, n, max, sevs, open, onPick, children }: {
  head: React.ReactNode; count: number; n: number; max: number; sevs?: Partial<Record<string, number>>; open: boolean; onPick: () => void; children: React.ReactNode;
}) {
  const w = max ? Math.round((100 * Math.sqrt(n)) / Math.sqrt(max)) : 0;
  return (
    <div className={`ae-rrow${open ? " open" : ""}`}>
      <button type="button" className="ae-rrow-head" aria-expanded={open} onClick={onPick}>
        <span className="ae-rrow-name">{head}</span>
        <span className="ae-rrow-n">{count}</span>
        <span className="ae-rrow-bar">
          <span className="ae-sbar" title={sevs ? SEVERITIES.filter((s) => sevs[s]).map((s) => `${s} ${sevs[s]}`).join(" · ") : undefined}>
            <span style={{ width: `${w}%` }}>
              {sevs ? SEVERITIES.filter((s) => sevs[s]).map((s) => <span key={s} className={`ae-bar-${s.toLowerCase()}`} style={{ flex: sevs[s] }} />)
                : <span className="ae-bar-high" style={{ flex: 1 }} />}
            </span>
          </span><b>{n}</b>
        </span>
      </button>
      {open && <div className="ae-rrow-body">{children}</div>}
    </div>
  );
}

/** " 3 rules skipped: skipped (HIERARCHY=0)." for the rules that did not run, else "". */
export function skipNote(skipped: Record<string, string>) {
  const why = [...new Set(Object.values(skipped))];
  return why.length ? ` ${plural(Object.keys(skipped).length, "rule")} skipped: ${why.join(", ")}.` : "";
}

/** "first 200 of 5000 groups" when the server sent only the first ones. */
export const firstOf = (d: RulesPage, what: string) =>
  d.groups_total > d.groups.length ? <p className="ae-muted">First {d.groups.length} of {d.groups_total} {what}, most findings first. Search or filter to narrow them.</p> : null;

/** Risks & change plan. d answers q (rulesQuery: by, sev, off); all shows the findings of rules turned off and muted. */
export function RisksTab({ d, q, all, setAll }: { d: RulesPage; q: Record<string, string | undefined>; all: boolean; setAll: (v: boolean) => void }) {
  const c = useApp();
  const o = useOpen(d.refs);
  const mute = useSaved(muted);
  const [open, setOpen] = useState<string | null>(c.params.rule ?? null);
  const nMuted = Object.keys(mute).length;
  const sev = d.filters.sev;
  const by = d.filters.by;
  const rules = c.meta.rules;
  const pass = rules.filter((r) => !d.per_rule[r.num] && !d.skipped[r.num]).length;
  const top = (d.counts.Critical ?? 0) + d.counts.High; // findings to act on: Critical and High
  const topRules = new Set(d.groups.filter((g) => by === "rule" && (g.sevs?.Critical || g.sevs?.High)).map((g) => g.key)).size;
  const info = (num: string) => rules.find((r) => r.num === num);
  // per person the bar is that person's findings (counted over rules); else the people the findings reach
  const groups = d.groups.map((g) => ({ ...g, count: by === "person" ? g.rules : g.findings, n: (by === "person" ? g.findings : g.people) ?? 0 }));
  const max = Math.max(1, ...groups.map((g) => g.n));
  const graph = (f: FindingRow) => c.nav("graph", Object.fromEntries(Object.entries(startOf(f.kind, f.grantee)).filter(([, x]) => x)) as Record<string, string>);
  const pick = (k: string) => setOpen(open === k ? null : k);
  return (
    <>
      <div className="ae-headrow">
        <p className="ae-answer">
          {plural(rules.length - Object.keys(d.skipped).length, "rule")} checked, {pass} pass.{skipNote(d.skipped)} {top > 0 && <b className="ae-bad">{plural(top, "critical or high finding")}</b>}
          {top > 0 && (topRules ? ` across ${plural(topRules, "rule")}.` : ".")} Fixes go into a plan you can test before touching Snowflake.
        </p>
        <FilterChips label="Group findings by" value={by} onPick={(k) => { c.set({ by: k === "rule" ? null : k }); setOpen(null); }}
          items={[{ key: "rule", label: "By rule" }, { key: "person", label: "By person" }, { key: "object", label: "By object" }, { key: "grid", label: "Heat grid" }]} />
      </div>
      <div className="ae-tiles">
        {SEVERITIES.map((s) => (
          <button type="button" key={s} aria-pressed={sev === s} className={`ae-tile${sev === s ? " on" : ""}${s === "Critical" || s === "High" ? " ae-tile-bad" : s === "Medium" ? " ae-tile-warn" : ""}`}
            onClick={() => { c.set({ sev: sev === s ? "all" : s }); setOpen(null); }} disabled={!d.sev_counts[s]}>
            <span className="ae-tile-l">{s}</span><span className="ae-tile-v">{d.sev_counts[s] ?? 0}</span>
          </button>
        ))}
        <button type="button" className={`ae-tile${d.admins_total ? " ae-tile-bad" : ""}`} onClick={() => c.nav("object", { preset: "admin" })}>
          <span className="ae-tile-l">Admin holders</span><span className="ae-tile-v">{d.admins_total}</span><span className="ae-muted ae-tile-c">Who has access, admin preset</span>
        </button>
      </div>
      {(d.hidden_off > 0 || nMuted > 0 || all) && (
        <p className="ae-muted">
          {[d.hidden_off > 0 && `${plural(d.hidden_off, "finding")} of rules turned off`, nMuted > 0 && `${nMuted} muted`].filter(Boolean).join(" and ")} {all ? "shown" : "hidden"} (saved in this browser).{" "}
          <button type="button" className="ae-link" onClick={() => setAll(!all)}>{all ? "Hide them" : "Show them"}</button>
        </p>
      )}
      {by === "grid" ? <HeatGrid d={d} onRule={(num) => { c.set({ by: null }); setOpen(num); }} onOpen={o.open} /> : (
      <div className="ae-whogrid">
        <section className="ae-rlist" aria-label="Findings">
          <div className="ae-rrow-h">
            <span>{by === "rule" ? `${sev || "All"} rules, most people affected first` : by === "person" ? "People, most findings first" : "Objects, most findings first"}</span>
            {by === "person" ? <><span>Rules</span><span>Findings</span></> : <><span>Findings</span><span>People affected</span></>}
          </div>
          {groups.map((g) => {
            const r = info(g.key);
            const head = by === "rule" ? <><span className="ae-rrow-num">#{g.key}</span>{r?.title ?? g.title}</>
              : <span className="ae-mono">{g.key || (by === "person" ? "No person affected" : "Not about one object")}</span>;
            return (
              <Row key={g.key} head={head} count={g.count} n={g.n} max={max} sevs={by === "person" ? g.sevs : undefined} open={open === g.key} onPick={() => pick(g.key)}>
                {by === "rule" && r && <p className="ae-rwhy">{r.why || r.meaning}</p>}
                <GroupItems key={qs(q)} q={q} group={g.key}>{(items, _r, open) => {
                  const v = visible(items, [], all ? {} : mute);
                  return (
                    <>
                      {v.shown.map((f) => <FixLine key={f.id} f={f} rule={by !== "rule"} onOpen={open} note={all ? mute[findingKey(f)] : undefined} />)}
                      {v.muted > 0 && <p className="ae-muted">{v.muted} muted on this page.</p>}
                      <div className="ae-how-links">
                        {items[0] && <button type="button" className="ae-link" onClick={() => graph(items[0])}>See on the graph</button>}
                        {by === "rule" && <button type="button" className="ae-link" onClick={() => c.set({ show: "list", open: g.key, sev: null, by: null })}>Rule settings</button>}
                        {by !== "rule" && g.key && <button type="button" className="ae-link" onClick={() => o.open(g.key)}>Open {g.key}</button>}
                        <Mute items={items.filter((f) => !(findingKey(f) in mute))} />
                      </div>
                    </>
                  );
                }}</GroupItems>
              </Row>
            );
          })}
          {firstOf(d, by === "person" ? "people" : "objects")}
          {!groups.length && <EmptyState title="Nothing here" art={(d.counts.Critical ?? 0) + d.counts.High + d.counts.Medium + d.counts.Low ? "search" : "clear"}>
            {(d.counts.Critical ?? 0) + d.counts.High + d.counts.Medium + d.counts.Low ? "No finding at this level: its rules are off or the filters leave none." : "Every rule passes."}</EmptyState>}
        </section>
        <PlanPanel />
      </div>)}
    </>
  );
}

const GRID_ROWS = 40;

/** Who breaks which rule: one row per grantee (worst first), one column per rule with a finding, the cell coloured by
 * the rule's severity and showing how many findings. A cell opens that rule's findings; a name opens the grantee. */
export function HeatGrid({ d, onRule, onOpen }: { d: RulesPage; onRule: (num: string) => void; onOpen: (id: string) => void }) {
  const c = useApp();
  const [all, setAll] = useState(false);
  const g = d.grid;
  if (!g || !g.rows.length) return <EmptyState title="Nothing here" art="clear">No finding at this level.</EmptyState>;
  const sevOf = (num: string): Severity => c.meta.rules.find((r) => r.num === num)?.severity ?? "Low";
  const title = (num: string) => c.meta.rules.find((r) => r.num === num)?.title ?? "";
  const shown = all ? g.rows : g.rows.slice(0, GRID_ROWS);
  return (
    <section className="ae-card ae-hgrid-card" aria-label="Findings heat grid">
      <p className="ae-muted">{d.groups_total} grantees × {g.rules.length} rules with a finding. Darker is more severe; the number is how many findings. Click a cell for the rule's findings.</p>
      <div className="ae-hgrid-scroll">
        <table className="ae-hgrid">
          <thead>
            <tr><th scope="col" className="ae-hgrid-who">Grantee</th>
              {g.rules.map((n) => <th key={n} scope="col" title={`#${n} ${title(n)} (${sevOf(n)})`}><span className={`ae-hgrid-rule ae-sev-${sevOf(n)}`}>#{n}</span></th>)}
              <th scope="col">All</th></tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.grantee}>
                <th scope="row" className="ae-hgrid-who"><button type="button" className={`ae-pchip ae-pchip-${r.kind === "object" ? "obj" : r.kind}`} onClick={() => onOpen(r.grantee)} title={r.grantee}>{r.grantee.replace(/ \(user\)$/, "")}</button></th>
                {g.rules.map((x) => {
                  const n = r.counts[x] ?? 0;
                  return <td key={x}>{n > 0 && <button type="button" className={`ae-hgrid-c ae-hc-${sevOf(x)}`} onClick={() => onRule(x)}
                    title={`${r.grantee}: ${n} finding${n === 1 ? "" : "s"} of #${x} ${title(x)}`}>{n}</button>}</td>;
                })}
                <td className="ae-hgrid-n">{r.total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {g.rows.length > GRID_ROWS && <button type="button" className="ae-btn ae-mt" onClick={() => setAll(!all)}>{all ? `Show the first ${GRID_ROWS}` : `Show ${g.rows.length < d.groups_total ? `the first ${g.rows.length}` : `all ${g.rows.length}`}`}</button>}
      {g.rows.length < d.groups_total && all && <p className="ae-muted">First {g.rows.length} of {d.groups_total} grantees, worst first. Search or filter to narrow them.</p>}
      <div className="ae-bar-legend ae-mt">{SEVERITIES.filter((s) => g.rules.some((n) => sevOf(n) === s)).map((s) => <span key={s}><span className={`ae-hgrid-c ae-hc-${s} ae-hgrid-key`} />{s}</span>)}</div>
    </section>
  );
}

/** The change plan, next to the findings: items, impact (access.what_if), who loses what, the text to apply. */
export function PlanPanel() {
  const c = useApp();
  const list = useSaved(plan);
  const s = useApi<WhatIfPage>(list.length ? "whatif" : null, { view: c.view, changes: JSON.stringify(list) });
  return (
    <aside className="ae-plan" id="plan" aria-label="Change plan">
      <div className="ae-plan-head"><h3>Change plan</h3><span className="ae-tag ae-tag-ok">Simulation</span></div>
      <p className="ae-muted">Nothing changes in Snowflake until you apply the text below. The plan is saved in this browser.</p>
      {!list.length && <EmptyState title="No changes yet" art="plan">Add a fix from a finding, or a change such as "revoke a role from a person" on What if, to see who would lose what.</EmptyState>}
      {list.length > 0 && (
        <>
          <ul className="ae-plan-items">
            {list.map((ch) => (
              <li key={changeText(ch)}><span>{changeText(ch)}</span>
                <button type="button" className="ae-link" aria-label="Remove from plan" onClick={() => plan.set(list.filter((x) => x !== ch))}>×</button></li>
            ))}
          </ul>
          <Load s={s}>{(d) => (
            <>
              <div className="ae-plan-tiles">
                <div className={`ae-tile${d.counts.users ? " ae-tile-bad" : ""}`}><span className="ae-tile-l">People lose access</span><span className="ae-tile-v">{d.counts.users}</span></div>
                <div className="ae-tile"><span className="ae-tile-l">Keep it another way</span><span className="ae-tile-v">{d.counts.kept}</span></div>
                <div className="ae-tile"><span className="ae-tile-l">Findings fixed</span><span className="ae-tile-v">{d.counts.fixed}</span></div>
                <div className={`ae-tile${d.counts.new ? " ae-tile-warn" : ""}`}><span className="ae-tile-l">New findings</span><span className="ae-tile-v">{d.counts.new}</span></div>
              </div>
              {d.users.length > 0 && (
                <div>
                  <h4>Who loses what</h4>
                  <LoseKeep users={d.users} />
                  <LossGroups users={d.users} changes={list} refs={d.refs} max={4} />
                </div>
              )}
              <CodeOutput changes={[]} name="change_plan" texts={planTexts(list, d.sql)} />
            </>
          )}</Load>
          <div className="ae-row">
            <button type="button" className="ae-btn ae-btn-primary" onClick={() => c.nav("whatif", { show: "plan" })}>Open full what-if</button>
            <button type="button" className="ae-btn" onClick={() => plan.set([])}>Clear plan</button>
          </div>
        </>
      )}
    </aside>
  );
}

const AREAS = ["Role model", "Read-only and write", "Admin and account", "Tasks, warehouses and objects", "Sensitive data", "Users and hygiene"];

/** Screen 10: every rule by area, severity, findings link and On/Off (this browser only); expand for what / how. */
export function RuleList({ d }: { d: RulesPage }) {
  const c = useApp();
  const off = useSaved(rulesOff);
  const [open, setOpen] = useState<string | null>(c.params.open ?? null);
  const rules = c.meta.rules;
  const areas = [...AREAS.filter((a) => rules.some((r) => r.area === a)), ...[...new Set(rules.map((r) => r.area))].filter((a) => !AREAS.includes(a))];
  const sevs = SEVERITIES.map((s) => [s, rules.filter((r) => r.severity === s).length] as const).filter(([, n]) => n);
  useEffect(() => { if (c.params.area) document.getElementById(`area-${c.params.area}`)?.scrollIntoView({ block: "start" }); }, [c.params.area]);
  const most = Math.max(1, ...areas.map((a) => rules.filter((r) => r.area === a).reduce((n, r) => n + (d.per_rule[r.num] ?? 0), 0)));
  return (
    <>
      <div className="ae-headrow">
        <p className="ae-answer">{plural(rules.length, "check")} in {areas.length} areas, {rules.filter((r) => d.per_rule[r.num]).length} with a finding today. Click a rule to see what it checks and how to fix it.</p>
        <span className="ae-row">{sevs.map(([s, n]) => <span key={s} className={`ae-sevpill ae-sev-${s}`}>{n} {s.toLowerCase()}</span>)}</span>
      </div>
      <p className="ae-muted">On / Off is saved in this browser: it only hides a rule's findings on Risks & fixes. The checks still run{off.length ? `; ${plural(off.length, "rule")} off` : ""}.</p>
      {areas.map((a) => {
        const rs = rules.filter((r) => r.area === a).sort((x, y) => Number(x.num) - Number(y.num));
        return (
          <section key={a} className={`ae-rarea${c.params.area === a ? " on" : ""}`} id={`area-${a}`}>
            <div className="ae-rarea-head"><h3>{a}</h3>
              <MiniBar of={most} text={plural(rs.reduce((n, r) => n + (d.per_rule[r.num] ?? 0), 0), "finding")} parts={SEVERITIES.map((s) => ({
                key: s, label: s, cls: s === "Critical" || s === "High" ? "high" : s.toLowerCase(),
                value: rs.filter((r) => r.severity === s).reduce((n, r) => n + (d.per_rule[r.num] ?? 0), 0) }))} />
              <span className="ae-muted">{plural(rs.length, "rule")}</span></div>
            {rs.map((r) => {
              const on = !off.includes(r.num);
              const n = d.per_rule[r.num] ?? 0;
              return (
                <div key={r.num} className={`ae-rule${on ? "" : " off"}`}>
                  <div className="ae-rule-row">
                    <button type="button" className="ae-rule-name" aria-expanded={open === r.num} onClick={() => setOpen(open === r.num ? null : r.num)}>
                      <span className="ae-rrow-num">#{r.num}</span>{r.title}
                    </button>
                    <span className={`ae-sevpill ae-sev-${r.severity}`} title={r.critical ? `Critical when ${r.critical}` : undefined}>{r.severity}</span>
                    {n ? <button type="button" className="ae-link" onClick={() => c.set({ show: "fixes", rule: r.num, sev: r.critical ? "all" : r.severity, open: null, by: null })}>{plural(n, "finding")}</button>
                      : <span className="ae-muted">{d.skipped[r.num] ?? "passes"}</span>}
                    <label className="ae-toggle"><input type="checkbox" checked={on} onChange={(e) => rulesOff.set(e.target.checked ? off.filter((x) => x !== r.num) : [...off, r.num])} />{on ? "On" : "Off"}</label>
                  </div>
                  {open === r.num && (
                    <div className="ae-rule-body">
                      <div><h4>What it checks</h4><p>{r.meaning || r.why}{r.critical && ` Critical when ${r.critical}.`}</p></div>
                      <div><h4>How to fix</h4><p>{r.fix}</p></div>
                    </div>
                  )}
                </div>
              );
            })}
          </section>
        );
      })}
    </>
  );
}
