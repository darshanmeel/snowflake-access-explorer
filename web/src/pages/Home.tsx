// Screen 0: start with a question. Hero (search: people, roles, objects, "can X read Y" goes to Can they?; quick
// links; recently viewed), then what needs attention, act first, findings, the admin / dormant / sensitive cards, the
// account at a glance and What changed. Every number comes from the server (home_page); takeaways from homedata.
import { useEffect, useRef, useState } from "react";
import { get, useApi } from "../api/client";
import type { FindItem, HomeCards, HomePage, Page, Severity } from "../api/types";
import { AgeBars, Card, EmptyState, FilterChips, NameList, SEVERITIES, StackBar, Tabs, type BarPart } from "../components";
import { action, areaTakeaway, attention, busiest, depthRows, depthTakeaway, headline, peopleTakeaway, readers, severityTakeaway, weekend } from "./homedata";
import { useApp } from "../ctx";
import { Load, unread } from "./common";
import { skipNote } from "./Risks";

const RECENT = "ae-recent";
/** Side menu groups (server.GROUP); Home has no heading. */
export const GROUPS: [string, string][] = [["home", ""], ["access", "Ask"], ["ask", "Ask"], ["risk", "Act"], ["govern", "Govern"]];

/** A search hit (top bar or Home): a person or role opens on Access, an object on Who has access. */
export function openFound(i: FindItem, nav: (p: Page, params: Record<string, string>) => void) {
  remember({ page: i.page, id: i.id, label: i.name });
  if (i.kind === "user") nav("access", { user: i.name });
  else if (i.kind === "object") nav("object", { name: i.id });
  else nav("access", { role: i.id });
}
type Recent = { page: Page; id: string; label: string };

export function recent(): Recent[] {
  try { return JSON.parse(localStorage.getItem(RECENT) ?? "[]"); } catch { return []; }
}

export function remember(r: Recent) {
  try { localStorage.setItem(RECENT, JSON.stringify([r, ...recent().filter((x) => x.id !== r.id)].slice(0, 8))); } catch { /* no storage */ }
}

/** "can ENGINEER_01 read SALES.CORE.TBL_CUSTOMER" -> who (a user, or a role such as F_MARKETING: Can they? takes a
 * name that is no user as the role), what, verb. */
export function parseQuestion(q: string): { who: string; what: string; priv: string } | null {
  const m = q.trim().match(/^can\s+(\S+)\s+(read|select|change|write|insert|update|delete|own|use|usage|operate|monitor)\s+(\S+?)\??$/i);
  if (!m) return null;
  const v = m[2].toLowerCase();
  const priv = v === "own" ? "OWNERSHIP" : v === "read" || v === "select" ? "SELECT" : v === "change" || v === "write" ? "INSERT"
    : v === "use" ? "USAGE" : v.toUpperCase();
  return { who: m[1], what: m[3], priv }; // as typed: the server matches names ignoring case
}

/** Screens whose name matches the search (2+ letters), so "graph" or "used" open them from Home. */
export function screensFor<T extends { key: string; label: string }>(q: string, pages: T[]): T[] {
  const t = q.trim().toLowerCase();
  return t.length < 2 ? [] : pages.filter((p) => p.key !== "home" && p.label.toLowerCase().includes(t));
}

type Who = { kind: string; id: string; name: string };
type Short = { page: Page; label: string; params: Record<string, string> };

const SHORT: [Page, string, ((w: Who) => Short | null)?][] = [
  ["check", "Can they read …?", (w) => (w.kind === "object" ? null : { page: "check", label: `Can ${w.name} read …?`, params: { [w.kind === "user" ? "name" : "role"]: w.kind === "user" ? w.name : w.id } })],
  ["graph", "Access graph", (w) => ({ page: "graph", label: `Graph of ${w.name}`, params: { [w.kind === "user" ? "user" : w.kind === "object" ? "table" : "role"]: w.kind === "user" ? w.name : w.id } })],
  ["compare", "Compare two people", (w) => (w.kind === "object" ? null : { page: "compare", label: `Compare ${w.name} with …`, params: { a: w.id } })],
  ["request", "Request access"], ["rules", "Risks"], ["whatif", "What if a role goes?"], ["sensitive", "Sensitive data"],
  ["flow", "Sensitive data flow"], ["usage", "Grants to trim"], ["objuse", "Used or not"], ["changes", "What changed"]];

/** The shortcuts to the pages in the nav (My access has no flow or changes), filled in with who (the first search hit
 * or the default user) where the question is about someone. */
export const shortcuts = (keys: string[], who?: Who | null): Short[] =>
  SHORT.filter(([p]) => keys.includes(p)).map(([page, label, fill]) => (who && fill?.(who)) || { page, label, params: {} });

const GROUP: [string, string][] = [["user", "People"], ["role", "Roles"], ["warehouse", "Warehouses"], ["object", "Objects"]];
export const groupOf = (i: Pick<FindItem, "kind" | "type">) =>
  i.kind === "user" ? "user" : i.kind !== "object" ? "role" : i.type === "WAREHOUSE" ? "warehouse" : "object";

/** Hero quick links: the questions (only those in the nav; the nav has the pages to explore). */
const QUICK: [string, Page[]][] = [["Ask a question", ["check", "compare", "whatif", "request"]]];

