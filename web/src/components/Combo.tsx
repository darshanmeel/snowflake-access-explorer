// Search box with a suggestion list: the top bar Find and every picker. The list closes on blur (a click elsewhere,
// Tab) and on Escape; ArrowUp / ArrowDown move through the hits, Enter picks the active one (or the first).
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

export interface ComboProps<T> {
  value: string; // committed value, shown when the box is not being edited
  search: (q: string) => Promise<T[]>; // hits for the typed text (debounced)
  onPick: (item: T) => void;
  keyOf: (item: T) => string;
  render: (item: T) => ReactNode;
  label: string; // aria-label of the box
  placeholder?: string;
  min?: number; // fewest letters before searching (0: the first hits on focus)
  clear?: boolean; // empty the box after a pick (Find) instead of showing the pick
  width?: number;
  className?: string;
  wait?: number;
}

export function Combo<T>({ value, search, onPick, keyOf, render, label, placeholder, min = 0, clear = false, width, className, wait = 160 }: ComboProps<T>) {
  const id = useId();
  const [q, setQ] = useState(value);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<T[]>([]);
  const [active, setActive] = useState(-1);
  const typed = useRef(false); // the box holds what the user typed, not the committed value
  useEffect(() => { if (!typed.current) setQ(clear ? "" : value); }, [value, clear]);
  useEffect(() => {
    if (!open) return;
    const text = typed.current ? q.trim() : "";
    if (text.length < min) { setItems([]); return; }
    let live = true;
    const t = setTimeout(() => search(text).then((xs) => { if (live) { setItems(xs); setActive(-1); } }, () => live && setItems([])), wait);
    return () => { live = false; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, open, min]);
  const close = () => { setOpen(false); setActive(-1); typed.current = false; setQ(clear ? q : value); };
  const pick = (x: T) => { typed.current = false; setOpen(false); setActive(-1); setItems([]); setQ(clear ? "" : keyOf(x)); onPick(x); };
  const shown = open ? items : [];
  const opt = (i: number) => `${id}-o${i}`;
  return (
    <span className={`ae-combo${className ? ` ${className}` : ""}`}>
      <input className="ae-input" type="search" role="combobox" aria-label={label} aria-expanded={shown.length > 0} aria-controls={`${id}-l`}
        aria-autocomplete="list" aria-activedescendant={active >= 0 && shown[active] ? opt(active) : undefined}
        autoComplete="off" placeholder={placeholder} value={q} style={width ? { width } : undefined}
        onChange={(e) => { typed.current = true; setQ(e.target.value); setOpen(true); }}
        onFocus={(e) => { e.target.select(); setOpen(true); }}
        onBlur={close}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            setOpen(true);
            if (shown.length) setActive((a) => (e.key === "ArrowDown" ? (a + 1) % shown.length : (a <= 0 ? shown.length : a) - 1));
          } else if (e.key === "Enter") {
            const x = shown[active] ?? shown[0];
            if (x) { e.preventDefault(); pick(x); }
          } else if (e.key === "Escape") {
            if (clear) setQ("");
            close();
          }
        }} />
      {shown.length > 0 && (
        <span className="ae-combo-list" role="listbox" id={`${id}-l`} aria-label={label}>
          {shown.map((x, i) => (
            <span key={keyOf(x) + i} id={opt(i)} role="option" aria-selected={i === active} className={i === active ? "on" : undefined}
              onMouseDown={(e) => e.preventDefault()} onClick={() => pick(x)} onMouseEnter={() => setActive(i)}>
              {render(x)}
            </span>
          ))}
        </span>
      )}
    </span>
  );
}
