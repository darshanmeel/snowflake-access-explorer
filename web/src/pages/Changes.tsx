// Screen 14, What changed: this snapshot against the previous one (gained and lost access, new and fixed findings),
// and watched questions saved in this browser, asked again on each snapshot. ChangeFeed is also the History tab of
// the Access and Object screens (subject=).
import { useEffect, useMemo, useState } from "react";
import { forget, useApi } from "../api/client";
import type { ChangeEvent, ChangesPage, CheckPage, ListItem, WhoPage } from "../api/types";
import { FilterChips, Fold, Card, EmptyState, FindingChip, Pager, Tabs } from "../components";
import { useApp } from "../ctx";
import { useSaved } from "./changeplan";
import { Head, Load, Pick, Sel } from "./common";
import { answerOf, ICON, question, recheck, watches, watchId, type Filter, type Watch, type WatchKind } from "./history";
import { PAGE } from "./paged";

const CTA: Record<string, string> = { object: "See who", access: "Open", rules: "Fix" };

export function ChangesPageView() {
  const c = useApp();
  const n = useSaved(watches).length;
  const show = c.params.show === "watch" || c.params.show === "findings" ? c.params.show : "feed";
  return (
    <>
      <Head title="What changed" quiet sub="This snapshot against the previous one: who gained or lost access, and which findings are new or fixed." />
      <Tabs nav active={show} onChange={(k) => c.set({ show: k === "feed" ? null : k })} tabs={[
        { key: "feed", label: "Changes" }, { key: "findings", label: "Findings" }, { key: "watch", label: "Watched", count: n }]} />
      {show === "watch" ? <Watched /> : <ChangeFeed key={show} only={show === "findings" ? "findings" : "access"} />}
    </>
  );
}

/** The feed, for every subject or only one (History tab of a person, role or object). The server filters (f) and
 * pages it (ev_at, limit): a big change has tens of thousands of events. */
export function ChangeFeed({ subject, only }: { subject?: string; only?: "access" | "findings" }) {
  const c = useApp();
  const s = useApi<ChangesPage>("changes", { view: c.view, subject, f: c.params.f ?? only, offset: c.params.ev_at, limit: c.params.limit });
  useEffect(() => { if (s.data?.available) forget("home"); }, [s.data]);  // a first comparison: Home's What changed card shows it
  return <Load s={s}>{(d) => <Feed d={d} only={only} />}</Load>;
}

function Feed({ d, only }: { d: ChangesPage; only?: "access" | "findings" }) {
  const c = useApp();
  const f = (only && (d.f as string) === only ? "all" : d.f ?? "all") as Filter;
  const top = (["Critical", "High"] as const).reduce((t, v) => t + (d.severity?.new[v] ?? 0), 0);
  const setF = (k: Filter) => c.set({ f: k === "all" ? null : k, ev_at: null });
  if (!d.available) return <Card><EmptyState title="Nothing to compare with yet" art="wait">{d.reason}</EmptyState></Card>;
  const n = d.counts!;
  const said = (d.text ?? "").replace(/^Since [^:]*:\d\d: /, "").replace(/\.$/, "") || `Nothing changed since ${d.before}`;
  const gained = only === "access" ? (d.text?.match(/(\d+ (?:person|people) gained) sensitive access/)?.[1] ?? "").replace(/$/, " access to sensitive data").replace(/^ access.*/, "") : "";
  const shown = d.events, size = Number(c.params.limit) || PAGE;
  return (
    <>
    <p className="ae-answer">{only === "findings" ? `${d.new} ${d.new === 1 ? "finding is" : "findings are"} new${top ? `, ${top} of them critical or high` : ""}; ${d.fixed} fixed` : gained || said[0].toUpperCase() + said.slice(1)}</p>
    {only === "findings" && d.severity && <Card title="New and fixed, by severity"><Strip s={d.severity} /></Card>}
    <Card title={`${d.before} to ${d.now}`} right={only !== "findings" && <FilterChips label="Show" value={f} onPick={(k) => setF(k as Filter)} items={[
        { key: "all", label: "All" }, { key: "gain", label: "Gained" }, { key: "lose", label: "Lost" }, ...(only ? [] : [{ key: "risk", label: "New findings" }]), { key: "sensitive", label: "Sensitive" }]} />}>
      {!shown.length ? <EmptyState title={n.all ? "Nothing under this filter" : "No changes"} art={n.all ? "search" : "clear"}>{n.all ? "Pick another filter." : `Nothing changed since ${d.before}.`}</EmptyState> : (
        <div className="ae-feed">
          {shown.map((e) => <Item key={e.id} e={e} onOpen={() => c.nav(e.link.page, e.link.params)} onRule={(num) => c.nav("rules", { rule: num })} />)}
        </div>
      )}
      {d.events_total > size && <Pager at={Math.floor(d.offset / size)} size={size} total={d.events_total} sizes={[25, 50, 100, 250]}
        onPage={(k) => c.set({ ev_at: k ? String(k * size) : null })} onSize={(k) => c.set({ limit: k === PAGE ? null : String(k), ev_at: null })} />}
      <p className="ae-muted ae-foot">The difference between two snapshots the app read; "by" is GRANTED_BY from the grant data. Nothing is written to Snowflake.</p>
    </Card>
    <p className="ae-muted"><span className="ae-ev-key more">+</span> more access or new risk <span className="ae-ev-key less">−</span> less access</p>
    </>
  );
}

