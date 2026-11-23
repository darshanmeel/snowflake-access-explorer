// What if: the picked user stays when the role changes; Add only when that user holds the new role.
import { afterEach, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { clearCache, setTransport } from "../api/client";
import { AppCtx, type Ctx } from "../ctx";
import { Root } from "../components";
import { WhatIfPageView } from "./Whatif";

globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as never;
const ctx = { page: "whatif", params: {}, view: "shared", meta: { pages: [] }, theme: "light", nav: () => {}, set: () => {} } as unknown as Ctx;
const item = (id: string, type: string | null = null) => ({ id, name: id, kind: null, type, status: null });
const held: Record<string, string[]> = { F_A: ["ANN", "BOB"], F_B: ["BOB"], F_C: ["ANN"] };
afterEach(() => { cleanup(); clearCache(); });

it("keeps the user when the role changes", async () => {
  setTransport(async (_m, url) => {
    const p = new URLSearchParams(url.split("?")[1]);
    return { items: p.get("what") === "roles" ? Object.keys(held).map((r) => item(r)) : (held[p.get("role") ?? ""] ?? []).map((u) => item(u, "direct")) };
  });
  render(<AppCtx.Provider value={ctx}><Root theme="light"><WhatIfPageView /></Root></AppCtx.Provider>);
  const wait = () => act(async () => { await new Promise((r) => setTimeout(r, 300)); });
  const box = (n: RegExp) => screen.getByRole("combobox", { name: n }) as HTMLInputElement;
  const pick = async (n: RegExp, v: string) => {
    fireEvent.focus(box(n)); fireEvent.change(box(n), { target: { value: v } }); await wait();
    const o = screen.getByRole("option", { name: new RegExp(v) });
    fireEvent.mouseDown(o); fireEvent.click(o); await wait();
  };
  const add = () => screen.getByRole("button", { name: "Add" }) as HTMLButtonElement;
  await pick(/^Role/, "F_A"); await pick(/^From user/, "ANN");
  expect(add().disabled).toBe(false);
  await pick(/^Role/, "F_B");
  expect(box(/^From user/).value).toBe("ANN");
  expect(add().disabled).toBe(true);
  expect(screen.getByRole("status").textContent).toContain("ANN does not hold F_B");
  await pick(/^Role/, "F_C");
  expect(box(/^From user/).value).toBe("ANN");
  expect(add().disabled).toBe(false);
}, 20000);
