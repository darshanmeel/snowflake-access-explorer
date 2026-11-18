// Risks & fixes asks the server for one page at a time: the groups and counts first, a group's findings when it
// opens, a finding's fix text when its Fix button is pressed.
import { afterEach, describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { clearCache, setTransport } from "../api/client";
import { AppCtx, type Ctx } from "../ctx";
import { Root } from "../components";
import { rulesOff } from "./changeplan";
import { RulesPageView } from "./Rules";

globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as never;
const refs = { kinds: { PUBLIC: "group" }, types: {}, labels: {}, sensitive: [], disabled: [] };
const rule = { num: "9", title: "PUBLIC grant", why: "", severity: "High", area: "Role model", spot: "", meaning: "", fix: "" };
const ctx = { page: "rules", params: {}, view: "shared", meta: { pages: [], default_user: "", rules: [rule] }, theme: "light",
  nav: () => {}, set: () => {} } as unknown as Ctx;
const row = { id: 7, num: "9", title: "PUBLIC grant", severity: "High", area: "Role model", grantee: "PUBLIC", kind: "group",
  what: "SELECT on DB.S.T", impact: null, people: [], people_total: 0, paths: [["PUBLIC", "DB.S.T"]], paths_total: 1, fix: true,
  same_fix: "", changes: [], objects: ["DB.S.T"] };
const page = {
  view: "shared", scope: "account", filters: { grantee: "", sev: "High", rule: "", q: "", area: "", people: false, off: [], by: "rule", group: null },
  counts: { High: 1, Medium: 0, Low: 0, Passing: 28 }, per_rule: { 9: 1 }, skipped: {}, sev_counts: { Critical: 0, High: 1, Medium: 0, Low: 0 },
  hidden_off: 0, areas: ["Role model"], total: 1, groups: [{ key: "9", title: "PUBLIC grant", severity: "High", findings: 1, rules: 1, people: 0, kind: null }],
  groups_total: 1, grid: null, findings: [row], findings_total: 1, offset: 0, limit: 100, rows_unknown: [], admins: [], admins_total: 0, refs };
afterEach(() => { cleanup(); clearCache(); });

describe("Risks & fixes", () => {
  it("loads groups, then a group's page, then a finding's fix", async () => {
    const asked: string[] = [];
    setTransport(async (_m, url) => {
      asked.push(url);
      if (url.startsWith("/api/finding")) return { view: "shared", finding: { ...row, iac: "REVOKE SELECT ON DB.S.T FROM ROLE PUBLIC;", sql: "", paths: row.paths }, refs };
      return page;
    });
    render(<AppCtx.Provider value={ctx}><Root theme="light"><RulesPageView /></Root></AppCtx.Provider>);
    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });
    expect(asked[0]).toMatch(/^\/api\/rules\?/);
    expect(asked.some((u) => /group=9/.test(u) && /limit=50/.test(u))).toBe(true); // the only group opens and loads its page
    expect(asked.some((u) => u.startsWith("/api/finding"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Fix" }));
    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });
    expect(asked.some((u) => u.startsWith("/api/finding?") && /id=7/.test(u))).toBe(true);
    expect(screen.getByText("REVOKE SELECT ON DB.S.T FROM ROLE PUBLIC;")).toBeTruthy();
  });
  it("draws the change plan view by rule and the heat grid from the server's groups, rules off sent along", async () => {
    rulesOff.set(["5"]);
    const asked: string[] = [];
    const grid = { rules: ["9"], rows: [{ grantee: "PUBLIC", kind: "group", severity: "High", total: 1, counts: { 9: 1 } }] };
    setTransport(async (_m, url) => { asked.push(url); return { ...page, grid, filters: { ...page.filters, by: /by=grid/.test(url) ? "grid" : "rule" } }; });
    for (const by of ["rule", "grid"]) {
      const c = { ...ctx, params: { show: "fixes", by } } as unknown as Ctx;
      render(<AppCtx.Provider value={c}><Root theme="light"><RulesPageView /></Root></AppCtx.Provider>);
      await act(async () => { await new Promise((r) => setTimeout(r, 50)); });
      expect(screen.getAllByText(/PUBLIC grant|PUBLIC/).length).toBeGreaterThan(0);
      cleanup(); clearCache();
    }
    expect(asked.some((u) => /by=grid/.test(u) && /sev=all/.test(u) && /off=5/.test(u))).toBe(true);
    expect(asked.every((u) => !u.startsWith("/api/rules") || /by=rule/.test(u) || /by=grid/.test(u))).toBe(true);
    rulesOff.set([]);
  });
});
