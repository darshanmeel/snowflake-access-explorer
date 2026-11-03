// Rule findings, the same on every page: severity tabs, one group per rule (most people affected first), a sentence per
// finding with its impact as a tag, and a Fix panel (path, infrastructure-as-code text, SQL; this app never runs it).
import { useMemo, useState } from "react";
import type { Finding, Severity } from "../api/types";
import { PathText } from "./PathText";
import { download, toCsv } from "./table";

export const SEVERITIES: Severity[] = ["Critical", "High", "Medium", "Low"];

/** Highest severity with findings, else "All". */
export const firstTab = (list: Finding[]) => SEVERITIES.find((s) => list.some((f) => f.severity === s)) ?? "All";

export interface RuleGroup { num: string; title: string; severity: Severity; items: Finding[]; people: number }

/** Findings grouped by rule, the rule affecting most people first. */
export function groupByRule(list: Finding[]): RuleGroup[] {
  const m = new Map<string, Finding[]>();
  for (const f of list) m.set(f.num, [...(m.get(f.num) ?? []), f]);
  return [...m.values()]
    .map((items) => ({ num: items[0].num, title: items[0].title, severity: items[0].severity, items,
      people: new Set(items.flatMap((f) => f.people)).size }))
    .sort((a, b) => b.people - a.people || b.items.length - a.items.length || Number(a.num) - Number(b.num));
}

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;

function Copy({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return <button className="ae-btn ae-btn-s" onClick={() => navigator.clipboard?.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1200); })}>{done ? "Copied" : "Copy"}</button>;
}

function Line({ f, kinds, onOpen }: { f: Finding; kinds: Record<string, string>; onOpen?: (id: string) => void }) {
  const [fix, setFix] = useState(false);
  const k = kinds[f.grantee] ?? f.kind;
  return (
    <li className="ae-fd">
      <div className="ae-fd-line">
        <button className={`ae-chip ae-chip-${k}`} onClick={() => onOpen?.(f.grantee)} title={f.grantee}>{f.grantee.replace(/ \(user\)$/, "")}</button>
        {f.what && <span className="ae-fd-what" title={f.what}>{f.what}</span>}
        {f.impact && <span className={`ae-tag ae-tag-${f.impact.tone}`}>{f.impact.text}</span>}
        {(f.iac || f.sql || f.paths.length > 0) && <button className="ae-btn ae-btn-s ae-fd-fix" onClick={() => setFix(!fix)}>{fix ? "Hide fix" : "Fix"}</button>}
      </div>
      {fix && (
        <div className="ae-fd-panel">
          {f.paths.map((p, i) => <div key={i}><PathText path={p} kinds={kinds} onOpen={onOpen} /></div>)}
          {f.same_fix && <p className="ae-muted">Same fix as {f.same_fix}.</p>}
          {(f.iac || f.sql) && <p className="ae-muted">Text for your infrastructure as code. This app never runs it.</p>}
          {f.iac && <div className="ae-code-row"><pre className="ae-code">{f.iac}</pre><Copy text={f.iac} /></div>}
          {f.sql && <div className="ae-code-row"><pre className="ae-code">{f.sql}</pre><Copy text={f.sql} /></div>}
        </div>
      )}
    </li>
  );
}

function Group({ g, open, kinds, onOpen, onRule }: { g: RuleGroup; open: boolean; kinds: Record<string, string>; onOpen?: (id: string) => void; onRule?: (num: string) => void }) {
  const [on, setOn] = useState(open);
  return (
    <div className={`ae-fg ae-sev-${g.severity}`}>
      <button className="ae-fg-head" onClick={() => setOn(!on)} aria-expanded={on}>
        <span className="ae-fg-caret">{on ? "▾" : "▸"}</span>
        <span className="ae-fg-num">{g.num}</span>
        <span className="ae-fg-title">{g.title}</span>
        <span className="ae-muted">{plural(g.items.length, "finding")}{g.people ? ` · ${plural(g.people, "person")}`.replace("persons", "people") : ""}</span>
      </button>
      {on && (
        <>
          <ul className="ae-fd-list">{g.items.map((f, i) => <Line key={i} f={f} kinds={kinds} onOpen={onOpen} />)}</ul>
          {onRule && <button className="ae-link ae-fg-all" onClick={() => onRule(g.num)}>Rule {g.num} on the Rule checks page</button>}
        </>
      )}
    </div>
  );
}

