import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { CsvOn, DataTable } from ".";

const rows = Array.from({ length: 120 }, (_, i) => ({ n: `ROLE_${String(i).padStart(3, "0")}` }));
const cols = [{ key: "n", label: "Name", get: (r: { n: string }) => r.n }];

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
});
