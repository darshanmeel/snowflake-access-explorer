// What if: pick grants to take away and see who loses what. A simulation in access.py only; this app never runs the
// REVOKE text, it only prints it for infrastructure as code. The changes live in the URL (changes=<JSON list>).
import { useState } from "react";
import { download, useApi } from "../api/client";
import type { ListItem, WhatIfChange, WhatIfFinding, WhatIfObjectRow, WhatIfOp, WhatIfPage, WhatIfUser } from "../api/types";
import { Banner, Card, DataTable, KpiRow, Tabs } from "../components";
import { apiParams, useApp, useOpen, type Ctx } from "../ctx";
import { col, Controls, Head, Load, NameLink, PathCell, Pick, Sel } from "./common";

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

const text = (ch: WhatIfChange) => {
  switch (ch.op) {
    case "revoke_role_from_user": return `Revoke ${ch.role} from user ${ch.user}`;
    case "revoke_role_from_role": return `Revoke ${ch.role} from role ${ch.grantee}`;
    case "revoke_priv": return `Revoke ${ch.privilege} on ${ch.object} from ${ch.role}`;
    case "drop_role": return `Drop role ${ch.role}`;
    default: return "Empty PUBLIC";
  }
};

function Builder({ onAdd }: { onAdd: (ch: WhatIfChange) => void }) {
  const c = useApp();
  const [op, setOp] = useState<WhatIfOp>("revoke_role_from_user");
  const [role, setRole] = useState("");
  const [other, setOther] = useState("");
  const [priv, setPriv] = useState("SELECT");
  const roles = useApi<{ items: ListItem[] }>("list", { what: "roles", view: c.view });
  const users = useApi<{ items: ListItem[] }>(op === "revoke_role_from_user" ? "list" : null, { what: "users", view: c.view });
  const objs = useApi<{ items: ListItem[] }>(op === "revoke_priv" ? "list" : null, { what: "objects", view: c.view });
  const ids = (s: typeof roles) => s.data?.items.map((i) => i.id) ?? [];
  const ch: WhatIfChange | null =
    op === "empty_public" ? { op } :
    !role ? null :
    op === "drop_role" ? { op, role } :
    !other ? null :
    op === "revoke_role_from_user" ? { op, role, user: other } :
    op === "revoke_role_from_role" ? { op, role, grantee: other } :
    { op, role, privilege: priv, object: other };
  return (
    <Controls>
      <Sel label="Change" value={op} onPick={(v) => { setOp(v as WhatIfOp); setOther(""); }} options={OPS} />
      {op !== "empty_public" && <Pick label={op === "revoke_role_from_role" ? "Role taken away" : "Role"} value={role} options={ids(roles)} onPick={setRole} />}
      {op === "revoke_role_from_user" && <Pick label="From user" value={other} options={ids(users)} onPick={setOther} />}
      {op === "revoke_role_from_role" && <Pick label="From role" value={other} options={ids(roles)} onPick={setOther} />}
      {op === "revoke_priv" && <Sel label="Privilege" value={priv} onPick={setPriv} options={PRIVS.map((p): [string, string] => [p, p])} />}
      {op === "revoke_priv" && <Pick label="On object" value={other} width={340} options={ids(objs)} onPick={setOther} />}
      <button className="ae-btn" disabled={!ch} onClick={() => ch && onAdd(ch)}>Add</button>
    </Controls>
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

function UserRow({ u, refs }: { u: WhatIfUser; refs: WhatIfPage["refs"] }) {
  const [on, setOn] = useState(false);
  return (
    <div className="ae-gg">
      <div className="ae-gg-head">
        <button className="ae-gg-toggle" onClick={() => setOn(!on)} aria-expanded={on}>{on ? "▾" : "▸"} <strong>{u.user}</strong></button>
        <span className="ae-muted">{u.status}</span>
        {u.objects > 0 && <span className="ae-tag ae-tag-bad">loses {u.lost} privilege{u.lost === 1 ? "" : "s"} on {u.objects} object{u.objects === 1 ? "" : "s"}</span>}
        {u.kept > 0 && <span className="ae-tag ae-tag-ok">keeps {u.kept} another way</span>}
      </div>
      {on && (
        <div className="ae-wi-user">
          {u.lost_rows.length > 0 && <><h4>Loses</h4><ObjRows rows={u.lost_rows} refs={refs} /></>}
          {u.kept_rows.length > 0 && <><h4>Keeps through another path</h4><ObjRows rows={u.kept_rows} refs={refs} kept /></>}
          {u.kept_roles.length > 0 && <><h4>Roles still reached</h4>{u.kept_roles.map((k) => <div key={k.role}><PathCell path={k.via} refs={refs} /></div>)}</>}
        </div>
      )}
    </div>
  );
}

function Result({ d }: { d: WhatIfPage }) {
  const c = useApp();
  const o = useOpen(d.refs);
  const [tab, setTab] = useState("users");
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
      <Banner tone={k.users || k.unreached ? "warn" : "info"} title="If these changes were made" lines={[d.summary, "A simulation: nothing changes in Snowflake."]} />
      <KpiRow items={[
        { label: "Users lose access", value: k.users }, { label: "Objects lost", value: k.objects }, { label: "Kept another way", value: k.kept },
        { label: "Objects nobody reaches", value: k.unreached }, { label: "Roles orphaned", value: k.orphans },
        { label: "Findings fixed", value: k.fixed }, { label: "New findings", value: k.new },
      ]} />
      <Tabs active={tab} onChange={setTab} tabs={[
        { key: "users", label: "Users", count: d.users.length },
        { key: "objects", label: "Objects", count: d.objects.length, tone: k.unreached ? "bad" : null },
        { key: "roles", label: "Roles", count: d.roles.length },
        { key: "findings", label: "Findings", count: d.findings.length },
        { key: "fix", label: "Text to apply" },
      ]} />
      {tab === "users" && (
        <Card>
          {d.users.length ? d.users.map((u) => <UserRow key={u.user} u={u} refs={d.refs} />) : <p className="ae-muted">No user loses anything.</p>}
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
        </Card>
      )}
      {tab === "findings" && (
        <Card title="Rule findings that change" sub={`${k.fixed} go away, ${k.new} new, ${k.changed} changed.`}>
          <DataTable csv="whatif_findings.csv" rows={d.findings} columns={fcols} onRowClick={(r: WhatIfFinding) => o.open(r.grantee)} />
        </Card>
      )}
      {tab === "fix" && (
        <Card title="Text for your infrastructure as code" sub="This app never runs it. Apply the change in your RBAC code; manual grants are removed by reconciliation.">
          <pre className="ae-code">{d.iac}</pre>
          {d.sql && <><p className="ae-muted">The same as SQL:</p><pre className="ae-code">{d.sql}</pre></>}
        </Card>
      )}
      <p><button className="ae-btn" onClick={() => download("whatif.csv", apiParams(c), "what_if.csv")}>Download CSV</button></p>
    </>
  );
}

export function WhatIfPageView() {
  const c = useApp();
  const list = changesOf(c);
  const put = (l: WhatIfChange[]) => c.set({ changes: l.length ? JSON.stringify(l) : null });
  const s = useApi<WhatIfPage>(list.length ? "whatif" : null, apiParams(c));
  return (
    <>
      <Head title="What if" sub="Take grants away in a simulation and see who loses what. Nothing changes in Snowflake." />
      <Card title="Changes">
        <Builder onAdd={(ch) => put([...list.filter((x) => text(x) !== text(ch)), ch])} />
        {list.length > 0
          ? <div className="ae-chips">{list.map((x) => (
              <button key={text(x)} className="ae-chip ae-chip-plain" onClick={() => put(list.filter((y) => y !== x))} title="Remove">{text(x)} ×</button>
            ))}</div>
          : <p className="ae-muted">Add one or more changes. You can also start from a role page, a path or a finding ("What if revoked?").</p>}
      </Card>
      {list.length > 0 && <Load s={s}>{(d) => <Result d={d} />}</Load>}
    </>
  );
}
