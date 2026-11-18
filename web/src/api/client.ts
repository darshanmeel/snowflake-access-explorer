// Thin fetch layer: every GET is cached in memory (key = url) until a load/reload clears it, so a page view fetches once.
import { useEffect, useState } from "react";
import type { ApiError } from "./types";

export class ApiFail extends Error {
  constructor(public status: number, public detail: string, message: string) { super(message); }
}

const cache = new Map<string, Promise<unknown>>();
let epoch = 0;
const subs = new Set<() => void>();

/** Drop every cached answer (after loading My access, reload, rebuild) and tell the open pages to refetch. */
export function clearCache() { cache.clear(); epoch++; subs.forEach((f) => f()); }

export const qs = (p: Record<string, string | undefined | null>) => {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) if (v != null && v !== "") u.set(k, v);
  const s = u.toString();
  return s ? `?${s}` : "";
};

/** Streamlit: API calls go to Python through the component instead of HTTP (src/st/main.tsx). */
type Transport = (method: "GET" | "POST", url: string, body?: unknown) => Promise<unknown>;
let transport: Transport | null = null;
export const setTransport = (t: Transport) => { transport = t; };

async function check(r: Response) {
  if (r.ok) return r;
  let b: Partial<ApiError> = {};
  try { b = await r.json(); } catch { /* not JSON */ }
  throw new ApiFail(r.status, String(b.detail ?? r.status), b.message ?? `Request failed (${r.status})`);
}

export function get<T>(path: string, p: Record<string, string | undefined | null> = {}): Promise<T> {
  const url = `/api/${path}${qs(p)}`;
  let hit = cache.get(url);
  if (!hit) {
    hit = transport ? transport("GET", url) : fetch(url, { credentials: "same-origin" }).then(check).then((r) => r.json());
    cache.set(url, hit);
    hit.catch(() => cache.delete(url));
  }
  return hit as Promise<T>;
}

/** GET without the cache, for polling; null inside Streamlit, where Python answers only once it is done. */
export async function peek<T>(path: string, p: Record<string, string | undefined | null> = {}): Promise<T | null> {
  if (transport) return null;
  return (await check(await fetch(`/api/${path}${qs(p)}`, { credentials: "same-origin" }))).json();
}

export async function post<T>(path: string, body?: unknown): Promise<T> {
  if (transport) return transport("POST", `/api/${path}`, body ?? {}) as Promise<T>;
  const r = await check(await fetch(`/api/${path}`, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}),
  }));
  return r.json();
}

/** Save a server CSV (`path` like "review.csv") as a file. */
export async function download(path: string, p: Record<string, string | undefined | null>, name: string) {
  const url = `/api/${path}${qs(p)}`;
  const text = transport ? String(await transport("GET", url)) : await (await check(await fetch(url, { credentials: "same-origin" }))).text();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

export interface State<T> { data: T | null; error: ApiFail | null; loading: boolean }

/** Fetch `path` with `p`; refetches when they change or the cache is cleared. Keeps the old data while loading. */
export function useApi<T>(path: string | null, p: Record<string, string | undefined | null> = {}): State<T> {
  const [s, setS] = useState<State<T>>({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(epoch);
  useEffect(() => { const f = () => setTick(epoch); subs.add(f); return () => { subs.delete(f); }; }, []);
  const [again, setAgain] = useState(0);
  const key = path ? `${path}${qs(p)}#${tick}` : "";
  useEffect(() => setAgain(0), [key]);
  useEffect(() => {
    if (!path) return;
    let live = true, timer = 0;
    setS((x) => ({ ...x, loading: true, error: null }));
    get<T>(path, p).then(
      (data) => live && setS({ data, error: null, loading: false }),
      (error) => {
        if (!live) return;
        if (passing(error) && again < RETRIES) timer = window.setTimeout(() => setAgain((n) => n + 1), RETRY_MS);  // still "Loading…"
        else setS({ data: null, error: error as ApiFail, loading: false });
      },
    );
    return () => { live = false; clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, again]);
  return s;
}

export const RETRY_MS = 2000, RETRIES = 150;  // about 5 minutes

/** A failure that passes by itself: the shared data still being read, a proxy timeout, the server restarting or the
 * connection dropped (a fetch that got no answer is no ApiFail). The page asks again instead of showing an error. */
export const passing = (e: unknown) =>
  !(e instanceof ApiFail) ? !transport : e.detail === "shared_loading" || e.status === 502 || e.status === 504;
