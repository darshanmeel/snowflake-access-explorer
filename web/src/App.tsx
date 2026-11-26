// App shell: header (logo to Home, find, data mode, snapshot time, demo badge, theme), side nav in groups (Answers,
// Admin, Detail) that folds into a menu below 1000px, URL state with redirects from old links, page switch.
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { clearCache, get, peek, post, useApi } from "./api/client";
import type { FindItem, Meta, MineState, Page, Progress } from "./api/types";
import { Banner, Card, Combo, CsvOn, LoadLog, Root, SEVERITIES, SqlCtx, TOKENS, Waiting, type ThemeName } from "./components";
import { AppCtx, type Ctx, type Params } from "./ctx";
import { AccessPageView } from "./pages/Access";
import { AllActivityPageView } from "./pages/AllActivity";
import { ChangesPageView } from "./pages/Changes";
import { CheckPageView } from "./pages/Check";
import { ComparePageView } from "./pages/Compare";
import { ErrorBox, SqlPanel } from "./pages/common";
import { FlowPageView } from "./pages/Flow";
import { GraphPageView } from "./pages/Map";
import { HomePageView, openFound } from "./pages/Home";
import { scope } from "./pages/changeplan";
import { askedOf, startWith, type Asked } from "./pages/screens";
import { ObjectPageView } from "./pages/Object";
import { RequestPageView } from "./pages/Request";
import { ReviewPageView } from "./pages/Review";
import { RolePageView } from "./pages/Role";
import { RulesPageView } from "./pages/Rules";
import { SeePageView } from "./pages/See";
import { SensitivePageView } from "./pages/Sensitive";
import { ObjectUsePageView } from "./pages/ObjectUse";
import { UsagePageView } from "./pages/Usage";
import { WhatIfPageView } from "./pages/Whatif";
import { UserPage } from "./pages/User";

// server.SHARED_ONLY: pages about everyone, not in My access (home is in both)
const SHARED_ONLY: Page[] = ["review", "flow", "changes", "objuse", "activity"];
/** The page to show after switching to the shared view or My access. */
export const viewPage = (page: Page, mine: boolean): Page => (mine && SHARED_ONLY.includes(page) ? "access" : page);
const PAGES: Page[] = ["home", "access", "user", "role", "object", "check", "graph", "see", "compare", "request", "sensitive", "flow", "rules", "review", "whatif", "usage", "objuse", "activity", "changes"];
const LABEL: Record<Page, string> = {
  home: "Home", access: "Access", user: "User paths", role: "Role paths", object: "An object", check: "Can they?", graph: "Access graph",
  see: "What they see", compare: "Compare", request: "Request access",
  sensitive: "Sensitive data", flow: "How it flows", rules: "Risks", review: "Review & sign-off", whatif: "Change plan",
  usage: "Grants to trim", objuse: "Objects", activity: "Activity", changes: "What changed",
};