export function HomePageView() {
  const c = useApp();
  const s = useApi<HomePage>("home", { view: c.view });
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<{ q: string; items: FindItem[]; totals?: Record<string, number> }>({ q: "", items: [] });
  const items = hits.items;
  const box = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const f = (e: KeyboardEvent) => { if (e.key === "/" && document.activeElement?.tagName !== "INPUT") { e.preventDefault(); box.current?.focus(); } };
    addEventListener("keydown", f);
    return () => removeEventListener("keydown", f);
  }, []);
  useEffect(() => {
    if (q.trim().length < 2 || parseQuestion(q)) { setHits({ q, items: [] }); return; }
    let live = true; // a slow answer for older text must not replace the newer one
    let t = 0;
    const load = (tries: number) => get<{ items: FindItem[]; totals: Record<string, number>; partial?: boolean }>("find", { q, view: c.view, limit: "24" }).then((r) => {
      if (!live) return;
      setHits({ q, items: r.items, totals: r.totals });
      if (r.partial && tries) t = window.setTimeout(() => load(tries - 1), 1500); // the server was busy: answer lines come later
    }, () => live && setHits({ q, items: [] }));
    t = window.setTimeout(() => load(20), 160);
    return () => { live = false; clearTimeout(t); };
  }, [q, c.view]);
  const openItem = (i: FindItem) => openFound(i, c.nav);
  const ask = parseQuestion(q);
  const screens = ask ? [] : screensFor(q, c.meta.pages);
  const go = () => {
    if (ask) c.nav("check", { name: ask.who, obj: ask.what, priv: ask.priv });
    else if (hits.q === q && items[0]) openItem(items[0]); // Enter waits for the hits of the text now in the box
  };
  const rec = recent();
  const [allRec, setAllRec] = useState(false);
  const first = items[0], me = c.meta.default_user;
  const who: Who | null = first ? { kind: first.kind, id: first.id, name: first.name } : me ? { kind: "user", id: me, name: me } : null;
  const links = shortcuts(c.meta.pages.map((p) => p.key), who);
  return (
    <div className="ae-home">
      {c.view === "shared" && c.meta.inside && <p className="ae-muted">These are the app owner's rights, not yours: inside Snowflake the app reads with its owner's role.</p>}
      <Load s={s}>{(d) => (
        <>
          {d.me && (
            <div className="ae-two">
              <Card title={c.view === "mine" ? "My access" : `Access of ${d.me.user}`} right={<button type="button" className="ae-btn" onClick={() => c.nav("access", c.view === "mine" ? {} : { user: d.me!.user })}>Open</button>}>
                <Ladder counts={d.me.counts} />
                <p className="ae-muted">Reads {d.me.counts.read} · changes {d.me.counts.change} · owns {d.me.counts.own} · runs {d.me.counts.runnable} · {d.me.counts.account} account powers</p>
              </Card>
            </div>
          )}
          {d.risks && d.cards && d.protection && <Shared d={d} risks={d.risks} k={d.cards} prot={d.protection} />}
        </>
      )}</Load>
      {(c.view !== "shared" || c.params.show === "glance") && <section className="ae-hero ae-ask-home" aria-labelledby="ae-home-h">
        <h2 id="ae-home-h" className="ae-hero-h">Ask who can access what</h2>
        <div className="ae-bigsearch">
          <label className="ae-sr" htmlFor="ae-home-q">Search</label>
          <svg className="ae-bigsearch-i" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></svg>
          <input id="ae-home-q" ref={box} type="search" className="ae-input" value={q} autoComplete="off"
            placeholder="Person, role or table, or ask: can PERSON read DB.SCHEMA.TABLE"
            onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") go(); if (e.key === "Escape") setQ(""); }} />
          {!q && <kbd className="ae-kbd" title="Press / to search">/</kbd>}
        </div>
        {ask && (
          <button type="button" className="ae-askrow" onClick={go}>
            Can <b className="ae-mono">{ask.who}</b> {ask.priv === "SELECT" ? "read" : ask.priv.toLowerCase()} <b className="ae-mono">{ask.what}</b>? <span className="ae-muted">Enter to check</span>
          </button>
        )}
        {(items.length > 0 || screens.length > 0) && (
          <div className="ae-suggest">
            {screens.length > 0 && (
              <div>
                <h4>Screens</h4>
                {screens.map((p) => (
                  <button type="button" key={p.key} className="ae-suggest-row" onClick={() => c.nav(p.key, {})}>
                    <span>{p.label}</span><span className="ae-muted">{GROUPS.find(([g]) => g === p.group)?.[1]}</span>
                  </button>
                ))}
              </div>
            )}
            {GROUP.map(([g, label]) => {
              const xs = items.filter((i) => groupOf(i) === g), shown = xs.slice(0, 8), all = hits.totals?.[g] ?? xs.length;
              return xs.length ? (
                <div key={g}>
                  <h4>{label}{all > shown.length && <span className="ae-muted"> · {shown.length} of {all.toLocaleString("en-US")}</span>}</h4>
                  {shown.map((i) => (
                    <button type="button" key={i.id} className="ae-suggest-row" onClick={() => openItem(i)}>
                      <span className="ae-mono">{i.name}{i.admin && <span className="ae-tone-bad"> · admin</span>}{i.status && i.status !== "active" && <span className="ae-warn-word"> · {i.status === "never" ? "never logged in" : i.status}</span>}</span>
                      <span className="ae-muted">{i.kind_label}{i.sensitive ? " · sensitive" : ""}{i.answer ? ` · ${i.answer}` : ""}{i.admin ? " · holds an admin role" : ""}</span>
                    </button>
                  ))}
                  {all > shown.length && <p className="ae-muted ae-suggest-more">{(all - shown.length).toLocaleString("en-US")} more {label.toLowerCase()}: type more of the name to narrow it.
                    {g === "object" && <> <button type="button" className="ae-link" onClick={() => c.nav("object", {})}>Search them on Who has access</button></>}</p>}
                </div>
              ) : null;
            })}
          </div>
        )}
        {!ask && q.trim().length >= 2 && hits.q === q && !items.length && !screens.length && (
          <EmptyState title={`No match for “${q.trim()}”`}>No person, role, object or screen has that in its name.</EmptyState>
        )}
        <div className="ae-quick">
          {QUICK.map(([title, keys]) => {
            const xs = keys.map((k) => links.find((x) => x.page === k)).filter((x): x is Short => !!x);
            return xs.length ? (
              <div key={title} className="ae-quick-g" role="group" aria-label={title}>
                <span className="ae-quick-h" aria-hidden>{title}</span>
                <div className="ae-quick-row">{xs.map((x) => <button type="button" key={x.page} className="ae-qa" onClick={() => c.nav(x.page, x.params)}>{x.label}</button>)}</div>
              </div>
            ) : null;
          })}
        </div>
        {rec.length > 0 && (
          <div className="ae-recent" role="group" aria-label="Recently viewed">
            <span className="ae-muted" aria-hidden>Recently viewed</span>
            {(allRec ? rec : rec.slice(0, 3)).map((r) => <button type="button" key={r.id} className="ae-pchip" title={r.label}
              onClick={() => (r.page === "user" ? c.nav("access", { user: r.label }) : r.page === "role" ? c.nav("access", { role: r.id }) : c.nav(r.page, { name: r.id }))}>{r.label}</button>)}
            {rec.length > 3 && <button type="button" className="ae-pchip ae-chip-more" onClick={() => setAllRec(!allRec)}>{allRec ? "show less" : `+${rec.length - 3} more`}</button>}
          </div>
        )}
      </section>}
    </div>
  );
}

