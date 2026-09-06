#!/usr/bin/env python3
"""Check the authority boundaries of the managed tool configurations.

These checks parse the deployed configuration files and assert the boundaries
that AGENTS.md promises: automatic modes stay bounded, pushes and privilege
escalation stay denied, credential stores are neither readable nor writable,
Git internals are not writable by file tools, destructive Git operations need
an explicit instruction, and permission ordering keeps later denies effective.
Wording, key order, and implementation shape are deliberately not pinned.
"""

from __future__ import annotations

import json
import os
import re
import runpy
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(os.environ.get("CONFIG_CONTRACT_ROOT", Path(__file__).resolve().parent.parent))

# Directory stores end with /** in Claude and OpenCode rules; file stores do not.
CREDENTIAL_DIRECTORIES = (
    "~/.aws",
    "~/.config/BraveSoftware",
    "~/.config/chromium",
    "~/.gnupg",
    "~/.kube",
    "~/.local/share/keyrings",
    "~/.mozilla",
    "~/.ssh",
)
CREDENTIAL_FILES = (
    "~/.bash_history",
    "~/.claude/.credentials.json",
    "~/.codex/auth.json",
    "~/.config/gh/hosts.yml",
    "~/.docker/config.json",
    "~/.local/share/opencode/auth.json",
    "~/.netrc",
    "~/.npmrc",
    "~/.pypirc",
    "~/.zsh_history",
)
# Credential stores that may be copied into a repository; every copy stays unreadable.
PROJECT_STORE_DIRECTORIES = (".aws", ".gnupg", ".kube", ".ssh", ".config/BraveSoftware", ".config/chromium", ".local/share/keyrings", ".mozilla")
PROJECT_STORE_FILES = (".claude/.credentials.json", ".codex/auth.json", ".config/gh/hosts.yml", ".docker/config.json", ".local/share/opencode/auth.json", ".bash_history", ".zsh_history")
PROJECT_STORES = (*PROJECT_STORE_DIRECTORIES, *PROJECT_STORE_FILES)
# System trees every tool reads by standing grant; the rest of the filesystem asks.
SYSTEM_READ_TREES = ("/usr", "/etc", "/opt", "/sys", "/var/lib/pacman")
# Temp roots every tool reads; each tool is denied the other tools' session roots there.
TEMP_READ_TREES = ("/tmp", "/var/tmp")

CREDENTIAL_SHAPES = (
    ".env",
    ".env.*",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "*.key",
    "*.p12",
    "*.pem",
    "*.pfx",
    "auth.json",
    "credentials",
    "credentials.*",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "secrets/**",
)
HARD_DENIED_GIT = ("git clean *", "git push", "git push *")
APPROVAL_GIT = (
    "git checkout -- *",
    "git reset *",
    "git restore *",
    "git stash clear *",
    "git stash drop *",
)
PRIVILEGE = ("doas *", "pkexec *", "su *", "sudo *")
REPOSITORY_HOST = (
    "gh gist create*",
    "gh issue create*",
    "gh pr create*",
    "gh pr merge*",
    "gh release create*",
)
REPOSITORY_HOST_EXTENDED = (
    "gh api *",
    "gh auth *",
    "gh gpg-key *",
    "gh repo create*",
    "gh repo delete*",
    "gh run cancel*",
    "gh secret *",
    "gh ssh-key *",
    "gh workflow run*",
)


def load_json(path: str):
    with (ROOT / path).open(encoding="utf-8") as handle:
        return json.load(handle)


def load_toml(path: str):
    with (ROOT / path).open("rb") as handle:
        return tomllib.load(handle)


def load_toml_file(path: str):
    with open(path, "rb") as handle:
        return tomllib.load(handle)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")


def denies_come_last(rules: dict, label: str) -> None:
    """Last match wins, so every allow or ask precedes every deny or it reopens one."""
    actions = list(rules.values())
    opens = [index for index, action in enumerate(actions) if action != "deny"]
    denies = [index for index, action in enumerate(actions) if action == "deny"]
    if opens and denies:
        require(max(opens) < min(denies), f"OpenCode {label}: an allow or ask follows a deny and reopens it")


