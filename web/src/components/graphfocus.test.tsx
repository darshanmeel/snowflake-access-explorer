import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Graph, Root } from ".";
import { pathGraph } from "./graphs";

globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as never;
globalThis.matchMedia ??= (() => ({ matches: false })) as never;

const g = pathGraph([{ path: ["U", "F", "T", "S.C.T1"], cls: "read" }], { kinds: { U: "user" } });

afterEach(cleanup);

describe("graph focus", () => {
  it("a focused graph says so, with who has access; Show all or Escape returns", () => {
    const only = vi.fn();
    const access = { type: "TABLE", people: 3, roles: 2, levels: [{ level: "read", word: "read", n: 3 }] };
    render(<Root theme="light"><Graph graph={{ ...g, focus: { id: "S.C.T1", label: "S.C.T1", access } }} onOnly={only} /></Root>);
    expect(screen.getByText(/Only the lines through/)).toBeTruthy();
    expect(screen.getByText(/3 people have access: 3 read/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Show all" }));
    expect(only).toHaveBeenLastCalledWith(null);
    only.mockClear();
    fireEvent.keyDown(document.querySelector(".ae-graph")!, { key: "Escape" });
    expect(only).toHaveBeenCalledWith(null);
  });

  it("a click shows only that box at once (no question), and the focused graph puts the keyboard on Show all", async () => {
    const only = vi.fn(), picked = vi.fn();
    const { container, rerender } = render(<Root theme="light"><Graph graph={g} onOnly={only} onPick={picked} /></Root>);
    const box = await waitFor(() => {
      const n = container.querySelector('.react-flow__node[data-id="F"]');
      expect(n).toBeTruthy();
      return n as HTMLElement;
    }, { timeout: 5000 });
    await act(async () => { fireEvent.click(box); });
    expect(picked).toHaveBeenCalledWith(expect.objectContaining({ id: "F" }));
    expect(only).toHaveBeenCalledWith("F");
    expect(screen.queryByRole("button", { name: "Show only this" })).toBeNull();
    rerender(<Root theme="light"><Graph graph={{ ...g, focus: { id: "F", label: "F" } }} onOnly={only} onPick={picked} /></Root>);
    fireEvent.keyDown(document.querySelector(".ae-graph")!, { key: "Escape" });
    expect(only).toHaveBeenLastCalledWith(null);
  });

  it("no bar without a focus, nor without onOnly", () => {
    render(<Root theme="light"><Graph graph={{ ...g, focus: { id: "F", label: "F" } }} /></Root>);
    expect(screen.queryByText(/Only the lines through/)).toBeNull();
  });
});
