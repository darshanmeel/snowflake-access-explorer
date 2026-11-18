// Big users: tables paged on the server, combined graph boxes whose members come on open.
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { clearCache, setTransport } from "../api/client";
import type { Graph as G, GraphEdge, GraphNode } from "../api/types";
import { DataTable } from "./DataTable";
import { Graph } from "./Graph";
import { expand } from "./graphs";

globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as never;
afterEach(() => { cleanup(); clearCache(); vi.useRealTimers(); });

const all = Array.from({ length: 600 }, (_, i) => ({ n: `OBJ_${String(i).padStart(3, "0")}` }));
const cols = [{ key: "n", label: "Name", get: (r: { n: string }) => r.n }];

describe("DataTable on the server", () => {
  it("asks for one page with the filter and sort, and exports the CSV from the server", async () => {
    const urls: string[] = [];
    setTransport(async (_m, url) => {
      urls.push(url);
      const u = new URL(url, "http://x");
      if (u.pathname.endsWith(".csv")) return "Name\r\nOBJ_000";
      const q = u.searchParams.get("q") ?? "", off = Number(u.searchParams.get("offset")), lim = Number(u.searchParams.get("limit"));
      const rows = all.filter((r) => r.n.includes(q.toUpperCase()));
      return { rows: rows.slice(off, off + lim), total: rows.length, offset: off, limit: lim };
    });
    URL.createObjectURL = () => "blob:x";
    URL.revokeObjectURL = () => {};
    render(<DataTable columns={cols} rows={[]} server={{ path: "privs", params: { name: "BIG", tab: "read" } }} />);
    expect(await screen.findByText("Rows 1–50 of 600")).toBeTruthy();
    expect(urls[0]).toBe("/api/privs?name=BIG&tab=read&offset=0&limit=50");
    fireEvent.click(screen.getByText("Next"));
    expect(await screen.findByText("OBJ_050")).toBeTruthy();
    fireEvent.click(screen.getByText("Name")); // sort by the column: the server sorts
    await waitFor(() => expect(urls.at(-1)).toContain("sort=n&dir=1"));
    fireEvent.change(screen.getByPlaceholderText("Filter rows"), { target: { value: "obj_01" } });
    await waitFor(() => expect(urls.at(-1)).toContain("q=obj_01"));
    expect(await screen.findByText("10 rows")).toBeTruthy();
    fireEvent.click(screen.getByText("CSV"));
    await waitFor(() => expect(urls.at(-1)).toBe("/api/privs.csv?name=BIG&tab=read&q=obj_01&sort=n&dir=1"));
  });
});

const node = (id: string, lane: number, extra: Partial<GraphNode> = {}): GraphNode => ({
  id, name: id, label: id, sub: null, kind: "technical", raw_kind: "technical", type: null, db: null, schema: null, lane,
  depth: lane, badge: "", tip: "", marks: [], rules: [], action: null, group: null, ...extra,
});

describe("lazy graph boxes", () => {
  it("draws a line into a closed lazy lane box from the role names it carries", () => {
    const lane = (id: string, lazy: boolean, ns: GraphNode[], ids: string[] | null) =>
      ({ kind: "lane_group", label: id, noun: "roles", count: 2, sensitive: 0, findings: 0, classes: [], nodes: ns, edges: [], truncated: 0, drill: null, lazy, ids }) as G["groups"][string];
    const e = (s: string, t: string): GraphEdge => ({ id: `${s}>${t}>inherit`, source: s, target: t, cls: "inherit", privs: [], count: null, back: false, rules: [], has: null, lacks: null });
    const g: G = {
      title: "t", header: "", level: "summary", note: null, full: false, selected: null, lanes: [], legend: { kinds: [], edges: [], marks: [], rules: false },
      nodes: [node("F", 0), node("lane:1", 1, { kind: "lane_group" }), node("lane:2", 2, { kind: "lane_group" })],
      edges: [e("F", "lane:1"), e("lane:1", "lane:2")],
      groups: { "lane:1": lane("lane:1", false, [node("T1", 1)], null), "lane:2": lane("lane:2", true, [], ["T2", "T3"]) },
    };
    g.groups["lane:1"].edges = [e("F", "T1"), e("T1", "T2")];
    expect(expand(g, new Set(["lane:1"])).edges.map((x) => x.id).sort()).toEqual(["F>T1>inherit", "T1>lane:2>inherit"]);
  });

  it("fetches a box's members from graph?group= when it is opened", async () => {
    const urls: string[] = [];
    setTransport(async (_m, url) => {
      urls.push(url);
      return { kind: "database_group", label: "DB05", noun: "objects", count: 2, sensitive: 0, findings: 0, classes: ["read"],
        nodes: [node("DB05.S.T1", 1, { kind: "object" }), node("DB05.S.T2", 1, { kind: "object" })],
        edges: [{ id: "R>DB05.S.T1>read", source: "R", target: "DB05.S.T1", cls: "read", privs: ["SELECT"], count: null, back: false, rules: [], has: null, lacks: null }],
        truncated: 0, drill: null, lazy: false };
    });
    const box = node("DB05", 1, { kind: "database_group", sub: "6186 objects", action: { kind: "expand", group: "DB05" }, group: "DB05" });
    const g: G = {
      title: "t", header: "", level: "summary", note: null, full: false, selected: null,
      lanes: [{ index: 0, label: "Depth 0", depth: 0 }, { index: 1, label: "Databases", depth: 1 }],
      nodes: [node("R", 0), box], edges: [{ id: "R>DB05>read", source: "R", target: "DB05", cls: "read", privs: ["SELECT"], count: 6186, back: false, rules: [], has: null, lacks: null }],
      groups: { DB05: { kind: "database_group", label: "DB05", noun: "objects", count: 6186, sensitive: 0, findings: 0, classes: ["read"], nodes: [], edges: [], truncated: 0, drill: null, lazy: true } },
      src: { of: "user", name: "BIG" }, legend: { kinds: [], edges: [], marks: [], rules: false },
    };
    const { container } = render(<Graph graph={g} legend={false} />);
    const el = await waitFor(() => {
      const n = container.querySelector('.react-flow__node[data-id="DB05"]');
      expect(n).toBeTruthy();
      return n as HTMLElement;
    }, { timeout: 5000 });
    await act(async () => { fireEvent.click(el); });
    await waitFor(() => expect(urls).toEqual(["/api/graph?of=user&name=BIG&group=DB05"]));
    expect(await screen.findByText(/DB05 · 6186 objects/)).toBeTruthy(); // the "Opened" chip: the box is open
  });
});
