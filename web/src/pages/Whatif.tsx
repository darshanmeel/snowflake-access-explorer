// What if: pick grants to take away and see who loses what. A simulation in access.py only; this app never runs the
// REVOKE text, it only prints it for infrastructure as code. The changes live in the URL (changes=<JSON list>).
import { useState } from "react";
import { download, useApi } from "../api/client";
import type { ListItem, WhatIfChange, WhatIfFinding, WhatIfObjectRow, WhatIfOp, WhatIfPage, WhatIfUser, WhatIfUserRows } from "../api/types";
import { Card, CodeOutput, DataTable, EmptyState, Fold, Tabs, useCsv } from "../components";
import { apiParams, useApp, useOpen, type Ctx } from "../ctx";
import { col, Head, Load, NameLink, PathCell, Pick, Sel } from "./common";
import { Gone, LoseKeep, Outcome, PlanTab } from "./Plan";
import { addTo, changeText, plan, planTexts, useSaved } from "./changeplan";

const OPS: [WhatIfOp, string][] = [
  ["revoke_role_from_user", "Revoke a role from a user"],
  ["revoke_role_from_role", "Revoke a role from a role"],
  ["revoke_priv", "Revoke a privilege on an object"],
  ["drop_role", "Drop a role"],
  ["empty_public", "Empty PUBLIC (remove all its grants)"],
];
const PRIVS = ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "USAGE", "OWNERSHIP", "OPERATE", "MONITOR", "MODIFY", "CREATE TABLE", "CREATE VIEW"];

export const changesOf = (c: Ctx): WhatIfChange[] => {
  try { const v = JSON.parse(c.params.changes ?? "[]"); return Array.isArray(v) ? v : []; } catch { return []; }
};

/** Opens the What-if page with these changes (added to the ones already picked when add is set). */
export function whatIf(c: Ctx, ch: WhatIfChange[]) {
  c.nav("whatif", { changes: JSON.stringify(ch) });
}

/** A small "What if revoked?" button for entity pages, findings and paths. */
export function WhatIfButton({ ch, label = "What if revoked?" }: { ch: WhatIfChange[]; label?: string }) {
  const c = useApp();
  return <button className="ae-btn ae-btn-s" title="Simulate it: nothing changes in Snowflake" onClick={() => whatIf(c, ch)}>{label}</button>;
}

/** The change a path suggests: the first link after its start (user > role, or role > role). */
export function changeOfPath(path: string[], kinds: Record<string, string>): WhatIfChange | null {
  if (path.length < 2 || kinds[path[1]] === "object") return null;
  const start = path[0];
  return kinds[start] === "user" || / \(user\)$/.test(start)
    ? { op: "revoke_role_from_user", role: path[1], user: start.replace(/ \(user\)$/, "") }
    : { op: "revoke_role_from_role", role: path[1], grantee: start };
}

const text = changeText;

function Builder({ onAdd }: { onAdd: (ch: WhatIfChange) => void }) {
  const c = useApp();
  const [op, setOp] = useState<WhatIfOp>("revoke_role_from_user");
  const [role, setRole] = useState("");
  const [other, setOther] = useState("");
  const [priv, setPriv] = useState("SELECT");
  // only who reaches the chosen role, directly first, then through other roles (cut where it is granted)
  const holders = useApi<{ items: ListItem[] }>(
    role && (op === "revoke_role_from_user" || op === "revoke_role_from_role") ? "list" : null,
    { what: op === "revoke_role_from_user" ? "user_holders" : "role_holders", role, view: c.view });
  const ids = (s: typeof holders) => s.data?.items.map((i) => i.id) ?? [];
  const nDirect = holders.data?.items.filter((i) => i.type === "direct").length ?? 0;
  const nVia = (holders.data?.items.length ?? 0) - nDirect;
  const holderHint = !role ? "pick a role first" : holders.data ? `${nDirect} direct · ${nVia} through other roles` : "…";
  const ready = op === "revoke_priv" || (!holders.loading && !!holders.data); // not the last role's holders
  const missing = op !== "revoke_priv" && ready && !!role && !!other && !ids(holders).includes(other); // picked for another role: kept, but nothing to revoke
  const ch: WhatIfChange | null =
    op === "empty_public" ? { op } :
    !role ? null :
    op === "drop_role" ? { op, role } :
    !other || !ready || missing ? null :
    op === "revoke_role_from_user" ? { op, role, user: other } :
    op === "revoke_role_from_role" ? { op, role, grantee: other } :
    { op, role, privilege: priv, object: other };
  return (
    <div className="ae-ask" role="form" aria-label="Add a change">
      <Sel label="Change" value={op} onPick={(v) => { setOp(v as WhatIfOp); setOther(""); }} options={OPS} />
      {op !== "empty_public" && <Pick label={op === "revoke_role_from_role" ? "Role taken away" : "Role"} value={role} what="roles" onPick={setRole} />}
      {(op === "revoke_role_from_user" || op === "revoke_role_from_role") && <span className="ae-ask-w">from</span>}
      {op === "revoke_role_from_user" && <Pick label={`From user (${holderHint})`} value={other} options={ids(holders)} onPick={setOther} />}
      {op === "revoke_role_from_role" && <Pick label={`From role (${holderHint})`} value={other} options={ids(holders)} onPick={setOther} />}
      {op === "revoke_priv" && <Sel label="Privilege" value={priv} onPick={setPriv} options={PRIVS.map((p): [string, string] => [p, p])} />}
      {op === "revoke_priv" && <Pick label="On object" value={other} width={340} what="objects" onPick={setOther} />}
      <button className="ae-btn" disabled={!ch} onClick={() => ch && onAdd(ch)}>Add</button>
      {missing && <span className="ae-muted" role="status">{other} does not hold {role}: pick someone who does, or another role.</span>}
    </div>
  );
}

