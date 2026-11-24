// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AppCtx, type Ctx } from "../ctx";
import { BuiltinNote, ErrorBox } from "./common";

afterEach(cleanup);
const show = (node: React.ReactNode, params = {}) => {
  const set = vi.fn();
  const r = render(<AppCtx.Provider value={{ params, set } as unknown as Ctx}>{node}</AppCtx.Provider>);
  return { set, r };
};

it("says how many built-in grants are left out and switches them on and off", () => {
  let { set, r } = show(<BuiltinNote b={{ grants: 2, roles: ["SNOWFLAKE.ML_USER"] }} />);
  expect(r.container.textContent).toContain("2 built-in grants here are left out of this answer");
  fireEvent.click(screen.getByRole("checkbox"));
  expect(set).toHaveBeenCalledWith({ builtin: "1" });
  cleanup();
  ({ set, r } = show(<BuiltinNote b={null} />, { builtin: "1" }));
  expect(r.container.textContent).toContain("are included");
  fireEvent.click(screen.getByRole("checkbox"));
  expect(set).toHaveBeenCalledWith({ builtin: null });
  cleanup();
  expect(show(<BuiltinNote b={null} />).r.container.textContent).toBe("");
});

it("an object only built-in grants reach offers to show them", () => {
  const { set } = show(<ErrorBox e={Object.assign(new Error("hidden"), { status: 404, detail: "builtin_hidden" })} />);
  fireEvent.click(screen.getByText("Show them"));
  expect(set).toHaveBeenCalledWith({ builtin: "1" });
});
