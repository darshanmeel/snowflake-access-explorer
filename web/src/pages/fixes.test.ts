import { describe, expect, it } from "vitest";
import type { AccessObject, CatalogRow, GridRow, UsageRow } from "../api/types";
import { groupOf, shortcuts } from "./Home";
import { usageCsv, usageRows } from "./history";
import { byName, groupKey } from "./screens";
import { catalogCsv, catalogOf, gridRows, hits } from "./signoff";

const cat = (object: string, more: Partial<CatalogRow> = {}): CatalogRow => ({
  object, name: object.split(".").pop()!, ns: "DB.S", type: "TABLE", labels: [], groups: [], status: "protected", masked: [1, 1],
  columns: [], unmasked: 0, row_policies: [], readers: 3, admin: 0, ...more,
});
const grow = (user: string, roles: string[]): GridRow => ({
  user, type: "PERSON", status: "active", days: 1, last_login: "", admin: [], roles, suggest: null, cells: {},
});
const use = (object: string): UsageRow => ({
  object, type: "TABLE", database: "DB", schema: "S", sensitive: false, level: "change", used: null, privileges: ["SELECT"],
  unused: ["SELECT"], weeks: [], reads: 0, writes: 0, last: null, people: [], holder: "T_R", suggest: "drop", text: "", changes: [],
});
const obj = (object: string, type: string, schema: string | null) => ({ object, type, database: "DB", schema } as AccessObject);

describe("list toolbar search and CSV", () => {
  it("matches any text, any case", () => {
    expect(hits("", "A")).toBe(true);
    expect(hits(" cust ", "DB.S.CUSTOMER")).toBe(true);
    expect(hits("x", "A", "B")).toBe(false);
  });
  it("searches the catalog, the review grid and granted vs used", () => {
    const rows = [cat("DB.S.LOG", { labels: ["PII=IP"] }), cat("DB.S.CUST", { columns: [{ column: "EMAIL", masked: true, policies: [] }] })];
    expect(catalogOf(rows, "all", "email").map((r) => r.object)).toEqual(["DB.S.CUST"]);
    expect(catalogOf(rows, "all", "pii=").map((r) => r.object)).toEqual(["DB.S.LOG"]);
    expect(catalogCsv(rows).split("\n")[0]).toContain("Columns not masked");
    expect(gridRows([grow("ANN", ["F_A"]), grow("BOB", ["F_B"])], true, false, "f_b").map((r) => r.user)).toEqual(["BOB"]);
    expect(usageRows([use("DB.S.A"), use("DB.S.B")], "all", "s.b").map((r) => r.object)).toEqual(["DB.S.B"]);
    expect(usageCsv([use("DB.S.A")]).split("\n")[1]).toContain("not used");
  });
});

describe("access list grouping and sort", () => {
  it("groups by schema or type, sorts by name", () => {
    expect(groupKey(obj("DB.S.T", "TABLE", "S"), "schema")).toBe("DB.S");
    expect(groupKey(obj("DB", "DATABASE", null), "schema")).toBe("DB");
    expect(groupKey(obj("DB.S.V", "VIEW", "S"), "type")).toBe("VIEW");
    expect(groupKey(obj("DB.S.V", "VIEW", "S"), "none")).toBe("");
    expect(byName([obj("DB.S.B", "TABLE", "S"), obj("DB.S.A", "TABLE", "S")]).map((x) => x.object)).toEqual(["DB.S.A", "DB.S.B"]);
  });
});

describe("Home search", () => {
  it("puts warehouses in their own group", () => {
    expect(groupOf({ kind: "object", type: "WAREHOUSE" })).toBe("warehouse");
    expect(groupOf({ kind: "object", type: "TABLE" })).toBe("object");
    expect(groupOf({ kind: "functional", type: null })).toBe("role");
  });
  it("fills the shortcuts with the first hit", () => {
    const u = shortcuts(["check", "graph", "compare", "rules"], { kind: "user", id: "ENGINEER_01", name: "ENGINEER_01" });
    expect(u.map((s) => s.label)).toEqual(["Can ENGINEER_01 read …?", "Graph of ENGINEER_01", "Compare ENGINEER_01 with …", "Risks & fixes"]);
    expect(u[0].params).toEqual({ name: "ENGINEER_01" });
    const t = shortcuts(["check", "graph", "compare"], { kind: "object", id: "DB.S.T", name: "DB.S.T" });
    expect(t.map((s) => s.label)).toEqual(["Can they read …?", "Graph of DB.S.T", "Compare two people"]);
    expect(t[1].params).toEqual({ table: "DB.S.T" });
    expect(shortcuts(["check"])[0]).toEqual({ page: "check", label: "Can they read …?", params: {} });
  });
});
