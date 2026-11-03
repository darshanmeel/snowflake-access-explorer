// Lane graph: ELK lays it out (one lane per depth, left to right, orthogonal bundled lines), React Flow draws it.
// Crowded lanes fold (database roles per database, group roles); folded and combined boxes open on click, big ones
// by schema / type first. Hover shows what a box or line is in words and lights up every path through it.
import { useEffect, useMemo, useRef, useState } from "react";
import {
  BaseEdge, EdgeLabelRenderer, Handle, Position, ReactFlow, Controls, getSmoothStepPath,
  type Edge, type EdgeProps, type Node, type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Graph as G, GraphEdge, GraphNode } from "../api/types";
import { EDGE, KIND_LABEL, TOKENS, edgeColor, kindStyle, type ThemeName, type Tokens } from "./theme";
import { GROUP_KINDS, buckets, edgeTip, expand, foldRoles, related } from "./graphs";
import { layout, nodeSize, roundPath, type Layout, type Pt } from "./layout";
import { Legend } from "./Legend";

export interface GraphProps {
  graph: G;
  theme?: ThemeName;
  onNodeClick?: (n: GraphNode) => void;
  onRules?: (id: string) => void; // a click on a box's rule badge
  legend?: boolean;
  maxHeight?: number;
  minZoom?: number; // never drawn smaller than this (labels stay readable): wider graphs pan sideways instead
}

const SEV = ["Critical", "High", "Medium", "Low"] as const;

type NData = { n: GraphNode; t: Tokens; lines: string[]; selected: boolean; dim: boolean };
type EData = { e: GraphEdge; t: Tokens; pts?: Pt[]; at?: Pt; dim: boolean; hot: boolean };
type Tip = { text: string; x: number; y: number };

const PAD = 16;
const isBox = (n: GraphNode) => !!n.group || GROUP_KINDS.has(n.kind);

