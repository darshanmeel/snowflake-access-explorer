// Shapes of server.py's JSON answers. Contract: web/API.md (keep both in step).

export type View = "shared" | "mine";
export type Mode = "fake" | "snowflake";
export type Source = "fake" | "objects" | "direct";
export type Severity = "Critical" | "High" | "Medium" | "Low";
export type Tone = "info" | "warn" | "bad";

/** Kinds of users, roles and objects; the last five are combined graph boxes. */
export type NodeKind =
  | "user" | "functional" | "technical" | "group" | "database_role" | "admin" | "object"
  | "schema_group" | "database_group" | "type_group" | "fold" | "lane_group";

/** Privilege class (a.priv_class), used for arrows and badges. */
export type PrivClass = "read" | "write" | "own" | "use" | "manage" | "admin";
export type EdgeCls = "inherit" | "inherit_db" | PrivClass;
export type Mark = "disabled" | "sensitive" | "bad" | "stack"; // stack: people with the same lines in one box

/** Privileges tabs, in this order. */
export type TabKey =
  | "account" | "granted" | "database_roles" | "usage" | "warehouses"
  | "execute" | "read" | "write" | "own" | "manage" | "all";

export type UserStatus = "active" | "dormant" | "never" | "disabled";
export type Page = "home" | "access" | "user" | "role" | "object" | "check" | "graph" | "see" | "compare" | "request" | "sensitive" | "flow" | "rules" | "review" | "whatif" | "usage" | "changes";

/** Node ids from start to end: user/role ... grant holder, then the object when there is one. */
export type Path = string[];

export interface Refs {
  kinds: Record<string, NodeKind>;
  types: Record<string, string>;
  labels: Record<string, string>;
  sensitive: string[];
  disabled: string[];
}

export interface RuleHit {
  num: string;
  severity: Severity;
  title: string;
}

export interface LinkTo {
  label: string;
  page: Page;
  params: Record<string, string>;
}

export interface Banner {
  tone: Tone;
  title: string;
  lines: string[];
  links?: LinkTo[];
}

export interface ApiError {
  detail: "not_found" | "mine_not_loaded" | "shared_unreadable" | "shared_only" | "bad_param" | string;
  message: string;
}

// ---------- graph ----------

export type NodeAction =
  | { kind: "page"; page: Page; params: Record<string, string> }
  | { kind: "expand"; group: string }
  | { kind: "drill"; schema: string }
  | { kind: "otype"; otype: string }
  | { kind: "full" };

export interface Lane {
  index: number;
  label: string;
  depth: number | null;
}

export interface GraphNode {
  id: string;
  name: string;
  label: string;
  sub: string | null;
  kind: NodeKind;
  raw_kind: string | null;
  type: string | null;
  db: string | null;
  schema: string | null;
  lane: number;
  depth: number | null;
  badge: string;
  tip: string;
  marks: Mark[];
  rules: RuleHit[];
  action: NodeAction | null;
  group: string | null; // id in Graph.groups when this is a combined box
  classes?: PrivClass[] | null; // roles: what their own grants allow (counts on a folded box)
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  cls: EdgeCls;
  privs: string[];
  count: number | null;
  back: boolean;
  rules: RuleHit[];
  has: string[] | null;
  lacks: string[] | null;
}

export interface GraphGroup {
  kind: NodeKind;
  label: string;
  noun: string;
  count: number;
  sensitive: number;
  findings: number;
  classes: PrivClass[];
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: number;
  drill: NodeAction | null;
  lazy?: boolean; // nodes and edges left out: GET graph with the graph's src plus group=<box id> answers this box in full
  ids?: string[] | null; // a lazy folded role lane ("lane:<i>"): its role names, so other boxes' lines can end at it
}

export interface Graph {
  title: string;
  header: string;
  level: "object" | "schema" | "database" | "type" | "summary";
  note: string | null;
  full: boolean;
  selected: string | null;
  lanes: Lane[];
  nodes: GraphNode[];
  edges: GraphEdge[];
  groups: Record<string, GraphGroup>;
  src?: Record<string, string> | null; // graph endpoint params of this graph when its boxes are lazy
  legend: { kinds: NodeKind[]; edges: EdgeCls[]; marks: Mark[]; rules: boolean; back?: boolean }; // back: a dotted "also deeper" line is drawn
}

// ---------- frame ----------

export interface RunInfo {
  run_id: string;
  finished_at: string;
  when: string;
  old: boolean;
  at?: number | null; // finished, epoch seconds: the top bar ages it itself
}

export interface Note {
  key: string;
  title: string;
  meaning: string;
  fix: string | null; // the grant or step that removes the gap
  raw: string;
}

export interface MineState {
  loaded: boolean;
  user: string | null;
  loaded_at: string | null;
  expires_at: string | null;
  notes?: Note[];
}

/** GET /api/progress: the lines of the read from Snowflake running now (none when idle). */
export interface Progress {
  running: boolean;
  view: "shared" | "mine" | null;
  lines: { t: number; text: string }[];
  /** The last refresh (Rebuild snapshot / Read Snowflake again) run in the background, null before any. */
  job?: { id: number; what: string; state: "running" | "done" | "failed"; ok: boolean | null; message: string | null } | null;
}

export interface RuleInfo {
  num: string;
  title: string;
  why: string;
  severity: Severity; // the rule's; some findings of rules 5 and 9 are Critical (critical: when)
  critical?: string | null;
  area: string;
  spot: string;
  meaning: string;
  fix: string;
}

export interface KindStyle {
  bg: string;
  border: string;
  text: string;
  radius: string;
  dash: string;
}

/** One theme of ui.TOKENS: colour strings plus the node styles per kind. */
export type ThemeTokens = Record<string, string> & { kind: Record<string, KindStyle> };

