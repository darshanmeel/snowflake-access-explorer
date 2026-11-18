import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { clearCache, useApi } from "./client";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); clearCache(); });

function Show() {
  const s = useApi<{ n: number }>("thing");
  return <p>{s.error ? `error ${s.error.message}` : s.data ? `got ${s.data.n}` : "waiting"}</p>;
}

const answer = (status: number, body: unknown) => Promise.resolve({ ok: status < 300, status, json: async () => body });  // no stream: fake timers

describe("useApi", () => {
  it("asks again after a dropped connection or a read still running, and shows a real error at once", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn()
      .mockImplementationOnce(() => Promise.reject(new TypeError("Failed to fetch")))  // the server restarted
      .mockImplementationOnce(() => answer(409, { detail: "shared_loading", message: "being read" }))
      .mockImplementationOnce(() => answer(200, { n: 7 }));
    vi.stubGlobal("fetch", fetch);
    render(<Show />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByText("waiting")).toBeTruthy();  // no error shown while it passes
    for (let i = 0; i < 6; i++) await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(screen.getByText("got 7")).toBeTruthy();
    expect(fetch).toHaveBeenCalledTimes(3);
    clearCache();
    fetch.mockImplementationOnce(() => answer(503, { detail: "shared_unreadable", message: "no warehouse" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByText("error no warehouse")).toBeTruthy();
  });
});
