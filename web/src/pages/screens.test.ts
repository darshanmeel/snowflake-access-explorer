import { describe, expect, it } from "vitest";
import { redirect } from "../App";
import { riskIds, seeSentence, startOf, whatIfOf } from "./screens";

const counts = { objects: 4, sensitive: 3, columns: 5, clear: 5, masked: 0, unknown: 0, unprotected: 3, rows: 0 };

describe("access graph, what they see, compare", () => {
  it("makes a box the start", () => {
    expect(startOf("user", "ENGINEER_01 (user)")).toEqual({ table: null, role: null, user: "ENGINEER_01", sel: null });
    expect(startOf("object", "DB.S.T")).toMatchObject({ table: "DB.S.T", user: null });
    expect(startOf("database_role", "HR.SC_R")).toMatchObject({ role: "HR.SC_R" });
  });
  it("collects risky ids", () => {
    expect([...riskIds({ "a>b>read": "public" }, { PUBLIC: "public" })]).toEqual(["a>b>read", "PUBLIC"]);
  });
  it("says what they see", () => {
    expect(seeSentence(counts)).toEqual({ rows: "all rows", cols: "all 5 sensitive columns in clear", fix: "3 of those columns have no masking policy at all." });
    expect(seeSentence({ ...counts, clear: 2, masked: 3, unprotected: 1, rows: 1 })).toEqual({
      rows: "fewer rows in 1 object (row policy)", cols: "2 of 5 sensitive columns in clear", fix: "1 of those column has no masking policy at all." });
    expect(seeSentence({ ...counts, clear: 0, unprotected: 0 }).cols).toBe("every sensitive column masked");
  });
  it("turns A's extras into What if revokes, grants left out", () => {
    expect(whatIfOf([
      { op: "revoke", role: "F_X", to: "U1", toUser: true },
      { op: "revoke", role: "T_X", to: "F_A", toUser: false },
      { op: "revoke", privilege: "SELECT", objectType: "TABLE", object: "DB.S.T", to: "F_A", toUser: false },
      { op: "grant", role: "T_X", to: "F_B", toUser: false },
    ])).toEqual([
      { op: "revoke_role_from_user", role: "F_X", user: "U1" },
      { op: "revoke_role_from_role", role: "T_X", grantee: "F_A" },
      { op: "revoke_priv", role: "F_A", privilege: "SELECT", object: "DB.S.T" },
    ]);
  });
  it("sends old links to the new screens", () => {
    expect(redirect("user", { name: "HR_01", part: "sees" })).toEqual({ page: "see", params: { user: "HR_01", part: "sees" } });
    expect(redirect("user", { name: "HR_01", part: "usage" })).toEqual({ page: "see", params: { user: "HR_01", part: "usage" } });
    expect(redirect("role", { name: "F_A", part: "sees" })).toEqual({ page: "see", params: { role: "F_A", part: "sees" } });
    expect(redirect("user", { name: "HR_01", part: "privs" })).toEqual({ page: "user", params: { name: "HR_01", part: "privs" } });
    expect(redirect("sensitive", { a: "F_A", b: "F_B" })).toEqual({ page: "compare", params: { a: "F_A", b: "F_B", scope: "sensitive" } });
    expect(redirect("sensitive", { tab: "compare" })).toEqual({ page: "compare", params: { scope: "sensitive" } });
    expect(redirect("sensitive", {})).toEqual({ page: "sensitive", params: {} });
    expect(redirect("see", { name: "HR_01" })).toEqual({ page: "see", params: { user: "HR_01" } });
    expect(redirect("graph", { table: "DB.S.T" })).toEqual({ page: "graph", params: { table: "DB.S.T" } });
    expect(redirect("compare", { a: "A", b: "B" })).toEqual({ page: "compare", params: { a: "A", b: "B" } });
  });
});