export interface Meta {
  mode: Mode;
  source: Source;
  where: string;
  fetched_at: string | null;
  fetched_ts?: number | null; // when this server read it from Snowflake (a .cache/ copy keeps its time), epoch seconds
  view: View;
  loaded: boolean;
  run: RunInfo | null;
  sources: Record<string, string>;
  notes: Note[];
  mine: MineState;
  mine_available: boolean; // false inside Snowflake (owner's rights)
  mine_note?: string | null; // why My access is off here (server.mine_off), else null
  cache_hours: number; // hours a copy stays in .cache/ (0: memory only, as inside Snowflake)
  inside?: boolean; // Streamlit in Snowflake: reads run with the app owner's role
  csv?: boolean; // false: CSV=0 on the server, every CSV button hidden
  /** DuckDB copy of the data shown (cache.sql_info): file + schema, or why there is none */
  sql_copy?: { on: boolean; path: string; schema: string | null; note: string | null; written_at: string | null };
  error?: { detail: string; message: string }; // shared_not_loaded: SOURCE=direct reads only on a click
  // rules: findings at the worst severity, title "75157 high findings in 6 rules"
  pages: { key: Page; label: string; badge: number | null; severity?: Severity | null; title?: string | null; group: "home" | "access" | "ask" | "risk" | "govern" }[];
  default_user: string | null; // My access: the signed-in user; shared: none, the pages ask for a pick
  rule_counts: Record<string, number>; // findings per rule number
  rule_sev?: Partial<Record<Severity, Record<string, number>>>; // findings per severity, then rule (rules 5 and 9 can be in two): the side menu's Findings
  people?: { admins: number; stale: number } | null; // side menu: admin holders; disabled or dormant people holding roles (shared only)
  prefixes: { func: string; tech: string };
  admin_roles: string[];
  build_roles: string[];
  limits: { max_paths: number; max_objects: number; max_hops: number; dormant_days: number; max_depth_rule: number };
  read_privs: string[];
  sensitive_tags: string;
  rules: RuleInfo[];
  governance: Record<string, string> | null;
  protection: { row_tables: number; masked_columns: number; tagged_objects: number; unmasked: number } | null;
  tokens: { light: ThemeTokens; dark: ThemeTokens };
  help: Record<string, string>;
  type_icon: Record<string, [string, string]>;
  pclass: Record<string, string>;
  /** Snowflake's built-in grants left out (null with builtin=1 or none); graphs show them as one fold box. */
  builtin: BuiltinInfo | null;
  what_if_ops: WhatIfOp[];
}

export interface BuiltinInfo {
  label: string; // "Snowflake built-in (via PUBLIC)", the fold box's node id
  grants: number;
  objects: number;
  roles: string[];
}

export interface ReloadAnswer {
  ok: boolean;
  result: unknown;
  message: string;
}

export interface FindItem {
  id: string;
  name: string;
  kind: NodeKind;
  kind_label: string;
  type: string | null;
  sensitive: boolean;
  page: Page;
  answer: string;
  status?: UserStatus | null; // users only
  admin?: boolean; // a user holding an admin role
}

export interface ListItem {
  id: string;
  name: string;
  kind: NodeKind | null;
  type: string | null;
  status: UserStatus | null;
}

// ---------- shared row shapes ----------

export interface Tab {
  key: TabKey;
  label: string;
  count: number;
}

export interface PrivRow {
  privilege: string;
  cls: PrivClass;
  tab: TabKey;
  type: string;
  object: string;
  database: string;
  schema: string;
  name: string;
  future_label: string | null;
  granted?: string; // user page: the depth-1 role ("Use role")
  holder: string;
  depth: number;
  path: Path;
  count: number;
  paths_note: string;
  sensitive: boolean;
  hidden: boolean;
}

export interface ReachRow {
  role: string;
  kind: NodeKind;
  tab: "granted" | "database_roles";
  depth: number;
  direct: boolean;
  path: Path;
  count: number;
  admin: boolean;
}

export interface Account {
  admin: { role: string; path: Path }[];
  privileges: { privilege: string; path: Path; via_public: boolean }[];
  public: string[];
}

/** One rule finding, the same shape on every page (server.finding). */
export interface Finding {
  num: string;
  title: string;
  severity: Severity;
  area: string;
  grantee: string;
  kind: NodeKind;
  what: string; // the role, object or privilege involved
  impact: { text: string; tone: "ok" | "warn" | "bad" } | null;
  people: string[]; // users affected: the grantee if a user, else those who lose access when it is fixed
  paths: Path[];
  iac: string;
  sql: string;
  same_fix: string;
  changes: WhatIfChange[]; // the fix as What if changes (the change plan); empty when the fix revokes no grant
  objects: string[]; // objects the finding is about (group by object)
}

export type RowsState = "all" | "filtered" | "none" | "unknown";
export type ColState = "clear" | "masked" | "unknown";

export interface StateWhy<S> {
  state: S;
  reason: string;
  policy?: string | null;
  body?: string | null;
}

/** What they see, a page of objects at a time (v_offset=, limit=): only the fields the table shows. */
export interface Sees {
  rows: { object: string; columns: (StateWhy<ColState> & { column: string })[]; rows: StateWhy<RowsState> & { condition?: string | null } }[];
  total: number;
  offset: number;
}

export interface DataView {
  object: string;
  name: string;
  can_read: boolean;
  tags: string[];
  columns: (StateWhy<ColState> & { column: string; tags: string[]; sensitive: boolean })[];
  rows: StateWhy<RowsState> & { condition?: string | null };
  summary: string;
}

export interface SensitiveReach {
  object: string;
  cols: string[];
  role: string;
  path: Path | null;
  text: string; // "EMAIL masked · all rows" as the granted role sees it
}

export interface UsageCard {
  days: number;
  source: string;
  readable: boolean;
  roles: { role: string; kind: NodeKind; default: boolean; status: "used" | "secondary" | "unused"; queries: number;
    last_used: string | null; takes: number | null }[]; // takes: objects the user loses if this unused role goes
  warehouses: { name: string; queries: number; last_used: string }[];
}

/** Role page: users holding the role who used it in the query history. */
export interface RoleUsage { holders: number; used: number; unused: string[] }

// ---------- pages ----------

export interface UserProfile {
  id: string;
  name: string;
  type: string;
  status: UserStatus;
  disabled: boolean;
  service: boolean;
  default_role: string | null;
  secondary_roles: "All" | "None";
  default_warehouse: string | null;
  last_login: string | null;
  last_login_text: string;
  login_mark: "" | "Dormant" | "Never";
  login_days: number | null;
}

