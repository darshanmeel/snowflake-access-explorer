// App shell: header (logo to Home, find, data mode, snapshot time, demo badge, theme), side nav in groups (Answers,
// Admin, Detail) that folds into a menu below 1000px, URL state with redirects from old links, page switch.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { clearCache, get, post, useApi } from "./api/client";
import type { FindItem, Meta, MineState, Page } from "./api/types";
import { Banner, Card, Combo, Root, SqlCtx, type ThemeName } from "./components";
import { AppCtx, type Ctx, type Params } from "./ctx";
import { AccessPageView } from "./pages/Access";
import { ChangesPageView } from "./pages/Changes";
import { CheckPageView } from "./pages/Check";
import { ComparePageView } from "./pages/Compare";
import { ErrorBox, SqlPanel } from "./pages/common";
import { FlowPageView } from "./pages/Flow";
import { GraphPageView } from "./pages/Map";
import { HomePageView, openFound } from "./pages/Home";
import { ObjectPageView } from "./pages/Object";
import { RequestPageView } from "./pages/Request";
import { ReviewPageView } from "./pages/Review";
import { RolePageView } from "./pages/Role";
import { RulesPageView } from "./pages/Rules";
import { SeePageView } from "./pages/See";
import { SensitivePageView } from "./pages/Sensitive";
import { UsagePageView } from "./pages/Usage";
import { WhatIfPageView } from "./pages/Whatif";
import { UserPage } from "./pages/User";

// server.SHARED_ONLY: pages about everyone, not in My access (home is in both)
const SHARED_ONLY: Page[] = ["review", "flow", "changes"];
/** The page to show after switching to the shared view or My access. */
export const viewPage = (page: Page, mine: boolean): Page => (mine && SHARED_ONLY.includes(page) ? "access" : page);
const PAGES: Page[] = ["home", "access", "user", "role", "object", "check", "graph", "see", "compare", "request", "sensitive", "flow", "rules", "review", "whatif", "usage", "changes"];
const LABEL: Record<Page, string> = {
  home: "Home", access: "Access", user: "User paths", role: "Role paths", object: "Object", check: "Can they?", graph: "Access graph",
  see: "What they see", compare: "Compare", request: "Request access",
  sensitive: "Sensitive data", flow: "Sensitive data flow", rules: "Risks & fixes", review: "Review & sign-off", whatif: "What if",
  usage: "Granted vs used", changes: "What changed",
};
const GROUPS: [string, string][] = [["answers", "Answers"], ["admin", "Admin"], ["detail", "Detail"]];