const TOP = 3; // names a card lists; the rest open on the full list

/** The headline, three figures, and who can read sensitive data as one picture. */
function Attention({ d }: { d: HomePage }) {
  const c = useApp();
  const off = (k: string) => !!unread(c.meta, k);
  const tiles = attention(d, off), t = (k: string) => tiles.find((x) => x.key === k);
  const risk = t("risk"), mask = t("mask"), rs = readers(d.cards?.readers), all = rs.reduce((n, x) => n + x.n, 0);
  const idle = rs.find((x) => x.id === "risky")?.n ?? 0;
  const bare = d.protection?.unmasked_names ?? [];
  const figs: { key: string; n: number; text: string; note: string; bad: boolean; go: () => void }[] = [];
  if (risk) figs.push({ key: "risk", n: risk.n, text: "critical or high findings", note: `${(d.risks!.Critical ?? 0).toLocaleString("en-US")} critical, ${(d.risks!.High ?? 0).toLocaleString("en-US")} high, ${risk.text.replace(/^findings /, "")}`, bad: risk.n > 0, go: () => c.nav(risk.page, risk.params) });
  if (all && !off("tags")) figs.push({ key: "read", n: all, text: "people and services can read sensitive data", note: idle ? `${idle.toLocaleString("en-US")} of them ${idle === 1 ? "is" : "are"} inactive` : "none of them is inactive", bad: false, go: () => c.nav("sensitive", {}) });
  if (mask) figs.push({ key: "mask", n: mask.n, text: `sensitive ${mask.n === 1 ? "column" : "columns"} nobody masks`, note: [...new Set(bare.map((x) => x.column))].slice(0, 3).join(", ") + (bare.length > 3 ? ", …" : ""), bad: false, go: () => c.nav(mask.page, mask.params) });
  return (
    <section aria-labelledby="ae-attn-h">
      <h2 id="ae-attn-h" className="ae-home-lead">{headline(d, off)}</h2>
      <div className="ae-figs">
        {figs.map((f) => (
          <button type="button" key={f.key} className={`ae-fig${f.bad ? " bad" : ""}`} onClick={f.go}>
            <span className="ae-fig-n">{f.n.toLocaleString("en-US")}</span><span className="ae-fig-t">{f.text}</span><span className="ae-fig-c">{f.note}</span>
          </button>
        ))}
      </div>
      {all > 0 && !off("tags") && (
        <Card title={idle ? `${idle.toLocaleString("en-US")} of the ${all.toLocaleString("en-US")} readers of sensitive data ${idle === 1 ? "is" : "are"} inactive` : `${all.toLocaleString("en-US")} can read sensitive data, all in use`}>
          {all <= 66
            ? <div className="ae-dots" role="img" aria-label={rs.map((x) => `${x.label} ${x.n}`).join(", ")}>{rs.flatMap((x) => Array.from({ length: x.n }, (_, k) => <i key={`${x.id}${k}`} className={`ae-d-${x.id}`} />))}</div>
            : <div className="ae-dotbar" role="img" aria-label={rs.map((x) => `${x.label} ${x.n}`).join(", ")}>{rs.map((x) => <i key={x.id} className={`ae-d-${x.id}`} style={{ flex: x.n }} />)}</div>}
          <div className="ae-dotkey">{rs.map((x) => <span key={x.id}><i className={`ae-d-${x.id}`} />{x.label}: {x.n.toLocaleString("en-US")}</span>)}</div>
        </Card>
      )}
    </section>
  );
}

