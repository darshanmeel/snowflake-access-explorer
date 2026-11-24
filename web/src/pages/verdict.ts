// Can they? (screens 3, 12) and Request access (15) helpers without React: cut labels and changes, verdict lines,
// nearest-way titles and notes.
import type { CheckPage, Nearest, Subject, UsedRow, WhatIfChange } from "../api/types";

type Patch = Record<string, string | null>;

type Edge = CheckPage["cuts"][number]["edges"][number];

const plural = (n: number, w: string, ws = `${w}s`) => `${n} ${n === 1 ? w : ws}`;

export function cutLabel(es: Edge[]): string {
  const e = es[0];
  if (!e) return "";
  if (!e.priv) return `Revoke ${e.to} from ${e.user ? "user " : ""}${e.grantee}`;
  return `Revoke ${es.map((x) => x.priv).join(", ")} on ${e.to} from ${e.grantee}`;
}

/** One cut's text as the server writes it (access.revoke: OWNERSHIP is a transfer, future grants ON FUTURE .. IN
 * SCHEMA / DATABASE): one statement per line; Terraform and ticket name what to remove in the IaC repo. */
export function cutTexts(cut: { iac: string; sql: string }, user: string): { sql: string; tf: string; ticket: string } {
  const items = cut.iac.split("; ");
  return {
    sql: `-- Where to cut: ${user}\n${cut.sql.replace(/;\s+/g, ";\n").trim()}\n`,
    tf: [`# Where to cut: ${user}`, ...items.map((t) => `# ${t}, then plan and apply.`)].join("\n") + "\n",
    ticket: [`Access change (${items.length} item${items.length === 1 ? "" : "s"})`, "", ...items.map((t, i) => `${i + 1}. ${t}`), "",
      "Reason: (fill in)", "Approver: (owner of the object)",
      "Apply through infrastructure as code; manual grants are removed by reconciliation."].join("\n") + "\n",
  };
}

/** The same cut for the What if page. */
export function cutWhatIf(es: Edge[]): WhatIfChange[] {
  return es.map((e): WhatIfChange => e.priv
    ? { op: "revoke_priv", role: e.grantee, privilege: e.priv, object: e.to }
    : e.user ? { op: "revoke_role_from_user", role: e.to, user: e.grantee } : { op: "revoke_role_from_role", role: e.to, grantee: e.grantee });
}

export function sideEffects(people: number, lost: number): { text: string; tone: "ok" | "warn" | "bad" }[] {
  return [{ text: `Affects ${plural(people, "person", "people")}`, tone: people > 1 ? "warn" : "ok" },
    ...(lost > 0 ? [{ text: `${plural(lost, "other privilege")} lost`, tone: "bad" as const }] : [])];
}

/** The line under Yes / Partly / No. */
export function verdictLine(d: Pick<CheckPage, "verdict" | "user" | "object" | "roles_count" | "lanes_total" | "cut" | "layers" | "nearest" | "answer">
  & { subject?: Pick<Subject, "user"> }): string {
  if (d.verdict === "blocked") return d.answer.title;
  if (d.verdict === "no") {
    const n = d.nearest?.[0];
    return (d.subject && !d.subject.user ? `By the grants in this data, neither ${d.user} nor any of its ${plural(d.roles_count, "role")} leads to ${d.object}.`
      : `By the grants in this data, none of ${d.user}'s ${plural(d.roles_count, "role")} leads to ${d.object}.`)
      + (n ? ` The nearest route is ${n.cost === 1 ? "one grant" : `${n.cost} grants`} away.` : "");
  }
  if (d.verdict === "partly") {
    const [, rows, cols] = d.layers ?? [];
    return rows && !rows.ok && rows.result === "No rows" ? "The query runs, but returns no rows." : `The query runs; ${cols?.result.toLowerCase() ?? "some columns masked"}.`;
  }
  if (!d.lanes_total) return d.answer.title;
  return `through ${plural(d.lanes_total, "route")}` + (d.cut.length && d.lanes_total > 1 ? `, all via ${d.cut[0]}` : "");
}

