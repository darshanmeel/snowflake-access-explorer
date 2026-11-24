// Home's pure helpers: the Needs attention tiles and the one-line takeaways, each computed from the server's numbers.
import type { HomePage, Page } from "../api/types";

const n0 = (n: number) => n.toLocaleString("en-US");
const plural = (n: number, w: string, ws = `${w}s`) => `${n0(n)} ${n === 1 ? w : ws}`;

/** Share as a whole percent; a non-zero share under 1% says "<1%", so it never reads as none. */
export const pct = (n: number, of: number) => (!of ? "0%" : n > 0 && (100 * n) / of < 1 ? "<1%" : `${Math.round((100 * n) / of)}%`);

export const weekend = (day: string) => [0, 6].includes(new Date(`${day}T00:00:00Z`).getUTCDay());

export const busiest = <T extends { queries: number }>(days: T[]): T | null =>
  days.length ? days.reduce((a, b) => (b.queries > a.queries ? b : a)) : null;

/** Every depth from shortest to deepest, so a depth with none shows as 0, not as a gap. */
export function depthRows(got: Record<string, number>): { d: number; n: number }[] {
  const ds = Object.keys(got).map(Number);
  if (!ds.length) return [];
  const lo = Math.min(...ds), hi = Math.max(...ds);
  return Array.from({ length: hi - lo + 1 }, (_, i) => ({ d: lo + i, n: got[lo + i] ?? 0 }));
}

/** "97% of users sit 4 roles away from what they can reach." from the depth with the most. */
export function depthTakeaway(rows: { d: number; n: number }[], what: string): string {
  const all = rows.reduce((s, r) => s + r.n, 0);
  if (!all) return `No ${what} reached through a role chain.`;
  const top = rows.reduce((a, b) => (b.n > a.n ? b : a));
  const away = `${plural(top.d, "role")} away`;
  return what === "users" ? `${pct(top.n, all)} of users sit ${away} from what they can reach.`
    : `${pct(top.n, all)} of ${what} are reached ${away} from the user.`;
}

/** "4% active. Includes 1 service user." */
export function peopleTakeaway(byStatus: Record<string, number>, service: number): string {
  const all = Object.values(byStatus).reduce((s, v) => s + v, 0);
  if (!all) return "No people.";
  return `${pct(byStatus.active ?? 0, all)} active. Includes ${plural(service, "service user")}.`;
}

/** "Role model has 88% of all findings." for the largest area. */
export function areaTakeaway(rows: { area: string; total: number }[]): string {
  const all = rows.reduce((s, r) => s + r.total, 0);
  if (!all) return "";
  const top = rows.reduce((a, b) => (b.total > a.total ? b : a));
  return `${top.area} has ${pct(top.total, all)} of all findings.`;
}

/** Home's headline: the worst thing true now, with its number. */
export function headline(d: HomePage, off: (source: string) => boolean): string {
  const crit = d.risks?.Critical ?? 0, high = d.risks?.High ?? 0, n = d.cards?.readers?.risky ?? d.protection?.dormant ?? 0; // the same number as the picture
  if (!d.risks || off("grants")) return "The grants were not read";
  if (n && !off("users")) return `${plural(n, "inactive person", "inactive people")} can still read sensitive data`;
  if (crit) return `${plural(crit, "critical finding")} to fix`;
  return high ? `${plural(high, "high finding")} to fix, none critical` : "No critical or high findings";
}

export interface Reader { id: "risky" | "admin" | "service" | "active"; label: string; n: number }
/** Who can read sensitive data, each user once, the inactive first. */
export function readers(r: Partial<Record<Reader["id"], number>> | undefined): Reader[] {
  const L: [Reader["id"], string][] = [["risky", "Inactive"], ["admin", "Admin"], ["service", "Service"], ["active", "Active"]];
  return L.map(([id, label]) => ({ id, label, n: r?.[id] ?? 0 })).filter((x) => x.n > 0);
}