export interface UserPage {
  view: View;
  user: UserProfile;
  filters: {
    roles: "all" | "default";
    depth: number | null;
    dataonly: boolean;
    schema: string;
    otype: string;
    on: string;
    priv: string;
    privileges: string[];
  };
  banners: Banner[];
  findings: Finding[]; // the worst FIRST_FINDINGS
  findings_total: number;
  findings_sev: Partial<Record<Severity, number>>;
  kpis: {
    privileges: number;
    objects: number;
    paths: number;
    multi: number;
    roles: number;
    roles_direct: number;
    deepest: number;
    sensitive: number | null;
    sensitive_known: boolean;
    admin_roles: number;
    account_privs: number;
  };
  account: Account;
  graph: Graph | null;
  tabs: Tab[];
  roles: ReachRow[]; // the privilege rows themselves come a page at a time from GET privs (PrivsPage)
  multi: { rows: { privilege: string; cls: PrivClass; object: string; depth: number; path: Path }[]; total: number; shown: number };
  can_read: Sees | null;
  sensitive: { known: boolean; roles: string[]; rows: SensitiveReach[] } | null;
  granted: { role: string; kind: NodeKind; default: boolean; used: { queries: number; last_used: string } | null; used_text: string }[];
  usage: UsageCard;
  capped: string[];
  refs: Refs;
}

/** One page of a table paged on the server (GET privs: rows are ObjRow of components/tabs.ts). */
export interface Paged<R> { rows: R[]; total: number; offset: number; limit: number }

export type HoldCell = "direct" | "inherited" | "owner" | "lacks";

export interface HeldRow {
  grantee: string;
  id: string;
  kind: NodeKind;
  kind_label: string;
  status: UserStatus | null;
  depth: number;
  direct: boolean;
  only_via: string[];
  path: Path;
  count: number;
  loses_it: boolean;
  loses: [string, string][];
}

export interface RolePage {
  view: View;
  role: { id: string; name: string; kind: NodeKind; owner: string[]; admin: boolean };
  filters: {
    depth: number | null;
    users: boolean;
    sensitive: boolean;
    schema: string;
    otype: string;
    cut: string;
    lacks: string;
    cuts_total: number; // direct holders: the cut picker searches /api/list?what=direct_holders
    gaps: string[];
  };
  kpis: {
    privileges: number;
    future: number;
    effective: number;
    above: number;
    above_direct: number;
    users: number;
    users_direct: number;
    farthest: number;
    sensitive: number;
    holds_roles: string[];
  };
  scope_kpis: { direct: number; effective: number; objects: number; holders: number; sensitive: number } | null;
  banners: Banner[];
  findings: Finding[]; // the worst FIRST_FINDINGS
  findings_total: number;
  findings_sev: Partial<Record<Severity, number>>;
  usage: RoleUsage;
  readonly_writes: {
    object: string;
    privileges: string[];
    holder: string;
    inherited: boolean;
    how: string;
    read_only: number;
    objects: number;
  }[];
  account: Account;
  graph: Graph | null;
  held_by: {
    rows: HeldRow[]; // the first users and roles (the small diagram); the table pages GET /api/held
    total: number;
    users: number;
    roles: number;
    revoke: { grantee: string; lost: number; users: number; iac: string; sql: string } | null;
  };
  holds: {
    types: {
      type: string;
      privs: string[];
      count: number; // every object of the type; rows: one page of the open type (htype, h_offset), none for the rest
      offset: number;
      rows: { object: string; name: string; cells: Record<string, HoldCell>; text: string }[];
    }[];
    other: { privilege: string; cls: PrivClass; type: string; object: string; name: string }[]; // one page (o_offset)
    other_total: number;
    other_offset: number;
    count: number;
    objects: number;
  };
  tabs: Tab[]; // privilege rows: GET /api/privs?of=role, a page at a time
  roles: ReachRow[];
  can_read: Sees | null;
  capped: string[];
  refs: Refs;
}

export interface MatrixCell {
  has: boolean;
  owner: boolean;
  depth: number | null;
  count: number;
  title: string;
}

export interface MatrixRow {
  user: string;
  type: string;
  status: UserStatus;
  admin: string[];
  real: boolean;
  cells: Record<string, MatrixCell>;
  seen: Record<string, StateWhy<ColState>>;
  rows_state: StateWhy<RowsState> | null;
  via: { classes: PrivClass[]; roles: string[]; holders: string[] }[];
  depth: number | null;
  paths: number;
  path: Path | null;
  admin_paths: Path[];
}

export interface Sensitivity {
  object_tags: { label: string; origin: string; sensitive: boolean }[];
  row_policies: { name: string; args: string; text: string; from_text: boolean }[];
  columns: {
    column: string;
    tags: { label: string; sensitive: boolean }[];
    semantic: string;
    masking: string[];
    clear_for: { role: string; how: "session" | "primary" }[];
    clear_known: boolean;
    unmasked_everyone: boolean;
  }[];
  policy_text: Record<string, string>;
  readers: { people: number; admin: number; service: number };
}

export interface GranteeRow {
  grantee: string;
  id: string;
  kind: NodeKind;
  kind_label: string;
  status: UserStatus | null;
  privileges: { privilege: string; cls: PrivClass; tab: TabKey }[];
  tabs: TabKey[];
  depth: number;
  path: Path;
  count: number;
}

export interface ObjectPage {
  view: View;
  object: {
    id: string;
    type: string;
    database: string;
    schema: string;
    name: string;
    sensitive: boolean;
    privileges: string[];
  };
  filters: { type: string; priv: string; active: boolean; users: boolean };
  kpis: {
    people: number;
    disabled: number;
    service: number;
    admin: number;
    read: number;
    write: number;
    own: number;
    roles: number;
    direct: number;
    owners: string[];
    deployers: string[];
    owner_note: string;
    longest: number;
  };
  admin_paths: Path[]; // the first MAX_ADMIN_PATHS
  admin_users: number;
  admin_total: number;
  sensitivity: Sensitivity | null;
  matrix: { privs: string[]; sensitive_cols: string[]; row_policy: boolean; rows: MatrixRow[]; total: number; offset: number }; // rows: one page (m_offset=, limit=)
  graph: Graph | null;
  sees: {
    cols: string[];
    row_policy: boolean;
    rows: { role: string; rows: StateWhy<RowsState>; columns: (StateWhy<ColState> & { column: string })[] }[];
  } | null;
  tabs: Tab[];
  grantees: { total: number; users: number; roles: number }; // the rows: GET /api/grantees, a page at a time
  capped: string[];
  refs: Refs;
}