const SEVS = ["Critical", "High", "Medium", "Low"] as const;

/** New findings against fixed ones, per severity: one row of blocks each, the worst first. */
function Strip({ s }: { s: NonNullable<ChangesPage["severity"]> }) {
  const total = (x: Record<string, number>) => SEVS.reduce((n, v) => n + (x[v] ?? 0), 0);
  const max = Math.max(1, total(s.new), total(s.fixed));
  const row = (label: string, x: Record<string, number>, cls: string) => (
    <div className={`ae-strip-row ae-strip-${cls}`}>
      <span className="ae-strip-l">{label}</span>
      <span className="ae-strip-track">
        {SEVS.map((v) => (x[v] ?? 0) > 0 && <span key={v} className={`ae-strip-seg ae-hc-${v}`} style={{ flex: `0 0 ${(100 * x[v]) / max}%` }} title={`${x[v]} ${v.toLowerCase()}`}>{x[v]}</span>)}
        {!total(x) && <span className="ae-muted">none</span>}
      </span>
      <b className="ae-strip-n">{total(x)}</b>
      <span />
    </div>
  );
  return (
    <div className="ae-strip" aria-label="Findings: new and fixed, per severity">
      {row("New findings", s.new, "new")}
      {row("Fixed", s.fixed, "fixed")}
      <div className="ae-bar-legend">{SEVS.filter((v) => s.new[v] || s.fixed[v]).map((v) => <span key={v}><span className={`ae-dot2 ae-hc-${v}`} />{v}</span>)}</div>
    </div>
  );
}

function Item({ e, onOpen, onRule }: { e: ChangeEvent; onOpen: () => void; onRule: (n: string) => void }) {
  return (
    <div className={`ae-ev ae-ev-${e.kind}`}>
      <span className="ae-ev-icon" aria-hidden>{ICON[e.kind]}</span>
      <div className="ae-ev-main">
        <div className="ae-ev-text"><button type="button" className="ae-link" onClick={onOpen} title={e.kind === "fixed" ? "Open the rule" : CTA[e.link.page] ?? "Open"}>{e.text}</button></div>
        <div className="ae-ev-meta">
          {e.impact && <span>{e.impact}</span>}
          {e.sensitive && <span className="ae-sens-word">sensitive</span>}
          {e.kind !== "risk" && e.findings.slice(0, 1).map((x) => <FindingChip key={x.num} num={x.num} severity={x.fixed ? "Fixed" : x.severity}
            label={`${x.fixed ? "" : "New · "}#${x.num} ${x.title}`} onOpen={() => onRule(x.num)} />)}
        </div>
      </div>
      {e.by && <span className="ae-muted ae-ev-go">by {e.by}</span>}
    </div>
  );
}

const KINDS: [WatchKind, string][] = [["can", "Can [person] read [object]?"], ["who", "Who can read [object]?"], ["admins", "Who holds admin roles?"]];

