import { beforeEach, describe, expect, it } from "vitest";
import { redirect } from "../App";
import type { Finding, WhatIfChange, WhatIfUser } from "../api/types";
import { addTo, changeText, findingKey, groupFindings, inPlan, objectImpact, planTexts, saved, toChange, toggleFix, visible } from "./changeplan";

const f = (num: string, grantee: string, more: Partial<Finding> = {}): Finding => ({
  num, title: `rule ${num}`, severity: "High", area: "", grantee, kind: "user", what: `w${num}`, impact: null, people: [grantee],
  paths: [[grantee]], iac: "", sql: "", same_fix: "", changes: [], objects: [], ...more,
});
const r1: WhatIfChange = { op: "revoke_role_from_user", role: "F_A", user: "U1" };
const r2: WhatIfChange = { op: "revoke_priv", role: "T_X", privilege: "SELECT", object: "DB.S.T" };

describe("change plan", () => {
  beforeEach(() => { try { localStorage.clear(); } catch { /* no storage */ } });
  it("adds each change once and toggles a fix", () => {
    expect(addTo([r1], [r1, r2])).toEqual([r1, r2]);
    expect(inPlan([r1], [r1, r2])).toBe(false);
    expect(inPlan([], [])).toBe(false);
    expect(toggleFix([r1], [r1])).toEqual([]);
    expect(toggleFix([r1], [r2])).toEqual([r1, r2]);
    expect(toggleFix([r1, r2], [{ ...r2 }])).toEqual([r1]);
  });
  it("keeps state in memory and tells subscribers, even without storage", () => {
    const s = saved<string[]>("ae-test", []);
    let n = 0;
    const off = s.sub(() => n++);
    s.set(["9"]);
    expect(s.get()).toEqual(["9"]);
    expect(n).toBe(1);
    off();
    s.set([]);
    expect(n).toBe(1);
  });
  it("hides rules turned off and muted findings, and counts them", () => {
    const xs = [f("9", "PUBLIC"), f("5", "ADMIN_01"), f("5", "OPS_01")];
    const v = visible(xs, ["9"], { [findingKey(xs[2])]: "break-glass" });
    expect(v.shown.map((x) => x.grantee)).toEqual(["ADMIN_01"]);
    expect([v.off, v.muted]).toEqual([1, 1]);
  });
  it("groups by person and object, the ones without last", () => {
    const xs = [f("1", "U1", { objects: ["A"] }), f("2", "R", { people: ["U1", "U2"], objects: ["A", "B"] }), f("13", "R2", { people: [] })];
    expect(groupFindings(xs, "person").map((g) => [g.key, g.items.length])).toEqual([["U1", 2], ["U2", 1], ["", 1]]);
    expect(groupFindings(xs, "object").map((g) => [g.key, g.items.length, g.people])).toEqual([["A", 2, 2], ["B", 1, 2], ["", 1, 0]]);
  });
  it("writes the plan as SQL, Terraform and ticket text", () => {
    expect(toChange(r1)).toEqual({ op: "revoke", role: "F_A", to: "U1", toUser: true });
    expect(toChange({ op: "drop_role", role: "F_A" })).toBeNull();
    const t = planTexts([r1, { op: "drop_role", role: "F_OLD" }, { op: "empty_public" }], "REVOKE ROLE F_A FROM USER U1;\nDROP ROLE F_OLD;");
    expect(t.sql).toBe("REVOKE ROLE F_A FROM USER U1;\nDROP ROLE F_OLD;\n");
    expect(t.tf).toContain("# Revoke F_A from U1");
    expect(t.tf).toContain("# Drop role F_OLD");
    expect(t.tf).toContain("# Empty PUBLIC");
    expect(t.ticket).toContain("1. Revoke F_A from user U1\n2. Drop role F_OLD\n3. Empty PUBLIC");
    expect(planTexts([], "").sql).toBe("-- nothing to revoke\n");
    expect(changeText(r2)).toBe("Revoke SELECT on DB.S.T from T_X");
  });
  it("adds up what each object loses", () => {
    const row = (object: string, privileges: string[]) => ({ object, type: "TABLE", privileges, classes: [], path: [] });
    const u = (user: string, rows: ReturnType<typeof row>[]): WhatIfUser => ({ user, status: "active", lost: rows.length, objects: rows.length, kept: 0, lost_rows: rows, kept_rows: [], kept_roles: [] });
    expect(objectImpact([u("U1", [row("B", ["SELECT"])]), u("U2", [row("B", ["INSERT"]), row("A", ["SELECT"])])])).toEqual([
      { object: "B", type: "TABLE", people: 2, privileges: ["INSERT", "SELECT"] }, { object: "A", type: "TABLE", people: 1, privileges: ["SELECT"] }]);
  });
  it("redirects the old and new links to Risks, Rules and the plan", () => {
    expect(redirect("rulelist", {})).toEqual({ page: "rules", params: { show: "list" } });
    expect(redirect("risks", { sev: "High" })).toEqual({ page: "rules", params: { sev: "High", show: "fixes" } });
    expect(redirect("plan", {})).toEqual({ page: "whatif", params: { show: "plan" } });
    expect(redirect("rules", {})).toEqual({ page: "rules", params: {} });
  });
});
