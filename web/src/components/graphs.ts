// Pure graph helpers: build a lane graph from paths, combine boxes when big, expand combined boxes on click.
import type { EdgeCls, Graph, GraphEdge, GraphGroup, GraphNode, NodeKind, PrivClass } from "../api/types";

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


export const FOLD_MIN = 6; // database roles of one database (or group roles) in one lane that fold into one box
export const MAX_LANE = 24; // role boxes one lane draws before the rest fold into one box

const CLS_SHOWN: PrivClass[] = ["read", "write", "manage", "own", "use"];
const RANK: PrivClass[] = ["own", "manage", "write", "read", "use"];
const isRole = (n: GraphNode) =>
  !n.group && !GROUP_KINDS.has(n.kind) && n.kind !== "object" && n.kind !== "user" && !n.id.startsWith("priv:");

export const plural = (n: number, w: string) =>
  `${n} ${n === 1 ? w : /[^aeiou]y$/.test(w) ? w.slice(0, -1) + "ies" : /(s|x|ch|sh)$/.test(w) ? w + "es" : w + "s"}`;

/** "6 read · 6 write · 5 manage": roles counted by the strongest class of their own grants (node.classes from the
 * server, else their lines to objects in this graph), not by their names. */
export function classCounts(ms: GraphNode[], g: Graph): string {
  const drawn = new Map<string, Set<string>>();
  for (const e of g.edges) if (!e.cls.startsWith("inherit")) drawn.set(e.source, (drawn.get(e.source) ?? new Set()).add(e.cls));
  const n = new Map<string, number>();
  for (const m of ms) {
    const top = RANK.find((c) => (m.classes ? m.classes.includes(c) : drawn.get(m.id)?.has(c)));
    if (top) n.set(top, (n.get(top) ?? 0) + 1);
  }
  return CLS_SHOWN.filter((c) => n.has(c)).map((c) => `${n.get(c)} ${c}`).join(" · ");
}

/** Crowded role lanes: FOLD_MIN+ database roles of one database, or group roles, become one box each (counts by grant
 * class); a lane still over `cap` boxes folds its other roles into one box. The selected node never folds. */
export function foldRoles(g: Graph, cap = MAX_LANE): Graph {
  const lanes = new Map<number, GraphNode[]>();
  for (const n of g.nodes) if (n.lane > 0 && isRole(n) && n.id !== g.selected) lanes.set(n.lane, [...(lanes.get(n.lane) ?? []), n]);
  let out = g;
  for (const [l, ms] of lanes) {
    const by = new Map<string, GraphNode[]>();
    for (const n of ms) {
      const k = n.kind === "database_role" ? `db:${dbOf(n)}` : n.kind === "group" ? "group" : null;
      if (k) by.set(k, [...(by.get(k) ?? []), n]);
    }
    let left = ms;
    let boxes = 0;
    for (const [k, xs] of by) {
      if (xs.length < FOLD_MIN) continue;
      const db = k !== "group";
      const noun = db ? "database roles" : "group roles";
      const box = makeNode(`fold:${l}:${k}`, xs[0].kind, l, {
        label: db ? dbOf(xs[0]) : "Group roles", sub: `${xs.length} ${noun}`, badge: classCounts(xs, g),
        db: db ? dbOf(xs[0]) : null, depth: xs[0].depth,
      });
      out = fold(out, box, xs, noun);
      left = left.filter((n) => !xs.includes(n));
      boxes++;
    }
    if (left.length + boxes > cap && left.length > 1) {
      const lane = g.lanes.find((x) => x.index === l)?.label ?? `Depth ${l}`;
      out = fold(out, makeNode(`lane:${l}`, "lane_group", l, { label: `${left.length} roles`, sub: lane, depth: l }), left, "roles");
    }
  }
  return out;
}

/** Over `max` objects: one box per database. Crowded role lanes: foldRoles with `max` boxes a lane. */
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
  return foldRoles(out, max);
}

export interface Bucket { key: string; label: string; sub: string; kind: NodeKind; members: GraphNode[] }

const ROLE_WORD: Record<string, string> = {
  functional: "Functional roles", technical: "Technical roles", group: "Group roles", admin: "Admin roles",
};

