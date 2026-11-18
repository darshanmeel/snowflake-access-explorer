import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { App } from "./App";
import { clearCache } from "./api/client";

const base = { mode: "snowflake", source: "direct", view: "shared", pages: [], notes: [], sources: {}, rules: [], help: {},
  tokens: {}, type_icon: {}, pclass: {}, mine: { loaded: false }, mine_available: false, limits: {}, prefixes: { func: "F_", tech: "T_" } };
const loaded = { ...base, loaded: true, run: { run_id: "direct", finished_at: "2026-11-17 10:00", when: "2026-11-17 10:00", old: false } };

/** fetch answered by answer(url, method); every other GET fails, so no page body draws. */
function serve(answer: (url: string, method: string) => unknown) {
  vi.stubGlobal("fetch", vi.fn(async (url: string, o?: RequestInit) => {
    const got = await answer(url, o?.method ?? "GET");
    return got === undefined ? new Response(JSON.stringify({ detail: "x", message: "x" }), { status: 404 })
      : new Response(JSON.stringify(got), { status: 200 });
  }));
}

afterEach(() => { cleanup(); clearCache(); vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("App shell during a load", () => {
  it("no data yet: no SQL buttons; the first load locks the rest of the page until it is done", async () => {
    let done: (v: unknown) => void = () => undefined;
    serve((url, method) => url.startsWith("/api/meta") ? { ...base, error: { detail: "shared_not_loaded", message: "" } }
      : method === "POST" ? new Promise((r) => { done = r; }) : url.startsWith("/api/progress") ? { running: true, view: "shared", lines: [] } : undefined);
    const { container } = render(<App />);
    const load = await screen.findByText("Load shared data");
    expect(screen.queryByText("</> SQL")).toBeNull();
    expect(container.querySelector(".ae-card-sql")).toBeNull();
    expect(container.querySelector(".top-lock[inert]")).toBeNull();
    await act(async () => { fireEvent.click(load); });
    expect(container.querySelectorAll(".top-lock[inert]").length).toBe(2);
    await act(async () => { done({ ok: true, message: "Loaded." }); });
    expect(container.querySelector(".top-lock[inert]")).toBeNull();
  });

  it("Read Snowflake again runs in the background: the page stays usable, the top bar shows the latest line, then the new data", async () => {
    let job: { id: number; state: string; ok: boolean | null; message: string | null } = { id: 1, state: "running", ok: null, message: null };
    let metas = 0;
    serve((url, method) => {
      if (url.startsWith("/api/meta")) { metas++; return loaded; }
      if (method === "POST") return { ok: true, started: true, job: 1, message: "Reading Snowflake in the background." };
      if (url.startsWith("/api/progress")) return { running: job.state === "running", view: "shared", lines: [{ t: 1, text: "GRANTS_TO_ROLES: 12 rows" }], job: { what: "page", ...job } };
      return undefined;
    });
    const { container } = render(<App />);
    fireEvent.click(await screen.findByLabelText("Read again"));
    expect(await screen.findByText("GRANTS_TO_ROLES: 12 rows", {}, { timeout: 3000 })).toBeTruthy();
    expect(container.querySelector(".top-lock[inert]")).toBeNull();
    expect(screen.getByText("</> SQL")).toBeTruthy();
    const before = metas;
    job = { id: 1, state: "done", ok: true, message: "Read Snowflake again." };
    expect(await screen.findByText("Read Snowflake again.", {}, { timeout: 3000 })).toBeTruthy();
    expect(container.querySelector(".top-bg")).toBeNull();
    expect(metas).toBeGreaterThan(before);  // the pages fetch the new data
  });
});

describe("No default person on shared data", () => {
  it("a person page asks for a pick and asks the server nothing until one is made", async () => {
    window.history.pushState({}, "", "/?page=access");
    const asked: string[] = [];
    serve((url) => { asked.push(url); return url.startsWith("/api/meta") ? { ...loaded, default_user: null } : undefined; });
    render(<App />);
    expect(await screen.findByText("The data is ready: pick a person or role")).toBeTruthy();
    expect(asked.some((u) => u.startsWith("/api/access"))).toBe(false);
    window.history.pushState({}, "", "/");
  });
});
