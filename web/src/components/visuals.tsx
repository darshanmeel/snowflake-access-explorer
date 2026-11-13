// Small drawings shared by the screens: the Compare overlap, a grant as two boxes and a + / - link (What changed),
// a path with the link a change cuts crossed out (What if, change plan). Plain SVG / CSS on the --ae-* variables.
import type { ReactNode } from "react";

/** Two circles: what only A has, what both have (different / the same), what only B has. */
export function Overlap({ a, b, onlyA, onlyB, different, same, onPick }: {
  a: string; b: string; onlyA: number; onlyB: number; different: number; same: number; onPick?: () => void;
}) {
  const go = onPick ? { role: "button", tabIndex: 0, onClick: onPick, onKeyDown: (e: React.KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(); } } } : {};
  const cut = (s: string) => (s.length > 22 ? s.slice(0, 21) + "…" : s);
  return (
    <figure className="ae-venn">
      <svg viewBox="0 0 400 176" role="img" aria-label={`Only ${a}: ${onlyA}. Both, different: ${different}. Both, the same: ${same}. Only ${b}: ${onlyB}.`}>
        <circle cx="158" cy="80" r="74" className="ae-venn-a" />
        <circle cx="242" cy="80" r="74" className="ae-venn-b" />
        <g {...go} className={onPick ? "ae-venn-hit" : undefined}>
          <text x="116" y="80" className="ae-venn-n ae-venn-na">{onlyA}</text>
          <text x="116" y="100" className="ae-venn-l">only A</text>
          <text x="200" y="58" className="ae-venn-n ae-venn-nd">{different}</text>
          <text x="200" y="73" className="ae-venn-l ae-venn-ls">different</text>
          <text x="200" y="102" className="ae-venn-n ae-venn-ns">{same}</text>
          <text x="200" y="117" className="ae-venn-l ae-venn-ls">same</text>
          <text x="284" y="80" className="ae-venn-n ae-venn-nb">{onlyB}</text>
          <text x="284" y="100" className="ae-venn-l">only B</text>
        </g>
        <text x="120" y="170" className="ae-venn-name ae-venn-na">A · {cut(a)}</text>
        <text x="280" y="170" className="ae-venn-name ae-venn-nb">B · {cut(b)}</text>
      </svg>
    </figure>
  );
}

/** A grant as two boxes and the link between them: + (added, solid) or - (removed, dashed and struck). */
export function GrantLink({ source, sourceKind, target, targetKind, privilege, added, onOpen }: {
  source: string; sourceKind: string; target: string; targetKind: string; privilege: string | null; added: boolean; onOpen?: (id: string) => void;
}) {
  const box = (id: string, kind: string) => (
    <button type="button" className={`ae-pchip ae-pchip-${kind === "object" ? "obj" : kind}`} onClick={() => onOpen?.(id)} title={id}>{id}</button>
  );
  return (
    <span className={`ae-glink ${added ? "ae-glink-add" : "ae-glink-del"}`} aria-label={`${added ? "Added" : "Removed"}: ${source} to ${target}${privilege ? `, ${privilege}` : ""}`}>
      {box(source, sourceKind)}
      <span className="ae-glink-line" aria-hidden>
        <span className="ae-glink-sign">{added ? "+" : "−"}</span>
        <span className="ae-glink-what">{privilege ?? "role"}</span>
      </span>
      {box(target, targetKind)}
    </span>
  );
}

/** A path left to right with the cut links (index i: path[i] -> path[i+1]) struck through in red. */
export function CutPath({ path, cuts, kinds, first, onOpen }: {
  path: string[]; cuts: Set<number>; kinds: Record<string, string>; first?: ReactNode; onOpen?: (id: string) => void;
}) {
  return (
    <span className="ae-cutpath">
      {path.map((n, i) => (
        <span key={i} className="ae-cutpath-step">
          {i > 0 && (cuts.has(i - 1)
            ? <span className="ae-cutpath-cut" title="The link this change removes"><span aria-hidden>✕</span><span className="ae-sr">cut</span></span>
            : <span className="ae-sep" aria-hidden>›</span>)}
          {i === 0 && first ? <span className="ae-pchip ae-pchip-user ae-cutpath-who">{first}</span>
            : <button type="button" className={`ae-pchip ae-pchip-${kinds[n] === "object" ? "obj" : kinds[n] ?? "plain"}`} onClick={() => onOpen?.(n)} title={n}>{n.replace(/ \(user\)$/, "")}</button>}
        </span>
      ))}
    </span>
  );
}

const SERIES = ["e_manage", "e_write", "warn_ink", "ok_ink", "e_read"]; // up to 5 keys, then "Other"

/** Queries per day as stacked bars, one colour per key (most first, the rest as Other), date axis and the top day. */
export function DayStack({ first, series, label }: { first: string; series: { key: string; values: number[] }[]; label: string }) {
  const top = series.slice(0, SERIES.length);
  const rest = series.slice(SERIES.length);
  const parts = rest.length ? [...top, { key: `Other (${rest.length})`, values: top[0].values.map((_, i) => rest.reduce((n, s) => n + s.values[i], 0)) }] : top;
  const n = parts[0]?.values.length ?? 0;
  const tot = Array.from({ length: n }, (_, i) => parts.reduce((s, p) => s + p.values[i], 0));
  const max = Math.max(1, ...tot), W = 600, H = 150, bw = W / Math.max(1, n);
  const date = (i: number) => new Date(Date.parse(first) + i * 864e5).toISOString().slice(0, 10);
  const color = (k: number) => k < SERIES.length ? `var(--ae-${SERIES[k]})` : "var(--ae-line_strong)";
  return (
    <figure className="ae-daystack">
      <svg viewBox={`0 0 ${W} ${H + 18}`} role="img" aria-label={`${label}: queries per day, ${n} days, most ${max} on one day`}>
        <line x1="0" x2={W} y1={H} y2={H} stroke="var(--ae-line)" />
        <line x1="0" x2={W} y1="0.5" y2="0.5" stroke="var(--ae-line)" strokeDasharray="3 3" />
        {tot.map((t, i) => {
          let y = H;
          return (
            <g key={i}>
              <title>{`${date(i)}: ${t} quer${t === 1 ? "y" : "ies"}\n${parts.filter((p) => p.values[i]).map((p) => `${p.key}: ${p.values[i]}`).join("\n")}`}</title>
              {parts.map((p, k) => {
                const h = (p.values[i] / max) * (H - 4);
                y -= h;
                return h > 0 ? <rect key={k} x={i * bw + 1} y={y} width={Math.max(1, bw - 2)} height={h} fill={color(k)} /> : null;
              })}
              <rect x={i * bw} y="0" width={bw} height={H} fill="transparent" />
            </g>
          );
        })}
        <text x="2" y="12" className="ae-daystack-ax">{max}</text>
        {[0, Math.floor(n / 2), n - 1].filter((i) => i >= 0).map((i, k) => (
          <text key={k} x={k === 0 ? 0 : k === 1 ? i * bw + bw / 2 : W} y={H + 14} textAnchor={k === 0 ? "start" : k === 1 ? "middle" : "end"} className="ae-daystack-ax">{date(i)}</text>
        ))}
      </svg>
      <figcaption className="ae-daystack-legend">
        {parts.map((p, k) => <span key={p.key}><i style={{ background: color(k) }} />{p.key}</span>)}
      </figcaption>
    </figure>
  );
}
