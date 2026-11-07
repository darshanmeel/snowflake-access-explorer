// Redesign building blocks: access ladder pill, path chips, finding chip, sensitive cell, filter chips, list toolbar,
// code output (SQL / Terraform / ticket), identity card, empty state. Colours only from --ae-* variables.
import { useState, type ReactNode } from "react";
import { sqlOf, terraformOf, ticketOf, type Change, type Note } from "./codegen";

export const LEVEL_WORD: Record<string, string> = { names: "Can see names", read: "Read", change: "Read + change", own: "Owns", admin: "Admin" };

export function AccessPill({ level, privileges }: { level: string | null; privileges?: string[] }) {
  return (
    <span className="ae-access">
      {level && <span className={`ae-lvl ae-lvl-${level}`}>{LEVEL_WORD[level] ?? level}</span>}
      {privileges && privileges.length > 0 && <span className="ae-privs">{privileges.join(" · ")}</span>}
    </span>
  );
}

/** first role › grant holder, "+N more ways". Granted straight: just the holder. */
export function PathChips({ first, holder, ways, kinds, onOpen }: {
  first: string | null; holder: string; ways: number; kinds?: Record<string, string>; onOpen?: (id: string) => void;
}) {
  const chip = (id: string, lead = false) => (
    <button type="button" className={`ae-pchip${lead ? ` ae-pchip-${kinds?.[id] ?? "plain"}` : ""}`} onClick={() => onOpen?.(id)} title={id}>
      {id === "PUBLIC" ? "PUBLIC (everyone)" : id}
    </button>
  );
  return (
    <span className="ae-pathchips">
      {first && first !== holder ? <>{chip(first, true)}<span className="ae-sep" aria-hidden>›</span>{chip(holder)}</> : chip(holder, true)}
      {ways > 1 && <span className="ae-more">+{ways - 1} more way{ways === 2 ? "" : "s"}</span>}
    </span>
  );
}

export function FindingChip({ num, severity, label, onOpen }: { num: string; severity: string; label: string; onOpen?: () => void }) {
  return (
    <button type="button" className={`ae-fchip ae-fchip-${severity.toLowerCase()}`} onClick={onOpen} title={`Rule ${num}: ${label}`}>
      <b>{severity}</b> {label}
    </button>
  );
}

const LOCK = (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden>
    <rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" />
  </svg>
);

export function SensitiveCell({ sensitive, columns }: { sensitive: boolean; columns: { column: string; state: string; reason: string }[] }) {
  if (!sensitive && !columns.length) return <span className="ae-muted">—</span>;
  const clear = columns.filter((c) => c.state !== "masked");
  const state = !columns.length ? "tagged" : clear.length === columns.length ? "clear" : clear.length ? `${columns.length - clear.length} masked` : "masked";
  return (
    <span className="ae-sens-cell" title={columns.map((c) => `${c.column}: ${c.state} (${c.reason})`).join("\n")}>
      <span className="ae-sens-tag">{LOCK}{columns.length ? columns.map((c) => c.column).join(", ") : "sensitive"}</span>
      <span className={`ae-sens-state ae-sens-${state === "masked" ? "masked" : "clear"}`}>{state}</span>
    </span>
  );
}

export interface FilterItem { key: string; label: string; count?: number }

/** Segmented filter: one pressed at a time, counts at full contrast. */
export function FilterChips({ items, value, onPick, label }: { items: FilterItem[]; value: string; onPick: (k: string) => void; label: string }) {
  return (
    <div className="ae-seg2" role="group" aria-label={label}>
      {items.map((i) => (
        <button key={i.key} type="button" aria-pressed={i.key === value} className={i.key === value ? "on" : ""} onClick={() => onPick(i.key)}>
          {i.label}{i.count != null && <span className="ae-seg2-n">{i.count}</span>}
        </button>
      ))}
    </div>
  );
}

/** Filter chips · search · toggles · CSV, the same on every list. */
export function ListToolbar({ children, search, onSearch, onCsv }: {
  children?: ReactNode; search?: string; onSearch?: (s: string) => void; onCsv?: () => void;
}) {
  return (
    <div className="ae-toolbar">
      {children}
      {onSearch && (
        <label className="ae-search">
          <span className="ae-sr">Filter</span>
          <input type="search" className="ae-input" placeholder="Filter" value={search} onChange={(e) => onSearch(e.target.value)} />
        </label>
      )}
      {onCsv && <button type="button" className="ae-btn ae-toolbar-csv" onClick={onCsv}>CSV</button>}
    </div>
  );
}

export function Toggle({ label, on, onPick }: { label: ReactNode; on: boolean; onPick: (v: boolean) => void }) {
  return <label className="ae-toggle"><input type="checkbox" checked={on} onChange={(e) => onPick(e.target.checked)} />{label}</label>;
}

const TABS = [["sql", "SQL"], ["tf", "Terraform"], ["ticket", "Ticket text"]] as const;

/** SQL / Terraform / ticket text of a change list, with copy and download. Text only: nothing runs. */
export function CodeOutput({ changes, note, name = "access_change" }: { changes: Change[]; note?: Note; name?: string }) {
  const [tab, setTab] = useState<(typeof TABS)[number][0]>("sql");
  const [done, setDone] = useState(false);
  const text = tab === "sql" ? sqlOf(changes, note) : tab === "tf" ? terraformOf(changes, note) : ticketOf(changes, note);
  const file = `${name}.${tab === "sql" ? "sql" : tab === "tf" ? "tf" : "txt"}`;
  const copy = () => { navigator.clipboard?.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1200); }, () => {}); };
  const save = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    a.download = file;
    a.click();
    URL.revokeObjectURL(a.href);
  };
  return (
    <div className="ae-codeout">
      <div className="ae-codeout-head">
        <div className="ae-seg2" role="tablist" aria-label="Format">
          {TABS.map(([k, l]) => <button key={k} type="button" role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>)}
        </div>
        <span className="ae-muted ae-mono">{file}</span>
        <span className="ae-codeout-act">
          <button type="button" className="ae-btn" onClick={copy}>{done ? "Copied" : "Copy"}</button>
          <button type="button" className="ae-btn" onClick={save}>Download</button>
        </span>
      </div>
      <pre className="ae-codeout-text">{text}</pre>
      <p className="ae-muted ae-codeout-foot">Read-only: copy this into your infrastructure as code or a ticket. The app never runs it.</p>
    </div>
  );
}

export function EmptyState({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return <div className="ae-empty"><b>{title}</b>{children && <p>{children}</p>}</div>;
}

const initials = (n: string) => (n.match(/[A-Z0-9]+/g) ?? [n]).slice(0, 2).map((w) => w[0]).join("") || n.slice(0, 2);

export function IdentityCard({ name, tag, line, roles }: {
  name: string; tag?: string; line: ReactNode; roles?: { id: string; note?: string; kind?: string }[];
}) {
  return (
    <div className="ae-idcard">
      <span className="ae-avatar" aria-hidden>{initials(name)}</span>
      <div className="ae-idcard-main">
        <div><span className="ae-mono ae-idname">{name}</span>{tag && <span className="ae-idtag">{tag}</span>}</div>
        <div className="ae-muted">{line}</div>
      </div>
      {roles && roles.length > 0 && (
        <div className="ae-idroles">
          <span className="ae-muted">Roles in use</span>
          {roles.map((r) => <span key={r.id} className={`ae-pchip ae-pchip-${r.kind ?? "plain"}`}>{r.id}{r.note ? ` · ${r.note}` : ""}</span>)}
        </div>
      )}
    </div>
  );
}
