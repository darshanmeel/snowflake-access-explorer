// Lane graph: React Flow draws, ELK orders, one lane per depth left to right. Combined boxes expand on click.
import { useEffect, useMemo, useRef, useState } from "react";
import {
  BaseEdge, EdgeLabelRenderer, Handle, Position, ReactFlow, Controls, getBezierPath,
  type Edge, type EdgeProps, type Node, type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Graph as G, GraphEdge, GraphNode } from "../api/types";
import { EDGE, KIND_LABEL, PCLASS, TOKENS, edgeColor, kindStyle, type ThemeName, type Tokens } from "./theme";
import { GROUP_KINDS, expand } from "./graphs";
import { layout, nodeSize, type Layout } from "./layout";
import { Legend } from "./Legend";

export interface GraphProps {
  graph: G;
  theme?: ThemeName;
  onNodeClick?: (n: GraphNode) => void;
  legend?: boolean;
  maxHeight?: number;
  minZoom?: number; // below this the graph scrolls (pans) instead of shrinking further
}

type NData = { n: GraphNode; t: Tokens; lines: string[]; selected: boolean; open: boolean };
type EData = { e: GraphEdge; t: Tokens };

export function Graph({ graph, theme = "light", onNodeClick, legend = true, maxHeight = 640, minZoom = 0.45 }: GraphProps) {
  const t = TOKENS[theme];
  const [open, setOpen] = useState<Set<string>>(new Set());
  useEffect(() => setOpen(new Set()), [graph]);
  const shown = useMemo(() => expand(graph, open), [graph, open]);
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

  const { nodes, edges } = useMemo(() => toFlow(shown, lay, t, open), [shown, lay, t, open]);
  const zoom = lay ? Math.max(minZoom, Math.min(1, (width - 24) / Math.max(1, lay.width))) : 1;
  const height = lay ? Math.min(maxHeight, Math.max(140, lay.height * zoom + 28)) : 160;

  const click = (n: GraphNode) => {
    if (n.action?.kind === "expand" || (graph.groups[n.id] && GROUP_KINDS.has(n.kind))) {
      setOpen((s) => new Set(s).add(n.id));
      return;
    }
    onNodeClick?.(n);
  };
  const openIds = [...open].filter((id) => graph.groups[id]);

  return (
    <div className="ae-graph-wrap">
      <div className="ae-graph" ref={box} style={{ height, background: t.panel }}>
        {lay && (
          <ReactFlow
            key={`${shown.nodes.length}:${shown.edges.length}:${Math.round(width / 50)}`}
            nodes={nodes} edges={edges} nodeTypes={NODE_TYPES} edgeTypes={EDGE_TYPES}
            fitView fitViewOptions={{ padding: 0.04, maxZoom: 1, minZoom }} minZoom={0.2} maxZoom={2}
            nodesDraggable={false} nodesConnectable={false} elementsSelectable={false}
            panOnScroll={false} zoomOnScroll={false} zoomOnPinch preventScrolling={false}
            proOptions={{ hideAttribution: true }}
            onNodeClick={(_, node) => node.type === "ae" && click((node.data as NData).n)}
          >
            <Controls showInteractive={false} position="bottom-right" />
          </ReactFlow>
        )}
      </div>
      {openIds.length > 0 && (
        <div className="ae-graph-open">
          Expanded:
          {openIds.map((id) => (
            <button key={id} className="ae-chip" onClick={() => setOpen((s) => { const c = new Set(s); c.delete(id); return c; })}
              title="Combine again">
              {graph.groups[id].label} <span aria-hidden>×</span>
            </button>
          ))}
        </div>
      )}
      {graph.note && <div className="ae-graph-note">{graph.note}</div>}
      {legend && <Legend legend={shown.legend.kinds.length ? mergeLegend(shown) : graph.legend} theme={theme} />}
    </div>
  );
}

function mergeLegend(g: G): G["legend"] {
  const kinds = [...new Set([...g.legend.kinds, ...g.nodes.map((n) => n.kind)])];
  const edges = [...new Set([...g.legend.edges, ...g.edges.map((e) => e.cls)])];
  return { ...g.legend, kinds, edges };
}