/** Old links to the new screens (docs/redesign-notes.md). No page: Home; an unknown page: Home. */
export function redirect(page: string | null, params: Params): { page: Page; params: Params } {
  if (page === "admins" || (page === "rules" && params.tab === "admins")) {
    const { tab: _t, ...rest } = params;
    return { page: "object", params: { ...rest, preset: "admin" } };
  }
  if (page === "who") return { page: "object", params };
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
  if (page === "sensitive" && (params.a || params.b || params.tab === "compare")) { // Compare two roles, now screen 9
    const { tab: _t, ...rest } = params;
    return { page: "compare", params: { ...rest, scope: "sensitive" } };
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

/** What the My access card says about where your access is kept (cache.py: 24 h in memory, CACHE_HOURS on disk). */
export const mineText = (hours: number | undefined) =>
  `This reads what you can reach with your own role, once, and keeps it for 24 hours in the server's memory${
    hours ? ` and in .cache/ on this machine (CACHE_HOURS=${hours})` : " only (CACHE_HOURS=0: nothing on disk)"}. Nothing is written to Snowflake.`;

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
  const go = useCallback((n: Loc, replace = false) => {
    history[replace ? "replaceState" : "pushState"](null, "", url(n));
    setLoc(n);
    scrollTo(0, 0);
  }, []);
  return [loc, go] as const;
}

function useTheme(): [ThemeName, () => void] {
  const [t, setT] = useState<ThemeName>(() => {
    try { const s = localStorage.getItem("ae-theme"); if (s === "light" || s === "dark") return s; } catch { /* no storage */ }
    return "dark";  // dark by default; the top-bar button switches and the choice is kept in this browser
  });
  useEffect(() => { document.body.style.background = t === "dark" ? "#0F1216" : "#F6F7F9"; }, [t]);
  return [t, () => setT((x) => { const n = x === "dark" ? "light" : "dark"; try { localStorage.setItem("ae-theme", n); } catch { /* no storage */ } return n; })];
}

/** Top-bar search: people, roles and objects, ArrowUp / ArrowDown and Enter, closes on a click elsewhere. */
export function Find({ view, onOpen }: { view: string; onOpen: (i: FindItem) => void }) {
  return (
    <div className="find">
      <Combo<FindItem> label="Find" placeholder="Find a person, role or object" value="" clear min={2} wait={180} keyOf={(i) => i.id} onPick={onOpen}
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

function Side({ meta, page, nav }: { meta: Meta; page: Page; nav: (p: Page, params?: Params) => void }) {
  const wide = useWide();
  const menu = useRef<HTMLDetailsElement>(null);
  useEffect(() => { if (menu.current) menu.current.open = wide; }, [wide, page]); // narrow: a pick folds the menu again
  return (
    <aside className="side">
      <details className="side-menu" ref={menu} open={wide}>
        <summary>Menu · {LABEL[page]}</summary>
        {GROUPS.map(([g, title]) => {
          const ps = meta.pages.filter((p) => (p.group ?? "detail") === g);
          return ps.length ? (
            <nav key={g} aria-label={title}>
              <h4>{title}</h4>
              {ps.map((p) => (
                <button type="button" key={p.key} className={p.key === page ? "on" : ""} aria-current={p.key === page ? "page" : undefined} onClick={() => nav(p.key)}>
                  <span>{p.label}</span>
                  {p.badge != null && <span className={`ae-tab-count${p.severity ? ` ae-sevpill ae-sev-${p.severity}` : ""}`}>{p.severity ? `${p.badge} ${p.severity.toLowerCase()}` : p.badge}</span>}
                </button>
              ))}
            </nav>
          ) : null;
        })}
      </details>
      {meta.notes.length > 0 && (
        <details className="side-notes">
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
      <DataInfo meta={meta} />
    </aside>
  );
}

/** Side panel "Data": where the data shown comes from, how long it is kept, and the DuckDB copy to query with SQL. */
export function DataInfo({ meta }: { meta: Meta }) {
  if (!meta.run) return null;
  const sq = meta.sql_copy;
  const from = meta.mode === "fake" ? "fake data in access.py" : meta.view === "mine" ? "Snowflake, with your own role"
    : meta.source === "direct" ? `Snowflake, read directly with ${meta.inside ? "the app owner's role" : "your role"} (SOURCE=direct)` : `the snapshot tables in ${meta.where} (SOURCE=objects)`;
  return (
    <details className="side-notes side-data">
      <summary><span className="side-data-dot" />Data from {meta.run.when}</summary>
      <ul>
        <li><b>Source</b><span>{from}{meta.fetched_at ? `, read ${meta.fetched_at}` : ""}.</span></li>
        <li><b>Kept</b><span>24 h in memory{meta.cache_hours && meta.mode !== "fake" ? ` and ${meta.cache_hours} h in .cache/ on this machine` : ""}. ↻ reads again.</span></li>
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

function DataTime({ meta, reload, busy }: { meta: Meta; reload: () => void; busy: boolean }) {
  if (!meta.run) return null;
  const what = meta.mode === "fake" ? "Data" : meta.source === "direct" ? "Read" : "Snapshot";
  const sq = meta.sql_copy?.on && meta.sql_copy.schema ? ` · SQL copy: ${meta.sql_copy.path} (schema ${meta.sql_copy.schema})` : "";
  return (
    <span className={`top-time${meta.mode !== "fake" && meta.run.old ? " old" : ""}`} title={meta.fetched_at || sq ? `${meta.fetched_at ? `Read ${meta.fetched_at}` : ""}${sq}` : undefined}>
      <span className="top-time-dot" aria-hidden />{what} {meta.run.when}
      <button type="button" className="side-reload" onClick={reload} disabled={busy} title={meta.mode === "fake" ? "Reload" : "Read Snowflake again"} aria-label="Read again">↻</button>
    </span>
  );
}

const VIEWS: Record<Page, () => JSX.Element> = {
  home: HomePageView, access: AccessPageView, user: UserPage, role: RolePageView, object: ObjectPageView, check: CheckPageView,
  graph: GraphPageView, see: SeePageView, compare: ComparePageView, request: RequestPageView,
  sensitive: SensitivePageView, flow: FlowPageView, rules: RulesPageView, review: ReviewPageView, whatif: WhatIfPageView,
  usage: UsagePageView, changes: ChangesPageView,
};

/** onUrl: the Streamlit wrapper mirrors the page's URL params into the browser address bar. */
export function App({ onUrl }: { onUrl?: (query: string) => void } = {}) {
  const [loc, go] = useLoc();
  useEffect(() => { onUrl?.(url(loc)); }, [loc]);
  const [theme, flip] = useTheme();
  const [busy, setBusy] = useState("");
  const [sql, setSql] = useState<string | null>(null);  // the "SQL behind this page" panel: the card it was opened from
  const [notice, setNotice] = useState<{ tone: "info" | "bad"; title: string; text: string } | null>(null);
  const view = loc.mine ? "mine" : "shared";
  const m = useApi<Meta>("meta", { view });
  const meta = m.data;

  const nav = useCallback((page: Page, params: Params = {}) => go({ page, params, mine: loc.mine }), [go, loc.mine]);
  const set = useCallback((patch: Record<string, string | null | undefined>) => {
    const params = { ...loc.params };
    for (const [k, v] of Object.entries(patch)) { if (v) params[k] = v; else delete params[k]; }
    go({ ...loc, params }, true);
  }, [go, loc]);
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
  const reload = () => run("Reading Snowflake…", () => post("reload", { what: "page" }));
  const loadShared = () => run("Reading Snowflake… this can take a few minutes", () => post("reload", { what: "load" }));
  const rebuild = () => run("Rebuilding snapshot…", async () => {
    const r = await post<{ ok: boolean; message: string }>("reload", { what: "rebuild" });
    if (r.message) setNotice({ tone: r.ok ? "info" : "bad", title: r.ok ? "Snapshot rebuilt" : "Snapshot not rebuilt", text: r.message });
  });

  const ctx: Ctx | null = useMemo(() => meta && {
    page: loc.page, params: loc.params, view, meta, theme, nav, set,
  }, [meta, loc, view, theme, nav, set]);

  useEffect(() => { document.title = `${LABEL[loc.page]} · Access explorer`; }, [loc.page]);

  const Body = VIEWS[loc.page];
  const needMine = loc.mine && meta && !meta.mine.loaded;
  const needShared = !loc.mine && meta?.error?.detail === "shared_not_loaded";
  return (
    <Root theme={theme}>
      <SqlCtx.Provider value={setSql}>
      <div className="app">
        <header className="top">
          <button type="button" className="top-logo" onClick={() => nav("home")} aria-label="Access explorer: home">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg>
            Access explorer
          </button>
          <Find view={view} onOpen={(i) => openFound(i, nav)} />
          <div className="seg" role="group" aria-label="Data">
            <button className={!loc.mine ? "on" : ""} onClick={() => setView(false)}>Shared snapshot</button>
            {meta?.mine_available !== false && <button className={loc.mine ? "on" : ""} disabled={!!busy && !meta?.mine.loaded} onClick={() => (meta?.mine.loaded ? setView(true) : loadMine())}>My access</button>}
          </div>
          {loc.mine && meta?.mine.loaded && <button className="ae-btn" onClick={() => loadMine(true)} disabled={!!busy} title={`Loaded ${meta.mine.loaded_at ?? ""}`}>Reload my access</button>}
          {!loc.mine && meta && meta.mode !== "fake" && <button className="ae-btn" onClick={rebuild} disabled={!!busy} title="Runs the snapshot procedure in Snowflake">Rebuild snapshot</button>}
          <span className="top-right">
            {meta && <DataTime meta={meta} reload={reload} busy={!!busy} />}
            {meta?.mode === "fake" && <span className="top-demo" title="Fake accounts, roles and tables. Run without --fake (FAKE=1), with the connection in .env, to read Snowflake.">Demo data</span>}
            <span className="ae-muted top-sqlnote" title="Every card has a </> mark in its top-right corner; right-click works too">{"</>"} on any card: its SQL</span>
            <button className="ae-btn" onClick={() => setSql("")} title="The SQL behind this page, to run yourself (or right-click the page)">{"</>"} SQL</button>
            <button className="ae-btn" onClick={flip}>{theme === "dark" ? "Light" : "Dark"}</button>
          </span>
          {busy && <span className="ae-muted top-busy" role="status"><span className="ae-spin" aria-hidden />{busy}</span>}
        </header>
        {meta ? <Side meta={meta} page={loc.page} nav={(p, params) => nav(p, params ?? {})} /> : <aside className="side" />}
        {/* right-click the page: the SQL behind it (Shift + right-click keeps the browser's menu) */}
        <main className="main" onContextMenu={(e) => { if (e.shiftKey) return; e.preventDefault();
          setSql((e.target as HTMLElement).closest(".ae-card")?.querySelector("h3")?.textContent ?? ""); }}>
          {sql !== null && <SqlPanel page={loc.page} hint={sql} params={{ ...(PERSON.has(loc.page) && !["user", "role", "name", "a"].some((k) => loc.params[k]) ? { user: meta?.default_user ?? undefined } : {}), ...loc.params, view }} onClose={() => setSql(null)} />}
          {notice && (
            <Banner tone={notice.tone} title={notice.title} lines={[notice.text]}>
              <button type="button" className="ae-btn ae-btn-s" onClick={() => setNotice(null)}>Dismiss</button>
            </Banner>
          )}
          {m.error && <ErrorBox e={m.error} />}
          {!meta && !m.error && <p className="ae-muted">Loading…</p>}
          {needMine && (
            <Card title="My access">
              <p>{mineText(meta.cache_hours)}</p>
              <button className="ae-btn" onClick={() => loadMine()} disabled={!!busy}>Load my access</button>
            </Card>
          )}
          {needShared && (
            <Card title="Shared data">
              <p>Reads every role, user and grant of the account with {meta?.inside ? "the app owner's role" : "your role"}, once, and keeps it for 24 hours.
                Without ACCOUNT_USAGE it sends a SHOW per role, so a big account can take a few minutes.</p>
              <div className="ae-row">
                <button className="ae-btn ae-btn-primary" onClick={loadShared} disabled={!!busy}>Load shared data</button>
                {meta?.mine_available !== false && <button className="ae-btn" onClick={() => loadMine()} disabled={!!busy}>Only my access</button>}
              </div>
            </Card>
          )}
          {ctx && !needMine && !needShared && (
            <AppCtx.Provider value={ctx}>
              <Body key={`${view}:${loc.page}`} />
            </AppCtx.Provider>
          )}
        </main>
      </div>
      </SqlCtx.Provider>
    </Root>
  );
}
