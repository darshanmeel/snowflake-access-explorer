// Lane graph: ELK lays it out (one lane per depth, left to right, orthogonal bundled lines), React Flow draws it.
// Crowded lanes fold (database roles per database, group roles); folded and combined boxes open on click, big ones
// by schema / type first. Hover (or keyboard focus, or a first tap on a touch screen) shows what a box or line is in
// words and lights up every path through it; Enter / Space or a second tap opens it. A tall drawing starts centred
// on the selected box; up to 6 lanes it is shrunk to fit when that keeps the labels readable.
import { useEffect, useMemo, useRef, useState } from "react";
import {
  BaseEdge, EdgeLabelRenderer, Handle, Position, ReactFlow, Controls, getSmoothStepPath,
  type Edge, type EdgeProps, type Node, type NodeProps, type ReactFlowInstance, type Viewport,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Graph as G, GraphEdge, GraphNode } from "../api/types";
import { EDGE, KIND_LABEL, TOKENS, edgeColor, kindStyle, type ThemeName, type Tokens } from "./theme";
import { GROUP_KINDS, buckets, edgeTip, expand, foldRoles, related } from "./graphs";
import { layout, nodeSize, roundPath, type Layout, type Pt, badgeLines } from "./layout";
import { SEVERITY_ORDER } from "./Legend";
import { Legend } from "./Legend";

export interface GraphProps {
  graph: G;
  theme?: ThemeName;
  onNodeClick?: (n: GraphNode) => void;
  onRules?: (id: string) => void; // a click on a box's rule badge
  legend?: boolean;
  maxHeight?: number;
  minZoom?: number; // never drawn smaller than this (labels stay readable): wider graphs pan sideways instead
  focus?: string | null; // a picked box: everything not on a path through it fades (as on hover)
  hi?: Set<string>; // node and edge ids drawn red (risky paths)
  flow?: boolean; // line width grows with edge.count (people flowing through it)
}

const SEV = ["Critical", "High", "Medium", "Low"] as const;

type NData = { n: GraphNode; t: Tokens; lines: string[]; subs: string[]; selected: boolean; dim: boolean; red: boolean };
type EData = { e: GraphEdge; t: Tokens; pts?: Pt[]; at?: Pt; dim: boolean; hot: boolean; red: boolean; flow: boolean };
type Tip = { text: string; x: number; y: number };

const PAD = 16;
const FIT_ZOOM = 0.68; // smallest zoom a whole graph is shrunk to (mono labels stay readable)
const isBox = (n: GraphNode) => !!n.group || GROUP_KINDS.has(n.kind);

/** First view of a drawing: the zoom that fits the width (never below minZoom); up to 6 lanes, the zoom that fits
 * it all when that is at least FIT_ZOOM; else, when it is taller than the panel, centred on the selected box. */
export function startView(lay: { width: number; height: number; lanes: unknown[]; nodes: Map<string, { x: number; y: number; w: number; h: number }> },
  width: number, maxHeight: number, minZoom: number, selected: string | null): { view: Viewport; height: number } {
  const zw = Math.max(minZoom, Math.min(1, (width - 2 * PAD) / Math.max(1, lay.width)));
  const fit = Math.min(zw, (maxHeight - 2 * PAD) / Math.max(1, lay.height));
  const zoom = lay.lanes.length <= 6 && lay.height * zw + 2 * PAD > maxHeight && fit >= FIT_ZOOM ? fit : zw;
  const height = Math.min(maxHeight, Math.ceil(lay.height * zoom + 2 * PAD));
  const p = selected ? lay.nodes.get(selected) : undefined;
  const cx = (w: number, at: number, size: number) => Math.min(PAD, Math.max(w - PAD - size * zoom, w / 2 - at * zoom));
  const x = lay.width * zoom <= width - 2 * PAD ? Math.max(PAD, (width - lay.width * zoom) / 2) : p ? cx(width, p.x + p.w / 2, lay.width) : PAD;
  const y = lay.height * zoom + 2 * PAD <= maxHeight || !p ? PAD : cx(height, p.y + p.h / 2, lay.height);
  return { view: { x, y, zoom }, height };
}

