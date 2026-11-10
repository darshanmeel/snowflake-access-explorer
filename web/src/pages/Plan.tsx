// Screen 11, What if (full page) on the change plan shared with Risks & fixes: one-line add form, plan chips, sentence and
// impact tiles, Group by People / Objects / Roles / Findings, the text to apply. access.what_if simulates; nothing runs.
import { useState } from "react";
import { download, useApi } from "../api/client";
import type { ListItem, Refs, WhatIfChange, WhatIfPage, WhatIfUser } from "../api/types";
import { Card, CodeOutput, CutPath, EmptyState, FilterChips, MiniBar, StackBar } from "../components";
import { useApp, useOpen } from "../ctx";
import { Load, Pick, Sel } from "./common";
import { addTo, changeText, cutLinks, lossGroups, objectImpact, plan, planTexts, useSaved } from "./changeplan";

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
      {k !== "public" && <Pick label="Role" value={role} what="roles" onPick={(v) => { setRole(v); setOther(""); }} width={220} />}
      {k === "revoke" && <><span className="ae-ask-w">from</span><Pick label={role ? `User or role (${ids(us).length + ids(rs).length} hold it)` : "User or role"} value={other} options={[...ids(us), ...ids(rs)]} onPick={setOther} width={220} /></>}
      {k === "priv" && <><Sel label="Privilege" value={priv} onPick={setPriv} options={PRIVS.map((p): [string, string] => [p, p])} /><span className="ae-ask-w">on</span>
        <Pick label="Object" value={other} what="objects" onPick={setOther} width={300} /></>}
      <button type="button" className="ae-btn ae-btn-primary" disabled={!ch} onClick={() => { if (ch) { plan.set(addTo(plan.get(), [ch])); setOther(""); } }}>Add to plan</button>
    </div>
  );
}

/** Lose vs keep for the whole plan: privileges taken away against privileges still reached another way. */
export function LoseKeep({ users }: { users: WhatIfUser[] }) {
  const lost = users.reduce((n, u) => n + u.lost, 0), kept = users.reduce((n, u) => n + u.kept, 0);
  if (!lost && !kept) return null;
  return <StackBar label="Privileges lost and kept" parts={[{ key: "lost", label: "Privileges lost", value: lost, cls: "lose" }, { key: "kept", label: "Kept another way", value: kept, cls: "keep" }]} />;
}

/** People who lose the same thing, as one row: who, what, the lost path with the cut link crossed out, what they keep. */
export function LossGroups({ users, changes, refs, max = 50 }: { users: WhatIfUser[]; changes: WhatIfChange[]; refs: Refs; max?: number }) {
  const o = useOpen(refs);
  const [open, setOpen] = useState<string | null>(null);
  const gs = lossGroups(users);
  if (!gs.length) return <EmptyState title="Nobody loses anything" art="clear">Everyone keeps their access through another path.</EmptyState>;
  return (
    <div className="ae-lgroups">
      {gs.slice(0, max).map((g) => {
        const n = g.users.length, lost = g.users.reduce((s, u) => s + u.lost, 0), kept = g.users.reduce((s, u) => s + u.kept, 0);
        const off = g.users.filter((u) => u.status !== "active");
        const on = open === g.key;
        return (
          <div key={g.key} className={`ae-lgroup${g.lost.length ? "" : " keep"}`}>
            <button type="button" className="ae-lgroup-head" aria-expanded={on} onClick={() => setOpen(on ? null : g.key)}>
              <span className="ae-lgroup-n" aria-hidden>{n}</span>
              <span className="ae-lgroup-text">{g.text}</span>
              {off.length > 0 && <span className="ae-warn-word">{off.length} not active</span>}
              <MiniBar of={Math.max(1, lost + kept)} text={`${lost} lost${kept ? ` · ${kept} kept` : ""}`}
                parts={[{ key: "l", label: "Lost", value: lost, cls: "lose" }, { key: "k", label: "Kept another way", value: kept, cls: "keep" }]} />
            </button>
            <div className="ae-lgroup-paths">
              {g.lost.slice(0, 3).map((r) => <CutPath key={r.object} path={r.path} cuts={cutLinks(r.path, changes)} kinds={refs.kinds}
                first={n > 1 ? `${n} people` : undefined} onOpen={o.open} />)}
              {g.kept.slice(0, 2).map((r) => <span key={`k:${r.object}`} className="ae-muted ae-lgroup-kept">Keeps <span className="ae-mono">{r.object}</span>{r.through ? <> through <span className="ae-mono">{r.through}</span></> : ""}</span>)}
            </div>
            {on && (
              <div className="ae-lgroup-who">
                {g.users.map((u) => <button type="button" key={u.user} className={`ae-pchip${u.status === "active" ? "" : " ae-pchip-off"}`} onClick={() => o.open(`${u.user} (user)`)}
                  title={u.status}>{u.user}{u.status === "active" ? "" : ` · ${u.status}`}</button>)}
              </div>
            )}
          </div>
        );
      })}
      {gs.length > max && <p className="ae-muted">and {gs.length - max} more groups: the CSV has every person.</p>}
    </div>
  );
}

