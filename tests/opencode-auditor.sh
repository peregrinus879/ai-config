#!/usr/bin/env bash
# Exercise the real config hook plus OpenCode's ordered permission semantics.
# All runtime inputs are fixtures; no OpenCode process or host config is used.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT
mkdir -p "$TMP/home" "$TMP/data"
export HOME="$TMP/home" XDG_DATA_HOME="$TMP/data" TMPDIR="$TMP"
env -i PATH="$PATH" HOME="$HOME" XDG_DATA_HOME="$XDG_DATA_HOME" TMPDIR="$TMPDIR" node --input-type=module - "$ROOT" "$TMP" <<'JS'
import assert from "node:assert/strict"
import { readFile, writeFile } from "node:fs/promises"
import { join } from "node:path"
import { pathToFileURL } from "node:url"

const [repo, tmp] = process.argv.slice(2)
const source = await readFile(join(repo, "opencode/.config/opencode/plugins/auditor-permissions.js"), "utf8")
await writeFile(join(tmp, "auditor.mjs"), source)
const { AuditorPermissions } = await import(pathToFileURL(join(tmp, "auditor.mjs")))
const base = JSON.parse(await readFile(join(repo, "opencode/.config/opencode/opencode.json"), "utf8"))
const truncation = join(process.env.XDG_DATA_HOME, "opencode/tool-output/*")
const defaults = { "*": "allow", read: { "*": "allow", "*.env": "ask", "*.env.*": "ask", "*.env.example": "allow" }, external_directory: { "*": "ask", [truncation]: "allow" } }
const rank = { allow: 0, ask: 1, deny: 2 }
const max = (left, right) => rank[left] >= rank[right] ? left : right
let checks = 0

function match(subject, pattern) {
  let escaped = pattern.replaceAll("\\", "/").replace(/[.+^${}()|[\]\\]/g, "\\$&")
    .replaceAll("*", ".*").replaceAll("?", ".")
  if (escaped.endsWith(" .*")) escaped = escaped.slice(0, -3) + "( .*)?"
  return new RegExp("^" + escaped + "$", "s").test(subject.replaceAll("\\", "/"))
}
function rules(config) {
  const result = []
  for (const [permission, value] of Object.entries(typeof config === "string" ? { "*": config } : config)) {
    for (let [pattern, action] of Object.entries(typeof value === "string" ? { "*": value } : value)) {
      if (pattern === "~" || pattern.startsWith("~/")) pattern = process.env.HOME + pattern.slice(1)
      else if (pattern.startsWith("$HOME")) pattern = process.env.HOME + pattern.slice(5)
      result.push({ permission, pattern, action })
    }
  }
  return result
}
function evaluate(tool, subject, ...sets) {
  return sets.flat().findLast((rule) => match(tool, rule.permission) && match(subject, rule.pattern))?.action ?? "ask"
}
function native(parent, agent) {
  const result = [...rules(defaults), ...rules(parent), ...rules(agent)]
  // agent.ts appends this after ALL agent policy unless an exact deny exists.
  if (!result.some((r) => r.permission === "external_directory" && r.pattern === truncation && r.action === "deny")) {
    result.push({ permission: "external_directory", pattern: truncation, action: "allow" })
  }
  return result
}
function merge(target, patch) {
  for (const [key, value] of Object.entries(patch)) {
    if (value && typeof value === "object" && !Array.isArray(value) && target[key] && typeof target[key] === "object") merge(target[key], value)
    else target[key] = structuredClone(value)
  }
  return target
}
const normalize = (value) => typeof value === "string" ? { "*": value } : value
const subjects = {
  read: ["README.md", "private/notes.md", "private/.env", ".env", "nested/.aws/ordinary.md", "public/notes.md", "docs/notes.md", "mcp:fixture:resource"],
  glob: ["**/*.md", "private/**", "public/*.md", "docs/*.js", "other/*"],
  external_directory: [
    ...["Projects/*", "Projects/public/*", "Projects/private/*", "Projects/scratch/*", "Projects/scratch/session/*", "Projects/scratch-other/*", "Projects/scratch/.ssh/*", "Projects/scratch/copy/.aws/*", ".agents/skills/*", ".agents/skills/spar/scripts/*", ".ssh/*"].map((path) => join(process.env.HOME, path)),
    "/usr/*", "/etc/*", "/opt/*", "/sys/*", "/var/lib/pacman/*", "/tmp/*", "/tmp/fixture/*", "/var/tmp/*", "/tmp/opencode/*", "/tmp/opencode/session/*", "/tmp/claude-1000/*", "/outside/*", truncation, truncation.replace("/*", "/nested/*"),
  ],
}
const forbidden = ["edit", "write", "apply_patch", "bash", "grep", "list", "task", "skill", "webfetch", "websearch", "lsp", "vendor_mcp", "future_extension"]