/** What to do about a rule, counted: the first words of an action, its kind. n: the roles or users it is about. */
const DO: Record<string, [(n: string, one: boolean) => string, string]> = {
  4: [(n, o) => `Take the owner role from ${n} consumer ${o ? "role" : "roles"}`, "Revoke"],
  5: [(n, o) => `Take admin roles from ${n} ${o ? "person" : "people"}`, "Revoke"],
  7: [(n, o) => `Remove the roles of ${n} inactive ${o ? "person" : "people"}`, "Revoke"],
  9: [() => "Stop granting to everyone through PUBLIC", "Revoke"],
  12: [(n, o) => `Give ${n} ${o ? "person" : "people"} a default role that is not admin`, "Change default"],
  17: [(n, o) => `Take write access from ${n} read-only ${o ? "role" : "roles"}`, "Revoke"],
  20: [(n, o) => `Take task OPERATE from ${n} ${o ? "role" : "roles"}`, "Revoke"],
  22: [(n, o) => `Take the stream from ${n} ${o ? "role" : "roles"} that cannot read the table`, "Revoke"],
  23: [(n, o) => `Take CREATE from ${n} read-only ${o ? "role" : "roles"}`, "Revoke"],
  25: [(n, o) => `Stop people using ${n} service ${o ? "user" : "users"}`, "Change use"],
  26: [(n, o) => `Move the data work of ${n} ${o ? "person" : "people"} off admin roles`, "Change use"],
  29: [(n, o) => `Check what ${n} ${o ? "role sees" : "roles see"} through an app`, "Protect"],
};
export function action(num: string, subjects: number, fix: string | null | undefined, title: string): { text: string; kind: string } {
  const d = DO[num];
  return d ? { text: d[0](n0(subjects), subjects === 1), kind: d[1] } : { text: fix?.split(/(?<=[.;])\s/)[0].replace(/[.;]$/, "") || title, kind: "Fix" };
}

/** "Most findings are medium: 33 of 68." */
export function severityTakeaway(risks: Record<string, number>): string {
  const all = Object.values(risks).reduce((s, v) => s + v, 0);
  if (!all) return "No findings";
  const [sev, n] = Object.entries(risks).reduce((a, b) => (b[1] > a[1] ? b : a));
  return `${2 * n > all ? "Most" : "The biggest group of"} findings ${2 * n > all ? "are" : "is"} ${sev.toLowerCase()}: ${n0(n)} of ${n0(all)}`;
}

export interface Tile { key: string; label: string; n: number; text: string; tone: "bad" | "warn" | null; page: Page; params: Record<string, string> }

/** Needs attention: one number per tile, each opening where it is acted on. A tile whose source was not read is left
 * out (`off` says which), so it never shows a 0 that only means "unknown". */
export function attention(d: HomePage, off: (source: string) => boolean): Tile[] {
  if (!d.risks || !d.cards || !d.protection || off("grants")) return [];
  const crit = d.risks.Critical ?? 0, top = crit + (d.risks.High ?? 0), p = d.protection, k = d.cards;
  const rules = new Set([...Object.keys(d.rule_sev?.Critical ?? {}), ...Object.keys(d.rule_sev?.High ?? {})]).size;
  const out: Tile[] = [
    { key: "risk", label: "Critical or high", n: top, tone: top ? "bad" : null, page: "rules", params: { sev: crit ? "Critical" : "High" },
      text: top ? `findings in ${plural(rules, "rule")}` : "No critical or high findings" }];
  if (!off("users")) out.push({ key: "stale", label: "Read sensitive data", n: p.dormant, tone: p.dormant ? "bad" : null, page: "rules", params: { rule: "7" },
    text: `dormant or disabled ${p.dormant === 1 ? "person" : "people"} can still read it` });
  if (!off("policies")) out.push({ key: "mask", label: "Not masked", n: p.unmasked_columns, tone: p.unmasked_columns ? "warn" : null, page: "rules", params: { rule: "6" },
    text: `sensitive ${p.unmasked_columns === 1 ? "column" : "columns"} without a masking policy` });
  out.push({ key: "admin", label: "Admin holders", n: k.admins.total, tone: k.admins.total ? "warn" : null, page: "rules", params: { part: "admins" },
    text: "with an admin role or account privilege" });
  if (k.objuse.ok) out.push({ key: "unused", label: "Not used", n: k.objuse.unused, tone: k.objuse.unused ? "warn" : null, page: "objuse", params: {},
    text: `${k.objuse.unused === 1 ? "object" : "objects"} not used in ${k.objuse.days} days` });
  return out;
}
