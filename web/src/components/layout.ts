// Node sizes and ELK layout. elk.bundled.js without a workerUrl runs on the main thread: no Worker, no eval
// (Streamlit in Snowflake's CSP blocks both). It is loaded on the first graph: the local build keeps ELK (1.6 MB) in
// its own file, so pages without a graph never fetch it; the Streamlit build inlines it (one JS file).
import type { ElkNode } from "elkjs/lib/elk-api";
import type { Graph, GraphNode } from "../api/types";

const CH = 7.2; // mono char width at 12px
const PAD = 26;
export const LANE_GAP = 72;
const ROW_GAP = 16;
export const TOP = 40; // room for lane headers
const MAX_W = 250;

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

/** Badge lines: "D1 · also D2, D3 · also grant holder" puts each part after the first "·" group on its own line. */
export const badgeLines = (b: string) => (b ? b.split(" · also grant holder").concat(b.includes("also grant holder") ? ["also grant holder"] : []).filter(Boolean) : []);

/** A subtitle ("table · SALES.CORE") on up to 2 lines that fit a box, broken after " · " or ".", never mid-word. */
export function subLines(s: string, cap = 34): string[] {
  if (s.length <= cap) return s ? [s] : [];
  const cut = Math.max(s.lastIndexOf(" · ", cap), s.lastIndexOf(".", cap));
  if (cut <= 0) return [s];
  const head = s.slice(0, s[cut] === "." ? cut + 1 : cut), tail = s.slice(s[cut] === "." ? cut + 1 : cut + 3);
  return [head, tail.length > cap ? tail.slice(0, cap - 1) + "…" : tail];
}

export function nodeSize(n: GraphNode): { w: number; h: number; lines: string[]; subs: string[] } {
  const lines = wrap(n.label);
  const subs = subLines(n.sub ?? "");
  const bl = badgeLines(n.badge);
  const longest = Math.max(...lines.map((l) => l.length), ...subs.map((l) => l.length * 0.85), ...bl.map((l) => l.length * 0.85));
  const w = Math.min(MAX_W, Math.max(n.kind === "user" ? 120 : 140, longest * CH + PAD + (n.marks.includes("sensitive") ? 18 : 0)));
  const h = 20 + lines.length * 16 + subs.length * 14 + (subs.length ? 1 : 0) + bl.length * 14;
  return { w, h, lines, subs };
}

type Elk = { layout: (g: ElkNode) => Promise<ElkNode> };
let elk: Promise<Elk> | null = null;
const getElk = () => (elk ??= import("elkjs/lib/elk.bundled.js").then((m) => new m.default() as unknown as Elk));

export interface Pt { x: number; y: number }
export interface Placed { id: string; x: number; y: number; w: number; h: number }
export interface Layout {
  nodes: Map<string, Placed>;
  routes: Map<string, Pt[]>; // forward edges: ELK's orthogonal route, start to end
  labels: Map<string, Pt>; // where an edge's count sits: the middle of its longest stretch no other edge shares
  lanes: { index: number; label: string; x: number; w: number }[];
  width: number;
  height: number;
}

const KIND_ORDER = ["user", "admin", "functional", "group", "technical", "database_role", "object"];

/** ELK layered, one layer per lane (interactive layering keeps the lane of every box), orthogonal edges routed around
 * the boxes, crossings minimised with the input order (kind, database, name) as the tie-break, so alike boxes sit
 * together. Every box of a lane gets the lane's width: lines leave a lane at one x. */
export async function layout(g: Graph): Promise<Layout> {
  const size = new Map(g.nodes.map((n) => [n.id, nodeSize(n)]));
  const laneW = new Map<number, number>();
  for (const n of g.nodes) laneW.set(n.lane, Math.max(laneW.get(n.lane) ?? 0, size.get(n.id)!.w));
  for (const n of g.nodes) size.get(n.id)!.w = laneW.get(n.lane)!;
  const laneOf = new Map(g.nodes.map((n) => [n.id, n.lane]));
  const forward = g.edges.filter((e) => laneOf.has(e.source) && laneOf.has(e.target) && laneOf.get(e.source)! < laneOf.get(e.target)!);
  const rank = (n: GraphNode) => KIND_ORDER.indexOf(n.kind) + 1 || KIND_ORDER.length;
  const order = [...g.nodes].sort((a, b) =>
    a.lane - b.lane || rank(a) - rank(b) || (a.db ?? "").localeCompare(b.db ?? "") || a.label.localeCompare(b.label));
  const root: ElkNode = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered", "elk.direction": "RIGHT", "elk.edgeRouting": "ORTHOGONAL",
      "elk.layered.layering.strategy": "INTERACTIVE", "elk.padding": "[top=0,left=0,bottom=0,right=0]",
      "elk.spacing.nodeNode": String(ROW_GAP), "elk.layered.spacing.nodeNodeBetweenLayers": String(LANE_GAP),
      "elk.spacing.edgeEdge": "5", "elk.spacing.edgeNode": "12", "elk.layered.spacing.edgeNodeBetweenLayers": "18",
      "elk.layered.spacing.edgeEdgeBetweenLayers": "5", "elk.layered.mergeEdges": "true",
      // big drawings (an opened fold box, ?full=1) get fewer crossing-minimisation passes: seconds, not a frozen tab
      "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP", "elk.layered.thoroughness": g.nodes.length > 150 ? "7" : "20",
      "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
      "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF", "elk.layered.nodePlacement.bk.fixedAlignment": "BALANCED",
    },
    children: order.map((n) => ({ id: n.id, x: n.lane * 2000, y: 0, width: size.get(n.id)!.w, height: size.get(n.id)!.h })),
    edges: forward.map((e) => ({ id: e.id, sources: [e.source], targets: [e.target] })),
  };
  try {
    const res = await (await getElk()).layout(root);
    const nodes = new Map<string, Placed>();
    for (const c of res.children ?? []) {
      const s = size.get(c.id)!;
      nodes.set(c.id, { id: c.id, x: c.x ?? 0, y: TOP + (c.y ?? 0), w: s.w, h: s.h });
    }
    const routes = new Map<string, Pt[]>();
    for (const e of res.edges ?? []) {
      const s = e.sections?.[0];
      if (s) routes.set(e.id, [s.startPoint, ...(s.bendPoints ?? []), s.endPoint].map((p) => ({ x: p.x, y: TOP + p.y })));
    }
    return finish(g, nodes, routes);
  } catch {
    return finish(g, columns(g, size), new Map()); // ELK refused the graph: plain columns, curved lines
  }
}

