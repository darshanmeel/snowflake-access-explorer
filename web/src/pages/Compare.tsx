// Screen 9: Compare two people or roles. The old Compare two roles table (what each sees of the sensitive objects)
// stays the default tab; "Differences" counts only A / only B / both but different / same, differences first, and
// writes the changes that make B match A or remove A's extras (text only, What if to simulate).
import { useState } from "react";
import { useApi } from "../api/client";
import type { CompareRow, CompareSide, ComparePage } from "../api/types";
import { AccessPill, Banner, Card, CodeOutput, DataTable, EmptyState, Tabs, type Change } from "../components";
import { apiParams, useApp, useOpen } from "../ctx";
import { col, Load, Pick, Sel } from "./common";
import { whatIfOf } from "./screens";
import { useSubjects } from "./See";
import { whatIf } from "./Whatif";

const PILL: Record<string, string> = { only_a: "Only A", only_b: "Only B", different: "Different", same: "Same" };

export function ComparePageView() {
  const c = useApp();
  const s = useApi<ComparePage>("compare", { ...apiParams(c), show: null, plan: null });
  const subj = useSubjects();
  const d = s.data;
  const opts = (v: string) => (subj.options.length ? subj.options : [v]);
  return (
    <>
      <div className="ae-h1 ae-h1-pick ae-cmp-head">
        Compare
        <span className="ae-cmp-a"><Pick label="A" value={d?.a.id ?? c.params.a ?? ""} options={opts(d?.a.id ?? "")} onPick={(v) => c.set({ a: v })} width={200} /></span>
        with
        <span className="ae-cmp-b"><Pick label="B" value={d?.b.id ?? c.params.b ?? ""} options={opts(d?.b.id ?? "")} onPick={(v) => c.set({ b: v })} width={200} /></span>
        on
        <Sel label="Scope" value={d?.scope ?? "sensitive"} onPick={(v) => c.set({ scope: v })}
          options={[["sensitive", "sensitive data"], ["all", "everything"], ["db", "one database"]]} />
        {d?.scope === "db" && <Sel label="Database" value={d.db} onPick={(v) => c.set({ db: v })} options={d.dbs.map((x): [string, string] => [x, x])} />}
      </div>
      <Load s={s}>{(x) => <Body d={x} />}</Load>
    </>
  );
}

function Body({ d }: { d: ComparePage }) {
  const c = useApp();
  const tab = c.params.show === "diff" ? "diff" : "old";
  const n = d.counts;
  return (
    <>
      <div className="ae-tiles">
        <div className="ae-tile"><span className="ae-tile-l">Only A has</span><span className="ae-tile-v ae-cmp-av">{n.only_a}</span></div>
        <div className="ae-tile"><span className="ae-tile-l">Only B has</span><span className="ae-tile-v ae-cmp-bv">{n.only_b}</span></div>
        <div className="ae-tile"><span className="ae-tile-l">Both, but different</span><span className="ae-tile-v">{n.different}</span></div>
        <div className="ae-tile"><span className="ae-tile-l">The same</span><span className="ae-tile-v ae-muted">{n.same}</span></div>
      </div>
      {d.scope === "sensitive" && !d.sensitive && <Banner tone="info" title="No sensitive objects known" lines={["Pick everything or one database as the scope."]} />}
      <Tabs active={tab} onChange={(k) => c.set({ show: k === "old" ? null : k })} tabs={[
        { key: "old", label: "What each sees", count: d.old?.rows.length ?? 0 },
        { key: "diff", label: "Differences", count: n.only_a + n.only_b + n.different },
      ]} />
      {tab === "old" && <Old d={d} />}
      {tab === "diff" && <Diffs d={d} />}
    </>
  );
}

type OR = NonNullable<ComparePage["old"]>["rows"][number];

/** The old Sensitive data tab "Compare two roles", for any two people or roles. */
function Old({ d }: { d: ComparePage }) {
  if (!d.old) return <EmptyState title="No sensitive objects">This table compares what each sees of the sensitive objects.</EmptyState>;
  return (
    <Card title="Compare two roles" sub="What each sees in the sensitive objects">
      {d.old.diff.length > 0 && <Banner tone="warn" title="They differ" lines={d.old.diff} />}
      <DataTable csv="sensitive_compare.csv" rows={d.old.rows}
        columns={[col("o", "Object", (r: OR) => r.object, { wrap: "wrap" }),
          col("a", d.a.name, (r: OR) => r.a ?? "no access", { wrap: "wrap" }),
          col("b", d.b.name, (r: OR) => r.b ?? "no access", { wrap: "wrap" })]} />
    </Card>
  );
}

