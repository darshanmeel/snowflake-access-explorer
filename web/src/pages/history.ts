// Screens 13 and 14 without React: the usage bars, the What changed filters and the watched questions (saved per
// viewer in this browser; re-asked through the existing endpoints, never sent anywhere).
import type { ChangeEvent, ChangeKind, CheckPage, UsageRow, WhoPage } from "../api/types";
import { saved } from "./changeplan";

export type Filter = "all" | "gain" | "lose" | "risk" | "sensitive";
export const ICON: Record<ChangeKind, string> = { gain: "+", lose: "−", risk: "!", user: "•", fixed: "✓" };

/** An event under a filter: New findings = an event that brings a new finding. */
export function keep(e: ChangeEvent, f: Filter): boolean {
  if (f === "gain" || f === "lose") return e.kind === f;
  if (f === "risk") return e.findings.some((x) => !x.fixed);
  if (f === "sensitive") return e.sensitive;
  return true;
}

/** Bar heights (px) of the weekly queries: 3px for a week without queries, the busiest week full height. */
export const bars = (weeks: number[], h = 32) => {
  const top = Math.max(1, ...weeks);
  return weeks.map((v) => (v ? Math.max(3, Math.round((v / top) * h)) : 3));
};

export type UsageFilter = "all" | "drop" | "trim" | "keep" | "sensitive";
export const usageRows = (rows: UsageRow[], f: UsageFilter) => rows.filter((r) => f === "all" || (f === "sensitive" ? r.sensitive : r.suggest === f));

/** "Write on TBL_LOGGING · read on TBL_EMPLOYEE": what the trim takes away, object by object. */
export function trimText(rows: UsageRow[]): string {
  return rows.filter((r) => r.changes.length).map((r) => `${[...new Set(r.changes.map((c) => (c.op === "revoke_priv" ? c.privilege : "")))].join(", ")} on ${r.object.split(".").pop()}`).join(" · ");
}

export type WatchKind = "can" | "who" | "admins";
export interface Watch { id: string; kind: WatchKind; user?: string; object?: string; notify: string; seen?: { run: string; answer: string }; before?: string | null }
export const watches = saved<Watch[]>("ae-watch", []);

export function question(w: Watch): string {
  if (w.kind === "can") return `Can ${w.user} read ${w.object}?`;
  if (w.kind === "who") return `Who can read ${w.object}?`;
  return "Who holds admin roles?";
}

/** The answer of a watched question from the endpoint it uses (check, who, who?preset=admin). */
export function answerOf(w: Watch, d: CheckPage | WhoPage): string {
  if (w.kind === "can") return ({ yes: "Yes", partly: "Partly", no: "No" } as const)[(d as CheckPage).verdict];
  const ps = (d as WhoPage).people.filter((p) => w.kind === "admins" || ["read", "change", "own", "admin"].includes(p.level));
  const n = `${ps.length} ${ps.length === 1 ? "person" : "people"}`;
  return ps.length && ps.length <= 3 ? `${n} · ${ps.map((p) => p.name).join(", ")}` : n;
}

/** The answer on this snapshot (run) against the one saved on an earlier snapshot: the tag, the earlier answer, and
 * the watch to save (null: nothing new to save). */
export function recheck(w: Watch, run: string, answer: string): { tag: "New" | "Changed" | "No change"; before: string | null; next: Watch | null } {
  if (!w.seen) return { tag: "New", before: null, next: { ...w, seen: { run, answer }, before: null } };
  if (w.seen.run !== run) {
    const before = w.seen.answer;
    return { tag: before === answer ? "No change" : "Changed", before, next: { ...w, seen: { run, answer }, before } };
  }
  const before = w.before ?? null;
  return { tag: before == null ? "New" : before === answer ? "No change" : "Changed", before, next: w.seen.answer === answer ? null : { ...w, seen: { run, answer } } };
}

export const watchId = (w: Omit<Watch, "id" | "notify">) => [w.kind, w.user ?? "", w.object ?? ""].join("|");