/** Old links to the new screens (docs/redesign-notes.md). No page: Home; an unknown page: Home. */
export function redirect(page: string | null, params: Params): { page: Page; params: Params } {
  if (page === "admins" || (page === "rules" && params.tab === "admins")) {
    const { tab: _t, ...rest } = params;
    return { page: "object", params: { ...rest, preset: "admin" } };
  }
  if (page === "who") return { page: "object", params };
  if (page === "rules" && params.st === "stale") { const { st: _s, ...rest } = params; return { page: "rules", params: { ...rest, part: "stale" } }; }
  if (page === "me") return redirect("access", params); // the brief's /me: My access, see mine()
  if (page === "object" && params.by === "path") { // Who has access by path: the access graph from this table (screen 4)
    const { by: _b, name, ...rest } = params;
    return { page: "graph", params: { ...rest, ...(name ? { table: name } : {}) } };
  }
  if (page === "rules" && params.tab === "rules") { const { tab: _t, ...rest } = params; return { page: "rules", params: { ...rest, show: "list" } }; } // screen 10
  if (page === "review" && params.scope && !params.show) return { page: "review", params: { ...params, show: "grid" } }; // screen 6 scope chips
  if (page === "whatif" && params.by && !params.show) return { page: "whatif", params: { ...params, show: "plan" } }; // screen 11 group by
  if (page === "see" && params.only) { // ?only=sensitive is the default, only=all shows every protected object
    const { only, ...rest } = params;
    return redirect("see", { ...rest, ...(only === "all" ? { all: "1" } : {}) });
  }
  if (page === "access" && params.filter && !params.show) return redirect("access", { ...params, show: "summary" }); // filter chips live there
  if (page === "rulelist" || page === "risks") return { page: "rules", params: { ...params, show: page === "risks" ? "fixes" : "list" } }; // screens 10 and 5
  if (page === "catalog") return { page: "sensitive", params: { ...params, show: "catalog" } }; // screen 8
  if (page === "dataflow" || (page === "sensitive" && params.show === "flow")) { // screen 16
    const { show: _s, ...rest } = params;
    return { page: "flow", params: rest };
  }
  if (page === "signoff") return { page: "review", params: { ...params, show: "grid" } }; // screen 6
  if (page === "history" || page === "diff") return { page: "changes", params }; // screen 14
  if (page === "unused" || page === "used" || ((page === "access" || page === "user" || page === "role") && params.show === "usage")) { // screen 13
    const { show: _s, name, ...rest } = params;
    return { page: "usage", params: { ...rest, ...(name ? { [page === "role" ? "role" : "user"]: name } : {}) } };
  }
  if (page === "plan") return { page: "whatif", params: { ...params, show: "plan" } }; // screen 11 on the change plan
  if ((page === "user" || page === "role") && params.part && ["sees", "sens", "usage"].includes(params.part)) { // old tabs, now on screen 7
    const { name, ...rest } = params;
    return { page: "see", params: { ...rest, ...(name ? { [page]: name } : {}) } };
  }
  if (page === "sensitive" && (params.a || params.b || [params.tab, params.part, params.show].includes("compare"))) { // Compare two roles, now screen 9
    const { tab: _t, part: _p, show: _s, ...rest } = params;
    return { page: "compare", params: { ...rest, scope: "sensitive" } };
  }
  if (page === "compare" && params.show) { // the old "What each sees" and "Differences" tabs are one view now
    const { show: _s, ...rest } = params;
    return { page: "compare", params: rest };
  }
  if ((page === "check" || page === "request") && (params.who || params.what)) { // the brief's ?who=&what=&do= links
    const { who, what, ...rest } = params;
    return { page, params: { ...rest, ...(who ? { name: who } : {}), ...(what ? { obj: what } : {}) } };
  }
  if ((page === "check" || page === "request") && params.user && !params.name) { // user= as on the Access screen: name= here
    const { user, ...rest } = params;
    return { page, params: { ...rest, name: user } };
  }
  if (!page || !PAGES.includes(page as Page)) return { page: "home", params };
  if ((page === "access" || page === "see" || page === "usage") && params.name) {
    const { name, ...rest } = params;
    return { page, params: { ...rest, user: name } };
  }
  return { page: page as Page, params };
}

interface Loc { page: Page; params: Params; mine: boolean }

/** What the My access card says about where your access is kept (cache.py: memory and .cache/ until read again). */
export const mineText = (hours: number | undefined) =>
  `This reads what you can reach with your own role, once, and keeps it in the server's memory${
    hours ? " and in .cache/ on this machine" : " only"} until you reload it. Nothing is written to Snowflake.`;

/** My access: ?data=mine, or the brief's ?page=me. */
/** Pages that show the default user when the URL names nobody: their SQL is for that user. */
const PERSON = new Set(["access", "see", "check", "usage", "user", "request"]);

export const mine = (page: string | null, data: string | null) => data === "mine" || page === "me";

function read(): Loc {
  const u = new URLSearchParams(location.search);
  const params: Params = {};
  u.forEach((v, k) => { if (k !== "page" && k !== "data") params[k] = v; });
  return { ...redirect(u.get("page"), params), mine: mine(u.get("page"), u.get("data")) };
}

function url(l: Loc) {
  const u = new URLSearchParams({ page: l.page });
  if (l.mine) u.set("data", "mine");
  for (const [k, v] of Object.entries(l.params)) if (v) u.set(k, v);
  return `?${u}`;
}

function useLoc() {
  const [loc, setLoc] = useState<Loc>(read);
  useEffect(() => { const f = () => setLoc(read()); addEventListener("popstate", f); return () => removeEventListener("popstate", f); }, []);
  const go = useCallback((n: Loc, replace = false, stay = false) => {
    history[replace ? "replaceState" : "pushState"](null, "", url(n));
    setLoc(n);
    if (!stay) scrollTo(0, 0);
  }, []);
  return [loc, go] as const;
}