type Act = NonNullable<HomePage["act_first"]>[number];

/** One thing to do: the rule, who it is about, what fixing it closes; opens to why, the steps and the findings. */
function ActRow({ r }: { r: Act }) {
  const c = useApp();
  const rule = c.meta.rules.find((x) => x.num === r.num);
  const act = action(r.num, r.subjects, rule?.fix, r.title);
  const go = () => c.nav("rules", { rule: r.num, sev: r.severity });
  return (
    <details className="ae-act-row">
      <summary>
        <b className="ae-act-t">{act.text}</b>
        <span className="ae-act-why">{r.title}: {r.names.slice(0, TOP).map((x) => x.id.replace(/ \(user\)$/, "")).join(", ")}{r.subjects > TOP ? ` and ${(r.subjects - TOP).toLocaleString("en-US")} more` : ""}</span>
        <span className={`ae-act-kind ae-tone-${r.severity === "Critical" ? "bad" : "warn"}`}>{act.kind}</span>
        <span className="ae-act-n">closes {r.findings.toLocaleString("en-US")} {r.severity.toLowerCase()} {r.findings === 1 ? "finding" : "findings"}</span>
      </summary>
      <div className="ae-act-more">
        {rule?.why && <p><b>Why.</b> {rule.why}</p>}
        {rule?.fix && <p><b>How.</b> {rule.fix}</p>}
        <p><b>Who.</b> <span className="ae-act-names"><NameList items={r.names.map((x) => ({ key: x.id, label: x.id.replace(/ \(user\)$/, ""), open: () => openNode(c.nav, x.id, x.kind) }))}
          total={r.subjects} max={TOP} onMore={go} /></span></p>
        <button type="button" className="ae-btn" onClick={go}>Open rule {r.num}: findings and fixes</button>
      </div>
    </details>
  );
}

/** Home's shared view below the hero: the headline, three figures, findings by severity and what to do first; At a glance
 * (admins, dormant, sensitive, areas, the account) and Changes are its other tabs. */