export interface Also { level: string; count: number; where: string }

export interface Nearest {
  path: Path; // user[, via], role, ..., holder, object; "<NEW_ROLE>" when a database role needs an account role between
  missing: number; // the link path[missing] -> path[missing + 1] is missing
  role: string;
  to: string;
  to_user: boolean;
  cost: number;
  people: number; // others who would get it too
  holders: number;
  extra: number;
  also: Also[];
  rule1: boolean;
  broad: string | null;
}

/** Who Can they? / Request access asks about: a user or a role (separate namespaces; id as in a.uid). */
export interface Subject { kind: NodeKind; name: string; id: string; user: boolean; people: number | null; database: string | null }

export interface CheckPage {
  verdict: "yes" | "partly" | "no";
  subject: Subject;
  layers: { step: string; ok: boolean; result: string; reason: string }[] | null;
  roles_count: number;
  ask_priv: string;
  held: { privilege: string; held: boolean }[];
  lanes: { path: Path; privileges: string[] }[];
  lanes_total: number;
  cut: string[];
  cuts: { iac: string; sql: string; people: string[]; lost: number; edges: { grantee: string; to: string; priv: string | null; user: boolean }[] }[];
  nearest: Nearest[] | null; // null: not worked out, ask again with near=1
  approver: string | null;
  view: View;
  user: string;
  object: string;
  type: string;
  priv: string; // "*" = all privileges the user holds on the object
  privileges: string[];
  answer: {
    yes: boolean;
    how: "paths" | "owner" | "admin" | "none";
    title: string;
    text: string;
    tone: "warn" | "low" | null;
    stats: [string, number | string][];
  };
  status: UserStatus | null; // null for a role
  dormant_days: number | null;
  admin_paths: Path[];
  paths: { path: Path; depth: number; holder: string; how: string; privilege: string }[];
  paths_total?: number; // every path (paths lists the first MAX_PATHS)
  owner: Path[];
  choke: string[];
  options: { iac: string; sql: string; affects: number; users: string[]; edges: number }[];
  use_role: string | null;
  warehouse: string | null;
  read: { summary: string; rows: StateWhy<RowsState> | null; columns: (StateWhy<ColState> & { column: string })[]; role_only: string | null } | null;
  graph: Graph | null;
  capped: string[];
  refs: Refs;
}

export interface RequestPage {
  view: View;
  user: string; // the subject's name: a user, or a role (subject.user false)
  subject: Subject;
  object: string | null; // null: no obj= asked, the rest is not sent
  type: string;
  database: string; // the object's database ("" for an account-level object)
  need: "read" | "change";
  privileges: string[];
  level: string | null; // the user's step on the object today
  has: boolean;
  via_admin?: string[]; // has only through these admin roles (they inherit every role)
  asked: { role: string; kind: NodeKind; to: string | null; rule1: boolean; people: number; broad: boolean; change: CompareChange } | null; // picked on Can they?
  suggestions: { role: string; path: Path; holders: number; extra: number; also: Also[]; unmasked: string[]; people: number; broad: boolean; change: CompareChange }[];
  approver: string | null;
  owners: string[];
  refs: Refs;
}

export interface SensitivePage {
  view: View;
  state: "ok" | "mine" | "unavailable" | "no_tags" | "none_sensitive";
  governance: Record<string, string> | null;
  protection: { row_tables: number; masked_columns: number; tagged_objects: number; unmasked: number } | null;
  filters: { tag: string; db: string; people: boolean; tags: string[]; dbs: string[] };
  kpis: {
    objects: number;
    columns: number;
    whole: number;
    people: number;
    admin: number;
    disabled: number;
    service: number;
    unmasked: number;
    stale: string[]; // the first NAMES of stale_total
    stale_total: number;
  };
  objects: {
    object: string;
    database: string;
    schema: string;
    name: string;
    type: string;
    tags: { label: string; origins: string[] }[];
    cols: string[];
    masked: [number, number];
    row_policies: string[];
    readers: { active: number; dormant: number; service: number; admin: number }; // each reader once
    columns: { column: string; masked: boolean; policies: string[] }[];
    clear: number | null; // readers who see a sensitive value in clear (null: a policy text gives no answer)
    roles: string[]; // the first ROLES_SHOWN (limit=0: all)
    roles_total: number;
  }[]; // one page: objects_offset, limit= rows (limit=0: all)
  objects_total: number;
  objects_offset: number;
  readers: {
    user: string;
    type: string;
    status: UserStatus;
    last_login_text: string;
    objects: number | null; // sensitive objects read (null: every one, through an admin role)
    roles: string[];
    path: Path | null;
    via_admin: boolean;
    admin_paths: Path[];
  }[]; // one page, as objects
  readers_total: number;
  readers_offset: number;
  catalog: CatalogRow[] | null; // screen 8, most exposed first: only with show=catalog
  catalog_total: number;
  row_list: { object: string; policies: string[] }[]; // tables with a row policy, sensitive or not: one page at row_offset
  row_total: number;
  row_offset: number;
  refs: Refs;
}

export interface StalePerson { user: string; status: UserStatus; service: boolean; roles: number; findings: number; sensitive: boolean; last_login: string | null }

export interface AdminPerson {
  user: string;
  service: boolean;
  roles: string[];
  account: string[]; // account privileges not through PUBLIC, the strong ones first
  strong: string[]; // of them, those that change who can do what (access.ADMIN_LEVEL): red
  paths: Path[];
  status: UserStatus;
  last_login: string | null;
}

/** A finding in a Rules page list: Finding without the fix texts, with the first path and people only. The whole
 * finding comes from /api/finding?id=. */
export interface FindingRow extends Omit<Finding, "iac" | "sql"> {
  id: number;
  people_total: number;
  paths_total: number;
  fix: boolean; // the whole finding has IaC / SQL fix text
}

/** One group of the filtered findings: a rule, a person, an object ("" = none) or, for the heat grid, a grantee. */
export interface FindingGroup {
  key: string;
  title: string | null; // the rule's title (by rule)
  severity: Severity; // the worst in the group
  findings: number;
  rules: number;
  people: number | null; // by rule, object and grantee
  kind: NodeKind | null; // the grantee's (grid, grantee)
  objects?: number; // by grantee: the objects its findings are on
  said?: { text: string; findings: number | null }[]; // by grantee: what most of its findings say, objects as "…" (rule 17: one example, findings null)
  said_total?: number; // patterns in all
  tags?: string[]; // rule 17: why the role counts as read-only (named / used read-only)
  sevs?: Partial<Record<Severity, number>>; // findings per severity
}

