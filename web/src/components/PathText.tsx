// A path as names joined by arrows; wraps between names, each name coloured by its kind.
import { Fragment } from "react";
import { normKind } from "./graphs";

export function PathText({ path, kinds = {}, onOpen }: { path: string[]; kinds?: Record<string, string>; onOpen?: (id: string) => void }) {
  return (
    <span className="ae-path" title={path.join(" > ")}>
      {path.map((id, i) => (
        <Fragment key={i}>
          {i > 0 && <span className="ae-path-arrow" aria-hidden>›</span>}
          {onOpen
            ? <button className={`ae-path-name ae-k-${normKind(kinds[id] ?? (i === path.length - 1 ? "object" : undefined))}`} onClick={() => onOpen(id)}>{id}</button>
            : <span className={`ae-path-name ae-k-${normKind(kinds[id])}`}>{id}</span>}
        </Fragment>
      ))}
    </span>
  );
}