function Shared({ d, risks, k, prot }: { d: HomePage; risks: Record<string, number>; k: HomeCards; prot: NonNullable<HomePage["protection"]> }) {
  const c = useApp();
  const total = Object.values(risks).reduce((a, b) => a + b, 0);
  const ad = k.admins;
  const open = (u: string) => ({ key: u, label: u, open: () => c.nav("access", { user: u }) });
  const off = (...keys: string[]) => keys.map((x) => unread(c.meta, x)).find(Boolean) ?? null; // its source not read
  const grantsOff = off("grants", "user_roles"), usersOff = off("users"), tagsOff = off("tags"), polOff = off("policies");
  const nr = (n: ReturnType<typeof off>, v: number) => (n ? <span className="ae-muted ae-hc-unit" title={`${n.title}: ${n.meaning}`}>not read</span> : v.toLocaleString("en-US"));
  const funcTech = (k.roles.functional ?? 0) + (k.roles.technical ?? 0);
  const [big, setBig] = useState<"schemas" | "databases">("schemas");
  const who = (n: { people: number; roles: number }) => [n.people && plural(n.people, "person", "people"), n.roles && plural(n.roles, "role")].filter(Boolean).join(" · ");
  const ruleN = Object.values(d.per_rule ?? {}).filter(Boolean).length;
  const stale = statusParts(k.stale.by_status);
  const people = statusParts(k.people.by_status, true);
  const tab = c.params.show === "glance" || c.params.show === "changes" ? c.params.show : "risks";
  return (
    <>
      {tab !== "risks" && <Tabs nav active={tab} onChange={(t) => c.set({ show: t === "risks" ? null : t })} tabs={[
        { key: "risks", label: "Now" },
        { key: "glance", label: "At a glance" },
        { key: "changes", label: "Changes", count: k.changes?.counts?.all ?? null }]} />}
      {tab === "risks" && <>
      <Attention d={d} />
      <Card title="What to do first" sub="Critical, then high; the shortest list first. Open a line for the steps. Nothing changes in Snowflake.">
        {d.act_first && d.act_first.length > 0 ? <div className="ae-act" aria-label="What to do first">{d.act_first.map((r) => <ActRow key={`${r.severity}${r.num}`} r={r} />)}</div>
          : <p className="ae-muted">No critical or high findings.</p>}
      </Card>
      <p className="ae-home-also">
        <span className="ae-muted">More</span>
        <button type="button" className="ae-link" onClick={() => c.nav("rules", {})}>{grantsOff ? "All findings" : `All ${total.toLocaleString("en-US")} findings`}</button>
        <button type="button" className="ae-link" onClick={() => c.set({ show: "glance" })}>At a glance</button>
        <button type="button" className="ae-link" onClick={() => c.set({ show: "changes" })}>Changes</button>
      </p>
      </>}

      {tab === "glance" && <section className="ae-home-sec" aria-labelledby="ae-glance-h">
        <h2 id="ae-glance-h" className="ae-home-sec-h">Your Snowflake at a glance</h2>
      <Card title={severityTakeaway(risks)} sub={grantsOff ? `${grantsOff.title}: not read` : `${plural(total, "finding")} in ${plural(ruleN, "rule")}`}
        right={<button type="button" className="ae-link" onClick={() => c.nav("rules", {})}>All {grantsOff ? "" : `${total.toLocaleString("en-US")} `}findings</button>}>
        <StackBar label={`Findings: ${sevParts(risks).map((p) => `${p.label} ${p.value}`).join(", ")}`} parts={sevParts(risks)} onPick={(s) => c.nav("rules", { sev: s })} />
        {d.skipped && skipNote(d.skipped) && <p className="ae-muted">{skipNote(d.skipped).trim()} Their findings are not counted here.</p>}
      </Card>
        <div className="ae-home-grid">
          <Card title={<>Admin holders <b className={`ae-hc-n${ad.total ? " ae-tone-bad" : ""}`}>{nr(grantsOff, ad.total)}</b></>} sub="Admin role or account privilege">
            <HBars label="Admin holders per admin role" rows={ad.by_role.map((r) => ({ key: r.role, label: r.role, n: r.people, cls: "high" }))
              .concat(ad.account_only ? [{ key: "acct", label: "Account privilege only", n: ad.account_only, cls: "medium" }] : [])} />
            <div className="ae-home-sub">
              <h4>Riskiest first</h4>
              <NameList items={ad.names.map((x) => ({ ...open(x.user), n: `${x.role} · ${x.login}` }))} total={ad.names.length} max={TOP} />
            </div>
            {(ad.service_names?.length ?? 0) > 0 && (
              <div className="ae-home-sub">
                <h4>Service users with admin</h4>
                <NameList items={ad.service_names!.map((x) => ({ ...open(x.user), n: `${x.role} · ${x.login}` }))} total={ad.service} max={TOP} onMore={() => c.nav("rules", { part: "admins" })} />
              </div>
            )}
            <button type="button" className="ae-link ae-home-more" onClick={() => c.nav("rules", { part: "admins" })}>All {plural(ad.total, "holder")} →</button>
          </Card>
          <Card title={<>Dormant & disabled <b className={`ae-hc-n${k.stale.total ? " ae-tone-warn" : ""}`}>{nr(usersOff ?? grantsOff, k.stale.total)}</b></>}
            sub="Still hold roles; dormant service users left out">
            {usersOff ? <p className="ae-muted">{usersOff.title}: {usersOff.meaning}</p> : <>
              <StackBar parts={stale} legend={false} />
              <ul className="ae-keyrows">
                {stale.map((p) => (
                  <li key={p.key}><span className={`ae-dot2 ae-bar-${p.cls}`} /><span>{p.label} <span className="ae-muted">· {p.value.toLocaleString("en-US")} of {(k.stale.of_status[p.key] ?? 0).toLocaleString("en-US")}</span></span><b>{p.value.toLocaleString("en-US")}</b></li>
                ))}
              </ul>
            </>}
            <div className="ae-home-sub"><NameList items={k.stale.names.map(open)} total={k.stale.total} max={TOP} onMore={() => c.nav("rules", { part: "stale" })} /></div>
          </Card>
          <Card title={<>Sensitive data <b className="ae-hc-n">{nr(tagsOff, d.counts.sensitive)}</b> {!tagsOff && <span className="ae-muted ae-hc-unit">objects</span>}</>}
            sub={tagsOff ? `${tagsOff.title}: sensitivity unknown` : "Objects with a sensitive tag, and how their columns are protected."}>
            {polOff ? <p className="ae-muted">{polOff.title}: masked or not is unknown.</p>
              : <StackBar label={`Sensitive columns: ${prot.unmasked_columns} not masked, ${prot.masked} masked`} parts={[{ key: "u", label: "Not masked", value: prot.unmasked_columns, cls: "high" }, { key: "m", label: "Masked", value: prot.masked, cls: "low" }]} />}
            <div className="ae-linerows">
              {!polOff && <button type="button" className="ae-linerow" onClick={() => c.nav("rules", { rule: "6" })}><span>Columns not masked</span><b className={prot.unmasked_columns ? "ae-tone-bad" : ""}>{prot.unmasked_columns.toLocaleString("en-US")}</b></button>}
              <button type="button" className="ae-linerow" onClick={() => c.nav("rules", { rule: "7" })}><span>Dormant or disabled people read it</span><b className={prot.dormant ? "ae-tone-bad" : ""}>{prot.dormant.toLocaleString("en-US")}</b></button>
              <button type="button" className="ae-linerow" onClick={() => c.nav("sensitive", { show: "rows" })} disabled={!prot.row_tables}><span>Tables with row policies</span><b>{prot.row_tables.toLocaleString("en-US")}</b></button>
            </div>
            <button type="button" className="ae-link ae-home-more" onClick={() => c.nav("flow", {})}>Where it flows: people → roles → objects</button>
            <button type="button" className="ae-link ae-home-more" onClick={() => c.nav("sensitive", {})}>Open Sensitive data →</button>
          </Card>
        </div>
        <Card title="Findings by area">
          {d.subjects && (
            <div className="ae-sevrows" aria-label="People and roles per severity">
              {SEVERITIES.filter((s) => risks[s]).map((s) => (
                <button type="button" key={s} className="ae-sevrow" onClick={() => c.nav("rules", { sev: s })}>
                  <span className={`ae-sevpill ae-sev-${s}`}>{s}</span>
                  <span className="ae-muted">{who(d.subjects![s]) || "objects only"}</span>
                  <b className="ae-area-n">{risks[s].toLocaleString("en-US")}</b>
                </button>
              ))}
            </div>
          )}
          <Areas ruleSev={d.rule_sev ?? {}} />
        </Card>
        <div className="ae-home-grid">
          <Card title={<>People <b className="ae-hc-n">{d.counts.users.toLocaleString("en-US")}</b></>}
            right={<button type="button" className="ae-btn" onClick={() => c.nav("access", {})}>Find one</button>}>
            {usersOff ? <p className="ae-muted">{usersOff.title}: who is active, dormant or disabled is unknown.</p> : <>
              <StackBar parts={people} />
              <p className="ae-muted ae-home-say">{peopleTakeaway(k.people.by_status, k.people.service)}</p>
            </>}
          </Card>
          <Card title={<>Roles <b className="ae-hc-n">{d.counts.roles.toLocaleString("en-US")}</b></>}
            right={<button type="button" className="ae-btn" onClick={() => c.nav("rules", { rule: "13" })}>Orphan roles</button>}>
            {!funcTech && d.counts.roles > 50
              ? <p className="ae-warn-word">No role starts with {c.meta.prefixes.func} / {c.meta.prefixes.tech}: set ROLE_PREFIXES to this account's naming. Rules 1 and 2 did not run.</p>
              : <HBars label="Roles by kind" rows={Object.entries(k.roles).sort((x, y) => y[1] - x[1]).map(([kind, n]) => ({ key: kind, label: KIND_WORD[kind] ?? kind, n, cls: kind === "admin" ? "high" : "low" }))} />}
          </Card>
          <Card title={<>Objects <b className="ae-hc-n">{d.counts.objects.toLocaleString("en-US")}</b></>}
            right={<button type="button" className="ae-btn" onClick={() => c.nav("object", {})}>Find one</button>}>
            <HBars label="Objects by type" rows={k.objects.by_type.map((t) => ({ key: t.type, label: t.type.toLowerCase().replace(/_/g, " "), n: t.n, cls: "low" }))} />
          </Card>
          <DepthCard k={k} />
          <Card title={`Biggest ${big}`}
            sub={`${plural(k.biggest.n_schemas, "schema")} · ${plural(k.biggest.n_databases, "database")}`}
            right={<button type="button" className="ae-btn" onClick={() => c.nav("object", k.biggest[big][0] ? { name: k.biggest[big][0].name } : {})}>Open</button>}>
            <FilterChips label="Count by" value={big} onPick={(v) => setBig(v as typeof big)} items={[{ key: "schemas", label: "Schemas" }, { key: "databases", label: "Databases" }]} />
            <HBars mono label={`Objects per ${big === "schemas" ? "schema" : "database"}`} rows={k.biggest[big].map((x) => ({ key: x.name, label: x.name, n: x.n, cls: "low" }))} />
          </Card>
          <Card title={<>Activity {k.activity.ok && <><b className="ae-hc-n">{k.activity.users.toLocaleString("en-US")}</b> <span className="ae-muted ae-hc-unit">people queried</span></>}</>}
            right={<button type="button" className="ae-btn" onClick={() => c.nav("rules", { area: "Activity", show: "list" })}>Rules 24–28</button>}>
            {k.activity.ok ? <DayBars days={k.activity.daily} /> : <p className="ae-muted">Not read: {k.activity.reason}</p>}
            {d.per_rule && k.activity.ok && (
              <div className="ae-home-sub">
                <div className="ae-ruletiles" role="group" aria-label="Findings from the activity rules, 24 to 28">
                  {["24", "25", "26", "27", "28"].map((n) => (
                    <button type="button" key={n} className="ae-ruletile" onClick={() => c.nav("rules", { rule: n })} title={c.meta.rules.find((r) => r.num === n)?.title}>
                      <span className="ae-muted">Rule {n}</span><b>{(d.per_rule![n] ?? 0).toLocaleString("en-US")}</b></button>
                  ))}
                </div>
              </div>
            )}
          </Card>
          <ObjUseCard u={k.objuse} />
        </div>
      </section>}

      {tab === "changes" && k.changes && (k.changes.counts ? (
        <Card title={<>What changed <b className="ae-hc-n">{k.changes.counts.all.toLocaleString("en-US")}</b></>} sub={`since ${k.changes.before}`}
          right={<button type="button" className="ae-btn" onClick={() => c.nav("changes", {})}>Open</button>}>
          <StackBar parts={[{ key: "gain", label: "Gained", value: k.changes.counts.gain, cls: "medium" }, { key: "lose", label: "Lost", value: k.changes.counts.lose, cls: "low" }]} />
          <p className="ae-muted">{k.changes.counts.risk.toLocaleString("en-US")} with a new finding · {k.changes.counts.sensitive.toLocaleString("en-US")} on sensitive data · {k.changes.high.toLocaleString("en-US")} new high findings</p>
        </Card>
      ) : (
        <div className="ae-home-changes">
          <Card title="What changed" sub={k.changes.reason ? "No earlier read kept" : "Not compared yet"}
            right={!k.changes.reason && <button type="button" className="ae-btn" onClick={() => c.nav("changes", {})}>Compare with the read before</button>}>
            <p className="ae-muted">{k.changes.reason ?? "The read before is kept: comparing takes a moment, then What changed opens."}</p>
          </Card>
        </div>
      ))}
    </>
  );
}

