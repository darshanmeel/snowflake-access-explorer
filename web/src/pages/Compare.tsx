// Screen 9: Compare two people or roles. One differences view: only A / only B / both reach (different or the same),
// differences first, and the changes that make B match A or remove A's extras (text only, What if to simulate).
import { useApi } from "../api/client";
import type { CompareRow, CompareSide, ComparePage } from "../api/types";
import { AccessPill, Banner, Card, CodeOutput, EmptyState, FilterChips, Overlap, Pager, type Change } from "../components";
import { apiParams, useApp, useOpen } from "../ctx";
import { Load, Pick, PickFirst, Sel } from "./common";
import { whatIfOf } from "./screens";
import { subjects } from "./See";
import { whatIf } from "./Whatif";

const PILL: Record<string, string> = { only_a: "Only A", only_b: "Only B", different: "Different", same: "Same" };

export function ComparePageView() {
  const c = useApp();
  const none = c.view !== "mine" && !c.params.a;  // shared: nobody picked yet
  const s = useApi<ComparePage>(none ? null : "compare", { ...apiParams(c), plan: null });
  const d = s.data;
  const what = subjects(c.view === "mine");
  return (
    <>
      <div className="ae-h1 ae-h1-pick ae-cmp-head">
        Compare
        <span className="ae-cmp-a"><Pick label="A · the one to copy" value={d?.a.id ?? c.params.a ?? ""} what={what} onPick={(v) => c.set({ a: v })} width={200} /></span>
        with
        <span className="ae-cmp-b"><Pick label="B · the one to change" value={d?.b.id ?? c.params.b ?? ""} what={what} onPick={(v) => c.set({ b: v })} width={200} /></span>
        on
        <Sel label="Scope" value={d?.scope ?? "sensitive"} onPick={(v) => c.set({ scope: v })}
          options={[["sensitive", "sensitive data"], ["all", "everything"], ["db", "one database"]]} />
        {d && <button type="button" className="ae-btn ae-cmp-swap" title="Swap A and B" onClick={() => c.set({ a: d.b.id, b: d.a.id, plan: null, f: null, c_offset: null })}>⇄ Swap</button>}
        {d?.scope === "db" && <Pick label="Database" value={d.db} what="databases" onPick={(v) => c.set({ db: v })} width={200} />}
      </div>
      {none ? <PickFirst what="who to compare (A)" /> : <Load s={s}>{(x) => <Body d={x} />}</Load>}
    </>
  );
}

/** The answer first: what B lacks of A, and the reverse. */
export function compareLine(n: ComparePage["counts"], a: string, b: string): string {
  if (!n.only_a && !n.only_b && !n.different) return `${a} and ${b} reach the same ${n.same.toLocaleString()} object${n.same === 1 ? "" : "s"} with the same access.`;
  const objs = (x: number) => `${x.toLocaleString()} object${x === 1 ? "" : "s"}`;
  return [n.only_a ? `${b} lacks ${objs(n.only_a)} ${a} reaches` : `${b} has everything ${a} reaches`,
    n.only_b ? `${a} lacks ${objs(n.only_b)} ${b} reaches` : `${a} has nothing ${b} lacks`,
    ...(n.different ? [`${objs(n.different)} both reach with different access`] : [])].join("; ") + ".";
}

function Body({ d }: { d: ComparePage }) {
  const n = d.counts;
  return (
    <>
      <div className="ae-cmp-sum">
        <Overlap a={d.a.name} b={d.b.name} onlyA={n.only_a} onlyB={n.only_b} different={n.different} same={n.same} />
        <div className="ae-cmp-say">
          <p className="ae-answer"><b>{compareLine(n, d.a.name, d.b.name)}</b></p>
          <p className="ae-muted">Of {(n.only_a + n.only_b + n.different + n.same).toLocaleString()} objects {d.scope === "sensitive" ? "with sensitive data" : d.scope === "db" ? `in ${d.db}` : ""} that either reaches:{" "}
            <span className="ae-cmp-a">{n.only_a} only A</span>, <span className="ae-cmp-b">{n.only_b} only B</span>, {n.different} different, {n.same} the same.</p>
          <Plans d={d} />
        </div>
      </div>
      {d.scope === "sensitive" && !d.sensitive && <Banner tone="info" title="No sensitive objects known" lines={["Pick everything or one database as the scope."]} />}
      <PlanText d={d} />
      <Diffs d={d} />
    </>
  );
}

