// Screen 14, What changed: this snapshot against the previous one (gained and lost access, new and fixed findings),
// and watched questions saved in this browser, asked again on each snapshot. ChangeFeed is also the History tab of
// the Access and Object screens (subject=).
import { useEffect, useMemo, useState } from "react";
import { useApi } from "../api/client";
import type { ChangeEvent, ChangesPage, CheckPage, ListItem, WhoPage } from "../api/types";
import { Card, EmptyState, FilterChips, FindingChip, Tabs } from "../components";
import { useApp } from "../ctx";
import { useSaved } from "./changeplan";
import { Head, Load, Pick, Sel } from "./common";
import { answerOf, ICON, keep, question, recheck, watches, watchId, type Filter, type Watch, type WatchKind } from "./history";

const CTA: Record<string, string> = { object: "See who", access: "Open", rules: "Fix" };

export function ChangesPageView() {
  const c = useApp();
  const n = useSaved(watches).length;
  const show = c.params.show === "watch" ? "watch" : "feed";
  return (
    <>
      <Head title="What changed" sub="This snapshot against the previous one: who gained or lost access, and which findings are new or fixed." />
      <Tabs active={show} onChange={(k) => c.set({ show: k === "feed" ? null : k })} tabs={[
        { key: "feed", label: "Changes" }, { key: "watch", label: "Watched questions", count: n }]} />
      {show === "feed" ? <ChangeFeed /> : <Watched />}
    </>
  );
}

/** The feed, for every subject or only one (History tab of a person, role or object). */
export function ChangeFeed({ subject }: { subject?: string }) {
  const c = useApp();
  const s = useApi<ChangesPage>("changes", { view: c.view, subject });
  return <Load s={s}>{(d) => <Feed d={d} />}</Load>;
}

function Feed({ d }: { d: ChangesPage }) {
  const c = useApp();
  const [f, setF] = useState<Filter>((c.params.f as Filter) ?? "all");
  if (!d.available) return <Card><EmptyState title="Nothing to compare with yet">{d.reason}</EmptyState></Card>;
  const n = d.counts!;
  const shown = d.events.filter((e) => keep(e, f));
  return (
    <Card>
      <p className="ae-answer">{d.subject ? <>For <span className="ae-mono">{d.subject}</span>: {d.text?.replace(/^Since/, "since")}</> : d.text}</p>
      <FilterChips label="Show" value={f} onPick={(k) => setF(k as Filter)} items={[
        { key: "all", label: "All", count: n.all }, { key: "gain", label: "Gained access", count: n.gain },
        { key: "lose", label: "Lost access", count: n.lose }, { key: "risk", label: "New findings", count: n.risk },
        { key: "sensitive", label: "Sensitive only", count: n.sensitive }]} />
      {!shown.length ? <EmptyState title={d.events.length ? "Nothing under this filter" : "No changes"}>{d.events.length ? "Pick another filter." : `Nothing changed since ${d.before}.`}</EmptyState> : (
        <div className="ae-feed">
          <div className="ae-feed-day">{d.before} → {d.now}</div>
          {shown.map((e) => <Item key={e.id} e={e} onOpen={() => c.nav(e.link.page, e.link.params)} onRule={(num) => c.nav("rules", { rule: num })} />)}
        </div>
      )}
      <p className="ae-muted ae-foot">The difference between two snapshots the app read; "by" is GRANTED_BY from the grant data. Nothing is written to Snowflake.</p>
    </Card>
  );
}

function Item({ e, onOpen, onRule }: { e: ChangeEvent; onOpen: () => void; onRule: (n: string) => void }) {
  return (
    <div className={`ae-ev ae-ev-${e.kind}`}>
      <span className="ae-ev-icon" aria-hidden>{ICON[e.kind]}</span>
      <div className="ae-ev-main">
        <div className="ae-ev-text">{e.text}</div>
        <div className="ae-ev-meta">
          {e.impact && <span>{e.impact}</span>}
          {e.by && <span className="ae-muted">by <span className="ae-mono">{e.by}</span></span>}
          {e.sensitive && <span className="ae-sens-word">sensitive</span>}
          {e.findings.map((x) => <FindingChip key={x.num} num={x.num} severity={x.fixed ? "Fixed" : x.severity}
            label={`${x.fixed ? "" : "New · "}#${x.num} ${x.title}`} onOpen={() => onRule(x.num)} />)}
        </div>
      </div>
      <button type="button" className="ae-btn ae-ev-go" onClick={onOpen}>{e.kind === "fixed" ? "Rule" : CTA[e.link.page] ?? "Open"}</button>
    </div>
  );
}

