// Screen 11, What if (full page) on the change plan shared with Risks & fixes: one-line add form, plan chips, sentence and
// impact tiles, Group by People / Objects / Roles / Findings, the text to apply. access.what_if simulates; nothing runs.
import { useMemo, useState, type ReactNode } from "react";
import { download, useApi } from "../api/client";
import type { ListItem, WhatIfChange, WhatIfPage } from "../api/types";
import { Card, EmptyState, Figs, Fold, Graph, pathGraph, StackBar } from "../components";
import type { PathIn } from "../components/graphs";
import { useApp, useOpen } from "../ctx";
import { Load, Pick, Sel } from "./common";
import { addTo, changeText, cutLinks, plan, useSaved } from "./changeplan";

type Kind = "revoke" | "drop" | "priv" | "public";
const KINDS: [Kind, string][] = [["revoke", "Revoke role"], ["drop", "Drop role"], ["priv", "Revoke privilege"], ["public", "Empty PUBLIC"]];
const PRIVS = ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "USAGE", "OWNERSHIP", "OPERATE", "MONITOR", "MODIFY", "CREATE TABLE", "CREATE VIEW"];
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;

function AddForm() {
  const c = useApp();
  const [k, setK] = useState<Kind>("revoke");
  const [role, setRole] = useState("");
  const [other, setOther] = useState("");
  const [priv, setPriv] = useState("SELECT");
  const us = useApi<{ items: ListItem[] }>(k === "revoke" && role ? "list" : null, { what: "user_holders", role, view: c.view });
  const rs = useApi<{ items: ListItem[] }>(k === "revoke" && role ? "list" : null, { what: "role_holders", role, view: c.view });
  const ids = (s: { data: { items: ListItem[] } | null }) => s.data?.items.map((i) => i.id) ?? [];
  const isUser = ids(us).includes(other);
  const ch: WhatIfChange | null = k === "public" ? { op: "empty_public" } : !role ? null : k === "drop" ? { op: "drop_role", role }
    : !other ? null : k === "priv" ? { op: "revoke_priv", role, privilege: priv, object: other }
    : isUser ? { op: "revoke_role_from_user", role, user: other } : ids(rs).includes(other) ? { op: "revoke_role_from_role", role, grantee: other } : null;
  return (
    <div className="ae-ask" role="form" aria-label="Add a change">
      <Sel label="Change" value={k} options={KINDS} onPick={(v) => { setK(v as Kind); setOther(""); }} />
      {k !== "public" && <Pick label="Role" value={role} what="roles" onPick={(v) => { setRole(v); if (k === "revoke") setOther(""); }} width={220} />}
      {k === "revoke" && <><span className="ae-ask-w">from</span><Pick label={role ? `User or role (${ids(us).length + ids(rs).length} hold it)` : "User or role"} value={other} options={[...ids(us), ...ids(rs)]} onPick={setOther} width={220} /></>}
      {k === "priv" && <><Sel label="Privilege" value={priv} onPick={setPriv} options={PRIVS.map((p): [string, string] => [p, p])} /><span className="ae-ask-w">on</span>
        <Pick label="Object" value={other} what="objects" onPick={setOther} width={300} /></>}
      <button type="button" className="ae-btn ae-btn-primary" disabled={!ch} onClick={() => { if (ch) { plan.set(addTo(plan.get(), [ch])); setOther(""); } }}>Add to plan</button>
    </div>
  );
}

/** Changes that take the role from others too: a role held through a group is revoked from the group. */
export const wider = (d: Pick<WhatIfPage, "changes">) => d.changes.map((x) => x.label).filter((l) => l.includes("other holders lose it"));
/** Lose vs keep for the whole plan: privileges taken away against privileges still reached another way. */
export function LoseKeep({ d }: { d: Pick<WhatIfPage, "lost_privs" | "kept_privs"> }) {
  const lost = d.lost_privs, kept = d.kept_privs;
  if (!lost && !kept) return null;
  return <StackBar label="Privileges lost and kept" parts={[{ key: "lost", label: "Privileges lost", value: lost, cls: "lose" }, { key: "kept", label: "Kept another way", value: kept, cls: "keep" }]} />;
}