function useTheme(): [ThemeName, () => void] {
  const [t, setT] = useState<ThemeName>(() => {
    try { const s = localStorage.getItem("ae-theme"); if (s === "light" || s === "dark") return s; } catch { /* no storage */ }
    return "light";  // light by default; the top-bar button switches and the choice is kept in this browser
  });
  useEffect(() => { document.body.style.background = TOKENS[t].bg; }, [t]);
  return [t, () => setT((x) => { const n = x === "dark" ? "light" : "dark"; try { localStorage.setItem("ae-theme", n); } catch { /* no storage */ } return n; })];
}

/** Top-bar search: people, roles and objects, ArrowUp / ArrowDown and Enter, closes on a click elsewhere. */
export function Find({ view, onOpen }: { view: string; onOpen: (i: FindItem) => void }) {
  return (
    <div className="find">
      <Combo<FindItem> label="Find" placeholder="Find anything" value="" clear min={2} wait={180} keyOf={(i) => i.id} onPick={onOpen}
        search={(q) => get<{ items: FindItem[] }>("find", { q, view, limit: "20" }).then((r) => r.items)}
        render={(i) => <><span className="ae-mono">{i.name}{i.sensitive && <span className="ae-sens-word"> · sensitive</span>}</span><span className="ae-muted">{i.kind_label}</span></>} />
    </div>
  );
}

/** Below 1000 px (the usual Streamlit width) the side menu folds; it follows the window as it is resized. */
function useWide() {
  const q = "(max-width: 1000px)";
  const [wide, setWide] = useState(() => typeof matchMedia !== "function" || !matchMedia(q).matches);
  useEffect(() => {
    if (typeof matchMedia !== "function") return;
    const m = matchMedia(q);
    const f = () => setWide(!m.matches);
    m.addEventListener?.("change", f);
    return () => m.removeEventListener?.("change", f);
  }, []);
  return wide;
}

/** Printed (Save as PDF) only: what the page is about, the data it shows, and the findings per severity in colour. */
function PrintHead({ meta, page, params }: { meta: Meta; page: Page; params: Params }) {
  const who = ["user", "role", "name", "a", "obj"].map((k) => params[k]).filter(Boolean).join(" · ");
  const per = SEVERITIES.map((s) => [s, Object.values(meta.rule_sev?.[s] ?? {}).reduce((t, v) => t + v, 0)] as const).filter(([, v]) => v);
  return (
    <header className="ae-print-head">
      <div className="ae-ph-title">{LABEL[page]}{who ? `: ${who}` : ""}</div>
      <div className="ae-ph-scope">Access explorer · {meta.view === "mine" ? "My access" : "shared snapshot"}{meta.run ? ` · data ${meta.run.when}` : ""} · printed {new Date().toISOString().slice(0, 16).replace("T", " ")}</div>
      {per.length > 0 && <div className="ae-ph-sev">Findings: {per.map(([s, v]) => <span key={s} className={`ae-sevpill ae-sev-${s}`}>{v.toLocaleString("en-US")} {s.toLowerCase()}</span>)}</div>}
    </header>
  );
}

/** 96412 -> "96k", 1234567 -> "1.2M": side menu counts stay one short word; the exact number is in the tooltip. */
export const short = (n: number) => n < 1000 ? String(n) : n < 1e6 ? `${+(n / 1e3).toFixed(n < 1e4 ? 1 : 0)}k` : `${+(n / 1e6).toFixed(1)}M`;

/** The menu: one entry per question. An entry with several pages opens its first; the others are tabs on top of it. */
const MENU: [string, { label: string; pages: Page[]; role?: boolean }[]][] = [
  ["", [{ label: "Home", pages: ["home"] }]],
  ["Ask", [{ label: "Can they?", pages: ["check"] }, { label: "A person", pages: ["access", "see", "user"] }, { label: "A role", pages: ["access", "see", "role"], role: true },
    { label: "An object", pages: ["object"] }, { label: "Access graph", pages: ["graph"] }, { label: "Activity", pages: ["activity"] }, { label: "Compare & request", pages: ["compare", "request"] }]],
  ["Act", [{ label: "Risks", pages: ["rules"] }, { label: "Sensitive data", pages: ["sensitive", "flow"] },
    { label: "Used or not", pages: ["objuse", "usage"] }, { label: "Change plan", pages: ["whatif"] }]],
  ["Govern", [{ label: "Review & sign-off", pages: ["review"] }, { label: "What changed", pages: ["changes"] }]],
];
const NAV_HIDDEN = new Set<Page>(["user", "role"]); // Access shows them; the pages still open from links