def relative_deny(rules: dict, path: str) -> bool:
    """A worktree-relative subject is denied at depth by a **/ rule on the path, its basename,
    or an ancestor, and at the worktree root by the bare form, since **/ needs a slash."""
    parts = path.split("/")
    deep = {f"**/{path}", f"**/{parts[-1]}"}
    bare = {path}
    for index in range(1, len(parts)):
        deep.add(f"**/{'/'.join(parts[:index])}/**")
        bare.add(f"{'/'.join(parts[:index])}/**")
    return any(rules.get(c) == "deny" for c in deep) and any(rules.get(c) == "deny" for c in bare)


def covered(rules: set[str], tool: str, path: str) -> bool:
    """A store path is covered by an exact rule or by a /** rule on an ancestor."""
    candidates = {f"{tool}({path})", f"{tool}({path}/**)"}
    parts = path.split("/")
    for index in range(1, len(parts)):
        candidates.add(f"{tool}({'/'.join(parts[:index])}/**)")
    return bool(rules & candidates)


# Claude Code
claude = load_json("claude-code/.claude/settings.json")
permissions = claude["permissions"]
require(permissions["defaultMode"] == "auto", "Claude default mode is not auto")
require(permissions["disableBypassPermissionsMode"] == "disable", "Claude bypass mode is enabled")
require("sandbox" not in claude, "Claude tracked settings enable sandboxing")
require("$defaults" in claude["autoMode"]["hard_deny"], "Claude auto mode dropped the built-in hard denies")
claude_deny = set(permissions["deny"])
for command in (*HARD_DENIED_GIT, *PRIVILEGE, *REPOSITORY_HOST):
    require(f"Bash({command})" in claude_deny, f"Claude deny missing: {command}")
for command in APPROVAL_GIT:
    require(f"Bash({command})" not in claude_deny, f"Claude denies an approval-based Git command outright: {command}")
soft_denies = " ".join(claude["autoMode"]["soft_deny"])
for phrase in ("git reset", "git remote", "gh auth", "startup files"):
    require(phrase in soft_denies, f"Claude classifier rule missing for: {phrase}")
for path in (*CREDENTIAL_DIRECTORIES, *CREDENTIAL_FILES):
    require(covered(claude_deny, "Read", path), f"Claude credential store readable: {path}")
    require(covered(claude_deny, "Edit", path), f"Claude credential store writable: {path}")
for shape in CREDENTIAL_SHAPES:
    require(f"Read(//**/{shape})" in claude_deny, f"Claude credential-shaped read deny missing: {shape}")
    require(f"Edit(//**/{shape})" in claude_deny, f"Claude credential-shaped edit deny missing: {shape}")
for rule in claude_deny:
    if rule.startswith("Read(") and (rule.startswith("Read(~/") or rule.startswith("Read(//")):
        require(rule.replace("Read(", "Edit(", 1) in claude_deny or covered(claude_deny, "Edit", rule[5:-1]),
                f"Claude read deny has no write mirror: {rule}")
require("Edit(//**/.git/**)" in claude_deny and "Edit(~/.config/git/**)" in claude_deny, "Claude Git internals are writable")
for rule in permissions["allow"]:
    require(
        not rule.startswith(("Bash(git push", "Bash(gh ", "Bash(sudo")),
        f"Claude automatic allow reaches a guarded command: {rule}",
    )

# Codex
codex_template = load_toml("templates/codex/config.toml")


