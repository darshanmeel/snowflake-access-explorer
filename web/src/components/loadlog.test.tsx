import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import type { Progress } from "../api/types";
import { LoadLog, Waiting } from ".";

afterEach(() => { vi.useRealTimers(); });

describe("LoadLog", () => {
  it("shows the server's lines while active, polls about once a second, stops when done", async () => {
    vi.useFakeTimers();
    let n = 0;
    const lines = [{ t: 0.4, text: "Reading GRANTS_TO_ROLES…" }, { t: 12, text: "SHOW GRANTS TO ROLE: 340 of 2,000" }];
    const poll = vi.fn(async (): Promise<Progress> => ({ running: true, view: "shared", lines: lines.slice(0, ++n) }));
    const { rerender, container } = render(<LoadLog active poll={poll} />);
    expect(container.innerHTML).toBe("");  // nothing before the first answer: a quick page never flashes the panel
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(screen.getByText("Reading GRANTS_TO_ROLES…")).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(screen.getByText("SHOW GRANTS TO ROLE: 340 of 2,000")).toBeTruthy();
    expect(screen.getByText("12.0 s")).toBeTruthy();
    const log = screen.getByRole("log");
    expect(log.getAttribute("aria-live")).toBe("polite");
    expect(log.children.length).toBe(2);
    rerender(<LoadLog active={false} poll={poll} />);
    expect(screen.queryByRole("log")).toBeNull();
    const calls = poll.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(poll.mock.calls.length).toBe(calls);
  });

  it("does not poll again inside Streamlit (no answer: null)", async () => {
    vi.useFakeTimers();
    const poll = vi.fn(async () => null);
    render(<LoadLog active poll={poll} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(poll).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("log")).toBeNull();
  });
});

describe("Waiting", () => {
  it("counts the seconds and, after 10, says the page is still working", async () => {
    vi.useFakeTimers();
    render(<Waiting />);
    expect(screen.getByRole("status").textContent).toBe("Loading…");
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    expect(screen.getByRole("status").textContent).toBe("Loading… 4 s");
    await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
    expect(screen.getByRole("status").textContent).toContain("12 s · still working");
  });
});