export interface RulesPage {
  view: View;
  scope: "account" | "mine";
  filters: { grantee: string; of: "user" | "role" | ""; sev: Severity | ""; rule: string; q: string; area: string; people: boolean; off: string[];
    by: "rule" | "person" | "object" | "grid"; group: string | null };
  counts: Record<Severity | "Passing", number>; // every finding (of grantee=)
  per_rule: Record<string, number>;
  skipped: Record<string, string>; // rules that did not run: HIERARCHY=0 / ACTIVITY=0 -> "skipped (...)"
  sev_counts: Record<Severity, number>; // after every filter but sev
  hidden_off: number; // findings of the off= rules
  areas: string[];
  total: number; // after every filter
  groups: FindingGroup[]; // the first 200
  groups_total: number;
  grid: { rules: string[]; rows: { grantee: string; kind: NodeKind; severity: Severity; total: number; counts: Record<string, number> }[] } | null;
  findings: FindingRow[]; // one page (offset, limit) of the group= or of every filtered finding
  findings_total: number;
  offset: number;
  limit: number;
  rows_unknown: string[]; // this and admins: not in a group= answer
  admins: AdminPerson[]; // the first 200
  admins_total: number;
  stale: StalePerson[]; // one page (s_offset=, limit=, sq= a name): disabled, dormant or never logged in, still holding roles (rules 8 and 16)
  stale_total: number;
  stale_matched: number; // the rows sq= keeps, before the page
  stale_offset: number;
  stale_split: Record<string, number>; // all of them per status
  refs: Refs;
}

export interface FindingPage { view: View; finding: Finding & { id: number }; refs: Refs }

export interface ReviewRow {
  database: string;
  schema: string;
  object: string;
  type: string;
  future_label: string | null;
  user: string;
  user_type: string;
  status: UserStatus;
  last_login: string | null;
  privileges: string[];
  classes: PrivClass[];
  sensitive: string[];
  granted: string[];
  path: Path;
  admin: boolean;
}

export interface ReviewPage {
  view: "shared";
  filters: {
    db: string; // "*": every database; the picker searches /api/list?what=databases
    schema: string;
    schemas: string[];
    object: string;
    objects: string[];
    active: boolean;
    hideusage: boolean;
  };
  kpis: {
    objects: number;
    users: number;
    not_active: number;
    rows: number;
    admin_rows: number;
    hidden_usage: number;
    sensitive: number;
    csv_rows: number; // rows the CSV has: every row of the scope, no search or hiding
  }; // over the rows the tabs hold: after q and Hide USAGE rows
  counts: { sens: number; all: number }; // rows per tab, after q
  part: "sens" | "all";
  note: string | null; // the Sensitive objects tab asked but empty: why All is shown
  total: number; // rows of the tab shown
  offset: number;
  limit: number;
  sort: string;
  dir: 1 | -1;
  csv_max: number; // rows one CSV holds at most (kpis.csv_rows is what it would have)
  rows: ReviewRow[]; // one page: offset .. offset + limit
  refs: Refs;
}

// ---------- What if (GET /api/whatif?changes=<JSON list>) ----------

export type WhatIfOp = "revoke_role_from_user" | "revoke_role_from_role" | "revoke_priv" | "drop_role" | "empty_public";

export type WhatIfChange =
  | { op: "revoke_role_from_user"; role: string; user: string }
  | { op: "revoke_role_from_role"; role: string; grantee: string }
  | { op: "revoke_priv"; role: string; privilege: string; object: string }
  | { op: "drop_role"; role: string }
  | { op: "empty_public" };

export interface WhatIfStep {
  change: WhatIfChange;
  label: string;
  iac: string;
  sql: string; // "" when no SQL fits
}

export interface WhatIfObjectRow {
  object: string;
  type: string;
  privileges: string[];
  classes: PrivClass[];
  path: Path; // shortest path before: user > ... > holder > object
  via?: Path; // kept rows: the path left
  through?: string; // kept rows: its first role the old path did not use
}

export interface WhatIfUser {
  user: string;
  status: UserStatus;
  lost: number; // privileges lost (exact)
  objects: number; // objects lost (exact)
  kept: number; // privileges kept through another path (exact)
}

/** One person's rows: GET /api/whatif?changes=…&user=<name> */
export interface WhatIfUserRows extends WhatIfUser {
  lost_rows: WhatIfObjectRow[]; // first max_paths objects
  kept_rows: WhatIfObjectRow[];
  kept_roles: { role: string; path: Path; via: Path; through: string }[];
}

/** People who lose the same thing: the first names, lost and kept rows, and the sentence. */
export interface LossGroup {
  key: string;
  n: number;
  users: { user: string; status: UserStatus }[];
  off: number; // not active
  lost: WhatIfObjectRow[]; // first 3
  kept: WhatIfObjectRow[]; // first 2
  lost_sum: number;
  kept_sum: number;
  text: string;
}

export interface WhatIfFinding {
  num: string;
  title: string;
  severity: Severity;
  grantee: string;
  kind: string;
  detail: string;
  path: Path;
  status: "fixed" | "new";
  changed: boolean; // the rule still fires on that grantee, with another detail
}

export interface WhatIfPage {
  changes: WhatIfStep[];
  summary: string;
  counts: {
    users: number;
    objects: number;
    kept: number;
    unreached: number;
    ownerless: number;
    orphans: number;
    unreached_roles: number;
    fixed: number;
    new: number;
    changed: number;
  };
  users: WhatIfUser[]; // the first WHATIF_USERS of users_total, most lost first
  users_total: number;
  groups: LossGroup[]; // biggest first, the first WHATIF_GROUPS of groups_total
  groups_total: number;
  impact: { object: string; type: string; people: number; privileges: string[] }[]; // objects people lose, most people first
  impact_total: number;
  lost_privs: number;
  kept_privs: number;
  rows_capped: boolean; // someone lists fewer objects than they lose
  objects: { object: string; type: string; sensitive: boolean; unreached: boolean; ownerless: boolean }[]; // first WHATIF_USERS of objects_total
  objects_total: number;
  roles: { role: string; kind: string; orphan: boolean; unreached: boolean }[]; // first WHATIF_USERS of roles_total
  roles_total: number;
  findings: WhatIfFinding[]; // the first WHATIF_USERS of findings_total
  findings_total: number;
  iac: string;
  sql: string;
  refs: Refs;
}

