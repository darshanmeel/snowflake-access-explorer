// Home as rendered: section order, headings in order, tiles and switches that work, charts that describe themselves.
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { HomePage, Meta } from "../api/types";
import { clearCache, setTransport } from "../api/client";
import { AppCtx, type Ctx } from "../ctx";
import { HomePageView } from "./Home";
import { dots } from "./homedata";

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
    readers: { active: 3, risky: 1, admin: 2, service: 1 },
    stale: { total: 1, by_status: { dormant: 1 }, of_status: { active: 3, dormant: 1 }, names: ["NAME_04"] },
    people: { by_status: { active: 3, dormant: 1 }, service: 1 }, roles: { functional: 2, technical: 4 }, objects: { by_type: [{ type: "TABLE", n: 9 }] },
    depth: { users: { 2: 1, 4: 3 }, objects: { 3: 9 }, schemas: { 3: 2 }, databases: { 3: 1 } },
    biggest: { schemas: [{ name: "DB.S", n: 9 }], databases: [{ name: "DB", n: 9 }], n_schemas: 1, n_databases: 1 },
    activity: { ok: true, reason: null, users: 3, daily: [{ day: "2026-11-13", queries: 5 }, { day: "2026-11-14", queries: 2 }, { day: "2026-11-16", queries: 9 }] },
    objuse: { ok: true, notes: [], new: 0, days: 90, unused: 4, unused_new: 0, types: [], nodata: [], read_only: 1, write_only: 0 },
    changes: { counts: null, high: 0, before: null, reason: "No earlier snapshot yet." },
  },
};

/** Home with params that c.set really changes, so its tabs switch. */
function Host({ nav, start }: { nav: Ctx["nav"]; start: Record<string, string> }) {
  const [params, setParams] = useState(start);
  const set = (p: Record<string, string | null | undefined>) => setParams((x) => {
    const y = { ...x };
    for (const [k, v] of Object.entries(p)) if (v == null) delete y[k]; else y[k] = v;
    return y;
  });
  return <AppCtx.Provider value={{ page: "home", params, view: "shared", meta, theme: "light", nav, set } as unknown as Ctx}><HomePageView /></AppCtx.Provider>;
}

const view = (nav = vi.fn(), start: Record<string, string> = {}) => {
  setTransport((_m, url) => (url.startsWith("/api/home") ? Promise.resolve(home) : Promise.resolve({ items: [] })));
  render(<Host nav={nav} start={start} />);
  return nav;
};

const heads = () => [...document.querySelectorAll("h2, h3")].map((h) => `${h.tagName}:${h.textContent}`);
const inOrder = (names: string[]) => {
  const hs = heads();
  const order = names.map((t) => hs.findIndex((h) => h.includes(t)));
  expect(order.every((i) => i >= 0)).toBe(true);
  expect(order).toEqual([...order].sort((x, y) => x - y));
  expect(hs.every((h) => h.startsWith("H2") || h.startsWith("H3"))).toBe(true);
};

describe("readers as dots", () => {
  it("draws one dot per person, and one per 100 for thousands; no group disappears", () => {
    const r = (id: "risky" | "admin" | "active", n: number) => ({ id, label: id, n });
    expect(dots([r("risky", 4), r("active", 15)]).per).toBe(1);
    const big = dots([r("risky", 3200), r("admin", 12), r("active", 440)]);
    expect([big.per, big.rows.map((x) => x.dots)]).toEqual([100, [32, 1, 4]]);
  });
});

describe("Home page", () => {
  it("keeps the sections of each tab in order with headings that never skip a level", async () => {
    view();
    await screen.findByText("1 inactive person can still read sensitive data");
    expect(heads()[0]).toBe("H2:1 inactive person can still read sensitive data");
    expect(screen.getByRole("img", { name: "Inactive 1, Admin 2, Service 1, Active 3" }).children).toHaveLength(7);
    inOrder(["1 inactive person", "1 of the 7 readers of sensitive data is inactive", "What to do first"]);
    expect(screen.getByText("Take admin roles from 2 people")).toBeTruthy();
    expect(screen.queryByRole("tab")).toBeNull(); // Now is one page
    fireEvent.click(screen.getByRole("button", { name: /At a glance/ }));
    inOrder(["Most findings are medium: 4 of 7", "Admin holders", "Dormant", "Sensitive data", "Findings by area", "People", "Role chain depth", "Activity", "Object activity"]);
    fireEvent.click(screen.getByRole("tab", { name: "Changes" }));
    expect(screen.getByText("No earlier snapshot yet.")).toBeTruthy();
  });

  it("tiles open their page; quick links are grouped; the depth switch is pressed", async () => {
    const nav = view();
    fireEvent.click(await screen.findByRole("button", { name: /3\s*critical or high findings/ }));
    expect(nav).toHaveBeenCalledWith("rules", { sev: "Critical" });
    fireEvent.click(screen.getByRole("button", { name: /At a glance/ }));
    expect(screen.getByRole("group", { name: "Ask a question" }).querySelectorAll("button")).toHaveLength(4);
    const objects = screen.getAllByRole("button", { name: "Objects" })[0];
    fireEvent.click(objects);
    expect(objects.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("img", { name: /Objects by chain depth: depth 3 9; most at depth 3/ })).toBeTruthy();
    expect(screen.getByText(/100% of objects are reached 3 roles away/)).toBeTruthy();
  });

  it("names the busiest day and the service users with admin; / focuses the search", async () => {
    view(vi.fn(), { show: "glance" });
    expect(await screen.findByRole("img", { name: /busiest 2026-11-16 with 9 queries/ })).toBeTruthy();
    expect(screen.getByText(/75% active/)).toBeTruthy();
    expect(screen.getByText("NAME_03")).toBeTruthy();
    await act(async () => { fireEvent.keyDown(window, { key: "/" }); });
    expect(document.activeElement).toBe(screen.getByLabelText("Search"));
    fireEvent.click(screen.getByRole("tab", { name: /Now/ }));
    expect(screen.getAllByText(/hold an admin role/).length).toBeGreaterThan(0);
  });
});
