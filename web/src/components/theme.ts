// Tokens copied from ui.py TOKENS (keep both in step). "database" there is "database_role" here.
import type { CSSProperties } from "react";

export type ThemeName = "light" | "dark";
export interface KindStyle { bg: string; border: string; text: string; radius: string; dash: string }

const KINDS = ["user", "functional", "technical", "group", "database_role", "admin", "object"] as const;
const SHAPE: Record<string, [string, string]> = {
  user: ["999px", "solid"], functional: ["6px", "solid"], technical: ["6px", "solid"], group: ["6px", "dashed"],
  database_role: ["6px", "dashed"], admin: ["6px", "solid"], object: ["12px / 9px", "solid"],
};

const kinds = (rows: [string, string, string][]) =>
  Object.fromEntries(KINDS.map((k, i) => {
    const [bg, border, text] = rows[i];
    return [k, { bg, border, text, radius: SHAPE[k][0], dash: SHAPE[k][1] }];
  })) as Record<string, KindStyle>;

export const TOKENS = {
  light: {
    bg: "#F7F4EE", side: "#EEE7DB", panel: "#FFFDF8", sunk: "#F2ECE2", line: "#E2D8C8",
    ink: "#1F1A14", muted: "#675E53", accent: "#975A16", edge: "#A89B89",
    warn_bg: "#F7EFCF", warn_ink: "#634B0E", warn_bd: "#E6D58A",
    bad_bg: "#F9E2DE", bad_ink: "#8C271D", bad_bd: "#EDB9B1",
    ok_bg: "#E3EFE4", ok_ink: "#2B5A33", ok_bd: "#B9D6BD",
    low_bg: "#ECE8E1", low_ink: "#5B544B", low_bd: "#D3CBBF",
    e_read: "#2F5D9E", e_write: "#B8650A", e_own: "#8A3B1E", e_use: "#2E7A4C", e_manage: "#6A4C9C",
    kind: kinds([["#FFFFFF", "#2A241D", "#1F1A14"], ["#DFE9F6", "#30476B", "#1D2C44"],
      ["#EEDDC8", "#8C5D34", "#4A2E14"], ["#FAEBCB", "#B07A1E", "#553806"],
      ["#E6EBF2", "#56677F", "#24303F"], ["#F9DCD6", "#B4362A", "#8C271D"], ["#ECE6DB", "#5E554A", "#2A241D"]]),
  },
  dark: {
    bg: "#14110D", side: "#1A1612", panel: "#1F1A15", sunk: "#28221B", line: "#3A3128",
    ink: "#F2ECE2", muted: "#ADA294", accent: "#E6A95C", edge: "#75685A",
    warn_bg: "#2C2610", warn_ink: "#EBD27E", warn_bd: "#4E4418",
    bad_bg: "#371A17", bad_ink: "#F4BDB4", bad_bd: "#5E2A24",
    ok_bg: "#18301D", ok_ink: "#A6D9AE", ok_bd: "#2D5235",
    low_bg: "#2A251F", low_ink: "#BDB3A6", low_bd: "#463D33",
    e_read: "#82AAE3", e_write: "#EBA84E", e_own: "#E58F6E", e_use: "#7DC896", e_manage: "#B9A0E6",
    kind: kinds([["#1F1A15", "#E9E1D4", "#F2ECE2"], ["#1C2A3F", "#7EA3D6", "#D5E3F6"],
      ["#35271A", "#C5926A", "#F1DCC5"], ["#352913", "#D7A443", "#F3DDAE"],
      ["#1D232C", "#93A6C0", "#DCE4EE"], ["#3A1B18", "#E27A6B", "#F6C3BA"], ["#2A251F", "#A39684", "#EDE5D8"]]),
  },
};
export type Tokens = typeof TOKENS.light;

/** Style of a node kind; combined boxes borrow the style of what they hold. */
export function kindStyle(t: Tokens, kind: string): KindStyle {
  const base = { schema_group: "object", database_group: "object", type_group: "object", fold: "technical", lane_group: "technical" }[kind];
  return t.kind[base ?? kind] ?? t.kind.group;
}

// edge class -> colour token, width, dash, double line (as ui.EDGE; inherit_db and back added)
export const EDGE: Record<string, [keyof Tokens | "db", number, string, boolean]> = {
  inherit: ["edge", 1.5, "", false], back: ["edge", 1.5, "2 3", false], inherit_db: ["db", 1.6, "2 3", true],
  read: ["e_read", 1.8, "", false], write: ["e_write", 3, "", false], own: ["e_own", 4.5, "", true],
  use: ["e_use", 1.8, "5 4", false], manage: ["e_manage", 2.2, "8 3 2 3", false], admin: ["bad_ink", 2, "1 3", false],
};

export function edgeColor(t: Tokens, cls: string): string {
  const key = (EDGE[cls] ?? EDGE.inherit)[0];
  return key === "db" ? t.kind.database_role.border : (t[key] as string);
}

/** CSS variables (--ae-*) for a wrapper element; the shared CSS reads only these. */
export function themeVars(name: ThemeName): CSSProperties {
  const t = TOKENS[name];
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(t)) if (typeof v === "string") out[`--ae-${k}`] = v;
  for (const [k, s] of Object.entries(t.kind)) {
    out[`--ae-k-${k}-bg`] = s.bg;
    out[`--ae-k-${k}-bd`] = s.border;
    out[`--ae-k-${k}-ink`] = s.text;
  }
  return out as CSSProperties;
}

export const PCLASS: Record<string, string> = {
  read: "Read", write: "Write", own: "Own", use: "Use", manage: "Manage", admin: "Account",
  inherit: "Inherits", inherit_db: "Database role", back: "Also deeper",
};
export const KIND_LABEL: Record<string, string> = {
  user: "User", functional: "Functional", technical: "Technical", group: "Group / other", database_role: "Database role",
  admin: "Admin / account", object: "Object", schema_group: "Schema (combined)", database_group: "Database (combined)",
  type_group: "Object type (combined)", fold: "Folded roles", lane_group: "Roles (combined)",
};
