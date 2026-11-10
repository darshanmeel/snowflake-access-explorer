// Redesign building blocks: access ladder pill, path chips, finding chip, sensitive cell, filter chips, list toolbar,
// code output (SQL / Terraform / ticket), identity card, empty state. Colours only from --ae-* variables.
import { useRef, useState, type ReactNode } from "react";
import { sqlOf, terraformOf, ticketOf, type Change, type Note } from "./codegen";

export const LEVEL_WORD: Record<string, string> = { names: "Can see names", use: "Can use", read: "Read", change: "Read + change", own: "Owns", admin: "Admin" };

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
export function CodeOutput({ changes, note, name = "access_change", texts }: {
  changes: Change[]; note?: Note; name?: string; texts?: { sql: string; tf: string; ticket: string };
}) {
  const [tab, setTab] = useState<(typeof TABS)[number][0]>("sql");
  const text = texts ? texts[tab] : tab === "sql" ? sqlOf(changes, note) : tab === "tf" ? terraformOf(changes, note) : ticketOf(changes, note);
  const file = `${name}.${tab === "sql" ? "sql" : tab === "tf" ? "tf" : "txt"}`;
  const [copied, setCopied] = useState<"" | "yes" | "no">("");
  const pre = useRef<HTMLPreElement>(null);
  const copy = () => copyText(text, pre.current).then((ok) => { setCopied(ok ? "yes" : "no"); setTimeout(() => setCopied(""), ok ? 1200 : 4000); });
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
          <button type="button" className="ae-btn" onClick={copy}>{copied === "yes" ? "Copied" : "Copy"}</button>
          <button type="button" className="ae-btn" onClick={save}>Download</button>
        </span>
      </div>
      {copied === "no" && <p className="ae-codeout-warn" role="alert">The browser blocked copying here: the text is selected, press Ctrl+C (Cmd+C on a Mac).</p>}
      <pre className="ae-codeout-text" ref={pre} tabIndex={0}>{text}</pre>
      <p className="ae-muted ae-codeout-foot">Read-only: copy this into your infrastructure as code or a ticket. The app never runs it.</p>
    </div>
  );
}

/** Copy to the clipboard; where the browser refuses (plain http on a LAN host, a frame without clipboard rights) the
 * old execCommand route, and failing that the text is left selected for Ctrl+C. */
export async function copyText(text: string, el?: HTMLElement | null): Promise<boolean> {
  try { await navigator.clipboard.writeText(text); return true; } catch { /* no clipboard API or no permission */ }
  const sel = typeof getSelection === "function" ? getSelection() : null;
  if (el && sel) { const r = document.createRange(); r.selectNodeContents(el); sel.removeAllRanges(); sel.addRange(r); }
  try { if (el && document.execCommand?.("copy")) return true; } catch { /* refused */ }
  return false;
}

export type Art = "empty" | "clear" | "search" | "plan" | "wait";

/** Small line drawings for empty states, in the theme's line and accent colours. */
function EmptyArt({ art }: { art: Art }) {
  const line = "var(--ae-line_strong)", acc = art === "clear" ? "var(--ae-ok_ink)" : "var(--ae-accent)";
  return (
    <svg className="ae-empty-art" width="72" height="52" viewBox="0 0 72 52" fill="none" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {art === "clear" && <><path d="M36 5 L56 12 V25 C56 37 47 44 36 48 C25 44 16 37 16 25 V12 Z" stroke={line} strokeWidth="2" /><path d="M27 26 L33.5 32.5 L46 20" stroke={acc} strokeWidth="3" /></>}
      {art === "search" && <><rect x="8" y="9" width="34" height="6" rx="3" fill={line} opacity=".5" /><rect x="8" y="21" width="24" height="6" rx="3" fill={line} opacity=".35" /><rect x="8" y="33" width="18" height="6" rx="3" fill={line} opacity=".2" /><circle cx="48" cy="26" r="11" stroke={acc} strokeWidth="2.5" /><path d="M56 34 L64 42" stroke={acc} strokeWidth="3" /></>}
      {art === "plan" && <><rect x="6" y="14" width="22" height="16" rx="4" stroke={line} strokeWidth="2" /><rect x="44" y="14" width="22" height="16" rx="4" stroke={line} strokeWidth="2" strokeDasharray="4 3" /><path d="M28 22 H44" stroke={line} strokeWidth="2" strokeDasharray="3 3" /><path d="M55 17 V27 M50 22 H60" stroke={acc} strokeWidth="2.5" /><path d="M14 40 H58" stroke={line} strokeWidth="2" opacity=".4" /></>}
      {art === "wait" && <><rect x="8" y="10" width="24" height="32" rx="4" stroke={line} strokeWidth="2" /><rect x="40" y="10" width="24" height="32" rx="4" stroke={line} strokeWidth="2" strokeDasharray="4 3" /><path d="M14 20 H26 M14 27 H24 M14 34 H22" stroke={line} strokeWidth="2" /><circle cx="52" cy="26" r="8" stroke={acc} strokeWidth="2" /><path d="M52 21 V26 L55 28" stroke={acc} strokeWidth="2.2" /></>}
      {art === "empty" && <><path d="M10 28 L18 10 H54 L62 28 V44 H10 Z" stroke={line} strokeWidth="2" /><path d="M10 28 H26 L30 34 H42 L46 28 H62" stroke={acc} strokeWidth="2.2" /></>}
    </svg>
  );
}

