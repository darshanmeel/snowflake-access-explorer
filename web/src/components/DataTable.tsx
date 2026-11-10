// Sortable, filterable table. Fits the card width; wider tables scroll inside the card, never the page.
import { useMemo, useState, type ReactNode } from "react";
import { cellText, download, filterRows, sortRows, toCsv, type Cell } from "./table";

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
  limit?: number; // rows drawn before "show all"
  onRowClick?: (r: R) => void;
  rowTone?: (r: R) => "bad" | "warn" | null;
}

export function DataTable<R>({
  columns, rows, filter = true, csv = "table.csv", sort, maxHeight = 520, empty = "Nothing to show.", limit = 500,
  onRowClick, rowTone,
}: DataTableProps<R>) {
  const [q, setQ] = useState("");
  const [by, setBy] = useState<{ key: string; dir: 1 | -1 } | null>(sort ? { key: sort.key, dir: sort.dir ?? 1 } : null);
  const [all, setAll] = useState(false);
  const view = useMemo(() => {
    const f = filterRows(rows, q, columns.map((c) => (r: R) => cellText(c.get(r))));
    const col = by && columns.find((c) => c.key === by.key);
    return col ? sortRows(f, col.get, by!.dir) : f;
  }, [rows, q, by, columns]);
  const shown = all ? view : view.slice(0, limit);
  const tools = filter && rows.length >= 10; // a filter box and row count only where there is something to filter

  const data = columns.filter((c) => c.label); // a column without a label holds buttons: not in the CSV, not sortable
  const exportCsv = () =>
    download(csv || "table.csv", toCsv(data.map((c) => c.label), view.map((r) => data.map((c) => cellText(c.get(r))))));

  return (
    <div className="ae-table-wrap">
      {(tools || csv !== null) && (
        <div className="ae-table-tools">
          {tools && <input className="ae-input" placeholder="Filter rows" value={q} onChange={(e) => setQ(e.target.value)} />}
          {tools && <span className="ae-muted">{view.length === rows.length ? `${rows.length} rows` : `${view.length} of ${rows.length} rows`}</span>}
          {csv !== null && <button className="ae-btn" onClick={exportCsv}>CSV</button>}
        </div>
      )}
      <div className="ae-table-scroll" style={{ maxHeight }}>
        <table className="ae-table">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.key} title={c.help} style={{ width: c.width }} className={c.num ? "num" : undefined}
                  aria-sort={c.label && by?.key === c.key ? (by.dir === 1 ? "ascending" : "descending") : undefined}
                  onClick={c.label ? () => setBy(by?.key === c.key ? { key: c.key, dir: by.dir === 1 ? -1 : 1 } : { key: c.key, dir: 1 }) : undefined}>
                  {c.label}
                  <span className="ae-sort">{by?.key === c.key ? (by.dir === 1 ? "▲" : "▼") : ""}</span>
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
      {view.length > shown.length && (
        <button className="ae-btn ae-more" onClick={() => setAll(true)}>Show all {view.length} rows</button>
      )}
    </div>
  );
}
