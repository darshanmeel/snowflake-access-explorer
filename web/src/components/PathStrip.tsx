// A path as one line of chips styled like graph nodes; long middles fold to "⋯ 7 roles ⋯". A click opens a small
// wrapping diagram with depths (user 0, then 1, 2 ... up to the grant holder) and a link per box; "+N more" steps
// through the other paths.
import { Fragment, useState } from "react";
import { normKind } from "./graphs";

export interface PathStripProps {
  path: string[];
  kinds?: Record<string, string>;
  onOpen?: (id: string) => void;
  more?: string[][]; // other paths of the same row
  cls?: string | null; // access on the last step: read / write / own / use / manage (colours the last arrow)
  grants?: string[]; // privileges on the last step (hover)
}

/** Steps shown collapsed, as indexes into path; {fold: n} stands for n hidden roles. Short paths show whole; long
 * ones keep the first 2 steps, the last role and the object. */
export function foldPath(path: string[]): (number | { fold: number })[] {
  const n = path.length;
  return n <= 5 ? path.map((_, i) => i) : [0, 1, { fold: n - 4 }, n - 2, n - 1];
}

const kindOf = (kinds: Record<string, string>, path: string[], i: number) =>
  normKind(kinds[path[i]] ?? (i === path.length - 1 ? "object" : i === 0 && path.length > 1 ? "user" : undefined));

const label = (id: string) => id.replace(/ \(user\)$/, "");

export function PathStrip({ path, kinds = {}, onOpen, more = [], cls, grants }: PathStripProps) {
  const [open, setOpen] = useState(false);
  const [at, setAt] = useState(0);
  const all = [path, ...more];
  const p = all[at] ?? path;
  if (!p.length) return null;
  const tip = p.map(label).join(" › ") + (grants?.length ? `\n${grants.join(", ")}` : "");
  if (!open)
    return (
      <button className="ae-ps" title={tip} onClick={() => setOpen(true)}>
        {foldPath(p).map((x, i) => (
          <Fragment key={i}>
            {i > 0 && <span className="ae-ps-arrow" aria-hidden>›</span>}
            {typeof x === "number"
              ? <span className={`ae-ps-chip ae-chip-${kindOf(kinds, p, x)}`}>{label(p[x])}</span>
              : <span className="ae-ps-fold">⋯ {x.fold} roles ⋯</span>}
          </Fragment>
        ))}
        {all.length > 1 && <span className="ae-ps-more">+{all.length - 1}</span>}
      </button>
    );
  return (
    <div className="ae-ps-open">
      <div className="ae-ps-flow">
        {p.map((id, i) => (
          <Fragment key={i}>
            {i > 0 && (
              <span className={`ae-ps-link${i === p.length - 1 && cls ? ` ae-e-${cls}` : ""}`}
                title={i === p.length - 1 && grants?.length ? grants.join(", ") : undefined}>→</span>
            )}
            <button className={`ae-ps-box ae-chip-${kindOf(kinds, p, i)}`} title={label(id)} onClick={() => onOpen?.(id)} disabled={!onOpen}>
              <span className="ae-ps-depth">{i === p.length - 1 ? "obj" : i}</span>{label(id)}
            </button>
          </Fragment>
        ))}
      </div>
      <div className="ae-ps-tools">
        {all.length > 1 && <button className="ae-link" onClick={() => setAt((at + 1) % all.length)}>path {at + 1} of {all.length} · next</button>}
        <button className="ae-link" onClick={() => setOpen(false)}>fold</button>
      </div>
    </div>
  );
}
