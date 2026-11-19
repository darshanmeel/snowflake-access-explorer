// Screen 0: start with a question. Search (people, roles, objects), "can X read Y" goes to Can they?, my access,
// account risks, data protection, recently viewed.
import { useEffect, useRef, useState } from "react";
import { get, useApi } from "../api/client";
import type { FindItem, HomeCards, HomePage, Page, Severity } from "../api/types";
import { Banner, Card, EmptyState, FilterChips, NameList, SEVERITIES, StackBar, type BarPart } from "../components";
import { useApp } from "../ctx";
import { Load, unread } from "./common";
import { skipNote } from "./Risks";

const RECENT = "ae-recent";
/** Side menu groups (server.GROUP); Home has no heading. */
export const GROUPS: [string, string][] = [["home", ""], ["access", "Access"], ["ask", "Ask"], ["risk", "Risk"], ["govern", "Govern"]];

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
  ["request", "Request access"], ["rules", "Risks & fixes"], ["whatif", "What if a role goes?"], ["sensitive", "Sensitive data"],
  ["flow", "Sensitive data flow"], ["usage", "Granted vs used"], ["changes", "What changed"]];

/** The shortcuts to the pages in the nav (My access has no flow or changes), filled in with who (the first search hit
 * or the default user) where the question is about someone. */
export const shortcuts = (keys: string[], who?: Who | null): Short[] =>
  SHORT.filter(([p]) => keys.includes(p)).map(([page, label, fill]) => (who && fill?.(who)) || { page, label, params: {} });

const GROUP: [string, string][] = [["user", "People"], ["role", "Roles"], ["warehouse", "Warehouses"], ["object", "Objects"]];
export const groupOf = (i: Pick<FindItem, "kind" | "type">) =>
  i.kind === "user" ? "user" : i.kind !== "object" ? "role" : i.type === "WAREHOUSE" ? "warehouse" : "object";

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
  const first = items[0], me = c.meta.default_user;
  const who: Who | null = first ? { kind: first.kind, id: first.id, name: first.name } : me ? { kind: "user", id: me, name: me } : null;
  return (
    <div className="ae-home">
      {s.data?.risks && s.data.cards && s.data.protection && <Verdict d={s.data} />}
      <h2 className="ae-home-h">Who can access what in Snowflake?</h2>
      <div className="ae-bigsearch">
        <label className="ae-sr" htmlFor="ae-home-q">Search</label>
        <input id="ae-home-q" ref={box} type="search" className="ae-input" value={q} autoComplete="off"
          placeholder="Person, role, table, or: can X read Y"
          onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") go(); if (e.key === "Escape") setQ(""); }} />
        {!q && <span className="ae-muted ae-kbd">Press / to search</span>}
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
                <h4>{label}{all > shown.length && <span className="ae-muted"> · {shown.length} of {all.toLocaleString()}</span>}</h4>
                {shown.map((i) => (
                  <button type="button" key={i.id} className="ae-suggest-row" onClick={() => openItem(i)}>
                    <span className="ae-mono">{i.name}{i.admin && <span className="ae-tone-bad"> · admin</span>}{i.status && i.status !== "active" && <span className="ae-warn-word"> · {i.status === "never" ? "never logged in" : i.status}</span>}</span>
                    <span className="ae-muted">{i.kind_label}{i.sensitive ? " · sensitive" : ""}{i.answer ? ` · ${i.answer}` : ""}{i.admin ? " · holds an admin role" : ""}</span>
                  </button>
                ))}
                {all > shown.length && <p className="ae-muted ae-suggest-more">{(all - shown.length).toLocaleString()} more {label.toLowerCase()}: type more of the name to narrow it.
                  {g === "object" && <> <button type="button" className="ae-link" onClick={() => c.nav("object", {})}>Search them on Who has access</button></>}</p>}
              </div>
            ) : null;
          })}
        </div>
      )}
      {!ask && q.trim().length >= 2 && hits.q === q && !items.length && !screens.length && (
        <EmptyState title={`No match for “${q.trim()}”`}>No person, role, object or screen has that in its name.</EmptyState>
      )}
      <div className="ae-shortcuts">
        <span className="ae-muted">Try:</span>
        {shortcuts(c.meta.pages.map((p) => p.key), who).map((x) => <button type="button" key={x.page} className="ae-link" onClick={() => c.nav(x.page, x.params)}>{x.label}</button>)}
        <span className="ae-muted">or type “can NAME read TABLE”</span>
      </div>
      {c.view === "shared" && c.meta.inside && <p className="ae-muted">These are the app owner's rights, not yours: inside Snowflake the app reads with its owner's role.</p>}
      {c.meta.notes.length > 0 && (
        <Banner tone="warn" title={`Incomplete: ${c.meta.notes.length} source${c.meta.notes.length === 1 ? "" : "s"} not fully read`}
          lines={c.meta.notes.map((n) => `${n.title}: ${n.meaning}${n.fix ? ` Fix: ${n.fix}` : ""}`)} />
      )}
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
          {d.risks && d.cards && d.protection && <Cards d={d} risks={d.risks} k={d.cards} prot={d.protection} />}
          {rec.length > 0 && (
            <div className="ae-shortcuts">
              <span className="ae-muted">Recently viewed:</span>
              {rec.map((r) => <button type="button" key={r.id} className="ae-pchip"
                onClick={() => (r.page === "user" ? c.nav("access", { user: r.label }) : r.page === "role" ? c.nav("access", { role: r.id }) : c.nav(r.page, { name: r.id }))}>{r.label}</button>)}
            </div>
          )}
        </>
      )}</Load>
    </div>
  );
}

