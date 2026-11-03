// Pure table helpers: sort, filter, CSV.

export type Cell = string | number | boolean | null | undefined | string[];

export function cellText(v: Cell): string {
  if (v == null) return "";
  if (Array.isArray(v)) return v.join(" > ");
  return String(v);
}

export function sortRows<R>(rows: R[], get: (r: R) => Cell, dir: 1 | -1): R[] {
  return [...rows].sort((a, b) => {
    const x = get(a);
    const y = get(b);
    if (typeof x === "number" && typeof y === "number") return (x - y) * dir;
    return cellText(x).localeCompare(cellText(y), undefined, { numeric: true }) * dir;
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
  const q = (s: string) => (/[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
  return [head, ...rows].map((r) => r.map(q).join(",")).join("\r\n");
}

export function download(name: string, text: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}
