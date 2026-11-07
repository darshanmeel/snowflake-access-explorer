// Screen 2 helpers without React: level groups, the "How X gets in" steps, the people-with-the-same-route label.
import type { ObjLevel, WhoEntry } from "../api/types";

export const ORDER: ObjLevel[] = ["admin", "own", "change", "read", "use", "names"];
export const TITLE: Record<ObjLevel, string> = {
  admin: "Admin", own: "Owns", change: "Can change", read: "Read only", use: "Can use", names: "Can see names",
};
export const NOTE: Record<ObjLevel, string> = {
  admin: "Admin roles inherit every role, so they need no grant on this object",
  own: "OWNERSHIP: every privilege, and can grant it on",
  change: "INSERT, UPDATE, DELETE, or MODIFY / OPERATE",
  read: "SELECT or READ",
  use: "USAGE or MONITOR: can run or watch it",
  names: "USAGE: can see the names inside",
};

/** Entries in level order, empty levels left out. */
export function byLevel<T extends WhoEntry>(xs: T[]): { level: ObjLevel; rows: T[] }[] {
  return ORDER.map((level) => ({ level, rows: xs.filter((x) => x.level === level) })).filter((g) => g.rows.length);
}

const KIND: Record<string, string> = {
  user: "User", functional: "Functional role", technical: "Technical role", group: "Group role",
  database_role: "Database role", admin: "Admin role", object: "Object",
};

/** One step per node of the shortest path; the grant holder says what it grants, an admin role that it inherits all. */
export function stepsOf(e: WhoEntry, kinds: Record<string, string>, disabled = false): { name: string; kind: string }[] {
  const p = e.path;
  const end = kinds[p[p.length - 1]] === "object" ? p.length - 1 : p.length;
  const out = p.slice(0, end).map((n, i) => {
    const k = kinds[n] ?? (i === 0 ? "user" : "role");
    let kind = KIND[k] ?? "Role";
    if (i === 0 && disabled) kind += " · disabled";
    if (n === e.holder && end < p.length && i > 0 && e.privileges.length) kind += ` · grants ${e.privileges.join(", ")}`;
    if (n === "PUBLIC") kind = "Everyone (PUBLIC)" + (n === e.holder && e.privileges.length ? ` · grants ${e.privileges.join(", ")}` : "");
    if (k === "admin") kind = "Admin role · inherits every role";
    return { name: n.replace(/ \(user\)$/, ""), kind };
  });
  if (end < p.length) out.push({ name: p[p.length - 1], kind: e.privileges.length ? e.privileges.join(", ") : "Object" });
  return out;
}

/** "12 people via PUBLIC", "ENGINEER_01 via F_ENGINEER". */
export function sameLabel(names: string[], route: string[]): string {
  const via = route[0] ?? "";
  const who = names.length === 1 ? names[0] : `${names.length} people`;
  return via ? `${who} via ${via === "PUBLIC" ? "PUBLIC (everyone)" : via}` : who;
}
