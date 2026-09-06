// Restore native scratch writes without a worktree-relative lookalike grant.
// Source contract: OpenCode b578b726, plugin/config, permission and native tools.
// Preflight rejects existing link escapes; it cannot prevent a subsequent
// filesystem race or identify which session owns a child of the managed root.
// Merged config has no provenance for a project restating a default unchanged.
import { lstat, realpath } from "node:fs/promises"
import { homedir, tmpdir } from "node:os"
import { isAbsolute, join, normalize, relative } from "node:path"

const SCRATCH_ROOT = "/tmp/opencode"
const inside = (root, target) => target === root || target.startsWith(root + "/")

function matches(subject, pattern) {
  if (pattern === "~" || pattern.startsWith("~/")) pattern = homedir() + pattern.slice(1)
  else if (pattern.startsWith("$HOME")) pattern = homedir() + pattern.slice(5)
  let expression = pattern.replaceAll("\\", "/").replace(/[.+^${}()|[\]\\]/g, "\\$&")
    .replaceAll("*", ".*").replaceAll("?", ".")
  if (expression.endsWith(" .*")) expression = expression.slice(0, -3) + "( .*)?"
  return new RegExp("^" + expression + "$", "s").test(subject.replaceAll("\\", "/"))
}

function action(permissions, tool, subject) {
  let result = "ask"
  for (const [name, value] of Object.entries(permissions)) {
    if (!matches(tool, name)) continue
    for (const [pattern, decision] of Object.entries(typeof value === "string" ? { "*": value } : value)) {
      if (matches(subject, pattern)) result = decision
    }
  }
  return result
}

export const ScratchPermissions = async ({ directory, worktree }) => {
  let guard
  const refuse = () => { throw new Error("scratch-permissions: unsafe or ambiguous scratch target; use a regular non-link path inside the managed root") }

  return {
    config: async (cfg) => {
      if (guard || process.platform !== "linux" || join(tmpdir(), "opencode") !== SCRATCH_ROOT) return
      const rules = cfg.permission?.edit
      if (!rules || typeof rules !== "object" || Array.isArray(rules)) return
      const read = cfg.permission.read
      if (!read || typeof read !== "object" || Array.isArray(read) || read["*"] !== "allow" ||
          Object.entries(read).some(([pattern, decision]) => pattern !== "*" && decision !== "deny")) return
      const entries = Object.entries(rules)
      if (entries[0]?.[0] !== "*" || entries[0]?.[1] !== "allow" ||
          entries[1]?.[0] !== "../*" || entries[1]?.[1] !== "ask") return
      if (![directory, worktree].every((path) => typeof path === "string" && isAbsolute(path) &&
          normalize(path) === path && !/[\\*?\x00-\x1f\x7f]/.test(path)) || !inside(worktree, directory) && worktree !== "/") return

      const additions = []
      if (worktree !== SCRATCH_ROOT) {
        if (inside(SCRATCH_ROOT, worktree)) {
          const depth = relative(SCRATCH_ROOT, worktree).split("/").length
          additions.push(["../**", "allow"], ["../".repeat(depth + 1) + "*", "ask"])
        } else {
          additions.push([relative(worktree, SCRATCH_ROOT) + "/*", "allow"])
        }
      }
      if (additions.some(([pattern]) => Object.hasOwn(rules, pattern))) return

      let root
      try {
        root = await lstat(SCRATCH_ROOT)
        if (!root.isDirectory() || root.uid !== process.getuid() || root.mode & 0o022 ||
            await realpath(SCRATCH_ROOT) !== SCRATCH_ROOT || await realpath(worktree) !== worktree ||
            await realpath(directory) !== directory) return
      } catch {
        return // Unsupported layout retains the native ask/deny, never a grant.
      }

      const next = Object.fromEntries([...entries.slice(0, 2), ...additions, ...entries.slice(2)])
      const added = { edit: Object.fromEntries(additions) }
      const before = async (input, output) => {
        if (!["edit", "write", "apply_patch"].includes(input.tool)) return
        const args = output.args
        let paths = []
        let move = false
        if (input.tool === "apply_patch") {
          if (typeof args?.patchText !== "string") return
          // Over-approximate the native parser's headers, including wrappers.
          // Added/context lines have a prefix and cannot become file headers.
          for (const line of args.patchText.trim().split("\n")) {
            const header = /^\*\*\* (Add File|Update File|Delete File|Move to):(.*)$/s.exec(line.replace(/\r$/, ""))
            if (!header) continue
            move ||= header[1] === "Move to"
            const operand = header[2].trim()
            if (operand) paths.push(isAbsolute(operand) ? normalize(operand) : join(directory, operand))
          }
        } else {
          if (typeof args?.filePath !== "string") return
          // Native edit/write normalize relative operands, but pass absolute
          // spellings unchanged to the filesystem, including symlink/.. traversal.
          paths = [isAbsolute(args.filePath) ? args.filePath : join(directory, args.filePath)]
        }
        paths = paths.filter((path) => inside(SCRATCH_ROOT, normalize(path)) ||
          action(added, "edit", relative(worktree, path)) === "allow")
        if (!paths.length) return
        if (move) throw new Error("scratch-permissions: use Add File and Delete File instead of Move to so both endpoints receive native permission checks")

        const current = await lstat(SCRATCH_ROOT).catch(refuse)
        if (!current.isDirectory() || current.uid !== process.getuid() || current.mode & 0o022 ||
            current.dev !== root.dev || current.ino !== root.ino || await realpath(SCRATCH_ROOT) !== SCRATCH_ROOT) refuse()
        for (const path of paths) {
          if (path === SCRATCH_ROOT || !inside(SCRATCH_ROOT, path) || normalize(path) !== path ||
              /[\\\x00-\x1f\x7f]/.test(path)) refuse()
          const subject = relative(worktree, path)
          const parent = path.slice(0, path.lastIndexOf("/"))
          if (action(cfg.permission, "read", subject) === "deny" || action(cfg.permission, "edit", subject) === "deny" ||
              action(cfg.permission, "external_directory", parent + "/*") === "deny") refuse()

          const parts = relative(SCRATCH_ROOT, path).split("/")
          let existing = SCRATCH_ROOT
          for (let index = 0; index < parts.length; index++) {
            const target = join(existing, parts[index])
            let metadata
            try { metadata = await lstat(target) } catch (error) {
              if (error.code === "ENOENT") break
              refuse()
            }
            if (metadata.isSymbolicLink() || metadata.uid !== process.getuid() || metadata.mode & 0o022 ||
                (index < parts.length - 1 ? !metadata.isDirectory() : !metadata.isFile() || metadata.nlink !== 1)) refuse()
            existing = target
          }
          if (await realpath(existing).catch(refuse) !== existing) refuse()
        }
      }

      // OpenCode ignores config-hook failures. The deny guard must exist before
      // the only mutation, which preserves the order of all existing rules.
      guard = before
      cfg.permission.edit = next
    },
    "tool.execute.before": async (input, output) => {
      if (guard) await guard(input, output)
    },
  }
}
