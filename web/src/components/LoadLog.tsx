// What the app is doing while it reads Snowflake: the server's progress lines (/api/progress), asked about once a
// second while `active`. Inside Streamlit, Python is busy during the load, so st_react.py writes the lines itself.
import { useEffect, useRef, useState } from "react";
import type { Progress } from "../api/types";

export function LoadLog({ active, poll, every = 1000 }: { active: boolean; poll: () => Promise<Progress | null>; every?: number }) {
  const [lines, setLines] = useState<Progress["lines"]>([]);
  const box = useRef<HTMLOListElement>(null);
  useEffect(() => {
    if (!active) { setLines([]); return; }
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
  useEffect(() => { const el = box.current; if (el) el.scrollTop = el.scrollHeight; }, [lines]);  // newest line in view
  if (!active || !lines.length) return null;
  return (
    <section className="ae-loadlog" aria-label="What the app is doing">
      <div className="ae-loadlog-head"><span className="ae-spin" aria-hidden />Reading Snowflake: what the app is doing</div>
      <ol ref={box} role="log" aria-live="polite">
        {lines.map((l, i) => <li key={i}><span className="ae-loadlog-t">{l.t.toFixed(1)} s</span>{l.text}</li>)}
      </ol>
    </section>
  );
}
