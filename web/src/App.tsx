// Local SPA frame: top bar (Find, data mode, theme), sidebar (pages, run info, incomplete notes), URL state, page switch.
import { useCallback, useEffect, useMemo, useState } from "react";
import { clearCache, get, post, useApi } from "./api/client";
import type { FindItem, Meta, MineState, Page } from "./api/types";
import { Banner, Card, Root, type ThemeName } from "./components";
import { AppCtx, type Ctx, type Params } from "./ctx";
import { ErrorBox } from "./pages/common";
import { CheckPageView } from "./pages/Check";
import { ObjectPageView } from "./pages/Object";
import { ReviewPageView } from "./pages/Review";
import { RolePageView } from "./pages/Role";
import { RulesPageView } from "./pages/Rules";
import { SensitivePageView } from "./pages/Sensitive";
import { UserPage } from "./pages/User";

const PAGES: Page[] = ["user", "role", "object", "check", "sensitive", "rules", "review"];
const LABEL: Record<Page, string> = {
  user: "User", role: "Role", object: "Object", check: "Can they?", sensitive: "Sensitive data", rules: "Rule checks", review: "Access review",
};

interface Loc { page: Page; params: Params; mine: boolean }

function read(): Loc {
  const u = new URLSearchParams(location.search);
  const p = u.get("page") as Page | null;
  const params: Params = {};
  u.forEach((v, k) => { if (k !== "page" && k !== "data") params[k] = v; });
  return { page: p && PAGES.includes(p) ? p : "user", params, mine: u.get("data") === "mine" };
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
  useEffect(() => { document.body.style.background = t === "dark" ? "#16130f" : "#f6f4f1"; }, [t]);
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
      <input className="ae-input" placeholder="Find a user, role or object" value={q} onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Escape") setQ(""); if (e.key === "Enter" && items[0]) { onOpen(items[0]); setQ(""); } }} />
      {items.length > 0 && (
        <div className="find-list">
          {items.map((i) => (
            <button key={i.id} onClick={() => { onOpen(i); setQ(""); }}>
              <span>{i.sensitive && <span className="ae-sens">●</span>}{i.name}</span><span className="ae-muted">{i.kind_label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Side({ meta, page, nav }: { meta: Meta; page: Page; nav: (p: Page) => void }) {
  return (
    <aside className="side">
      <nav>
        {meta.pages.map((p) => (
          <button key={p.key} className={p.key === page ? "on" : ""} onClick={() => nav(p.key)}>
            <span>{p.label}</span>{p.badge != null && <span className="ae-tab-count">{p.badge}</span>}
          </button>
        ))}
      </nav>
      {meta.run && (
        <>
          <h4>Data</h4>
          <p>{meta.mode === "fake" ? "Demo data (FAKE=1)" : meta.source === "direct" ? "Read directly from Snowflake" : "Snapshot tables"}</p>
          {meta.fetched_at && <p className="ae-muted">Data from {meta.fetched_at}</p>}
          <p className={meta.run.old ? "ae-muted" : undefined}>{meta.run.when}</p>
          {meta.run.old && <p>The snapshot is older than a day.</p>}
        </>
      )}
      {meta.notes.length > 0 && (
        <>
          <h4>Incomplete</h4>
          <p className="ae-muted">Some data could not be read, so some answers may be missing things.</p>
          {meta.notes.map((n) => (
            <details key={n.key}>
              <summary>{n.title}</summary>
              <p>{n.meaning}</p>
              {n.raw && <p className="ae-muted">{n.raw}</p>}
            </details>
          ))}
        </>
      )}
      {meta.governance && Object.keys(meta.governance).length > 0 && (
        <>
          <h4>Governance</h4>
          {Object.entries(meta.governance).map(([k, v]) => <p key={k}><strong>{k}:</strong> {v}</p>)}
        </>
      )}
    </aside>
  );
}

const VIEWS: Record<Page, () => JSX.Element> = {
  user: UserPage, role: RolePageView, object: ObjectPageView, check: CheckPageView,
  sensitive: SensitivePageView, rules: RulesPageView, review: ReviewPageView,
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
  const setView = (mine: boolean) => go({ page: mine && loc.page === "review" ? "user" : loc.page, params: {}, mine });

  const run = async (label: string, f: () => Promise<unknown>) => {
    setBusy(label);
    try { await f(); } catch (e) { alert((e as Error).message); } finally { clearCache(); setBusy(""); }
  };
  const loadMine = (fresh = false) => run("Loading your access…", async () => { await post<MineState>(fresh ? "mine/load?fresh=1" : "mine/load"); setView(true); });
  const reload = () => run("Reading Snowflake…", () => post("reload", { what: "page" }));
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
  return (
    <Root theme={theme}>
      <div className="app">
        <header className="top">
          <h1>Access explorer</h1>
          <Find view={view} onOpen={(i) => go({ page: i.page, params: { name: i.id }, mine: loc.mine })} />
          <div className="seg" role="group" aria-label="Data">
            <button className={!loc.mine ? "on" : ""} onClick={() => setView(false)}>Shared snapshot</button>
            <button className={loc.mine ? "on" : ""} onClick={() => (meta?.mine.loaded ? setView(true) : loadMine())}>My access</button>
          </div>
          {loc.mine && meta?.mine.loaded && <button className="ae-btn" onClick={() => loadMine(true)} title={`Loaded ${meta.mine.loaded_at ?? ""}`}>Reload my access</button>}
          {!loc.mine && <button className="ae-btn" onClick={reload} title="Reads Snowflake again; the data is otherwise kept for a day">Read Snowflake again</button>}
          {!loc.mine && meta && meta.mode !== "fake" && <button className="ae-btn" onClick={rebuild} title="Runs the snapshot procedure in Snowflake">Rebuild snapshot</button>}
          <button className="ae-btn" onClick={flip}>{theme === "dark" ? "Light" : "Dark"}</button>
          {busy && <span className="ae-muted">{busy}</span>}
        </header>
        {meta ? <Side meta={meta} page={loc.page} nav={(p) => nav(p, {})} /> : <aside className="side" />}
        <main className="main">
          {m.error && <ErrorBox e={m.error} />}
          {!meta && !m.error && <p className="ae-muted">Loading…</p>}
          {needMine && (
            <Card title="My access">
              <p>This reads what you can reach, once, and keeps it in server memory for an hour. Nothing is written anywhere.</p>
              <button className="ae-btn" onClick={() => loadMine()}>Load my access</button>
            </Card>
          )}
          {ctx && !needMine && (
            <AppCtx.Provider value={ctx}>
              {meta?.mode === "fake" && <Banner tone="info" title="Demo data" lines={["Fake accounts, roles and tables. Run without --fake (FAKE=1), with the connection in .env, to read Snowflake."]} />}
              <Body key={`${view}:${loc.page}`} />
            </AppCtx.Provider>
          )}
        </main>
      </div>
    </Root>
  );
}
