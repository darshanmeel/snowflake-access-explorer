// A table the server pages (a big account sends one page of it): this page's rows, Prev / Next over the server's
// total (offset in the URL param `at`, page size in `limit`), and a CSV of every row (the same request with limit=0).
import { get } from "../api/client";
import { cellText, DataTable, Pager, toCsv, useCsv, type DataTableProps } from "../components";
import { download } from "../components/table";
import { apiParams, useApp } from "../ctx";

export const PAGE = 50; // server.PAGE

export function PagedTable<R, P>({ path, at, total, offset, pick, csv, ...t }: Omit<DataTableProps<R>, "csv" | "limit" | "filter"> & {
  path: string; at: string; total: number; offset: number; pick: (d: P) => R[]; csv: string;
}) {
  const c = useApp(), csvOn = useCsv();
  const size = Number(c.params.limit) || PAGE;
  const all = async () => {
    const rows = pick(await get<P>(path, { ...apiParams(c), limit: "0" }));
    const cols = t.columns.filter((x) => x.label);
    download(csv, toCsv(cols.map((x) => x.label), rows.map((r) => cols.map((x) => cellText(x.get(r))))));
  };
  return (
    <>
      {csvOn && <div className="ae-row ae-right"><button type="button" className="ae-btn" onClick={all}>CSV (all {total} rows)</button></div>}
      <DataTable {...t} filter={false} csv={null} limit={Math.max(size, t.rows.length)} />
      {total > size && <Pager at={Math.floor(offset / size)} size={size} total={total} sizes={[25, 50, 100, 250]}
        onPage={(n) => c.set({ [at]: n ? String(n * size) : null })}
        onSize={(n) => c.set({ limit: n === PAGE ? null : String(n), [at]: null })} />}
    </>
  );
}
