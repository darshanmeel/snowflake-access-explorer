// Small building blocks: Card, Tabs, Chips, Banner, KpiRow. Colours only through --ae-* variables (themeVars).
import { createContext, useContext, useState, type MouseEvent, type ReactNode } from "react";
import { copyText } from "./kit";
import { themeVars } from "./theme";

/** Opens the "SQL behind this page" panel with a hint (the card's title); set by the app, absent in tests. */
export const SqlCtx = createContext<((hint: string) => void) | null>(null);

/** The </> mark in a card's top-right corner: its own SQL (sql) inline, else the page's SQL panel led by this card. */
function SqlMark({ sql, open, setOpen }: { sql?: string; open: boolean; setOpen: (v: boolean) => void }) {
  const show = useContext(SqlCtx);
  if (!show) return null;
  const click = (e: MouseEvent<HTMLButtonElement>) => sql ? setOpen(!open)
    : show(e.currentTarget.closest(".ae-card")?.querySelector("h3")?.textContent ?? "");
  return <button type="button" className={`ae-card-sql${open ? " on" : ""}`} onClick={click} aria-pressed={sql ? open : undefined}
    title="The SQL behind this, to run yourself in Snowflake" aria-label="Show the SQL behind this">{"</>"}</button>;
}

/** A card's own SQL, shown in the card. */
function SqlInline({ sql }: { sql: string }) {
  const [done, setDone] = useState("");
  return (
    <div className="ae-sqlbox">
      <div className="ae-sqlbox-h"><b>SQL behind this</b><span className="ae-muted">read-only · change the SET lines · run it with your own role</span>
        <button type="button" className="ae-btn" onClick={() => copyText(sql).then((ok) => { setDone(ok ? "Copied" : "Select and copy"); setTimeout(() => setDone(""), 1500); })}>{done || "Copy SQL"}</button></div>
      <pre tabIndex={0}>{sql}</pre>
    </div>
  );
}

export function Card({ title, sub, right, children, scroll = false, sql }: {
  title?: ReactNode; sub?: ReactNode; right?: ReactNode; children?: ReactNode; scroll?: boolean; sql?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section className="ae-card">
      <SqlMark sql={sql} open={open} setOpen={setOpen} />
      {(title || right) && (
        <header className="ae-card-head">
          <div>
            {title && <h3>{title}</h3>}
            {sub && <p className="ae-muted">{sub}</p>}
          </div>
          {right && <div className="ae-card-right">{right}</div>}
        </header>
      )}
      <div className={scroll ? "ae-card-body ae-scroll" : "ae-card-body"}>{open && sql && <SqlInline sql={sql} />}{children}</div>
    </section>
  );
}

export interface TabItem { key: string; label: string; count?: number | null; tone?: "bad" | "warn" | null }

export function Tabs({ tabs, active, onChange }: { tabs: TabItem[]; active: string; onChange: (key: string) => void }) {
  return (
    <div className="ae-tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.key} role="tab" aria-selected={t.key === active}
          className={`ae-tab${t.key === active ? " on" : ""}${t.tone ? ` ae-tone-${t.tone}` : ""}`} onClick={() => onChange(t.key)}>
          {t.label}
          {t.count != null && <span className="ae-tab-count">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export interface ChipItem { id: string; label?: string; kind?: string; title?: string; tone?: "bad" | "warn" | null; onClick?: () => void }

/** Chips wrap onto new lines (never cut off); over `max` they fold into "+N more". */
export function Chips({ items, max = 12, onClick }: { items: ChipItem[]; max?: number; onClick?: (c: ChipItem) => void }) {
  const [all, setAll] = useState(false);
  const shown = all ? items : items.slice(0, max);
  return (
    <div className="ae-chips">
      {shown.map((c) => {
        const click = c.onClick ?? (onClick ? () => onClick(c) : undefined);
        const cls = `ae-chip ae-chip-${c.kind ?? "plain"}${c.tone ? ` ae-tone-${c.tone}` : ""}`;
        return click
          ? <button key={c.id} className={cls} title={c.title ?? c.id} onClick={click}>{c.label ?? c.id}</button>
          : <span key={c.id} className={cls} title={c.title ?? c.id}>{c.label ?? c.id}</span>;
      })}
      {items.length > max && (
        <button className="ae-chip ae-chip-more" onClick={() => setAll(!all)}>{all ? "show less" : `+${items.length - max} more`}</button>
      )}
    </div>
  );
}

export function Banner({ tone = "info", title, lines = [], children }: {
  tone?: "info" | "warn" | "bad"; title: ReactNode; lines?: ReactNode[]; children?: ReactNode;
}) {
  return (
    <div className={`ae-banner ae-tone-${tone}`} role={tone === "info" ? "status" : "alert"}>
      <strong>{title}</strong>
      {lines.length > 0 && <ul>{lines.map((l, i) => <li key={i}>{l}</li>)}</ul>}
      {children}
    </div>
  );
}

export interface Kpi { label: string; value: ReactNode; caption?: ReactNode; tone?: "bad" | "warn" | "ok" | null; help?: string }

export function KpiRow({ items }: { items: Kpi[] }) {
  return (
    <div className="ae-kpis">
      {items.map((k) => (
        <div key={k.label} className={`ae-kpi${k.tone ? ` ae-tone-${k.tone}` : ""}`} title={k.help}>
          <div className="ae-kpi-label">{k.label}</div>
          <div className="ae-kpi-value">{k.value}</div>
          {k.caption && <div className="ae-kpi-cap">{k.caption}</div>}
        </div>
      ))}
    </div>
  );
}

/** Wrapper that sets the theme variables every component reads. */
export function Root({ theme, children }: { theme: "light" | "dark"; children?: ReactNode }) {
  return <div className="ae-root" style={themeVars(theme)}>{children}</div>;
}
