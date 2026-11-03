// Pure graph helpers: build a lane graph from paths, combine boxes when big, expand combined boxes on click.
import type { EdgeCls, Graph, GraphEdge, GraphGroup, GraphNode, NodeKind } from "../api/types";

export const MAX_BOXES = 12; // a.MAX_OBJECTS: a lane's boxes before they combine

const KNOWN = new Set<string>([
  "user", "functional", "technical", "group", "database_role", "admin", "object",
  "schema_group", "database_group", "type_group", "fold", "lane_group",
]);
export const GROUP_KINDS = new Set<string>(["schema_group", "database_group", "type_group", "fold", "lane_group"]);

/** access.py kind -> NodeKind; "database" is the database-role kind there, unknown kinds draw as group. */
export function normKind(raw: string | null | undefined): NodeKind {
  if (raw === "database") return "database_role";
  return (raw && KNOWN.has(raw) ? raw : "group") as NodeKind;
}

export function makeNode(id: string, kind: NodeKind, lane: number, extra: Partial<GraphNode> = {}): GraphNode {
  return {
    id, name: id, label: id, sub: null, kind, raw_kind: null, type: null, db: null, schema: null, lane,
    depth: null, badge: "", tip: "", marks: [], rules: [], action: null, group: null, ...extra,
  };
}

function makeEdge(source: string, target: string, cls: EdgeCls, privs: string[] = [], back = false): GraphEdge {
  return { id: `${source}>${target}>${cls}`, source, target, cls, privs, count: null, back, rules: [], has: null, lacks: null };
}

/** Database of a node: given db, else the part before the first dot (object and database-role names are qualified). */
export const dbOf = (n: GraphNode): string => n.db ?? (n.id.includes(".") ? n.id.split(".")[0] : n.id);

export interface PathIn {
  path: string[]; // start, roles..., then the object when `cls` is set
  cls?: EdgeCls;
  privilege?: string;
}

export interface BuildOpts {
  kinds: Record<string, string>; // id -> kind (refs.kinds); objects default to "object"
  title?: string;
  max?: number;
  objectLabel?: string;
  node?: (n: GraphNode) => GraphNode; // caller hook: action, marks, sub ...
}

/** Graph from paths: lane = shortest depth of each role, objects in the last lane, then combine() when big. */
export function pathGraph(paths: PathIn[], o: BuildOpts): Graph {
  const lane = new Map<string, number>();
  const objs = new Set<string>();
  for (const p of paths) {
    const roles = p.cls ? p.path.slice(0, -1) : p.path;
    roles.forEach((id, i) => lane.set(id, Math.min(lane.get(id) ?? i, i)));
    if (p.cls) objs.add(p.path[p.path.length - 1]);
  }
  for (const id of objs) lane.delete(id);
  const last = Math.max(0, ...lane.values()) + 1;
  const kindOf = (id: string, obj: boolean) => normKind(o.kinds[id] ?? (obj ? "object" : undefined));
  const nodes: GraphNode[] = [];
  for (const [id, l] of lane) nodes.push(roleNode(id, kindOf(id, false), l));
  for (const id of objs) nodes.push(makeNode(id, kindOf(id, true), last, { depth: null, db: id.split(".")[0] }));

  const edges = new Map<string, GraphEdge>();
  const add = (a: string, b: string, cls: EdgeCls, priv?: string) => {
    const back = !objs.has(b) && (lane.get(a) ?? 0) >= (lane.get(b) ?? 0);
    const e = edges.get(`${a}>${b}>${cls}`) ?? makeEdge(a, b, cls, [], back);
    if (priv && !e.privs.includes(priv)) e.privs.push(priv);
    edges.set(e.id, e);
  };
  for (const p of paths) {
    const roles = p.cls ? p.path.slice(0, -1) : p.path;
    for (let i = 1; i < roles.length; i++) {
      add(roles[i - 1], roles[i], kindOf(roles[i], false) === "database_role" ? "inherit_db" : "inherit");
    }
    if (p.cls && roles.length) add(roles[roles.length - 1], p.path[p.path.length - 1], p.cls, p.privilege);
  }
  const lanes = Array.from({ length: last + 1 }, (_, i) => ({
    index: i, depth: i === 0 || i === last ? null : i,
    label: i === 0 ? "Start" : i === last ? o.objectLabel ?? "Objects" : `Depth ${i}`,
  }));
  if (!objs.size) lanes.pop();
  const g: Graph = {
    title: o.title ?? "", header: "", level: "object", note: null, full: false, selected: paths[0]?.path[0] ?? null,
    lanes, nodes: o.node ? nodes.map(o.node) : nodes, edges: [...edges.values()], groups: {},
    legend: { kinds: [], edges: [], marks: [], rules: false },
  };
  const out = combine(g, o.max ?? MAX_BOXES);
  out.legend = legendOf(out);
  return out;
}

function roleNode(id: string, kind: NodeKind, lane: number): GraphNode {
  if (kind !== "database_role" || !id.includes(".")) return makeNode(id, kind, lane, { depth: lane || null });
  const cut = id.indexOf(".");
  return makeNode(id, kind, lane, { depth: lane || null, label: id.slice(cut + 1), db: id.slice(0, cut), sub: id.slice(0, cut) });
}