def check_codex(config: dict, label: str) -> None:
    require(config["default_permissions"] == "trusted-workspace", f"{label} default profile drifted")
    require(config["approvals_reviewer"] == "auto_review", f"{label} approval review drifted")
    require("sandbox_mode" not in config, f"{label} mixes legacy sandbox with permission profile")
    profile = config["permissions"]["trusted-workspace"]
    filesystem = profile["filesystem"]
    require(filesystem[":root"] == "deny", f"{label} filesystem root is not denied")
    require(profile["network"]["enabled"] is False, f"{label} command network is enabled")
    require(filesystem.get("~/.local/share/mise") == "read", f"{label} cannot execute mise-managed runtimes")
    for path in (*CREDENTIAL_DIRECTORIES, *CREDENTIAL_FILES):
        require(filesystem.get(path) == "deny", f"{label} credential store reachable: {path}")
    require(filesystem.get("~/Projects") == "read", f"{label} cannot read H's repositories under ~/Projects")
    for tree in SYSTEM_READ_TREES:
        require(filesystem.get(tree) == "read", f"{label} cannot read the system tree {tree}")
    require(filesystem.get("/var/tmp") == "read" and filesystem.get(":slash_tmp") in ("read", "write"), f"{label} cannot read the temp roots")
    for other in ("/tmp/opencode", "/tmp/claude-1000"):
        require(filesystem.get(other) == "deny", f"{label} reads another tool's session root: {other}")
    for key in filesystem:
        require(not (key.startswith(("/tmp/", "/var/tmp/")) and any(c in key for c in "*?")), f"{label} carries a glob under a temp root, which stalls the sandbox: {key}")
    for shape in CREDENTIAL_SHAPES:
        require(shape == ".npmrc" or filesystem.get(f"~/**/{shape}") == "deny" or filesystem.get(f"~/Projects/**/{shape}") == "deny", f"{label} credential shape reachable under ~/Projects: {shape}")
    for store in PROJECT_STORES:
        require(filesystem.get(f"~/Projects/**/{store}") == "deny", f"{label} credential store copy reachable under ~/Projects: {store}")
    # OpenSSH keys live under ~/.ssh and the rc files are denied as literal
    # home paths; home-wide globs for them match files inside already denied
    # or runtime trees and break or slow sandbox startup.
    for shape in CREDENTIAL_SHAPES:
        name = shape.removesuffix("/**")
        if name.startswith("id_") or name in (".netrc", ".npmrc", ".pypirc"):
            require(f"~/**/{name}" not in filesystem, f"{label} home-wide glob breaks sandbox startup: {name}")
            continue
        require(filesystem.get(f"~/**/{name}") == "deny", f"{label} home deny missing: {shape}")
    workspace = filesystem[":workspace_roots"]
    require(workspace["."] == "write", f"{label} workspace is not writable")
    require(workspace.get(".git/config") == "read" and workspace.get(".git/hooks") == "read",
            f"{label} Git configuration or hooks are writable in the workspace")
    for shape in CREDENTIAL_SHAPES:
        name = shape.removesuffix("/**")
        require(workspace.get(f"**/{name}") == "deny", f"{label} workspace deny missing: {shape}")
        require(name not in workspace, f"{label} literal workspace entry creates placeholder files: {name}")
    policy = config["auto_review"]["policy"]
    require("explicitly approves the exact candidate" in policy, f"{label} auto review no longer gates commits")
    # No template carries the marker the reconcile puts on a kept host line, so a
    # root the merge wrote with a host choice never reads as a template root.
    require("kept by the reconcile" not in (ROOT / "templates/codex/config.toml").read_text(encoding="utf-8"), "Codex template carries the reconcile's kept marker")
    # No model pin: the catalog default is the moving target (AGENTS.md, Tool Configuration).
    require("model" not in config and "default_subagent_model" not in config.get("agents", {}), f"{label} pins a model instead of the catalog default")


check_codex(codex_template, "Codex portable template")
if os.environ.get("HOST_CODEX_CONFIG"):
    check_codex(load_toml_file(os.environ["HOST_CODEX_CONFIG"]), "host Codex config")

# OpenCode
opencode = load_json("opencode/.config/opencode/opencode.json")
require(opencode["share"] == "disabled", "OpenCode sharing is enabled")
require(opencode["autoupdate"] is False, "OpenCode autoupdate competes with the wrapper")
bash = opencode["permission"]["bash"]
require(next(iter(bash.items())) == ("*", "allow"), "OpenCode Bash autonomy catch-all is not first")
for command in (*HARD_DENIED_GIT, *PRIVILEGE, *REPOSITORY_HOST, *REPOSITORY_HOST_EXTENDED, "claude *", "codex *", "opencode *"):
    require(bash.get(command) == "deny", f"OpenCode Bash deny missing: {command}")
for command in (*APPROVAL_GIT, "git remote set-url *", "git config core.hooksPath*", "git config credential*"):
    require(bash.get(command) == "ask", f"OpenCode Bash approval missing: {command}")