export function Graph({ graph, theme = "light", onNodeClick, onRules, legend = true, maxHeight = 640, minZoom = 0.8, focus = null, hi, flow = false }: GraphProps) {
  const t = TOKENS[theme];
  const [open, setOpen] = useState<Map<string, string>>(new Map()); // opened box -> its label (for the chips)
  useEffect(() => setOpen(new Map()), [graph]);
  const folded = useMemo(() => foldRoles(graph), [graph]);
  const shown = useMemo(() => expand(folded, new Set(open.keys())), [folded, open]);
  const [laid, setLaid] = useState<{ g: G; lay: Layout } | null>(null);
  useEffect(() => {
    let live = true;
    layout(shown).then((l) => live && setLaid({ g: shown, lay: l }));
    return () => { live = false; };
  }, [shown]);
  const lay = laid?.lay ?? null;
  const busy = !laid || laid.g !== shown; // a layout is running: the old drawing stays, under a note

  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0); // 0 until measured: the first view is worked out for the real width
  useEffect(() => {
    if (!box.current) return;
    setWidth(box.current.clientWidth || 800);
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width || 800));
    ro.observe(box.current);
    return () => ro.disconnect();
  }, []);

  const [hover, setHover] = useState<string | null>(null);
  const [tip, setTip] = useState<Tip | null>(null);
  const lit = hover ?? (focus && shown.nodes.some((n) => n.id === focus) ? focus : null);
  const hot = useMemo(() => (lit ? related(shown, lit) : null), [shown, lit]);
  const byId = useMemo(() => new Map(shown.nodes.map((n) => [n.id, n])), [shown]);
  const { nodes, edges } = useMemo(() => toFlow(shown, lay, t, hot, focus, hi, flow), [shown, lay, t, hot, focus, hi, flow]);

  // the panel is as tall as the drawing; a resize keeps the reader's pan and zoom once they moved it
  const sel = useMemo(() => { // the picked box, else the start of the walk (the one box of the first lane)
    if (focus ?? graph.selected) return focus ?? graph.selected ?? null;
    const first = Math.min(...shown.nodes.map((n) => n.lane));
    const lane0 = shown.nodes.filter((n) => n.lane === first);
    return lane0.length === 1 ? lane0[0].id : null;
  }, [focus, graph.selected, shown]);
  const start = lay && width ? startView(lay, width, maxHeight, minZoom, sel) : null;
  const height = start?.height ?? 120;
  const pans = !!lay && !!start && (lay.width * start.view.zoom > width - 2 * PAD || lay.height * start.view.zoom + 2 * PAD > maxHeight);
  const rf = useRef<ReactFlowInstance | null>(null);
  const moved = useRef(false);
  const startKey = start ? `${start.view.x}:${start.view.y}:${start.view.zoom}` : "";
  useEffect(() => { if (start && rf.current && !moved.current) rf.current.setViewport(start.view); }, [startKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const touch = useRef(false); // the last pointer was a finger: a first tap explains, a second one opens
  const tapped = useRef<string | null>(null);

  const click = (n: GraphNode) => {
    if (n.action?.kind === "expand" || (shown.groups[n.id] && isBox(n))) {
      setOpen((m) => new Map(m).set(n.id, n.sub ? `${n.label} · ${n.sub}` : n.label));
      setHover(null);
      setTip(null);
      return;
    }
    onNodeClick?.(n);
  };
  const place = (ev: React.MouseEvent, text: string) => {
    const r = box.current?.getBoundingClientRect();
    if (!r || !text) return setTip(null);
    const x = ev.clientX - r.left;
    setTip({ text, x: x > r.width - 300 ? x - 296 : x + 14, y: ev.clientY - r.top + 14 });
  };
  const nodeTip = (n: GraphNode) => {
    const grp = shown.groups[n.id];
    return [n.name === n.label || isBox(n) ? n.label : n.name, isBox(n) ? n.sub : KIND_LABEL[n.kind] ?? n.raw_kind ?? n.kind,
      n.badge && isBox(n) ? `By grants: ${n.badge}` : "", isBox(n) ? "" : n.tip,
      n.rules.length ? ["Rules broken (click the badge):", ...n.rules.map((r) => `  ${r.num} · ${r.severity} · ${r.title}`)].join("\n") : "",
      grp ? `Click to open${buckets(grp.nodes) ? ", grouped" : ""}` : ""]
      .filter(Boolean).join("\n");
  };
  const tapOrClick = (ev: React.MouseEvent, n: GraphNode) => {
    if (touch.current && tapped.current !== n.id) { tapped.current = n.id; setHover(n.id); place(ev, nodeTip(n)); return; }
    tapped.current = null;
    if (onRules && (ev.target as HTMLElement).closest(".ae-node-rules")) onRules(n.id); else click(n);
  };
  const keyNode = (ev: React.KeyboardEvent | React.FocusEvent, open: boolean) => {
    const el = (ev.target as HTMLElement).closest?.(".react-flow__node");
    const n = el && byId.get(el.getAttribute("data-id") ?? "");
    if (!n || !box.current) return;
    if (open) { ev.preventDefault(); click(n); return; }
    const r = el.getBoundingClientRect(), b = box.current.getBoundingClientRect();
    setHover(n.id);
    const x = r.right - b.left + 8;
    setTip({ text: nodeTip(n), x: x > b.width - 300 ? Math.max(4, r.left - b.left - 296) : x, y: r.top - b.top });
  };
  const drop = (id: string) => setOpen((m) => {
    const c = new Map(m);
    for (const k of c.keys()) if (k === id || k.startsWith(id + "/")) c.delete(k);
    return c;
  });

  return (
    <div className="ae-graph-wrap">
      <div className="ae-graph" ref={box} style={{ height, background: t.panel }} aria-busy={busy}
        onMouseLeave={() => { setHover(null); setTip(null); }}
        onPointerDown={(e) => { touch.current = e.pointerType === "touch"; }}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") keyNode(e, true); else if (e.key === "Escape") { setHover(null); setTip(null); } }}
        onFocus={(e) => keyNode(e, false)}>
        {lay && start && (
          <ReactFlow
            key={`${lay.width}:${lay.height}:${shown.nodes.length}`}
            nodes={nodes} edges={edges} nodeTypes={NODE_TYPES} edgeTypes={EDGE_TYPES}
            defaultViewport={start.view} fitViewOptions={{ padding: 0.04 }} minZoom={0.2} maxZoom={2}
            nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} nodesFocusable edgesFocusable={false}
            panOnScroll={false} zoomOnScroll={false} zoomOnPinch preventScrolling={false}
            proOptions={{ hideAttribution: true }}
            onInit={(i) => { rf.current = i; moved.current = false; }}
            onMoveStart={(ev) => { if (ev) moved.current = true; }}
            onNodeClick={(ev, node) => { if (node.type === "ae") tapOrClick(ev, (node.data as NData).n); }}
            onEdgeClick={(ev, edge) => { if (touch.current) { setHover(edge.id); place(ev, edgeTip((edge.data as EData).e, byId, shown.groups)); } }}
            onNodeMouseEnter={(ev, node) => { if (node.type === "ae") { setHover(node.id); place(ev, nodeTip((node.data as NData).n)); } }}
            onNodeMouseMove={(ev, node) => node.type === "ae" && place(ev, nodeTip((node.data as NData).n))}
            onNodeMouseLeave={() => { setHover(null); setTip(null); }}
            onEdgeMouseEnter={(ev, edge) => { setHover(edge.id); place(ev, edgeTip((edge.data as EData).e, byId, shown.groups)); }}
            onEdgeMouseMove={(ev, edge) => place(ev, edgeTip((edge.data as EData).e, byId, shown.groups))}
            onEdgeMouseLeave={() => { setHover(null); setTip(null); }}
          >
            <Controls showInteractive={false} position="bottom-right" />
          </ReactFlow>
        )}
        {pans && <div className="ae-graph-hint" style={{ color: t.muted }}>Drag to see the rest</div>}
        {busy && <div className="ae-graph-busy" role="status"><span className="ae-spin" aria-hidden />Laying out {shown.nodes.length} boxes…</div>}
        {tip && (
          <div className="ae-graph-tip" style={{ left: tip.x, top: tip.y, background: t.ink, color: t.panel }}>
            {tip.text.split("\n").map((l, i) => <div key={i} className={i ? "" : "ae-graph-tip-head"}>{l}</div>)}
          </div>
        )}
      </div>
      {open.size > 0 && (
        <div className="ae-graph-open">
          Opened:
          {[...open].map(([id, label]) => (
            <button key={id} className="ae-chip" onClick={() => drop(id)} title="Fold again">
              {label} <span aria-hidden>×</span>
            </button>
          ))}
        </div>
      )}
      {graph.note && <div className="ae-graph-note">{graph.note}</div>}
      {legend && <Legend legend={mergeLegend(shown)} theme={theme} severities={SEVERITY_ORDER.filter((v: string) => shown.nodes.some((n) => n.rules.some((r) => r.severity === v)))} />}
    </div>
  );
}

