#!/usr/bin/env bash
# Hermetic plugin fixtures only. No OpenCode process, host config or model call.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT
mkdir -p "$TMP/home" "$TMP/opencode" "$TMP/repo/subdir" "$TMP/outside"
export HOME="$TMP/home" TMPDIR="$TMP"
unset NODE_OPTIONS NODE_COMPILE_CACHE
node --input-type=module - "$ROOT" "$TMP" <<'JS'
import assert from "node:assert/strict"
import * as fs from "node:fs/promises"
import { execFileSync } from "node:child_process"
import { dirname, isAbsolute, join, relative, resolve } from "node:path"
import { pathToFileURL } from "node:url"

const [repo, tmp] = process.argv.slice(2)
const root = join(tmp, "opencode")
const worktree = join(tmp, "repo")
const directory = join(worktree, "subdir")
const source = await fs.readFile(join(repo, "opencode/.config/opencode/plugins/scratch-permissions.js"), "utf8")
const base = JSON.parse(await fs.readFile(join(repo, "opencode/.config/opencode/opencode.json"), "utf8"))
const anchor = 'const SCRATCH_ROOT = "/tmp/opencode"'
assert.equal(source.split(anchor).length, 2)
// Only disposable copies admit a fixture root. The production copy must not
// accept TMPDIR (or plugin options) as an alternate authority root.
// Relocate its location grant too; do not rely on a broad /tmp allow or the
// caller's own /tmp/opencode parent to authorize every simulated outside path.
base.permission.external_directory = Object.fromEntries(Object.entries(base.permission.external_directory)
  .map(([pattern, action]) => [pattern === "/tmp/opencode/*" ? root + "/*" : pattern, action]))
await fs.writeFile(join(tmp, "production.mjs"), source)
await fs.writeFile(join(tmp, "fixture.mjs"), source.replace(anchor, `const SCRATCH_ROOT = ${JSON.stringify(root)}`))
const { ScratchPermissions } = await import(pathToFileURL(join(tmp, "fixture.mjs")))
const production = await import(pathToFileURL(join(tmp, "production.mjs")))
const unchanged = structuredClone(base)
await (await production.ScratchPermissions({ directory, worktree, root })).config(unchanged)
assert.deepEqual(unchanged, base)

let checks = 1
const contains = (parent, target) => parent === target || target.startsWith(parent + "/")
function matches(subject, pattern) {
  pattern = pattern.replace(/^~(?=\/|$)/, process.env.HOME).replace(/^\$HOME/, process.env.HOME)
  let escaped = pattern.replaceAll("\\", "/").replace(/[.+^${}()|[\]\\]/g, "\\$&")
    .replaceAll("*", ".*").replaceAll("?", ".")
  if (escaped.endsWith(" .*")) escaped = escaped.slice(0, -3) + "( .*)?"
  return new RegExp("^" + escaped + "$", "s").test(subject.replaceAll("\\", "/"))
}
function evaluate(tool, subject, ...configs) {
  let decision = "ask"
  for (const config of configs) {
    for (const [permission, value] of Object.entries(config)) {
      if (!matches(tool, permission)) continue
      for (const [pattern, action] of Object.entries(typeof value === "string" ? { "*": value } : value)) {
        if (matches(subject, pattern)) decision = action
      }
    }
  }
  return decision
}
async function setup(config = structuredClone(base), wt = worktree, cwd = directory) {
  const original = structuredClone(config)
  const hooks = await ScratchPermissions({ directory: cwd, worktree: wt })
  assert.deepEqual(Object.keys(hooks).sort(), ["config", "tool.execute.before"])
  await hooks.config(config)
  assert.deepEqual(config.agent, original.agent)
  assert.deepEqual(Object.keys(config.permission), Object.keys(original.permission))
  for (const key of Object.keys(original.permission).filter((key) => key !== "edit")) {
    assert.deepEqual(config.permission[key], original.permission[key])
  }
  if (typeof original.permission.edit === "object") {
    assert.deepEqual(Object.entries(config.permission.edit).filter(([key]) => Object.hasOwn(original.permission.edit, key)), Object.entries(original.permission.edit))
  }
  const once = structuredClone(config)
  await hooks.config(config)
  assert.deepEqual(config, once)
  return { config, hooks, wt, cwd }
}

