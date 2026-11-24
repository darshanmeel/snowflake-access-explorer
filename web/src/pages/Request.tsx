// Request access (screen 15): object, read or change, the suggested role (smallest existing one first), how long,
// approver and reason, then SQL / Terraform / ticket text to copy. Read-only: the page only writes text. For a person
// (name=) or a role (for_role=: GRANT ROLE x TO ROLE y; role= is the role picked on Can they?).
import { useMemo, useState } from "react";
import { useApi } from "../api/client";
import type { ListItem, RequestPage } from "../api/types";
import { Card, CodeOutput, EmptyState, expiryOf, FilterChips, Fold, LEVEL_WORD, newRoleOf } from "../components";
import { apiParams, useApp } from "../ctx";
import { Load, Pick, PickFirst } from "./common";
import { pickSubject, subjectIn, subjectLink } from "./verdict";

const DAYS: [number, string][] = [[30, "30 days"], [90, "90 days"], [0, "Until revoked"]];

export function RequestPageView() {
  const c = useApp();
  const mine = c.view === "mine";
  const p = c.params;
  const none = !mine && !subjectIn(p, "request").name;  // shared: nobody picked yet
  const s = useApi<RequestPage>(none ? null : "request", apiParams(c));
  const name = subjectIn(p, "request").name ?? s.data?.user ?? c.meta.default_user ?? "";
  const back = s.data ? subjectLink(s.data.subject) : { name };
  return (
    <>
      <div className="ae-headrow">
        <div>
          {p.role && <button type="button" className="ae-link ae-crumb" onClick={() => c.nav("check", { ...back, obj: p.obj ?? "" })}>← Can they?</button>}
          <h2 className="ae-sr">Request access</h2>
        </div>
      </div>
      <div className="ae-ask"><span className="ae-ask-w">Let</span>
        {!mine && <Pick label="For (person or role)" value={name} user={!subjectIn(p, "request").role} what="users,roles"
          onPick={(v, i) => c.set({ ...pickSubject(v, i.kind === "user" ? [v] : [], i.kind === "user" ? [] : [v], "request"), obj: p.obj ?? s.data?.object ?? null, role: null, to: null })} />}
        <span className="ae-ask-w">reach</span> <Pick label="Object" value={p.obj ?? s.data?.object ?? ""} width={340} what="objects" onPick={(v) => c.set({ obj: v, role: null, to: null })} /><span className="ae-ask-w">: which role?</span>
      </div>
      {none ? <PickFirst /> : <Load s={s}>{(d) => d.object ? <Body key={`${d.user}:${d.object}:${d.need}:${d.asked?.role ?? ""}`} d={{ ...d, object: d.object }} />
        : <EmptyState title="Pick an object" art="search">Search for the table, view or other object above.</EmptyState>}</Load>}
    </>
  );
}