const KIND_WORD: Record<string, string> = { functional: "Functional", technical: "Technical", group: "Group", database: "Database role", admin: "Admin", object: "Named like an object" };

const statusParts = (n: Record<string, number>, active = false): BarPart[] => [
  ...(active ? [{ key: "active", label: "Active", value: n.active ?? 0, cls: "lvl-read" }] : []),
  { key: "disabled", label: "Disabled", value: n.disabled ?? 0, cls: "high" }, { key: "dormant", label: "Dormant", value: n.dormant ?? 0, cls: "medium" },
  { key: "never", label: "Never logged in", value: n.never ?? 0, cls: "low" }];

/** Ranked bars on a square-root scale, so 4,000 next to 3 still shows both; the real number is printed. */
function HBars({ rows, label, mono }: { rows: { key: string; label: string; n: number; cls: string }[]; label: string; mono?: boolean }) {
  const max = Math.sqrt(Math.max(1, ...rows.map((r) => r.n)));
  if (!rows.length) return <p className="ae-muted">None.</p>;
  return (
    <div className="ae-hbars" role="img" aria-label={`${label}: ${rows.map((r) => `${r.label} ${r.n}`).join(", ")}`}>
      {rows.map((r) => (
        <div key={r.key} className="ae-hbar">
          <span className={`ae-area-name${mono ? " ae-mono" : ""}`} title={r.label}>{r.label}</span>
          <span className="ae-area-track" style={{ width: `${(100 * Math.sqrt(r.n)) / max}%` }}><span className={`ae-bar-${r.cls}`} style={{ flex: 1 }} /></span>
          <b className="ae-area-n">{r.n.toLocaleString("en-US")}</b>
        </div>
      ))}
    </div>
  );
}

