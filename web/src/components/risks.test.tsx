// The risk strip at the top of Access Overview, Role paths, Who has access and Can they?
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render } from "@testing-library/react";
import { RiskStrip, type RiskLine } from "./kit";

const line = (severity: RiskLine["severity"], text: string, n = 1): RiskLine =>
  ({ severity, text, n, link: { label: "Findings", page: "rules", params: { rule: "9" } } });

describe("risk strip", () => {
  afterEach(cleanup);
  it("keeps the server's order and says each tone in words", () => {
    const { getAllByRole } = render(<RiskStrip items={[line("bad", "Holds 1 admin role", 1), line("warn", "Dormant", 1200)]} onOpen={() => {}} />);
    const items = getAllByRole("listitem");
    expect(items.map((x) => x.className)).toEqual(["ae-risk ae-tone-bad", "ae-risk ae-tone-warn"]);
    expect(items[0].textContent).toContain("Risk");
    expect(items[1].textContent).toContain("Check");
    expect(items[1].textContent).toContain((1200).toLocaleString());
  });

  it("opens the line's link", () => {
    const open = vi.fn();
    const { getByRole } = render(<RiskStrip items={[line("bad", "Granted to PUBLIC")]} onOpen={open} />);
    fireEvent.click(getByRole("button", { name: "Findings →" }));
    expect(open).toHaveBeenCalledWith({ label: "Findings", page: "rules", params: { rule: "9" } });
  });

  it("says no risks in one quiet line", () => {
    const { container } = render(<RiskStrip items={[]} onOpen={() => {}} />);
    expect(container.textContent).toBe("No risks found");
    expect(container.querySelector(".ae-tone-bad, .ae-tone-warn")).toBeNull();
  });
});
