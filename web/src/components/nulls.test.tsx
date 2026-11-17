// Missing or null data draws empty, never a crash: null names, a missing first day, an empty series.
import { afterEach, describe, expect, it } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import { clearCache, setTransport } from "../api/client";
import { AppCtx, type Ctx } from "../ctx";
import { ActivityTab, short } from "../pages/Activity";
import { Root } from "./index";
import { DayStack } from "./visuals";

globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as never;
globalThis.matchMedia ??= (() => ({ matches: false, addEventListener() {}, removeEventListener() {} })) as never;
const ctx = { page: "role", params: {}, view: "shared", meta: { pages: [], default_user: "" }, theme: "light", nav: () => {}, set: () => {} } as unknown as Ctx;
afterEach(() => { cleanup(); clearCache(); });

const N = 3, daily = [2, 0, 5];
const row = (user: string | null, action: string, last: string | null) => ({
  user, role: "F_ENGINEER", client: "Snowsight", type: "SELECT", object: "SALES.CORE.TBL_CUSTOMER", action, queries: 7, days: 2,
  first_day: "2026-11-01", last, daily, hours: Array(24).fill(0).map((_, h) => (h === 22 ? 7 : 0)), weekend: 0,
  weekend_hours: Array(24).fill(0), dh: [[0, 22, 2], [2, 22, 5]], kind: "person", interactive: true });
const group = (key: string | null) => ({ key, read: 7, write: 0, ddl: 0, last: "2026-11-03 22:15", daily });
const body = (first: string | null) => ({
  view: "shared", what: "role", kind: "role", name: "F_ENGINEER", user: null, days: N, available: true, reason: null,
  work: { start: 7, end: 19 }, note: null, first, last: "2026-11-03", daily, total: 7, gone: [], graph: null, sensitive: [],
  by: { user: [group(null)], role: [group("F_ENGINEER")], client: [group("Snowsight")], type: [group("SELECT")], object: [group("SALES.CORE.TBL_CUSTOMER")] },
  rows: [row(null, "READ", null)], ddl: [], query_sql: "", section_sql: {}, objects: {}, mark: null, app: null, findings: [],
  refs: { kinds: {}, types: {}, labels: {}, sensitive: [], disabled: [] } });

async function draw(b: unknown) {
  setTransport(async () => b);
  const errs: string[] = [];
  const oe = console.error;
  console.error = (...a: unknown[]) => { const s = a.map(String).join(" "); if (/Error/.test(s) && !/act\(/.test(s)) errs.push(s.slice(0, 300)); };
  try {
    render(<AppCtx.Provider value={ctx}><Root theme="light"><ActivityTab what="role" name="F_ENGINEER" /></Root></AppCtx.Provider>);
    await act(async () => { await new Promise((r) => setTimeout(r, 100)); });
  } finally { console.error = oe; }
  return errs;
}

describe("null and empty data", () => {
  it("short() shows a dash for a missing day, never Invalid Date", () => {
    expect([short(null), short(undefined), short(""), short("None")]).toEqual(["–", "–", "–", "–"]);
    expect(short("2026-11-03 22:15")).toBe("3 Nov");
  });

  it("DayStack draws nothing without a first day, and an empty series without a crash", () => {
    expect(render(<DayStack first="" series={[{ key: "a", values: [1, 2] }]} label="x" />).container.innerHTML).toBe("");
    expect(() => render(<DayStack first="2026-11-01" series={[]} label="x" />)).not.toThrow();
  });

  it("the Activity tab of a role draws with a null user name and a null last time", async () => {
    expect(await draw(body("2026-11-01"))).toEqual([]);
    expect(document.body.innerHTML).not.toMatch(/Invalid Date|NaN/);
  });

  it("the Activity tab without a first day says there is no activity", async () => {
    expect(await draw(body(null))).toEqual([]);
    expect(document.body.textContent).toContain("No table activity");
  });
});