/** Home's answer first: one line of the account's state, each part a link to where it is acted on. */
export function Verdict({ d }: { d: HomePage }) {
  const c = useApp();
  if (!d.risks || !d.cards || !d.protection || unread(c.meta, "grants")) return null;
  const crit = d.risks.Critical ?? 0, top = crit + (d.risks.High ?? 0);
  const rules = new Set([...Object.keys(d.rule_sev?.Critical ?? {}), ...Object.keys(d.rule_sev?.High ?? {})]).size;
  const parts: { key: string; text: string; bad: boolean; open: () => void }[] = [
    { key: "risk", bad: top > 0, open: () => c.nav("rules", { sev: crit ? "Critical" : "High" }),
      text: top ? `${plural(top, crit ? "critical or high finding" : "high finding")}${rules ? ` in ${plural(rules, "rule")}` : ""}` : "No critical or high findings" },
    { key: "admin", bad: d.cards.admins.total > 0, open: () => c.nav("rules", { part: "admins" }), text: plural(d.cards.admins.total, "admin holder") },
    ...(unread(c.meta, "users") ? [] : [{ key: "stale", bad: d.protection.dormant > 0, open: () => c.nav("rules", { rule: "7" }),
      text: `${d.protection.dormant.toLocaleString()} dormant or disabled ${d.protection.dormant === 1 ? "person reads" : "people read"} sensitive data` }]),
    ...(unread(c.meta, "policies") ? [] : [{ key: "mask", bad: d.protection.unmasked_columns > 0, open: () => c.nav("rules", { rule: "6" }),
      text: `${plural(d.protection.unmasked_columns, "sensitive column")} not masked` }])];
  return (
    <p className="ae-home-verdict" aria-label="At a glance">
      {parts.map((x, i) => <span key={x.key}>{i > 0 && <span className="ae-muted" aria-hidden> · </span>}
        <button type="button" className={`ae-link${x.bad ? " ae-tone-bad" : ""}`} onClick={x.open}>{x.text}</button></span>)}
    </p>
  );
}

const TOP = 3; // names a card lists; the rest open on the full list