function ObjRows({ rows, refs, kept }: { rows: WhatIfObjectRow[]; refs: WhatIfPage["refs"]; kept?: boolean }) {
  return (
    <DataTable csv={kept ? "whatif_kept.csv" : "whatif_lost.csv"} rows={rows}
      columns={[
        col("o", "Object", (r: WhatIfObjectRow) => r.object, { wrap: "nowrap", render: (r: WhatIfObjectRow) => <NameLink id={r.object} refs={refs} /> }),
        col("t", "Type", (r: WhatIfObjectRow) => r.type, { wrap: "nowrap" }),
        col("p", "Privileges", (r: WhatIfObjectRow) => r.privileges.join(", "), { wrap: "wrap" }),
        col("b", kept ? "Path before" : "Path lost", (r: WhatIfObjectRow) => r.path.join(" > "), { wrap: "nowrap", render: (r: WhatIfObjectRow) => <PathCell path={r.path} refs={refs} /> }),
        ...(kept ? [col("v", "Path left", (r: WhatIfObjectRow) => (r.via ?? []).join(" > "), { wrap: "nowrap", render: (r: WhatIfObjectRow) => <PathCell path={r.via ?? []} refs={refs} /> })] : []),
      ]} />
  );
}

/** One person: counts, and their rows fetched when opened (a big plan has thousands of people). */
function UserRow({ u, refs, changes }: { u: WhatIfUser; refs: WhatIfPage["refs"]; changes: string }) {
  const c = useApp();
  const [on, setOn] = useState(false);
  const r = useApi<{ user: WhatIfUserRows }>(on ? "whatif" : null, { view: c.view, changes, user: u.user });
  return (
    <div className="ae-gg">
      <div className="ae-gg-head">
        <button className="ae-gg-toggle" onClick={() => setOn(!on)} aria-expanded={on}>{on ? "▾" : "▸"} <strong>{u.user}</strong></button>
        <span className="ae-muted">{u.status}</span>
        {u.objects > 0 && <span className="ae-tag ae-tag-bad">loses {u.lost} privilege{u.lost === 1 ? "" : "s"} on {u.objects} object{u.objects === 1 ? "" : "s"}</span>}
        {u.kept > 0 && <span className="ae-tag ae-tag-ok">keeps {u.kept} another way</span>}
      </div>
      {on && <Load s={r}>{({ user: x }) => (
        <div className="ae-wi-user">
          {x.lost_rows.length > 0 && <><h4>Loses</h4><ObjRows rows={x.lost_rows} refs={refs} />
            {x.lost_rows.length < x.objects && <p className="ae-muted">First {x.lost_rows.length} of {x.objects.toLocaleString("en-US")} objects: the CSV has all.</p>}</>}
          {x.kept_rows.length > 0 && <><h4>Keeps through another path</h4><ObjRows rows={x.kept_rows} refs={refs} kept /></>}
          {x.kept_roles.length > 0 && <><h4>Roles still reached</h4>{x.kept_roles.map((k) => <div key={k.role}><PathCell path={k.via} refs={refs} /></div>)}</>}
        </div>
      )}</Load>}
    </div>
  );
}

