// Who can reach an object, grouped: users who come in through the same chain are one row ("via GRP_X · 14 users (11
// active, 1 dormant) · SELECT · depth 10") with the chain drawn once; expanding shows them as status chips, problem
// statuses first. Roles keep a row each. "By user" is the flat list.
import { useMemo, useState } from "react";
import type { GranteeRow, PrivClass, UserStatus } from "../api/types";
import { DataTable, type Column } from "./DataTable";
import { Tabs } from "./parts";
import { PathText } from "./PathText";

export interface GranteeGroup {
  key: string; entry: string; chain: string[]; users: GranteeRow[]; role: GranteeRow | null;
  privileges: string[]; cls: PrivClass; depth: number; status: Partial<Record<UserStatus, number>>;
}

const RANK: Record<string, number> = { use: 0, read: 1, manage: 2, write: 3, own: 4, admin: 5 };
const BAD: UserStatus[] = ["disabled", "dormant", "never", "active"];
const isUser = (r: GranteeRow) => r.kind === "user";

/** Users sharing the chain after themselves (and the privileges) form one group; each role is its own group. */
export function groupGrantees(rows: GranteeRow[]): GranteeGroup[] {
  const m = new Map<string, GranteeGroup>();
  for (const r of rows) {
    const privs = r.privileges.map((p) => p.privilege);
    const key = isUser(r) ? `${r.path.slice(1).join(">")}|${privs.join(",")}` : `role:${r.id}`;
    let g = m.get(key);
    if (!g) {
      const cls = r.privileges.reduce<PrivClass>((c, p) => (RANK[p.cls] > RANK[c] ? p.cls : c), r.privileges[0]?.cls ?? "use");
      g = { key, entry: isUser(r) ? r.path[1] ?? r.grantee : r.grantee, chain: isUser(r) ? r.path.slice(1) : r.path,
        users: [], role: isUser(r) ? null : r, privileges: privs, cls, depth: r.depth, status: {} };
      m.set(key, g);
    }
    if (isUser(r)) {
      g.users.push(r);
      const s = r.status ?? "active";
      g.status[s] = (g.status[s] ?? 0) + 1;
    }
  }
  const order = (g: GranteeGroup) => (g.role ? 1 : 0);
  return [...m.values()].sort((a, b) => order(a) - order(b) || b.users.length - a.users.length || a.depth - b.depth);
}

export const StatusDot = ({ s }: { s: UserStatus | null }) =>
  s ? <span className={`ae-dot ae-dot-${s}`} title={s} aria-label={s} /> : null;

function statusText(st: GranteeGroup["status"]) {
  return BAD.slice().reverse().filter((s) => st[s]).map((s) => `${st[s]} ${s}`).join(", ");
}

function Group({ g, kinds, onOpen }: { g: GranteeGroup; kinds: Record<string, string>; onOpen?: (id: string) => void }) {
  const [on, setOn] = useState(false);
  const n = g.users.length;
  const users = [...g.users].sort((a, b) => BAD.indexOf(a.status ?? "active") - BAD.indexOf(b.status ?? "active") || a.grantee.localeCompare(b.grantee));
  const bad = (g.status.disabled ?? 0) + (g.status.dormant ?? 0);
  return (
    <div className={`ae-gg${g.cls === "admin" ? " ae-tone-bad" : ""}`}>
      <div className="ae-gg-head">
        {g.role
          ? <button className={`ae-chip ae-chip-${kinds[g.role.id] ?? g.role.kind}`} onClick={() => onOpen?.(g.role!.id)}>{g.role.grantee}</button>
          : <button className="ae-gg-toggle" onClick={() => setOn(!on)} aria-expanded={on}>
              {on ? "▾" : "▸"} via <strong>{g.entry}</strong> · {n} user{n === 1 ? "" : "s"}
              <span className={bad ? "ae-gg-st ae-warn" : "ae-gg-st"}> ({statusText(g.status)})</span>
            </button>}
        <span className={`ae-pclass ae-pclass-${g.cls}`}>{g.privileges.join(", ")}</span>
        <span className="ae-muted">depth {g.depth}</span>
        <span className="ae-gg-path"><PathText path={g.chain} kinds={kinds} onOpen={onOpen} cls={g.cls} grants={g.privileges} /></span>
      </div>
      {on && (
        <div className="ae-chips ae-gg-users">
          {users.map((u) => (
            <button key={u.id} className={`ae-chip ae-chip-user ae-st-${u.status ?? "active"}`} onClick={() => onOpen?.(u.id)} title={`${u.grantee} · ${u.status ?? ""}`}>
              <StatusDot s={u.status} />{u.grantee}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function GroupedGrantees({ rows, kinds = {}, onOpen, csv }: { rows: GranteeRow[]; kinds?: Record<string, string>; onOpen?: (id: string) => void; csv: string }) {
  const [view, setView] = useState("groups");
  const groups = useMemo(() => groupGrantees(rows), [rows]);
  const cols: Column<GranteeRow>[] = [
    { key: "g", label: "Grantee", get: (r) => r.grantee, wrap: "nowrap",
      render: (r) => <button className={`ae-link ae-k-${kinds[r.id] ?? r.kind}`} onClick={() => onOpen?.(r.id)}>{r.grantee}</button> },
    { key: "k", label: "Kind", get: (r) => r.kind_label, wrap: "nowrap" },
    { key: "s", label: "Status", get: (r) => r.status ?? "", wrap: "nowrap", render: (r) => r.status && <><StatusDot s={r.status} /> {r.status}</> },
    { key: "p", label: "Privileges", get: (r) => r.privileges.map((p) => p.privilege).join(", "), wrap: "wrap" },
    { key: "d", label: "Depth", get: (r) => r.depth, num: true },
    { key: "n", label: "Paths", get: (r) => r.count, num: true },
    { key: "path", label: "Shortest path", get: (r) => r.path.join(" > "), wrap: "nowrap", render: (r) => <PathText path={r.path} kinds={kinds} onOpen={onOpen} /> },
  ];
  const nUsers = rows.filter(isUser).length;
  return (
    <div className="ae-grantees">
      <Tabs active={view} onChange={setView} tabs={[{ key: "groups", label: "By path", count: groups.length }, { key: "flat", label: "By user or role", count: rows.length }]} />
      {view === "groups"
        ? <>
            <p className="ae-muted">{nUsers} users in {groups.filter((g) => !g.role).length} groups by the chain they come through; {groups.filter((g) => g.role).length} roles.</p>
            {groups.map((g) => <Group key={g.key} g={g} kinds={kinds} onOpen={onOpen} />)}
          </>
        : <DataTable columns={cols} rows={rows} csv={csv} sort={{ key: "d" }} rowTone={(r) => (r.kind === "admin" ? "bad" : null)} />}
    </div>
  );
}
