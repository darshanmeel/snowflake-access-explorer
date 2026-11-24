// Screen 11, What if (full page) on the change plan shared with Risks & fixes: one-line add form, plan chips, sentence and
// impact tiles, Group by People / Objects / Roles / Findings, the text to apply. access.what_if simulates; nothing runs.
import { useState } from "react";
import { download, useApi } from "../api/client";
import type { ListItem, LossGroup, Refs, WhatIfChange, WhatIfPage } from "../api/types";
import { Banner, Card, CodeOutput, CutPath, EmptyState, FilterChips, MiniBar, StackBar, useCsv } from "../components";
import { useApp, useOpen } from "../ctx";
import { Load, Pick, Sel } from "./common";
import { addTo, changeText, cutLinks, plan, planTexts, useSaved } from "./changeplan";

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
export function Wider({ d }: { d: Pick<WhatIfPage, "changes"> }) {
  const xs = wider(d);
  return xs.length ? <Banner tone="warn" title="This reaches more people than the one named" lines={xs} /> : null;
}

/** Lose vs keep for the whole plan: privileges taken away against privileges still reached another way. */
export function LoseKeep({ d }: { d: Pick<WhatIfPage, "lost_privs" | "kept_privs"> }) {
  const lost = d.lost_privs, kept = d.kept_privs;
  if (!lost && !kept) return null;
  return <StackBar label="Privileges lost and kept" parts={[{ key: "lost", label: "Privileges lost", value: lost, cls: "lose" }, { key: "kept", label: "Kept another way", value: kept, cls: "keep" }]} />;
}

/** People who lose the same thing, as one row (grouped on the server): who, what, the lost path with the cut link
 * crossed out, what they keep. */
export function LossGroups({ gs, total, changes, refs, max = 50 }: { gs: LossGroup[]; total: number; changes: WhatIfChange[]; refs: Refs; max?: number }) {
  const o = useOpen(refs);
  const [open, setOpen] = useState<string | null>(null);
  if (!gs.length) return <EmptyState title="Nobody loses anything" art="clear">Everyone keeps their access through another path.</EmptyState>;
  return (
    <div className="ae-lgroups">
      {gs.slice(0, max).map((g) => {
        const n = g.n, lost = g.lost_sum, kept = g.kept_sum;
        const on = open === g.key;
        return (
          <div key={g.key} className={`ae-lgroup${g.lost.length ? "" : " keep"}`}>
            <button type="button" className="ae-lgroup-head" aria-expanded={on} onClick={() => setOpen(on ? null : g.key)}>
              <span className="ae-lgroup-n" aria-hidden>{n}</span>
              <span className="ae-lgroup-text">{g.text}</span>
              {g.off > 0 && <span className="ae-warn-word">{g.off} not active</span>}
              <MiniBar of={Math.max(1, lost + kept)} text={`${lost} lost${kept ? ` · ${kept} kept` : ""}`}
                parts={[{ key: "l", label: "Lost", value: lost, cls: "lose" }, { key: "k", label: "Kept another way", value: kept, cls: "keep" }]} />
            </button>
            <div className="ae-lgroup-paths">
              {g.lost.slice(0, 3).map((r) => <CutPath key={r.object} path={r.path} cuts={cutLinks(r.path, changes)} kinds={refs.kinds}
                first={n > 1 ? `${n} people` : undefined} onOpen={o.open} />)}
              {g.kept.slice(0, 2).map((r) => <span key={`k:${r.object}`} className="ae-muted ae-lgroup-kept">Keeps <span className="ae-mono">{r.object}</span>{r.through ? <> through <span className="ae-mono">{r.through}</span></> : ""}</span>)}
            </div>
            {g.where.length > 1 || (g.where[0]?.objects ?? 0) > 1 ? (
              <table className="ae-lgroup-where">
                <tbody>{g.where.map((w) => <tr key={w.where}><td className="ae-mono">{w.where}</td><td className="ae-num">{w.objects.toLocaleString()} object{w.objects === 1 ? "" : "s"}</td><td>{w.privileges.join(" ")}</td></tr>)}</tbody>
                {g.where_total > g.where.length && <tfoot><tr><td colSpan={3} className="ae-muted">and {g.where_total - g.where.length} more places: the CSV has every object</td></tr></tfoot>}
              </table>) : null}
            {on && (
              <div className="ae-lgroup-who">
                {g.users.map((u) => <button type="button" key={u.user} className={`ae-pchip${u.status === "active" ? "" : " ae-pchip-off"}`} onClick={() => o.open(`${u.user} (user)`)}
                  title={u.status}>{u.user}{u.status === "active" ? "" : ` · ${u.status}`}</button>)}
                {n > g.users.length && <span className="ae-muted">and {n - g.users.length} more: the CSV has every person</span>}
              </div>
            )}
          </div>
        );
      })}
      {total > Math.min(max, gs.length) && <p className="ae-muted">and {total - Math.min(max, gs.length)} more groups: the CSV has every person.</p>}
    </div>
  );
}

