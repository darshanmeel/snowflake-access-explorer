// NameList: names one per line with "+N more", replacing comma-joined text.
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { NameList } from "./kit";

const names = Array.from({ length: 12 }, (_, i) => `USER_${i}`);

describe("NameList", () => {
  it("links the first 8, opens a name, and shows the rest on +N more", () => {
    const open = vi.fn();
    render(<NameList items={names} onOpen={open} />);
    expect(screen.getAllByRole("button", { name: /^USER_/ })).toHaveLength(8);
    fireEvent.click(screen.getByRole("button", { name: "USER_0" }));
    expect(open).toHaveBeenCalledWith("USER_0");
    fireEvent.click(screen.getByRole("button", { name: "+4 more" }));
    expect(screen.getAllByRole("button", { name: /^USER_/ })).toHaveLength(12);
  });

  it("sends +N more to the full view when the server sent only the first names", () => {
    const more = vi.fn();
    render(<NameList items={names.slice(0, 3)} total={2068} max={3} onMore={more} />);
    fireEvent.click(screen.getByRole("button", { name: /\+2,065 more/ }));
    expect(more).toHaveBeenCalled();
  });

  it("has no buttons when plain, so it fits inside a button", () => {
    const { container } = render(<NameList items={names} max={4} plain />);
    expect(container.querySelectorAll("button")).toHaveLength(0);
    expect(container.textContent).toContain("+8 more");
    expect(container.textContent).not.toContain(",");
  });
});