function SideCell({ x, who }: { x: CompareSide | null; who: "a" | "b" }) {
  if (!x) return <span className="ae-cmp-cell ae-muted">No access</span>;
  return (
    <span className={`ae-cmp-cell ae-cmp-cell-${who}`}>
      <AccessPill level={x.level} privileges={x.privileges} />
      {x.sees && <span className="ae-cmp-sees">{x.sees}</span>}
    </span>
  );
}

function Diffs({ d }: { d: ComparePage }) {
  const c = useApp();
  const o = useOpen(d.refs);
  const [same, setSame] = useState(false);
  const plan = c.params.plan === "match" || c.params.plan === "extras" ? c.params.plan : null;
  const rows = d.rows.filter((r) => same || r.diff !== "same");
  const changes = (plan === "match" ? d.match : d.extras) as Change[];
  return (
    <>
      <Card title={<>Differences · <span className="ae-cmp-a ae-mono">A {d.a.name}</span> and <span className="ae-cmp-b ae-mono">B {d.b.name}</span></>}
        sub="Differences first; the same ones are folded.">
        {!d.rows.length ? <EmptyState title="Nothing in scope">Neither reaches an object here.</EmptyState> : (
          <div className="ae-cmp" role="table">
            <div className="ae-cmp-row ae-cmp-row-h" role="row"><span>Object</span><span>Difference</span><span className="ae-cmp-a">A · {d.a.name}</span><span className="ae-cmp-b">B · {d.b.name}</span></div>
            {rows.map((r: CompareRow) => (
              <div key={r.object} role="row" className={`ae-cmp-row${r.diff === "same" ? " ae-cmp-same" : ""}`}>
                <span><button type="button" className="ae-link ae-mono" onClick={() => o.open(r.object)}>{r.name || r.object}</button>
                  <span className="ae-muted ae-osub">{r.type.toLowerCase()}{r.schema ? ` · ${r.database}.${r.schema}` : r.database && r.database !== r.object ? ` · ${r.database}` : ""}</span></span>
                <span><span className={`ae-cmp-pill ae-cmp-${r.diff}`}>{PILL[r.diff]}</span></span>
                <SideCell x={r.a} who="a" />
                <SideCell x={r.b} who="b" />
              </div>
            ))}
          </div>
        )}
        {d.counts.same > 0 && <button type="button" className="ae-btn ae-mt" onClick={() => setSame(!same)}>{same ? `Hide the ${d.counts.same} that are the same` : `Show the ${d.counts.same} that are the same`}</button>}
      </Card>
      <div className="ae-actions">
        <button type="button" className={`ae-btn${plan === "match" ? " ae-btn-primary" : ""}`} disabled={!d.match.length} onClick={() => c.set({ plan: plan === "match" ? null : "match" })}>Make B match A</button>
        <button type="button" className={`ae-btn${plan === "extras" ? " ae-btn-primary" : ""}`} disabled={!d.extras.length} onClick={() => c.set({ plan: plan === "extras" ? null : "extras" })}>Remove A's extras</button>
        {plan === "extras" && <button type="button" className="ae-btn" onClick={() => whatIf(c, whatIfOf(d.extras))}>Simulate on What if</button>}
      </div>
      {plan && (
        <Card title={plan === "match" ? `Give ${d.b.name} what only ${d.a.name} has` : `Take away what only ${d.a.name} has`}
          sub={plan === "match" ? "B gets the grant holder role (a person: the role A starts with), or the privilege A holds itself."
            : "The first link of A's path, or A's own grant: a role link removes everything it brings, so simulate it first."}>
          <CodeOutput changes={changes} name={`compare_${plan}`} note={{ reason: `Compare ${d.a.name} with ${d.b.name} (${d.scope === "db" ? d.db : d.scope})` }} />
        </Card>
      )}
    </>
  );
}
