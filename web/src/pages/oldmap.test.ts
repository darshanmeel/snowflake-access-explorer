import { describe, expect, it } from "vitest";
import { mine, redirect } from "../App";
import { screensFor, shortcuts } from "./Home";
import type { Params } from "../ctx";

// specs/old-to-new-map.md, one row each: the old link (page, params) -> where it lands. Old pages stay as default tabs.
const MAP: [string, string | null, Params, string, Params][] = [
  ["1 User · Privileges", "user", { name: "U" }, "user", { name: "U" }],
  ["1 Privileges sub-tab -> level chip", "access", { user: "U", filter: "read" }, "access", { user: "U", filter: "read", show: "summary" }],
  ["2 Reached more than one way", "user", { name: "U", part: "multi" }, "user", { name: "U", part: "multi" }],
  ["2 ?filter=multi", "access", { name: "U", filter: "multi" }, "access", { user: "U", filter: "multi", show: "summary" }],
  ["3 What they see", "user", { name: "U", part: "sees" }, "see", { user: "U", part: "sees" }],
  ["4 Sensitive data they can see", "user", { name: "U", part: "sens" }, "see", { user: "U", part: "sens" }],
  ["4 ?only=sensitive", "see", { user: "U", only: "sensitive" }, "see", { user: "U" }],
  ["4 ?only=all", "see", { name: "U", only: "all" }, "see", { user: "U", all: "1" }],
  ["5 Role usage", "user", { name: "U", part: "usage" }, "see", { user: "U", part: "usage" }],
  ["6 Role · Privileges", "role", { name: "R" }, "role", { name: "R" }],
  ["6 ?role=", "access", { role: "R" }, "access", { role: "R" }],
  ["7 Role · Held by", "role", { name: "R", part: "held" }, "role", { name: "R", part: "held" }],
  ["8 Role · What it sees", "role", { name: "R", part: "sees" }, "see", { role: "R", part: "sees" }],
  ["9 Role · What it holds", "role", { name: "R", part: "holds" }, "role", { name: "R", part: "holds" }],
  ["10 Object · Who has access", "object", { name: "D.S.T" }, "object", { name: "D.S.T" }],
  ["10 by path -> graph", "object", { name: "D.S.T", by: "path" }, "graph", { table: "D.S.T" }],
  ["11 Users x privileges", "object", { name: "D.S.T", part: "users" }, "object", { name: "D.S.T", part: "users" }],
  ["11 privilege grid", "review", { object: "D.S.T", columns: "privileges" }, "review", { object: "D.S.T", columns: "privileges" }],
  ["12 Sensitive objects", "sensitive", {}, "sensitive", {}],
  ["12 Catalog", "catalog", {}, "sensitive", { show: "catalog" }],
  ["13 Who can read them", "sensitive", { part: "readers" }, "sensitive", { part: "readers" }],
  ["14 Compare two roles", "sensitive", { a: "A", b: "B" }, "compare", { a: "A", b: "B", scope: "sensitive" }],
  ["15 Can they?", "check", { name: "U", obj: "D.S.T" }, "check", { name: "U", obj: "D.S.T" }],
  ["15 ?who=&what=", "check", { who: "U", what: "D.S.T" }, "check", { name: "U", obj: "D.S.T" }],
  ["16 Findings", "rules", { sev: "High" }, "rules", { sev: "High" }],
  ["16 severity tile", "risks", { sev: "High" }, "rules", { sev: "High", show: "fixes" }],
  ["17 Admin holders", "rules", { tab: "admins" }, "object", { preset: "admin" }],
  ["18 Rules", "rules", { tab: "rules" }, "rules", { show: "list" }],
  ["18 rule list", "rulelist", {}, "rules", { show: "list" }],
  ["19 Review · Sensitive objects", "review", { part: "sens" }, "review", { part: "sens" }],
  ["19 scope Sensitive data", "review", { scope: "sensitive" }, "review", { scope: "sensitive", show: "grid" }],
  ["20 scope Everything", "review", { scope: "all" }, "review", { scope: "all", show: "grid" }],
  ["21 What if · Users", "whatif", { changes: "[]" }, "whatif", { changes: "[]" }],
  ["21 group by People", "whatif", { by: "people" }, "whatif", { by: "people", show: "plan" }],
  ["22 group by Objects", "whatif", { by: "objects" }, "whatif", { by: "objects", show: "plan" }],
  ["23 group by Roles", "whatif", { by: "roles" }, "whatif", { by: "roles", show: "plan" }],
  ["24 group by Findings", "whatif", { by: "findings" }, "whatif", { by: "findings", show: "plan" }],
  ["25 Text to apply", "whatif", { part: "fix" }, "whatif", { part: "fix" }],
  ["- Landing", null, {}, "home", {}],
  ["- builtin=1", "graph", { builtin: "1" }, "graph", { builtin: "1" }],
  ["- /me", "me", {}, "access", {}],
];

describe("old-to-new map", () => {
  it.each(MAP)("%s", (_n, page, params, to, out) => {
    expect(redirect(page, params)).toEqual({ page: to, params: out });
  });
  it("opens My access from ?data=mine and ?page=me", () => {
    expect(mine("me", null)).toBe(true);
    expect(mine("access", "mine")).toBe(true);
    expect(mine("access", null)).toBe(false);
  });
});

describe("Home", () => {
  const pages = [{ key: "graph", label: "Access graph" }, { key: "compare", label: "Compare" }, { key: "usage", label: "Granted vs used" }] as const;
  it("finds screens by name", () => {
    expect(screensFor("graph", [...pages]).map((p) => p.key)).toEqual(["graph"]);
    expect(screensFor("used", [...pages]).map((p) => p.key)).toEqual(["usage"]);
    expect(screensFor("g", [...pages])).toEqual([]);
  });
  it("shows only shortcuts to pages in the nav", () => {
    const all = shortcuts(["check", "graph", "compare", "flow", "usage", "changes", "request", "rules", "whatif", "sensitive"]);
    expect(all.map((s) => s.page)).toEqual(expect.arrayContaining(["graph", "compare", "flow", "usage", "changes", "request"]));
    expect(shortcuts(["check", "graph", "usage"]).map((s) => s.page)).toEqual(["check", "graph", "usage"]);
  });
});
