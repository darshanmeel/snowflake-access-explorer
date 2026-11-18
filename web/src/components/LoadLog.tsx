// What the app is doing while it loads: the server's progress lines (/api/progress), asked about once a second while
// `active`, shown in their own panel while `open` (the top bar's Log button). The last load's lines stay for a later
// look. Inside Streamlit, Python is busy during the load, so st_react.py writes the lines itself.
import { useEffect, useRef, useState } from "react";
import type { Progress } from "../api/types";

export function LoadLog({ active, open = true, onClose, poll, every = 1000 }:
  { active: boolean; open?: boolean; onClose?: () => void; poll: () => Promise<Progress | null>; every?: number }) {
  const [lines, setLines] = useState<Progress["lines"]>([]);
  const box = useRef<HTMLOListElement>(null);
  useEffect(() => {
    if (!active) return;
    let live = true, timer = 0;
    const tick = () => {
      timer = window.setTimeout(() => poll().then(
        (p) => { if (!live || !p) return; if (p.running) setLines(p.lines); tick(); },  // null: Streamlit, no polling
        () => live && tick(),
      ), every);
    };
    tick();
    return () => { live = false; clearTimeout(timer); };
  }, [active, poll, every]);
  useEffect(() => { const el = box.current; if (el) el.scrollTop = el.scrollHeight; }, [lines, open]);  // newest line in view
  if (!open || (!lines.length && active)) return null;
  const what = lines[0]?.text.startsWith("Opening the saved copy") ? "Opening the saved copy" : "Reading Snowflake";
  return (
    <section className="ae-loadlog" aria-label="Load log">
      <div className="ae-loadlog-head">
        {active && <span className="ae-spin" aria-hidden />}
        {!lines.length ? "Load log" : active ? `${what}: what the app is doing` : `${what}: the last load`}
        {onClose && <button type="button" className="ae-btn ae-btn-s ae-loadlog-x" onClick={onClose}>Close</button>}
      </div>
      {lines.length ? (
        <ol ref={box} role="log" aria-live="polite">
          {lines.map((l, i) => <li key={i}><span className="ae-loadlog-t">{l.t.toFixed(1)} s</span>{l.text}</li>)}
        </ol>
      ) : <p className="ae-muted">Nothing loaded since this page opened.</p>}
    </section>
  );
}