// ---------- redesign: access ladder ----------

export type Level = "names" | "read" | "change" | "own" | "admin";
export type Category = "data" | "runnable" | "account" | "names";

export interface RowFinding { num: string; severity: Severity; label: string }

/** One object at its highest level (access.access_objects + server.access_page). */
export interface AccessObject {
  object: string;
  type: string;
  database: string;
  schema: string;
  category: Category;
  level: Level | null;
  privileges: string[];
  path: Path; // shortest: subject, ..., holder, object
  paths: Path[];
  first: string | null; // first role after the subject (null: granted straight)
  holder: string;
  ways: number;
  depth: number;
  sensitive: boolean;
  columns: { column: string; state: ColState; reason: string }[];
  findings: RowFinding[];
  label: string | null; // "Future tables · SALES.CORE"
}

export interface LadderCounts { read: number; change: number; own: number; admin: number; future?: number; usage: number; runnable: number; account: number; sensitive?: number; schemas?: number }

export interface Who {
  kind: NodeKind;
  name: string;
  id: string;
  type: string;
  status: UserStatus | null;
  disabled: boolean;
  last_login: string | null;
  login_mark: string;
  default_role: string | null;
  secondary_all: boolean;
  held_by: { users: number; roles: number } | null;
}

export interface AccessPage {
  view: View;
  who: Who;
  counts: LadderCounts & { sensitive: number; schemas: number };
  objects: AccessObject[]; // one page (offset, limit) of the list filters asked for; total: all that match
  total: number;
  data: number; // entries in the list before the filters (data, plus names with usage=1)
  offset: number;
  limit: number;
  groups: Record<string, number>; // group=schema|type: entries per group, over every page
  runs: AccessObject[]; // things they can run, the first PAGE of runs_total
  runs_total: number;
  powers: AccessObject[]; // powers over the account, the first PAGE of powers_total
  powers_total: number;
  heat: { schema: string; read: number; change: number; own: number; sensitive: number }[]; // riskiest HEAT schemas (hq= filters), each object in one cell
  heat_total: number;
  why: { role: string; kind: NodeKind; note: string; kids: string[]; kids_total: number }[]; // kids: the first KIDS
  why_more: number; // a role's holders past the HOLDERS listed
  deepest: number;
  roles: number;
  admin_roles?: string[]; // admin roles held (a role: itself too); what they reach is not in the counts
  refs: Refs;
}

export interface HomePage {
  view: View;
  me: { user: string; counts: LadderCounts } | null;
  risks: Record<Severity, number> | null;
  counts: { users: number; roles: number; objects: number; sensitive: number };
  per_rule: Record<string, number> | null; // findings per rule (shared only): Home's findings by area
  rule_sev?: Partial<Record<Severity, Record<string, number>>>; // findings per severity, then rule (shared only)
  subjects?: Record<Severity, { people: number; roles: number }>; // distinct people and roles per severity (shared only)
  /** Critical, then High rules, fewest findings first (shared only) */
  act_first?: { num: string; severity: Severity; title: string; findings: number; subjects: number; names: { id: string; kind: NodeKind }[] }[];
  skipped: Record<string, string> | null; // rules that did not run (shared only), as RulesPage.skipped
  protection: { unmasked: number; unmasked_names: { object: string; column: string }[]; unmasked_columns: number; dormant: number; dormant_names: string[]; tagged: number;
    masked: number; row_tables: number } | null; // the row-policy tables are listed on Sensitive data (show=rows)
  cards: HomeCards | null; // shared only
}

/** Home's area cards (server.home_cards): first NAMES names, counts per part. */
export interface HomeCards {
  admins: { total: number; service: number; by_role: { role: string; people: number }[]; account_only: number; names: { user: string; role: string; login: string }[] }; // riskiest first
  stale: { total: number; by_status: Record<string, number>; names: string[] };
  people: { by_status: Record<string, number>; service: number };
  roles: Record<string, number>; // per role kind
  objects: { by_type: { type: string; n: number }[] };
  activity: { ok: boolean; reason: string | null; users: number; daily: { day: string; queries: number }[] };
  /** counts null: not compared yet (Changes compares on open), or reason: no earlier snapshot kept */
  changes: { counts: { all: number; gain: number; lose: number; risk: number; sensitive: number } | null; high: number; before: string | null; reason: string | null } | null;
}

// ---------- who has access (screen 2) ----------

export type ObjLevel = "names" | "use" | "read" | "change" | "own" | "admin";

/** One user or role on one object, at its highest step (a.who_entry). */
export interface WhoEntry {
  name: string;
  level: ObjLevel;
  privileges: string[]; // highest first; admin preset: the admin roles held
  path: Path; // shortest: name ... grant holder, object (admin without a grant: ends at the admin role)
  first: string | null;
  holder: string;
  ways: number;
  depth: number | null;
}

export interface WhoPerson extends WhoEntry {
  id: string;
  admin: string[];
  status: UserStatus;
  service: boolean;
  days: number | null;
  login: string;
  mark: string;
  columns: { column: string; state: string; reason: string }[];
}

export interface WhoRole extends WhoEntry { kind: NodeKind; users: number }

export interface WhoColumn {
  column: string;
  tags: string[];
  sensitive: boolean;
  policies: string[];
  clear: string[];
  masked: string[];
  unknown: string[];
}

export interface WhoPage {
  view: View;
  object: {
    id: string | null; preset: "admin" | null; type: string; database: string | null; schema: string | null; name: string;
    sensitive: boolean; tags: string[]; columns: number; masking: string[]; row_policies: string[]; owners: string[]; owner_note: string;
  };
  people: WhoPerson[]; // the first 200 matching q= (plus as= and sel=); shown counts every match
  shown: { people: number; roles: number; groups: number };
  /** A Streamlit app: it runs with its owner's rights, so viewers see what the owner role reads. */
  app: { owner: string[]; sensitive: Record<string, string[]>; holders: Record<string, string[]>; exposed: Record<string, string[]> } | null;
  roles: WhoRole[];
  groups: { level: ObjLevel; privileges: string[]; route: string[]; names: string[] }[];
  counts: { levels: Record<ObjLevel, number>; people: number; roles: number; disabled: number; dormant: number };
  columns: WhoColumn[];
  default_user: string | null;
  refs: Refs;
}