async function check(parentPatch = {}, capPatch = {}, restricted = []) {
  const config = structuredClone(base)
  merge(config.permission, normalize(parentPatch))
  merge(config.agent.auditor.permission, normalize(capPatch))
  const before = structuredClone(config)
  const caps = Object.fromEntries(Object.entries(config.agent.auditor.permission).filter(([key]) => key !== "**"))
  const hooks = await AuditorPermissions()
  assert.deepEqual(Object.keys(hooks), ["config"], "no tool, event or auto-approval surface")
  const warnings = []
  const warn = console.warn
  console.warn = (message) => warnings.push(message)
  try { await hooks.config(config) } finally { console.warn = warn }
  const permission = config.agent.auditor.permission
  const actual = native(config.permission, permission)
  for (const [tool, paths] of Object.entries(subjects)) {
    for (const path of paths) {
      let expected = max(evaluate(tool, path, rules(defaults), rules(before.permission)), evaluate(tool, path, rules({ "*": "allow" }), rules(caps)))
      if (tool === "read" && path.startsWith("mcp:")) expected = "deny"
      const decision = evaluate(tool, path, actual)
      if (restricted.includes(tool)) {
        assert.equal(decision, "deny")
        assert.ok(rank[decision] >= rank[expected])
      } else assert.equal(decision, expected, JSON.stringify({ tool, path, expected, decision, parentPatch, capPatch }))
    }
  }
  for (const tool of forbidden) assert.equal(evaluate(tool, "*", actual), "deny", tool)
  for (const tool of restricted) assert.ok(warnings.some((message) => message.includes(`${tool} restricted to deny`)))
  if (!restricted.length) assert.deepEqual(warnings, [])
  const normalized = structuredClone(config)
  normalized.agent.auditor.permission = before.agent.auditor.permission
  assert.deepEqual(normalized, before, "the hook may change only the auditor permission map")
  const once = structuredClone(config)
  await hooks.config(config)
  assert.deepEqual(config, once, "repeat transform must not reinterpret generated rules as caps")
  checks++
  return config
}