// The simulated dispatcher deliberately starts native work only after the
// hook returns. Supplied native target lists are independent of its scanner.
async function probe(state, tool, args, nativeTargets, expected, extra = {}) {
  for (const { path } of nativeTargets) {
    assert.ok(isAbsolute(path) && contains(tmp, resolve(path)), "fixture native target escaped its private scratch")
  }
  let native = 0
  let reads = 0
  let writes = 0
  let decision = "allow"
  const beforeArgs = structuredClone(args)
  try {
    await state.hooks["tool.execute.before"]({ tool, sessionID: "fixture", callID: "fixture" }, { args })
  } catch (error) {
    assert.match(error.message, /scratch-permissions/)
    decision = "refused"
  }
  if (decision !== "refused") {
    native++
    for (const { path } of nativeTargets) {
      const external = !contains(state.cwd, path) && !(state.wt !== "/" && contains(state.wt, path))
      const subjects = [["edit", relative(state.wt, path)]]
      if (external) subjects.unshift(["external_directory", dirname(path) + "/*"])
      for (const [permission, subject] of subjects) {
        const action = evaluate(permission, subject, state.config.permission, extra)
        if (action !== "allow") decision = action
      }
    }
    if (decision === "allow") {
      for (const target of nativeTargets) {
        if (target.operation !== "add") {
          reads++
          await fs.readFile(target.path)
        }
        writes++
        if (target.operation === "delete") await fs.unlink(target.path)
        else {
          await fs.mkdir(dirname(target.path), { recursive: true })
          await fs.writeFile(target.path, "native fixture result\n")
        }
      }
    }
  }
  assert.deepEqual(args, beforeArgs, "hook must not rewrite permission subjects")
  assert.equal(decision, expected, JSON.stringify({ tool, args, expected, decision }))
  if (expected === "refused") assert.deepEqual([native, reads, writes], [0, 0, 0])
  if (expected === "ask" || expected === "deny") assert.equal(writes, 0)
  checks++
}
const add = (path) => ({ path, operation: "add" })
const edit = (path) => ({ path, operation: "update" })
const patch = (...headers) => "*** Begin Patch\n" + headers.join("\n") + "\n*** End Patch"
const state = await setup()
const atInstall = structuredClone(base)
const installingHooks = await ScratchPermissions({ directory, worktree })
let installedEdit = atInstall.permission.edit
let installationCheck
Object.defineProperty(atInstall.permission, "edit", {
  enumerable: true,
  get: () => installedEdit,
  set: (value) => {
    installedEdit = value
    installationCheck = installingHooks["tool.execute.before"]({ tool: "write" }, { args: { filePath: join(root, ".env"), content: "synthetic" } })
  },
})
await installingHooks.config(atInstall)
await assert.rejects(installationCheck, /scratch-permissions/, "guard must be ready at the instant the allowance is installed")
checks++
const frozen = structuredClone(base)
Object.freeze(frozen.permission)
const frozenHooks = await ScratchPermissions({ directory, worktree })
await assert.rejects(frozenHooks.config(frozen), TypeError)
assert.deepEqual(frozen, base, "failed config mutation must not leave an allowance")
checks++
const normal = join(root, "session/note.md")
await probe(state, "write", { filePath: normal, content: "fixture" }, [add(normal)], "allow")
await probe(state, "edit", { filePath: normal, oldString: "fixture", newString: "next" }, [edit(normal)], "allow")
await probe(state, "write", { filePath: relative(directory, normal), content: "fixture" }, [edit(normal)], "allow")
assert.equal(await fs.readFile(normal, "utf8"), "native fixture result\n")
const mixed = join(worktree, "ordinary.md")
const nested = join(root, "session/new/parents/result.md")
await probe(state, "apply_patch", { patchText: patch(`*** Add File: ${mixed}`, "+workspace", `*** Add File: ${nested}`, "+scratch") }, [add(mixed), add(nested)], "allow")
await probe(state, "apply_patch", { patchText: patch(`*** Update File: ${normal}`, "@@", "-old", "+new", `*** Delete File: ${nested}`) }, [edit(normal), { path: nested, operation: "delete" }], "allow")
await probe(state, "apply_patch", { patchText: "cat <<'EOF'\n" + patch(`*** Add File: ${nested}`, "+*** Move to: this is content, not a header").replaceAll("\n", "\r\n") + "\nEOF" }, [add(nested)], "allow")
for (const path of [join(tmp, "sibling/tmp/opencode/note.md"), root + "X/note.md", join(tmp, "outside/note.md")]) {
  await probe(state, "write", { filePath: path, content: "fixture" }, [add(path)], "ask")
}
for (const [name, expected] of [["scratch", "allow"], ["scratch-other", "ask"]]) {
  const path = join(process.env.HOME, "Projects", name, "note.md")
  assert.equal(evaluate("external_directory", dirname(path) + "/*", state.config.permission), expected)
  await probe(state, "write", { filePath: path, content: "fixture" }, [add(path)], "ask")
}