function Impact({ d, list }: { d: WhatIfPage; list: WhatIfChange[] }) {
  const c = useApp();
  const o = useOpen(d.refs);
  const k = d.counts;
  const objs = objectImpact(d.users);
  const by = (["people", "objects", "roles", "findings"] as const).find((x) => x === c.params.by) ?? "people";
  const tiles: [string, number, string][] = [["People lose access", k.users, k.users ? " ae-tile-bad" : ""], ["Objects affected", k.objects, ""],
    ["Kept another way", k.kept, ""], ["Nobody reaches", k.unreached, k.unreached ? " ae-tile-bad" : ""], ["Roles orphaned", k.orphans, k.orphans ? " ae-tile-warn" : ""],
    ["Findings fixed", k.fixed, ""], ["New findings", k.new, k.new ? " ae-tile-warn" : ""]];
  return (
    <>
      <p className="ae-answer"><b>{d.summary}.</b> A simulation: nothing changes in Snowflake.</p>
      <LoseKeep users={d.users} />
      <div className="ae-tiles">{tiles.map(([l, v, t]) => <div key={l} className={`ae-tile${t}`}><span className="ae-tile-l">{l}</span><span className="ae-tile-v">{v}</span></div>)}</div>
      <Card title="Impact" right={
          <FilterChips label="Group impact by" value={by} onPick={(x) => c.set({ by: x === "people" ? null : x })} items={[
            { key: "people", label: "People", count: d.users.length }, { key: "objects", label: "Objects", count: objs.length },
            { key: "roles", label: "Roles", count: d.roles.length }, { key: "findings", label: "Findings", count: d.findings.length }]} />}>
        {by === "people" && <LossGroups users={d.users} changes={list} refs={d.refs} />}
        {by === "objects" && (objs.length || d.objects.length ? (
          <ul className="ae-plan-lose ae-plan-objs">
            {objs.map((x) => <li key={x.object}><button type="button" className="ae-link ae-mono" onClick={() => o.open(x.object)}>{x.object}</button><span className="ae-muted">{x.type.toLowerCase()}</span>
              <span><b>{x.people === 1 ? "1 person" : `${x.people} people`}</b> lose {x.privileges.join(", ")}</span></li>)}
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
        right={<button type="button" className="ae-btn" onClick={() => download("whatif.csv", { view: c.view, changes: JSON.stringify(list) }, "what_if.csv")}>Download CSV</button>}>
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
        <span className="ae-muted">· the same plan as on Risks & fixes, saved in this browser</span>
      </div>
      {list.length > 0 ? <Load s={s}>{(d) => <Impact d={d} list={list} />}</Load>
        : <EmptyState title="Add a change to see its impact" art="plan">Pick a change above, or add fixes from findings on Risks & fixes.</EmptyState>}
    </>
  );
}