/** Home's area cards (shared view): each a number, one chart, its first names as links and a way into the page. */
function Cards({ d, risks, k, prot }: { d: HomePage; risks: Record<string, number>; k: HomeCards; prot: NonNullable<HomePage["protection"]> }) {
  const c = useApp();
  const total = Object.values(risks).reduce((a, b) => a + b, 0);
  const ad = k.admins;
  const open = (u: string) => ({ key: u, label: u, open: () => c.nav("access", { user: u }) });
  const off = (...keys: string[]) => keys.map((x) => unread(c.meta, x)).find(Boolean) ?? null; // its source not read
  const grantsOff = off("grants", "user_roles"), usersOff = off("users"), tagsOff = off("tags"), polOff = off("policies");
  const nr = (n: ReturnType<typeof off>, v: number) => (n ? <span className="ae-muted ae-hc-unit" title={`${n.title}: ${n.meaning}`}>not read</span> : v.toLocaleString());
  const funcTech = (k.roles.functional ?? 0) + (k.roles.technical ?? 0);
  const [big, setBig] = useState<"schemas" | "databases">("schemas");
  const who = (n: { people: number; roles: number }) => [n.people && plural(n.people, "person", "people"), n.roles && plural(n.roles, "role")].filter(Boolean).join(", ");
  return (
    <div className="ae-hcards">
      <Card title="Findings by area" sub="Worst severity first; a bar opens that area on the Rules list.">
        <Areas ruleSev={d.rule_sev ?? {}} />
      </Card>
      <Card title={<>Admin holders <b className={`ae-hc-n${ad.total ? " ae-tone-bad" : ""}`}>{nr(grantsOff, ad.total)}</b></>}
        sub="An admin role, or an account privilege not given to everyone through PUBLIC."
        right={<button type="button" className="ae-btn" onClick={() => c.nav("rules", { part: "admins" })}>Open</button>}>
        <HBars rows={ad.by_role.map((r) => ({ key: r.role, label: r.role, n: r.people, cls: "high" }))
          .concat(ad.account_only ? [{ key: "acct", label: "Account privilege only", n: ad.account_only, cls: "medium" }] : [])} />
        <p className="ae-muted">{ad.service.toLocaleString()} of them service users.</p>
        <NameList items={ad.names.map((x) => ({ ...open(x.user), n: `${x.role} · ${x.login}` }))} total={ad.total} max={TOP} onMore={() => c.nav("rules", { part: "admins" })} />
      </Card>
      <Card title={<>Dormant & disabled <b className={`ae-hc-n${k.stale.total ? " ae-tone-warn" : ""}`}>{nr(usersOff ?? grantsOff, k.stale.total)}</b></>}
        sub="Only people who still hold roles (rules 8 and 16): service users that are dormant or never logged in are left out, so People shows more."
        right={<button type="button" className="ae-btn" onClick={() => c.nav("rules", { part: "stale" })}>Open</button>}>
        {usersOff ? <p className="ae-muted">{usersOff.title}: {usersOff.meaning}</p> : <>
          <StackBar parts={statusParts(k.stale.by_status)} />
          <p className="ae-muted">{statusParts(k.stale.by_status).map((p) => `${p.label} ${p.value.toLocaleString()} of ${(k.stale.of_status[p.key] ?? 0).toLocaleString()}`).join(" · ")}</p>
        </>}
        <NameList items={k.stale.names.map(open)} total={k.stale.total} max={TOP} onMore={() => c.nav("rules", { part: "stale" })} />
      </Card>
      <Card title={<>Sensitive data <b className="ae-hc-n">{nr(tagsOff, d.counts.sensitive)}</b></>} sub={tagsOff ? `${tagsOff.title}: sensitivity unknown` : "objects with a sensitive tag"}
        right={<button type="button" className="ae-btn" onClick={() => c.nav("sensitive", {})}>Open</button>}>
        {polOff ? <p className="ae-muted">{polOff.title}: masked or not is unknown.</p>
          : <StackBar label="Sensitive columns" parts={[{ key: "u", label: "Not masked", value: prot.unmasked_columns, cls: "high" }, { key: "m", label: "Masked", value: prot.masked, cls: "low" }]} />}
        <ul className="ae-hc-facts">
          {!polOff && <li><button type="button" className="ae-link" onClick={() => c.nav("rules", { rule: "6" })}>{prot.unmasked_columns.toLocaleString()} columns not masked</button></li>}
          <li><button type="button" className="ae-link" onClick={() => c.nav("rules", { rule: "7" })}>{prot.dormant.toLocaleString()} dormant or disabled people read it</button></li>
          <li><button type="button" className="ae-link" onClick={() => c.nav("sensitive", { show: "rows" })} disabled={!prot.row_tables}>{prot.row_tables.toLocaleString()} tables with row policies</button></li>
          <li><button type="button" className="ae-link" onClick={() => c.nav("flow", {})}>Where it flows: people → roles → objects</button></li>
        </ul>
      </Card>
      <Card title={<>People <b className="ae-hc-n">{d.counts.users.toLocaleString()}</b></>} sub={`${k.people.service.toLocaleString()} service users`}
        right={<button type="button" className="ae-btn" onClick={() => c.nav("access", {})}>Find one</button>}>
        {usersOff ? <p className="ae-muted">{usersOff.title}: who is active, dormant or disabled is unknown.</p> : <StackBar parts={statusParts(k.people.by_status, true)} />}
      </Card>
      <Card title={<>Roles <b className="ae-hc-n">{d.counts.roles.toLocaleString()}</b></>}
        right={<button type="button" className="ae-btn" onClick={() => c.nav("rules", { rule: "13" })}>Orphan roles</button>}>
        {!funcTech && d.counts.roles > 50
          ? <p className="ae-warn-word">No role starts with {c.meta.prefixes.func} / {c.meta.prefixes.tech}: set ROLE_PREFIXES to this account's naming. Rules 1 and 2 did not run.</p>
          : <HBars rows={Object.entries(k.roles).sort((x, y) => y[1] - x[1]).map(([kind, n]) => ({ key: kind, label: KIND_WORD[kind] ?? kind, n, cls: kind === "admin" ? "high" : "low" }))} />}
      </Card>
      <Card title={<>Objects <b className="ae-hc-n">{d.counts.objects.toLocaleString()}</b></>}
        right={<button type="button" className="ae-btn" onClick={() => c.nav("object", {})}>Find one</button>}>
        <HBars rows={k.objects.by_type.map((t) => ({ key: t.type, label: t.type.toLowerCase().replace(/_/g, " "), n: t.n, cls: "low" }))} />
      </Card>
      <DepthCard k={k} />
      <Card title={`Biggest ${big}`}
        sub={`${plural(k.biggest.n_schemas, "schema")} · ${plural(k.biggest.n_databases, "database")}`}
        right={<button type="button" className="ae-btn" onClick={() => c.nav("object", k.biggest[big][0] ? { name: k.biggest[big][0].name } : {})}>Open</button>}>
        <FilterChips label="Count by" value={big} onPick={(v) => setBig(v as typeof big)} items={[{ key: "schemas", label: "Schemas" }, { key: "databases", label: "Databases" }]} />
        <HBars rows={k.biggest[big].map((x) => ({ key: x.name, label: x.name, n: x.n, cls: "low" }))} />
        <p className="ae-muted">Objects in each, schemas and databases themselves not counted.</p>
      </Card>
      <Card title={<>Activity {k.activity.ok && <b className="ae-hc-n">{k.activity.users.toLocaleString()}</b>}</>} sub={k.activity.ok ? "people with queries on objects" : undefined}
        right={<button type="button" className="ae-btn" onClick={() => c.nav("rules", { area: "Activity", show: "list" })}>Rules 24–28</button>}>
        {k.activity.ok ? <DayBars days={k.activity.daily} /> : <p className="ae-muted">Not read: {k.activity.reason}</p>}
        {d.per_rule && k.activity.ok && <p className="ae-muted">{["24", "25", "26", "27", "28"].map((n) => `rule ${n}: ${(d.per_rule![n] ?? 0).toLocaleString()}`).join(" · ")}</p>}
      </Card>
      {k.changes && (k.changes.counts ? (
        <Card title={<>What changed <b className="ae-hc-n">{k.changes.counts.all.toLocaleString()}</b></>} sub={`since ${k.changes.before}`}
          right={<button type="button" className="ae-btn" onClick={() => c.nav("changes", {})}>Open</button>}>
          <StackBar parts={[{ key: "gain", label: "Gained", value: k.changes.counts.gain, cls: "medium" }, { key: "lose", label: "Lost", value: k.changes.counts.lose, cls: "low" }]} />
          <p className="ae-muted">{k.changes.counts.risk.toLocaleString()} with a new finding · {k.changes.counts.sensitive.toLocaleString()} on sensitive data · {k.changes.high.toLocaleString()} new high findings</p>
        </Card>
      ) : (
        <Card title="What changed" sub={k.changes.reason ? "No earlier read kept" : "Not compared yet"}
          right={!k.changes.reason && <button type="button" className="ae-btn" onClick={() => c.nav("changes", {})}>Compare with the read before</button>}>
          <p className="ae-muted">{k.changes.reason ?? "The read before is kept: comparing takes a moment, then What changed opens."}</p>
        </Card>
      ))}
      <Card title={<>Risks <b className="ae-hc-n">{nr(grantsOff, total)}</b> {!grantsOff && <span className="ae-muted ae-hc-unit">findings</span>}</>}
        right={<button type="button" className="ae-btn" onClick={() => c.nav("rules", {})}>Risks & fixes</button>}>
        {d.act_first && d.act_first.length > 0 && (
          <div className="ae-act" aria-label="Act first">
            <div className="ae-muted ae-areas-h">Act first: critical, then high, rarest first</div>
            {d.act_first.map((r) => (
              <div key={`${r.severity}${r.num}`} className="ae-act-row">
                <span className={`ae-sevpill ae-sev-${r.severity}`}>{r.severity}</span>
                <button type="button" className="ae-link ae-act-t" onClick={() => c.nav("rules", { rule: r.num, sev: r.severity })}>#{r.num} {r.title}</button>
                <span className="ae-muted">{plural(r.findings, "finding")}</span>
                <span className="ae-act-names"><NameList items={r.names.map((x) => ({ key: x.id, label: x.id.replace(/ \(user\)$/, ""), open: () => openNode(c.nav, x.id, x.kind) }))}
                  total={r.subjects} max={TOP} onMore={() => c.nav("rules", { rule: r.num, sev: r.severity })} /></span>
              </div>
            ))}
          </div>
        )}
        {d.subjects && (
          <ul className="ae-act-who" aria-label="People and roles per severity">
            {SEVERITIES.filter((s) => risks[s]).map((s) => (
              <li key={s}><button type="button" className="ae-link" onClick={() => c.nav("rules", { sev: s })}>
                <span className={`ae-sevpill ae-sev-${s}`}>{s}</span> {who(d.subjects![s]) || plural(risks[s], "finding")}</button></li>
            ))}
          </ul>
        )}
        <StackBar label="Findings" parts={sevParts(risks)} onPick={(s) => c.nav("rules", { sev: s })} />
        {d.skipped && skipNote(d.skipped) && <p className="ae-muted">{skipNote(d.skipped).trim()} Their findings are not counted here.</p>}
      </Card>
    </div>
  );
}