function Impact({ d, list }: { d: WhatIfPage; list: WhatIfChange[] }) {
  const c = useApp();
  const csvOn = useCsv();
  const o = useOpen(d.refs);
  const k = d.counts;
  const objs = d.impact;
  const by = (["people", "objects", "roles", "findings"] as const).find((x) => x === c.params.by) ?? "people";
  const tiles: [string, number, string][] = [["People lose access", k.users, k.users ? " ae-tile-bad" : ""], ["Objects affected", k.objects, ""],
    ["Of them keep some of it", k.kept, ""], ["Nobody reaches", k.unreached, k.unreached ? " ae-tile-bad" : ""], ["Roles orphaned", k.orphans, k.orphans ? " ae-tile-warn" : ""],
    ["Findings fixed", k.fixed, ""], ["New findings", k.new, k.new ? " ae-tile-warn" : ""]];
  return (
    <>
      <p className="ae-answer"><b>{d.summary}.</b> A simulation: nothing changes in Snowflake.</p>
      <Wider d={d} />
      <LoseKeep d={d} />
      <div className="ae-tiles">{tiles.map(([l, v, t]) => <div key={l} className={`ae-tile${t}`}><span className="ae-tile-l">{l}</span><span className="ae-tile-v">{v}</span></div>)}</div>
      <Card title="Impact" right={
          <FilterChips label="Group impact by" value={by} onPick={(x) => c.set({ by: x === "people" ? null : x })} items={[
            { key: "people", label: "People", count: d.users_total }, { key: "objects", label: "Objects", count: d.impact_total },
            { key: "roles", label: "Roles", count: d.roles_total }, { key: "findings", label: "Findings", count: d.findings_total }]} />}>
        {by === "people" && <LossGroups gs={d.groups} total={d.groups_total} changes={list} refs={d.refs} />}
        {by === "objects" && (objs.length || d.objects.length ? (
          <ul className="ae-plan-lose ae-plan-objs">
            {objs.map((x) => <li key={x.object}><button type="button" className="ae-link ae-mono" onClick={() => o.open(x.object)}>{x.object}</button><span className="ae-muted">{x.type.toLowerCase()}</span>
              <span><b>{x.people === 1 ? "1 person" : `${x.people} people`}</b> lose {x.privileges.join(", ")}</span></li>)}
            {d.impact_total > objs.length && <li className="ae-muted">First {objs.length} of {d.impact_total} objects, most people first: the CSV has all.</li>}
            {d.objects.map((x) => <li key={`left:${x.object}`}><span className="ae-mono">{x.object}</span><span className="ae-muted">{x.type.toLowerCase()}</span>
              <span className="ae-bad">{[x.unreached && "nobody reaches it", x.ownerless && "no owner"].filter(Boolean).join(", ")}{x.sensitive ? " · sensitive" : ""}</span></li>)}
          </ul>) : <EmptyState title="No object loses a reader" art="clear" />)}
        {by === "roles" && (d.roles.length ? (
          <ul className="ae-plan-lose">{d.roles.map((r) => <li key={r.role}><button type="button" className="ae-link ae-mono" onClick={() => o.open(r.role)}>{r.role}</button>
            <span className="ae-muted">{r.kind} · {[r.orphan && "orphan: no user or role holds it", r.unreached && "no user reaches it"].filter(Boolean).join(", ")}</span></li>)}</ul>
        ) : <EmptyState title="No role is left orphaned" art="clear">Every role keeps a holder.</EmptyState>)}
        {by === "findings" && (d.findings.length ? (
          <ul className="ae-plan-lose">{d.findings.map((f, i) => (
            <li key={i}><span className={`ae-tag ae-tag-${f.status === "fixed" && !f.changed ? "ok" : "warn"}`}>{f.changed ? "Changed" : f.status === "fixed" ? "Fixed" : "New"}</span>
              <span>#{f.num} {f.title} <span className="ae-mono">({f.grantee.replace(/ \(user\)$/, "")})</span></span></li>))}</ul>
        ) : <EmptyState title="No finding changes" art="search" />)}
      </Card>
      <Card title="Text to apply" sub="Copy it into your infrastructure as code or a ticket. This app never runs it."
        right={csvOn && <button type="button" className="ae-btn" onClick={() => download("whatif.csv", { view: c.view, changes: JSON.stringify(list) }, "what_if.csv")}>Download CSV</button>}>
        <CodeOutput changes={[]} name="what_if" texts={planTexts(list, d.sql)} />
      </Card>
    </>
  );
}

export function PlanTab({ fromUrl }: { fromUrl: WhatIfChange[] }) {
  const c = useApp();
  const list = useSaved(plan);
  const s = useApi<WhatIfPage>(list.length ? "whatif" : null, { view: c.view, changes: JSON.stringify(list) });
  const extra = fromUrl.filter((x) => !list.some((y) => changeText(y) === changeText(x)));
  return (
    <>
      <AddForm />
      <div className="ae-plan-chips">
        <span className="ae-muted">In this plan:</span>
        {list.map((x) => <span key={changeText(x)} className="ae-chip ae-chip-plain">{changeText(x)}
          <button type="button" className="ae-link" aria-label="Remove" onClick={() => plan.set(list.filter((y) => y !== x))}>×</button></span>)}
        {!list.length && <span className="ae-muted">nothing yet</span>}
        {extra.length > 0 && <button type="button" className="ae-btn" onClick={() => plan.set(addTo(list, extra))}>Add the {plural(extra.length, "change")} from the Changes tab</button>}
        {list.length > 0 && <button type="button" className="ae-link" onClick={() => plan.set([])}>Clear</button>}
        <span className="ae-muted">· the same plan as on Risks, saved in this browser</span>
      </div>
      {list.length > 0 ? <Load s={s}>{(d) => <Impact d={d} list={list} />}</Load>
        : <EmptyState title="Add a change to see its impact" art="plan">Pick a change above, or add fixes from findings on Risks.</EmptyState>}
    </>
  );
}
