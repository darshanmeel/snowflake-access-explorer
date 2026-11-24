import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Combo } from "../components";
import { askedOf, startWith } from "./screens";

afterEach(cleanup);

describe("what was asked stays", () => {
  it("the object stays when the person changes, also on the next page", () => {
    let a = askedOf("check", { name: "ANNA", obj: "DB" }, {});
    a = askedOf("access", { user: "BEN" }, a);
    expect(startWith("check", a)).toEqual({ name: "BEN", obj: "DB" });
    expect(startWith("object", a)).toEqual({ name: "DB" });
    expect(startWith("request", askedOf("check", { role: "F_X" }, a))).toEqual({ for_role: "F_X", obj: "DB" });
    expect(startWith("see", askedOf("home", {}, a))).toEqual({ user: "BEN" });
    expect(startWith("rules", a)).toEqual({});
    expect(askedOf("request", { name: "ANNA", role: "R_ASKED_FOR" }, {}).role).toBeUndefined(); // role= is what is asked for there
  });

  const combo = (hits: string[], pick: (x: string) => void) => render(
    <Combo<string> label="Object" value="OLD" search={async () => hits} onPick={pick} keyOf={(x) => x} render={(x) => x} wait={5000} />);

  it("a full name typed and left is picked, before its list came too; part of a name is not", async () => {
    const pick = vi.fn();
    combo(["SALES", "SALES_2"], pick);
    const box = screen.getByRole("combobox");
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "sales" } });
    fireEvent.blur(box);
    await waitFor(() => expect(pick).toHaveBeenCalledWith("SALES"));
    fireEvent.change(box, { target: { value: "SAL" } });
    fireEvent.blur(box);
    await new Promise((r) => setTimeout(r, 20));
    expect(pick).toHaveBeenCalledTimes(1);
  });

  it("Escape drops the text; a name two hits share is not guessed", async () => {
    const pick = vi.fn();
    combo(["X", "X"], pick);
    const box = screen.getByRole("combobox");
    fireEvent.change(box, { target: { value: "X" } });
    fireEvent.keyDown(box, { key: "Escape" });
    fireEvent.blur(box);
    fireEvent.change(box, { target: { value: "X" } });
    fireEvent.blur(box);
    await new Promise((r) => setTimeout(r, 20));
    expect(pick).not.toHaveBeenCalled();
  });
});
