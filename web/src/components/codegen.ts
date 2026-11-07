// Text to apply a change elsewhere: SQL, Terraform (Snowflake provider) or ticket text. Pure functions; the app never runs them.

export interface Change {
  op: "grant" | "revoke";
  role?: string; // a role granted or revoked ...
  to: string; // ... to / from this user or role (for a privilege: the role holding it)
  toUser?: boolean;
  privilege?: string; // a privilege instead of a role
  objectType?: string; // TABLE, VIEW, SCHEMA, WAREHOUSE, ...
  object?: string;
}

export interface Note { reason?: string; approver?: string; expiry?: string; by?: string }

const q = (s: string) => (/^[A-Z_][A-Z0-9_$]*(\.[A-Z_][A-Z0-9_$]*)*$/.test(s) ? s : s.split(".").map((p) => `"${p.replace(/"/g, '""')}"`).join("."));
const isDbRole = (r: string) => r.includes(".");
const comments = (n: Note, mark: string) =>
  [n.reason && `Reason: ${n.reason}`, n.approver && `Approver: ${n.approver}`, n.expiry && `Expires: ${n.expiry}`, n.by && `Requested by: ${n.by}`]
    .filter(Boolean).map((l) => `${mark} ${l}`);

export function sqlOf(cs: Change[], n: Note = {}): string {
  const lines = comments(n, "--");
  for (const c of cs) {
    const from = c.op === "grant" ? "TO" : "FROM";
    const target = c.toUser ? `USER ${q(c.to)}` : isDbRole(c.to) ? `DATABASE ROLE ${q(c.to)}` : `ROLE ${q(c.to)}`;
    if (c.privilege && c.object) {
      const on = c.objectType === "ACCOUNT" ? "ACCOUNT" : `${(c.objectType ?? "TABLE").replace(/^FUTURE (.*)$/, "FUTURE $1S IN SCHEMA")} ${q(c.object)}`;
      lines.push(`${c.op.toUpperCase()} ${c.privilege} ON ${on} ${from} ${target};`);
    } else if (c.role) {
      lines.push(`${c.op.toUpperCase()} ${isDbRole(c.role) ? "DATABASE ROLE" : "ROLE"} ${q(c.role)} ${from} ${target};`);
    }
    if (c.op === "grant" && c.role) lines.push(`-- undo: REVOKE ${isDbRole(c.role) ? "DATABASE ROLE" : "ROLE"} ${q(c.role)} FROM ${target};`);
  }
  return lines.join("\n") + "\n";
}

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");

export function terraformOf(cs: Change[], n: Note = {}): string {
  const out = comments(n, "#");
  for (const c of cs) {
    if (c.op === "revoke") {
      const what = c.role ?? `${c.privilege} on ${c.object}`;
      out.push(`# Revoke ${what} from ${c.to}: delete the resource that grants it (search the repo for "${c.role ?? c.object}"), then plan and apply.`);
      continue;
    }
    if (c.role && isDbRole(c.role)) {
      out.push(`resource "snowflake_grant_database_role" "${slug(`${c.role}_to_${c.to}`)}" {`,
        `  database_role_name = "${c.role}"`, c.toUser ? `  # database roles cannot be granted to users: grant to an account role`
          : isDbRole(c.to) ? `  parent_database_role_name = "${c.to}"` : `  parent_role_name   = "${c.to}"`, "}");
    } else if (c.role) {
      out.push(`resource "snowflake_grant_account_role" "${slug(`${c.role}_to_${c.to}`)}" {`,
        `  role_name        = "${c.role}"`, c.toUser ? `  user_name        = "${c.to}"` : `  parent_role_name = "${c.to}"`, "}");
    } else if (c.privilege && c.object) {
      const t = c.objectType ?? "TABLE";
      const body = t === "ACCOUNT" ? ["  on_account = true"]
        : t === "DATABASE" ? [`  on_database = "${c.object}"`]
        : t === "SCHEMA" ? ["  on_schema {", `    schema_name = "${c.object}"`, "  }"]
        : t.startsWith("FUTURE ") ? ["  on_schema_object {", "    future {", `      object_type_plural = "${t.slice(7)}S"`, `      in_schema          = "${c.object.replace(/\.<[^>]*>$/, "")}"`, "    }", "  }"]
        : ["  on_schema_object {", `    object_type = "${t}"`, `    object_name = "${c.object}"`, "  }"];
      out.push(`resource "snowflake_grant_privileges_to_account_role" "${slug(`${c.privilege}_${c.object}_${c.to}`)}" {`,
        `  account_role_name = "${c.to}"`, `  privileges        = ["${c.privilege}"]`, ...body, "}");
    }
    out.push("");
  }
  return out.join("\n").trimEnd() + "\n";
}

export function ticketOf(cs: Change[], n: Note = {}): string {
  const say = (c: Change) => {
    const what = c.role ? `role ${c.role}` : `${c.privilege} on ${c.objectType?.toLowerCase() ?? "object"} ${c.object}`;
    const who = `${c.toUser ? "user" : "role"} ${c.to}`;
    return c.op === "grant" ? `Grant ${what} to ${who}` : `Revoke ${what} from ${who}`;
  };
  return [
    `Access change (${cs.length} item${cs.length === 1 ? "" : "s"})`,
    "",
    ...cs.map((c, i) => `${i + 1}. ${say(c)}`),
    "",
    `Reason: ${n.reason || "(fill in)"}`,
    `Approver: ${n.approver || "(owner of the object)"}`,
    ...(n.expiry ? [`Expires: ${n.expiry}`] : []),
    "Apply through infrastructure as code; manual grants are removed by reconciliation.",
  ].join("\n") + "\n";
}