/** A box too big to draw member by member (over 2 * max): objects by schema, then by type; roles by kind and database;
 * then name ranges of at most `max` boxes. null: draw the members. */
export function buckets(ms: GraphNode[], max = MAX_BOXES): Bucket[] | null {
  if (ms.length <= max * 2) return null;
  const objs = ms.every((n) => n.kind === "object");
  const type = (n: GraphNode) => (n.type ?? "object").toLowerCase().replace(/^future /, "");
  const scope = (n: GraphNode) => [n.db ?? dbOf(n), n.schema].filter(Boolean).join(".");
  const what = (xs: GraphNode[]) => {
    const ts = new Set(xs.map(type));
    return plural(xs.length, ts.size === 1 ? [...ts][0] : objs ? "object" : xs[0].kind === "database_role" ? "database role" : "role");
  };
  const keys: [(n: GraphNode) => string, (xs: GraphNode[]) => Omit<Bucket, "key" | "members">][] = objs
    ? [[scope, (xs) => ({ label: scope(xs[0]), sub: what(xs), kind: "schema_group" })],
       [type, (xs) => ({ label: scope(xs[0]), sub: what(xs), kind: "type_group" })]]
    : [[(n) => (n.kind === "database_role" ? `db:${dbOf(n)}` : n.kind), (xs) => ({
        label: xs[0].kind === "database_role" ? dbOf(xs[0]) : ROLE_WORD[xs[0].kind] ?? "Roles", sub: what(xs), kind: xs[0].kind,
      })]];
  for (const [key, make] of keys) {
    const by = new Map<string, GraphNode[]>();
    for (const n of ms) by.set(key(n), [...(by.get(key(n)) ?? []), n]);
    if (by.size < 2) continue;
    return [...by].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]))
      .map(([k, xs]) => ({ key: k, members: xs, ...make(xs) }));
  }
  const sorted = [...ms].sort((a, b) => a.label.localeCompare(b.label));
  const size = Math.ceil(sorted.length / max);
  const out: Bucket[] = [];
  for (let i = 0; i < sorted.length; i += size) {
    const xs = sorted.slice(i, i + size);
    const cut = (s: string) => (s.length > 12 ? s.slice(0, 11) + "…" : s);
    out.push({ key: `${i}`, members: xs, label: `${cut(xs[0].label)} – ${cut(xs[xs.length - 1].label)}`, sub: what(xs),
      kind: objs ? "type_group" : xs[0].kind });
  }
  return out;
}

/** The graph with the boxes in `open` swapped for their members (a big box: for its buckets, which open the same way);
 * edges to members of closed boxes point at the box. Opened boxes leave `groups`. */
export function expand(g: Graph, open: Set<string>, max = MAX_BOXES): Graph {
  const here = new Set(g.nodes.map((n) => n.id));
  const opening = new Set([...open].filter((id) => g.groups[id] && here.has(id)));
  if (!opening.size) return g;
  const owner = new Map<string, string>();
  for (const [id, grp] of Object.entries(g.groups)) if (!opening.has(id)) for (const n of grp.nodes) owner.set(n.id, id);
  const nodes = g.nodes.filter((n) => !opening.has(n.id));
  const edges = g.edges.filter((e) => !opening.has(e.source) && !opening.has(e.target));
  for (const id of opening) {
    nodes.push(...g.groups[id].nodes);
    edges.push(...g.groups[id].edges);
  }
  const have = new Set(nodes.map((n) => n.id));
  const merged = new Map<string, GraphEdge>();
  for (const e of edges) {
    const s = owner.get(e.source) ?? e.source;
    const t = owner.get(e.target) ?? e.target;
    if (s === t || !have.has(s) || !have.has(t)) continue;
    const id = `${s}>${t}>${e.cls}`;
    const m = merged.get(id);
    if (!m) merged.set(id, { ...e, id, source: s, target: t, privs: [...e.privs] });
    else for (const p of e.privs) if (!m.privs.includes(p)) m.privs.push(p);
  }
  const groups = Object.fromEntries(Object.entries(g.groups).filter(([id]) => !opening.has(id)));
  let out: Graph = { ...g, nodes, edges: [...merged.values()], groups };
  for (const id of opening) {
    const grp = g.groups[id];
    for (const b of buckets(grp.nodes, max) ?? []) {
      if (b.members.length < 2) continue;
      const box = makeNode(`${id}/${b.key}`, b.kind, b.members[0].lane, {
        label: b.label, sub: b.sub, db: b.members[0].db, depth: b.members[0].depth,
      });
      out = fold(out, box, b.members, grp.noun);
    }
  }
  return expand(out, open, max);
}