const KIND_WORD: Record<string, string> = { functional: "Functional", technical: "Technical", group: "Group", database: "Database role", admin: "Admin", object: "Named like an object" };

const statusParts = (n: Record<string, number>, active = false): BarPart[] => [
  ...(active ? [{ key: "active", label: "Active", value: n.active ?? 0, cls: "lvl-read" }] : []),
  { key: "disabled", label: "Disabled", value: n.disabled ?? 0, cls: "high" }, { key: "dormant", label: "Dormant", value: n.dormant ?? 0, cls: "medium" },
  { key: "never", label: "Never logged in", value: n.never ?? 0, cls: "low" }];

/** Ranked bars on a square-root scale, so 4,000 next to 3 still shows both; the real number is printed. */
function HBars({ rows }: { rows: { key: string; label: string; n: number; cls: string }[] }) {
  const max = Math.sqrt(Math.max(1, ...rows.map((r) => r.n)));
  if (!rows.length) return <p className="ae-muted">None.</p>;
  return (
    <div className="ae-hbars">
      {rows.map((r) => (
        <div key={r.key} className="ae-hbar">
          <span className="ae-area-name" title={r.label}>{r.label}</span>
          <span className="ae-area-track" style={{ width: `${(100 * Math.sqrt(r.n)) / max}%` }}><span className={`ae-bar-${r.cls}`} style={{ flex: 1 }} /></span>
          <b className="ae-area-n">{r.n.toLocaleString()}</b>
        </div>
      ))}
    </div>
  );
}

