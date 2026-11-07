import { describe, expect, it } from "vitest";
import { redirect } from "../App";
import type { ChangeEvent, CheckPage, UsageRow, WhoPage } from "../api/types";
import { answerOf, bars, keep, question, recheck, trimText, usageRows, watchId, type Watch } from "./history";

const ev = (kind: ChangeEvent["kind"], more: Partial<ChangeEvent> = {}): ChangeEvent => ({
  id: kind, kind, text: "", impact: "", by: null, sensitive: false, findings: [], link: { page: "object", params: {} },
  subjects: [], people: [], objects: [], ...more,
});
const row = (object: string, more: Partial<UsageRow> = {}): UsageRow => ({
  object, type: "TABLE", database: "DB", schema: "S", sensitive: false, level: "change", used: "read", privileges: ["INSERT", "SELECT"],
  unused: [], weeks: [0, 2, 4], reads: 6, writes: 0, last: "2026-11-02", people: ["U"], holder: "T_R", suggest: "keep", text: "Keep", changes: [], ...more,
});

describe("granted vs used", () => {
  it("draws weekly bars, empty weeks low", () => {
    expect(bars([0, 2, 4], 32)).toEqual([3, 16, 32]);
    expect(bars([0, 0])).toEqual([3, 3]);
  });
  it("filters rows and says what the trim takes", () => {
    const rows = [row("DB.S.A", { suggest: "drop", sensitive: true, changes: [{ op: "revoke_priv", role: "T_R", privilege: "SELECT", object: "DB.S.A" }] }),
      row("DB.S.B", { suggest: "trim", changes: [{ op: "revoke_priv", role: "T_W", privilege: "INSERT", object: "DB.S.B" }] }), row("DB.S.C")];
    expect(usageRows(rows, "drop").map((r) => r.object)).toEqual(["DB.S.A"]);
    expect(usageRows(rows, "sensitive").map((r) => r.object)).toEqual(["DB.S.A"]);
    expect(usageRows(rows, "all")).toHaveLength(3);
    expect(trimText(rows)).toBe("SELECT on A · INSERT on B");
  });
});

describe("what changed", () => {
  it("filters the feed", () => {
    const list = [ev("gain", { sensitive: true }), ev("lose"), ev("user", { findings: [{ num: "7", severity: "High", title: "t", fixed: false }] }),
      ev("fixed", { findings: [{ num: "4", severity: "High", title: "t", fixed: true }] })];
    expect(list.filter((e) => keep(e, "gain")).map((e) => e.kind)).toEqual(["gain"]);
    expect(list.filter((e) => keep(e, "risk")).map((e) => e.kind)).toEqual(["user"]);
    expect(list.filter((e) => keep(e, "sensitive")).map((e) => e.kind)).toEqual(["gain"]);
    expect(list.filter((e) => keep(e, "all"))).toHaveLength(4);
  });
  it("answers watched questions from the existing endpoints", () => {
    const can: Watch = { id: "", kind: "can", user: "U", object: "DB.S.T", notify: "" };
    expect(question(can)).toBe("Can U read DB.S.T?");
    expect(answerOf(can, { verdict: "partly" } as CheckPage)).toBe("Partly");
    const who: Watch = { id: "", kind: "who", object: "DB.S.T", notify: "" };
    const people = [{ name: "A", level: "read" }, { name: "B", level: "names" }, { name: "C", level: "own" }];
    expect(answerOf(who, { people } as WhoPage)).toBe("2 people · A, C");
    expect(answerOf({ ...who, kind: "admins" }, { people } as WhoPage)).toBe("3 people · A, B, C");
    expect(watchId(can)).toBe("can|U|DB.S.T");
  });
  it("tags an answer New, then Changed or No change on the next snapshot", () => {
    const w: Watch = { id: "x", kind: "admins", notify: "#sec" };
    const a = recheck(w, "r1", "2 people");
    expect(a.tag).toBe("New");
    expect(recheck(a.next!, "r1", "2 people")).toEqual({ tag: "New", before: null, next: null });
    const b = recheck(a.next!, "r2", "3 people");
    expect([b.tag, b.before]).toEqual(["Changed", "2 people"]);
    expect(recheck(b.next!, "r2", "3 people")).toMatchObject({ tag: "Changed", next: null });
    expect(recheck(b.next!, "r3", "3 people").tag).toBe("No change");
  });
  it("sends old links to the new screens", () => {
    expect(redirect("history", {})).toEqual({ page: "changes", params: {} });
    expect(redirect("diff", { f: "gain" })).toEqual({ page: "changes", params: { f: "gain" } });
    expect(redirect("unused", { user: "U" })).toEqual({ page: "usage", params: { user: "U" } });
    expect(redirect("user", { name: "U", show: "usage" })).toEqual({ page: "usage", params: { user: "U" } });
    expect(redirect("role", { name: "F_A", show: "usage" })).toEqual({ page: "usage", params: { role: "F_A" } });
    expect(redirect("access", { role: "F_A", show: "usage", days: "30" })).toEqual({ page: "usage", params: { role: "F_A", days: "30" } });
    expect(redirect("usage", { name: "U" })).toEqual({ page: "usage", params: { user: "U" } });
    expect(redirect("access", { user: "U", show: "history" })).toEqual({ page: "access", params: { user: "U", show: "history" } });
  });
});