/** The paths people lose as one graph, the removed links red and dashed; what they keep another way in grey. */
export function LossGraph({ d, changes }: { d: WhatIfPage; changes: WhatIfChange[] }) {
  const c = useApp();
  const o = useOpen(d.refs);
  const x = useMemo(() => {
    const paths: PathIn[] = [], kinds: Record<string, string> = { ...d.refs.kinds };
    const red = new Set<string>(), types = d.refs.types;
    const many = d.groups.slice(0, 6).some((g) => g.n > 4) || d.groups.length > 6;
    d.groups.slice(0, 6).forEach((g, gi) => {
      const starts = many && g.n > 1 ? [`${g.n} people${gi ? " " + "\u200b".repeat(gi) : ""}`] : g.users.slice(0, 4).map((u) => `${u.user} (user)`);
      starts.forEach((s) => {
        kinds[s] = "user";
        for (const r of g.lost) {
          if (types[r.object] === "DATABASE" || types[r.object] === "SCHEMA") continue;
          const path = [s, ...r.path.slice(1)], cuts = cutLinks(r.path, changes);
          paths.push({ path, cls: "read", privilege: r.privileges[0] });
          cuts.forEach((i) => red.add(`${path[i]}>${path[i + 1]}`));
        }
        for (const r of g.kept) if (r.via?.length && types[r.object] !== "DATABASE" && types[r.object] !== "SCHEMA") paths.push({ path: [s, ...r.via.slice(1)], cls: "use", privilege: r.privileges[0] });
      });
    });
    if (!paths.length) return null;
    const g = pathGraph(paths, { kinds, max: 40, objectLabel: "Objects", node: (n) => ({ ...n, label: n.label.replace(/ \(user\)$/, "").replace(/^(.*)\.<([A-Z ]+)>$/, (_, w: string, t: string) => `future ${t.toLowerCase()}s in ${w}`) }) });
    const hi = new Set<string>();
    g.edges.forEach((e) => { if (red.has(`${e.source}>${e.target}`)) { hi.add(e.id); e.privs = ["removed"]; } });
    return { g, hi };
  }, [d, changes]);
  if (!x) return null;
  return (
    <Card title="What would be cut" sub="Databases and schemas are left out.">
      <Graph graph={x.g} theme={c.theme} hi={x.hi} legend={false} maxHeight={460} onNodeClick={(n) => o.open(n.id)} />
      <div className="ae-bar-legend"><span><span className="ae-gline ae-gline-risk" aria-hidden />Link removed</span><span><span className="ae-gline ae-gline-read" aria-hidden />Access lost with it</span><span><span className="ae-gline ae-gline-use" aria-hidden />Kept another way</span>
        {d.groups_total > 6 && <span>First 6 of {d.groups_total} groups</span>}</div>
    </Card>
  );
}

/** Who loses what, as bullets: one row per group of people with the same loss. */
export function LossTable({ d }: { d: WhatIfPage }) {
  const o = useOpen(d.refs);
  const [all, setAll] = useState(false);
  if (!d.groups.length) return <EmptyState title="Nobody loses anything" art="clear">Everyone keeps their access through another path.</EmptyState>;
  const gs = all ? d.groups : d.groups.slice(0, 8);
  return (
    <Card title="Who loses what">
      <div className="ae-table-scroll"><table className="ae-table ae-losstab">
        <thead><tr><th>Person</th><th>Loses</th><th>Keeps another way</th></tr></thead>
        <tbody>{gs.map((g) => (
          <tr key={g.key}>
            <td><ul>{g.users.slice(0, 4).map((u) => <li key={u.user}><button type="button" className="ae-link ae-mono" onClick={() => o.open(`${u.user} (user)`)}>{u.user}</button>{u.status !== "active" && <span className="ae-bad"> {u.status}</span>}</li>)}
              {g.n > 4 && <li className="ae-muted">+{(g.n - 4).toLocaleString("en-US")} more</li>}</ul></td>
            <td><ul>{g.where.length ? g.where.map((w) => <li key={w.where}><b>{w.objects.toLocaleString("en-US")}</b> in <span className="ae-mono">{w.where}</span> <span className="ae-muted">{w.privileges.slice(0, 4).join(", ")}</span></li>) : <li className="ae-muted">nothing</li>}
              {g.where_total > g.where.length && <li className="ae-muted">+{g.where_total - g.where.length} more places</li>}</ul></td>
            <td><ul>{g.kept.length ? g.kept.map((k) => <li key={k.object}><span className="ae-mono">{k.object}</span>{k.through && <> through <span className="ae-mono">{k.through}</span></>}</li>) : <li className="ae-muted">nothing</li>}
              {g.kept_sum > g.kept.length * g.n && <li className="ae-muted">{Math.round(g.kept_sum / g.n).toLocaleString("en-US")} privileges in all</li>}</ul></td>
          </tr>))}</tbody>
      </table></div>
      {d.groups_total > gs.length && <button type="button" className="ae-link" onClick={() => setAll(true)} disabled={all}>{all ? `First ${gs.length} of ${d.groups_total}: the CSV has every person` : `+${d.groups_total - gs.length} more`}</button>}
    </Card>
  );
}