function toFlow(g: G, lay: Layout | null, t: Tokens, open: Set<string>): { nodes: Node[]; edges: Edge[] } {
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
      data: { n, t, lines: nodeSize(n).lines, selected: g.selected === n.id, open: open.has(n.id) } satisfies NData,
    });
  }
  const edges: Edge[] = g.edges.map((e) => ({ id: e.id, source: e.source, target: e.target, type: "ae", data: { e, t } satisfies EData }));
  return { nodes, edges };
}

function LaneLabel({ data }: NodeProps) {
  const d = data as { label: string; w: number; t: Tokens };
  return <div className="ae-lane" style={{ width: d.w, color: d.t.muted, borderColor: d.t.line }}>{d.label}</div>;
}

function AeNode({ data }: NodeProps) {
  const { n, t, lines, selected } = data as NData;
  const bad = n.kind === "admin" || n.marks.includes("bad");
  const s = kindStyle(t, bad ? "admin" : n.kind);
  const group = GROUP_KINDS.has(n.kind);
  const dbRole = n.kind === "database_role";
  const style: React.CSSProperties = {
    background: dbRole ? "transparent" : s.bg, color: s.text, borderColor: s.border,
    borderStyle: group ? "double" : dbRole ? "none" : s.dash, borderWidth: group ? 3 : dbRole ? 0 : 1.5,
    borderRadius: s.radius, opacity: n.marks.includes("disabled") ? 0.6 : 1,
    outline: selected ? `2px solid ${t.accent}` : undefined, outlineOffset: 2,
  };
  const tip = [n.name, KIND_LABEL[n.kind] ?? n.raw_kind ?? n.kind, n.tip, group ? "Click to expand" : ""].filter(Boolean).join("\n");
  return (
    <div className={`ae-node ae-node-${n.kind}`} style={style} title={tip}>
      {dbRole && <DbRoleShape s={s} />}
      <Handle type="target" position={Position.Left} className="ae-handle" />
      <div className="ae-node-label" style={{ textDecoration: n.marks.includes("disabled") ? "line-through" : undefined }}>
        {n.marks.includes("sensitive") && <Lock color={t.bad_ink} />}
        {lines.map((l, i) => <div key={i}>{l}</div>)}
      </div>
      {n.sub && <div className="ae-node-sub" style={{ color: dbRole ? s.border : t.muted }}>{group ? "+ " : ""}{n.sub}</div>}
      {n.badge && <div className="ae-node-badge" style={{ color: t.muted }}>{n.badge}</div>}
      {n.rules.length > 0 && (
        <div className="ae-node-rules">
          {n.rules.slice(0, 4).map((r) => (
            <span key={r.num} title={`Rule ${r.num}: ${r.title}`}
              style={{ background: r.severity === "High" ? t.bad_ink : r.severity === "Medium" ? t.warn_ink : t.low_ink, color: t.panel }}>
              {r.num}
            </span>
          ))}
        </div>
      )}
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
  const { e, t } = data as EData;
  const cls = e.back ? "back" : e.cls;
  const [, w, dash, double] = EDGE[cls] ?? EDGE.inherit;
  const color = edgeColor(t, cls);
  const [path, lx, ly] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const tip = [PCLASS[cls] ?? cls, e.privs.join(", "), e.count ? `${e.count} boxes` : "", e.has ? `Has: ${e.has.join(", ")}` : "",
    e.lacks ? `Lacks: ${e.lacks.join(", ")}` : "", ...e.rules.map((r) => `Rule ${r.num}: ${r.title}`)].filter(Boolean).join("\n");
  return (
    <>
      {double ? (
        <>
          <BaseEdge id={id} path={path} style={{ stroke: color, strokeWidth: w + 2, strokeDasharray: dash }} />
          <path d={path} fill="none" stroke={t.panel} strokeWidth={Math.max(1, w - 1.5)} strokeDasharray={dash} />
        </>
      ) : (
        <BaseEdge id={id} path={path} style={{ stroke: color, strokeWidth: w, strokeDasharray: dash }} />
      )}
      <path d={path} fill="none" stroke="transparent" strokeWidth={12}><title>{tip}</title></path>
      {(e.count ?? 0) > 1 && (
        <EdgeLabelRenderer>
          <div className="ae-edge-label" style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)`, color, background: t.panel, borderColor: color }}>
            {e.count}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const NODE_TYPES = { ae: AeNode, lane: LaneLabel };
const EDGE_TYPES = { ae: AeEdge };