export function Graph({ graph, theme = "light", onNodeClick, onRules, legend = true, maxHeight = 640, minZoom = 0.8 }: GraphProps) {
  const t = TOKENS[theme];
  const [open, setOpen] = useState<Map<string, string>>(new Map()); // opened box -> its label (for the chips)
  useEffect(() => setOpen(new Map()), [graph]);
  const folded = useMemo(() => foldRoles(graph), [graph]);
  const shown = useMemo(() => expand(folded, new Set(open.keys())), [folded, open]);
  const [lay, setLay] = useState<Layout | null>(null);
  useEffect(() => {
    let live = true;
    layout(shown).then((l) => live && setLay(l));
    return () => { live = false; };
  }, [shown]);

  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  useEffect(() => {
    if (!box.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width || 800));
    ro.observe(box.current);
    return () => ro.disconnect();
  }, []);

  const [hover, setHover] = useState<string | null>(null);
  const [tip, setTip] = useState<Tip | null>(null);
  const hot = useMemo(() => (hover ? related(shown, hover) : null), [shown, hover]);
  const byId = useMemo(() => new Map(shown.nodes.map((n) => [n.id, n])), [shown]);
  const { nodes, edges } = useMemo(() => toFlow(shown, lay, t, hot), [shown, lay, t, hot]);

  // drawn at the zoom that fits the width, never below minZoom; the panel is as tall as the drawing
  const zoom = lay ? Math.max(minZoom, Math.min(1, (width - 2 * PAD) / Math.max(1, lay.width))) : 1;
  const height = lay ? Math.min(maxHeight, Math.ceil(lay.height * zoom + 2 * PAD)) : 120;
  const pans = !!lay && (lay.width * zoom > width - 2 * PAD || lay.height * zoom + 2 * PAD > maxHeight);
  const vx = lay ? Math.max(PAD, (width - lay.width * zoom) / 2) : PAD;

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
  const drop = (id: string) => setOpen((m) => {
    const c = new Map(m);
    for (const k of c.keys()) if (k === id || k.startsWith(id + "/")) c.delete(k);
    return c;
  });

  return (
    <div className="ae-graph-wrap">
      <div className="ae-graph" ref={box} style={{ height, background: t.panel }} onMouseLeave={() => { setHover(null); setTip(null); }}>
        {lay && (
          <ReactFlow
            key={`${lay.width}:${lay.height}:${shown.nodes.length}:${Math.round(width / 40)}`}
            nodes={nodes} edges={edges} nodeTypes={NODE_TYPES} edgeTypes={EDGE_TYPES}
            defaultViewport={{ x: vx, y: PAD, zoom }} fitViewOptions={{ padding: 0.04 }} minZoom={0.2} maxZoom={2}
            nodesDraggable={false} nodesConnectable={false} elementsSelectable={false}
            panOnScroll={false} zoomOnScroll={false} zoomOnPinch preventScrolling={false}
            proOptions={{ hideAttribution: true }}
            onNodeClick={(ev, node) => { if (node.type !== "ae") return; const n = (node.data as NData).n;
              if (onRules && (ev.target as HTMLElement).closest(".ae-node-rules")) onRules(n.id); else click(n); }}
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
      {legend && <Legend legend={mergeLegend(shown)} theme={theme} />}
    </div>
  );
}

function mergeLegend(g: G): G["legend"] {
  const kinds = [...new Set([...g.legend.kinds, ...g.nodes.map((n) => (n.group && !GROUP_KINDS.has(n.kind) ? "fold" : n.kind))])];
  const edges = [...new Set([...g.legend.edges, ...g.edges.map((e) => e.cls)])];
  const marks = [...new Set([...g.legend.marks, ...g.nodes.flatMap((n) => n.marks)])];
  return { ...g.legend, kinds, edges, marks, rules: g.legend.rules || g.nodes.some((n) => n.rules.length > 0) };
}

function toFlow(g: G, lay: Layout | null, t: Tokens, hot: Set<string> | null): { nodes: Node[]; edges: Edge[] } {
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
      data: { n, t, lines: nodeSize(n).lines, selected: g.selected === n.id, dim: !!hot && !hot.has(n.id) } satisfies NData,
    });
  }
  const edges: Edge[] = g.edges.filter((e) => lay.nodes.has(e.source) && lay.nodes.has(e.target)).map((e) => ({
    id: e.id, source: e.source, target: e.target, type: "ae",
    data: { e, t, pts: lay.routes.get(e.id), at: lay.labels.get(e.id), dim: !!hot && !hot.has(e.id), hot: !!hot?.has(e.id) } satisfies EData,
  }));
  return { nodes, edges };
}

function LaneLabel({ data }: NodeProps) {
  const d = data as { label: string; w: number; t: Tokens };
  return <div className="ae-lane" style={{ width: d.w, color: d.t.muted, borderColor: d.t.line }}>{d.label}</div>;
}

function AeNode({ data }: NodeProps) {
  const { n, t, lines, selected, dim } = data as NData;
  const bad = n.kind === "admin" || n.marks.includes("bad");
  const s = kindStyle(t, bad ? "admin" : n.kind);
  const group = isBox(n);
  const dbRole = n.kind === "database_role";
  const style: React.CSSProperties = {
    background: dbRole ? "transparent" : s.bg, color: s.text, borderColor: s.border,
    borderStyle: dbRole ? "none" : s.dash, borderWidth: dbRole ? 0 : 1.5,
    borderRadius: s.radius, opacity: dim ? 0.2 : n.marks.includes("disabled") ? 0.6 : 1,
    outline: selected ? `2px solid ${t.accent}` : undefined, outlineOffset: 3,
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
      {n.sub && <div className="ae-node-sub" style={{ color: dbRole ? s.border : t.muted }}>{n.sub}</div>}
      {n.badge && <div className="ae-node-badge" style={{ color: group ? s.text : t.muted }}>{n.badge}</div>}
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
  const { e, t, pts, at, dim, hot } = data as EData;
  const cls = e.back ? "back" : e.cls;
  const [, w0, dash, double] = EDGE[cls] ?? EDGE.inherit;
  const w = hot ? w0 + 1 : w0;
  const color = edgeColor(t, cls);
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
