// Screen 8, the sensitive objects catalog: one row per tagged object with its protection, most exposed first.
import { useState } from "react";
import type { CatalogRow } from "../api/types";
import { Card, EmptyState, FilterChips } from "../components";
import { useApp } from "../ctx";
import { catalogOf, catalogSentence, protectionText, type CatFilter } from "./signoff";

const STATUS: Record<CatalogRow["status"], [string, string]> = {
  not: ["Not protected", "ae-pst-bad"], partly: ["Partly", "ae-pst-warn"], protected: ["Protected", "ae-pst-ok"], whole: ["Whole object", "ae-pst-plain"],
};

export function Catalog({ rows }: { rows: CatalogRow[] }) {
  const c = useApp();
  const [f, setF] = useState<CatFilter>("all");
  const shown = catalogOf(rows, f);
  return (
    <>
      <div className="ae-headrow">
        <p className="ae-answer">{catalogSentence(rows)} Most exposed first.</p>
        <button type="button" className="ae-btn" onClick={() => c.nav("flow", {})}>Where it flows</button>
      </div>
      <div className="ae-toolbar">
        <FilterChips label="Filter" value={f} onPick={(k) => setF(k as CatFilter)} items={([["all", "All"], ["open", "Not protected"], ["pii", "PII / identifiers"], ["confidential", "Confidential"]] as const)
          .map(([key, label]) => ({ key, label, count: catalogOf(rows, key).length }))} />
      </div>
      <Card scroll>
        {!shown.length ? <EmptyState title="Nothing matches">Pick another filter.</EmptyState> : (
          <div className="ae-cat" role="table">
            <div className="ae-cat-row ae-cat-h" role="row"><span>Object</span><span>Tags</span><span>Protection</span><span>Who can read</span><span /></div>
            {shown.map((r) => (
              <div className="ae-cat-row" role="row" key={r.object}>
                <span><b className="ae-mono">{r.name}</b><span className="ae-muted ae-osub">{r.type.toLowerCase()} · {r.ns}</span></span>
                <span className="ae-objtags0">{r.labels.map((t) => <span key={t} className="ae-otag ae-sens-tag">{t.split("=").pop()}</span>)}</span>
                <span className="ae-cat-prot">
                  <span><span className={`ae-pst ${STATUS[r.status][1]}`}>{STATUS[r.status][0]}</span> <span className="ae-small">{protectionText(r)}</span></span>
                  {r.columns.length > 0 && <span className="ae-objtags0">{r.columns.map((x) => (
                    <span key={x.column} className={`ae-colchip ${x.masked ? "ae-colchip-ok" : "ae-colchip-bad"}`} title={x.masked ? `Masked by ${x.policies.join(", ")}` : "No masking policy"}>{x.column}</span>))}</span>}
                </span>
                <span><b className="ae-cat-n">{r.readers}</b> <span className="ae-muted">people{r.admin ? ` · +${r.admin} admin` : ""}</span></span>
                <span><button type="button" className="ae-btn" onClick={() => c.nav("object", { name: r.object, show: "who" })}>Who →</button></span>
              </div>
            ))}
          </div>
        )}
      </Card>
      <div className="ae-bar-legend">
        <span><span className="ae-colchip ae-colchip-bad">COL</span>column with no masking</span>
        <span><span className="ae-colchip ae-colchip-ok">COL</span>masked</span>
      </div>
    </>
  );
}
