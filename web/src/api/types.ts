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
  legend: { kinds: NodeKind[]; edges: EdgeCls[]; marks: Mark[]; rules: boolean; back?: boolean }; // back: a dotted "also deeper" line is drawn
}

// ---------- frame ----------

export interface RunInfo {
  run_id: string;
  finished_at: string;
  when: string;
  old: boolean;
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

export interface RuleInfo {
  num: string;
  title: string;
  why: string;
  severity: Severity;
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
  view: View;
  loaded: boolean;
  run: RunInfo | null;
  sources: Record<string, string>;
  notes: Note[];
  mine: MineState;
  mine_available: boolean; // false inside Snowflake (owner's rights)
  cache_hours: number; // hours a copy stays in .cache/ (0: memory only, as inside Snowflake)
  inside?: boolean; // Streamlit in Snowflake: reads run with the app owner's role
  /** DuckDB copy of the data shown (cache.sql_info): file + schema, or why there is none */
  sql_copy?: { on: boolean; path: string; schema: string | null; note: string | null; written_at: string | null };
  error?: { detail: string; message: string }; // shared_not_loaded: SOURCE=direct reads only on a click
  pages: { key: Page; label: string; badge: number | null; severity?: Severity | null; group: "answers" | "admin" | "detail" }[]; // rules: count of the worst severity
  default_user: string;
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
    objects: string[];
    privileges: string[];
  };
  banners: Banner[];
  findings: Finding[];
  findings_total: number;
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
  privileges: PrivRow[];
  roles: ReachRow[];
  multi: { rows: { privilege: string; cls: PrivClass; object: string; depth: number; path: Path }[]; total: number; shown: number };
  can_read: DataView[] | null;
  sensitive: { known: boolean; roles: string[]; rows: SensitiveReach[] } | null;
  granted: { role: string; kind: NodeKind; default: boolean; used: { queries: number; last_used: string } | null; used_text: string }[];
  usage: UsageCard;
  capped: string[];
  refs: Refs;
}

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
    cuts: string[];
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
  findings: Finding[];
  findings_total: number;
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
    rows: HeldRow[];
    revoke: { grantee: string; lost: number; users: number; iac: string; sql: string } | null;
  };
  holds: {
    types: {
      type: string;
      privs: string[];
      rows: { object: string; name: string; cells: Record<string, HoldCell>; text: string }[];
    }[];
    other: { privilege: string; cls: PrivClass; type: string; object: string; name: string }[];
    count: number;
    objects: number;
  };
  tabs: Tab[];
  privileges: PrivRow[];
  roles: ReachRow[];
  can_read: DataView[] | null;
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
  admin_paths: Path[];
  sensitivity: Sensitivity | null;
  matrix: { privs: string[]; sensitive_cols: string[]; row_policy: boolean; rows: MatrixRow[] };
  graph: Graph | null;
  sees: {
    cols: string[];
    row_policy: boolean;
    rows: { role: string; rows: StateWhy<RowsState>; columns: (StateWhy<ColState> & { column: string })[] }[];
  } | null;
  tabs: Tab[];
  grantees: GranteeRow[];
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
  nearest: Nearest[];
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
  owner: Path[];
  choke: string[];
  closest: Path | null;
  ask: { role: string; privileges: number; path: Path }[];
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
  object: string;
  type: string;
  database: string; // the object's database ("" for an account-level object)
  need: "read" | "change";
  privileges: string[];
  level: string | null; // the user's step on the object today
  has: boolean;
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
    stale: string[];
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
    people: string[];
    disabled: string[];
    service: string[];
    admin: string[];
    roles: string[];
  }[];
  readers: {
    user: string;
    type: string;
    status: UserStatus;
    last_login_text: string;
    objects: string[];
    roles: string[];
    path: Path | null;
    via_admin: boolean;
    admin_paths: Path[];
  }[];
  compare: { a: string; b: string; roles: string[]; rows: { object: string; a: string | null; b: string | null }[]; diff: string[] };
  catalog: CatalogRow[]; // screen 8, most exposed first
  refs: Refs;
}

export interface AdminPerson {
  user: string;
  service: boolean;
  roles: string[];
  account: string[];
  paths: Path[];
  status: UserStatus;
  last_login: string | null;
}