// ---------- screen 4: access graph (GET /api/map?table=|role=|user=&same=1&admin=1) ----------

export type Risk = "admin" | "public" | "writes";

export interface MapNode {
  level: ObjLevel | null; // the step it leads to
  people: string[]; // first 30 users through it
  people_count: number;
  leads: string[]; // first 30 objects it leads to
  leads_count: number;
  risk: Risk | null;
  members: string[] | null; // a stack: the people in it
}

export interface MapPage {
  view: View;
  start: "object" | "role" | "user";
  name: string;
  id: string; // node id of the start
  graph: Graph;
  detail: Record<string, MapNode>;
  risky: Record<string, Risk>; // edge id -> why
  risky_nodes: Record<string, Risk>;
  why: Record<Risk, string>;
  builtin: { label: string; grants: number; roles: string[]; objects: number } | null;
  refs: Refs;
}

// ---------- screen 7: what they see (GET /api/see?user=|role=) ----------

export interface SeeCard {
  object: string;
  type: string;
  sensitive: boolean;
  rows: { state: RowsState; reason: string; policy: string | null };
  columns: { column: string; sensitive: boolean; state: ColState; reason: string; policy: string | null; fix: boolean }[];
}

export interface SeePage {
  view: View;
  who: { kind: NodeKind; name: string; id: string; type: string; status: UserStatus | null; default_role: string | null;
    secondary_all: boolean; roles: string[] };
  known: boolean; // policies readable here (not in My access without tags)
  cards: SeeCard[]; // one page (c_offset, limit) of the sensitive ones, or of all (all=1)
  cards_total: number;
  cards_offset: number;
  counts: { objects: number; sensitive: number; columns: number; clear: number; masked: number; unknown: number;
    unprotected: number; rows: number } | null;
  can_read: Sees | null;
  sensitive: { known: boolean; roles: string[]; rows: SensitiveReach[] } | null;
  usage: UsageCard | null; // a person
  role_usage: RoleUsage | null; // a role
  refs: Refs;
}

// ---------- screen 9: compare (GET /api/compare?a=&b=&scope=sensitive|all|db&db=) ----------

export type Diff = "only_a" | "only_b" | "different" | "same";
export interface CompareSide { level: string | null; privileges: string[]; sees: string }

export interface CompareRow {
  object: string; type: string; database: string; schema: string; name: string;
  diff: Diff;
  a: CompareSide | null;
  b: CompareSide | null;
  extra_a: string[];
  extra_b: string[];
}

/** A grant or revoke as text only; sql, roleDb and toDb from access.with_sql. */
export interface CompareChange { op: "grant" | "revoke"; role?: string; privilege?: string; objectType?: string; object?: string; to: string; toUser: boolean;
  sql: string; roleDb: boolean; toDb: boolean }

export interface ComparePage {
  view: View;
  a: { name: string; id: string; kind: NodeKind };
  b: { name: string; id: string; kind: NodeKind };
  scope: "sensitive" | "all" | "db";
  db: string;
  sensitive: boolean;
  rows: CompareRow[]; // one page (offset) of the rows f= / same= keep; rows_total: all of them
  rows_total: number;
  offset: number;
  any: boolean; // either reaches something in scope
  counts: Record<Diff, number>;
  match: CompareChange[]; // make B match A
  extras: CompareChange[]; // remove A's extras
  refs: Refs;
}

/** Screen 8: one sensitive object with its protection. */
export interface CatalogRow {
  object: string;
  name: string;
  ns: string;
  type: string;
  labels: string[]; // tag=value
  groups: ("pii" | "confidential")[];
  status: "not" | "partly" | "protected" | "whole";
  masked: [number, number];
  columns: { column: string; masked: boolean; policies: string[] }[];
  unmasked: number;
  row_policies: string[];
  readers: number; // users who can read it, disabled and service users included
  clear: number | null; // of them, who see a sensitive value in clear (null: a policy text gives no answer)
  admin: number;
}

/** Screen 6 grid (/api/grid). */
export interface GridCell { level: string; privileges: string[]; path: Path }
export interface GridRow {
  user: string;
  type: string;
  status: UserStatus;
  days: number | null;
  last_login: string;
  admin: string[];
  roles: string[]; // granted roles on the paths: what a revoke takes away
  suggest: string | null; // dormant / disabled / never: suggested revoke
  cells: Record<string, GridCell>;
  beyond?: number; // objects they reach that the grid does not draw (past GRID_MAX)
}
export interface GridPage {
  view: View;
  scope: "sensitive" | "db" | "all" | "object";
  db: string;
  dbs: string[];
  object: string;
  columns: { id: string; name: string; ns: string; note: string; sensitive: boolean }[];
  rows: GridRow[]; // the first rows_cap of matched: admins and the highest access first
  matched: number; // rows the filters (people, stale, q) keep
  rows_cap: number;
  total: number;
  cap: number;
  sensitive: number;
  counts: { people: number; admin: number; stale: number; service: number };
  refs: Refs;
}

/** Screen 16 (/api/flow). */
export interface FlowNode { id: string; label: string; count: number; kind?: string; ns?: string; status?: string | null; unmasked?: string[]; masked?: string[]; row_policies?: string[]; roles?: number }
/** One real role of the flow (not a box): people who hold it, sensitive objects it reaches. */
export interface FlowRole { id: string; kind: string; count: number; objects: number }
export interface FlowLink { source: string; target: string; count: number }
/** The box followed (sel=): link keys "source>target" -> people and their main group; users: the box's first 200. */
export interface FlowFollow { sel: string | null; lit: string[] | null; width: Record<string, number>; tone: Record<string, string>; headline: string; users: string[]; count: number }
export interface FlowPage {
  view: View;
  state: "ok" | "mine" | "none";
  groups: FlowNode[];
  roles: FlowNode[];
  objects: FlowNode[]; // show=graph: the FLOW_OBJECTS most read, then one fold box (kind "fold")
  links: FlowLink[]; // show=graph only
  select: string | null;
  follow: FlowFollow | null; // show=graph only
  roles_all: FlowRole[]; // one page (roles_offset, e_offset=) of every role, most people first
  roles_total: number;
  roles_offset: number;
  refs: Refs;
}

