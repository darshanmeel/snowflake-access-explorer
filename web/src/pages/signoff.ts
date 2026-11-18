// Pure helpers of Review & sign-off (6), the Sensitive objects catalog (8) and Sensitive data flow (16).
import type { CatalogRow, GridPage, GridRow, WhatIfChange } from "../api/types";
import { toCsv } from "../components/table";

export type Decision = "keep" | "revoke";
const n = (k: number, w: string, many = `${w}s`) => `${k} ${k === 1 ? w : many}`;

/** The list toolbar's search: q (any case) in one of the texts; an empty q keeps everything. */
export const hits = (q: string | undefined, ...xs: string[]) => {
  const t = (q ?? "").trim().toLowerCase();
  return !t || xs.some((x) => x.toLowerCase().includes(t));
};

/** Rows left after People only (no service users), Only dormant / disabled and the search (person or role). */
export const gridRows = (rows: GridRow[], people: boolean, stale: boolean, q = "") =>
  rows.filter((r) => (!people || !r.type.includes("SERVICE")) && (!stale || r.suggest) && hits(q, r.user, ...r.roles));

/** Revoke rows as What if changes: every granted role on their paths, from that user (PUBLIC is never revoked). */
export const revokesOf = (rows: GridRow[], dec: Record<string, Decision>): WhatIfChange[] =>
  rows.filter((r) => dec[r.user] === "revoke").flatMap((r) => r.roles.map((role): WhatIfChange => ({ op: "revoke_role_from_user", role, user: r.user })));

/** The sign-off CSV: who reviewed, when, the scope, then one row per person with the decision and the access per column. */
export function signoffCsv(d: Pick<GridPage, "columns" | "scope" | "db" | "object">, rows: GridRow[], dec: Record<string, Decision>, reviewer: string, when: string): string {
  const scope = d.scope === "object" ? `${d.object} (privileges)` : d.scope === "db" ? `database ${d.db}` : d.scope === "all" ? "everything" : "sensitive data";
  const head = ["Person", "Type", "Status", "Last login", "Decision", "Suggested", "Granted roles", ...d.columns.map((c) => (d.scope === "object" ? c.name : c.id))];
  const meta = [["Access review sign-off"], ["Scope", scope], ["Reviewer", reviewer], ["Signed at", when],
    ["Decided", `${rows.filter((r) => dec[r.user]).length} of ${rows.length}`], []];
  const body = rows.map((r) => [r.user, r.type, r.status, r.last_login, dec[r.user] ?? "", r.suggest ? "revoke" : "", r.roles.join(" "),
    ...d.columns.map((c) => { const x = r.cells[c.id]; return x ? `${x.level} (${x.privileges.join(" ")})` : ""; })]);
  return toCsv(meta[0], [...meta.slice(1), head, ...body].map((r) => r.map(String)));
}

export type CatFilter = "all" | "open" | "pii" | "confidential";

/** Catalog filter: open = a sensitive column without masking (Not protected or Partly); q searches object, tags and
 * columns. */
export const catalogOf = (rows: CatalogRow[], f: CatFilter, q = "") =>
  rows.filter((r) => (f === "all" || (f === "open" ? r.unmasked > 0 : r.groups.includes(f)))
    && hits(q, r.object, ...r.labels, ...r.columns.map((c) => c.column)));

/** The catalog as CSV: one row per object. */
export const catalogCsv = (rows: CatalogRow[]) => toCsv(["Object", "Type", "Status", "Tags", "Columns not masked", "Columns masked", "Row policies", "Readers"],
  rows.map((r) => [r.object, r.type, r.status, r.labels.join(" "), r.columns.filter((c) => !c.masked).map((c) => c.column).join(" "),
    r.columns.filter((c) => c.masked).map((c) => c.column).join(" "), r.row_policies.join(" "), String(r.readers)]));

export function catalogSentence(rows: CatalogRow[]): string {
  const open = rows.filter((r) => r.unmasked > 0);
  const cols = open.reduce((s, r) => s + r.unmasked, 0);
  return `${n(rows.length, "object")} carry a sensitivity tag.${open.length ? ` ${open.length} ${open.length === 1 ? "has" : "have"} columns with no masking (${n(cols, "column")} in total).` : " Every tagged column is masked."}`;
}

export function protectionText(r: CatalogRow): string {
  if (r.status === "whole") return r.row_policies.length ? `Row policy ${r.row_policies.map((p) => p.split(".").pop()).join(", ")}` : "No row policy";
  return `${r.masked[0]} of ${n(r.masked[1], "column")} masked`;
}

export const linkKey = (s: string, t: string) => `${s}>${t}`;