const DEPTH: { key: keyof HomeCards["depth"]; label: string }[] = [
  { key: "users", label: "Users" }, { key: "objects", label: "Objects" }, { key: "schemas", label: "Schemas" }, { key: "databases", label: "Databases" }];

/** How many roles deep access goes (a.depth_counts): one column per depth, the depth with the most in full ink. */
function DepthCard({ k }: { k: HomeCards }) {
  const c = useApp();
  const [on, setOn] = useState<keyof HomeCards["depth"]>("users");
  const rows = depthRows(k.depth[on]);
  const what = DEPTH.find((x) => x.key === on)!.label.toLowerCase();
  const top = rows.length ? rows.reduce((a, b) => (b.n > a.n ? b : a)) : null;
  const max = Math.sqrt(Math.max(1, ...rows.map((r) => r.n)));
  return (
    <Card title={<>Role chain depth {rows.length > 0 && <span className="ae-muted ae-hc-unit">shortest {rows[0].d} · deepest {rows[rows.length - 1].d}</span>}</>}
      sub="Roles from the role granted to a user to the grant holder, holder included; each counted at its deepest. Users include service users."
      right={<button type="button" className="ae-btn" onClick={() => c.nav("rules", { rule: "14" })}>Deep chains</button>}>
      <FilterChips label="Count" value={on} onPick={(v) => setOn(v as typeof on)} items={DEPTH} />
      {rows.length ? <>
        <div className="ae-cols" role="img" aria-label={`${DEPTH.find((x) => x.key === on)!.label} by chain depth: ${rows.map((r) => `depth ${r.d} ${r.n}`).join(", ")}; most at depth ${top!.d}`}>
          {rows.map((r) => (
            <div key={r.d} className="ae-col">
              <span className="ae-col-n">{r === top ? <b>{r.n.toLocaleString("en-US")}</b> : r.n.toLocaleString("en-US")}</span>
              <span className={`ae-col-bar${r === top ? " top" : ""}`} style={{ height: `${r.n ? Math.max(3, (100 * Math.sqrt(r.n)) / max) : 0}%` }} />
            </div>
          ))}
        </div>
        <div className="ae-col-x" aria-hidden>{rows.map((r) => <span key={r.d}>{r.d}</span>)}</div>
        <p className="ae-muted ae-home-say">{depthTakeaway(rows, what)} Column height on a √ scale.</p>
      </> : <p className="ae-muted">None.</p>}
    </Card>
  );
}

/** Object activity at 90 days: last use per type, tables read but never written and the reverse. */
function ObjUseCard({ u }: { u: HomeCards["objuse"] }) {
  const c = useApp();
  return (
    <Card title="Object activity" sub={u.ok ? `${u.unused.toLocaleString("en-US")} objects not used in ${u.days} days${u.unused_new ? `, ${u.unused_new.toLocaleString("en-US")} of them new or changed` : ""}` : undefined}
      right={<button type="button" className="ae-btn" onClick={() => c.nav("objuse", {})}>Open</button>}>
      {u.notes.map((n) => <p key={n} className="ae-muted">Not read: {n}</p>)}
      <AgeBars types={u.types} onPick={(t) => c.nav("objuse", { type: t })} />
      {u.ok && <div className="ae-linerows">
        <button type="button" className="ae-linerow" onClick={() => c.nav("objuse", { tab: "read_only" })}><span>Tables read, never written</span><b>{u.read_only.toLocaleString("en-US")}</b></button>
        <button type="button" className="ae-linerow" onClick={() => c.nav("objuse", { tab: "write_only" })}><span>Tables written, never read</span><b>{u.write_only.toLocaleString("en-US")}</b></button>
      </div>}
      {u.nodata.length > 0 && <p className="ae-muted">No activity data for {u.nodata.map((t) => t.toLowerCase()).join(", ")}.</p>}
    </Card>
  );
}

