// Screen 11, What if (full page) on the change plan shared with Risks & fixes: one-line add form, plan chips, sentence and
// impact tiles, Group by People / Objects / Roles / Findings, the text to apply. access.what_if simulates; nothing runs.
import { useState } from "react";
import { download, useApi } from "../api/client";
import type { ListItem, WhatIfChange, WhatIfObjectRow, WhatIfPage, WhatIfUser } from "../api/types";
import { Card, CodeOutput, EmptyState, FilterChips } from "../components";
import { useApp, useOpen } from "../ctx";
import { Load, Pick, Sel } from "./common";
import { addTo, changeText, objectImpact, plan, planTexts, useSaved } from "./changeplan";

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
  const roles = useApi<{ items: ListItem[] }>(k === "public" ? null : "list", { what: "roles", view: c.view });
  const us = useApi<{ items: ListItem[] }>(k === "revoke" && role ? "list" : null, { what: "user_holders", role, view: c.view });
  const rs = useApi<{ items: ListItem[] }>(k === "revoke" && role ? "list" : null, { what: "role_holders", role, view: c.view });
  const objs = useApi<{ items: ListItem[] }>(k === "priv" ? "list" : null, { what: "objects", view: c.view });
  const ids = (s: { data: { items: ListItem[] } | null }) => s.data?.items.map((i) => i.id) ?? [];
  const isUser = ids(us).includes(other);
  const ch: WhatIfChange | null = k === "public" ? { op: "empty_public" } : !role ? null : k === "drop" ? { op: "drop_role", role }
    : !other ? null : k === "priv" ? { op: "revoke_priv", role, privilege: priv, object: other }
    : isUser ? { op: "revoke_role_from_user", role, user: other } : ids(rs).includes(other) ? { op: "revoke_role_from_role", role, grantee: other } : null;
  return (
    <div className="ae-ask" role="form" aria-label="Add a change">
      <Sel label="Change" value={k} options={KINDS} onPick={(v) => { setK(v as Kind); setOther(""); }} />
      {k !== "public" && <Pick label="Role" value={role} options={ids(roles)} onPick={(v) => { setRole(v); setOther(""); }} width={220} />}
      {k === "revoke" && <><span className="ae-ask-w">from</span><Pick label={role ? `User or role (${ids(us).length + ids(rs).length} hold it)` : "User or role"} value={other} options={[...ids(us), ...ids(rs)]} onPick={setOther} width={220} /></>}
      {k === "priv" && <><Sel label="Privilege" value={priv} onPick={setPriv} options={PRIVS.map((p): [string, string] => [p, p])} /><span className="ae-ask-w">on</span>
        <Pick label="Object" value={other} options={ids(objs)} onPick={setOther} width={300} /></>}
      <button type="button" className="ae-btn ae-btn-primary" disabled={!ch} onClick={() => { if (ch) { plan.set(addTo(plan.get(), [ch])); setOther(""); } }}>Add to plan</button>
    </div>
  );
}

function Rows({ rows, kept }: { rows: WhatIfObjectRow[]; kept?: boolean }) {
  return (
    <ul className="ae-plan-lose">
      {rows.map((r) => <li key={r.object}><span className="ae-mono">{r.object}</span>
        <span className="ae-muted">{r.privileges.join(", ")} · {r.type.toLowerCase()}{kept && r.through ? ` · via ${r.through}` : ""}</span></li>)}
    </ul>
  );
}

function Person({ u, open, onPick }: { u: WhatIfUser; open: boolean; onPick: () => void }) {
  return (
    <div className={`ae-rrow${open ? " open" : ""}`}>
      <button type="button" className="ae-rrow-head ae-prow" aria-expanded={open} onClick={onPick}>
        <span className="ae-mono">{u.user}</span>
        <span className={u.status === "active" ? "ae-muted" : "ae-warn-word"}>{u.status}</span>
        <span className={u.objects ? "ae-bad" : "ae-muted"}>{u.objects ? `loses ${plural(u.lost, "privilege")} on ${plural(u.objects, "object")}` : "loses nothing"}</span>
        <span className="ae-muted">{u.kept || u.kept_roles.length ? `keeps ${u.kept + u.kept_roles.length} another way` : ""}</span>
      </button>
      {open && (
        <div className="ae-rrow-body ae-two">
          <div><h4>Loses</h4>{u.lost_rows.length ? <Rows rows={u.lost_rows} /> : <p className="ae-muted">Nothing.</p>}</div>
          <div><h4>Keeps, through another path</h4>
            {u.kept_rows.length || u.kept_roles.length ? <>
              <Rows rows={u.kept_rows} kept />
              {u.kept_roles.length > 0 && <ul className="ae-plan-lose">{u.kept_roles.map((x) => <li key={x.role}><span className="ae-mono">{x.role}</span><span className="ae-muted">role, via {x.through}</span></li>)}</ul>}
            </> : <p className="ae-muted">Nothing.</p>}
          </div>
        </div>
      )}
    </div>
  );
}