export function EmptyState({ title, children, art = "empty" }: { title: ReactNode; children?: ReactNode; art?: Art }) {
  return <div className={`ae-empty ae-empty-${art}`}><EmptyArt art={art} /><b>{title}</b>{children && <p>{children}</p>}</div>;
}

export interface BarPart { key: string; label: string; value: number; cls: string } // cls: an ae-bar-* colour

/** One stacked bar with its legend: parts sized by value. onPick makes each part (and its legend entry) a filter. */
export function StackBar({ parts, onPick, on, legend = true, label }: {
  parts: BarPart[]; onPick?: (key: string) => void; on?: string | null; legend?: boolean; label?: string;
}) {
  const total = parts.reduce((n, p) => n + p.value, 0) || 1;
  return (
    <div className="ae-stack">
      <div className={`ae-bar${onPick ? " ae-bar-pick" : ""}`} role={onPick ? "group" : "img"} aria-label={label ?? parts.map((p) => `${p.label} ${p.value}`).join(", ")}>
        {parts.map((p) => p.value > 0 && (onPick
          ? <button type="button" key={p.key} className={`ae-bar-${p.cls}${on === p.key ? " on" : ""}`} style={{ width: `${(100 * p.value) / total}%` }}
              aria-pressed={on === p.key} title={`${p.label}: ${p.value}`} onClick={() => onPick(p.key)}><span className="ae-sr">{p.label} {p.value}</span></button>
          : <span key={p.key} className={`ae-bar-${p.cls}`} style={{ width: `${(100 * p.value) / total}%` }} title={`${p.label}: ${p.value}`} />))}
      </div>
      {legend && (
        <div className="ae-bar-legend">
          {parts.map((p) => onPick
            ? <button type="button" key={p.key} className={`ae-bar-key${on === p.key ? " on" : ""}`} aria-pressed={on === p.key} disabled={!p.value} onClick={() => onPick(p.key)}>
                <span className={`ae-dot2 ae-bar-${p.cls}`} />{p.label} <b>{p.value}</b></button>
            : <span key={p.key}><span className={`ae-dot2 ae-bar-${p.cls}`} />{p.label} <b>{p.value}</b></span>)}
        </div>
      )}
    </div>
  );
}

/** A small bar for a table cell: the parts against `of` (the column's largest total), the number after it. */
export function MiniBar({ parts, of, text }: { parts: BarPart[]; of: number; text?: ReactNode }) {
  const total = parts.reduce((n, p) => n + p.value, 0);
  return (
    <span className="ae-mini" title={parts.filter((p) => p.value).map((p) => `${p.label}: ${p.value}`).join("\n")}>
      <span className="ae-mini-track">
        {parts.map((p) => p.value > 0 && <span key={p.key} className={`ae-bar-${p.cls}`} style={{ width: `${(100 * p.value) / Math.max(1, of)}%` }} />)}
      </span>
      <span className="ae-mini-n">{text ?? total}</span>
    </span>
  );
}

/** One dot per sensitive column: filled green when masked, an open red ring when anyone reads it in the clear. */
export function MaskDots({ columns }: { columns: { column: string; masked: boolean }[] }) {
  return (
    <span className="ae-dots" role="img" aria-label={`${columns.filter((c) => c.masked).length} of ${columns.length} columns masked`}>
      {columns.map((c) => <span key={c.column} className={`ae-dotm ${c.masked ? "ae-dotm-ok" : "ae-dotm-bad"}`} title={`${c.column}: ${c.masked ? "masked" : "not masked"}`} />)}
    </span>
  );
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
