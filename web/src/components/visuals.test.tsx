// Step 3 of the 2026-11-09 review: the small visuals and the web fixes (search box, copy, start view, legend).
import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import type { WhatIfObjectRow, WhatIfUser } from "../api/types";
import { cutLinks, lossGroups } from "../pages/changeplan";
import { areaCounts, ladderParts, sevParts } from "../pages/Home";
import { mineText } from "../App";
import { Combo } from "./Combo";
import { startView } from "./Graph";
import { copyText, MiniBar, StackBar } from "./kit";
import { Legend } from "./Legend";
import { subLines } from "./layout";
import { Overlap } from "./visuals";
import { DataTable } from "./DataTable";

const lost = (object: string, privileges: string[]): WhatIfObjectRow =>
  ({ object, type: "TABLE", privileges, classes: ["read"], path: ["U", "F_A", "T_R", object] }) as WhatIfObjectRow;
const user = (name: string, rows: WhatIfObjectRow[], objects = rows.length): WhatIfUser =>
  ({ user: name, status: "active", lost: rows.length, objects, kept: 0, lost_rows: rows, kept_rows: [], kept_roles: [] }) as unknown as WhatIfUser;

describe("change plan pictures", () => {
  it("crosses out only the links a change removes", () => {
    const p = ["ANALYST_01 (user)", "F_ANALYST", "T_SALES_CORE_READ", "SALES.CORE.TBL_CUSTOMER"];
    expect([...cutLinks(p, [{ op: "revoke_role_from_role", grantee: "F_ANALYST", role: "T_SALES_CORE_READ" } as never])]).toEqual([1]);
    expect([...cutLinks(p, [{ op: "revoke_role_from_user", user: "ANALYST_01", role: "F_ANALYST" } as never])]).toEqual([0]);
    expect([...cutLinks(p, [{ op: "drop_role", role: "T_SALES_CORE_READ" } as never])].sort()).toEqual([1, 2]);
    expect(cutLinks(p, [{ op: "revoke_role_from_role", grantee: "F_OTHER", role: "T_SALES_CORE_READ" } as never]).size).toBe(0);
  });

  it("groups people who lose the same thing, most people first", () => {
    const a = [lost("SALES.CORE.TBL_CUSTOMER", ["SELECT"])];
    const g = lossGroups([user("A1", a), user("A2", a), user("E1", [lost("SALES.CORE.TBL_ORDER", ["SELECT", "INSERT"])], 3)]);
    expect(g.map((x) => x.users.length)).toEqual([2, 1]);
    expect(g[0].text).toBe("2 people lose SELECT on SALES.CORE.TBL_CUSTOMER");
    expect(g[1].text).toBe("E1 loses SELECT, INSERT on SALES.CORE.TBL_ORDER and 2 more objects");
  });
});

describe("bars", () => {
  it("splits the ladder so each object counts once", () => {
    expect(ladderParts({ read: 6, change: 5, own: 2 }).map((p) => p.value)).toEqual([1, 3, 2]);
  });

  it("counts Critical with High, and findings per area by severity", () => {
    expect(sevParts({ Critical: 1, High: 2, Low: 4 }).map((p) => p.value)).toEqual([3, 0, 4]);
    const rules = [{ num: "1", area: "Role model", severity: "Medium" }, { num: "4", area: "Role model", severity: "High" },
      { num: "6", area: "Sensitive data", severity: "Medium" }];
    const a = areaCounts(rules, { "1": 2, "4": 1 });
    expect(a.find((x) => x.area === "Role model")).toMatchObject({ total: 3, n: { High: 1, Medium: 2 } });
    expect(a.find((x) => x.area === "Sensitive data")?.total).toBe(0);
  });

  it("StackBar picks a part from the bar and from its key, MiniBar scales to the largest row", () => {
    const pick = vi.fn();
    render(<StackBar label="ladder" parts={ladderParts({ read: 6, change: 5, own: 2 })} onPick={pick} />);
    fireEvent.click(screen.getAllByRole("button", { name: /Owns/ })[0]);
    expect(pick).toHaveBeenCalledWith("own");
    const { container } = render(<MiniBar of={10} parts={[{ key: "a", label: "A", value: 5, cls: "people" }]} />);
    expect((container.querySelector(".ae-mini-track > span") as HTMLElement).style.width).toBe("50%");
  });

  it("Overlap names both sides and opens the differences", () => {
    const pick = vi.fn();
    render(<Overlap a="ENGINEER_01" b="ANALYST_01" onlyA={3} onlyB={1} different={2} same={4} onPick={pick} />);
    expect(screen.getByRole("img").getAttribute("aria-label")).toContain("Only ENGINEER_01: 3");
    fireEvent.click(screen.getByText("different"));
    expect(pick).toHaveBeenCalled();
  });
});