read_rules = opencode["permission"]["read"]
edit_rules = opencode["permission"]["edit"]
external_rules = opencode["permission"]["external_directory"]
require(read_rules["*"] == "allow" and edit_rules["*"] == "allow", "OpenCode workspace autonomy drifted")
require(external_rules["*"] == "ask", "OpenCode external directories no longer ask")
# Read and edit subjects are worktree-relative; external subjects are the parent
# directory plus /*, so an external rule that names a file can never match and
# file stores are denied by **/ rules in read and edit, while directory stores
# under $HOME rely on the external directory globs and the ask default.
for rule in external_rules:
    require(rule == "*" or rule.endswith("/*") or rule.endswith("/**"), f"OpenCode external rule can never match a parent-directory subject: {rule}")
require(edit_rules.get("../*") == "ask", "OpenCode edits outside the worktree without asking")
require(edit_rules.get("../*/tmp/opencode/*") == "allow", "OpenCode asks before writing its own temp root")
for path in CREDENTIAL_DIRECTORIES:
    glob = "**/" + path.removeprefix("~/") + "/**"
    require(external_rules.get(glob) == "deny", f"OpenCode external credential store deny missing: {glob}")
require(external_rules.get("**/.config/git/**") == "deny", "OpenCode Git configuration directory is reachable")
for shape in CREDENTIAL_SHAPES:
    for label, rules in (("read", read_rules), ("edit", edit_rules)):
        require(rules.get(f"**/{shape}") == "deny", f"OpenCode credential-shaped {label} deny missing: {shape}")
        require(rules.get(shape) == "deny", f"OpenCode credential-shaped {label} deny missing at the worktree root: {shape}")
require(edit_rules.get("**/.git/**") == "deny", "OpenCode Git internals are writable by file tools")
for label, rules in (("read", read_rules), ("edit", edit_rules), ("external_directory", external_rules)):
    denies_come_last(rules, label)
for tree in TEMP_READ_TREES:
    require(external_rules.get(f"{tree}/**") == "allow", f"OpenCode lacks the standing access under {tree}")
    require(f"Read(//{tree.lstrip('/')}/**)" in claude["permissions"]["allow"], f"Claude Code lacks the standing read allow on {tree}")
require(external_rules.get("/tmp/claude-*/**") == "deny", "OpenCode reads Claude Code's session root under /tmp")
require(external_rules.get("~/.agents/skills/**") == "allow", "OpenCode asks before its shell runs the skill scripts under ~/.agents/skills")
require(external_rules.get("~/.agents/hooks/**") == "deny", "OpenCode reaches the installed commit gate under ~/.agents/hooks")
require("Read(//tmp/opencode/**)" in claude["permissions"]["deny"], "Claude Code reads OpenCode's session root under /tmp")
claude = load_json("claude-code/.claude/settings.json")
def frontmatter(path):
    """Parse the YAML subset the agent files use: top-level `key: value` and one nested block of `  key: value`."""
    text = path.read_text(encoding="utf-8")
    require(text.startswith("---\n"), f"agent file has no frontmatter: {path.name}")
    fields, nested, current = {}, {}, None
    for line in text.split("---\n", 2)[1].splitlines():
        if line.startswith("  ") and current:
            key, _, value = line.strip().partition(":")
            nested.setdefault(current, {})[key.strip()] = value.strip()
        elif ":" in line:
            key, _, value = line.partition(":")
            current = key.strip()
            fields[current] = value.strip()
    return fields, nested


charter = (ROOT / "agents/.agents/agents/auditor.md").read_text(encoding="utf-8")
require(charter.strip() and "VERDICT" in charter, "the shared auditor charter is missing or has no verdict line")
claude_auditor = ROOT / "claude-code/.claude/agents/auditor.md"
require(claude_auditor.is_file(), "Claude Code auditor agent is missing")
fields, nested = frontmatter(claude_auditor)
require(fields.get("name") == "auditor", "Claude auditor agent name drifted")
require(set(fields.get("tools", "").replace(",", " ").split()) == {"Read", "Grep", "Glob"}, "Claude auditor agent is not exactly Read, Grep, Glob")
require(fields.get("model") == "fable" and fields.get("effort") == "xhigh", "Claude auditor agent is not the strongest model at xhigh")
CLAUDE_AGENT_FIELDS = {"name", "description", "tools", "model", "effort"}
require(set(fields) <= CLAUDE_AGENT_FIELDS, f"Claude auditor agent carries fields outside the permitted set: {set(fields) - CLAUDE_AGENT_FIELDS}")
require(claude_auditor.read_text(encoding="utf-8").split("---\n", 2)[2].strip() == charter.strip(), "Claude auditor body differs from the shared charter")
for agent_file in (ROOT / "claude-code/.claude/agents").glob("*.md"):
    agent_fields, _ = frontmatter(agent_file)
    require(set(agent_fields.get("tools", "x").replace(",", " ").split()) <= {"Read", "Grep", "Glob"}, f"Claude agent is not read-only: {agent_file.name}")
    require(set(agent_fields) <= CLAUDE_AGENT_FIELDS, f"Claude agent carries fields outside the permitted set: {agent_file.name}")