const planOf = (p: string | undefined) => (p === "match" || p === "extras" ? p : null);

/** The two plans, right under the answer; one with nothing to do is not offered. */
function Plans({ d }: { d: ComparePage }) {
  const c = useApp();
  const plan = planOf(c.params.plan);
  if (!d.match.length && !d.extras.length) return <p className="ae-muted">Nothing to plan: {d.b.name} already reaches what {d.a.name} reaches, with the same access, here.</p>;
  return (
    <div className="ae-actions">
      {d.match.length > 0 && <button type="button" className={`ae-btn${plan === "match" ? " ae-btn-primary" : ""}`} onClick={() => c.set({ plan: plan === "match" ? null : "match" })}>Make B match A ({d.match.length})</button>}
      {d.extras.length > 0 && <button type="button" className={`ae-btn${plan === "extras" ? " ae-btn-primary" : ""}`} onClick={() => c.set({ plan: plan === "extras" ? null : "extras" })}>Remove A's extras ({d.extras.length})</button>}
      {plan === "extras" && <button type="button" className="ae-btn" onClick={() => whatIf(c, whatIfOf(d.extras))}>Simulate on What if</button>}
    </div>
  );
}

function PlanText({ d }: { d: ComparePage }) {
  const c = useApp();
  const plan = planOf(c.params.plan);
  if (!plan) return null;
  return (
    <Card title={plan === "match" ? `Give ${d.b.name} what only ${d.a.name} has` : `Take away what only ${d.a.name} has`}
      sub={plan === "match" ? "B gets the grant holder role (a person: the role A starts with), or the privilege A holds itself."
        : "The first link of A's path, or A's own grant: a role link removes everything it brings, so simulate it first."}>
      <CodeOutput changes={(plan === "match" ? d.match : d.extras) as Change[]} name={`compare_${plan}`} note={{ reason: `Compare ${d.a.name} with ${d.b.name} (${d.scope === "db" ? d.db : d.scope})` }} />
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
  const same = c.params.same === "1";
  const f = c.params.f === "only_a" || c.params.f === "only_b" || c.params.f === "both" ? c.params.f : "";
  const n = d.counts;
  const rows = d.rows; // filtered and paged on the server
  const size = 50; // the server's PAGE
  return (
    <>
      <Card title={<>Differences · <span className="ae-cmp-a ae-mono">A {d.a.name}</span> and <span className="ae-cmp-b ae-mono">B {d.b.name}</span></>}
        sub="Differences first; the same ones are folded.">
        <FilterChips label="Show" value={f} onPick={(k) => c.set({ f: k || null, c_offset: null })} items={[
          { key: "", label: "All differences", count: n.only_a + n.only_b + n.different },
          { key: "only_a", label: "Only A", count: n.only_a }, { key: "only_b", label: "Only B", count: n.only_b },
          { key: "both", label: "Both", count: n.different + n.same }]} />
        {!d.any ? <EmptyState title="Nothing in scope" art="search">Neither reaches an object here.</EmptyState>
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
        {d.rows_total > size && <Pager at={Math.floor(d.offset / size)} size={size} total={d.rows_total} onPage={(n) => c.set({ c_offset: n ? String(n * size) : null })} />}
        {!f && d.counts.same > 0 && <button type="button" className="ae-btn ae-mt" onClick={() => c.set({ same: same ? null : "1", c_offset: null })}>{same ? `Hide the ${d.counts.same} that are the same` : `Show the ${d.counts.same} that are the same`}</button>}
      </Card>
    </>
  );
}