/** Screen 13 (/api/usage): granted next to used, from ACCESS_HISTORY. */
export interface UsageRow {
  object: string;
  type: string;
  database: string | null;
  schema: string | null;
  sensitive: boolean;
  level: string; // granted step
  used: "read" | "change" | null; // null: not used in the period
  privileges: string[];
  unused: string[];
  weeks: number[]; // queries per week, oldest first
  reads: number;
  writes: number;
  last: string | null;
  holder: string;
  suggest: "keep" | "trim" | "drop" | "none"; // none: nobody holds the role
  text: string;
}
export interface UsagePage {
  view: View;
  who: { kind: NodeKind; name: string; id: string; status: UserStatus | null };
  days: number;
  periods: number[];
  available: boolean;
  reason: string | null;
  enable: string;
  source: string | null;
  rows: UsageRow[]; // one page (u_offset, limit) of the filter (f) and search (q)
  rows_total: number;
  offset: number;
  f: string;
  weeks: string[]; // Monday of each week
  counts: { objects: number; used: number; drop: number; trim: number; keep: number; write_unused: number; changes: number; sensitive: number } | null;
  changes: WhatIfChange[]; // none when changes_capped (more than the server lists)
  changes_capped: boolean;
  trim_text: string; // what the trim takes away, object by object
  sql: string; // the trim as What if writes it
  people: number;
  refs: Refs;
}

/** Screen 14 (/api/changes): this snapshot against the previous one. */
export type ChangeKind = "gain" | "lose" | "user" | "risk" | "fixed";
export interface ChangeEvent {
  id: string;
  kind: ChangeKind;
  text: string;
  impact: string;
  by: string | null; // GRANTED_BY, when known
  edge?: ChangeEdge; // gain / lose: the grant drawn as two boxes and a + / - link
  sensitive: boolean;
  findings: { num: string; severity: Severity; title: string; fixed: boolean }[];
  link: { page: Page; params: Record<string, string> };
  subjects: string[];
  people: string[];
  objects: string[];
}
export interface ChangeEdge { source: string; source_kind: NodeKind; target: string; target_kind: NodeKind; privilege: string | null; added: boolean }
export interface ChangeCounts { all: number; gain: number; lose: number; risk: number; sensitive: number }
export interface ChangesPage {
  view: View;
  subject: string | null;
  available: boolean;
  reason?: string;
  events: ChangeEvent[]; // this page of the filter's events (f, offset; limit server.PAGE)
  events_total: number;
  offset: number;
  f?: "all" | "gain" | "lose" | "risk" | "sensitive";
  counts: ChangeCounts | null; // over every event
  text?: string;
  before?: string;
  now?: string;
  new?: number;
  fixed?: number;
  high?: number;
  severity?: { new: Record<Severity, number>; fixed: Record<Severity, number> } | null; // the strip; null for one subject
  refs: Refs;
}

/** Activity tab (/api/activity): table use per day of an object, a person or a role (ACCESS_HISTORY). */
export type ActivityKey = "user" | "role" | "client" | "type" | "object";
export interface ActivityBy { key: string; read: number; write: number; ddl: number; last: string; daily: number[] }
export interface ActivityRow {
  user: string; role: string; client: string; type: string; object: string; action: "READ" | "WRITE" | "DDL";
  queries: number; days: number; first_day: string; last: string; daily: number[];
  hours: number[]; weekend: number; weekend_hours: number[]; dh?: number[][]; // dh: [day index, UTC hour, queries] // weekday queries per UTC hour (24); weekend total and per hour
  kind: "person" | "service" | "system"; interactive: boolean; // the user's type; run from Snowsight, SnowSQL or the CLI
}
/** Sensitive data of one object used: columns, policies, and per user and role used what they see. */
export interface ActivitySensitive {
  object: string; sensitive: boolean; columns: string[]; whole: boolean; masking: Record<string, string[]>; row_policies: string[];
  people: { user: string; role: string; read: boolean; clear: string[]; masked: string[]; rows: "all" | "filtered" | "none" | "unknown" }[];
}
export interface ActivityPage {
  view: View;
  what: "object" | "user" | "role" | "app" | "scope" | "warehouse"; // app: a Streamlit app's queries for its viewers;
  // scope: every object in a database or schema; warehouse: who ran queries on it (QUERY_HISTORY)
  kind?: string | null; // the object's type (TABLE, STREAMLIT, SCHEMA, WAREHOUSE, ...)
  app?: { can: Record<string, string>; opened: Record<string, { queries: number; last: string }>; never: string[]; saw: Record<string, string[]> } | null;
  warehouse?: { used: { user: string; queries: number; last: string }[]; unused: string[] };
  source?: string;
  name: string;
  user: string | null; // object page: only this user's use ("Access for")
  days?: number;
  work?: { start: number; end: number }; // business hours, local, Mon-Fri (WORK_HOURS); the tab shifts UTC to local
  available: boolean;
  admin?: boolean; // the person or role holds an admin role (rule 26 looks at its use)
  reason: string | null;
  note: string | null; // read, but partly (no client)
  first?: string;
  last?: string;
  daily?: number[]; // queries per day, oldest first
  by?: Record<ActivityKey, ActivityBy[]>;
  rows?: ActivityRow[]; // first MAX_ACTIVITY of total
  total?: number;
  ddl?: ActivityRow[];
  findings?: { num: string; title: string; severity: Severity; grantee: string; detail: string }[];
  graph?: Graph | null; // user / role used -> grant path it has now -> object
  gone?: { user: string; role: string; object: string; action: string }[]; // used, but that role has no grant path now
  sensitive?: ActivitySensitive[];
  mark?: { sql: string; tf: string; ticket: string; tag: string; value: string } | null; // tag text for an untagged table
  query_sql?: string; // copy-only SQL: every query behind the tab, one by one
  section_sql?: Record<string, string>; // the SQL behind each section (tiles, client, kinds, matrix, ...), copy-only
  objects?: Record<string, { kind: string; sensitive: boolean }>;
  refs?: Refs;
}