/** Moves `members` into one combined box `box`: edges touching them go into the group, visible edges point at the box. */
export function fold(g: Graph, box: GraphNode, members: GraphNode[], noun: string): Graph {
  const ids = new Set(members.map((n) => n.id));
  const inner = g.edges.filter((e) => ids.has(e.source) || ids.has(e.target));
  const rest = g.edges.filter((e) => !ids.has(e.source) && !ids.has(e.target));
  const merged = new Map<string, GraphEdge & { _m: Set<string> }>();
  for (const e of inner) {
    const s = ids.has(e.source) ? box.id : e.source;
    const t = ids.has(e.target) ? box.id : e.target;
    if (s === t) continue;
    const key = `${s}>${t}>${e.cls}`;
    const m = merged.get(key) ?? { ...makeEdge(s, t, e.cls, [], e.back), _m: new Set<string>() };
    for (const p of e.privs) if (!m.privs.includes(p)) m.privs.push(p);
    m._m.add(ids.has(e.target) ? e.target : e.source);
    merged.set(key, m);
  }
  const outer = [...merged.values()].map(({ _m, ...e }) => ({ ...e, count: _m.size }));
  const group: GraphGroup = {
    kind: box.kind, label: box.label, noun, count: members.length,
    sensitive: members.filter((n) => n.marks.includes("sensitive")).length,
    findings: members.reduce((s, n) => s + n.rules.length, 0),
    classes: [...new Set(inner.map((e) => e.cls).filter((c) => c !== "inherit" && c !== "inherit_db"))] as GraphGroup["classes"],
    nodes: members, edges: inner, truncated: 0, drill: null,
  };
  const node = { ...box, group: box.id, action: { kind: "expand" as const, group: box.id } };
  return {
    ...g, nodes: [...g.nodes.filter((n) => !ids.has(n.id)), node], edges: [...rest, ...outer],
    groups: { ...g.groups, [box.id]: group },
  };
}

/** Over `max` objects: one box per database. A role lane over `max` boxes: one box for the lane. */
export function combine(g: Graph, max = MAX_BOXES): Graph {
  let out = g;
  const objs = g.nodes.filter((n) => n.kind === "object" || n.kind === "admin" && n.id.startsWith("priv:"));
  if (objs.length > max) {
    const by = new Map<string, GraphNode[]>();
    for (const n of objs) by.set(dbOf(n), [...(by.get(dbOf(n)) ?? []), n]);
    for (const [db, ms] of by) {
      if (ms.length < 2) continue;
      const box = makeNode(`db:${db}`, "database_group", ms[0].lane, { label: db, db, sub: `${ms.length} objects` });
      out = fold(out, box, ms, "objects");
    }
  }
  const lanes = new Map<number, GraphNode[]>();
  for (const n of out.nodes) if (n.lane > 0 && !GROUP_KINDS.has(n.kind) && n.kind !== "object" && !n.id.startsWith("priv:")) {
    lanes.set(n.lane, [...(lanes.get(n.lane) ?? []), n]);
  }
  for (const [l, ms] of lanes) {
    if (ms.length <= max) continue;
    const box = makeNode(`lane:${l}`, "lane_group", l, { label: `${ms.length} roles`, sub: `Depth ${l}`, depth: l });
    out = fold(out, box, ms, "roles");
  }
  return out;
}

/** The graph with the boxes in `open` swapped for their members; edges to members of closed boxes point at the box. */
export function expand(g: Graph, open: Set<string>): Graph {
  const isOpen = (id: string) => open.has(id) && !!g.groups[id];
  if (![...open].some(isOpen)) return g;
  const owner = new Map<string, string>();
  for (const [id, grp] of Object.entries(g.groups)) if (!isOpen(id)) for (const n of grp.nodes) owner.set(n.id, id);
  const nodes = g.nodes.filter((n) => !isOpen(n.id));
  const edges = g.edges.filter((e) => !isOpen(e.source) && !isOpen(e.target));
  for (const id of open) {
    if (!isOpen(id)) continue;
    nodes.push(...g.groups[id].nodes);
    edges.push(...g.groups[id].edges);
  }
  const have = new Set(nodes.map((n) => n.id));
  const out = new Map<string, GraphEdge>();
  for (const e of edges) {
    const s = owner.get(e.source) ?? e.source;
    const t = owner.get(e.target) ?? e.target;
    if (s === t || !have.has(s) || !have.has(t)) continue;
    const id = `${s}>${t}>${e.cls}`;
    const m = out.get(id);
    if (!m) out.set(id, { ...e, id, source: s, target: t, privs: [...e.privs] });
    else for (const p of e.privs) if (!m.privs.includes(p)) m.privs.push(p);
  }
  return { ...g, nodes, edges: [...out.values()] };
}

export function legendOf(g: Graph): Graph["legend"] {
  const kinds = [...new Set(g.nodes.map((n) => n.kind))];
  const edges = [...new Set(g.edges.map((e) => (e.back ? "inherit" : e.cls)))] as EdgeCls[];
  const marks = [...new Set(g.nodes.flatMap((n) => n.marks))];
  return { kinds, edges, marks, rules: g.nodes.some((n) => n.rules.length > 0) };
}