// Rules already merged from projects remain later and authoritative.
for (const wanted of ["ask", "deny"]) {
  const config = structuredClone(base)
  config.permission.edit[relative(worktree, normal)] = wanted
  await probe(await setup(config), "write", { filePath: normal, content: "fixture" }, [edit(normal)], wanted === "deny" ? "refused" : "ask")
}
for (const replacement of ["ask", "deny", { "*": "deny", "../*": "ask" }, { "*": "allow", "../*": "deny" }, { "../*": "ask", "*": "allow" }]) {
  const config = structuredClone(base)
  config.permission.edit = replacement
  const snapshot = structuredClone(config)
  await setup(config)
  assert.deepEqual(config, snapshot)
  checks++
}
for (const replacement of ["ask", "deny", { "*": "allow", [relative(worktree, normal)]: "ask" }]) {
  const config = structuredClone(base)
  config.permission.read = replacement
  const snapshot = structuredClone(config)
  const conservative = await setup(config)
  assert.deepEqual(config, snapshot, "non-default read policy must retain the original edit ask")
  await probe(conservative, "write", { filePath: normal, content: "fixture" }, [edit(normal)], "ask")
}
for (const wanted of ["ask", "deny"]) {
  const config = structuredClone(base)
  config.permission.edit[relative(worktree, root) + "/*"] = wanted
  const snapshot = structuredClone(config)
  await setup(config)
  assert.deepEqual(config, snapshot, "an existing exact-pattern override must not be replaced")
  checks++
}
for (const overrides of [{ "*": "deny" }, { edit: "deny" }, base.agent.auditor.permission]) {
  await probe(state, "write", { filePath: normal, content: "fixture" }, [edit(normal)], "deny", overrides)
}
await probe(state, "write", { filePath: normal, content: "fixture" }, [edit(normal)], "ask", { edit: { [relative(worktree, normal)]: "ask" } })
const globalDeny = structuredClone(base)
globalDeny.permission["*"] = "deny"
await probe(await setup(globalDeny), "write", { filePath: normal, content: "fixture" }, [edit(normal)], "refused")
const readDeny = structuredClone(base)
readDeny.permission.read[relative(worktree, normal)] = "deny"
await probe(await setup(readDeny), "edit", { filePath: normal, oldString: "x", newString: "y" }, [edit(normal)], "refused")

// Synthetic sensitive paths need no contents: the guard refuses before reads.
for (const name of [".env", ".env.local", "secrets/ordinary.md", "credentials", "auth.json", "private.pem", ".ssh/config", ".aws/ordinary.md", ".gnupg/ordinary.md", ".kube/config", ".mozilla/profile", ".config/BraveSoftware/profile", ".config/chromium/profile", ".local/share/keyrings/ordinary", ".claude/.credentials.json", ".codex/auth.json", ".config/gh/hosts.yml", ".docker/config.json", ".local/share/opencode/auth.json", ".bash_history", ".zsh_history", ".git/config", ".agents/hooks/commit-gate"]) {
  const path = join(root, "session", name)
  await probe(state, "apply_patch", { patchText: patch(`*** Add File: ${path}`, "+synthetic") }, [add(path)], "refused")
}
await fs.writeFile(join(tmp, "outside/unread.md"), "outside synthetic sentinel\n")
await fs.symlink(join(tmp, "outside"), join(root, "escape"))
await fs.symlink(join(tmp, "outside"), join(root, "line\u2028break"))
await fs.symlink(normal, join(root, "inside-link"))
await fs.symlink(join(tmp, "missing"), join(root, "dangling"))
await fs.link(normal, join(root, "hardlink"))
for (const path of [join(root, "escape/unread.md"), join(root, "inside-link"), join(root, "dangling/new.md"), join(root, "hardlink"), root + "/escape/../new.md", root + "\\escape\\new.md", root + "/session/../new.md", root + "/session/control\nname"]) {
  await probe(state, "write", { filePath: path, content: "fixture" }, [add(path)], "refused")
}
await fs.unlink(join(root, "hardlink"))
const unicodeEscape = join(root, "line\u2028break/unread.md")
await probe(state, "apply_patch", { patchText: patch(`*** Add File: ${unicodeEscape}`, "+synthetic") }, [add(unicodeEscape)], "refused")
const beforeMixed = await fs.readFile(mixed, "utf8")
for (const kind of ["Add", "Update", "Delete"]) {
  await probe(state, "apply_patch", { patchText: patch(`*** Update File: ${mixed}`, "@@", "-old", "+new", `*** ${kind} File: ${join(root, "escape/unread.md")}`, "+bad last hunk") }, [edit(mixed), add(join(root, "escape/unread.md"))], "refused")
}
assert.equal(await fs.readFile(mixed, "utf8"), beforeMixed)
assert.equal(await fs.readFile(join(tmp, "outside/unread.md"), "utf8"), "outside synthetic sentinel\n")
for (const [from, to] of [[normal, join(root, "renamed.md")], [normal, join(tmp, "outside/destination.md")], [mixed, join(root, "renamed.md")]]) {
  await probe(state, "apply_patch", { patchText: patch(`*** Update File: ${from}`, `*** Move to: ${to}`, "@@", "-old", "+new") }, [edit(from), add(to)], "refused")
}
const renamed = join(root, "renamed.md")
await probe(state, "apply_patch", { patchText: patch(`*** Add File: ${renamed}`, "+fixture result", `*** Delete File: ${normal}`) }, [add(renamed), { path: normal, operation: "delete" }], "allow")