function Watched() {
  const c = useApp();
  const list = useSaved(watches);
  const objs = useApi<{ items: ListItem[] }>("list", { what: "objects", type: "TABLE", view: c.view, limit: "1" }); // the first table: a default
  const oo = useMemo(() => (objs.data?.items ?? []).map((i) => i.id), [objs.data]);
  const [kind, setKind] = useState<WatchKind>("can");
  const [user, setUser] = useState(c.meta.default_user ?? "");
  const [object, setObject] = useState("");
  const [notify, setNotify] = useState("");
  const obj = object || oo.find((o) => o.split(".").length === 3) || "";
  const add = (w: Omit<Watch, "id">) => {
    const id = watchId(w);
    if (!watches.get().some((x) => x.id === id)) watches.set([...watches.get(), { ...w, id }]);
  };
  const draft = { kind, notify, ...(kind === "admins" ? {} : { object: obj }), ...(kind === "can" ? { user } : {}) };
  return (
    <>
      <p className="ae-answer">{list.length ? `${list.length} ${list.length === 1 ? "question is" : "questions are"} asked again on every snapshot` : "Pick a question to ask again on every snapshot"}</p>
      <Card title="Answers today" sub="Saved in this browser. Asked again on each snapshot; the answer shows Changed when it differs from the one on the snapshot before.">
        {!list.length ? (
          <EmptyState title="No watched questions yet" art="plan">
            Add one, or start with{" "}
            <button type="button" className="ae-link" onClick={() => add({ kind: "admins", notify: "" })}>Who holds admin roles?</button>
          </EmptyState>
        ) : (
          <div className="ae-table-scroll"><table className="ae-table"><thead><tr><th>Question</th><th>Answer</th><th>Against the snapshot before</th><th /></tr></thead><tbody>{list.map((w) => <WatchRow key={w.id} w={w} />)}</tbody></table></div>
        )}
      </Card>
      <Fold label="Watch a question" on={!list.length}>
        <div className="ae-watch-form">
          <Sel label="Question" value={kind} options={KINDS} onPick={(v) => setKind(v as WatchKind)} />
          {kind === "can" && <Pick label="Person" value={user} what="users" onPick={setUser} />}
          {kind !== "admins" && <Pick label="Object" value={obj} what="objects" onPick={setObject} width={300} />}
          <label className="ae-field"><span>Notify (text only: nothing is sent)</span>
            <input className="ae-input" value={notify} placeholder="email or #channel" onChange={(e) => setNotify(e.target.value)} /></label>
          <button type="button" className="ae-btn ae-btn-primary" disabled={(kind !== "admins" && !obj) || (kind === "can" && !user)} onClick={() => add(draft)}>Watch: {question({ id: "", ...draft })}</button>
        </div>
      </Fold>
    </>
  );
}

function WatchRow({ w }: { w: Watch }) {
  const c = useApp();
  const can = w.kind === "can";
  const s = useApi<CheckPage | WhoPage>(can ? "check" : "who", can ? { view: c.view, name: w.user, obj: w.object, do: "read" }
    : w.kind === "admins" ? { view: c.view, preset: "admin" } : { view: c.view, name: w.object });
  const run = c.meta.run?.run_id + "|" + c.meta.run?.finished_at;
  const answer = s.data ? answerOf(w, s.data) : null;
  const r = answer != null ? recheck(w, run, answer) : null;
  useEffect(() => { if (r?.next) watches.set(watches.get().map((x) => (x.id === w.id ? r.next! : x))); }, [answer, run]);
  const open = () => (can ? c.nav("check", { name: w.user ?? "", obj: w.object ?? "", do: "read" })
    : c.nav("object", w.kind === "admins" ? { preset: "admin" } : { name: w.object ?? "" }));
  return (
    <tr className={r?.tag === "Changed" ? "ae-tone-warn" : undefined}>
      <td><button type="button" className="ae-link" onClick={open}>{question(w)}</button>{w.notify && <span className="ae-muted"> notify {w.notify}</span>}</td>
      <td>{s.error ? s.error.message : answer ?? "…"}</td>
      <td>{r && <span className="ae-muted">{r.tag}{r.before && r.tag === "Changed" ? `, was ${r.before}` : ""}</span>}</td>
      <td><button type="button" className="ae-link" onClick={() => watches.set(watches.get().filter((x) => x.id !== w.id))}>Stop</button></td>
    </tr>
  );
}
