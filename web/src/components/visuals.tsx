// Small drawings shared by the screens: the Compare overlap, a grant as two boxes and a + / - link (What changed),
// a path with the link a change cuts crossed out (What if, change plan). Plain SVG / CSS on the --ae-* variables.
import { useState, type ReactNode } from "react";

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

/** Queries per day as stacked HTML bars (fixed-size text at any width), one colour per key (most first, the rest as
 * Other), weekends shaded, the average day dashed. Above it a readout: the hovered or pinned day (else the whole window)
 * with each key's count; click a key to show only it. Click a day to pin it (again to unpin). lanes: labelled rows under
 * the chart with a mark on the days something happened (a DDL, a person writing, ...). */
export function DayStack({ first, series, label, pinned = null, onPin, focus = null, onFocus, lanes = [], top: most = SERIES.length, colors }: {
  first: string; series: { key: string; values: number[] }[]; label: string; pinned?: number | null; onPin?: (i: number | null) => void;
  focus?: string | null; onFocus?: (key: string | null) => void; lanes?: { label: string; color: string; days: boolean[] }[];
  top?: number; colors?: string[]; // top: keys drawn before Other; colors: one per key instead of the palette
}) {
  const [hover, setHover] = useState<number | null>(null);
  const top = series.slice(0, most);
  const rest = series.slice(most);
  const parts = rest.length ? [...top, { key: `Other (${rest.length})`, values: top[0].values.map((_, i) => rest.reduce((n, s) => n + s.values[i], 0)) }] : top;
  const n = parts[0]?.values.length ?? 0;
  const tot = Array.from({ length: n }, (_, i) => parts.reduce((s, p) => s + p.values[i], 0));
  const max = Math.max(1, ...tot);
  const avg = tot.reduce((a, v) => a + v, 0) / Math.max(1, n);
  const day = (i: number) => new Date(Date.parse(first) + i * 864e5);
  const short = (i: number) => day(i).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
  const weekend = (i: number) => [0, 6].includes(day(i).getUTCDay());
  const color = (k: number) => k < top.length ? (colors?.[k] ?? `var(--ae-${SERIES[k % SERIES.length]})`) : "var(--ae-line_strong)";
  const show = hover ?? pinned;
  const sum = (p: { values: number[] }) => (show == null ? p.values.reduce((a, v) => a + v, 0) : p.values[show]);
  const cols = { gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))` };
  const pin = (i: number) => onPin?.(pinned === i ? null : i);
  const bg = (i: number) => (i === pinned ? "var(--ae-accent_soft)" : i === hover ? "var(--ae-sunk)" : weekend(i) ? "var(--ae-bg)" : undefined);
  return (
    <figure className="ae-ds" aria-label={`${label}: queries per day, ${n} days, most ${max} on one day, ${Math.round(avg)} on an average day`}>
      <div className="ae-ds-read">
        <b>{show == null ? `All ${n} days · ${tot.reduce((a, v) => a + v, 0)} queries` : `${day(show).toISOString().slice(0, 10)}${weekend(show) ? " (weekend)" : ""} · ${tot[show]} queries`}</b>
        <span className="ae-muted">{hover != null ? (hover === pinned ? "pinned" : onPin ? "click to pin" : "") : pinned != null ? "pinned · the table shows this day" : `${short(0)} – ${short(n - 1)} · average ${Math.round(avg)} a day`}</span>
        {pinned != null && onPin && <button type="button" className="ae-link" onClick={() => onPin(null)}>Clear day</button>}
        {focus && onFocus && <button type="button" className="ae-link" onClick={() => onFocus(null)}>Show all</button>}
      </div>
      <div className="ae-ds-keys">
        {parts.map((p, k) => {
          const body = <><i style={{ background: color(k) }} /><span className="ae-mono">{p.key}</span><b>{sum(p)}</b></>;
          return onFocus && k < top.length
            ? <button type="button" key={p.key} className={focus && focus !== p.key ? "off" : ""} aria-pressed={focus === p.key} onClick={() => onFocus(focus === p.key ? null : p.key)}>{body}</button>
            : <span key={p.key}>{body}</span>;
        })}
      </div>
      <div className="ae-ds-plot" onMouseLeave={() => setHover(null)}>
        <div className="ae-ds-y"><span>{max}</span><span>{Math.round((max * 2) / 3)}</span><span>{Math.round(max / 3)}</span><span>0</span></div>
        <div className="ae-ds-area">
          <div className="ae-ds-grid" />
          <div className="ae-ds-avg" style={{ bottom: `${(avg / max) * 100}%` }}><span>avg {Math.round(avg)}/day</span></div>
          <div className="ae-ds-cols" style={cols}>
            {tot.map((t, i) => (
              <div key={i} className="ae-ds-col" style={{ background: bg(i) }} onMouseEnter={() => setHover(i)} onClick={() => pin(i)}
                title={`${day(i).toISOString().slice(0, 10)}: ${t} quer${t === 1 ? "y" : "ies"}`}>
                {parts.map((p, k) => p.values[i] ? (
                  <div key={k} style={{ height: `${(p.values[i] / max) * 100}%`, background: color(k), opacity: focus && focus !== p.key ? 0.15 : 1 }} />
                ) : null)}
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="ae-ds-x" style={cols}>
        <span style={{ gridColumn: "1 / span 12" }}>{short(0)}</span>
        {n > 30 && <span style={{ gridColumn: `${Math.floor(n / 2) - 4} / span 10`, textAlign: "center" }}>{short(Math.floor(n / 2))}</span>}
        <span style={{ gridColumn: `${Math.max(1, n - 11)} / span 12`, textAlign: "right" }}>{short(n - 1)}</span>
      </div>
      {lanes.length > 0 && (
        <div className="ae-ds-lanes">
          {lanes.map((l) => (
            <div key={l.label}>
              <div className="ae-ds-lane-h"><i style={{ background: l.color }} />{l.label}<span className="ae-muted">{l.days.filter(Boolean).length} days</span></div>
              <div className="ae-ds-lane" style={cols}>
                {l.days.map((on, i) => (
                  <div key={i} style={{ background: bg(i) }} onMouseEnter={() => setHover(i)} onClick={() => pin(i)}>{on && <i style={{ background: l.color }} />}</div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </figure>
  );
}
