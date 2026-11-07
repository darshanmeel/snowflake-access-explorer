// Can they? (screens 3, 12) and Request access (15) helpers without React: cut labels and changes, verdict lines,
// nearest-way titles and notes.
import type { CheckPage, Nearest, WhatIfChange } from "../api/types";
import type { Change } from "../components/codegen";

type Edge = CheckPage["cuts"][number]["edges"][number];

const plural = (n: number, w: string, ws = `${w}s`) => `${n} ${n === 1 ? w : ws}`;

export function cutLabel(es: Edge[]): string {
  const e = es[0];
  if (!e) return "";
  if (!e.priv) return `Revoke ${e.to} from ${e.user ? "user " : ""}${e.grantee}`;
  return `Revoke ${es.map((x) => x.priv).join(", ")} on ${e.to} from ${e.grantee}`;
}

/** The revokes of one cut as CodeOutput changes (text only). */
export function cutChanges(es: Edge[], objectType: string): Change[] {
  return es.map((e) => e.priv
    ? { op: "revoke", privilege: e.priv, objectType, object: e.to, to: e.grantee }
    : { op: "revoke", role: e.to, to: e.grantee, toUser: e.user });
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
export function verdictLine(d: Pick<CheckPage, "verdict" | "user" | "object" | "roles_count" | "lanes_total" | "cut" | "layers" | "nearest" | "answer">): string {
  if (d.verdict === "no") {
    const n = d.nearest[0];
    return `None of ${d.user}'s ${plural(d.roles_count, "role")} leads to ${d.object}.`
      + (n ? ` The nearest route is ${n.cost === 1 ? "one grant" : `${n.cost} grants`} away.` : "");
  }
  if (d.verdict === "partly") {
    const [, rows, cols] = d.layers ?? [];
    return rows && !rows.ok && rows.result === "No rows" ? "The query runs, but returns no rows." : `The query runs; ${cols?.result.toLowerCase() ?? "some columns masked"}.`;
  }
  if (!d.lanes_total) return d.answer.title;
  return `through ${plural(d.lanes_total, "route")}` + (d.cut.length && d.lanes_total > 1 ? `, all via ${d.cut[0]}` : "");
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

/** Request page need from a Can they? privilege. */
export const needOf = (priv: string) => (["SELECT", "USAGE", "READ", "MONITOR", "REFERENCES"].includes(priv) ? "read" : "change");
