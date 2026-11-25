import { beforeEach, describe, expect, it } from "vitest";
import { redirect } from "../App";
import type { Finding, WhatIfChange } from "../api/types";
import { addTo, changeText, findingKey, inPlan, planTexts, rulesQuery, saved, toChange, toggleFix, visible } from "./changeplan";

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
  it("asks the server for the page's findings: by rule on Findings, one rule per role or user, rules off only on the change plan", () => {
    const none = { q: "", area: "", people: false };
    expect(rulesQuery({ rule: "9", area: "Role model" }, "checks", ["5"], none)).toEqual({ rule: "9", by: "grantee", sev: undefined, off: undefined, q: undefined, area: undefined, people: undefined });
    expect(rulesQuery({}, "checks", [], none).by).toBe("rule");
    expect(rulesQuery({ by: "grid" }, "fixes", ["5", "9"], { q: " x ", area: "Sensitive data", people: true }))
      .toEqual({ by: "grid", sev: "all", off: "5,9", q: "x", area: "Sensitive data", people: "1" });
    expect(rulesQuery({ by: "person", sev: "High" }, "fixes", [], none)).toMatchObject({ by: "person", sev: "High", off: "" });
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
  it("redirects the old and new links to Risks, Rules and the plan", () => {
    expect(redirect("rulelist", {})).toEqual({ page: "rules", params: { show: "list" } });
    expect(redirect("risks", { sev: "High" })).toEqual({ page: "rules", params: { sev: "High", show: "fixes" } });
    expect(redirect("plan", {})).toEqual({ page: "whatif", params: { show: "plan" } });
    expect(redirect("rules", {})).toEqual({ page: "rules", params: {} });
    expect(redirect("rules", { st: "stale" })).toEqual({ page: "rules", params: { part: "stale" } }); // the side menu's old Dormant & disabled link
  });
});

describe("a role held through a group", () => {
  it("is crossed out where it is granted, and the plan says who else loses it", async () => {
    const { cutLinks } = await import("./changeplan");
    const { wider } = await import("./Plan");
    const ch = { op: "revoke_role_from_user" as const, role: "F_X", user: "U1" };
    expect([...cutLinks(["U1 (user)", "GRP", "F_X", "T_READ", "DB.S.T"], [ch])]).toEqual([1]);
    expect([...cutLinks(["U1 (user)", "F_X", "T_READ", "DB.S.T"], [ch])]).toEqual([0]);
    const step = (label: string) => ({ change: ch, label, iac: "", sql: "" });
    expect(wider({ changes: [step("Revoke role F_X from user U1"), step("Revoke role F_X from user U1 (held through GRP: revoked there, so their other holders lose it as well)")] })).toHaveLength(1);
  });
});

it("what names one account's people and roles stays with that account", async () => {
  const { scope, saved: keep } = await import("./changeplan");
  localStorage.setItem("ae-own", JSON.stringify(["kept before the account was known"]));
  const own = keep<string[]>("ae-own", [], true), all = keep<string[]>("ae-all", []);
  scope("demo");
  expect(own.get()).toEqual([]);
  own.set(["DW_DEV_01"]);
  all.set(["5"]);
  scope("real");
  expect(own.get()).toEqual([]);
  expect(all.get()).toEqual(["5"]);
  scope("demo");
  expect(own.get()).toEqual(["DW_DEV_01"]);
});