/** The pages shown as tabs above this one: its menu entry's, when it has more than one here. */
export function family(page: Page, here: Page[]): Page[] {
  const f = MENU.flatMap(([, es]) => es).find((e) => e.pages.includes(page));
  const xs = (f?.pages ?? []).filter((p) => here.includes(p) && (!NAV_HIDDEN.has(p) || p === page));
  return xs.length > 1 && page !== "access" ? xs : []; // a person's first page links What they see itself
}

function Side({ meta, page, params, nav, onShut, foot, asked }: { meta: Meta; page: Page; params: Params; nav: (p: Page, params?: Params) => void; onShut: () => void; foot: ReactNode; asked: Asked }) {
  const wide = useWide();
  const menu = useRef<HTMLDetailsElement>(null);
  useEffect(() => { if (menu.current) menu.current.open = wide; }, [wide, page]); // narrow: a pick folds the menu again
  const here = meta.pages.map((p) => p.key);
  return (
    <aside className="side">
      {wide && <button type="button" className="side-hide" onClick={onShut} title="Hide the menu: the page takes the full width" aria-label="Hide the menu">«</button>}
      <details className="side-menu" ref={menu} open={wide}>
        <summary>Menu · {LABEL[page]}</summary>
        {MENU.map(([title, es]) => {
          const xs = es.map((e) => ({ ...e, first: e.pages.find((p) => here.includes(p)) })).filter((e) => e.first);
          return xs.length ? (
            <nav key={title} aria-label={title || undefined}>
              {title && <h4>{title}</h4>}
              {xs.map((e) => {
                const on = e.pages.includes(page) && (e.role == null && e.label !== "A person" ? true : !!e.role === (page === "role" || !!params.role || params.kind === "role"));
                return <button key={e.label} type="button" className={on ? "on" : ""} aria-current={on ? "page" : undefined}
                  onClick={() => nav(e.first!, e.role ? (asked.role ? { role: asked.role } : { kind: "role" }) : e.label === "A person" ? (asked.user ? { user: asked.user } : {}) : undefined)}><span>{e.label}</span></button>;
              })}
            </nav>
          ) : null;
        })}
      </details>
      {meta.notes.length > 0 && (
        <details className="side-notes" id="side-notes">
          <summary><span className="side-notes-dot" />Incomplete · {meta.notes.length} source{meta.notes.length === 1 ? "" : "s"}</summary>
          <ul>
            {meta.notes.map((n) => (
              <li key={n.key}>
                <b>{n.title}</b>
                <span>{n.meaning}</span>
                {n.fix && <span className="side-notes-fix">Fix: {n.fix}</span>}
                {n.raw && (
                  <details className="side-notes-raw">
                    <summary>Snowflake error</summary>
                    <code>{n.raw}</code>
                  </details>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
      {foot}
    </aside>
  );
}

/** The tools used now and then, behind one button next to the name; a pick, Escape or a click elsewhere closes it. */
export function More({ children }: { children: ReactNode }) {
  const box = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const shut = (e: Event) => {
      const d = box.current;
      if (!d?.open) return;
      if (e instanceof KeyboardEvent) { if (e.key === "Escape") { d.open = false; d.querySelector("summary")?.focus(); } }
      else if (!d.contains(e.target as Node) || (e.target as Element).closest("button.ae-btn")) d.open = false;
    };
    addEventListener("click", shut);
    addEventListener("keydown", shut);
    return () => { removeEventListener("click", shut); removeEventListener("keydown", shut); };
  }, []);
  return <details className="top-more" ref={box}><summary>More</summary><div>{children}</div></details>;
}

/** Side panel "Data": where the data shown comes from, how long it is kept, and the DuckDB copy to query with SQL. */
export function DataInfo({ meta }: { meta: Meta }) {
  if (!meta.run) return null;
  const sq = meta.sql_copy;
  const from = meta.mode === "fake" ? "fake data in access.py" : meta.view === "mine" ? "Snowflake, with your own role"
    : meta.source === "direct" ? `Snowflake, read directly with ${meta.inside ? "the app owner's role" : "your role"} (SOURCE=direct)` : `the snapshot tables in ${meta.where} (SOURCE=objects)`;
  return (
    <details className="side-notes side-data">
      <summary><span className="side-data-dot" />Data source</summary>
      <ul>
        <li><b>Source</b><span>{from}{meta.fetched_at ? `, read ${meta.fetched_at}` : ""}.</span></li>
        <li><b>Kept</b><span>In memory{meta.cache_hours && meta.mode !== "fake" ? " and in .cache/ on this machine" : ""}, until ↻ reads again.</span></li>
        <li>
          <b>SQL copy (DuckDB)</b>
          {sq?.on && sq.schema ? (
            <span>
              <code className="side-data-path">{sq.path}</code>, schema <code>{sq.schema}</code>: the TBL_ACCESS_ tables of this read
              {sq.written_at ? ` (written ${sq.written_at})` : " (written at the next read from Snowflake)"}, the read before as TBL_ACCESS_…_PREV.
              {sq.note && <span className="side-notes-fix">{sq.note}</span>}
            </span>
          ) : <span>{sq?.note ?? "None."}</span>}
        </li>
      </ul>
    </details>
  );
}

/** "13 h ago" / "17 days ago" of epoch seconds at, from now (ms). */
export const ago = (at: number, now: number) => {
  const h = Math.max(0, (now / 1000 - at) / 3600);
  return h < 48 ? `${Math.round(h)} h ago` : `${Math.round(h / 24)} days ago`;
};

/** The data's age in the top bar, aged here every minute (a tab left open overnight still tells the truth): the dot
 * green under 24 h, amber over, red over 7 days, said in words when stale; a .cache/ copy read over 24 h ago says so. */
function DataTime({ meta, reload, busy }: { meta: Meta; reload: () => void; busy: boolean }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), 60_000); return () => clearInterval(t); }, []);
  if (!meta.run) return null;
  const what = meta.mode === "fake" ? "Data" : meta.source === "direct" ? "Read" : "Snapshot";
  const sq = meta.sql_copy?.on && meta.sql_copy.schema ? ` · SQL copy: ${meta.sql_copy.path} (schema ${meta.sql_copy.schema})` : "";
  const at = meta.run.at, h = at ? (now / 1000 - at) / 3600 : meta.run.old ? 25 : 0;
  const tone = meta.mode === "fake" ? "" : h > 24 * 7 ? " stale" : h > 24 ? " old" : "";
  const when = at ? `${meta.run.when.split(" · ")[0]} · ${tone ? `Stale: ${ago(at, now).replace(" ago", " old")}` : ago(at, now)}` : meta.run.when;
  const cached = meta.fetched_ts && now / 1000 - meta.fetched_ts > 24 * 3600 ? ` · read from cache ${meta.fetched_at}` : "";
  return (
    <span className={`top-time${tone}`} title={meta.fetched_at || sq ? `${meta.fetched_at ? `Read ${meta.fetched_at}` : ""}${sq}` : undefined}>
      <span className="top-time-dot" aria-hidden />{what} {when}{cached}
      <button type="button" className="side-reload" onClick={reload} disabled={busy} title={meta.mode === "fake" ? "Reload" : "Read Snowflake again"} aria-label="Read again">↻</button>
    </span>
  );
}

const VIEWS: Record<Page, () => JSX.Element> = {
  home: HomePageView, access: AccessPageView, user: UserPage, role: RolePageView, object: ObjectPageView, check: CheckPageView,
  graph: GraphPageView, see: SeePageView, compare: ComparePageView, request: RequestPageView,
  sensitive: SensitivePageView, flow: FlowPageView, rules: RulesPageView, review: ReviewPageView, whatif: WhatIfPageView,
  usage: UsagePageView, objuse: ObjectUsePageView, activity: AllActivityPageView, changes: ChangesPageView,
};

/** onUrl: the Streamlit wrapper mirrors the page's URL params into the browser address bar. */
export function App({ onUrl }: { onUrl?: (query: string) => void } = {}) {
  const [loc, go] = useLoc();
  useEffect(() => { onUrl?.(url(loc)); }, [loc]);
  const [theme, flip] = useTheme();
  // Save as PDF (or Ctrl+P): the browser's print, in the light theme, the open page and tab only (app.css @media print)
  const [printing, setPrinting] = useState(false);
  useEffect(() => {
    const on = () => flushSync(() => setPrinting(true)), off = () => setPrinting(false);
    window.addEventListener("beforeprint", on);
    window.addEventListener("afterprint", off);
    return () => { window.removeEventListener("beforeprint", on); window.removeEventListener("afterprint", off); };
  }, []);
  const [busy, setBusy] = useState("");
  const [sql, setSql] = useState<string | null>(null);  // the "SQL behind this page" panel: the card it was opened from
  const [notice, setNotice] = useState<{ tone: "info" | "bad"; title: string; text: string } | null>(null);
  const view = loc.mine ? "mine" : "shared";
  const m = useApi<Meta>("meta", { view });
  const meta = m.data;
  scope(meta?.data_id); // before any page reads what the browser kept
  const poll = useCallback(() => peek<Progress>("progress"), []);

  const at = useRef(loc);
  at.current = loc;
  const nav = useCallback((page: Page, params: Params = {}) => go({ page, params, mine: loc.mine }), [go, loc.mine]);
  const set = useCallback((patch: Record<string, string | null | undefined>, o: { push?: boolean; stay?: boolean } = {}) => {
    const params = { ...at.current.params }; // the newest URL: two picks before a redraw must not undo each other
    for (const [k, v] of Object.entries(patch)) { if (v) params[k] = v; else delete params[k]; }
    at.current = { ...at.current, params };
    go(at.current, !o.push, o.stay);
  }, [go]);
  const asked = useRef<Asked>({}); // kept across pages opened from the side menu
  useEffect(() => { if (!loc.mine) asked.current = askedOf(loc.page, loc.params, asked.current); }, [loc]);
  const setView = (mine: boolean) => go({ page: viewPage(loc.page, mine), params: {}, mine });

  // one at a time: a second click while Snowflake is being read does nothing (the buttons are disabled too)
  const running = useRef(false);
  const run = async (label: string, f: () => Promise<unknown>) => {
    if (running.current) return;
    running.current = true;
    setBusy(label);
    setNotice(null);
    try { await f(); } catch (e) { setNotice({ tone: "bad", title: `${label.replace(/….*$/, "")} failed`, text: (e as Error).message }); }
    finally { running.current = false; clearCache(); setBusy(""); }
  };
  const loadMine = (fresh = false) => run("Loading your access…", async () => { await post<MineState>(fresh ? "mine/load?fresh=1" : "mine/load"); setView(true); });
  const loadShared = () => run("Reading Snowflake… this can take a few minutes", () => post("reload", { what: "load" }));
  // Read Snowflake again / Rebuild snapshot: the server reads in the background (started) while the pages keep the
  // data they have; inside Streamlit it answers when done
  const [bg, setBg] = useState<{ job: number; what: string; line: string } | null>(null);
  const [logOpen, setLogOpen] = useState(false);  // the load log: its own panel, opened from the top bar
  const [shut, setShutState] = useState(() => { try { return localStorage.getItem("ae-side") === "shut"; } catch { return false; } });
  const setShut = (v: boolean) => { setShutState(v); try { localStorage.setItem("ae-side", v ? "shut" : "open"); } catch { /* no storage */ } };
  const title = (what: string, ok: boolean | null) => what === "rebuild" ? (ok ? "Snapshot rebuilt" : "Snapshot not rebuilt")
    : ok ? "Read Snowflake again" : "Read Snowflake again failed";
  const refresh = (what: "page" | "rebuild") => run(what === "rebuild" ? "Rebuilding snapshot…" : "Reading Snowflake…", async () => {
    const r = await post<{ ok: boolean; message: string; started?: boolean; job?: number }>("reload", { what });
    if (r.started && r.job) setBg({ job: r.job, what, line: r.message });
    else if (r.message && (what === "rebuild" || !r.ok)) setNotice({ tone: r.ok ? "info" : "bad", title: title(what, r.ok), text: r.message });
  });
  const reload = () => refresh("page");
  const rebuild = () => refresh("rebuild");
  useEffect(() => {
    if (!bg) return;
    let live = true, timer = 0;
    const tick = () => {
      timer = window.setTimeout(() => poll().then((p) => {
        if (!live || !p) return;
        const j = p.job;
        if (!j || j.id !== bg.job) {  // the server restarted: that refresh is gone
          clearCache();
          setBg(null);
          setNotice({ tone: "bad", title: title(bg.what, false), text: "The server restarted during it: click again." });
          return;
        }
        if (j.state !== "running") {  // done: the pages fetch the new data; failed: the old stays
          clearCache();
          setBg(null);
          setNotice({ tone: j.ok ? "info" : "bad", title: title(bg.what, j.ok), text: j.message ?? "" });
          return;
        }
        const last = p.lines[p.lines.length - 1]?.text;
        if (last) setBg((b) => b && { ...b, line: last });
        tick();
      }, () => live && tick()), 1000);
    };
    tick();
    return () => { live = false; clearTimeout(timer); };
  }, [bg?.job]);

  const ctx: Ctx | null = useMemo(() => meta && {
    page: loc.page, params: loc.params, view, meta, theme, nav, set,
  }, [meta, loc, view, theme, nav, set]);

  useEffect(() => { document.title = `${LABEL[loc.page]} · Access explorer`; }, [loc.page]);

  const Body = VIEWS[loc.page];
  const fam = family(loc.page, meta?.pages.map((p) => p.key) ?? []);
  const needMine = loc.mine && meta && !meta.mine.loaded;
  const needShared = !loc.mine && meta?.error?.detail === "shared_not_loaded";
  const loadingShared = !loc.mine && meta?.error?.detail === "shared_loading";  // another tab's or the first page's load
  useEffect(() => {  // ask again once that load is done
    if (!loadingShared) return;
    const t = window.setInterval(() => poll().then((p) => { if (p && !p.running) clearCache(); }, () => undefined), 1500);
    return () => clearInterval(t);
  }, [loadingShared, poll]);
  // the first load: everything but its log waits (inert: no clicks, no keyboard); a refresh keeps the page usable
  const lock = loadingShared || (!!busy && !meta?.loaded) ? ({ inert: "", "aria-busy": true } as Record<string, unknown>) : {};
  const hasData = !!meta?.loaded;
  const controls = (
    <span className="top-right">
            {meta && <DataTime meta={meta} reload={reload} busy={!!busy || !!bg} />}
            {meta && meta.notes.length > 0 && <button type="button" className="top-chip top-incomplete" onClick={() => { setShut(false); requestAnimationFrame(() => { const n = document.getElementById("side-notes") as HTMLDetailsElement | null; if (n) { n.open = true; n.scrollIntoView({ block: "nearest" }); } }); }}
              title={meta.notes.map((n) => `${n.title}: ${n.meaning}`).join("\n")}><span className="side-notes-dot" aria-hidden />Incomplete · {meta.notes.length}</button>}
            {meta?.mode === "fake" && <span className="top-demo" title="Fake accounts, roles and tables. Run without --fake (FAKE=1), with the connection in .env, to read Snowflake.">Demo data</span>}
            {hasData && <button className="ae-btn" onClick={() => setSql("")} title="The SQL behind this page, to run yourself (every card has its own </> mark too)">{"</>"} SQL</button>}
            <button type="button" className="ae-btn" onClick={() => setLogOpen(!logOpen)} aria-expanded={logOpen} title="What the app did while loading, step by step">Log</button>
            {meta?.mine_available !== false && <button className="ae-btn" aria-pressed={loc.mine} disabled={!!busy && !loc.mine && !meta?.mine.loaded} title={loc.mine ? "Back to everyone: the shared snapshot" : "Only what you can reach, read as you"}
              onClick={() => (loc.mine ? setView(false) : meta?.mine.loaded ? setView(true) : loadMine())}>{loc.mine ? "Everyone" : "My access"}</button>}
          </span>
  );
  return (
    <Root theme={printing ? "light" : theme}>
      <SqlCtx.Provider value={hasData ? setSql : null}>
      <CsvOn.Provider value={meta?.csv !== false}>
      <div className={`app${shut ? " side-shut" : ""}`}>
        <div className="left">
        <header className="top">
          <button type="button" className="top-logo" onClick={() => nav("home")} aria-label="Access explorer: home">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg>
            Access explorer
          </button>
          <More>
            {hasData && <button type="button" className="ae-btn" onClick={() => window.print()} title="Print this page with its open tab, or save it as a PDF">Save as PDF</button>}
            <button type="button" className="ae-btn" onClick={flip}>{theme === "dark" ? "Light" : "Dark"}</button>
            {!loc.mine && meta && meta.mode !== "fake" && <button type="button" className="ae-btn" onClick={rebuild} disabled={!!busy || !!bg} title="Runs the snapshot procedure in Snowflake">Rebuild snapshot</button>}
            {meta && <DataInfo meta={meta} />}
          </More>
          <div className="top-lock" {...lock}>
          <Find view={view} onOpen={(i) => openFound(i, nav)} />
          {loc.mine && <span className="top-demo">My access</span>}
          {meta?.mine_available === false && <span className="ae-muted top-chip" title={meta.mine_note ?? undefined}>My access: off{meta.inside ? " (owner's rights)" : ""}</span>}
          {loc.mine && meta?.mine.loaded && <button className="ae-btn" onClick={() => loadMine(true)} disabled={!!busy} title={`Loaded ${meta.mine.loaded_at ?? ""}`}>Reload my access</button>}
          {bg && (
            <button type="button" className="ae-btn top-bg" onClick={() => setLogOpen(!logOpen)} aria-expanded={logOpen}
              title="The pages keep the data they have until the new read is ready. Click for the full log.">
              <span className="ae-spin" aria-hidden /><b>{bg.what === "rebuild" ? "Rebuilding" : "Reading again"}:</b>&nbsp;<span className="top-bg-line">{bg.line}</span>
            </button>
          )}
          </div>
          {busy && <span className="ae-muted top-busy" role="status"><span className="ae-spin" aria-hidden />{busy}</span>}
        </header>
        <div className="top-lock" {...lock}>
        {!meta ? <aside className="side">{controls}</aside> : shut
          ? <aside className="side side-rail"><button type="button" className="side-open" onClick={() => setShut(false)} title="Show the menu" aria-label="Show the menu">»</button>{controls}</aside>
          : <Side meta={meta} page={loc.page} params={loc.params} asked={loc.mine ? {} : asked.current} nav={(p, params) => nav(p, params ?? startWith(p, loc.mine ? {} : asked.current))} onShut={() => setShut(true)} foot={controls} />}
        </div>
        </div>
        <main className="main">
          {meta && <PrintHead meta={meta} page={loc.page} params={loc.params} />}
          {sql !== null && hasData && <SqlPanel page={loc.page} hint={sql} params={{ ...(PERSON.has(loc.page) && !["user", "role", "name", "a"].some((k) => loc.params[k]) ? { user: meta?.default_user ?? undefined } : {}), ...loc.params, view }} onClose={() => setSql(null)} />}
          {notice && (
            <Banner tone={notice.tone} title={notice.title} lines={[notice.text]}>
              <button type="button" className="ae-btn ae-btn-s" onClick={() => setNotice(null)}>Dismiss</button>
            </Banner>
          )}
          <LoadLog active={!!busy || m.loading || loadingShared || !!bg} open={logOpen} onClose={() => setLogOpen(false)} poll={poll} />
          {m.error && <ErrorBox e={m.error} />}
          {!meta && !m.error && <Waiting />}
          {needMine && (
            <Card title="My access">
              <p>{mineText(meta.cache_hours)}</p>
              <button className="ae-btn" onClick={() => loadMine()} disabled={!!busy}>Load my access</button>
            </Card>
          )}
          {needShared && (
            <Card title="Shared data">
              <p>Reads every role, user and grant of the account with {meta?.inside ? "the app owner's role" : "your role"}, once, and keeps it until you read it again.
                Without ACCOUNT_USAGE it sends a SHOW per role, so a big account can take a few minutes.</p>
              <div className="ae-row">
                <button className="ae-btn ae-btn-primary" onClick={loadShared} disabled={!!busy}>Load shared data</button>
                {meta?.mine_available !== false && <button className="ae-btn" onClick={() => loadMine()} disabled={!!busy}>Only my access</button>}
              </div>
            </Card>
          )}
          {loadingShared && !busy && <p className="ae-muted" role="status">The shared data is being read from Snowflake: the pages open when it is done.</p>}
          {ctx && !needMine && !needShared && !loadingShared && (
            <AppCtx.Provider value={ctx}>
              {fam.length > 0 && (
                <nav className="ae-family" aria-label={LABEL[loc.page]}>
                  {fam.map((p) => <button key={p} type="button" className={p === loc.page ? "on" : ""} aria-current={p === loc.page ? "page" : undefined}
                    onClick={() => { if (p !== loc.page) nav(p, startWith(p, loc.mine ? {} : asked.current)); }}>{LABEL[p]}</button>)}
                </nav>
              )}
              <Body key={`${view}:${loc.page}`} />
            </AppCtx.Provider>
          )}
        </main>
      </div>
      </CsvOn.Provider>
      </SqlCtx.Provider>
    </Root>
  );
}
