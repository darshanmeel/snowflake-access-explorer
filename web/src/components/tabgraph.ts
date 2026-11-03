// The small diagram of one privilege tab, built from the tab's rows (pure; the server may send its own instead).
import type { Account, Graph, GraphNode, PrivRow, ReachRow, Refs, TabKey } from "../api/types";
import { MAX_BOXES, pathGraph, type PathIn } from "./graphs";
import { tabRoles, tabRows } from "./tabs";

export interface TabGraphIn {
  tab: TabKey;
  rows: PrivRow[];
  roles?: ReachRow[];
  account?: Account | null;
  refs?: Refs | null;
  max?: number;
}

const PRIV = "priv:"; // account privileges are boxes too, keyed apart from object names

export function tabPaths({ tab, rows, roles = [], account }: TabGraphIn): PathIn[] {
  if (tab === "granted" || tab === "database_roles") return tabRoles(roles, tab).map((r) => ({ path: r.path }));
  if (tab === "account") {
    const start = rows[0]?.path[0] ?? roles[0]?.path[0] ?? account?.admin[0]?.path[0] ?? account?.privileges[0]?.path[0] ?? "";
    const out: PathIn[] = [];
    for (const a of account?.admin ?? []) out.push({ path: a.path });
    for (const p of account?.privileges ?? []) {
      if (!p.via_public) out.push({ path: [...p.path, PRIV + p.privilege], cls: "admin", privilege: p.privilege });
    }
    for (const p of account?.public ?? []) out.push({ path: [start, "PUBLIC", PRIV + p], cls: "admin", privilege: p });
    if (!account) {
      for (const r of tabRows(rows, "account")) {
        out.push({ path: [...r.path.slice(0, -1), PRIV + r.privilege], cls: "admin", privilege: r.privilege });
      }
    }
    return out.filter((p) => p.path[0]);
  }
  return tabRows(rows, tab).map((r) => ({ path: r.path, cls: r.cls, privilege: r.privilege }));
}

export function tabGraph(i: TabGraphIn): Graph {
  const refs = i.refs;
  const kinds: Record<string, string> = { ...(refs?.kinds ?? {}) };
  for (const r of i.roles ?? []) kinds[r.role] ??= r.kind;
  for (const a of i.account?.admin ?? []) kinds[a.role] = "admin";
  const sensitive = new Set(refs?.sensitive ?? []);
  const disabled = new Set(refs?.disabled ?? []);
  const rowOf = new Map(i.rows.map((r) => [r.object, r]));
  const node = (n: GraphNode): GraphNode => {
    if (n.id.startsWith(PRIV)) {
      return { ...n, kind: "admin", label: n.id.slice(PRIV.length), sub: "account privilege", db: null, marks: ["bad"], action: null };
    }
    const marks = [...n.marks];
    if (sensitive.has(n.id) || rowOf.get(n.id)?.sensitive) marks.push("sensitive");
    if (disabled.has(n.id)) marks.push("disabled");
    if (n.kind === "object") {
      const r = rowOf.get(n.id);
      const type = refs?.types[n.id] ?? r?.type ?? null;
      const label = refs?.labels[n.id] ?? r?.future_label ?? r?.name ?? n.id;
      const where = r ? [r.database, r.schema].filter(Boolean).join(".") : n.id.split(".").slice(0, -1).join(".");
      return {
        ...n, label, type, db: r?.database || n.db, schema: r?.schema || null, marks,
        sub: [type?.toLowerCase(), where].filter(Boolean).join(" · ") || null,
        action: { kind: "page", page: "object", params: { name: n.id } },
      };
    }
    const page = n.kind === "user" ? "user" : "role";
    return { ...n, marks, action: { kind: "page", page, params: { name: n.id } } };
  };
  const g = pathGraph(tabPaths(i), {
    kinds, max: i.max ?? MAX_BOXES, node,
    objectLabel: i.tab === "account" ? "Account privileges" : "Objects",
  });
  return g;
}
