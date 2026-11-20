import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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

  it("no bar without a focus or a pick, nor without onOnly", () => {
    render(<Root theme="light"><Graph graph={{ ...g, focus: { id: "F", label: "F" } }} /></Root>);
    expect(screen.queryByText(/Only the lines through/)).toBeNull();
  });
});