export interface FindingsProps {
  list: Finding[];
  kinds?: Record<string, string>;
  onOpen?: (id: string) => void;
  onRule?: (num: string) => void;
  compact?: boolean; // entity pages: one line "High 2 · Medium 1" that opens the tabs in place
  csvName?: string;
}

export function Findings({ list, kinds = {}, onOpen, onRule, compact = false, csvName = "findings" }: FindingsProps) {
  const [tab, setTab] = useState<Severity | "All">(() => firstTab(list));
  const [open, setOpen] = useState(!compact);
  const [area, setArea] = useState("");
  const [q, setQ] = useState("");
  const [people, setPeople] = useState(false);
  const areas = useMemo(() => [...new Set(list.map((f) => f.area).filter(Boolean))].sort(), [list]);
  const count = (s: Severity) => list.filter((f) => f.severity === s).length;
  const inTab = list.filter((f) => tab === "All" || f.severity === tab);
  const ql = q.trim().toLowerCase();
  const shown = inTab.filter((f) => (!area || f.area === area) && (!people || f.people.length > 0)
    && (!ql || [f.title, f.grantee, f.what, f.num].some((x) => x.toLowerCase().includes(ql))));
  const hidden = inTab.length - shown.length;
  const why = [area && `area = ${area}`, people && "people only", ql && `search "${q.trim()}"`].filter(Boolean).join(", ");
  const groups = groupByRule(shown);
  if (!list.length) return null;

  const summary = SEVERITIES.filter((s) => count(s)).map((s) => (
    <span key={s} className={`ae-sevpill ae-sev-${s}`}>{s} {count(s)}</span>
  ));
  if (compact && !open)
    return <button className="ae-fsum" onClick={() => setOpen(true)}><span className="ae-muted">Rule findings</span>{summary}<span className="ae-link">show</span></button>;

  const csv = () => download(`${csvName}_${tab}.csv`, toCsv(["Rule", "Severity", "Finding", "Grantee", "What", "Impact", "Fix", "SQL"],
    shown.map((f) => [f.num, f.severity, f.title, f.grantee, f.what, f.impact?.text ?? "", f.iac, f.sql])));

  return (
    <div className="ae-findings">
      {compact && <button className="ae-fsum" onClick={() => setOpen(false)}><span className="ae-muted">Rule findings</span>{summary}<span className="ae-link">hide</span></button>}
      <div className="ae-tabs" role="tablist">
        {[...SEVERITIES, "All" as const].map((s) => {
          const n = s === "All" ? list.length : count(s);
          return (
            <button key={s} role="tab" aria-selected={tab === s} disabled={!n}
              className={`ae-tab ae-sevtab ae-sev-${s}${tab === s ? " on" : ""}`} onClick={() => setTab(s)}>
              {s}<span className="ae-tab-count">{n}</span>
            </button>
          );
        })}
      </div>
      {inTab.length > 6 && (
        <div className="ae-controls ae-fd-filter">
          {areas.length > 1 && (
            <select className="ae-input" value={area} onChange={(e) => setArea(e.target.value)} aria-label="Area">
              <option value="">Every area</option>{areas.map((a) => <option key={a}>{a}</option>)}
            </select>
          )}
          <input className="ae-input" placeholder="Search findings" value={q} onChange={(e) => setQ(e.target.value)} />
          <label className="ae-check"><input type="checkbox" checked={people} onChange={(e) => setPeople(e.target.checked)} /> People affected only</label>
          <button className="ae-btn ae-btn-s" onClick={csv}>CSV</button>
        </div>
      )}
      {hidden > 0 && <p className="ae-muted ae-fd-hidden">{hidden} hidden: {why}</p>}
      {groups.map((g, i) => <Group key={`${tab}:${g.num}`} g={g} open={groups.length === 1 || (i === 0 && g.items.length <= 5)} kinds={kinds} onOpen={onOpen} onRule={onRule} />)}
      {!groups.length && <p className="ae-muted">Nothing here.</p>}
    </div>
  );
}
