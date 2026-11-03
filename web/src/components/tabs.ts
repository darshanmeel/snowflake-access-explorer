// Privilege tabs: order, labels, counts. The server sets row.tab; privTab is the fallback for rows without it.
import type { Account, PrivClass, PrivRow, ReachRow, Tab, TabKey } from "../api/types";

export const TAB_ORDER: TabKey[] = [
  "account", "granted", "database_roles", "usage", "warehouses", "execute", "read", "write", "own", "manage", "all",
];
export const TAB_LABEL: Record<TabKey, string> = {
  account: "Account", granted: "Granted roles", database_roles: "Database roles", usage: "Usage",
  warehouses: "Warehouses", execute: "Execute", read: "Read", write: "Write", own: "Own", manage: "Manage", all: "All",
};

const ROUTINES = new Set(["PROCEDURE", "FUNCTION", "TASK"]);

export function privTab(privilege: string, type: string, cls?: string): TabKey {
  const p = privilege.toUpperCase();
  const t = type.toUpperCase();
  if (t === "ACCOUNT" || cls === "admin") return "account";
  if (t === "WAREHOUSE") return "warehouses";
  if (t === "DATABASE_ROLE" || t === "DATABASE ROLE") return "database_roles";
  if (t === "ROLE") return "granted";
  if (p === "OWNERSHIP" || cls === "own") return "own";
  if (p.startsWith("EXECUTE") || (ROUTINES.has(t) && (p === "USAGE" || p === "OPERATE"))) return "execute";
  if (cls === "write") return "write";
  if (cls === "manage") return "manage";
  if (p === "USAGE" || p === "MONITOR" || cls === "use") return "usage";
  return "read";
}

export const tabOf = (r: PrivRow): TabKey => r.tab ?? privTab(r.privilege, r.type, r.cls);

/** Rows of one tab; hidden rows (database/schema USAGE under "Data only") show only in Usage. */
export function tabRows(rows: PrivRow[], tab: TabKey): PrivRow[] {
  if (tab === "all") return rows.filter((r) => !r.hidden);
  return rows.filter((r) => tabOf(r) === tab && (!r.hidden || tab === "usage"));
}

export function tabRoles(roles: ReachRow[], tab: TabKey): ReachRow[] {
  return tab === "granted" || tab === "database_roles" ? roles.filter((r) => r.tab === tab) : [];
}

export function accountCount(a?: Account | null): number {
  return a ? a.admin.length + a.privileges.length + a.public.length : 0;
}

/** Tabs with their counts; empty ones are left out, All stays. */
export function tabList(rows: PrivRow[], roles: ReachRow[] = [], account?: Account | null): Tab[] {
  return TAB_ORDER.map((key) => {
    let count = 0;
    if (key === "account") count = accountCount(account) || tabRows(rows, key).length;
    else if (key === "granted" || key === "database_roles") count = tabRoles(roles, key).length;
    else count = tabRows(rows, key).length;
    return { key, label: TAB_LABEL[key], count };
  }).filter((t) => t.count > 0 || t.key === "all");
}

/** One row per object: the strongest access (own > write > read; manage, use, admin kept as they are), every grant,
 * and the shortest path with the other distinct paths. SELECT + INSERT is write; OWNERSHIP is own. */
export interface ObjRow {
  object: string; label: string; type: string; access: PrivClass; grants: string[]; holder: string; depth: number;
  path: string[]; more: string[][]; count: number; sensitive: boolean;
}
const RANK: Record<PrivClass, number> = { use: 0, read: 1, manage: 2, write: 3, own: 4, admin: 5 };
export function byObject(rows: PrivRow[]): ObjRow[] {
  const m = new Map<string, ObjRow>();
  for (const r of [...rows].sort((a, b) => a.depth - b.depth)) {
    let o = m.get(r.object);
    if (!o) {
      o = { object: r.object, label: r.future_label ?? r.object, type: r.type, access: r.cls, grants: [], holder: r.holder,
        depth: r.depth, path: r.path, more: [], count: 0, sensitive: r.sensitive };
      m.set(r.object, o);
    } else if (o.more.length < 4 && ![o.path, ...o.more].some((p) => p.join(">") === r.path.join(">"))) o.more.push(r.path);
    if (RANK[r.cls] > RANK[o.access]) o.access = r.cls;
    if (!o.grants.includes(r.privilege)) o.grants.push(r.privilege);
    o.count = Math.max(o.count, r.count);
  }
  return [...m.values()];
}