/** What to mind about a plan, one bullet each. */
export function Care({ d }: { d: WhatIfPage }) {
  const k = d.counts, more = wider(d), n = (x: number, w: string) => `${x.toLocaleString("en-US")} ${w}${x === 1 ? "" : "s"}`;
  if (!more.length && !k.unreached && !k.orphans && !k.new && !d.one_more.length) return null;
  return (
    <ul className="ae-plan-care">
      {more.map((x) => <li key={x} className="ae-warn-word">Reaches more people than named: {x.replace(/^Revoke role /, "")}</li>)}
      {k.unreached > 0 && <li className="ae-bad">Nobody reaches {n(k.unreached, "object")} any more</li>}
      {k.orphans > 0 && <li>{n(k.orphans, "role")} left without users or parent roles</li>}
      {k.new > 0 && <li className="ae-bad">{n(k.new, "new finding")}</li>}
      {d.one_more.map((x) => <li key={x.role}>One more step: dropping <span className="ae-mono">{x.role}</span> would also touch {x.people <= x.names.length ? x.names.join(", ") : `${x.people.toLocaleString("en-US")} other people`}</li>)}
    </ul>
  );
}

/** The result in one sentence, three numbers and bullets; the same on both tabs. */
export function Outcome({ d, changes }: { d: WhatIfPage; changes: WhatIfChange[] }) {
  const k = d.counts, n = (x: number, w: string, ws = `${w}s`) => `${x.toLocaleString("en-US")} ${x === 1 ? w : ws}`;
  const off = d.groups.reduce((t, g) => t + g.off, 0);
  const crit = d.findings.filter((f) => f.status === "fixed" && !f.changed);
  const sev = (["Critical", "High", "Medium", "Low"] as const).map((s) => [s, crit.filter((f) => f.severity === s).length] as const).filter(([, x]) => x);
  return (
    <>
      <p className="ae-answer">{k.users ? `${n(k.users, "person loses", "people lose")} access${k.fixed ? `, ${n(k.fixed, "finding closes", "findings close")}` : ""}${k.fixed && d.critical_stay ? `, ${d.critical_stay} critical ${d.critical_stay === 1 ? "one stays" : "ones stay"}` : ""}` : "Nobody loses access"}</p>
      <Figs items={[
        { key: "u", n: k.users.toLocaleString("en-US"), text: k.users === 1 ? "person loses access" : "people lose access", bad: k.users > off, note: k.users && off >= k.users ? `all inactive, ${n(k.objects, "object")} lost` : off ? `${off} inactive, ${n(k.objects, "object")} lost` : k.users ? `all active, ${n(k.objects, "object")} lost` : undefined },
        { key: "f", n: k.fixed.toLocaleString("en-US"), text: k.fixed === 1 ? "finding closes" : "findings close", note: sev.map(([s, x]) => `${x} ${s.toLowerCase()}`).join(", ") || undefined },
        { key: "c", n: d.critical_stay.toLocaleString("en-US"), text: d.critical_stay === 1 ? "critical finding stays" : "critical findings stay", bad: d.critical_stay > 0 },
      ]} />
      <Care d={d} />
      <LossGraph d={d} changes={changes} />
      <LossTable d={d} />
    </>
  );
}

/** result: what a plan does (the page's own). */
export function PlanTab({ fromUrl, result }: { fromUrl: WhatIfChange[]; result: (d: WhatIfPage, list: WhatIfChange[]) => ReactNode }) {
  const c = useApp();
  const list = useSaved(plan);
  const s = useApi<WhatIfPage>(list.length ? "whatif" : null, { view: c.view, changes: JSON.stringify(list) });
  const extra = fromUrl.filter((x) => !list.some((y) => changeText(y) === changeText(x)));
  return (
    <>
      <Fold label="Add a change to the plan" on={!list.length}><AddForm /></Fold>
      <div className="ae-plan-chips">
        <span className="ae-muted">In this plan:</span>
        {list.map((x) => <span key={changeText(x)} className="ae-chip ae-chip-plain">{changeText(x)}
          <button type="button" className="ae-link" aria-label="Remove" onClick={() => plan.set(list.filter((y) => y !== x))}>×</button></span>)}
        {!list.length && <span className="ae-muted">nothing yet</span>}
        {extra.length > 0 && <button type="button" className="ae-btn" onClick={() => plan.set(addTo(list, extra))}>Add the {plural(extra.length, "change")} from the Changes tab</button>}
        {list.length > 0 && <button type="button" className="ae-link" onClick={() => plan.set([])}>Clear</button>}
      </div>
      {list.length > 0 ? <Load s={s}>{(d) => <>{result(d, list)}</>}</Load>
        : <EmptyState title="Add a change to see its impact" art="plan">Pick a change above, or add fixes from findings on Risks.</EmptyState>}
    </>
  );
}