opencode_agents = opencode.get("agent", {})
auditor = opencode_agents.get("auditor", {})
require(auditor.get("mode") == "subagent", "OpenCode auditor agent is not a subagent")
require(auditor.get("model") == opencode["model"], "OpenCode auditor agent does not run the configured primary model")
require(opencode["provider"]["openai"]["models"][opencode["model"].split("/", 1)[1]]["options"]["reasoningEffort"] == "xhigh", "OpenCode auditor model is not configured at xhigh")
require(auditor.get("prompt") == "{file:~/.agents/agents/auditor.md}", "OpenCode auditor does not read the shared charter")
require(auditor.get("permission") == {"edit": "deny", "bash": "deny", "webfetch": "deny", "websearch": "deny", "task": "deny"}, "OpenCode auditor does not deny exactly edit, bash, webfetch, websearch, task")
for name, agent in opencode_agents.items():
    permissions = agent.get("permission", {})
    require(permissions and all(value == "deny" for value in permissions.values()), f"OpenCode agent loosens or omits permissions: {name}")
    require("tools" not in agent, f"OpenCode agent uses the deprecated tools field: {name}")
require(not (ROOT / "opencode/.config/opencode/agents").exists(), "OpenCode markdown agents exist beside the config agents")
require(not (ROOT / "codex/.codex/agents").exists(), "a Codex agent role exists without a verified read-only authority profile")
require(claude.get("attribution", {}).get("sessionUrl") is False, "Claude Code would add a session URL trailer to commits")
require("classifyAllShell" not in claude.get("autoMode", {}), "Claude Code re-classifies its allow-listed commands for no gain")
for store in PROJECT_STORES:
    glob = f"//**/{store}/**" if store in PROJECT_STORE_DIRECTORIES else f"//**/{store}"
    for tool in ("Read", "Edit"):
        require(f"{tool}({glob})" in claude["permissions"]["deny"], f"Claude Code file tools reach a credential store copy: {tool}({glob})")
    for label, rules in (("read", read_rules), ("edit", edit_rules)):
        if store in PROJECT_STORE_DIRECTORIES:
            require(rules.get(f"**/{store}/**") == "deny" and rules.get(f"{store}/**") == "deny", f"OpenCode {label} rules reach a credential store copy: {store}")
        else:
            require(relative_deny(rules, store), f"OpenCode {label} rules reach a credential store copy: {store}")
    if store in PROJECT_STORE_DIRECTORIES:
        require(external_rules.get(f"**/{store}/**") == "deny", f"OpenCode external directory rule reaches a credential store copy: {store}")
require("Read(~/Projects/**)" in claude["permissions"]["allow"], "Claude Code lacks the standing read allow under ~/Projects")
require(external_rules.get("~/Projects/**") == "allow", "OpenCode lacks the standing access under ~/Projects")
for tree in SYSTEM_READ_TREES:
    require(f"Read(//{tree.lstrip('/')}/**)" in claude["permissions"]["allow"], f"Claude Code lacks the standing read allow on {tree}")
    require(external_rules.get(f"{tree}/**") == "allow", f"OpenCode lacks the standing access under {tree}")
require(codex_template.get("personality") == "none", "Codex personality filler is not disabled")
require(re.fullmatch(r"openai/[a-z0-9][a-z0-9.-]*", opencode.get("small_model", "")), "OpenCode small_model is not a concrete OpenAI model id")
require(opencode.get("skills", {}).get("paths") == ["~/.agents/skills"], "OpenCode skill paths are not exactly the neutral source")
load_json("opencode/.config/opencode/tui.json")

