// Sortable, filterable table. Fits the card width; wider tables scroll inside the card, never the page.
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { cellText, download, filterRows, sortRows, toCsv, useCsv, type Cell } from "./table";

export interface Column<R> {
  key: string;
  label: string;
  get: (r: R) => Cell; // value for sort, filter and CSV
  render?: (r: R) => ReactNode;
  num?: boolean;
  wrap?: "wrap" | "truncate" | "nowrap"; // long text (Path): wrap (default) or one line with the full text on hover
  width?: number | string;
  help?: string;
}

export interface DataTableProps<R> {
  columns: Column<R>[];
  rows: R[];
  filter?: boolean;
  csv?: string | null; // file name; null hides the button
  sort?: { key: string; dir?: 1 | -1 };
  maxHeight?: number;
  empty?: ReactNode;
  limit?: number; // rows per page at first (the viewer picks 25 / 50 / 100 / 250)
  onRowClick?: (r: R) => void;
  rowTone?: (r: R) => "bad" | "warn" | null;
  server?: ServerTable; // rows are the page the server filtered, sorted and cut: the table asks it for another
}

/** A table the server pages: rows = page `at` of `size` rows, out of `total` that match `q`, sorted by `by`. */
export interface ServerTable {
  total: number;
  at: number;
  size: number;
  q: string;
  by: { key: string; dir: 1 | -1 } | null;
  onChange: (s: { at: number; size?: number; q?: string; by?: { key: string; dir: 1 | -1 } }) => void;
}

export function DataTable<R>({
  columns, rows, filter = true, csv = "table.csv", sort, maxHeight = 520, empty = "Nothing to show.", limit = 50,
  onRowClick, rowTone, server,
}: DataTableProps<R>) {
  const [ownQ, setOwnQ] = useState("");
  const [ownBy, setOwnBy] = useState<{ key: string; dir: 1 | -1 } | null>(sort ? { key: sort.key, dir: sort.dir ?? 1 } : null);
  const [ownSize, setOwnSize] = useState(limit);
  const [page, setPage] = useState(0);
  const q = server ? server.q : ownQ, by = server ? server.by : ownBy, size = server ? server.size : ownSize;
  const csvOn = useCsv() && csv !== null;
  const keys = columns.map((c) => c.key).join("\u0001");
  const view = useMemo(() => {
    if (server) return rows;
    const f = filterRows(rows, q, columns.map((c) => (r: R) => cellText(c.get(r))));
    const col = by && columns.find((c) => c.key === by.key);
    return col ? sortRows(f, col.get, by!.dir) : f;
  }, [rows, q, by, keys, !server]); // keys, not columns: pages pass a new columns array each render, which re-sorted every time
  useEffect(() => setPage(0), [q, by, rows.length]); // a new filter, sort or row set starts on page 1 (rows.length: pages often pass a new array each render)
  const total = server ? server.total : view.length;
  const last = Math.max(0, Math.ceil(total / size) - 1), at = server ? server.at : Math.min(page, last);
  const shown = server ? rows : view.slice(at * size, (at + 1) * size);
  const sizes = [...new Set([25, 50, 100, 250, limit])].sort((x, y) => x - y);
  const pager = total > size || (size !== limit && total > sizes[0]); // kept once the viewer picked a size, to pick again
  const tools = filter && (!!server || rows.length >= 10); // a filter box and row count only where there is something to filter
  const setQ = (v: string) => (server ? server.onChange({ at: 0, q: v }) : setOwnQ(v));
  const setBy = (v: { key: string; dir: 1 | -1 }) => (server ? server.onChange({ at: 0, by: v }) : setOwnBy(v));
  const onPage = (n: number) => (server ? server.onChange({ at: n }) : setPage(n));
  const onSize = (n: number) => (server ? server.onChange({ at: 0, size: n }) : (setOwnSize(n), setPage(0)));

  const data = columns.filter((c) => c.label); // a column without a label holds buttons: not in the CSV, not sortable
  const exportCsv = () =>
    download(csv || "table.csv", toCsv(data.map((c) => c.label), view.map((r) => data.map((c) => cellText(c.get(r))))));

  return (
    <div className="ae-table-wrap">
      {(tools || csvOn) && (
        <div className="ae-table-tools">
          {tools && <input className="ae-input" placeholder="Filter rows" value={q} onChange={(e) => setQ(e.target.value)} />}
          {tools && <span className="ae-muted">{server ? `${total} rows` : view.length === rows.length ? `${rows.length} rows` : `${view.length} of ${rows.length} rows`}</span>}
          {csvOn && <button className="ae-btn" onClick={exportCsv}>CSV</button>}
        </div>
      )}
      <div className="ae-table-scroll" style={{ maxHeight }}>
        <table className="ae-table">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.key} title={c.help} style={{ width: c.width }} className={c.num ? "num" : undefined}
                  aria-sort={c.label && by?.key === c.key ? (by.dir === 1 ? "ascending" : "descending") : undefined}>
                  {c.label && (
                    <button type="button" className="ae-th-btn"
                      onClick={() => setBy(by?.key === c.key ? { key: c.key, dir: by.dir === 1 ? -1 : 1 } : { key: c.key, dir: 1 })}>
                      {c.label}
                      <span className="ae-sort">{by?.key === c.key ? (by.dir === 1 ? "▲" : "▼") : ""}</span>
                    </button>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => {
              const tone = rowTone?.(r);
              return (
                <tr key={i} className={`${tone ? `ae-tone-${tone}` : ""}${onRowClick ? " click" : ""}`} onClick={onRowClick && (() => onRowClick(r))}>
                  {columns.map((c) => {
                    const text = cellText(c.get(r));
                    const cls = [c.num ? "num" : "", `ae-${c.wrap ?? "wrap"}`].join(" ");
                    return <td key={c.key} className={cls} title={c.wrap === "truncate" ? text : undefined}>{c.render ? c.render(r) : text}</td>;
                  })}
                </tr>
              );
            })}
            {!shown.length && <tr><td colSpan={columns.length} className="ae-muted">{empty}</td></tr>}
          </tbody>
        </table>
      </div>
      {pager && <Pager at={at} size={size} total={total} onPage={onPage} sizes={sizes} onSize={onSize} />}
    </div>
  );
}

/** Prev / Next under a long list: "Rows a–b of N", optionally a page-size pick. `at` is the 0-based page. */
export function Pager({ at, size, total, onPage, sizes, onSize }: {
  at: number; size: number; total: number; onPage: (p: number) => void; sizes?: number[]; onSize?: (n: number) => void;
}) {
  const last = Math.max(0, Math.ceil(total / size) - 1);
  return (
    <nav className="ae-pager" aria-label="Table pages">
      <button type="button" className="ae-btn" disabled={at === 0} onClick={() => onPage(at - 1)}>Prev</button>
      <span className="ae-muted" aria-live="polite">Rows {total ? at * size + 1 : 0}–{Math.min(total, (at + 1) * size)} of {total}</span>
      <button type="button" className="ae-btn" disabled={at >= last} onClick={() => onPage(at + 1)}>Next</button>
      {sizes && onSize && (
        <label className="ae-muted">Per page{" "}
          <select className="ae-input ae-pager-size" value={size} onChange={(e) => onSize(Number(e.target.value))}>
            {sizes.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
      )}
    </nav>
  );
}