const DEPTH: { key: keyof HomeCards["depth"]; label: string }[] = [
  { key: "users", label: "Users" }, { key: "objects", label: "Objects" }, { key: "schemas", label: "Schemas" }, { key: "databases", label: "Databases" }];

/** How many roles deep access goes (a.depth_counts): each user, object, schema or database at its deepest chain. */
function DepthCard({ k }: { k: HomeCards }) {
  const c = useApp();
  const [on, setOn] = useState<keyof HomeCards["depth"]>("users");
  const got = k.depth[on];
  const ds = Object.keys(got).map(Number);
  const lo = Math.min(...ds), hi = Math.max(...ds);
  // Every depth from shortest to deepest, so a depth with none shows as 0, not as a missing row.
  const rows = ds.length ? Array.from({ length: hi - lo + 1 }, (_, i) => lo + i)
    .map((d) => ({ key: String(d), label: `Depth ${d}`, n: got[d] ?? 0, cls: "low" })) : [];
  return (
    <Card title={<>Chain depth {ds.length > 0 && <span className="ae-muted ae-hc-unit">shortest {lo} · deepest {hi}</span>}</>}
      sub="Roles from the role granted to a user to the grant holder, holder included; each counted at its deepest. Users include service users."
      right={<button type="button" className="ae-btn" onClick={() => c.nav("rules", { rule: "14" })}>Deep chains</button>}>
      <FilterChips label="Count" value={on} onPick={(v) => setOn(v as typeof on)} items={DEPTH} />
      <HBars rows={rows} />
    </Card>
  );
}

