import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { CsvOn, DataTable } from ".";

const rows = Array.from({ length: 120 }, (_, i) => ({ n: `ROLE_${String(i).padStart(3, "0")}` }));
const cols = [{ key: "n", label: "Name", get: (r: { n: string }) => r.n }];

afterEach(cleanup);

describe("DataTable pages", () => {
  it("pages rows, resets on filter, hides CSV when off", () => {
    const { rerender } = render(<DataTable columns={cols} rows={rows} />);
    expect(screen.getByText("Rows 1–50 of 120")).toBeTruthy();
    fireEvent.click(screen.getByText("Next"));
    expect(screen.getByText("ROLE_050")).toBeTruthy();
    expect(screen.getByText("Rows 51–100 of 120")).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText("Filter rows"), { target: { value: "ROLE_01" } });
    expect(screen.queryByText("Next")).toBeNull(); // 10 rows: one page, no pager
    expect(screen.getByText("CSV")).toBeTruthy();
    rerender(<CsvOn.Provider value={false}><DataTable columns={cols} rows={rows} /></CsvOn.Provider>);
    expect(screen.queryByText("CSV")).toBeNull();
  });

  it("server pages: shows the page as sent, asks the server for the next page, sort and filter", () => {
    const asked: object[] = [];
    const server = { total: 5000, at: 2, size: 50, q: "", by: { key: "n", dir: 1 as const }, onChange: (s: object) => asked.push(s) };
    render(<DataTable columns={cols} rows={rows.slice(0, 50)} csv={null} paged={server} />);
    expect(screen.getByText("Rows 101–150 of 5000")).toBeTruthy();
    expect(screen.getByText("ROLE_000")).toBeTruthy(); // not cut again in the browser
    fireEvent.click(screen.getByText("Next"));
    fireEvent.click(screen.getByText("Name"));
    fireEvent.change(screen.getByPlaceholderText("Filter rows"), { target: { value: "ROLE_01" } });
    expect(asked).toEqual([{ at: 3 }, { at: 0, by: { key: "n", dir: -1 } }, { at: 0, q: "ROLE_01" }]);
  });
});