function Result({ d, list }: { d: WhatIfPage; list: WhatIfChange[] }) {
  const c = useApp();
  const o = useOpen(d.refs);
  const tab = ["roles", "findings", "users"].includes(c.params.part ?? "") ? c.params.part! : "objects";
  const k = d.counts;
  const fcols = [
    col("s", "Status", (r: WhatIfFinding) => (r.changed ? "changed" : r.status), { wrap: "nowrap",
      render: (r: WhatIfFinding) => <span className={`ae-tag ae-tag-${r.status === "fixed" ? "ok" : "bad"}`}>{r.changed ? "changed" : r.status === "fixed" ? "goes away" : "new"}</span> }),
    col("n", "Rule", (r: WhatIfFinding) => Number(r.num), { num: true }),
    col("v", "Severity", (r: WhatIfFinding) => r.severity, { wrap: "nowrap", render: (r: WhatIfFinding) => <span className={`ae-sevpill ae-sev-${r.severity}`}>{r.severity}</span> }),
    col("t", "Finding", (r: WhatIfFinding) => r.title, { wrap: "wrap" }),
    col("g", "Grantee", (r: WhatIfFinding) => r.grantee, { wrap: "nowrap", render: (r: WhatIfFinding) => <NameLink id={r.grantee} refs={d.refs} /> }),
    col("d", "Detail", (r: WhatIfFinding) => r.detail, { wrap: "wrap" }),
  ];
  return (
    <>
      <Outcome d={d} changes={list} />
      <Fold label="Objects, roles and findings touched, every person" on={!!c.params.part}>
      <Tabs nav={2} active={tab} onChange={(t) => c.set({ part: t === "objects" ? null : t })} tabs={[
        { key: "objects", label: "Objects", count: d.objects_total, tone: k.unreached ? "bad" : null },
        { key: "roles", label: "Roles", count: d.roles_total, tone: k.orphans ? "warn" : null },
        { key: "findings", label: "Findings", count: d.findings_total },
        { key: "users", label: "Every person", count: d.users_total },
      ]} />
      {tab === "users" && (
        <Card title="One row per person, with every path" sub={d.rows_capped ? `A person lists at most ${c.meta.limits.max_paths} objects: the CSV has all.` : undefined}>
          <LoseKeep d={d} />
          {d.users.map((u) => <UserRow key={u.user} u={u} refs={d.refs} changes={JSON.stringify(list)} />)}
          {d.users_total > d.users.length && <p className="ae-muted">First {d.users.length} of {d.users_total} people, most lost first: the CSV has all.</p>}
        </Card>
      )}
      {tab === "objects" && (
        <Card title="Objects left behind" sub="Nobody reaches them any more, or they are left without an owner.">
          <DataTable csv="whatif_objects.csv" rows={d.objects} columns={[
            col("o", "Object", (r: WhatIfPage["objects"][number]) => r.object, { wrap: "nowrap", render: (r: WhatIfPage["objects"][number]) => <NameLink id={r.object} refs={d.refs} /> }),
            col("t", "Type", (r: WhatIfPage["objects"][number]) => r.type, { wrap: "nowrap" }),
            col("u", "Nobody reaches it", (r: WhatIfPage["objects"][number]) => (r.unreached ? "yes" : ""), { wrap: "nowrap" }),
            col("w", "No owner", (r: WhatIfPage["objects"][number]) => (r.ownerless ? "yes" : ""), { wrap: "nowrap" }),
            col("s", "Sensitive", (r: WhatIfPage["objects"][number]) => (r.sensitive ? "yes" : ""), { wrap: "nowrap" }),
          ]} />
          {d.objects_total > d.objects.length && <p className="ae-muted">First {d.objects.length} of {d.objects_total} objects: the CSV has all.</p>}
        </Card>
      )}
      {tab === "roles" && (
        <Card title="Roles left behind" sub="Orphan: no user or role holds it. Unreached: no user gets to it.">
          <DataTable csv="whatif_roles.csv" rows={d.roles} columns={[
            col("r", "Role", (r: WhatIfPage["roles"][number]) => r.role, { wrap: "nowrap", render: (r: WhatIfPage["roles"][number]) => <NameLink id={r.role} refs={d.refs} /> }),
            col("k", "Kind", (r: WhatIfPage["roles"][number]) => r.kind, { wrap: "nowrap" }),
            col("o", "Orphan", (r: WhatIfPage["roles"][number]) => (r.orphan ? "yes" : ""), { wrap: "nowrap" }),
            col("u", "No user reaches it", (r: WhatIfPage["roles"][number]) => (r.unreached ? "yes" : ""), { wrap: "nowrap" }),
          ]} />
          {d.roles_total > d.roles.length && <p className="ae-muted">First {d.roles.length} of {d.roles_total} roles: the CSV has all.</p>}
        </Card>
      )}
      {tab === "findings" && (
        <Card title="Rule findings that change" sub={`${k.fixed} go away, ${k.new} new, ${k.changed} changed.`}>
          <DataTable csv="whatif_findings.csv" rows={d.findings} columns={fcols} onRowClick={(r: WhatIfFinding) => o.open(r.grantee)} />
          {d.findings_total > d.findings.length && <p className="ae-muted">First {d.findings.length} of {d.findings_total} findings: the CSV has all.</p>}
        </Card>
      )}
      </Fold>
    </>
  );
}

