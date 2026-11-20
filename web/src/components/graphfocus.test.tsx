import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Graph, Root } from ".";
import { pathGraph } from "./graphs";

globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as never;
globalThis.matchMedia ??= (() => ({ matches: false })) as never;

const g = pathGraph([{ path: ["U", "F", "T", "S.C.T1"], cls: "read" }], { kinds: { U: "user" } });

afterEach(cleanup);

describe("graph focus", () => {
  it("a focused graph says so and Whole graph or Escape returns", () => {
    const only = vi.fn();
    render(<Root theme="light"><Graph graph={{ ...g, focus: { id: "F", label: "F" } }} onOnly={only} /></Root>);
    expect(screen.getByText(/Only the lines through/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Whole graph" }));
    expect(only).toHaveBeenLastCalledWith(null);
    only.mockClear();
    fireEvent.keyDown(document.querySelector(".ae-graph")!, { key: "Escape" });
    expect(only).toHaveBeenCalledWith(null);
  });

  it("a click picks a box, Show only this asks for it and the focused graph puts the keyboard on Whole graph", async () => {
    const only = vi.fn(), picked = vi.fn();
    const { container, rerender } = render(<Root theme="light"><Graph graph={g} onOnly={only} onPick={picked} /></Root>);
    const box = await waitFor(() => {
      const n = container.querySelector('.react-flow__node[data-id="F"]');
      expect(n).toBeTruthy();
      return n as HTMLElement;
    }, { timeout: 5000 });
    await act(async () => { fireEvent.click(box); });
    expect(picked).toHaveBeenCalledWith(expect.objectContaining({ id: "F" }));
    fireEvent.click(screen.getByRole("button", { name: "Show only this" }));
    expect(only).toHaveBeenCalledWith("F");
    rerender(<Root theme="light"><Graph graph={{ ...g, focus: { id: "F", label: "F" } }} onOnly={only} onPick={picked} /></Root>);
    await waitFor(() => expect(document.activeElement?.textContent).toBe("Whole graph"));
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(only).toHaveBeenLastCalledWith(null);
  });

  it("Enter on a box picks it and moves the keyboard to Show only this", async () => {
    const { container } = render(<Root theme="light"><Graph graph={g} onOnly={vi.fn()} /></Root>);
    const box = await waitFor(() => {
      const n = container.querySelector('.react-flow__node[data-id="T"]');
      expect(n).toBeTruthy();
      return n as HTMLElement;
    }, { timeout: 5000 });
    await act(async () => { fireEvent.keyDown(box, { key: "Enter" }); });
    await waitFor(() => expect(document.activeElement?.textContent).toBe("Show only this"));
  });

  it("no bar without a focus or a pick, nor without onOnly", () => {
    render(<Root theme="light"><Graph graph={{ ...g, focus: { id: "F", label: "F" } }} /></Root>);
    expect(screen.queryByText(/Only the lines through/)).toBeNull();
  });
});
