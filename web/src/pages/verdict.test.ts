import { describe, expect, it } from "vitest";
import { redirect } from "../App";
import type { CheckPage, Nearest } from "../api/types";
import { expiryOf, newRoleOf, sqlOf } from "../components/codegen";
import { cutChanges, cutLabel, cutWhatIf, needOf, nearestNote, nearestTitle, sideEffects, verdictLine } from "./verdict";

const roleEdge = { grantee: "F_ENGINEER", to: "HR.SC_W_PEOPLE", priv: null, user: false };
const userEdge = { grantee: "ENGINEER_01", to: "F_ENGINEER", priv: null, user: true };
const privEdge = { grantee: "T_X_READ", to: "DB.S.T", priv: "SELECT", user: false };
const near = (o: Partial<Nearest>): Nearest => ({
  path: ["FIN_09", "F_X", "T_X_READ", "DB.S.T"], missing: 0, role: "F_X", to: "FIN_09", to_user: true, cost: 1, people: 0, holders: 2,
  extra: 5, also: [{ level: "read", count: 2, where: "DB.S" }], rule1: false, broad: null, ...o,
});
const base = { user: "FIN_09", object: "DB.S.T", roles_count: 11, lanes_total: 0, cut: [], layers: null, nearest: [] as Nearest[],
  answer: { yes: false, how: "none", title: "No, not through any role", text: "", tone: null, stats: [] } } as const;

describe("Can they? helpers", () => {
  it("labels cuts and turns them into revokes and What if changes", () => {
    expect(cutLabel([roleEdge])).toBe("Revoke HR.SC_W_PEOPLE from F_ENGINEER");
    expect(cutLabel([userEdge])).toBe("Revoke F_ENGINEER from user ENGINEER_01");
    expect(cutLabel([privEdge])).toBe("Revoke SELECT on DB.S.T from T_X_READ");
    expect(sqlOf(cutChanges([roleEdge], "TABLE"))).toContain("REVOKE DATABASE ROLE HR.SC_W_PEOPLE FROM ROLE F_ENGINEER;");
    expect(sqlOf(cutChanges([privEdge], "TABLE"))).toContain("REVOKE SELECT ON TABLE DB.S.T FROM ROLE T_X_READ;");
    expect(cutWhatIf([userEdge, roleEdge, privEdge])).toEqual([
      { op: "revoke_role_from_user", role: "F_ENGINEER", user: "ENGINEER_01" },
      { op: "revoke_role_from_role", role: "HR.SC_W_PEOPLE", grantee: "F_ENGINEER" },
      { op: "revoke_priv", role: "T_X_READ", privilege: "SELECT", object: "DB.S.T" }]);
    expect(sideEffects(1, 0)).toEqual([{ text: "Affects 1 person", tone: "ok" }]);
    expect(sideEffects(3, 19).map((b) => b.tone)).toEqual(["warn", "bad"]);
  });
  it("writes the verdict line for Yes, Partly and No", () => {
    expect(verdictLine({ ...base, verdict: "no" } as unknown as CheckPage)).toBe("None of FIN_09's 11 roles leads to DB.S.T.");
    expect(verdictLine({ ...base, verdict: "no", nearest: [near({})] } as unknown as CheckPage)).toContain("one grant away");
    expect(verdictLine({ ...base, verdict: "yes", lanes_total: 2, cut: ["F_ENGINEER"] } as unknown as CheckPage)).toBe("through 2 routes, all via F_ENGINEER");
    const layers = [{ step: "Grant", ok: true, result: "Allowed", reason: "" }, { step: "Rows", ok: false, result: "No rows", reason: "" },
      { step: "Columns", ok: false, result: "Not reached", reason: "" }];
    expect(verdictLine({ ...base, verdict: "partly", layers } as unknown as CheckPage)).toBe("The query runs, but returns no rows.");
  });
  it("names the nearest ways and warns", () => {
    expect(nearestTitle(near({}))).toBe("Get role F_X");
    expect(nearestTitle(near({ to: "GRP_ALL", to_user: false }))).toBe("Grant F_X to GRP_ALL");
    expect(nearestTitle(near({ cost: 2, role: "DB.R" }))).toBe("New account role with DB.R");
    const n = nearestNote(near({ rule1: true }), "HR data owner");
    expect(n).toContain("held by 2 people today");
    expect(n).toContain("read · 2 in DB.S");
    expect(n).toContain("breaks rule 1");
    expect(n).toContain("approver: HR data owner");
    expect(needOf("SELECT")).toBe("read");
    expect(needOf("INSERT")).toBe("change");
  });
});

describe("Request access text", () => {
  it("dates the expiry and writes a commented skeleton when no role fits", () => {
    expect(expiryOf(30, new Date("2026-11-07T12:00:00Z"))).toBe("2026-12-07");
    expect(expiryOf(0)).toBe("");
    const t = newRoleOf("FIN_09", ["INSERT", "UPDATE"], "TABLE", "HR.PEOPLE.TBL_EMPLOYEE", { reason: "Q4 report", approver: "HR data owner" });
    const lines = t.sql.trim().split("\n");
    expect(lines.every((l) => l.startsWith("--"))).toBe(true);
    expect(t.sql).toContain("-- GRANT INSERT, UPDATE ON TABLE HR.PEOPLE.TBL_EMPLOYEE TO ROLE <NEW_ROLE>;");
    expect(t.sql).toContain("-- Reason: Q4 report");
    expect(t.tf.trim().split("\n").every((l) => l.startsWith("#"))).toBe(true);
    expect(t.ticket).toContain("Approver: HR data owner");
    expect(newRoleOf("FIN_09", ["SELECT"], "TABLE", "HR.PEOPLE.T", {}, "HR.SC_R_PEOPLE").sql).toContain("-- GRANT DATABASE ROLE HR.SC_R_PEOPLE TO ROLE <NEW_ROLE>;");
  });
  it("keeps the brief's ?who=&what= links working", () => {
    expect(redirect("check", { who: "FIN_09", what: "HR.PEOPLE.T", do: "read" })).toEqual({ page: "check", params: { name: "FIN_09", obj: "HR.PEOPLE.T", do: "read" } });
    expect(redirect("request", { who: "FIN_09", what: "HR.PEOPLE.T" })).toEqual({ page: "request", params: { name: "FIN_09", obj: "HR.PEOPLE.T" } });
    expect(redirect("request", { name: "FIN_09" })).toEqual({ page: "request", params: { name: "FIN_09" } });
  });
});