/** Every node and edge on a path through `id` (a node, or an edge "a>b>cls"): its ancestors and its descendants. */
export function related(g: Graph, id: string): Set<string> {
  const outs = new Map<string, GraphEdge[]>();
  const ins = new Map<string, GraphEdge[]>();
  for (const e of g.edges) {
    outs.set(e.source, [...(outs.get(e.source) ?? []), e]);
    ins.set(e.target, [...(ins.get(e.target) ?? []), e]);
  }
  const seen = new Set<string>([id]);
  const walk = (start: string, next: Map<string, GraphEdge[]>, end: (e: GraphEdge) => string) => {
    const todo = [start];
    seen.add(start);
    while (todo.length) {
      for (const e of next.get(todo.pop()!) ?? []) {
        seen.add(e.id);
        if (!seen.has(end(e))) { seen.add(end(e)); todo.push(end(e)); }
      }
    }
  };
  const edge = g.edges.find((e) => e.id === id);
  walk(edge ? edge.source : id, ins, (e) => e.source);
  walk(edge ? edge.target : id, outs, (e) => e.target);
  return seen;
}

const nameOf = (n: GraphNode) => (n.kind === "object" ? `${(n.type ?? "object").toLowerCase()} ${n.name}` : n.name);

/** An edge in words: "F_ANALYST is granted role T_SALES_READ", "T_READ has SELECT on 12 tables in SALES.CORE",
 * "Folded: 6 of the 18 database roles in HR ...", then rule hits. by: the drawn nodes. */
export function edgeTip(e: GraphEdge, by: Map<string, GraphNode>, groups: Record<string, GraphGroup>): string {
  const s = by.get(e.source);
  const t = by.get(e.target);
  if (!s || !t) return "";
  const gs = groups[s.id];
  const gt = groups[t.id];
  const n = e.count ?? 0;
  const who = gs ? `${n || gs.count} of the ${plural(gs.count, gs.noun.replace(/s$/, ""))} in ${s.label}` : s.name;
  const part = (x: GraphGroup) => (!gs && n && n < x.count ? `${n} of the ${x.count}` : `${x.count}`);
  const role = (x: GraphNode) => (x.kind === "database_role" ? "database role" : "role");
  let line: string;
  if (e.cls === "inherit" || e.cls === "inherit_db") {
    const what = gt ? `${part(gt)} ${gt.noun} of ${t.label}` : `${role(t)} ${t.name}`;
    line = `${who} ${gs && (n || gs.count) > 1 ? "are" : "is"} granted ${what}`;
  } else {
    const privs = e.privs.length ? e.privs.join(", ") : e.cls;
    const what = gt ? `${part(gt)} ${gt.noun} in ${t.label}` : nameOf(t);
    line = `${who} ${gs && (n || gs.count) > 1 ? "have" : "has"} ${privs} on ${what}`;
  }
  return [
    (gs || gt ? "Folded: " : e.back ? "Also deeper: " : "") + line,
    e.has ? `Has: ${e.has.join(", ")}` : "", e.lacks ? `Lacks: ${e.lacks.join(", ")}` : "",
    ...e.rules.map((r) => `Rule ${r.num} (${r.severity}): ${r.title}`),
  ].filter(Boolean).join("\n");
}

export function legendOf(g: Graph): Graph["legend"] {
  const kinds = [...new Set(g.nodes.map((n) => n.kind))];
  const edges = [...new Set(g.edges.map((e) => (e.back ? "inherit" : e.cls)))] as EdgeCls[];
  const marks = [...new Set(g.nodes.flatMap((n) => n.marks))];
  return { kinds, edges, marks, rules: g.nodes.some((n) => n.rules.length > 0) };
}