/** How a use came about when no grant explains it: certain only for an app the query names. */
export function usedHow(r: UsedRow, user = true): string {
  const as = r.role ? `as ${r.role}` : "with no role recorded";
  if (r.how === "app") return `through app ${r.app}${r.role ? ` (runs as ${r.role})` : ""}`;
  if (r.how === "owner") return `${as}${r.role ? ", a role not held now" : ""}: likely a Streamlit app or owner's-rights code, or a role held then`;
  return `${as}${user ? ", a role held now" : ""}: the grant may be gone, or left out here`;
}

/** The line under a No or Blocked when the activity shows use all the same. */
export function usedAnyway(d: Pick<CheckPage, "used_anyway" | "subject">): string | null {
  const u = d.used_anyway;
  if (!u?.rows.length) return null;
  const more = u.total - 1;
  return `But used: ${plural(u.queries, "query", "queries")} in ${u.days} days, last ${u.last.slice(0, 10)}, ${usedHow(u.rows[0], d.subject.user)}${more ? ` (+${plural(more, "more way")})` : ""}`;
}

/** The note under the answer: the warehouses a query can run on (it needs one); none = it can't run queries. */
export function warehouseNote(w: CheckPage["warehouses"]): { text: string; bad: boolean } {
  if (!w.total) return { text: "No warehouse it can use: blocked to run queries", bad: true };
  const more = w.total > w.names.length ? ` and ${w.total - w.names.length} more` : "";
  return { text: `Can run queries on ${w.total === 1 ? "warehouse" : "warehouses"} ${w.names.join(", ")}${more}${w.admin ? ", some through an admin role" : ""}`, bad: false };
}

export function nearestTitle(n: Nearest): string {
  if (n.cost > 1) return `New account role with ${n.role}`;
  return n.to_user ? `Get role ${n.role}` : `Grant ${n.role} to ${n.to}`;
}

export function nearestNote(n: Nearest, approver: string | null): string {
  const bits = [`held by ${plural(n.holders, "person", "people")} today`,
    n.extra ? `also brings ${plural(n.extra, "other privilege")}` : "brings nothing else",
    ...n.also.slice(0, 2).map((a) => `${a.level} · ${a.count} in ${a.where}`)];
  if (n.cost > 1) bits.push("a database role can't be granted to a user: needs an account role between");
  if (n.rule1) bits.push("a technical role on a user or group role breaks rule 1");
  if (approver) bits.push(`approver: ${approver}`);
  return bits.join(" · ");
}

/** URL params of a Can they? / Request access subject: name= for a user (old links keep it), role= for a role on
 * Can they?, for_role= on Request access (whose role= is the role to ask for). The other keys are cleared. */
export function subjectParams(s: Pick<Subject, "name" | "user">, page: "check" | "request" = "check"): Patch {
  const k = page === "check" ? "role" : "for_role";
  return s.user ? { name: s.name, user: null, [k]: null } : { [k]: s.name, name: null, user: null };
}

/** The same for a link to another page (only the key that is set). */
export const subjectLink = (s: Pick<Subject, "name" | "user">, page: "check" | "request" = "check"): Record<string, string> =>
  s.user ? { name: s.name } : { [page === "check" ? "role" : "for_role"]: s.name };

/** A picked name: a role when only a role has it (as on the Access screen), else the user. */
export const pickSubject = (v: string, users: string[], roles: string[], page: "check" | "request" = "check"): Patch =>
  subjectParams({ name: v, user: !(roles.includes(v) && !users.includes(v)) }, page);

/** The subject named in the URL: a role from role= / for_role=, else a user from name= or user=. */
export function subjectIn(p: Record<string, string | undefined>, page: "check" | "request" = "check"): { name: string | null; role: boolean } {
  const r = p[page === "check" ? "role" : "for_role"];
  return r ? { name: r, role: true } : { name: p.name ?? p.user ?? null, role: false };
}

/** Request page need from a Can they? privilege. */
export const needOf = (priv: string) => (["SELECT", "USAGE", "READ", "MONITOR", "REFERENCES"].includes(priv) ? "read" : "change");

/** Can they? do= for a step on an object (admin and names: every privilege held). */
export const doOf = (level: string | null): Record<string, string> => (level === "read" || level === "change" || level === "own" ? { do: level } : {});
