import { describe, expect, it } from "vitest";
import { adminText, adminTitle } from "./Object";

const cell = (has: boolean, admin: string | null = null) => ({ has, admin });

describe("Users × privileges, Admin column", () => {
  it("lists the admin roles and says the marked cells come through them", () => {
    const r = { admin: ["SYSADMIN"], unknown: [], real: false, cells: { SELECT: cell(true, "SYSADMIN") } };
    expect(adminText(r)).toBe("SYSADMIN");
    expect(adminTitle(r)).toContain('marked "admin"');
  });
  it("says all, via the role, when the snapshot holds nothing that shows what it gives", () => {
    const r = { admin: ["ORGADMIN"], unknown: ["ORGADMIN"], real: false, cells: { SELECT: cell(false) } };
    expect(adminText(r)).toBe("all, via ORGADMIN");
    expect(adminTitle(r)).toContain("not known");
  });
  it("says when the admin role reaches nothing here", () => {
    const r = { admin: ["USERADMIN"], unknown: [], real: false, cells: { SELECT: cell(false) } };
    expect(adminTitle(r)).toContain("no role it holds reaches this object");
  });
});