export interface RulesPage {
  view: View;
  scope: "account" | "mine";
  filters: { grantee: string; sev: Severity | "Passing" | ""; rule: string };
  counts: Record<Severity | "Passing", number>;
  per_rule: Record<string, number>;
  findings: Finding[];
  total: number;
  rows_unknown: string[];
  admins: AdminPerson[];
  refs: Refs;
}

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
  hidden: boolean;
}

export interface ReviewPage {
  view: "shared";
  filters: {
    db: string;
    dbs: string[];
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
  };
  rows: ReviewRow[];
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
  lost_rows: WhatIfObjectRow[]; // first max_paths objects
  kept_rows: WhatIfObjectRow[];
  kept_roles: { role: string; path: Path; via: Path; through: string }[];
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
  users: WhatIfUser[];
  objects: { object: string; type: string; sensitive: boolean; unreached: boolean; ownerless: boolean }[];
  roles: { role: string; kind: string; orphan: boolean; unreached: boolean }[];
  findings: WhatIfFinding[];
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
  holders: string[];
  sensitive: boolean;
  columns: { column: string; state: ColState; reason: string }[];
  findings: RowFinding[];
  label: string | null; // "Future tables · SALES.CORE"
}

export interface LadderCounts { read: number; change: number; own: number; admin: number; usage: number; runnable: number; account: number; sensitive?: number; schemas?: number }

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
  objects: AccessObject[];
  heat: { schema: string; read: number; change: number; own: number; sensitive: number }[];
  why: { role: string; kind: NodeKind; note: string; kids: string[] }[];
  findings: Finding[];
  findings_total: number;
  deepest: number;
  roles: number;
  refs: Refs;
}

export interface HomePage {
  view: View;
  me: { user: string; counts: LadderCounts } | null;
  risks: Record<Severity, number> | null;
  counts: { users: number; roles: number; objects: number; sensitive: number };
  per_rule: Record<string, number> | null; // findings per rule (shared only): Home's findings by area
  protection: { unmasked: number; unmasked_names: string[]; dormant: number; dormant_names: string[]; tagged: number;
    masked: number; row_tables: number; row_list: { object: string; policies: string[] }[] } | null;
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
  people: WhoPerson[];
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
  cards: SeeCard[];
  counts: { objects: number; sensitive: number; columns: number; clear: number; masked: number; unknown: number;
    unprotected: number; rows: number } | null;
  can_read: DataView[] | null;
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
  dbs: string[];
  sensitive: boolean;
  rows: CompareRow[];
  counts: Record<Diff, number>;
  match: CompareChange[]; // make B match A
  extras: CompareChange[]; // remove A's extras
  old: { rows: { object: string; a: string | null; b: string | null }[]; diff: string[] } | null; // Compare two roles
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
  readers: number;
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
}
export interface GridPage {
  view: View;
  scope: "sensitive" | "db" | "all" | "object";
  db: string;
  dbs: string[];
  object: string;
  columns: { id: string; name: string; ns: string; note: string; sensitive: boolean }[];
  rows: GridRow[];
  total: number;
  cap: number;
  sensitive: number;
  counts: { people: number; admin: number; stale: number; service: number };
  refs: Refs;
}

/** Screen 16 (/api/flow). */
export interface FlowNode { id: string; label: string; users: string[]; kind?: string; ns?: string; status?: string; unmasked?: string[]; masked?: string[]; row_policies?: string[] }
export interface FlowLink { source: string; target: string; users: string[] }
export interface FlowPage {
  view: View;
  state: "ok" | "mine" | "none";
  groups: FlowNode[];
  roles: FlowNode[];
  objects: FlowNode[];
  links: FlowLink[];
  select: string | null;
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
  people: string[]; // who used it (a role: its people)
  holder: string;
  suggest: "keep" | "trim" | "drop";
  text: string;
  changes: WhatIfChange[]; // revokes of the unused privileges where they are granted
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
  rows: UsageRow[];
  weeks: string[]; // Monday of each week
  counts: { objects: number; used: number; drop: number; trim: number; keep: number; write_unused: number; changes: number } | null;
  changes: WhatIfChange[];
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
  events: ChangeEvent[];
  counts: ChangeCounts | null;
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
  hours: number[]; weekend: number; weekend_hours: number[]; // weekday queries per UTC hour (24); weekend total and per hour
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
  objects?: Record<string, { kind: string; sensitive: boolean }>;
  refs?: Refs;
}