/** Expiry date (YYYY-MM-DD) days after now; 0 or less: none ("until revoked"). */
export function expiryOf(days: number, now = new Date()): string {
  if (days <= 0) return "";
  const d = new Date(now.getTime() + days * 86400000);
  return d.toISOString().slice(0, 10);
}

/** No existing role fits: a commented skeleton for a new role (every line a comment, so nothing runs by accident).
 * dbRole: the new account role holds this database role (a database role can't be granted to a user).
 * toRole: user is a role, so the new role is granted to that role.
 * inDb: user is a database role: { db: its database, objDb: the object's database }. Only a database role of the same
 * database can be granted to it, and a database role holds privileges only on objects in its own database. */
export function newRoleOf(user: string, privs: string[], objectType: string, object: string, n: Note = {}, dbRole?: string,
  toRole = false, inDb?: { db: string; objDb: string }): { sql: string; tf: string; ticket: string } {
  const r = "<NEW_ROLE>";
  const head = (m: string) => [`${m} No existing role gives ${user} ${privs.join(", ")} on ${object}. The owner decides; a skeleton:`, ...comments(n, m)];
  if (inDb) return newDbRoleOf(user, privs, objectType, object, n, inDb, head);
  const give = dbRole ? `-- GRANT DATABASE ROLE ${q(dbRole)} TO ROLE ${r};` : `-- GRANT ${privs.join(", ")} ON ${objectType} ${q(object)} TO ROLE ${r};`;
  const sql = [...head("--"), `-- CREATE ROLE ${r};`, give, `-- GRANT ROLE ${r} TO ${toRole ? "ROLE" : "USER"} ${q(user)};`].join("\n") + "\n";
  const tfGive = dbRole
    ? [`# resource "snowflake_grant_database_role" "${slug(dbRole)}_to_new_role" {`, `#   database_role_name = "${dbRole}"`, `#   parent_role_name   = "${r}"`, "# }"]
    : [`# resource "snowflake_grant_privileges_to_account_role" "new_role_${slug(object)}" {`, `#   account_role_name = "${r}"`,
      `#   privileges        = [${privs.map((p) => `"${p}"`).join(", ")}]`, "#   on_schema_object {", `#     object_type = "${objectType}"`,
      `#     object_name = "${object}"`, "#   }", "# }"];
  const tf = [...head("#"), `# resource "snowflake_account_role" "new_role" {`, `#   name = "${r}"`, "# }", ...tfGive,
    `# resource "snowflake_grant_account_role" "new_role_to_${slug(user)}" {`, `#   role_name = "${r}"`, toRole ? `#   parent_role_name = "${user}"` : `#   user_name = "${user}"`, "# }"].join("\n") + "\n";
  const ticket = [`Access request · ${user}`, `Object: ${object}`, `Need: ${privs.join(", ")}`,
    dbRole ? `Role: a new account role holding ${dbRole}` : "Role: none fits, owner to decide (new role)",
    ...(n.expiry ? [`Expires: ${n.expiry}`] : []), `Approver: ${n.approver || "(owner of the object)"}`, `Reason: ${n.reason || "(fill in)"}`].join("\n") + "\n";
  return { sql, tf, ticket };
}

/** newRoleOf for a database role subject: a new database role in its database, or why it can't be done. */
function newDbRoleOf(user: string, privs: string[], objectType: string, object: string, n: Note,
  { db, objDb }: { db: string; objDb: string }, head: (m: string) => string[]): { sql: string; tf: string; ticket: string } {
  const r = `${db}.<NEW_ROLE>`;
  const tail = (m: string) => [...(n.expiry ? [`Expires: ${n.expiry}`] : []), `Approver: ${n.approver || "(owner of the object)"}`, `Reason: ${n.reason || "(fill in)"}`].map((l) => m ? `${m} ${l}` : l);
  if (objDb !== db) {
    const why = `${user} is a database role of ${db}: it can only hold privileges on objects in ${db}, and ${object} is not in it. Ask for an account role that holds ${user} instead.`;
    return { sql: [`-- ${why}`, ...comments(n, "--")].join("\n") + "\n", tf: [`# ${why}`, ...comments(n, "#")].join("\n") + "\n",
      ticket: [`Access request · ${user}`, `Object: ${object}`, `Need: ${privs.join(", ")}`, `Not possible this way: ${why}`, ...tail("")].join("\n") + "\n" };
  }
  const sql = [...head("--"), `-- CREATE DATABASE ROLE ${r};`, `-- GRANT ${privs.join(", ")} ON ${objectType} ${q(object)} TO DATABASE ROLE ${r};`,
    `-- GRANT DATABASE ROLE ${r} TO DATABASE ROLE ${q(user)};`].join("\n") + "\n";
  const tf = [...head("#"), `# resource "snowflake_database_role" "new_role" {`, `#   database = "${db}"`, `#   name     = "<NEW_ROLE>"`, "# }",
    `# resource "snowflake_grant_privileges_to_database_role" "new_role_${slug(object)}" {`, `#   database_role_name = "${r}"`,
    `#   privileges         = [${privs.map((p) => `"${p}"`).join(", ")}]`, "#   on_schema_object {", `#     object_type = "${objectType}"`,
    `#     object_name = "${object}"`, "#   }", "# }",
    `# resource "snowflake_grant_database_role" "new_role_to_${slug(user)}" {`, `#   database_role_name        = "${r}"`,
    `#   parent_database_role_name = "${user}"`, "# }"].join("\n") + "\n";
  const ticket = [`Access request · ${user}`, `Object: ${object}`, `Need: ${privs.join(", ")}`,
    `Role: a new database role in ${db}, granted to ${user}`, ...tail("")].join("\n") + "\n";
  return { sql, tf, ticket };
}
