import { describe, expect, it } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Combo } from ".";

describe("Combo", () => {
  it("shows only the answer for the text in the box: no match says so, never the last key's list", async () => {
    const search = (q: string) => Promise.resolve(q === "SALES" ? ["SALES.CORE"] : []);
    render(<Combo<string> label="Object" value="" search={search} keyOf={(x) => x} render={(x) => x} onPick={() => {}} wait={0} />);
    const box = screen.getByRole("combobox");
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "SALES" } });
    await waitFor(() => expect(screen.getByText("SALES.CORE")).toBeTruthy());
    fireEvent.change(box, { target: { value: "SALES.ZZ" } });
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("No match"));
    expect(screen.queryByText("SALES.CORE")).toBeNull();
  });
});