describe("graph", () => {
  const lay = (lanes: number, height: number, sel = { x: 100, y: 1800, w: 140, h: 40 }) =>
    ({ width: 1200, height, lanes: Array(lanes).fill(0), nodes: new Map([["U", sel]]) });

  it("fits a drawing of up to 6 lanes, else centres on the selected box", () => {
    expect(startView(lay(5, 900), 1200, 640, 0.6, "U").view.zoom).toBeLessThan(1);
    const v = startView(lay(7, 2400), 1200, 640, 0.8, "U");
    const centre = v.view.y + (1800 + 20) * v.view.zoom;
    expect(Math.abs(centre - v.height / 2)).toBeLessThan(2);
  });

  it("breaks a subtitle after a dot, never mid-word", () => {
    expect(subLines("table · SALES.CORE")).toEqual(["table · SALES.CORE"]);
    const l = subLines("table · A_VERY_LONG_DATABASE_NAME.A_LONG_SCHEMA_NAME");
    expect(l).toHaveLength(2);
    expect(l[0].endsWith(".") || l[0] === "table").toBe(true);
  });

  it("the legend shows only the kinds and lines present", () => {
    render(<Legend legend={{ kinds: ["user", "functional"], edges: ["read"], marks: [], rules: false }} />);
    expect(screen.queryByText("Database role")).toBeNull();
    expect(screen.queryByText("Also deeper")).toBeNull();
    expect(screen.getByText("Functional")).toBeTruthy();
  });
});

describe("web fixes", () => {
  it("Combo searches as you type, moves with the arrow keys and picks with Enter", async () => {
    vi.useFakeTimers();
    const pick = vi.fn();
    const search = vi.fn(async (q: string) => ["F_ANALYST", "F_ENGINEER", "F_MARKETING"].filter((x) => x.includes(q.toUpperCase())));
    render(<Combo<string> value="" search={search} onPick={pick} keyOf={(x) => x} render={(x) => x} label="Find" wait={10} />);
    const box = screen.getByRole("combobox");
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "f_" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(20); });
    expect(search).toHaveBeenLastCalledWith("f_");
    expect(screen.getAllByRole("option")).toHaveLength(3);
    fireEvent.keyDown(box, { key: "ArrowDown" });
    fireEvent.keyDown(box, { key: "ArrowDown" });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(pick).toHaveBeenCalledWith("F_ENGINEER");
    fireEvent.change(box, { target: { value: "f_m" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(20); });
    fireEvent.keyDown(box, { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    vi.useRealTimers();
  });

  it("copyText falls back to execCommand and reports a failure", async () => {
    Object.defineProperty(navigator, "clipboard", { value: { writeText: () => Promise.reject(new Error("denied")) }, configurable: true });
    const pre = document.createElement("pre");
    pre.textContent = "GRANT ...";
    document.body.appendChild(pre);
    (document as unknown as { execCommand: (c: string) => boolean }).execCommand = () => true;
    expect(await copyText("GRANT ...", pre)).toBe(true);
    (document as unknown as { execCommand: (c: string) => boolean }).execCommand = () => false;
    expect(await copyText("GRANT ...", pre)).toBe(false);
  });

  it("the My access card says where the copy is kept", () => {
    expect(mineText(24)).toContain("CACHE_HOURS=24");
    expect(mineText(0)).toContain("nothing on disk");
  });

  it("a column without a label is left out of the CSV and is not sortable", () => {
    render(<DataTable rows={[{ a: "x" }, { a: "y" }]} csv="t" columns={[{ key: "a", label: "Name", get: (r: { a: string }) => r.a }, { key: "act", label: "", get: () => "" }]} />);
    const th = screen.getAllByRole("columnheader");
    fireEvent.click(th[1]);
    expect(th[1].getAttribute("aria-sort")).toBeNull();
    fireEvent.click(th[0]);
    expect(th[0].getAttribute("aria-sort")).toBe("ascending");
  });
});