function Impact({ d, list }: { d: WhatIfPage; list: WhatIfChange[] }) {
  const c = useApp();
  const o = useOpen(d.refs);
  const [open, setOpen] = useState<string | null>(d.users[0]?.user ?? null);
  const k = d.counts;
  const objs = objectImpact(d.users);
  const by = (["people", "objects", "roles", "findings"] as const).find((x) => x === c.params.by) ?? "people";
  const tiles: [string, number, string][] = [["People lose access", k.users, k.users ? " ae-tile-bad" : ""], ["Objects affected", k.objects, ""],
    ["Kept another way", k.kept, ""], ["Nobody reaches", k.unreached, k.unreached ? " ae-tile-bad" : ""], ["Roles orphaned", k.orphans, k.orphans ? " ae-tile-warn" : ""],
    ["Findings fixed", k.fixed, ""], ["New findings", k.new, k.new ? " ae-tile-warn" : ""]];
  return (
    <>
      <p className="ae-answer"><b>{d.summary}.</b> A simulation: nothing changes in Snowflake.</p>
      <div className="ae-tiles">{tiles.map(([l, v, t]) => <div key={l} className={`ae-tile${t}`}><span className="ae-tile-l">{l}</span><span className="ae-tile-v">{v}</span></div>)}</div>
      <Card title="Impact" right={
          <FilterChips label="Group impact by" value={by} onPick={(x) => c.set({ by: x === "people" ? null : x })} items={[
            { key: "people", label: "People", count: d.users.length }, { key: "objects", label: "Objects", count: objs.length },
            { key: "roles", label: "Roles", count: d.roles.length }, { key: "findings", label: "Findings", count: d.findings.length }]} />}>
        {by === "people" && (d.users.length ? d.users.map((u) => <Person key={u.user} u={u} open={open === u.user} onPick={() => setOpen(open === u.user ? null : u.user)} />)
          : <EmptyState title="Nobody loses anything" />)}
        {by === "objects" && (objs.length || d.objects.length ? (
          <ul className="ae-plan-lose ae-plan-objs">
            {objs.map((x) => <li key={x.object}><button type="button" className="ae-link ae-mono" onClick={() => o.open(x.object)}>{x.object}</button><span className="ae-muted">{x.type.toLowerCase()}</span>
              <span><b>{x.people === 1 ? "1 person" : `${x.people} people`}</b> lose {x.privileges.join(", ")}</span></li>)}
            {d.objects.map((x) => <li key={`left:${x.object}`}><span className="ae-mono">{x.object}</span><span className="ae-muted">{x.type.toLowerCase()}</span>
              <span className="ae-bad">{[x.unreached && "nobody reaches it", x.ownerless && "no owner"].filter(Boolean).join(", ")}{x.sensitive ? " · sensitive" : ""}</span></li>)}
          </ul>) : <EmptyState title="No object loses a reader" />)}
        {by === "roles" && (d.roles.length ? (
          <ul className="ae-plan-lose">{d.roles.map((r) => <li key={r.role}><button type="button" className="ae-link ae-mono" onClick={() => o.open(r.role)}>{r.role}</button>
            <span className="ae-muted">{r.kind} · {[r.orphan && "orphan: no user or role holds it", r.unreached && "no user reaches it"].filter(Boolean).join(", ")}</span></li>)}</ul>
        ) : <EmptyState title="No role is left orphaned">Every role keeps a holder.</EmptyState>)}
        {by === "findings" && (d.findings.length ? (
          <ul className="ae-plan-lose">{d.findings.map((f, i) => (
            <li key={i}><span className={`ae-tag ae-tag-${f.status === "fixed" && !f.changed ? "ok" : "warn"}`}>{f.changed ? "Changed" : f.status === "fixed" ? "Fixed" : "New"}</span>
              <span>#{f.num} {f.title} <span className="ae-mono">({f.grantee.replace(/ \(user\)$/, "")})</span></span></li>))}</ul>
        ) : <EmptyState title="No finding changes" />)}
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
        : <EmptyState title="Add a change to see its impact">Pick a change above, or add fixes from findings on Risks & fixes.</EmptyState>}
    </>
  );
}
