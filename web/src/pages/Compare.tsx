// Screen 9: Compare two people or roles. One differences view: only A / only B / both reach (different or the same),
// differences first, and the changes that make B match A or remove A's extras (text only, What if to simulate).
import { useState } from "react";
import { useApi } from "../api/client";
import type { CompareRow, CompareSide, ComparePage } from "../api/types";
import { AccessPill, Banner, Card, CodeOutput, EmptyState, FilterChips, Overlap, type Change } from "../components";
import { apiParams, useApp, useOpen } from "../ctx";
import { Load, Pick, PickFirst, Sel } from "./common";
import { whatIfOf } from "./screens";
import { subjects } from "./See";
import { whatIf } from "./Whatif";

const PILL: Record<string, string> = { only_a: "Only A", only_b: "Only B", different: "Different", same: "Same" };

export function ComparePageView() {
  const c = useApp();
  const none = c.view !== "mine" && !c.params.a;  // shared: nobody picked yet
  const s = useApi<ComparePage>(none ? null : "compare", { ...apiParams(c), f: null, plan: null });
  const d = s.data;
  const what = subjects(c.view === "mine");
  return (
    <>
      <div className="ae-h1 ae-h1-pick ae-cmp-head">
        Compare
        <span className="ae-cmp-a"><Pick label="A" value={d?.a.id ?? c.params.a ?? ""} what={what} onPick={(v) => c.set({ a: v })} width={200} /></span>
        with
        <span className="ae-cmp-b"><Pick label="B" value={d?.b.id ?? c.params.b ?? ""} what={what} onPick={(v) => c.set({ b: v })} width={200} /></span>
        on
        <Sel label="Scope" value={d?.scope ?? "sensitive"} onPick={(v) => c.set({ scope: v })}
          options={[["sensitive", "sensitive data"], ["all", "everything"], ["db", "one database"]]} />
        {d?.scope === "db" && <Pick label="Database" value={d.db} what="databases" onPick={(v) => c.set({ db: v })} width={200} />}
      </div>
      {none ? <PickFirst what="who to compare (A)" /> : <Load s={s}>{(x) => <Body d={x} />}</Load>}
    </>
  );
}

function Body({ d }: { d: ComparePage }) {
  const n = d.counts;
  return (
    <>
      <div className="ae-cmp-sum">
        <Overlap a={d.a.name} b={d.b.name} onlyA={n.only_a} onlyB={n.only_b} different={n.different} same={n.same} />
        <p className="ae-answer">
          Of {n.only_a + n.only_b + n.different + n.same} objects {d.scope === "sensitive" ? "with sensitive data" : d.scope === "db" ? `in ${d.db}` : ""} that either reaches,{" "}
          <b className="ae-cmp-a">{n.only_a} only A</b> reaches, <b className="ae-cmp-b">{n.only_b} only B</b>, {n.different} both reach with different access and {n.same} the same.
        </p>
      </div>
      {d.scope === "sensitive" && !d.sensitive && <Banner tone="info" title="No sensitive objects known" lines={["Pick everything or one database as the scope."]} />}
      <Diffs d={d} />
    </>
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
  const f = c.params.f === "only_a" || c.params.f === "only_b" || c.params.f === "both" ? c.params.f : "";
  const n = d.counts;
  const rows = d.rows.filter((r) => (f === "both" ? r.a && r.b : f ? r.diff === f : same || r.diff !== "same"));
  const changes = (plan === "match" ? d.match : d.extras) as Change[];
  return (
    <>
      <Card title={<>Differences · <span className="ae-cmp-a ae-mono">A {d.a.name}</span> and <span className="ae-cmp-b ae-mono">B {d.b.name}</span></>}
        sub="Differences first; the same ones are folded.">
        <FilterChips label="Show" value={f} onPick={(k) => c.set({ f: k || null })} items={[
          { key: "", label: "All differences", count: n.only_a + n.only_b + n.different },
          { key: "only_a", label: "Only A", count: n.only_a }, { key: "only_b", label: "Only B", count: n.only_b },
          { key: "both", label: "Both", count: n.different + n.same }]} />
        {!d.rows.length ? <EmptyState title="Nothing in scope" art="search">Neither reaches an object here.</EmptyState>
          : !rows.length ? <p className="ae-muted">{f ? "No objects match this filter." : "No differences: both reach the same objects with the same access."}</p> : (
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
        {!f && d.counts.same > 0 && <button type="button" className="ae-btn ae-mt" onClick={() => setSame(!same)}>{same ? `Hide the ${d.counts.same} that are the same` : `Show the ${d.counts.same} that are the same`}</button>}
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
