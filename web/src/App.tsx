// App shell: header (logo to Home, find, data mode, snapshot time, demo badge, theme), side nav in groups (Answers,
// Admin, Detail) that folds into a menu below 1000px, URL state with redirects from old links, page switch.
import { useCallback, useEffect, useMemo, useState } from "react";
import { clearCache, get, post, useApi } from "./api/client";
import type { FindItem, Meta, MineState, Page } from "./api/types";
import { Card, Root, type ThemeName } from "./components";
import { AppCtx, type Ctx, type Params } from "./ctx";
import { AccessPageView } from "./pages/Access";
import { CheckPageView } from "./pages/Check";
import { ErrorBox } from "./pages/common";
import { HomePageView, remember } from "./pages/Home";
import { ObjectPageView } from "./pages/Object";
import { ReviewPageView } from "./pages/Review";
import { RolePageView } from "./pages/Role";
import { RulesPageView } from "./pages/Rules";
import { SensitivePageView } from "./pages/Sensitive";
import { WhatIfPageView } from "./pages/Whatif";
import { UserPage } from "./pages/User";

const PAGES: Page[] = ["home", "access", "user", "role", "object", "check", "sensitive", "rules", "review", "whatif"];
const LABEL: Record<Page, string> = {
  home: "Home", access: "Access", user: "User paths", role: "Role paths", object: "Object", check: "Can they?",
  sensitive: "Sensitive data", rules: "Risks & fixes", review: "Review & sign-off", whatif: "What if",
};
const GROUPS: [string, string][] = [["answers", "Answers"], ["admin", "Admin"], ["detail", "Detail"]];

/** Old links to the new screens (docs/redesign-notes.md). No page: Home; an unknown page: Home. */
export function redirect(page: string | null, params: Params): { page: Page; params: Params } {
  if (page === "admins" || (page === "rules" && params.tab === "admins")) {
    const { tab: _t, ...rest } = params;
    return { page: "object", params: { ...rest, preset: "admin" } };
  }
  if (page === "who") return { page: "object", params };
  if (!page || !PAGES.includes(page as Page)) return { page: "home", params };
  if (page === "access" && params.name) {
    const { name, ...rest } = params;
    return { page, params: { ...rest, user: name } };
  }
  return { page: page as Page, params };
}

interface Loc { page: Page; params: Params; mine: boolean }

function read(): Loc {
  const u = new URLSearchParams(location.search);
  const params: Params = {};
  u.forEach((v, k) => { if (k !== "page" && k !== "data") params[k] = v; });
  return { ...redirect(u.get("page"), params), mine: u.get("data") === "mine" };
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
    return typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  useEffect(() => { document.body.style.background = t === "dark" ? "#0F1216" : "#F6F7F9"; }, [t]);
  return [t, () => setT((x) => { const n = x === "dark" ? "light" : "dark"; try { localStorage.setItem("ae-theme", n); } catch { /* no storage */ } return n; })];
}

