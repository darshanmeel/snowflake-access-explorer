import { describe, expect, it } from "vitest";
import type { HomePage } from "../api/types";
import { areaTakeaway, attention, busiest, depthRows, depthTakeaway, pct, peopleTakeaway, weekend } from "./homedata";

describe("Home takeaways", () => {
  it("rounds shares and never shows a small share as none", () => {
    expect(pct(1, 3)).toBe("33%");
    expect(pct(1, 1000)).toBe("<1%");
    expect(pct(0, 0)).toBe("0%");
  });
  it("shades weekends from the date alone and names the busiest day", () => {
    expect(weekend("2026-11-14")).toBe(true); // Saturday
    expect(weekend("2026-11-15")).toBe(true);
    expect(weekend("2026-11-16")).toBe(false);
    expect(busiest([{ day: "a", queries: 3 }, { day: "b", queries: 9 }, { day: "c", queries: 9 }])?.day).toBe("b");
    expect(busiest([])).toBeNull();
  });
  it("fills missing depths and names the depth with the most", () => {
    const rows = depthRows({ 2: 6, 4: 30 });
    expect(rows).toEqual([{ d: 2, n: 6 }, { d: 3, n: 0 }, { d: 4, n: 30 }]);
    expect(depthTakeaway(rows, "users")).toBe("83% of users sit 4 roles away from what they can reach.");
    expect(depthTakeaway([{ d: 1, n: 5 }], "schemas")).toBe("100% of schemas are reached 1 role away from the user.");
    expect(depthTakeaway([], "objects")).toBe("No objects reached through a role chain.");
  });
  it("says how many are active and the biggest area", () => {
    expect(peopleTakeaway({ active: 1, dormant: 2, never: 1 }, 1)).toBe("25% active. Includes 1 service user.");
    expect(areaTakeaway([{ area: "Role model", total: 88 }, { area: "Activity", total: 12 }])).toBe("Role model has 88% of all findings.");
    expect(areaTakeaway([])).toBe("");
  });
});

describe("Needs attention", () => {
  const d = {
    risks: { Critical: 2, High: 3, Medium: 9, Low: 0 }, rule_sev: { Critical: { 5: 2 }, High: { 9: 1, 12: 2 } },
    protection: { dormant: 1, unmasked_columns: 0 },
    cards: { admins: { total: 4 }, objuse: { ok: true, unused: 7, days: 90 } },
  } as unknown as HomePage;
  it("one tile per problem, its tone from the count, each opening its page", () => {
    const t = attention(d, () => false);
    expect(t.map((x) => [x.key, x.n, x.tone])).toEqual([["risk", 5, "bad"], ["stale", 1, "bad"], ["mask", 0, null], ["admin", 4, "warn"], ["unused", 7, "warn"]]);
    expect(t[0].text).toBe("findings in 3 rules");
    expect(t[0].params).toEqual({ sev: "Critical" });
    expect(t[1].text).toBe("dormant or disabled person can still read it");
    expect(t[4]).toMatchObject({ page: "objuse", text: "objects not used in 90 days" });
  });
  it("leaves out tiles whose source was not read", () => {
    expect(attention(d, (k) => k === "policies" || k === "users").map((x) => x.key)).toEqual(["risk", "admin", "unused"]);
    expect(attention(d, (k) => k === "grants")).toEqual([]);
    const off = { ...d, cards: { ...d.cards!, objuse: { ...d.cards!.objuse, ok: false } } } as HomePage;
    expect(attention(off, () => false).map((x) => x.key)).not.toContain("unused");
  });
});

describe("headline", () => {
  const d = (risks: Record<string, number>, dormant: number) => ({ risks, protection: { dormant } }) as unknown as HomePage;
  it("says the worst thing true now, and never a number from a source that was not read", async () => {
    const { headline, severityTakeaway } = await import("./homedata");
    const none = () => false;
    expect(headline(d({ Critical: 5, High: 1 }, 4), none)).toBe("4 inactive people can still read sensitive data");
    expect(headline(d({ Critical: 5, High: 1 }, 4), (k) => k === "users")).toBe("5 critical findings to fix");
    expect(headline(d({ Critical: 0, High: 1 }, 0), none)).toBe("1 high finding to fix, none critical");
    expect(headline(d({ Critical: 0, High: 0 }, 0), none)).toBe("No critical or high findings");
    expect(headline(d({ Critical: 5 }, 4), (k) => k === "grants")).toBe("The grants were not read");
    expect(severityTakeaway({ Critical: 5, High: 18, Medium: 33, Low: 12 })).toBe("The biggest group of findings is medium: 33 of 68");
  });
});