# Models: a moving alias or catalog default where the tool offers one, a
# concrete id only where it does not (AGENTS.md, Tool Configuration).
require(claude.get("model") == "fable", "Claude Code pins a model instead of the fable alias")
require(claude.get("env", {}).get("CLAUDE_CODE_EFFORT_LEVEL") == "xhigh", "Claude Code effort is not xhigh")
spar_claude = (ROOT / "agents/.agents/skills/spar/scripts/spar-claude").read_text(encoding="utf-8")
require('MODEL="fable"' in spar_claude and re.search(r'^\s*--model "\$MODEL"\s*$', spar_claude, re.M), "spar-claude does not review with the fable alias")
require(re.search(r'ANTHROPIC_DEFAULT_FABLE_MODEL:\s*""', spar_claude) and spar_claude.count("ANTHROPIC_DEFAULT_") == 1, "spar-claude does not clear exactly the fable override")
require("service_tier" not in codex_template and codex_template["features"].get("fast_mode") is True, "Codex template sets a service tier by default or drops the /fast toggle")
require(codex_template.get("model_reasoning_effort") == "xhigh" and codex_template.get("agents", {}).get("default_subagent_reasoning_effort") == "xhigh", "Codex template effort is not xhigh")
spar_codex = (ROOT / "agents/.agents/skills/spar/scripts/spar-codex").read_text(encoding="utf-8")
require(not re.search(r"^\s*(-m\S*|--model\S*|-p\S*|--profile\S*)(\s|$)", spar_codex, re.M) and not re.search(r"""(^|\s)(-c|--config)(=|\s+)?["']?\s*(profiles\.[^=\s]+\.)?model\s*=""", spar_codex, re.M), "spar-codex pins a reviewer model instead of the catalog default")
require('service_tier="default"' in spar_codex and 'service_tier="fast"' not in spar_codex and 'model_reasoning_effort="xhigh"' in spar_codex, "spar-codex does not review on the standard tier at xhigh")
require(re.fullmatch(r"openai/gpt-[0-9][a-z0-9.-]*", opencode["model"]) and not opencode["model"].endswith("-fast"), "OpenCode model is not a concrete GPT id on the standard tier")
require(not opencode["small_model"].endswith("-fast"), "OpenCode small model is on the Fast tier")


# Commit gate: every tool runs commit-gate before a shell command.
claude = load_json("claude-code/.claude/settings.json")
gate_hooks = [
    hook["command"]
    for entry in claude.get("hooks", {}).get("PreToolUse", [])
    if entry.get("matcher") == "Bash"
    for hook in entry.get("hooks", [])
    if hook.get("type") == "command"
]
require(any(command.endswith(".agents/hooks/commit-gate") for command in gate_hooks), "Claude Code does not run the installed commit-gate before Bash")
require(not any("\"if\"" in json.dumps(entry) for entry in claude.get("hooks", {}).get("PreToolUse", [])), "Claude Code narrows the gate hook with an if filter")
require("Edit(~/.agents/hooks/**)" in claude["permissions"]["deny"], "Claude Code file tools may edit the installed commit gate")
require(codex_template["features"].get("hooks") is True, "Codex hooks are not enabled, so commit-gate cannot run")
codex_gate = [
    hook["command"]
    for entry in codex_template.get("hooks", {}).get("PreToolUse", [])
    for hook in entry.get("hooks", [])
    if hook.get("type") == "command"
]
require(any(command.endswith(".agents/hooks/commit-gate") for command in codex_gate), "Codex does not run the installed commit-gate before a tool call")
require(edit_rules.get("**/.agents/hooks/**") == "deny", "OpenCode file tools may edit the installed commit gate")
require(external_rules.get("~/.agents/hooks/**") == "deny", "OpenCode may reach the installed commit gate")
require((ROOT / "opencode/.config/opencode/plugins/commit-gate.js").is_file(), "OpenCode commit-gate plugin is missing")
for skill, script in (("commit", "commit-candidate"), ("commit", "commit-apply"), ("publish", "publish-bind"), ("publish", "publish-verify")):
    require(os.access(ROOT / "agents/.agents/skills" / skill / "scripts" / script, os.X_OK), f"skill script missing or not executable: {skill}/scripts/{script}")
