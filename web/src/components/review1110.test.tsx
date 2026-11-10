// Web fixes from the 2026-11-10 review: sort speed, copy-paste SQL / Terraform, CSV, races, pickers, keyboard, frame.
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { FindItem, Meta } from "../api/types";
import { clearCache, setTransport } from "../api/client";
import { AppCtx, type Ctx } from "../ctx";
import { viewPage } from "../App";
import { HomePageView } from "../pages/Home";
import { Pick } from "../pages/common";
import { onRender } from "../st/protocol";
import { newRoleOf, sqlOf, terraformOf } from "./codegen";
import { Combo } from "./Combo";
import { DataTable } from "./DataTable";
import { sortRows, toCsv } from "./table";

afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); clearCache(); });

const ctx = (nav = vi.fn(), set = vi.fn()): Ctx =>
  ({ page: "home", params: {}, view: "shared", meta: { pages: [], default_user: "" } as unknown as Meta, theme: "light", nav, set }) as Ctx;

describe("table helpers", () => {
  it("sorts with one collator, numbers in names in order", () => {
    const spy = vi.spyOn(String.prototype, "localeCompare");
    const rows = ["T10", "t2", "T1"].map((a) => ({ a }));
    expect(sortRows(rows, (r) => r.a, 1).map((r) => r.a)).toEqual(["T1", "t2", "T10"]);
    expect(spy).not.toHaveBeenCalled(); // localeCompare with options builds a collator per call: minutes on 100k rows
  });

  it("neutralises cells Excel would run as a formula", () => {
    const csv = toCsv(["a"], [["=HYPERLINK(\"x\")"], ["+1+2"], ["-A1"], ["@SUM(A1)"], ["\tx"], ["\rx"], ["-3"], ["SALES.CORE.T"]]);
    expect(csv.split("\r\n").slice(1, 5)).toEqual(['"\'=HYPERLINK(""x"")"', "'+1+2", "'-A1", "'@SUM(A1)"]);
    expect(csv).toContain("'\tx");
    expect(csv).toContain('"\'\rx"');
    expect(csv).toContain("\r\n-3\r\n"); // a plain number stays a number
    expect(csv.endsWith("\r\nSALES.CORE.T")).toBe(true);
  });
});

describe("copy-paste code", () => {
  it("quotes a user name whole in the new-role skeleton (SQL itself: access.with_sql, test_with_sql)", () => {
    expect(newRoleOf("JOHN.DOE", ["SELECT"], "TABLE", "DB.SCHEMA.T").sql).toContain('TO USER "JOHN.DOE";');
  });

  it("escapes names inside Terraform strings", () => {
    const t = terraformOf([{ op: "grant", privilege: "SELECT", objectType: "TABLE", object: 'SALES.CORE."we\\ird"${x}', to: "F_X" }]);
    expect(t).toContain('object_name = "SALES.CORE.\\"we\\\\ird\\"$${x}"');
  });

  it("comments out every line of a multi-line reason", () => {
    const n = { reason: "Quarter close\nGRANT ROLE ACCOUNTADMIN TO USER BOB;\r\nthird" };
    const all = [sqlOf([{ op: "grant", role: "F_X", to: "A", toUser: true }], n), newRoleOf("A", ["SELECT"], "TABLE", "DB.S.T", n).sql];
    for (const s of all) expect(s.split("\n").filter((l) => l.includes("ACCOUNTADMIN") || l.includes("third")).every((l) => l.startsWith("-- "))).toBe(true);
    const tf = [terraformOf([], n), newRoleOf("A", ["SELECT"], "TABLE", "DB.S.T", n).tf];
    for (const s of tf) expect(s.split("\n").filter(Boolean).every((l) => l.startsWith("#"))).toBe(true);
  });
});

describe("races, pickers and keys", () => {
  it("Home's Enter opens the hit for the text now in the box, not a late answer for older text", async () => {
    vi.useFakeTimers();
    const slow: { done?: (v: unknown) => void } = {};
    const hit = (id: string) => ({ id, name: id, kind: "user", kind_label: "user", type: null, sensitive: false, page: "user", answer: "" }) as FindItem;
    setTransport((_m, url) => {
      if (url.startsWith("/api/find") && url.includes("q=eng&")) return new Promise((r) => { slow.done = r; });
      if (url.startsWith("/api/find")) return Promise.resolve({ items: [hit("ENGINEER_07")] });
      return new Promise(() => {});
    });
    const nav = vi.fn();
    render(<AppCtx.Provider value={ctx(nav)}><HomePageView /></AppCtx.Provider>);
    const box = screen.getByLabelText("Search");
    fireEvent.change(box, { target: { value: "eng" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });
    fireEvent.change(box, { target: { value: "engineer_07" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });
    await act(async () => { slow.done!({ items: [hit("ENGINEER_01")] }); });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(nav).toHaveBeenCalledWith("access", { user: "ENGINEER_07" });
    setTransport(null as never);
  });

  it("a picker picks a role that has the shown user's name", async () => {
    vi.useFakeTimers();
    setTransport(() => Promise.resolve({ items: [{ id: "SVC_ETL", name: "SVC_ETL", kind: "user" }, { id: "SVC_ETL", name: "SVC_ETL", kind: "functional" }] }));
    const pick = vi.fn();
    render(<AppCtx.Provider value={ctx()}><Pick label="Who" value="SVC_ETL" user what="users,roles" onPick={pick} /></AppCtx.Provider>);
    const box = screen.getByRole("combobox");
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "SVC" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });
    const [asUser, asRole] = screen.getAllByRole("option");
    fireEvent.click(asUser);
    expect(pick).not.toHaveBeenCalled(); // the same user again: nothing to do
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "SVC_" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });
    fireEvent.click(screen.getAllByRole("option")[1] ?? asRole);
    expect(pick).toHaveBeenCalledWith("SVC_ETL", expect.objectContaining({ kind: "functional" }));
    setTransport(null as never);
  });

  it("Escape empties a clearing box", async () => {
    vi.useFakeTimers();
    render(<Combo<string> value="" clear search={async () => ["SALES"]} onPick={vi.fn()} keyOf={(x) => x} render={(x) => x} label="Find" wait={10} />);
    const box = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "sales" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(20); });
    fireEvent.keyDown(box, { key: "Escape" });
    expect(box.value).toBe("");
  });

  it("table headers sort from the keyboard (a button), unlabeled columns have none", () => {
    render(<DataTable rows={[{ a: "y" }, { a: "x" }]} csv={null} columns={[{ key: "a", label: "Name", get: (r: { a: string }) => r.a }, { key: "act", label: "", get: () => "" }]} />);
    const th = screen.getAllByRole("columnheader");
    expect(th[1].querySelector("button")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Name/ }));
    expect(th[0].getAttribute("aria-sort")).toBe("ascending");
  });

  it("switching to My access keeps Home, leaves shared-only pages", () => {
    expect(viewPage("home", true)).toBe("home");
    expect(viewPage("review", true)).toBe("access");
    expect(viewPage("review", false)).toBe("review");
  });

  it("the Streamlit frame listens only to its parent", () => {
    const cb = vi.fn();
    onRender(cb);
    const data = { type: "streamlit:render", args: { component: "app" } };
    window.dispatchEvent(new MessageEvent("message", { data, source: null }));
    expect(cb).not.toHaveBeenCalled();
    window.dispatchEvent(new MessageEvent("message", { data, source: window.parent }));
    expect(cb).toHaveBeenCalledTimes(1);
  });
});
