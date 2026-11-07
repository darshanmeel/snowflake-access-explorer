import { describe, expect, it } from "vitest";
import type { WhoEntry } from "../api/types";
import { byLevel, sameLabel, stepsOf } from "./who";

const e = (name: string, level: WhoEntry["level"], path: string[], privileges = ["SELECT"]): WhoEntry =>
  ({ name, level, privileges, path, first: path.length > 3 ? path[1] : null, holder: path[path.length - 2], ways: 1, depth: 1 });
const kinds = { ENGINEER_01: "user", F_ENGINEER: "functional", T_W: "technical", "DB.S.T": "object", SYSADMIN: "admin", PUBLIC: "group" };

describe("who has access", () => {
  it("groups by level, highest first, empty levels left out", () => {
    const g = byLevel([e("A", "read", ["A", "R", "O"]), e("B", "admin", ["B", "SYSADMIN"]), e("C", "read", ["C", "R", "O"])]);
    expect(g.map((x) => [x.level, x.rows.map((r) => r.name)])).toEqual([["admin", ["B"]], ["read", ["A", "C"]]]);
  });
  it("lists the steps of the shortest path, the holder with what it grants", () => {
    const s = stepsOf(e("ENGINEER_01", "change", ["ENGINEER_01", "F_ENGINEER", "T_W", "DB.S.T"], ["INSERT", "SELECT"]), kinds);
    expect(s).toEqual([{ name: "ENGINEER_01", kind: "User" }, { name: "F_ENGINEER", kind: "Functional role" },
      { name: "T_W", kind: "Technical role · grants INSERT, SELECT" }, { name: "DB.S.T", kind: "INSERT, SELECT" }]);
    const a = stepsOf(e("OPS_01", "admin", ["OPS_01", "SYSADMIN"], []), kinds, true);
    expect(a).toEqual([{ name: "OPS_01", kind: "User · disabled" }, { name: "SYSADMIN", kind: "Admin role · inherits every role" }]);
  });
  it("names a group of people with the same route", () => {
    expect(sameLabel(["A", "B", "C"], ["PUBLIC", "WH"])).toBe("3 people via PUBLIC (everyone)");
    expect(sameLabel(["A"], ["F_X", "T_Y", "WH"])).toBe("A via F_X");
  });
});