function Body({ d }: { d: RequestPage & { object: string } }) {
  const c = useApp();
  const a = d.asked;
  const viaNew = a && a.kind === "database_role" && !a.to ? a.role : undefined; // a database role can't go to a user
  const asked = viaNew ? undefined : a?.role;
  const extra = a && asked && !d.suggestions.some((x) => x.role === asked) ? [{ role: asked, to: a.to ?? undefined, change: a.change }] : [];
  const forRole = !d.subject.user; // GRANT ROLE x TO ROLE <the role>: everyone holding it gets it too
  const choices = [...extra, ...d.suggestions.map((x) => ({ role: x.role, change: x.change }))];
  const [pick, setPick] = useState(viaNew ? "" : asked ?? choices[0]?.role ?? "");
  const [days, setDays] = useState(30);
  const [approver, setApprover] = useState(d.approver ?? d.owners[0] ?? "");  // no owner tag: the owner role
  const [reason, setReason] = useState("");
  const [more, setMore] = useState(false);
  const shown = more ? d.suggestions : d.suggestions.slice(0, 3); // smallest first, as sent
  const ch = choices.find((x) => x.role === pick);
  const note = { by: forRole ? undefined : d.user, reason, approver, expiry: expiryOf(days) || "until revoked" };
  const changes = ch ? [ch.change] : [];
  const inDb = d.subject.database ? { db: d.subject.database, objDb: d.database } : undefined; // a database role subject
  const text = ch ? undefined : newRoleOf(d.user, d.privileges, d.type, d.object, note, viaNew, forRole, inDb);
  const now = d.level ? (LEVEL_WORD[d.level] ?? d.level).toLowerCase() : null;
  return (
    <>
    <p className="ae-answer">{d.has ? `${d.user} already has it` : choices.length ? <><span className="ae-mono">{d.suggestions[0]?.role ?? choices[0].role}</span> is the smallest existing role that lets {d.user} {d.need === "change" ? "change" : "read"} it{(d.suggestions[0]?.here.length ?? 0) > 0 && <b className="ae-bad">, and it also gives {d.suggestions[0].here.join(", ")}</b>}</> : "No existing role fits"}</p>
    <div className="ae-req ae-req-one">
      <section className="ae-card ae-req-form" aria-label="Request">
        <h3>{d.suggestions[0] ? `${d.suggestions[0].role} brings least extra` : "The request"}</h3>
        <p className="ae-muted">{d.via_admin?.length ? `${d.user} reaches it through admin role ${d.via_admin.join(", ")} today` : now ? `${d.user} can ${now === "can use" ? "use" : now} it today` : `${d.user} has no access today`} · needs {d.privileges.join(", ")}</p>
        <div>
          <FilterChips label="Access needed" value={d.need} onPick={(k) => c.set({ need: k === "read" ? null : k, role: null, to: null })}
            items={[{ key: "read", label: "Read it" }, { key: "change", label: "Change it" }]} />
        </div>
        {d.has ? (
          <EmptyState title={d.via_admin?.length ? `${d.user} already reaches it through admin role ${d.via_admin.join(", ")}` : `${d.user} already has ${d.privileges.join(", ")} on it`}>
            <button type="button" className="ae-link" onClick={() => c.nav("check", { ...subjectLink(d.subject), obj: d.object })}>See how on Can they?</button>
          </EmptyState>
        ) : choices.length ? (
          <div className="ae-req-roles" role="radiogroup" aria-label="Suggested role">
            {extra.map((x) => (
              <label key={x.role} className={`ae-req-role${pick === x.role ? " on" : ""}`}>
                <input type="radio" name="role" checked={pick === x.role} onChange={() => setPick(x.role)} />
                <span><b className="ae-mono">{x.role}</b>{x.to && <> to <span className="ae-mono">{x.to}</span></>}
                  <span className="ae-muted"> · picked on Can they?{x.to ? `: everyone holding ${x.to} gets it too (${a?.people ?? 0} ${a?.people === 1 ? "person" : "people"})` : ""}</span>
                  {a?.broad && <span className="ae-warn-word ae-block">Too broad: it reaches {a.people} people. Not recommended.</span>}
                  {a?.rule1 && <span className="ae-warn-word ae-block">A technical role on a user or group role breaks rule 1.</span>}</span>
              </label>
            ))}
            <table className="ae-table ae-reqtab">
              <thead><tr><th>Role</th><th className="num">People today</th><th className="num">Extra</th><th>What else it opens</th></tr></thead>
              <tbody>{shown.map((x) => (
                <tr key={x.role} className={pick === x.role ? "on" : ""}>
                  <td><label><input type="radio" name="role" checked={pick === x.role} onChange={() => setPick(x.role)} /> <b className="ae-mono">{x.role}</b></label></td>
                  <td className="num">{x.holders.toLocaleString("en-US")}</td>
                  <td className="num">+{(x.extra + x.here.length).toLocaleString("en-US")}</td>
                  <td>{x.here.length > 0 && <b className="ae-bad">{x.here.join(", ")} on it too; </b>}{[...x.also.map((a) => `${(LEVEL_WORD[a.level] ?? a.level).toLowerCase()} ${a.count} in ${a.where}`)].join("; ") || (x.here.length ? "no other object" : "nothing else")}{x.unmasked.length > 0 && <span className="ae-bad">; {x.unmasked.join(", ")} unmasked</span>}
                    {x.broad && <span className="ae-warn-word">; too broad: everyone holding {d.user} ({x.people} people) gets it</span>}{forRole && !x.broad && <span className="ae-muted">; its {x.people} {x.people === 1 ? "holder gets" : "holders get"} it too</span>}</td>
                </tr>))}</tbody>
            </table>
            {d.suggestions.length > 3 && <button type="button" className="ae-link" onClick={() => setMore(!more)}>{more ? "Fewer roles" : `+${d.suggestions.length - 3} more roles`}</button>}
            <label className={`ae-req-role${!ch ? " on" : ""}`}>
              <input type="radio" name="role" checked={!ch} onChange={() => setPick("")} />
              <span><b>None of these</b><span className="ae-muted"> · a skeleton for a new role, for the owner to decide</span></span>
            </label>
          </div>
        ) : (
          <div className="ae-note">
            <b>No existing role fits.</b> {inDb
              ? <>Only a database role of {inDb.db} can be granted to the database role {d.user}{inDb.objDb === inDb.db ? "" : `, and it can't hold privileges on ${d.object} (not in ${inDb.db})`}.</>
              : <>No functional role gives {d.privileges.join(", ")} on {d.object} without an admin or build role{forRole ? ` or a loop through ${d.user}` : ""}.</>}
            {" "}The text below is {inDb && inDb.objDb !== inDb.db ? "why it can't be done this way" : `a commented skeleton for a new ${inDb ? "database " : ""}role`}{d.owners.length ? `; the owner (${d.owners.join(", ")}) decides` : ""}.
          </div>
        )}
        <Fold label="How long, approver, reason" on={!!reason}>
        <div className="ae-req-row">
          <label className="ae-field">For how long
            <select className="ae-input" value={days} onChange={(e) => setDays(Number(e.target.value))}>
              {DAYS.map(([n, l]) => <option key={n} value={n}>{l}</option>)}
            </select>
          </label>
          <label className="ae-field">Approver{d.approver && <span className="ae-muted"> (from the object's owner tag)</span>}
            <input className="ae-input" value={approver} placeholder="owner of the data" onChange={(e) => setApprover(e.target.value)} />
          </label>
        </div>
        <label className="ae-field">Why you need it
          <textarea className="ae-input" rows={3} value={reason} placeholder="What it is for, and until when" onChange={(e) => setReason(e.target.value)} />
        </label>
        </Fold>
      </section>
      <Card title="Text for the ticket">
        {d.has ? <p className="ae-muted">Nothing to request.</p>
          : <CodeOutput changes={changes} note={note} texts={text} name={`access_request_${d.user.toLowerCase()}`} />}
      </Card>
    </div>
    </>
  );
}