function mergeLegend(g: G): G["legend"] {
  const kinds = [...new Set([...g.legend.kinds, ...g.nodes.map((n) => (n.group && !GROUP_KINDS.has(n.kind) ? "fold" : n.kind))])];
  const edges = [...new Set([...g.legend.edges, ...g.edges.map((e) => e.cls)])];
  const marks = [...new Set([...g.legend.marks, ...g.nodes.flatMap((n) => n.marks)])];
  return { ...g.legend, kinds, edges, marks, rules: g.legend.rules || g.nodes.some((n) => n.rules.length > 0), back: g.edges.some((e) => e.back) };
}

function toFlow(g: G, lay: Layout | null, t: Tokens, hot: Set<string> | null, focus: string | null, hi: Set<string> | undefined,
  flow: boolean): { nodes: Node[]; edges: Edge[] } {
  if (!lay) return { nodes: [], edges: [] };
  const nodes: Node[] = lay.lanes.map((l) => ({
    id: `lane:${l.index}:label`, type: "lane", position: { x: l.x, y: 0 }, data: { label: l.label, w: l.w, t },
    selectable: false, draggable: false, style: { width: l.w },
  }));
  for (const n of g.nodes) {
    const p = lay.nodes.get(n.id);
    if (!p) continue;
    nodes.push({
      id: n.id, type: "ae", position: { x: p.x, y: p.y }, width: p.w, height: p.h,
      ariaLabel: `${n.name === n.label ? n.label : n.name}, ${KIND_LABEL[n.kind] ?? n.kind}${n.action || g.groups[n.id] ? ": Enter opens it" : ""}`,
      data: { n, t, lines: nodeSize(n).lines, subs: nodeSize(n).subs, selected: (focus ?? g.selected) === n.id, dim: !!hot && !hot.has(n.id), red: !!hi?.has(n.id) } satisfies NData,
    });
  }
  const edges: Edge[] = g.edges.filter((e) => lay.nodes.has(e.source) && lay.nodes.has(e.target)).map((e) => ({
    id: e.id, source: e.source, target: e.target, type: "ae",
    data: { e, t, pts: lay.routes.get(e.id), at: lay.labels.get(e.id), dim: !!hot && !hot.has(e.id), hot: !!hot?.has(e.id), red: !!hi?.has(e.id), flow } satisfies EData,
  }));
  return { nodes, edges };
}

