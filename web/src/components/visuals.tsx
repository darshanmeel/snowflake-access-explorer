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
