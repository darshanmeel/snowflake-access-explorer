import { describe, expect, it } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { PrivRow, ReachRow, Account } from "../api/types";
import { PrivilegeTabs, Root } from ".";
import { layout } from "./layout";
import { pathGraph } from "./graphs";

globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as never;
globalThis.matchMedia ??= (() => ({ matches: false })) as never;

const U = "ANALYST_01";
const row = (privilege: string, cls: PrivRow["cls"], tab: PrivRow["tab"], type: string, object: string, path: string[]): PrivRow => {
  const [database, schema, name] = object.split(".");
  return { privilege, cls, tab, type, object, database, schema: schema ?? "", name: name ?? object, future_label: null,
    granted: path[1], holder: path[path.length - 1], depth: path.length - 1, path: [...path, object], count: 1,
    paths_note: "", sensitive: false, hidden: false };
};
const rows: PrivRow[] = [
  row("SELECT", "read", "read", "TABLE", "SALES.CORE.TBL_CUSTOMER", [U, "F_ANALYST", "T_SALES_CORE_READ"]),
  row("USAGE", "use", "warehouses", "WAREHOUSE", "WH_ANALYTICS", [U, "F_ANALYST"]),
];
const roles: ReachRow[] = [
  { role: "HR.PEOPLE_READER", kind: "database_role", tab: "database_roles", depth: 2, direct: false, path: [U, "F_ANALYST", "HR.PEOPLE_READER"], count: 1, admin: false },
];
const account: Account = { admin: [], privileges: [], public: ["VIEW LINEAGE"] };

describe("render", () => {
  it("lays out lanes left to right without overlaps", async () => {
    const g = pathGraph([
      { path: ["U", "F", "T", "S.C.T1"], cls: "read" }, { path: ["U", "F", "T2", "S.C.T2"], cls: "write" },
      { path: ["U", "G", "T", "S.C.T3"], cls: "read" },
    ], { kinds: { U: "user" } });
    const l = await layout(g);
    const x = (id: string) => l.nodes.get(id)!.x;
    expect(x("U") < x("F") && x("F") < x("T") && x("T") < x("S.C.T1")).toBe(true);
    const lane1 = ["F", "G"].map((id) => l.nodes.get(id)!).sort((a, b) => a.y - b.y);
    expect(lane1[0].y + lane1[0].h).toBeLessThanOrEqual(lane1[1].y);
  });

  it("renders the privilege tabs and switches tab", async () => {
    render(<Root theme="light"><PrivilegeTabs rows={rows} roles={roles} account={account} /></Root>);
    expect(screen.getByRole("tab", { name: /Database roles/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: /Read/ }));
    await waitFor(() => expect(screen.getAllByText("SALES.CORE.TBL_CUSTOMER").length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("tab", { name: /Account/ }));
    expect(screen.getByText(/Via PUBLIC: every user has these/)).toBeTruthy();
  });
});
