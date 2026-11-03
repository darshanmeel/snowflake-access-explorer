import { describe, expect, it } from "vitest";
import type { PrivRow } from "../api/types";
import { buckets, combine, edgeTip, expand, foldRoles, makeNode, normKind, pathGraph, related } from "./graphs";
import { labelSpots, roundPath, wrap } from "./layout";
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
    const kinds = { U: "user", ...Object.fromEntries(paths.map((p) => [p.path[1], "functional"])) };
    const g = combine(pathGraph(paths, { kinds, max: 99 }), 12);
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

describe("folding and opening", () => {
  it("folds the database roles of one database into one box counted by grant class, and opens it", () => {
    const cls = ["read", "write", "manage"] as const;
    const paths = Array.from({ length: 9 }, (_, i) => ({ path: ["U", "G", `HR.R${i}`, `HR.S.T${i}`], cls: cls[i % 3], privilege: "X" }));
    const kinds = { U: "user", G: "group", ...Object.fromEntries(paths.map((p) => [p.path[2], "database"])) };
    const g = pathGraph(paths, { kinds, max: 99 });
    const box = g.nodes.find((n) => n.id === "fold:2:db:HR")!;
    expect([box.kind, box.label, box.sub, box.badge]).toEqual(["database_role", "HR", "9 database roles", "3 read · 3 write · 3 manage"]);
    expect(g.edges.find((e) => e.source === "G" && e.target === box.id)!.count).toBe(9);
    expect(foldRoles(g)).toBe(g); // nothing left to fold
    const open = expand(g, new Set([box.id]));
    expect(open.nodes.filter((n) => n.kind === "database_role")).toHaveLength(9);
    expect(open.groups[box.id]).toBeUndefined();
  });

  it("opens a huge box by schema, then type, never member by member", () => {
    const ms = Array.from({ length: 500 }, (_, i) => makeNode(`SNOWFLAKE.${i < 380 ? "CORE" : "ML"}.F${i}`, "object", 2,
      { db: "SNOWFLAKE", schema: i < 380 ? "CORE" : "ML", type: i % 50 ? "FUNCTION" : "PROCEDURE", label: `F${i}` }));
    const g = combine(pathGraph(ms.map((n) => ({ path: ["U", "R", n.id], cls: "use" as const })), { kinds: { U: "user" }, max: 99 }), 12);
    const g2 = { ...g, groups: { ...g.groups, "db:SNOWFLAKE": { ...g.groups["db:SNOWFLAKE"], nodes: ms } } };
    const one = expand(g2, new Set(["db:SNOWFLAKE"]));
    expect(one.nodes.filter((n) => n.lane === 2).map((n) => [n.label, n.sub])).toEqual([["SNOWFLAKE.CORE", "380 objects"], ["SNOWFLAKE.ML", "120 objects"]]);
    const two = expand(g2, new Set(["db:SNOWFLAKE", "db:SNOWFLAKE/SNOWFLAKE.CORE"]));
    expect(two.nodes.filter((n) => n.lane === 2).map((n) => n.sub)).toEqual(["120 objects", "372 functions", "8 procedures"]);
    expect(buckets(ms.slice(0, 20))).toBeNull();
    const many = buckets(ms.slice(0, 300).map((n) => ({ ...n, type: "FUNCTION" })))!;
    expect(many.length).toBeLessThanOrEqual(12);
    expect(many.reduce((s, b) => s + b.members.length, 0)).toBe(300);
  });

  it("lights up every path through a node or a line, and says what a line is", () => {
    const g = pathGraph([
      { path: ["U", "F", "T", "S.C.T1"], cls: "read", privilege: "SELECT" },
      { path: ["U", "F2", "T2", "S.C.T2"], cls: "write", privilege: "INSERT" },
    ], { kinds: { U: "user", F: "functional", F2: "functional", T: "technical", T2: "technical" } });
    expect([...related(g, "T")].filter((x) => !x.includes(">")).sort()).toEqual(["F", "S.C.T1", "T", "U"]);
    expect(related(g, "F>T>inherit").has("T2")).toBe(false);
    const by = new Map(g.nodes.map((n) => [n.id, n]));
    expect(edgeTip(g.edges.find((e) => e.id === "F>T>inherit")!, by, g.groups)).toBe("F is granted role T");
    expect(edgeTip(g.edges.find((e) => e.target === "S.C.T2")!, by, g.groups)).toBe("T2 has INSERT on object S.C.T2");
  });
});

describe("routes", () => {
  it("rounds corners and puts a count on a stretch the line has to itself", () => {
    expect(roundPath([{ x: 0, y: 0 }, { x: 20, y: 0 }, { x: 20, y: 20 }], 8)).toBe("M0,0 L12,0 Q20,0 20,8 L20,20");
    const spots = labelSpots(new Map([
      ["a", [{ x: 0, y: 0 }, { x: 100, y: 0 }]],
      ["b", [{ x: 0, y: 0 }, { x: 40, y: 0 }, { x: 40, y: 30 }, { x: 100, y: 30 }]],
    ]));
    expect(spots.get("a")).toEqual({ x: 70, y: 0 });
    expect(spots.get("b")).toEqual({ x: 70, y: 30 });
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
