// Node sizes and ELK layout. elk.bundled.js without a workerUrl runs on the main thread: no Worker, no eval
// (Streamlit in Snowflake's CSP blocks both).
import ELK from "elkjs/lib/elk.bundled.js";
import type { ElkNode } from "elkjs/lib/elk-api";
import type { Graph, GraphNode } from "../api/types";

const CH = 7.2; // mono char width at 12px
const PAD = 26;
export const LANE_GAP = 90;
const ROW_GAP = 14;
export const TOP = 36; // room for lane labels

/** Up to 3 lines of about `cap` chars, broken after '_' or '.' (as ui.wrap). */
export function wrap(s: string, cap = 26, n = 3): string[] {
  const out: string[] = [];
  while (s.length > cap && out.length < n - 1) {
    let cut = Math.max(s.lastIndexOf("_", cap), s.lastIndexOf(".", cap)) + 1;
    if (cut <= 0) {
      const after = [s.indexOf("_", cap), s.indexOf(".", cap)].filter((i) => i > 0).map((i) => i + 1);
      cut = after.length ? Math.min(...after) : s.length;
    }
    if (cut >= s.length) break;
    out.push(s.slice(0, cut));
    s = s.slice(cut);
  }
  return [...out, s];
}

export function nodeSize(n: GraphNode): { w: number; h: number; lines: string[] } {
  const lines = wrap(n.label);
  const longest = Math.max(...lines.map((l) => l.length), (n.sub ?? "").length * 0.85, n.badge.length * 0.8);
  const w = Math.min(280, Math.max(n.kind === "user" ? 110 : 120, longest * CH + PAD + (n.marks.includes("sensitive") ? 18 : 0)));
  const h = 18 + lines.length * 16 + (n.sub ? 15 : 0) + (n.badge ? 14 : 0);
  return { w, h, lines };
}

const elk = new ELK();

export interface Placed { id: string; x: number; y: number; w: number; h: number }
export interface Layout { nodes: Map<string, Placed>; lanes: { index: number; label: string; x: number; w: number }[]; width: number; height: number }

/** ELK orders boxes within lanes (fewest crossings); x comes from the lane, boxes in a lane never overlap. */
export async function layout(g: Graph): Promise<Layout> {
  const size = new Map(g.nodes.map((n) => [n.id, nodeSize(n)]));
  const laneOf = new Map(g.nodes.map((n) => [n.id, n.lane]));
  const forward = g.edges.filter((e) => (laneOf.get(e.source) ?? 0) < (laneOf.get(e.target) ?? 0));
  const root: ElkNode = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered", "elk.direction": "RIGHT", "elk.partitioning.activate": "true",
      "elk.spacing.nodeNode": String(ROW_GAP), "elk.layered.spacing.nodeNodeBetweenLayers": String(LANE_GAP),
      "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP", "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
    },
    children: g.nodes.map((n) => ({
      id: n.id, width: size.get(n.id)!.w, height: size.get(n.id)!.h,
      layoutOptions: { "elk.partitioning.partition": String(n.lane) },
    })),
    edges: forward.map((e) => ({ id: e.id, sources: [e.source], targets: [e.target] })),
  };
  let ys = new Map<string, number>();
  try {
    const res = await elk.layout(root);
    ys = new Map((res.children ?? []).map((c) => [c.id, c.y ?? 0]));
  } catch {
    // keep input order when ELK refuses the graph
  }
  const laneIdx = [...new Set(g.nodes.map((n) => n.lane))].sort((a, b) => a - b);
  const laneW = new Map(laneIdx.map((l) => [l, Math.max(...g.nodes.filter((n) => n.lane === l).map((n) => size.get(n.id)!.w))]));
  let x = 0;
  const laneX = new Map<number, number>();
  for (const l of laneIdx) { laneX.set(l, x); x += laneW.get(l)! + LANE_GAP; }
  const nodes = new Map<string, Placed>();
  let height = 0;
  for (const l of laneIdx) {
    const inLane = g.nodes.filter((n) => n.lane === l);
    inLane.sort((a, b) => (ys.get(a.id) ?? 0) - (ys.get(b.id) ?? 0));
    let bottom = TOP;
    inLane.forEach((n, i) => {
      const s = size.get(n.id)!;
      const y = Math.max(TOP + (ys.has(n.id) ? ys.get(n.id)! : i * 60), bottom);
      // centre the box in its lane column
      nodes.set(n.id, { id: n.id, x: laneX.get(l)! + (laneW.get(l)! - s.w) / 2, y, w: s.w, h: s.h });
      bottom = y + s.h + ROW_GAP;
    });
    height = Math.max(height, bottom);
  }
  const label = new Map(g.lanes.map((l) => [l.index, l.label]));
  return {
    nodes, width: Math.max(0, x - LANE_GAP), height,
    lanes: laneIdx.map((l) => ({ index: l, label: label.get(l) ?? `Depth ${l}`, x: laneX.get(l)!, w: laneW.get(l)! })),
  };
}