export function WhatIfPageView() {
  const c = useApp();
  const list = changesOf(c);
  const put = (l: WhatIfChange[]) => c.set({ changes: l.length ? JSON.stringify(l) : null });
  const saved = useSaved(plan);
  // the plan first; a link with changes opens Add a change
  const show = c.params.show === "plan" || c.params.show === "text" || c.params.show === "changes" ? c.params.show : list.length ? "changes" : "plan";
  const every = addTo(saved, list);
  const tx = useApi<WhatIfPage>(show === "text" && every.length ? "whatif" : null, { view: c.view, changes: JSON.stringify(every) });
  const s = useApi<WhatIfPage>(list.length && show === "changes" ? "whatif" : null, apiParams(c));
  const csvOn = useCsv();
  return (
    <>
      <Head title="Change plan" quiet sub="Take grants away in a simulation and see who loses what. Nothing changes in Snowflake."
        right={<>
          {csvOn && list.length > 0 && <button className="ae-btn" onClick={() => download("whatif.csv", apiParams(c), "what_if.csv")}>Download CSV</button>}
          <button className="ae-btn" onClick={() => c.nav("rules", { show: "fixes" })}>← Risks</button></>} />
      <Tabs nav active={show} onChange={(k) => c.set({ show: k, by: null, part: null })} tabs={[
        { key: "plan", label: "What happens", count: saved.length || null },
        { key: "changes", label: "Add a change", count: list.length || null },
        { key: "text", label: "Text to apply" },
      ]} />
      {show === "plan" && <PlanTab fromUrl={list} result={(d, l) => <Result d={d} list={l} />} />}
      {show === "text" && (every.length ? <Load s={tx}>{(d) => <><Gone d={d} /><p className="ae-answer">{d.changes.length} {d.changes.length === 1 ? "change" : "changes"} for your RBAC code</p>
        <Card title="Text to apply"><CodeOutput changes={[]} name="what_if" texts={planTexts(d.changes.map((x) => x.change), d.sql)} /></Card></>}</Load>
        : <EmptyState title="No change yet" art="plan">Add one on Add a change.</EmptyState>)}
      {show === "changes" && <>
      {!list.length && <p className="ae-answer">Add a change, see who it hits before it is written down</p>}
      <Card title="Pick" right={list.length > 0 && <button className="ae-btn" onClick={() => { plan.set(addTo(plan.get(), list)); c.set({ show: "plan" }); }}>Add to the change plan</button>}>
        <Builder onAdd={(ch) => put([...list.filter((x) => text(x) !== text(ch)), ch])} />
        {list.length > 0
          ? <div className="ae-chips">{list.map((x) => (
              <button key={text(x)} className="ae-chip ae-chip-plain" onClick={() => put(list.filter((y) => y !== x))} title="Remove">{text(x)} ×</button>
            ))}</div>
          : <EmptyState title="No change yet" art="plan">Or start from a role, a path or a finding ("What if revoked?").</EmptyState>}
      </Card>
      {list.length > 0 && <Load s={s}>{(d) => <><Gone d={d} />{(d.changes.length > 0 || !d.gone?.length) && <Result d={d} list={list} />}</>}</Load>}
      </>}
    </>
  );
}
