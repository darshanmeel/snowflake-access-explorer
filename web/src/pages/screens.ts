// Pure helpers of the Access graph (4), What they see (7) and Compare (9) screens.
import type { AccessObject, CompareChange, NodeKind, SeePage, WhatIfChange } from "../api/types";

export type GroupBy = "none" | "schema" | "type";

/** Access list group of one row: its schema (or the object itself when it has none), its type, or "" (no groups). */
export const groupKey = (x: Pick<AccessObject, "object" | "database" | "schema" | "type">, by: GroupBy) =>
  by === "schema" ? (x.schema ? `${x.database}.${x.schema}` : x.object) : by === "type" ? x.type : "";

/** Access list sorted by name (the server sends riskiest first). */
export const byName = <T extends Pick<AccessObject, "object">>(xs: T[]) => [...xs].sort((a, b) => a.object.localeCompare(b.object));

/** URL params that make a graph box the start: a table, a role or a person. */
export function startOf(kind: NodeKind | string, id: string): Record<string, string | null> {
  const none = { table: null, role: null, user: null, sel: null, focus: null }; // a new start: the whole graph
  if (kind === "user") return { ...none, user: id.replace(/ \(user\)$/, "") };
  if (kind === "object") return { ...none, table: id };
  return { ...none, role: id };
}

export interface Asked { user?: string; role?: string; object?: string }

/** The person or role and the object a page's URL names, over the ones before: kept until another one is picked. */
export function askedOf(page: string, p: Record<string, string>, before: Asked): Asked {
  const from = (user?: string, role?: string): Asked =>
    role ? { role, object: before.object } : user ? { user, object: before.object } : { ...before };
  if (page === "access" || page === "see" || page === "usage" || page === "graph") return from(p.user, p.role);
  if (page === "user") return from(p.name);
  if (page === "role") return from(undefined, p.name);
  if (page === "check" || page === "request") {
    const a = from(p.name ?? p.user, page === "check" ? p.role : p.for_role);
    return p.obj ? { ...a, object: p.obj } : a;
  }
  return page === "object" && p.name ? { ...before, object: p.name } : { ...before };
}

/** URL params a page opened from the side menu starts with: the person or role and the object asked about. */
export function startWith(page: string, a: Asked): Record<string, string> {
  const who: Record<string, string> = a.role ? { role: a.role } : a.user ? { user: a.user } : {};
  const obj: Record<string, string> = a.object ? { obj: a.object } : {};
  if (page === "access" || page === "see" || page === "usage" || page === "graph") return who;
  if (page === "check" || page === "request")
    return { ...(a.role ? { [page === "check" ? "role" : "for_role"]: a.role } : a.user ? { name: a.user } : {}), ...obj };
  return page === "object" && a.object ? { name: a.object } : {};
}

/** Node and edge ids drawn red when "Highlight risky paths" is on. */
export function riskIds(edges: Record<string, string>, nodes: Record<string, string>): Set<string> {
  return new Set([...Object.keys(edges), ...Object.keys(nodes)]);
}

const n = (k: number, w: string) => `${k} ${w}${k === 1 ? "" : "s"}`;

/** "all rows" / "all 5 sensitive columns in clear" / "3 of those columns have no masking policy at all." */
export function seeSentence(c: NonNullable<SeePage["counts"]>): { rows: string; cols: string; fix: string } {
  const rows = c.rows ? `fewer rows in ${n(c.rows, "object")} (row policy)` : "all rows";
  const cols = !c.columns ? "no sensitive columns" : c.clear === c.columns ? `all ${n(c.columns, "sensitive column")} in clear`
    : c.clear ? `${c.clear} of ${n(c.columns, "sensitive column")} in clear` : `every sensitive column masked`;
  const fix = c.unprotected ? `${c.unprotected} of those column${c.unprotected === 1 ? " has" : "s have"} no masking policy at all.` : "";
  return { rows, cols, fix };
}

/** Compare's "Remove A's extras" as What if changes (simulation only); grants are not simulated. */
export function whatIfOf(cs: CompareChange[]): WhatIfChange[] {
  return cs.flatMap((c): WhatIfChange[] => {
    if (c.op !== "revoke") return [];
    if (c.role) return [c.toUser ? { op: "revoke_role_from_user", role: c.role, user: c.to } : { op: "revoke_role_from_role", role: c.role, grantee: c.to }];
    return c.privilege && c.object ? [{ op: "revoke_priv", role: c.to, privilege: c.privilege, object: c.object }] : [];
  });
}
