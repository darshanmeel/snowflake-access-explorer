import { describe, expect, it } from "vitest";
import type { CheckPage } from "../api/types";
import { mid } from "./Access";
import { answerLine } from "./Check";
import { compareLine } from "./Compare";

const check = (more: Partial<CheckPage>) => ({
  verdict: "yes", user: "ANN", object: "DB.S.T", roles_count: 2, lanes_total: 4, cut: ["F_A"], layers: null, nearest: null,
  subject: { user: true }, answer: { yes: true, title: "Yes, through 7 paths", text: "ANN can SELECT DB.S.T.", stats: [["Paths", 7], ["Shortest depth", 2]] },
  ...more,
}) as unknown as CheckPage;

describe("answer first", () => {
  it("Can they? says routes and the depth once, never paths", () => {
    expect(answerLine(check({}))).toBe("Through 4 routes, all via F_A · shortest 2 roles deep.");
    expect(answerLine(check({ lanes_total: 0, answer: { yes: true, title: "Yes, via ownership", text: "ANN reaches OWNERSHIP of DB.S.T.", stats: [] } as never })))
      .toBe("ANN reaches OWNERSHIP of DB.S.T.");
    expect(answerLine(check({ verdict: "no", lanes_total: 0 }))).toMatch(/^None of ANN's 2 roles leads to DB.S.T\./);
  });
  it("Compare says what B lacks of A first", () => {
    expect(compareLine({ only_a: 0, only_b: 3, different: 0, same: 2 }, "A1", "B1")).toBe("B1 has everything A1 reaches; A1 lacks 3 objects B1 reaches.");
    expect(compareLine({ only_a: 1, only_b: 0, different: 2, same: 0 }, "A1", "B1"))
      .toBe("B1 lacks 1 object A1 reaches; A1 has nothing B1 lacks; 2 objects both reach with different access.");
    expect(compareLine({ only_a: 0, only_b: 0, different: 0, same: 5 }, "A1", "B1")).toBe("A1 and B1 reach the same 5 objects with the same access.");
  });
  it("cuts a long role name in the middle", () => {
    expect(mid("T_SALES")).toBe("T_SALES");
    const s = mid("T_FINANCE_REPORTING_ARCHIVE_2024_EXTERNAL_READ");
    expect(s.length).toBe(30);
    expect(s.startsWith("T_FINANCE")).toBe(true);
    expect(s.endsWith("EXTERNAL_READ")).toBe(true);
  });
});