const writable = join(root, "writable")
await fs.mkdir(writable)
await fs.chmod(writable, 0o777)
await probe(state, "write", { filePath: join(writable, "new.md"), content: "fixture" }, [add(join(writable, "new.md"))], "refused")
await fs.chmod(writable, 0o700)
await probe(state, "write", { filePath: renamed + "/child", content: "fixture" }, [add(renamed + "/child")], "refused")
execFileSync("mkfifo", [join(root, "fifo")])
await probe(state, "write", { filePath: join(root, "fifo"), content: "fixture" }, [add(join(root, "fifo"))], "refused")
if (process.getuid() !== 0) {
  await fs.chmod(writable, 0)
  try { await probe(state, "write", { filePath: join(writable, "new.md"), content: "fixture" }, [add(join(writable, "new.md"))], "refused") }
  finally { await fs.chmod(writable, 0o700) }
}
await fs.chmod(root, 0o777)
const noGrant = structuredClone(base)
await setup(noGrant)
assert.deepEqual(noGrant, base)
await probe(state, "write", { filePath: renamed, content: "fixture" }, [edit(renamed)], "refused")
await fs.chmod(root, 0o700)
await fs.rename(root, root + "-saved")
try {
  await fs.mkdir(root)
  await probe(state, "write", { filePath: join(root, "replacement.md"), content: "fixture" }, [add(join(root, "replacement.md"))], "refused")
  await fs.rmdir(root)
  await fs.symlink(root + "-saved", root)
  const symlinkRoot = structuredClone(base)
  await setup(symlinkRoot)
  assert.deepEqual(symlinkRoot, base)
  await probe(state, "write", { filePath: renamed, content: "fixture" }, [edit(renamed)], "refused")
  await fs.unlink(root)
} finally { await fs.rename(root + "-saved", root) }

// Real worktree coordinates, including bounded nested-worktree grants.
for (const wt of ["/", tmp, root, join(root, "nested/repo"), join(tmp, "worktree [with spaces]")]) {
  if (wt !== "/" && wt !== tmp) await fs.mkdir(wt, { recursive: true })
  const cwd = wt === "/" || wt === tmp ? directory : wt
  const located = await setup(structuredClone(base), wt, cwd)
  const target = join(root, "location-result.md")
  await probe(located, "write", { filePath: target, content: "fixture" }, [add(target)], "allow")
  const outside = join(tmp, "outside/no-grant.md")
  const baseline = evaluate("edit", relative(wt, outside), base.permission)
  assert.equal(evaluate("edit", relative(wt, outside), located.config.permission), baseline)
  await probe(located, "write", { filePath: outside, content: "fixture" }, [add(outside)], wt === "/" ? "ask" : baseline)
  if (wt === "/") {
    // The unchanged ../* edit rule misses non-Git '/' subjects. An approved
    // persistent location therefore permits edits here, not in a Git worktree.
    const persistent = join(process.env.HOME, "Projects/scratch/root-worktree.md")
    assert.equal(evaluate("edit", relative(wt, persistent), base.permission), "allow")
    await probe(located, "write", { filePath: persistent, content: "fixture" }, [add(persistent)], "allow")
  }
}
for (const wt of [join(tmp, "missing-worktree"), join(tmp, "wild*worktree")]) {
  const config = structuredClone(base)
  await setup(config, wt, wt)
  assert.deepEqual(config, base)
  checks++
}
await fs.symlink(worktree, join(tmp, "linked-worktree"))
const linked = structuredClone(base)
await setup(linked, join(tmp, "linked-worktree"), join(tmp, "linked-worktree"))
assert.deepEqual(linked, base)
for (const tool of ["read", "glob", "bash", "custom_write", "unknown_future_tool"]) {
  const args = { filePath: join(root, "escape/unread.md"), command: "unchanged" }
  const saved = structuredClone(args)
  await state.hooks["tool.execute.before"]({ tool }, { args })
  assert.deepEqual(args, saved)
  checks++
}
console.log(`ok: OpenCode scratch permissions (${checks} hermetic checks; no live tool calls)`)
JS
