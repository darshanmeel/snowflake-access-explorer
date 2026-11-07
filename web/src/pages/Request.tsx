// Request access (screen 15): object, read or change, the suggested role (smallest existing one first), how long,
// approver and reason, then SQL / Terraform / ticket text to copy. Read-only: the page only writes text.
import { useState } from "react";
import { useApi } from "../api/client";
import type { ListItem, RequestPage } from "../api/types";
import { Card, CodeOutput, EmptyState, expiryOf, FilterChips, LEVEL_WORD, newRoleOf, type Change } from "../components";
import { apiParams, useApp, useOpen } from "../ctx";
import { Load, Pick } from "./common";

const DAYS: [number, string][] = [[30, "30 days"], [90, "90 days"], [0, "Until revoked"]];

export function RequestPageView() {
  const c = useApp();
  const mine = c.view === "mine";
  const users = useApi<{ items: ListItem[] }>(mine ? null : "list", { what: "users", view: c.view });
  const objs = useApi<{ items: ListItem[] }>("list", { what: "objects", view: c.view });
  const p = c.params;
  const s = useApi<RequestPage>("request", apiParams(c));
  const name = p.name ?? s.data?.user ?? c.meta.default_user;
  return (
    <>
      <div className="ae-headrow">
        <div>
          {p.role && <button type="button" className="ae-link ae-crumb" onClick={() => c.nav("check", { name, obj: p.obj ?? "" })}>← Can they?</button>}
          <h2 className="ae-h1">Request access</h2>
          <p className="ae-muted ae-lead">This app never changes Snowflake. It writes the SQL or Terraform for the right role, with the reason and approver as comments, ready for a pull request.</p>
        </div>
      </div>
      <div className="ae-forstrip">
        {!mine && <Pick label="For" value={name} options={users.data?.items.map((i) => i.id) ?? [name]} onPick={(v) => c.set({ name: v, role: null, to: null })} />}
        <Pick label="Object" value={p.obj ?? s.data?.object ?? ""} width={340} options={objs.data?.items.map((i) => i.id) ?? []} onPick={(v) => c.set({ obj: v, role: null, to: null })} />
      </div>
      <Load s={s}>{(d) => <Body key={`${d.user}:${d.object}:${d.need}:${d.asked?.role ?? ""}`} d={d} />}</Load>
    </>
  );
}