const KINDS: [WatchKind, string][] = [["can", "Can [person] read [object]?"], ["who", "Who can read [object]?"], ["admins", "Who holds admin roles?"]];

function Watched() {
  const c = useApp();
  const list = useSaved(watches);
  const users = useApi<{ items: ListItem[] }>("list", { what: "users", view: c.view });
  const objs = useApi<{ items: ListItem[] }>("list", { what: "objects", view: c.view });
  const uo = useMemo(() => (users.data?.items ?? []).map((i) => i.id), [users.data]);
  const oo = useMemo(() => (objs.data?.items ?? []).map((i) => i.id), [objs.data]);
  const [kind, setKind] = useState<WatchKind>("can");
  const [user, setUser] = useState(c.meta.default_user);
  const [object, setObject] = useState("");
  const [notify, setNotify] = useState("");
  const obj = object || oo.find((o) => o.split(".").length === 3) || "";
  const add = (w: Omit<Watch, "id">) => {
    const id = watchId(w);
    if (!watches.get().some((x) => x.id === id)) watches.set([...watches.get(), { ...w, id }]);
  };
  const draft = { kind, notify, ...(kind === "admins" ? {} : { object: obj }), ...(kind === "can" ? { user } : {}) };
  return (
    <div className="ae-two">
      <Card title="Watched questions" sub="Saved in this browser. Asked again on each snapshot; the answer shows Changed when it differs from the one on the snapshot before.">
        {!list.length ? (
          <EmptyState title="No watched questions yet">
            Add one, or start with{" "}
            <button type="button" className="ae-link" onClick={() => add({ kind: "admins", notify: "" })}>Who holds admin roles?</button>
          </EmptyState>
        ) : (
          <div className="ae-watch-list">{list.map((w) => <WatchRow key={w.id} w={w} />)}</div>
        )}
      </Card>
      <Card title="Watch a question">
        <div className="ae-watch-form">
          <Sel label="Question" value={kind} options={KINDS} onPick={(v) => setKind(v as WatchKind)} />
          {kind === "can" && <Pick label="Person" value={user} options={uo.length ? uo : [user]} onPick={setUser} />}
          {kind !== "admins" && <Pick label="Object" value={obj} options={oo.length ? oo : [obj]} onPick={setObject} width={300} />}
          <label className="ae-field"><span>Notify (text only: nothing is sent)</span>
            <input className="ae-input" value={notify} placeholder="email or #channel" onChange={(e) => setNotify(e.target.value)} /></label>
          <button type="button" className="ae-btn ae-btn-primary" disabled={kind !== "admins" && !obj} onClick={() => add(draft)}>Watch: {question({ id: "", ...draft })}</button>
        </div>
      </Card>
    </div>
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
    : c.nav("object", w.kind === "admins" ? { preset: "admin" } : { name: w.object ?? "", show: "who" }));
  return (
    <div className={`ae-watch${r?.tag === "Changed" ? " ae-watch-alert" : ""}`}>
      <button type="button" className="ae-link ae-watch-q" onClick={open}>{question(w)}</button>
      <div className="ae-watch-a">
        <span>{s.error ? s.error.message : answer ?? "…"}{r?.before && r.tag === "Changed" ? <span className="ae-muted"> · was {r.before}</span> : null}</span>
        {r && <span className={`ae-watch-tag${r.tag === "Changed" ? " on" : ""}`}>{r.tag}</span>}
      </div>
      <div className="ae-muted ae-watch-n">
        Notify: {w.notify || "—"} <button type="button" className="ae-link" onClick={() => watches.set(watches.get().filter((x) => x.id !== w.id))}>Stop watching</button>
      </div>
    </div>
  );
}