require(os.access(ROOT / "templates/hooks/commit-gate", os.X_OK), "templates/hooks/commit-gate is missing or not executable")

# Skills stay portable: the name matches the directory and only standard frontmatter fields appear.
STANDARD_SKILL_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
for skill_dir in sorted([*(ROOT / "agents/.agents/skills").iterdir(), *(ROOT / ".agents/skills").iterdir()]):
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    require(text.startswith("---\n"), f"skill has no frontmatter: {skill_dir.name}")
    frontmatter = text.split("---\n", 2)[1]
    fields = {line.split(":", 1)[0].strip(): line.split(":", 1)[1].strip() for line in frontmatter.splitlines() if ":" in line and not line.startswith(" ")}
    require(fields.get("name") == skill_dir.name, f"skill name does not match its directory: {skill_dir.name}")
    require(bool(fields.get("description")), f"skill lacks a description: {skill_dir.name}")
    require(set(fields) <= STANDARD_SKILL_FIELDS, f"skill uses non-standard frontmatter fields: {skill_dir.name}: {set(fields) - STANDARD_SKILL_FIELDS}")

# One concrete path corpus exercises the scanner and effective permission
# matchers, including store copies at the worktree root and at depth.
scan = runpy.run_path(str(ROOT / "agents/.agents/skills/spar/scripts/spar-payload-scan"))
corpus = [*(store + "/ordinary.txt" for store in PROJECT_STORE_DIRECTORIES), *PROJECT_STORE_FILES,
          *(shape.replace("*", "fixture") for shape in CREDENTIAL_SHAPES if shape != "secrets/**"), "secrets/ordinary.txt"]
safe_paths = ("README.md", "credentials-policy.md", "example.env", "docs/authentication.md", ".config/gh-policy.md")
bridge_fixtures = os.environ.get("SPAR_BRIDGE_FIXTURES")
if bridge_fixtures:
    argv = (Path(bridge_fixtures) / "spar-claude.argv").read_bytes().decode().rstrip("\0").split("\0")
    bridge_claude = json.loads(argv[argv.index("--settings") + 1])["permissions"]["deny"]
    argv = (Path(bridge_fixtures) / "spar-codex.argv").read_bytes().decode().rstrip("\0").split("\0")
    profile = next(arg for arg in argv if arg.startswith("permissions.spar-reviewer="))
    bridge_codex = tomllib.loads(profile)["permissions"]["spar-reviewer"]["filesystem"][":workspace_roots"]

    def path_glob(subject: str, pattern: str) -> bool:
        # Claude path globs and Codex workspace globs match **/ at zero depth.
        expression = re.escape(pattern).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
        return re.fullmatch(expression, subject) is not None

for prefix in ("", "copy/deep/"):
    for name, denied in [(name, True) for name in corpus] + [(name, False) for name in safe_paths]:
        subject = prefix + name
        require(scan["sensitive_path"](subject) == denied, f"scanner path corpus mismatch: {subject}")
        if bridge_fixtures:
            claude_denied = any(rule.startswith("Read(./") and path_glob(subject, rule[7:-1]) for rule in bridge_claude)
            ancestors = ["/".join(subject.split("/")[:end]) for end in range(1, len(subject.split("/")) + 1)]
            codex_denied = any(action == "deny" and any(path_glob(path, pattern) for path in ancestors) for pattern, action in bridge_codex.items())
            require(claude_denied == denied, f"Claude bridge path corpus mismatch: {subject}")
            require(codex_denied == denied, f"Codex bridge path corpus mismatch: {subject}")
            fixture = Path(bridge_fixtures) / "corpus" / subject
            fixture.parent.mkdir(parents=True, exist_ok=True)
            fixture.write_text("ordinary synthetic fixture\n")
            scanned = subprocess.run([str(ROOT / "agents/.agents/skills/spar/scripts/spar-payload-scan"),
                                      "outbound", "--scratch-root", bridge_fixtures, "--", str(fixture)],
                                     input="Review synthetic fixture.", capture_output=True, text=True)
            require(scanned.returncode == (2 if denied else 0), f"scanner artifact corpus mismatch: {subject}")
print("ok: configuration authority boundaries")
