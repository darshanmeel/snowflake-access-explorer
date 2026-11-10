// Pure table helpers: sort, filter, CSV.

export type Cell = string | number | boolean | null | undefined | string[];

export function cellText(v: Cell): string {
  if (v == null) return "";
  if (Array.isArray(v)) return v.join(" > ");
  return String(v);
}

// one collator: localeCompare with options builds a new one per call (100k rows: about 25x slower)
const coll = new Intl.Collator(undefined, { numeric: true });

export function sortRows<R>(rows: R[], get: (r: R) => Cell, dir: 1 | -1): R[] {
  return [...rows].sort((a, b) => {
    const x = get(a);
    const y = get(b);
    if (typeof x === "number" && typeof y === "number") return (x - y) * dir;
    return coll.compare(cellText(x), cellText(y)) * dir;
  });
}

/** Rows where every word of `q` is in some cell (case-insensitive). */
export function filterRows<R>(rows: R[], q: string, texts: ((r: R) => string)[]): R[] {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return rows;
  return rows.filter((r) => {
    const all = texts.map((f) => f(r)).join(" \u0001 ").toLowerCase();
    return words.every((w) => all.includes(w));
  });
}

export function toCsv(head: string[], rows: string[][]): string {
  // a cell starting with = + - @ tab or CR runs as a formula in Excel: an object name is account metadata anyone may set
  const safe = (s: string) => (/^[=+\-@\t\r]/.test(s) && !/^[+-]?\d+(\.\d+)?$/.test(s) ? `'${s}` : s);
  const q = (s: string) => (/[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
  return [head, ...rows].map((r) => r.map((s) => q(safe(s))).join(",")).join("\r\n");
}

export function download(name: string, text: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}