function LaneLabel({ data }: NodeProps) {
  const d = data as { label: string; w: number; t: Tokens };
  return <div className="ae-lane" style={{ width: d.w, color: d.t.muted, borderColor: d.t.line }}>{d.label}</div>;
}

function AeNode({ data }: NodeProps) {
  const { n, t, lines, subs, selected, dim, red } = data as NData;
  const bad = n.kind === "admin" || n.marks.includes("bad");
  const s = kindStyle(t, bad ? "admin" : n.kind);
  const group = isBox(n) || n.marks.includes("stack");
  const dbRole = n.kind === "database_role";
  const style: React.CSSProperties = {
    background: dbRole ? "transparent" : s.bg, color: s.text, borderColor: s.border,
    borderStyle: dbRole ? "none" : s.dash, borderWidth: dbRole ? 0 : 1.5,
    borderRadius: s.radius, opacity: dim ? 0.2 : n.marks.includes("disabled") ? 0.6 : 1,
    outline: selected ? `2px solid ${t.accent}` : red ? `2px solid ${t.bad_ink}` : undefined, outlineOffset: 3,
    // a combined box is a small stack of cards
    boxShadow: group ? `4px 4px 0 -1.5px ${s.bg}, 4px 4px 0 0 ${s.border}, 8px 8px 0 -1.5px ${s.bg}, 8px 8px 0 0 ${s.border}` : undefined,
  };
  return (
    <div className={`ae-node ae-node-${n.kind}${group ? " ae-node-box" : ""}`} style={style}>
      {dbRole && <DbRoleShape s={s} />}
      <Handle type="target" position={Position.Left} className="ae-handle" />
      <div className="ae-node-label" style={{ textDecoration: n.marks.includes("disabled") ? "line-through" : undefined }}>
        {n.marks.includes("sensitive") && <Lock color={t.bad_ink} />}
        {lines.map((l, i) => <div key={i}>{l}</div>)}
      </div>
      {subs.map((l, i) => <div key={i} className="ae-node-sub" style={{ color: dbRole ? s.border : t.muted }}>{l}</div>)}
      {badgeLines(n.badge).map((l, i) => <div key={i} className="ae-node-badge" style={{ color: group ? s.text : t.muted }}>{l}</div>)}
      {n.rules.length > 0 && (() => {
        const worst = SEV.find((v) => n.rules.some((r) => r.severity === v)) ?? "Low";
        return <span className={`ae-node-rules ae-sevpill ae-sev-${worst}`}>{worst} · {n.rules.length}</span>;
      })()}
      <Handle type="source" position={Position.Right} className="ae-handle" />
    </div>
  );
}