// Missing plugin: the stock bootstrap, common tighter agent policies and
// inherited unknown extensions cannot expose a usable tool.
for (const cap of [{}, "ask", "deny", { read: "ask", glob: "ask", external_directory: "ask" }]) {
  const config = structuredClone(base)
  config.permission.future_extension = "allow"
  merge(config.agent.auditor.permission, normalize(cap))
  const missing = native(config.permission, config.agent.auditor.permission)
  for (const tool of ["read", "glob", ...forbidden]) assert.equal(evaluate(tool, "ordinary", missing), "deny")
  checks++
}
await check()
for (const action of ["ask", "deny"]) {
  for (const tool of ["read", "glob", "external_directory"]) {
    await check({ [tool]: action })
    await check({}, { [tool]: action })
    const pattern = tool === "external_directory" ? "~/Projects/private/**" : "private/**"
    await check({ [tool]: { [pattern]: action } })
    await check({}, { [tool]: { [pattern]: action } })
  }
  await check(action)
  await check({}, action)
  for (const toolPattern of ["*", "**", "r*", "g*", "external_*", "read *"]) await check({ [toolPattern]: action })
  for (const toolPattern of ["*", "r*", "g*", "external_*"]) await check({}, { [toolPattern]: action })
  await check({ "*": { "private/**": action } })
  await check({ read: { "private/**": action } }, { read: { "private/notes.md": "deny" } })
  await check({ external_directory: { [truncation]: action } })
  await check({ external_directory: { [truncation]: "allow", [truncation + "*"]: action } })
}
await check({ read: "deny", glob: "deny", external_directory: "deny" }, { read: "ask", glob: { "private/**": "ask" }, external_directory: "ask" })
await check({ read: "ask", external_directory: "ask" }, { read: "allow", external_directory: { "*": "allow" } })
await check({ read: { "*": "deny", "public/**": "allow" }, external_directory: { "*": "deny", "~/Projects/public/**": "allow" } })
await check({ read: { "private/**": "ask" } }, { read: "ask" })
await check({}, { read: { "*": "ask", "private/**": "deny" } })
await check({}, { glob: { "*": "deny", "public/**": "allow" } })
await check({ read: { "mcp:*": "allow" }, vendor_mcp: "allow", future_extension: "allow" }, { read: { "mcp:*": "allow" }, vendor_mcp: "allow", bash: "allow" })
// Intersections that cannot be represented without crossing ordered glob
// exceptions are conservatively denied, with safe, tool-specific diagnostics.
await check({}, { read: { "*": "deny", "public/**": "allow" } })
await check({ read: { "private/**": "ask" } }, { read: { "docs/**": "ask" } }, ["read"])
await check({ read: { "123": "allow" } }, {}, ["read"])
await check({ external_directory: { "~\\Projects\\*": "allow" } }, {}, ["external_directory"])
await check({}, { read: { "private/**": "deny", "private/notes.md": "ask" } })
await check({}, { external_directory: { "*": "deny", "~/Projects/public/**": "allow" } }, ["external_directory"])

// A bounded overlap matrix checks non-loosening even for conservative cases.
const policies = [
  "allow", "ask", "deny",
  { "*": "allow", "private/**": "deny", "private/public/**": "ask" },
  { "*": "ask", "public/**": "allow", "public/private/**": "deny" },
  { "*": "deny", "public/**": "allow" },
  { "*": "allow", "private/**": "ask", "private/private/**": "deny" },
]
for (const parent of policies) for (const cap of policies) {
  const config = structuredClone(base)
  config.permission.read = parent
  config.agent.auditor.permission.read = cap
  const before = structuredClone(config)
  const warn = console.warn
  console.warn = () => {}
  try { await (await AuditorPermissions()).config(config) } finally { console.warn = warn }
  const actual = native(config.permission, config.agent.auditor.permission)
  for (const path of ["README", "private/.env", "private/private/a", "private/public/a", "public/a", "public/private/a"]) {
    const expected = max(evaluate("read", path, rules(defaults), rules(before.permission)), evaluate("read", path, rules({ read: cap })))
    assert.ok(rank[evaluate("read", path, actual)] >= rank[expected], JSON.stringify({ parent, cap, path }))
  }
  checks++
}

// Failure after entry must remove even project-added extension grants; the
// native loader catches config-hook failures, so partial grants cannot remain.
const failure = structuredClone(base)
failure.agent.auditor.permission.future_extension = "allow"
Object.defineProperty(failure, "permission", { get: () => { throw new Error("fixture failure") } })
const failureWarnings = []
const warn = console.warn
console.warn = (message) => failureWarnings.push(message)
try { await (await AuditorPermissions()).config(failure) } finally { console.warn = warn }
for (const tool of ["read", "glob", ...forbidden]) assert.equal(evaluate(tool, "ordinary", rules(failure.agent.auditor.permission)), "deny")
assert.equal(failureWarnings.length, 3)
checks++
const invalid = structuredClone(base)
invalid.agent.auditor.permission["**"] = "ask"
await assert.rejects((await AuditorPermissions()).config(invalid), /auditor remains denied/)
assert.deepEqual(invalid.agent.auditor.permission, { "**": "deny" })
checks++
const disabled = structuredClone(base)
disabled.agent.auditor.disable = true
const snapshot = structuredClone(disabled)
await (await AuditorPermissions()).config(disabled)
assert.deepEqual(disabled, snapshot)
checks++
console.log(`ok: OpenCode auditor inheritance (${checks} hermetic policy scenarios; no live tool calls)`)
JS