function Find({ view, onOpen }: { view: string; onOpen: (i: FindItem) => void }) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<FindItem[]>([]);
  useEffect(() => {
    if (q.trim().length < 2) { setItems([]); return; }
    const t = setTimeout(() => { get<{ items: FindItem[] }>("find", { q, view, limit: "20" }).then((r) => setItems(r.items), () => setItems([])); }, 180);
    return () => clearTimeout(t);
  }, [q, view]);
  return (
    <div className="find">
      <input className="ae-input" type="search" aria-label="Find" placeholder="Find a person, role or object" value={q} onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Escape") setQ(""); if (e.key === "Enter" && items[0]) { onOpen(items[0]); setQ(""); } }} />
      {items.length > 0 && (
        <div className="find-list">
          {items.map((i) => (
            <button key={i.id} onClick={() => { onOpen(i); setQ(""); }}>
              <span className="ae-mono">{i.name}{i.sensitive && <span className="ae-sens-word"> · sensitive</span>}</span><span className="ae-muted">{i.kind_label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Side({ meta, page, nav }: { meta: Meta; page: Page; nav: (p: Page, params?: Params) => void }) {
  const wide = typeof matchMedia !== "function" || !matchMedia("(max-width: 1000px)").matches;
  return (
    <aside className="side">
      <details className="side-menu" open={wide}>
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
    </aside>
  );
}

function DataTime({ meta, reload }: { meta: Meta; reload: () => void }) {
  if (!meta.run) return null;
  const what = meta.mode === "fake" ? "Data" : meta.source === "direct" ? "Read" : "Snapshot";
  return (
    <span className={`top-time${meta.mode !== "fake" && meta.run.old ? " old" : ""}`} title={meta.fetched_at ? `Read ${meta.fetched_at}` : undefined}>
      <span className="top-time-dot" aria-hidden />{what} {meta.run.when}
      <button type="button" className="side-reload" onClick={reload} title={meta.mode === "fake" ? "Reload" : "Read Snowflake again"} aria-label="Read again">↻</button>
    </span>
  );
}

const VIEWS: Record<Page, () => JSX.Element> = {
  home: HomePageView, access: AccessPageView, user: UserPage, role: RolePageView, object: ObjectPageView, check: CheckPageView,
  sensitive: SensitivePageView, rules: RulesPageView, review: ReviewPageView, whatif: WhatIfPageView,
};

/** onUrl: the Streamlit wrapper mirrors the page's URL params into the browser address bar. */
export function App({ onUrl }: { onUrl?: (query: string) => void } = {}) {
  const [loc, go] = useLoc();
  useEffect(() => { onUrl?.(url(loc)); }, [loc]);
  const [theme, flip] = useTheme();
  const [busy, setBusy] = useState("");
  const view = loc.mine ? "mine" : "shared";
  const m = useApi<Meta>("meta", { view });
  const meta = m.data;

  const nav = useCallback((page: Page, params: Params = {}) => go({ page, params, mine: loc.mine }), [go, loc.mine]);
  const set = useCallback((patch: Record<string, string | null | undefined>) => {
    const params = { ...loc.params };
    for (const [k, v] of Object.entries(patch)) { if (v) params[k] = v; else delete params[k]; }
    go({ ...loc, params }, true);
  }, [go, loc]);
  const setView = (mine: boolean) => go({ page: mine && (loc.page === "review" || loc.page === "home") ? "access" : loc.page, params: {}, mine });

  const run = async (label: string, f: () => Promise<unknown>) => {
    setBusy(label);
    try { await f(); } catch (e) { alert((e as Error).message); } finally { clearCache(); setBusy(""); }
  };
  const loadMine = (fresh = false) => run("Loading your access…", async () => { await post<MineState>(fresh ? "mine/load?fresh=1" : "mine/load"); setView(true); });
  const reload = () => run("Reading Snowflake…", () => post("reload", { what: "page" }));
  const loadShared = () => run("Reading Snowflake… this can take a few minutes", () => post("reload", { what: "load" }));
  const rebuild = () => run("Rebuilding snapshot…", async () => {
    const r = await post<{ ok: boolean; message: string }>("reload", { what: "rebuild" });
    if (r.message) alert(r.message);
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
      <div className="app">
        <header className="top">
          <button type="button" className="top-logo" onClick={() => nav("home")} aria-label="Access explorer: home">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg>
            Access explorer
          </button>
          <Find view={view} onOpen={(i) => {
            remember({ page: i.page, id: i.id, label: i.name });
            go(i.kind === "user" ? { page: "access", params: { user: i.name }, mine: loc.mine }
              : i.kind === "object" ? { page: "object", params: { name: i.id }, mine: loc.mine } : { page: "access", params: { role: i.id }, mine: loc.mine });
          }} />
          <div className="seg" role="group" aria-label="Data">
            <button className={!loc.mine ? "on" : ""} onClick={() => setView(false)}>Shared snapshot</button>
            {meta?.mine_available !== false && <button className={loc.mine ? "on" : ""} onClick={() => (meta?.mine.loaded ? setView(true) : loadMine())}>My access</button>}
          </div>
          {loc.mine && meta?.mine.loaded && <button className="ae-btn" onClick={() => loadMine(true)} title={`Loaded ${meta.mine.loaded_at ?? ""}`}>Reload my access</button>}
          {!loc.mine && meta && meta.mode !== "fake" && <button className="ae-btn" onClick={rebuild} title="Runs the snapshot procedure in Snowflake">Rebuild snapshot</button>}
          <span className="top-right">
            {meta && <DataTime meta={meta} reload={reload} />}
            {meta?.mode === "fake" && <span className="top-demo" title="Fake accounts, roles and tables. Run without --fake (FAKE=1), with the connection in .env, to read Snowflake.">Demo data</span>}
            <button className="ae-btn" onClick={flip}>{theme === "dark" ? "Light" : "Dark"}</button>
          </span>
          {busy && <span className="ae-muted">{busy}</span>}
        </header>
        {meta ? <Side meta={meta} page={loc.page} nav={(p, params) => nav(p, params ?? {})} /> : <aside className="side" />}
        <main className="main">
          {m.error && <ErrorBox e={m.error} />}
          {!meta && !m.error && <p className="ae-muted">Loading…</p>}
          {needMine && (
            <Card title="My access">
              <p>This reads what you can reach, once, and keeps it in server memory for an hour. Nothing is written anywhere.</p>
              <button className="ae-btn" onClick={() => loadMine()}>Load my access</button>
            </Card>
          )}
          {needShared && (
            <Card title="Shared data">
              <p>Reads every role, user and grant of the account with your role, once, and keeps it for 24 hours.
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
    </Root>
  );
}