/** Database role: grey-blue box with a folded tab corner (top right). */
function DbRoleShape({ s }: { s: { bg: string; border: string } }) {
  return (
    <svg className="ae-dbrole" preserveAspectRatio="none" viewBox="0 0 100 100" aria-hidden>
      <path d="M2 2 H86 L98 14 V98 H2 Z" fill={s.bg} stroke={s.border} strokeWidth="2" vectorEffect="non-scaling-stroke" />
      <path d="M86 2 V14 H98" fill="none" stroke={s.border} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Lock({ color }: { color: string }) {
  return (
    <svg className="ae-lock" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2.4" aria-label="sensitive">
      <rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" />
    </svg>
  );
}

function AeEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data }: EdgeProps) {
  const { e, t, pts, at, dim, hot, red, flow } = data as EData;
  const cls = e.back ? "back" : e.cls;
  const [, w0, dash, double] = EDGE[cls] ?? EDGE.inherit;
  const w = (hot ? w0 + 1 : w0) + (flow && (e.count ?? 0) > 1 ? Math.min(4, Math.log2(e.count ?? 1)) : 0);
  const color = red ? t.bad_ink : edgeColor(t, cls);
  // back edges (to an earlier lane) are not routed by ELK: a rounded step line
  const [path, lx, ly] = pts ? [roundPath(pts), at?.x ?? 0, at?.y ?? 0]
    : getSmoothStepPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, borderRadius: 8, offset: 18 });
  const op = dim ? 0.12 : 1;
  return (
    <g style={{ opacity: op, transition: "opacity .15s" }}>
      {double ? (
        <>
          <BaseEdge id={id} path={path} style={{ stroke: color, strokeWidth: w + 2, strokeDasharray: dash }} />
          <path d={path} fill="none" stroke={t.panel} strokeWidth={Math.max(1, w - 1.5)} strokeDasharray={dash} />
        </>
      ) : (
        <BaseEdge id={id} path={path} style={{ stroke: color, strokeWidth: w, strokeDasharray: dash }} />
      )}
      {(e.count ?? 0) > 1 && (
        <EdgeLabelRenderer>
          <div className="ae-edge-label"
            style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)`, color, background: t.panel, borderColor: color, opacity: op }}>
            {e.count}
          </div>
        </EdgeLabelRenderer>
      )}
    </g>
  );
}

const NODE_TYPES = { ae: AeNode, lane: LaneLabel };
const EDGE_TYPES = { ae: AeEdge };
