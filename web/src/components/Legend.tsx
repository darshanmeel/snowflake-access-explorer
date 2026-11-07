// Legend for a lane graph: box kinds, line styles, marks. Always drawn next to a graph.
import type { Graph } from "../api/types";
import { EDGE, KIND_LABEL, PCLASS, TOKENS, edgeColor, kindStyle, type ThemeName } from "./theme";
import { GROUP_KINDS } from "./graphs";

const MARK_LABEL: Record<string, string> = { sensitive: "Sensitive", disabled: "Disabled user", bad: "Admin / finding", stack: "Stacked: same path" };

export function Legend({ legend, theme = "light" }: { legend: Graph["legend"]; theme?: ThemeName }) {
  const t = TOKENS[theme];
  // database roles are new to most readers: their box and line are in every legend
  const kinds = [...new Set([...legend.kinds, "database_role"])];
  const edges = [...new Set([...legend.edges, "inherit", "inherit_db"])];
  return (
    <div className="ae-legend" style={{ color: t.muted }}>
      {kinds.map((k) => {
        const s = kindStyle(t, k);
        const group = GROUP_KINDS.has(k);
        return (
          <span key={k} className="ae-legend-item">
            {k === "database_role" ? (
              <svg width="22" height="14" viewBox="0 0 22 14" aria-hidden>
                <path d="M1 1 H16 L21 6 V13 H1 Z" fill={s.bg} stroke={s.border} strokeWidth="1.3" />
                <path d="M16 1 V6 H21" fill="none" stroke={s.border} strokeWidth="1" />
              </svg>
            ) : (
              <span className="ae-swatch" style={{
                background: s.bg, borderColor: s.border, borderStyle: s.dash, borderWidth: 1.5,
                borderRadius: k === "user" ? 999 : k === "object" ? "6px / 5px" : 3,
                boxShadow: group ? `2px 2px 0 -1px ${s.bg}, 2px 2px 0 0 ${s.border}, 4px 4px 0 -1px ${s.bg}, 4px 4px 0 0 ${s.border}` : undefined,
                width: group ? 18 : undefined, height: group ? 10 : undefined, marginRight: group ? 4 : undefined,
              }} />
            )}
            {KIND_LABEL[k] ?? k}
          </span>
        );
      })}
      {edges.map((c) => <EdgeSample key={c} cls={c} label={PCLASS[c] ?? c} theme={theme} />)}
      <EdgeSample cls="back" label={PCLASS.back} theme={theme} />
      {legend.marks.map((m) => <span key={m} className="ae-legend-item">{MARK_LABEL[m] ?? m}</span>)}
      {legend.rules && <span className="ae-legend-item">{["Critical", "High", "Medium", "Low"].map((v) => <span key={v} className={`ae-sevpill ae-sev-${v}`}>{v}</span>)} rules broken (click opens them)</span>}
    </div>
  );
}

function EdgeSample({ cls, label, theme }: { cls: string; label: string; theme: ThemeName }) {
  const t = TOKENS[theme];
  const [, w, dash, double] = EDGE[cls] ?? EDGE.inherit;
  const color = edgeColor(t, cls);
  return (
    <span className="ae-legend-item">
      <svg width="30" height="12" viewBox="0 0 30 12" aria-hidden>
        <line x1="1" y1="6" x2="29" y2="6" stroke={color} strokeWidth={double ? w + 2 : w} strokeDasharray={dash} />
        {double && <line x1="1" y1="6" x2="29" y2="6" stroke={t.panel} strokeWidth={Math.max(1, w - 1.5)} strokeDasharray={dash} />}
      </svg>
      {label}
    </span>
  );
}
