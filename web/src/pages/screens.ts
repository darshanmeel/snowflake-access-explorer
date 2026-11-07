// Pure helpers of the Access graph (4), What they see (7) and Compare (9) screens.
import type { CompareChange, NodeKind, SeePage, WhatIfChange } from "../api/types";

/** URL params that make a graph box the start: a table, a role or a person. */
export function startOf(kind: NodeKind | string, id: string): Record<string, string | null> {
  const none = { table: null, role: null, user: null, sel: null };
  if (kind === "user") return { ...none, user: id.replace(/ \(user\)$/, "") };
  if (kind === "object") return { ...none, table: id };
  return { ...none, role: id };
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
