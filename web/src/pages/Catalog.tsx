// Screen 8, the sensitive objects catalog: one row per tagged object with its protection, most exposed first.
import { useEffect, useState } from "react";
import type { CatalogRow } from "../api/types";
import { Card, EmptyState, FilterChips, ListToolbar, MiniBar, Pager, StackBar } from "../components";
import { download } from "../components/table";
import { useApp } from "../ctx";
import { catalogCsv, catalogOf, catalogSentence, protectionText, type CatFilter } from "./signoff";

const STATUS: Record<CatalogRow["status"], [string, string]> = {
  not: ["Not protected", "ae-pst-bad"], partly: ["Partly", "ae-pst-warn"], protected: ["Protected", "ae-pst-ok"], whole: ["Whole object", "ae-pst-plain"],
};

const SIZE = 50; // rows drawn per page: a big account tags hundreds of objects
const BAR: Record<CatalogRow["status"], string> = { not: "high", partly: "medium", protected: "keep", whole: "people" };
const SORTS: Record<string, (a: CatalogRow, b: CatalogRow) => number> = {
  exposed: () => 0, readers: (a, b) => b.readers + b.admin - a.readers - a.admin, name: (a, b) => a.object.localeCompare(b.object),
};

export function Catalog({ rows }: { rows: CatalogRow[] }) {
  const c = useApp();
  const [f, setF] = useState<CatFilter>("all");
  const [q, setQ] = useState("");
  const [st, setSt] = useState<string | null>(null); // a status picked on the bar
  const [sort, setSort] = useState("exposed");
  const [at, setAt] = useState(0);
  useEffect(() => setAt(0), [f, q, st, sort]);
  const shown = catalogOf(rows, f, q).filter((r) => !st || r.status === st).sort(SORTS[sort]);
  const page = shown.slice(at * SIZE, (at + 1) * SIZE);
  const by = (k: CatalogRow["status"]) => rows.filter((r) => r.status === k).length;
  const most = Math.max(1, ...rows.map((r) => r.readers + r.admin));
  const off = c.meta.sources.policies === "UNAVAILABLE"; // not read: masked or not is unknown, never "Not protected"
  return (
    <>
      <div className="ae-headrow">
        <p className="ae-answer">{catalogSentence(rows)}</p>
        <button type="button" className="ae-btn" onClick={() => c.nav("flow", {})}>Where it flows</button>
      </div>
      {!off && <StackBar label="Tagged objects by protection: click a part to list them" on={st} onPick={(k) => setSt(st === k ? null : k)}
        parts={(Object.keys(STATUS) as CatalogRow["status"][]).map((k) => ({ key: k, label: STATUS[k][0], value: by(k), cls: BAR[k] }))} />}
      <ListToolbar search={q} onSearch={setQ} onCsv={() => download("sensitive_catalog.csv", catalogCsv(shown))}>
        <FilterChips label="Filter" value={f} onPick={(k) => setF(k as CatFilter)} items={([["all", "All"], ["open", "Has unmasked columns"], ["pii", "PII / identifiers"], ["confidential", "Confidential"]] as const)
          .map(([key, label]) => ({ key, label, count: catalogOf(rows, key, q).length }))} />
        <FilterChips label="Sort" value={sort} onPick={setSort} items={[{ key: "exposed", label: "Most exposed" }, { key: "readers", label: "Most readers" }, { key: "name", label: "Name" }]} />
        {st && <button type="button" className="ae-chip ae-chip-plain" onClick={() => setSt(null)}>{STATUS[st as CatalogRow["status"]][0]} ×</button>}
      </ListToolbar>
      <Card scroll>
        {!shown.length ? <EmptyState title="Nothing matches" art="search">Pick another filter or clear the search.</EmptyState> : (
          <div className="ae-cat" role="table">
            <div className="ae-cat-row ae-cat-h" role="row"><span>Object</span><span>Tags</span><span>Protection</span><span>Who can read</span><span /></div>
            {page.map((r) => (
              <div className="ae-cat-row" role="row" key={r.object}>
                <span><b className="ae-mono">{r.name}</b><span className="ae-muted ae-osub">{r.type.toLowerCase()} · {r.ns}</span></span>
                <span className="ae-objtags0">{r.labels.map((t) => <span key={t} className="ae-otag ae-sens-tag">{t.split("=").pop()}</span>)}</span>
                <span className="ae-cat-prot">
                  {off && r.status !== "whole" ? <span><span className="ae-pst ae-pst-plain">Unknown</span> <span className="ae-small">policies not read</span></span> : <>
                    <span><span className={`ae-pst ${STATUS[r.status][1]}`}>{STATUS[r.status][0]}</span> <span className="ae-small">{protectionText(r)}</span></span>
                    {r.columns.length > 0 && <Cols cols={r.columns} />}</>}
                </span>
                <span className="ae-cat-who"><MiniBar of={most} text={<><b className="ae-cat-n">{r.readers}</b> <span className="ae-muted">users{r.admin ? ` · +${r.admin} admin` : ""} · {r.clear ?? "?"} see clear</span></>}
                  parts={[{ key: "p", label: "Users", value: r.readers, cls: r.status === "not" ? "high" : r.status === "partly" ? "medium" : "people" }, { key: "a", label: "Through an admin role", value: r.admin, cls: "admin" }]} /></span>
                <span><button type="button" className="ae-btn" onClick={() => c.nav("object", { name: r.object, show: "who" })}>Who →</button></span>
              </div>
            ))}
          </div>
        )}
        {shown.length > SIZE && <Pager at={at} size={SIZE} total={shown.length} onPage={setAt} />}
      </Card>
      <div className="ae-bar-legend">
        <span><span className="ae-colchip ae-colchip-bad">COL</span>column with no masking</span>
        <span><span className="ae-colchip ae-colchip-ok">COL</span>masked</span>
        <span><span className="ae-dot2 ae-bar-high" />users: no column masked</span><span><span className="ae-dot2 ae-bar-medium" />partly masked</span><span><span className="ae-dot2 ae-bar-people" />all masked or whole object</span><span><span className="ae-dot2 ae-bar-admin" />through an admin role</span>
      </div>
    </>
  );
}

const FEW = 4; // column chips shown per object before "+N more": a wide table has dozens of tagged columns

/** Sensitive columns of one object: a masked / unmasked bar, then the unmasked ones first, a few, the rest on a click. */
function Cols({ cols }: { cols: { column: string; masked: boolean; policies: string[] }[] }) {
  const [all, setAll] = useState(false);
  const sorted = [...cols].sort((a, b) => Number(a.masked) - Number(b.masked));
  const masked = cols.filter((x) => x.masked).length;
  const shown = all ? sorted : sorted.slice(0, FEW);
  return (
    <>
      {cols.length > 1 && (
        <span className="ae-cat-bar" role="img" aria-label={`${masked} of ${cols.length} columns masked`}>
          <span className="ae-cat-bar-ok" style={{ flex: masked }} /><span className="ae-cat-bar-bad" style={{ flex: cols.length - masked }} />
        </span>
      )}
      <span className="ae-objtags0">
        {shown.map((x) => (
          <span key={x.column} className={`ae-colchip ${x.masked ? "ae-colchip-ok" : "ae-colchip-bad"}`} title={x.masked ? `Masked by ${x.policies.join(", ")}` : "No masking policy"}>{x.column}</span>))}
        {cols.length > FEW && <button type="button" className="ae-link ae-small" onClick={() => setAll(!all)}>{all ? "show fewer" : `+${cols.length - FEW} more`}</button>}
      </span>
    </>
  );
}
