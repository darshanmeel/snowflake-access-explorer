// Screen 5, Risks & fixes: severity tiles as filters, findings by rule / person / object, each fix into the change plan
// (a simulation through access.what_if; its text is never run). Screen 10, Rules: the rule list by area with On/Off.
import { useEffect, useState } from "react";
import { useApi } from "../api/client";
import type { Finding, RulesPage, Severity, WhatIfPage } from "../api/types";
import { CodeOutput, CutPath, EmptyState, FilterChips, groupByRule, MiniBar, SEVERITIES, StackBar } from "../components";
import { useApp, useOpen } from "../ctx";
import { Load } from "./common";
import { changeText, findingKey, groupFindings, inPlan, muted, plan, planTexts, rulesOff, toggleFix, useSaved, visible } from "./changeplan";
import { LoseKeep, LossGroups } from "./Plan";
import { startOf } from "./screens";

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
const people = (n: number) => (n === 1 ? "1 person" : `${n} people`);

function Chain({ f, onOpen }: { f: Finding; onOpen: (id: string) => void }) {
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

function FixLine({ f, rule, onOpen, note }: { f: Finding; rule?: boolean; onOpen: (id: string) => void; note?: string }) {
  const list = useSaved(plan);
  const on = inPlan(list, f.changes);
  return (
    <div className="ae-rfix">
      <div className="ae-rfix-main">
        <div className="ae-rfix-line">
          {rule && <span className={`ae-sevpill ae-sev-${f.severity}`}>#{f.num}</span>}
          <Chain f={f} onOpen={onOpen} />
          <span className="ae-rfix-what">{f.what}</span>
        </div>
        <div className="ae-muted">{rule && `${f.title} · `}{f.impact?.text ?? (f.people.length ? `Reaches ${people(f.people.length)}` : "")}</div>
        {!f.changes.length && f.iac && <div className="ae-muted ae-rfix-text">Fix: {f.iac}</div>}
        {note && <div className="ae-muted">Muted: {note} <button type="button" className="ae-link" onClick={() => { const m = { ...muted.get() }; delete m[findingKey(f)]; muted.set(m); }}>Unmute</button></div>}
      </div>
      {f.changes.length > 0
        ? <button type="button" className={`ae-btn ae-rfix-btn${on ? " on" : ""}`} aria-pressed={on} onClick={() => plan.set(toggleFix(plan.get(), f.changes))}>{on ? "In plan ✓" : "Add fix to plan"}</button>
        : <span className="ae-muted ae-rfix-btn" title="The fix is not a revoke: apply the text above">No grant to revoke</span>}
    </div>
  );
}

function Mute({ items }: { items: Finding[] }) {
  const [open, setOpen] = useState(false);
  const [why, setWhy] = useState("");
  if (!open) return <button type="button" className="ae-link" onClick={() => setOpen(true)}>Mute with a reason</button>;
  return (
    <span className="ae-mute">
      <input className="ae-input" placeholder="Why it is accepted" value={why} onChange={(e) => setWhy(e.target.value)} aria-label="Reason" />
      <button type="button" className="ae-btn" disabled={!why.trim()} onClick={() => {
        muted.set({ ...muted.get(), ...Object.fromEntries(items.map((f) => [findingKey(f), why.trim()])) });
        setOpen(false);
      }}>Mute {plural(items.length, "finding")}</button>
      <button type="button" className="ae-link" onClick={() => setOpen(false)}>Cancel</button>
      <span className="ae-muted">saved in this browser</span>
    </span>
  );
}

function Row({ head, count, n, max, open, onPick, children }: {
  head: React.ReactNode; count: number; n: number; max: number; open: boolean; onPick: () => void; children: React.ReactNode;
}) {
  return (
    <div className={`ae-rrow${open ? " open" : ""}`}>
      <button type="button" className="ae-rrow-head" aria-expanded={open} onClick={onPick}>
        <span className="ae-rrow-name">{head}</span>
        <span className="ae-rrow-n">{count}</span>
        <span className="ae-rrow-bar"><span className="ae-gbar"><span style={{ width: `${max ? Math.round((n / max) * 100) : 0}%` }} className="ae-gbar-bad" /></span><b>{n}</b></span>
      </button>
      {open && <div className="ae-rrow-body">{children}</div>}
    </div>
  );
}

export function RisksTab({ d }: { d: RulesPage }) {
  const c = useApp();
  const o = useOpen(d.refs);
  const off = useSaved(rulesOff);
  const mute = useSaved(muted);
  const [all, setAll] = useState(false);
  const [open, setOpen] = useState<string | null>(c.params.rule ?? null);
  const v = visible(d.findings, off, mute);
  const pool = all ? d.findings : v.shown;
  const count = (s: Severity) => pool.filter((f) => f.severity === s).length;
  // no sev= opens the worst severity; sev=all (a click on the active tile) shows every severity
  const sev = (c.params.sev === "all" ? "" : c.params.sev && SEVERITIES.includes(c.params.sev as Severity) ? c.params.sev : SEVERITIES.find((s) => count(s)) ?? "") as Severity | "";
  const list = pool.filter((f) => !sev || f.severity === sev);
  const by = c.params.by === "person" || c.params.by === "object" || c.params.by === "grid" ? c.params.by : "rule";
  const onSev = by === "grid" && !c.params.sev ? "" : sev; // the heat grid opens on every severity
  const rules = c.meta.rules;
  const pass = rules.filter((r) => !d.per_rule[r.num]).length;
  const high = d.findings.filter((f) => f.severity === "High");
  const info = (num: string) => rules.find((r) => r.num === num);
  // per person the bar is that person's findings (counted over rules); else the people the findings reach
  const groups = (by === "rule" || by === "grid" ? groupByRule(list).map((g) => ({ key: g.num, items: g.items, people: g.people })) : groupFindings(list, by))
    .map((g) => ({ ...g, count: by === "person" ? new Set(g.items.map((f) => f.num)).size : g.items.length, n: by === "person" ? g.items.length : g.people }));
  const max = Math.max(1, ...groups.map((g) => g.n));
  const graph = (f: Finding) => c.nav("graph", Object.fromEntries(Object.entries(startOf(f.kind, f.grantee)).filter(([, x]) => x)) as Record<string, string>);
  const pick = (k: string) => setOpen(open === k ? null : k);
  return (
    <>
      <div className="ae-headrow">
        <p className="ae-answer">
          {plural(rules.length, "rule")} checked, {pass} pass. {high.length > 0 && <b className="ae-bad">{plural(high.length, "high finding")}</b>}
          {high.length > 0 && ` across ${plural(new Set(high.map((f) => f.num)).size, "rule")}.`} Fixes go into a plan you can test before touching Snowflake.
        </p>
        <FilterChips label="Group findings by" value={by} onPick={(k) => { c.set({ by: k === "rule" ? null : k }); setOpen(null); }}
          items={[{ key: "rule", label: "By rule" }, { key: "person", label: "By person" }, { key: "object", label: "By object" }, { key: "grid", label: "Heat grid" }]} />
      </div>
      <div className="ae-tiles">
        {SEVERITIES.map((s) => (
          <button type="button" key={s} aria-pressed={onSev === s} className={`ae-tile${onSev === s ? " on" : ""}${s === "Critical" || s === "High" ? " ae-tile-bad" : s === "Medium" ? " ae-tile-warn" : ""}`}
            onClick={() => { c.set({ sev: onSev === s ? "all" : s }); setOpen(null); }} disabled={!count(s)}>
            <span className="ae-tile-l">{s}</span><span className="ae-tile-v">{count(s)}</span>
          </button>
        ))}
        <button type="button" className={`ae-tile${d.admins.length ? " ae-tile-bad" : ""}`} onClick={() => c.nav("object", { preset: "admin" })}>
          <span className="ae-tile-l">Admin holders</span><span className="ae-tile-v">{d.admins.length}</span><span className="ae-muted ae-tile-c">Who has access, admin preset</span>
        </button>
      </div>
      {(v.off > 0 || v.muted > 0) && (
        <p className="ae-muted">
          {[v.off && `${plural(v.off, "finding")} of rules turned off`, v.muted && `${v.muted} muted`].filter(Boolean).join(" and ")} hidden (saved in this browser).{" "}
          <button type="button" className="ae-link" onClick={() => setAll(!all)}>{all ? "Hide them" : "Show them"}</button>
        </p>
      )}
      {by === "grid" ? <HeatGrid list={onSev ? list : pool} onRule={(num) => { c.set({ by: null }); setOpen(num); }} onOpen={o.open} /> : (
      <div className="ae-whogrid">
        <section className="ae-rlist" aria-label="Findings">
          <div className="ae-rrow-h">
            <span>{by === "rule" ? `${sev || "All"} rules, most people affected first` : by === "person" ? "People, most findings first" : "Objects, most findings first"}</span>
            {by === "person" ? <><span>Rules</span><span>Findings</span></> : <><span>Findings</span><span>People affected</span></>}
          </div>
          {groups.map((g) => {
            const r = info(g.key);
            const head = by === "rule" ? <><span className="ae-rrow-num">#{g.key}</span>{r?.title ?? g.items[0].title}</>
              : <span className="ae-mono">{g.key || (by === "person" ? "No person affected" : "Not about one object")}</span>;
            return (
              <Row key={g.key} head={head} count={g.count} n={g.n} max={max} open={open === g.key} onPick={() => pick(g.key)}>
                {by === "rule" && r && <p className="ae-rwhy">{r.why || r.meaning}</p>}
                {g.items.map((f) => <FixLine key={findingKey(f) + g.key} f={f} rule={by !== "rule"} onOpen={o.open} note={all ? mute[findingKey(f)] : undefined} />)}
                <div className="ae-how-links">
                  <button type="button" className="ae-link" onClick={() => graph(g.items[0])}>See on the graph</button>
                  {by === "rule" && <button type="button" className="ae-link" onClick={() => c.set({ show: "list", open: g.key, sev: null, by: null })}>Rule settings</button>}
                  {by !== "rule" && g.key && <button type="button" className="ae-link" onClick={() => o.open(g.key)}>Open {g.key}</button>}
                  <Mute items={g.items.filter((f) => !(findingKey(f) in mute))} />
                </div>
              </Row>
            );
          })}
          {!groups.length && <EmptyState title="Nothing here" art={d.findings.length ? "search" : "clear"}>{d.findings.length ? "Every finding at this level is muted or its rule is off." : "Every rule passes."}</EmptyState>}
        </section>
        <PlanPanel />
      </div>)}
    </>
  );
}

const SEV_RANK: Record<string, number> = { Critical: 0, High: 1, Medium: 2, Low: 3 };
const GRID_ROWS = 40;

/** Who breaks which rule: one row per grantee (worst first), one column per rule with a finding, the cell coloured by
 * the rule's severity and showing how many findings. A cell opens that rule's findings; a name opens the grantee. */
export function HeatGrid({ list, onRule, onOpen }: { list: Finding[]; onRule: (num: string) => void; onOpen: (id: string) => void }) {
  const [all, setAll] = useState(false);
  if (!list.length) return <EmptyState title="Nothing here" art="clear">No finding at this level.</EmptyState>;
  const rules = [...new Map(list.map((f) => [f.num, f])).values()].sort((a, b) => SEV_RANK[a.severity] - SEV_RANK[b.severity] || Number(a.num) - Number(b.num));
  const by = new Map<string, Finding[]>();
  for (const f of list) by.set(f.grantee, [...(by.get(f.grantee) ?? []), f]);
  const rows = [...by].map(([g, fs]) => ({ g, fs, kind: fs[0].kind, worst: Math.min(...fs.map((f) => SEV_RANK[f.severity])) }))
    .sort((a, b) => a.worst - b.worst || b.fs.length - a.fs.length || a.g.localeCompare(b.g));
  const shown = all ? rows : rows.slice(0, GRID_ROWS);
  return (
    <section className="ae-card ae-hgrid-card" aria-label="Findings heat grid">
      <p className="ae-muted">{rows.length} grantees × {rules.length} rules with a finding. Darker is more severe; the number is how many findings. Click a cell for the rule's findings.</p>
      <div className="ae-hgrid-scroll">
        <table className="ae-hgrid">
          <thead>
            <tr><th scope="col" className="ae-hgrid-who">Grantee</th>
              {rules.map((r) => <th key={r.num} scope="col" title={`#${r.num} ${r.title} (${r.severity})`}><span className={`ae-hgrid-rule ae-sev-${r.severity}`}>#{r.num}</span></th>)}
              <th scope="col">All</th></tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.g}>
                <th scope="row" className="ae-hgrid-who"><button type="button" className={`ae-pchip ae-pchip-${r.kind === "object" ? "obj" : r.kind}`} onClick={() => onOpen(r.g)} title={r.g}>{r.g.replace(/ \(user\)$/, "")}</button></th>
                {rules.map((x) => {
                  const n = r.fs.filter((f) => f.num === x.num).length;
                  return <td key={x.num}>{n > 0 && <button type="button" className={`ae-hgrid-c ae-hc-${x.severity}`} onClick={() => onRule(x.num)}
                    title={`${r.g}: ${n} finding${n === 1 ? "" : "s"} of #${x.num} ${x.title}`}>{n}</button>}</td>;
                })}
                <td className="ae-hgrid-n">{r.fs.length}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > GRID_ROWS && <button type="button" className="ae-btn ae-mt" onClick={() => setAll(!all)}>{all ? "Show the first 40" : `Show all ${rows.length}`}</button>}
      <div className="ae-bar-legend ae-mt">{(["Critical", "High", "Medium", "Low"] as const).filter((s) => rules.some((r) => r.severity === s)).map((s) => <span key={s}><span className={`ae-hgrid-c ae-hc-${s} ae-hgrid-key`} />{s}</span>)}</div>
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
                    <span className={`ae-sevpill ae-sev-${r.severity}`}>{r.severity}</span>
                    {n ? <button type="button" className="ae-link" onClick={() => c.set({ show: "fixes", rule: r.num, sev: r.severity, open: null, by: null })}>{plural(n, "finding")}</button>
                      : <span className="ae-muted">passes</span>}
                    <label className="ae-toggle"><input type="checkbox" checked={on} onChange={(e) => rulesOff.set(e.target.checked ? off.filter((x) => x !== r.num) : [...off, r.num])} />{on ? "On" : "Off"}</label>
                  </div>
                  {open === r.num && (
                    <div className="ae-rule-body">
                      <div><h4>What it checks</h4><p>{r.meaning || r.why}</p></div>
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
