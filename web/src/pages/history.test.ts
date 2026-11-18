import { describe, expect, it } from "vitest";
import { redirect } from "../App";
import type { ChangeEvent, CheckPage, WhoPage } from "../api/types";
import { answerOf, bars, keep, question, recheck, watchId, type Watch } from "./history";

const ev = (kind: ChangeEvent["kind"], more: Partial<ChangeEvent> = {}): ChangeEvent => ({
  id: kind, kind, text: "", impact: "", by: null, sensitive: false, findings: [], link: { page: "object", params: {} },
  subjects: [], people: [], objects: [], ...more,
});

describe("granted vs used", () => {
  it("draws weekly bars, empty weeks low", () => {
    expect(bars([0, 2, 4], 32)).toEqual([3, 16, 32]);
    expect(bars([0, 0])).toEqual([3, 3]);
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
