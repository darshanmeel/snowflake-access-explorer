// Home as rendered: section order, headings in order, tiles and switches that work, charts that describe themselves.
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { HomePage, Meta } from "../api/types";
import { clearCache, setTransport } from "../api/client";
import { AppCtx, type Ctx } from "../ctx";
import { HomePageView } from "./Home";

afterEach(() => { cleanup(); clearCache(); setTransport(null as never); });

const meta = {
  pages: ["home", "check", "compare", "whatif", "request", "graph", "flow", "usage", "changes", "objuse", "rules"].map((key) => ({ key, label: key, group: "ask" })),
  default_user: "", notes: [], sources: {}, inside: false, prefixes: { func: "F_", tech: "T_" },
  rules: [{ num: "5", area: "Admin", title: "Admin role on a person" }, { num: "9", area: "Role model", title: "PUBLIC grant" }, { num: "24", area: "Activity", title: "Person changed a table" }],
} as unknown as Meta;

const home: HomePage = {
  view: "shared", me: null, risks: { Critical: 2, High: 1, Medium: 4, Low: 0 }, counts: { users: 4, roles: 6, objects: 9, sensitive: 2 },
  per_rule: { 5: 2, 9: 5, 24: 1 }, rule_sev: { Critical: { 5: 2 }, High: { 9: 1 }, Medium: { 9: 4 } },
  subjects: { Critical: { people: 2, roles: 0 }, High: { people: 0, roles: 1 }, Medium: { people: 1, roles: 2 }, Low: { people: 0, roles: 0 } },
  act_first: [{ num: "5", severity: "Critical", title: "Admin role on a person", findings: 2, subjects: 2, names: [{ id: "NAME_01 (user)", kind: "user" }, { id: "NAME_02 (user)", kind: "user" }] }],
  skipped: {}, protection: { unmasked: 3, unmasked_names: [], unmasked_columns: 3, dormant: 1, dormant_names: [], tagged: 2, masked: 5, row_tables: 1 },
  cards: {
    admins: { total: 2, service: 1, by_role: [{ role: "ACCOUNTADMIN", people: 2 }], account_only: 0, names: [{ user: "NAME_01", role: "ACCOUNTADMIN", login: "2026-11-01" }],
      service_names: [{ user: "NAME_03", role: "ACCOUNTADMIN", login: "never" }] },
    stale: { total: 1, by_status: { dormant: 1 }, of_status: { active: 3, dormant: 1 }, names: ["NAME_04"] },
    people: { by_status: { active: 3, dormant: 1 }, service: 1 }, roles: { functional: 2, technical: 4 }, objects: { by_type: [{ type: "TABLE", n: 9 }] },
    depth: { users: { 2: 1, 4: 3 }, objects: { 3: 9 }, schemas: { 3: 2 }, databases: { 3: 1 } },
    biggest: { schemas: [{ name: "DB.S", n: 9 }], databases: [{ name: "DB", n: 9 }], n_schemas: 1, n_databases: 1 },
    activity: { ok: true, reason: null, users: 3, daily: [{ day: "2026-11-13", queries: 5 }, { day: "2026-11-14", queries: 2 }, { day: "2026-11-16", queries: 9 }] },
    objuse: { ok: true, notes: [], new: 0, days: 90, unused: 4, unused_new: 0, types: [], nodata: [], read_only: 1, write_only: 0 },
    changes: { counts: null, high: 0, before: null, reason: "No earlier snapshot yet." },
  },
};

const view = (nav = vi.fn()) => {
  setTransport((_m, url) => (url.startsWith("/api/home") ? Promise.resolve(home) : Promise.resolve({ items: [] })));
  render(<AppCtx.Provider value={{ page: "home", params: {}, view: "shared", meta, theme: "light", nav, set: vi.fn() } as unknown as Ctx}><HomePageView /></AppCtx.Provider>);
  return nav;
};

describe("Home page", () => {
  it("keeps the sections in order with headings that never skip a level", async () => {
    view();
    await screen.findByText("Needs attention");
    const hs = [...document.querySelectorAll("h2, h3")].map((h) => `${h.tagName}:${h.textContent}`);
    const at = (t: string) => hs.findIndex((h) => h.includes(t));
    expect(hs[0]).toBe("H2:Who can access what in Snowflake?");
    const order = ["Needs attention", "Act first", "All findings by severity", "Admin holders", "Dormant", "Sensitive data",
      "at a glance", "People", "Role chain depth", "Activity", "Object activity", "What changed"].map(at);
    expect(order.every((i) => i >= 0)).toBe(true);
    expect(order).toEqual([...order].sort((x, y) => x - y));
    expect(hs.every((h) => h.startsWith("H2") || h.startsWith("H3"))).toBe(true);
    expect(screen.getByText("No earlier snapshot yet.")).toBeTruthy();
  });

  it("tiles open their page; quick links are grouped; the depth switch is pressed", async () => {
    const nav = view();
    fireEvent.click(await screen.findByRole("button", { name: /Critical or high\s*3/ }));
    expect(nav).toHaveBeenCalledWith("rules", { sev: "Critical" });
    fireEvent.click(screen.getByRole("button", { name: /Not used\s*4/ }));
    expect(nav).toHaveBeenCalledWith("objuse", {});
    expect(screen.getByRole("group", { name: "Ask a question" }).querySelectorAll("button")).toHaveLength(4);
    expect(screen.getByRole("group", { name: "Explore" }).querySelectorAll("button")).toHaveLength(5);
    const objects = screen.getAllByRole("button", { name: "Objects" })[0];
    fireEvent.click(objects);
    expect(objects.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("img", { name: /Objects by chain depth: depth 3 9; most at depth 3/ })).toBeTruthy();
    expect(screen.getByText(/100% of objects are reached 3 roles away/)).toBeTruthy();
  });

  it("names the busiest day and the service users with admin; / focuses the search", async () => {
    view();
    expect(await screen.findByRole("img", { name: /busiest 2026-11-16 with 9 queries/ })).toBeTruthy();
    expect(screen.getByText("NAME_03")).toBeTruthy();
    expect(screen.getByText(/75% active/)).toBeTruthy();
    await act(async () => { fireEvent.keyDown(window, { key: "/" }); });
    expect(document.activeElement).toBe(screen.getByLabelText("Search"));
  });
});
