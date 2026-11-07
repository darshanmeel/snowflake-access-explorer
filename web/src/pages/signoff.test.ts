import { describe, expect, it } from "vitest";
import { redirect } from "../App";
import type { CatalogRow, GridRow } from "../api/types";
import { catalogOf, catalogSentence, follow, gridRows, protectionText, revokesOf, signoffCsv } from "./signoff";

const row = (user: string, more: Partial<GridRow> = {}): GridRow => ({
  user, type: "PERSON", status: "active", days: 1, last_login: "2026-11-01", admin: [], roles: ["F_A"], suggest: null,
  cells: { "DB.S.T": { level: "read", privileges: ["SELECT"], path: [user, "F_A", "T_R", "DB.S.T"] } }, ...more,
});
const cat = (object: string, more: Partial<CatalogRow>): CatalogRow => ({
  object, name: object.split(".").pop()!, ns: "DB.S", type: "TABLE", labels: [], groups: [], status: "protected", masked: [1, 1],
  columns: [], unmasked: 0, row_policies: [], readers: 3, admin: 0, ...more,
});

describe("review grid and sign-off", () => {
  const rows = [row("A"), row("B", { status: "disabled", suggest: "disabled", roles: ["F_A", "GRP_X"] }), row("SVC", { type: "SERVICE" })];
  it("filters people and the dormant or disabled", () => {
    expect(gridRows(rows, true, false).map((r) => r.user)).toEqual(["A", "B"]);
    expect(gridRows(rows, false, true).map((r) => r.user)).toEqual(["B"]);
  });
  it("turns revokes into What if changes", () => {
    expect(revokesOf(rows, { A: "keep", B: "revoke" })).toEqual([
      { op: "revoke_role_from_user", role: "F_A", user: "B" }, { op: "revoke_role_from_user", role: "GRP_X", user: "B" }]);
  });
  it("writes the sign-off CSV with reviewer, decision and time", () => {
    const t = signoffCsv({ columns: [{ id: "DB.S.T", name: "T", ns: "DB.S", note: "", sensitive: true }], scope: "sensitive", db: "", object: "" },
      rows.slice(0, 2), { B: "revoke" }, "Pat", "2026-11-07 10:00").split("\r\n");
    expect(t.slice(0, 5)).toEqual(["Access review sign-off", "Scope,sensitive data", "Reviewer,Pat", "Signed at,2026-11-07 10:00", "Decided,1 of 2"]);
    expect(t[6]).toBe("Person,Type,Status,Last login,Decision,Suggested,Granted roles,DB.S.T");
    expect(t[8]).toBe("B,PERSON,disabled,2026-11-01,revoke,revoke,F_A GRP_X,read (SELECT)");
  });
});

describe("catalog", () => {
  const rows = [
    cat("DB.S.LOG", { status: "not", masked: [0, 1], unmasked: 1, groups: ["pii"], columns: [{ column: "IP", masked: false, policies: [] }] }),
    cat("DB.S.CUST", { status: "partly", masked: [1, 3], unmasked: 2, groups: ["pii"] }),
    cat("DB.S.REV", { status: "whole", masked: [0, 0], groups: ["confidential"], row_policies: ["G.RAP_REGION"] }),
  ];
  it("filters and says what is open", () => {
    expect(catalogOf(rows, "open").map((r) => r.name)).toEqual(["LOG", "CUST"]);
    expect(catalogOf(rows, "confidential").map((r) => r.name)).toEqual(["REV"]);
    expect(catalogSentence(rows)).toBe("3 objects carry a sensitivity tag. 2 have columns with no masking (3 columns in total).");
    expect(protectionText(rows[1])).toBe("1 of 3 columns masked");
    expect(protectionText(rows[2])).toBe("Row policy RAP_REGION");
  });
});

describe("sensitive data flow", () => {
  const d = {
    groups: [{ id: "active", label: "Active people", users: ["A"] }, { id: "risky", label: "Dormant or disabled", users: ["D1", "D2"] }],
    roles: [{ id: "GRP_E", label: "GRP_E", users: ["A", "D1"] }, { id: "GRP_N", label: "GRP_N", users: ["D2"] }],
    objects: [{ id: "DB.S.REV", label: "REV", users: ["A", "D1"] }, { id: "DB.S.CUST", label: "CUST", users: ["D2"] }],
    links: [
      { source: "active", target: "GRP_E", users: ["A"] }, { source: "risky", target: "GRP_E", users: ["D1"] }, { source: "risky", target: "GRP_N", users: ["D2"] },
      { source: "GRP_E", target: "DB.S.REV", users: ["A", "D1"] }, { source: "GRP_N", target: "DB.S.CUST", users: ["D2"] },
    ],
  };
  it("follows the dormant or disabled", () => {
    const f = follow(d, "risky");
    expect(f.headline).toBe("2 dormant or disabled people still reach 2 sensitive objects, through GRP_E and GRP_N.");
    expect(f.width.get("GRP_E>DB.S.REV")).toBe(1);
    expect(f.width.has("active>GRP_E")).toBe(false);
    expect(f.lit?.has("active")).toBe(false);
    expect(f.tone.get("GRP_E>DB.S.REV")).toBe("risky");
  });
  it("follows an object back and shows everyone", () => {
    const f = follow(d, "DB.S.REV");
    expect([...f.lit!].sort()).toEqual(["DB.S.REV", "GRP_E", "active", "risky"]);
    expect(f.headline).toBe("REV: reached by 2 people through GRP_E.");
    expect(follow(d, null).headline).toBe("3 people reach 2 sensitive objects through 2 roles.");
  });
  it("sends the new links to their screens", () => {
    expect(redirect("catalog", {})).toEqual({ page: "sensitive", params: { show: "catalog" } });
    expect(redirect("dataflow", { sel: "risky" })).toEqual({ page: "flow", params: { sel: "risky" } });
    expect(redirect("sensitive", { show: "flow" })).toEqual({ page: "flow", params: {} });
    expect(redirect("signoff", { scope: "all" })).toEqual({ page: "review", params: { scope: "all", show: "grid" } });
    expect(redirect("review", { object: "DB.S.T", columns: "privileges" })).toEqual({ page: "review", params: { object: "DB.S.T", columns: "privileges" } });
    expect(redirect("flow", {})).toEqual({ page: "flow", params: {} });
  });
});