function Body({ d }: { d: RequestPage }) {
  const c = useApp();
  const o = useOpen(d.refs);
  const a = d.asked;
  const viaNew = a && a.kind === "database_role" && !a.to ? a.role : undefined; // a database role can't go to a user
  const asked = viaNew ? undefined : a?.role;
  const extra = a && asked && !d.suggestions.some((x) => x.role === asked) ? [{ role: asked, to: a.to ?? undefined }] : [];
  const choices = [...extra, ...d.suggestions.map((x) => ({ role: x.role, to: undefined as string | undefined }))];
  const [pick, setPick] = useState(viaNew ? "" : asked ?? choices[0]?.role ?? "");
  const [days, setDays] = useState(30);
  const [approver, setApprover] = useState(d.approver ?? "");
  const [reason, setReason] = useState("");
  const ch = choices.find((x) => x.role === pick);
  const note = { by: d.user, reason, approver, expiry: expiryOf(days) || "until revoked" };
  const changes: Change[] = ch ? [{ op: "grant", role: ch.role, to: ch.to ?? d.user, toUser: !ch.to }] : [];
  const text = ch ? undefined : newRoleOf(d.user, d.privileges, d.type, d.object, note, viaNew);
  const now = d.level ? (LEVEL_WORD[d.level] ?? d.level).toLowerCase() : null;
  return (
    <div className="ae-req">
      <section className="ae-card ae-req-form" aria-label="Request">
        <div>
          <div className="ae-muted">Object</div>
          <div className="ae-req-obj">
            <button type="button" className="ae-link ae-mono" onClick={() => o.open(d.object)}>{d.object}</button>
            <span className="ae-muted">{d.type.toLowerCase()} · {now ? `${d.user} can ${now === "can use" ? "use" : now} it today` : `${d.user} has no access today`}</span>
          </div>
        </div>
        <div>
          <div className="ae-muted">I need to</div>
          <FilterChips label="Access needed" value={d.need} onPick={(k) => c.set({ need: k === "read" ? null : k, role: null, to: null })}
            items={[{ key: "read", label: "Read it" }, { key: "change", label: "Change it" }]} />
          <div className="ae-muted ae-mt">{d.privileges.join(", ")}</div>
        </div>
        {d.has ? (
          <EmptyState title={`${d.user} already has ${d.privileges.join(", ")} on it`}>
            <button type="button" className="ae-link" onClick={() => c.nav("check", { name: d.user, obj: d.object })}>See how on Can they?</button>
          </EmptyState>
        ) : choices.length ? (
          <div className="ae-req-roles" role="radiogroup" aria-label="Suggested role">
            <div className="ae-muted">Suggested role</div>
            {extra.map((x) => (
              <label key={x.role} className={`ae-req-role${pick === x.role ? " on" : ""}`}>
                <input type="radio" name="role" checked={pick === x.role} onChange={() => setPick(x.role)} />
                <span><b className="ae-mono">{x.role}</b>{x.to && <> to <span className="ae-mono">{x.to}</span></>}
                  <span className="ae-muted"> · picked on Can they?{x.to ? `: everyone holding ${x.to} gets it too` : ""}</span></span>
              </label>
            ))}
            {d.suggestions.map((x, i) => (
              <label key={x.role} className={`ae-req-role${pick === x.role ? " on" : ""}`}>
                <input type="radio" name="role" checked={pick === x.role} onChange={() => setPick(x.role)} />
                <span>
                  <b className="ae-mono">{x.role}</b>{i === 0 && <span className="ae-otag ae-ml">smallest</span>}
                  <span className="ae-muted"> · gives {d.privileges.join(", ")} on this {d.type.toLowerCase()} · held by {x.holders} {x.holders === 1 ? "person" : "people"} · {x.extra} other privilege{x.extra === 1 ? "" : "s"}</span>
                  {(x.also.length > 0 || x.unmasked.length > 0) && (
                    <span className="ae-req-also">
                      <span className="ae-muted">It also gives you</span>
                      {x.also.map((a) => <span key={a.level + a.where} className={`ae-lvl ae-lvl-${a.level}`}>{(LEVEL_WORD[a.level] ?? a.level).toLowerCase()} · {a.count} in {a.where}</span>)}
                      {x.unmasked.map((col) => <span key={col} className="ae-otag ae-sens-tag">{col} unmasked</span>)}
                    </span>
                  )}
                </span>
              </label>
            ))}
            <label className={`ae-req-role${!ch ? " on" : ""}`}>
              <input type="radio" name="role" checked={!ch} onChange={() => setPick("")} />
              <span><b>None of these</b><span className="ae-muted"> · a skeleton for a new role, for the owner to decide</span></span>
            </label>
          </div>
        ) : (
          <div className="ae-note">
            <b>No existing role fits.</b> No functional role gives {d.privileges.join(", ")} on {d.object} without an admin or build role.
            The text on the right is a commented skeleton for a new role{d.owners.length ? `; the owner (${d.owners.join(", ")}) decides` : ""}.
          </div>
        )}
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
      </section>
      <Card title="Ready to copy" sub="Paste into your RBAC repo or a pull request; ticket text for teams without infrastructure as code.">
        {d.has ? <p className="ae-muted">Nothing to request.</p>
          : <CodeOutput changes={changes} note={note} texts={text} name={`access_request_${d.user.toLowerCase()}`} />}
      </Card>
    </div>
  );
}