/** Queries per day: weekdays in full colour, weekends lighter, the busiest day in ink and named. */
function DayBars({ days }: { days: { day: string; queries: number }[] }) {
  const top = busiest(days);
  if (!top) return <p className="ae-muted">No queries in this window.</p>;
  const max = Math.max(1, top.queries);
  const from = days[0].day, to = days[days.length - 1].day;
  return (
    <>
      <div className="ae-daybars" role="img" aria-label={`Queries per day, ${from} to ${to}, busiest ${top.day} with ${top.queries.toLocaleString("en-US")} queries, weekends lighter`}>
        {days.map((x) => <span key={x.day} className={x === top ? "top" : weekend(x.day) ? "we" : ""} style={{ height: `${Math.max(2, (100 * x.queries) / max)}%` }} title={`${x.day}: ${x.queries.toLocaleString("en-US")} queries`} />)}
      </div>
      <div className="ae-dayx"><span>{from}</span><span>busiest {top.day} · {top.queries.toLocaleString("en-US")} queries</span><span>{to}</span></div>
      <div className="ae-bar-legend" aria-hidden><span><span className="ae-dot2 ae-day-wd" />Weekday</span><span><span className="ae-dot2 ae-day-we" />Weekend</span><span><span className="ae-dot2 ae-day-top" />Busiest</span></div>
    </>
  );
}

/** Read only / read + change / owns: the access ladder as one bar (Home, and the Access screen where it filters). */
export const ladderParts = (counts: { read: number; change: number; own: number }): BarPart[] => [
  { key: "read", label: "Read only", value: counts.read - counts.change, cls: "lvl-read" },
  { key: "change", label: "Read + change", value: counts.change - counts.own, cls: "lvl-change" },
  { key: "own", label: "Owns", value: counts.own, cls: "lvl-own" }];

function Ladder({ counts }: { counts: { read: number; change: number; own: number } }) {
  return <StackBar parts={ladderParts(counts)} />;
}

const plural = (n: number, w: string, ws = `${w}s`) => `${n.toLocaleString("en-US")} ${n === 1 ? w : ws}`;

/** A name from a finding: a person or role opens on Access, an object on Who has access. */
const openNode = (nav: (p: Page, params: Record<string, string>) => void, id: string, kind: string) =>
  kind === "user" ? nav("access", { user: id.replace(/ \(user\)$/, "") }) : kind === "object" ? nav("object", { name: id }) : nav("access", { role: id });

export const sevParts = (n: Record<string, number>): BarPart[] => [
  ...(n.Critical ? [{ key: "Critical", label: "Critical", value: n.Critical, cls: "critical" }] : []),
  { key: "High", label: "High", value: n.High ?? 0, cls: "high" },
  { key: "Medium", label: "Medium", value: n.Medium ?? 0, cls: "medium" }, { key: "Low", label: "Low", value: n.Low ?? 0, cls: "low" }];

/** Findings per rule area and severity, from the findings per severity and rule (rules 5 and 9 can be in two). */
export function areaCounts(rules: { num: string; area: string }[], ruleSev: Partial<Record<Severity, Record<string, number>>>) {
  const area = new Map(rules.map((r) => [r.num, r.area]));
  const out = new Map<string, Record<string, number>>(rules.map((r) => [r.area, { Critical: 0, High: 0, Medium: 0, Low: 0 }]));
  for (const s of SEVERITIES) for (const [num, v] of Object.entries(ruleSev[s] ?? {})) {
    const m = out.get(area.get(num) ?? "Other") ?? { Critical: 0, High: 0, Medium: 0, Low: 0 };
    m[s] += v;
    out.set(area.get(num) ?? "Other", m);
  }
  return [...out].map(([area, n]) => ({ area, n, total: Object.values(n).reduce((a, b) => a + b, 0) }));
}

/** One small bar per rule area (length on a square-root scale), worst severity first (a few critical findings above thousands of medium ones); a
 * click opens that area on the Rules list. */
function Areas({ ruleSev }: { ruleSev: Partial<Record<Severity, Record<string, number>>> }) {
  const c = useApp();
  const worst = (n: Record<string, number>) => SEVERITIES.findIndex((s) => n[s]);
  const rows = areaCounts(c.meta.rules, ruleSev).filter((r) => r.total).sort((x, y) => worst(x.n) - worst(y.n) || y.total - x.total);
  const max = Math.sqrt(Math.max(1, ...rows.map((r) => r.total))); // square-root scale: 9 next to 146,000 still shows
  if (!rows.length) return <p className="ae-muted">None.</p>;
  return (
    <>
    <div className="ae-areas" aria-label="Findings by area">
      {rows.map((r) => (
        <button type="button" key={r.area} className="ae-area" onClick={() => c.nav("rules", { show: "list", area: r.area })} title={`Open ${r.area} on the Rules list`}>
          <span className="ae-area-name">{r.area}</span>
          <span className="ae-area-track" style={{ width: `${(100 * Math.sqrt(r.total)) / max}%` }}>
            {sevParts(r.n).map((p) => p.value > 0 && <span key={p.key} className={`ae-bar-${p.cls}`} style={{ flex: p.value }} />)}
          </span>
          <b className="ae-area-n">{r.total.toLocaleString("en-US")}</b>
        </button>
      ))}
    </div>
    <p className="ae-muted ae-home-say">{areaTakeaway(rows)}</p>
    </>
  );
}