/** Queries per day, weekends lighter; the busiest day named. */
function DayBars({ days }: { days: { day: string; queries: number }[] }) {
  if (!days.length) return <p className="ae-muted">No queries in this window.</p>;
  const max = Math.max(1, ...days.map((x) => x.queries));
  const top = days.reduce((a, b) => (b.queries > a.queries ? b : a));
  const wkend = (d: string) => [0, 6].includes(new Date(`${d}T00:00:00Z`).getUTCDay());
  return (
    <>
      <div className="ae-daybars" role="img" aria-label={`Queries per day, ${days[0].day} to ${days[days.length - 1].day}`}>
        {days.map((x) => <span key={x.day} className={wkend(x.day) ? "we" : ""} style={{ height: `${Math.max(2, (100 * x.queries) / max)}%` }} title={`${x.day}: ${x.queries.toLocaleString()} queries`} />)}
      </div>
      <p className="ae-muted">{days[0].day} to {days[days.length - 1].day} · busiest {top.day}, {top.queries.toLocaleString()} queries · weekends lighter</p>
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

const plural = (n: number, w: string, ws = `${w}s`) => `${n.toLocaleString()} ${n === 1 ? w : ws}`;

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

/** One small bar per rule area, worst severity first (a few critical findings above thousands of medium ones); a
 * click opens that area on the Rules list. */
function Areas({ ruleSev }: { ruleSev: Partial<Record<Severity, Record<string, number>>> }) {
  const c = useApp();
  const worst = (n: Record<string, number>) => SEVERITIES.findIndex((s) => n[s]);
  const rows = areaCounts(c.meta.rules, ruleSev).filter((r) => r.total).sort((x, y) => worst(x.n) - worst(y.n) || y.total - x.total);
  const max = Math.max(1, ...rows.map((r) => r.total));
  if (!rows.length) return <p className="ae-muted">None.</p>;
  return (
    <div className="ae-areas" aria-label="Findings by area">
      {rows.map((r) => (
        <button type="button" key={r.area} className="ae-area" onClick={() => c.nav("rules", { show: "list", area: r.area })} title={`Open ${r.area} on the Rules list`}>
          <span className="ae-area-name">{r.area}</span>
          <span className="ae-area-track" style={{ width: `${(100 * r.total) / max}%` }}>
            {sevParts(r.n).map((p) => p.value > 0 && <span key={p.key} className={`ae-bar-${p.cls}`} style={{ flex: p.value }} />)}
          </span>
          <b className="ae-area-n">{r.total}</b>
        </button>
      ))}
    </div>
  );
}
