import { describe, expect, it } from "vitest";
import type { PrivRow } from "../api/types";
import { combine, expand, normKind, pathGraph } from "./graphs";
import { wrap } from "./layout";
import { filterRows, sortRows, toCsv } from "./table";
import { tabGraph } from "./tabgraph";
import { privTab, tabList, tabRows } from "./tabs";

const row = (privilege: string, cls: PrivRow["cls"], type: string, object: string, path: string[], extra: Partial<PrivRow> = {}): PrivRow => ({
  privilege, cls, tab: privTab(privilege, type, cls), type, object, database: object.split(".")[0], schema: object.split(".")[1] ?? "",
  name: object.split(".").pop()!, future_label: null, holder: path[path.length - 1], depth: path.length - 1,
  path: [...path, object], count: 1, paths_note: "", sensitive: false, hidden: false, ...extra,
});

describe("categorising", () => {
  it("maps privileges to tabs", () => {
    expect(privTab("MANAGE GRANTS", "ACCOUNT")).toBe("account");
    expect(privTab("USAGE", "WAREHOUSE", "use")).toBe("warehouses");
    expect(privTab("OWNERSHIP", "TABLE", "own")).toBe("own");
    expect(privTab("USAGE", "PROCEDURE", "use")).toBe("execute");
    expect(privTab("EXECUTE TASK", "ACCOUNT", "admin")).toBe("account");
    expect(privTab("USAGE", "SCHEMA", "read")).toBe("usage");
    expect(privTab("SELECT", "TABLE", "read")).toBe("read");
    expect(privTab("INSERT", "TABLE", "write")).toBe("write");
    expect(privTab("CREATE TABLE", "SCHEMA", "manage")).toBe("manage");
  });

  it("counts tabs, drops empty ones but keeps All, hides hidden rows outside Usage", () => {
    const rows = [
      row("SELECT", "read", "TABLE", "S.C.T1", ["U", "F"]),
      row("USAGE", "read", "SCHEMA", "S.C", ["U", "F"], { tab: "usage", hidden: true }),
    ];
    const tabs = tabList(rows, [], { admin: [], privileges: [], public: ["VIEW LINEAGE"] });
    expect(tabs.map((t) => [t.key, t.count])).toEqual([["account", 1], ["usage", 1], ["read", 1], ["all", 1]]);
    expect(tabRows(rows, "usage")).toHaveLength(1);
  });
});

describe("graphs", () => {
  const kinds = { U: "user", F: "functional", T: "technical", "HR.R": "database" };

  it("puts roles on lanes by shortest depth and marks database-role links", () => {
    const g = pathGraph([
      { path: ["U", "F", "T", "S.C.T1"], cls: "read", privilege: "SELECT" },
      { path: ["U", "T", "S.C.T1"], cls: "read", privilege: "SELECT" },
      { path: ["U", "F", "HR.R", "HR.P.T2"], cls: "read", privilege: "SELECT" },
    ], { kinds });
    const lane = Object.fromEntries(g.nodes.map((n) => [n.id, n.lane]));
    expect(lane).toMatchObject({ U: 0, F: 1, T: 1, "HR.R": 2, "S.C.T1": 3, "HR.P.T2": 3 });
    expect(g.edges.find((e) => e.target === "HR.R")!.cls).toBe("inherit_db");
    expect(g.edges.find((e) => e.source === "F" && e.target === "T")!.back).toBe(true);
    const r = g.nodes.find((n) => n.id === "HR.R")!;
    expect([r.kind, r.label, r.sub]).toEqual(["database_role", "R", "HR"]);
    expect(normKind("something_new")).toBe("group");
  });

  it("combines objects per database over the limit and expands back", () => {
    const paths = Array.from({ length: 14 }, (_, i) => ({ path: ["U", "F", "T", `${i < 10 ? "A" : "B"}.S.T${i}`], cls: "read" as const, privilege: "SELECT" }));
    const g = pathGraph(paths, { kinds, max: 12 });
    const boxes = g.nodes.filter((n) => n.kind === "database_group").map((n) => [n.id, g.groups[n.id].count]);
    expect(boxes).toEqual([["db:A", 10], ["db:B", 4]]);
    expect(g.edges.find((e) => e.target === "db:A")!.count).toBe(10);
    const open = expand(g, new Set(["db:A"]));
    expect(open.nodes.filter((n) => n.kind === "object")).toHaveLength(10);
    expect(open.edges.filter((e) => e.source === "T" && e.cls === "read")).toHaveLength(11); // 10 objects + box B
  });

  it("folds a crowded role lane and remaps edges of closed boxes", () => {
    const paths = Array.from({ length: 13 }, (_, i) => ({ path: ["U", `F${i}`, `X.S.T${i}`], cls: "read" as const }));
    const g = combine(pathGraph(paths, { kinds: { U: "user" }, max: 99 }), 12);
    expect(g.nodes.map((n) => n.id).sort()).toEqual(["U", "db:X", "lane:1"]);
    const open = expand(g, new Set(["lane:1"]));
    expect(open.nodes).toHaveLength(15);
    expect(open.edges.filter((e) => e.target === "db:X")).toHaveLength(13);
  });

  it("draws the Account tab in red with PUBLIC grouped", () => {
    const g = tabGraph({
      tab: "account", rows: [],
      account: { admin: [{ role: "SYSADMIN", path: ["U", "F", "SYSADMIN"] }], privileges: [], public: ["VIEW LINEAGE"] },
      refs: { kinds: { U: "user", F: "functional" }, types: {}, labels: {}, sensitive: [], disabled: [] },
    });
    expect(g.nodes.find((n) => n.id === "SYSADMIN")!.kind).toBe("admin");
    const p = g.nodes.find((n) => n.label === "VIEW LINEAGE")!;
    expect(p.kind).toBe("admin");
    expect(g.edges.find((e) => e.target === p.id)).toMatchObject({ source: "PUBLIC", cls: "admin" });
  });
});

describe("helpers", () => {
  it("wraps names after _ or .", () => {
    expect(wrap("T_SALES_CORE_PIPELINE_READ_ALL", 12)).toEqual(["T_SALES_CORE_", "PIPELINE_", "READ_ALL"]);
  });
  it("sorts, filters and writes CSV", () => {
    const rows = [{ a: "x10", n: 2 }, { a: "x9", n: 10 }];
    expect(sortRows(rows, (r) => r.a, 1).map((r) => r.a)).toEqual(["x9", "x10"]);
    expect(sortRows(rows, (r) => r.n, -1)[0].n).toBe(10);
    expect(filterRows(rows, "X1", [(r) => r.a])).toHaveLength(1);
    expect(toCsv(["a"], [['he said "hi", ok']])).toBe('a\r\n"he said ""hi"", ok"');
  });
});
