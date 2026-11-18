// Sortable, filterable table. Fits the card width; wider tables scroll inside the card, never the page.
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { download as saveCsv, useApi } from "../api/client";
import type { Paged } from "../api/types";
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
  /** Rows paged, filtered and sorted on the server: GET path with params plus offset, limit, q, sort (a column key)
   * and dir answers Paged<R>; `rows` is then ignored. The CSV comes from GET `${path}.csv` (every matching row). */
  server?: { path: string; params: Record<string, string | undefined | null> };
}

export function DataTable<R>({
  columns, rows, filter = true, csv = "table.csv", sort, maxHeight = 520, empty = "Nothing to show.", limit = 50,
  onRowClick, rowTone, server,
}: DataTableProps<R>) {
  const [q, setQ] = useState("");
  const [sq, setSq] = useState(""); // q as sent to the server, a moment after the last key
  const [by, setBy] = useState<{ key: string; dir: 1 | -1 } | null>(sort ? { key: sort.key, dir: sort.dir ?? 1 } : null);
  const [size, setSize] = useState(limit);
  const [page, setPage] = useState(0);
  const csvOn = useCsv() && csv !== null;
  const keys = columns.map((c) => c.key).join("\u0001");
  useEffect(() => { const t = setTimeout(() => setSq(q), 250); return () => clearTimeout(t); }, [q]);
  const ask = server && { ...server.params, q: sq, sort: by?.key, dir: by ? String(by.dir) : null };
  const got = useApi<Paged<R>>(server ? server.path : null, ask ? { ...ask, offset: String(page * size), limit: String(size) } : {});
  const view = useMemo(() => {
    if (server) return [];
    const f = filterRows(rows, q, columns.map((c) => (r: R) => cellText(c.get(r))));
    const col = by && columns.find((c) => c.key === by.key);
    return col ? sortRows(f, col.get, by!.dir) : f;
  }, [rows, q, by, keys, !server]); // keys, not columns: pages pass a new columns array each render, which re-sorted every time
  const scope = server ? JSON.stringify(server.params) : rows.length;
  useEffect(() => setPage(0), [server ? sq : q, by, scope]); // a new filter, sort or row set starts on page 1 (rows.length: pages often pass a new array each render)
  const total = server ? got.data?.total ?? 0 : view.length;
  const last = Math.max(0, Math.ceil(total / size) - 1), at = server ? page : Math.min(page, last);
  const shown = server ? got.data?.rows ?? [] : view.slice(at * size, (at + 1) * size);
  const sizes = [...new Set([25, 50, 100, 250, limit])].sort((x, y) => x - y);
  const pager = total > size || (size !== limit && total > sizes[0]); // kept once the viewer picked a size, to pick again
  const tools = filter && (server ? total >= 10 || !!q : rows.length >= 10); // a filter box and row count only where there is something to filter
  const all = server ? total : rows.length;

  const data = columns.filter((c) => c.label); // a column without a label holds buttons: not in the CSV, not sortable
  const exportCsv = () => server && ask
    ? saveCsv(`${server.path}.csv`, ask, csv || "table.csv")
    : download(csv || "table.csv", toCsv(data.map((c) => c.label), view.map((r) => data.map((c) => cellText(c.get(r))))));

  return (
    <div className="ae-table-wrap">
      {(tools || csvOn) && (
        <div className="ae-table-tools">
          {tools && <input className="ae-input" placeholder="Filter rows" value={q} onChange={(e) => setQ(e.target.value)} />}
          {tools && <span className="ae-muted">{server || total === all ? `${total} rows` : `${total} of ${all} rows`}</span>}
          {csvOn && <button className="ae-btn" onClick={exportCsv}>CSV</button>}
        </div>
      )}
      <div className={`ae-table-scroll${server && got.loading ? " ae-fade" : ""}`} style={{ maxHeight }}>
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
            {!shown.length && <tr><td colSpan={columns.length} className="ae-muted">
              {server && got.error ? got.error.message : server && !got.data ? "Loading…" : empty}</td></tr>}
          </tbody>
        </table>
      </div>
      {pager && <Pager at={at} size={size} total={total} onPage={setPage} sizes={sizes} onSize={(n) => { setSize(n); setPage(0); }} />}
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
