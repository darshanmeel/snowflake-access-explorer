import { expect, it } from "vitest";
import { render } from "@testing-library/react";
import type { CheckPage } from "../api/types";
import { Blocked } from "./Check";

it("Why it is blocked: one line per fact and per grant", () => {
  const d = { object: "D.S.T", paths: [{ privilege: "SELECT" }, { privilege: "SELECT" }],
    usage: [{ type: "DATABASE", name: "D", held: true }, { type: "SCHEMA", name: "D.S", held: false }] } as unknown as CheckPage;
  const iac = "Add in the infrastructure-as-code repo: USAGE on database D granted to role F_A; Add in the infrastructure-as-code repo: USAGE on schema D.S granted to role F_A";
  const { container } = render(<Blocked d={d} fix={{ iac, sql: "GRANT USAGE ON DATABASE D TO ROLE F_A; GRANT USAGE ON SCHEMA D.S TO ROLE F_A;" }} />);
  expect([...container.querySelectorAll("li")].map((x) => x.textContent)).toEqual([
    "✓ Has SELECT on D.S.T", "✓ Has USAGE on database D", "✕ Missing USAGE on schema D.S",
    "+ Add USAGE on database D granted to role F_A", "+ Add USAGE on schema D.S granted to role F_A"]);
  expect(container.querySelector("pre")!.textContent!.split("\n")).toHaveLength(2);
});