function columns(g: Graph, size: Map<string, { w: number; h: number }>): Map<string, Placed> {
  const out = new Map<string, Placed>();
  const lanes = [...new Set(g.nodes.map((n) => n.lane))].sort((a, b) => a - b);
  let x = 0;
  for (const l of lanes) {
    let y = TOP;
    let w = 0;
    for (const n of g.nodes.filter((m) => m.lane === l)) {
      const s = size.get(n.id)!;
      out.set(n.id, { id: n.id, x, y, w: s.w, h: s.h });
      y += s.h + ROW_GAP;
      w = Math.max(w, s.w);
    }
    x += w + LANE_GAP;
  }
  return out;
}

function finish(g: Graph, nodes: Map<string, Placed>, routes: Map<string, Pt[]>): Layout {
  const label = new Map(g.lanes.map((l) => [l.index, l.label]));
  const span = new Map<number, [number, number]>();
  for (const n of g.nodes) {
    const p = nodes.get(n.id);
    if (!p) continue;
    const [a, b] = span.get(n.lane) ?? [Infinity, -Infinity];
    span.set(n.lane, [Math.min(a, p.x), Math.max(b, p.x + p.w)]);
  }
  const all = [...nodes.values()];
  const pts = [...routes.values()].flat();
  return {
    nodes, routes, labels: labelSpots(routes),
    lanes: [...span].sort((a, b) => a[0] - b[0]).map(([l, [a, b]]) => ({ index: l, label: label.get(l) ?? `Depth ${l}`, x: a, w: b - a })),
    width: Math.max(0, ...all.map((p) => p.x + p.w), ...pts.map((p) => p.x)),
    height: Math.max(TOP, ...all.map((p) => p.y + p.h), ...pts.map((p) => p.y)) + 4,
  };
}

/** Where each route's count label goes: the middle of its longest horizontal stretch that no other route covers
 * (bundled routes share their trunks), else the middle of its first segment. */
export function labelSpots(routes: Map<string, Pt[]>): Map<string, Pt> {
  const flat = (pts: Pt[]) => pts.slice(1).map((b, i) => [pts[i], b] as const).filter(([a, b]) => Math.abs(a.y - b.y) < 0.5 && a.x !== b.x)
    .map(([a, b]) => ({ y: a.y, lo: Math.min(a.x, b.x), hi: Math.max(a.x, b.x) }));
  const segs = new Map([...routes].map(([id, pts]) => [id, flat(pts)]));
  const atY = new Map<number, { id: string; y: number; lo: number; hi: number }[]>(); // segments by row: no all-pairs scan
  for (const [id, ss] of segs) for (const s of ss) { const k = Math.round(s.y); atY.set(k, [...(atY.get(k) ?? []), { id, ...s }]); }
  const near = (y: number, id: string) => [-1, 0, 1].flatMap((d) => atY.get(Math.round(y) + d) ?? []).filter((o) => o.id !== id);
  const out = new Map<string, Pt>();
  for (const [id, pts] of routes) {
    let best: { y: number; lo: number; hi: number } | null = null;
    for (const s of segs.get(id)!) {
      // free stretches of s: s minus every other route's overlapping segment on the same y
      let free = [[s.lo, s.hi]];
      for (const o of near(s.y, id)) {
        if (Math.abs(o.y - s.y) >= 0.5) continue;
        free = free.flatMap(([a, b]) => [[a, Math.min(b, o.lo)], [Math.max(a, o.hi), b]].filter(([x, y]) => y - x > 0));
      }
      for (const [a, b] of free) if (!best || b - a > best.hi - best.lo) best = { y: s.y, lo: a, hi: b };
    }
    out.set(id, best && best.hi - best.lo >= 16 ? { x: (best.lo + best.hi) / 2, y: best.y }
      : { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 });
  }
  return out;
}

/** SVG path through orthogonal points with rounded corners (radius r, smaller on short segments). */
export function roundPath(pts: Pt[], r = 8): string {
  if (pts.length < 2) return "";
  let d = `M${pts[0].x},${pts[0].y}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const [a, b, c] = [pts[i - 1], pts[i], pts[i + 1]];
    const k = Math.min(r, Math.hypot(b.x - a.x, b.y - a.y) / 2, Math.hypot(c.x - b.x, c.y - b.y) / 2);
    const to = (p: Pt, q: Pt) => {
      const len = Math.hypot(q.x - p.x, q.y - p.y) || 1;
      return { x: p.x + ((q.x - p.x) / len) * k, y: p.y + ((q.y - p.y) / len) * k };
    };
    const p1 = to(b, a);
    const p2 = to(b, c);
    d += ` L${p1.x},${p1.y} Q${b.x},${b.y} ${p2.x},${p2.y}`;
  }
  const z = pts[pts.length - 1];
  return `${d} L${z.x},${z.y}`;
}
