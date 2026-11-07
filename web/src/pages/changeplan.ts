// The change plan (one store for the Risks & fixes panel and What if), rules On/Off and muted findings. Per viewer, in
// this browser only (localStorage, which can be blocked: every access wrapped). They only change what the UI shows: the
// plan is simulated by access.what_if and its text never runs; Off and Mute hide findings, access.py results stay.
import { useSyncExternalStore } from "react";
import type { Finding, WhatIfChange, WhatIfUser } from "../api/types";
import { terraformOf, type Change } from "../components/codegen";

export interface Saved<T> { get: () => T; set: (v: T) => void; sub: (f: () => void) => () => void }

export function saved<T>(key: string, empty: T): Saved<T> {
  let v = empty;
  try { const s = localStorage.getItem(key); if (s) v = JSON.parse(s) as T; } catch { /* no storage */ }
  const subs = new Set<() => void>();
  return {
    get: () => v,
    set: (n) => { v = n; try { localStorage.setItem(key, JSON.stringify(n)); } catch { /* no storage */ } subs.forEach((f) => f()); },
    sub: (f) => { subs.add(f); return () => { subs.delete(f); }; },
  };
}

export const plan = saved<WhatIfChange[]>("ae-plan", []);
export const muted = saved<Record<string, string>>("ae-muted", {}); // finding key -> reason
export const rulesOff = saved<string[]>("ae-rules-off", []);
export const useSaved = <T,>(s: Saved<T>): T => useSyncExternalStore(s.sub, s.get, s.get);

export function changeText(ch: WhatIfChange): string {
  switch (ch.op) {
    case "revoke_role_from_user": return `Revoke ${ch.role} from user ${ch.user}`;
    case "revoke_role_from_role": return `Revoke ${ch.role} from role ${ch.grantee}`;
    case "revoke_priv": return `Revoke ${ch.privilege} on ${ch.object} from ${ch.role}`;
    case "drop_role": return `Drop role ${ch.role}`;
    default: return "Empty PUBLIC";
  }
}

const has = (list: WhatIfChange[], ch: WhatIfChange) => list.some((x) => changeText(x) === changeText(ch));

/** list plus chs, each change once. */
export const addTo = (list: WhatIfChange[], chs: WhatIfChange[]) => chs.reduce((l, c) => (has(l, c) ? l : [...l, c]), list);

/** Every change of a fix is in the plan. */
export const inPlan = (list: WhatIfChange[], chs: WhatIfChange[]) => chs.length > 0 && chs.every((c) => has(list, c));

/** Add a finding's fix, or take it out again when it is already in. */
export const toggleFix = (list: WhatIfChange[], chs: WhatIfChange[]) =>
  inPlan(list, chs) ? list.filter((x) => !has(chs, x)) : addTo(list, chs);

export const findingKey = (f: Finding) => `${f.num}|${f.grantee}|${f.what}`;

/** Findings left after rules Off and muted ones; with how many each hid. */
export function visible(list: Finding[], off: string[], mute: Record<string, string>) {
  const o = new Set(off);
  const shown = list.filter((f) => !o.has(f.num) && !(findingKey(f) in mute));
  return { shown, off: list.filter((f) => o.has(f.num)).length, muted: list.filter((f) => !o.has(f.num) && findingKey(f) in mute).length };
}

export interface FGroup { key: string; items: Finding[]; people: number }

/** Findings per person affected or per object, most findings first; findings without one under "". */
export function groupFindings(list: Finding[], by: "person" | "object"): FGroup[] {
  const m = new Map<string, Finding[]>();
  for (const f of list) {
    const ks = by === "person" ? f.people : f.objects;
    for (const k of ks.length ? ks : [""]) m.set(k, [...(m.get(k) ?? []), f]);
  }
  return [...m.entries()].map(([key, items]) => ({ key, items, people: new Set(items.flatMap((f) => f.people)).size }))
    .sort((a, b) => Number(!a.key) - Number(!b.key) || b.items.length - a.items.length || a.key.localeCompare(b.key));
}

/** A revoke in CodeOutput's Change shape; drop role and Empty PUBLIC have none. */
export function toChange(ch: WhatIfChange): Change | null {
  if (ch.op === "revoke_role_from_user") return { op: "revoke", role: ch.role, to: ch.user, toUser: true };
  if (ch.op === "revoke_role_from_role") return { op: "revoke", role: ch.role, to: ch.grantee };
  if (ch.op === "revoke_priv") return { op: "revoke", privilege: ch.privilege, object: ch.object, to: ch.role };
  return null;
}

/** SQL (as access.what_if wrote it), Terraform and ticket text of a plan. Text only: the app never runs it. */
export function planTexts(list: WhatIfChange[], sql: string): { sql: string; tf: string; ticket: string } {
  const tf = list.map((ch) => {
    const c = toChange(ch);
    if (c) return terraformOf([c]).trimEnd();
    return ch.op === "drop_role"
      ? `# Drop role ${ch.role}: delete its snowflake_account_role resource and every grant that names it, then plan and apply.`
      : `# Empty PUBLIC: delete every grant to PUBLIC (search the repo for "PUBLIC"), then plan and apply.`;
  }).join("\n") + "\n";
  const ticket = [`Access change (${list.length} item${list.length === 1 ? "" : "s"})`, "", ...list.map((ch, i) => `${i + 1}. ${changeText(ch)}`), "",
    "Reason: (fill in)", "Approver: (owner of the object)", "Simulated in the access explorer before the change.",
    "Apply through infrastructure as code; manual grants are removed by reconciliation."].join("\n") + "\n";
  return { sql: sql ? `${sql.trimEnd()}\n` : "-- nothing to revoke\n", tf, ticket };
}

/** What if "Group by Objects": per object the people who lose it and the privileges lost, most people first. */
export function objectImpact(users: WhatIfUser[]): { object: string; type: string; people: number; privileges: string[] }[] {
  const m = new Map<string, { type: string; who: Set<string>; pv: Set<string> }>();
  for (const u of users) for (const r of u.lost_rows) {
    const x = m.get(r.object) ?? { type: r.type, who: new Set(), pv: new Set() };
    x.who.add(u.user); r.privileges.forEach((p) => x.pv.add(p));
    m.set(r.object, x);
  }
  return [...m.entries()].map(([object, x]) => ({ object, type: x.type, people: x.who.size, privileges: [...x.pv].sort() }))
    .sort((a, b) => b.people - a.people || a.object.localeCompare(b.object));
}
