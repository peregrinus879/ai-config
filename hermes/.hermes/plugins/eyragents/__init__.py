"""EyrAgents guardrails for Hermes 0.19's local native-tool dispatch.

Keep Hermes's toolset and learning intact. This is not a sandbox: arbitrary
shell/Python, interactive-process input, remote backends and foreign plugins
have distinct authority. Missing/disabled plugins are an upstream fail-open
condition, checked by deployment, not an isolation guarantee.

Request middleware makes local file operands task-absolute because 0.19's
backend may otherwise use a shared environment cwd. The only internal binding
adaptation composes file_tools.get_read_block_error to preserve native search
result filtering with the same credential predicate. It filters returned paths,
not the backend's traversal. Revalidate these interfaces on Hermes updates.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

SECRET_DIRS = {".ssh", ".aws", ".gnupg", ".kube", ".mozilla", "secrets"}
SECRET_FILES = {
    ".env", ".envrc", ".netrc", ".npmrc", ".pypirc", "auth.json",
    "credentials", ".credentials.json", ".bash_history", ".zsh_history",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
}
SECRET_GLOBS = (".env.*", "credentials.*", "*.key", "*.pem", "*.p12", "*.pfx")
SECRET_SUFFIXES = (
    ".config/gh/hosts.yml", ".docker/config.json", ".hermes/config.yaml",
    ".codex/config.toml",
)
SECRET_TREES = (".config/BraveSoftware", ".config/chromium", ".local/share/keyrings")
FILE_TOOLS = {"read_file", "search_files", "write_file", "patch"}
HEADER = re.compile(r"^(\*\*\*\s*(?:Update|Add|Delete)\s+File:\s*)(.+)$")
MOVE = re.compile(r"^(\*\*\*\s*Move\s+File:\s*)(.+?)\s*->\s*(.+)$")
_ERROR = "_eyragents_refusal"
_ready = False
OTHER_SESSION_ROOT = Path("/tmp/opencode")


def below(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def absolute(value: str, cwd: Path) -> Path:
    if not isinstance(value, str) or not value or any(ord(x) < 32 for x in value):
        raise ValueError("invalid path")
    path = Path(value).expanduser()
    # Retain '..' until realpath resolves preceding symlinks. abspath would
    # silently select a different file for link/../name.
    return path if path.is_absolute() else cwd / path


def secret(path: Path) -> bool:
    for candidate in (path, path.resolve()):
        parts = candidate.parts
        if any(part in SECRET_DIRS for part in parts):
            return True
        if any(part in SECRET_FILES or any(fnmatch.fnmatchcase(part, p) for p in SECRET_GLOBS)
               for part in parts):
            return True
        text = candidate.as_posix()
        if any(text.endswith("/" + suffix) for suffix in SECRET_SUFFIXES):
            return True
        if any("/" + tree + "/" in text + "/" for tree in SECRET_TREES):
            return True
    return False


def workspace(cwd: Path) -> Path:
    for directory in (cwd, *cwd.parents):
        if (directory / ".git").exists():
            return directory
    return cwd


def path_denial(path: Path, write: bool, home: Path) -> str | None:
    if secret(path):
        return "credential-shaped files and stores are not accessible"
    for candidate in (path, path.resolve()):
        if below(candidate, home / ".agents/hooks"):
            return "the installed commit gate is protected"
        if below(candidate, OTHER_SESSION_ROOT) or any(
            part.startswith("claude-") for part in candidate.parts[:3]
        ) and below(candidate, Path("/tmp")):
            return "other tools' session roots are protected"
        if write:
            if ".git" in candidate.parts:
                return "Git internals must be changed through the reviewed Git workflow"
            if below(candidate, home / ".hermes/plugins") or candidate == home / ".hermes/SOUL.md":
                return "managed policy and agent identity require an explicit configuration task"
            if below(candidate, home / ".agents"):
                return "shared guidance and skills are repository-owned; edit their authorized source checkout"
            if below(candidate, home / ".config/git"):
                return "Git configuration requires an explicit configuration task"
    if write and path.exists() and path.is_file() and path.stat().st_nlink != 1:
        return "native mutation of multiply-linked files requires ownership review"
    return None


def context(task_id: str) -> tuple[Path, Path]:
    from tools import file_tools
    if file_tools._terminal_env_type_for_task(task_id) != "local":
        raise ValueError("EyrAgents native path checks require the configured local backend")
    cwd = Path(file_tools._resolve_base_dir(task_id, container_paths=False))
    if not cwd.is_absolute() or not cwd.is_dir():
        raise ValueError("task cwd unavailable")
    return cwd.resolve(), Path.home().resolve()


def prepare(tool_name: str, args: dict, cwd: Path, home: Path) -> tuple[dict, list[Path], bool]:
    """Return normalized args and all file subjects, including both move ends."""
    args = dict(args)
    if _ERROR in args:
        raise ValueError("request normalization failed")
    paths = []
    write = tool_name in {"write_file", "patch"}

    def operand(value):
        path = absolute(value, cwd)
        denial = path_denial(path, write, home)
        if denial:
            raise ValueError(denial)
        paths.append(path.resolve())
        return str(path)

    if tool_name == "patch" and args.get("mode") == "patch":
        from tools.patch_parser import parse_v4a_patch
        patch = args.get("patch")
        if not isinstance(patch, str):
            raise ValueError("missing patch")
        operations, error = parse_v4a_patch(patch)
        if error or not operations:
            raise ValueError("unsupported patch")
        # Validate the parser's actual operation set before changing headers.
        for operation in operations:
            operand(operation.file_path)
            if operation.new_path:
                operand(operation.new_path)
        lines = []
        for line in patch.split("\n"):
            move = MOVE.match(line)
            header = HEADER.match(line)
            if move:
                line = move[1] + operand(move[2].strip()) + " -> " + operand(move[3].strip())
            elif header:
                line = header[1] + operand(header[2].strip())
            lines.append(line)
        args["patch"] = "\n".join(lines)
    elif tool_name in FILE_TOOLS:
        args["path"] = operand(args.get("path", "." if tool_name == "search_files" else ""))
    return args, paths, write


def command_denial(command: str, cwd: Path, home: Path) -> str | None:
    if not isinstance(command, str) or not command.strip() or "\0" in command:
        return "invalid terminal command"
    gate = home / ".agents/hooks/commit-gate"
    info = gate.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        return "installed commit-gate endpoint is unsafe"
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}
    result = subprocess.run([str(gate)], input=json.dumps(payload), text=True,
                            capture_output=True, cwd=cwd, timeout=8, check=False)
    if result.returncode != 0:
        return "commit-gate refused the command; use the commit skill and H's exact approval"
    if result.stdout.strip():
        return "commit-gate returned an unexpected response"
    # Named consequential forms, not a parser or arbitrary-script containment.
    normalized = command.replace("\\\n", " ")
    normalized = re.sub(r"['\"\\]", "", normalized)
    if re.search(r"(?:^|[\s;&|()])(?:\S*/)?(?:sudo|doas|pkexec|su)(?:\s|$)", normalized):
        return "privilege escalation is H-run"
    if re.search(r"\bgit\s+(?:(?:-[Cc]\s+\S+|--\S+)\s+)*(?:push|clean)\b", normalized):
        return "push and clean are H-run operations"
    return None


def inspect(tool_name: str, args: dict, task_id="default") -> tuple[dict, dict | None]:
    if not _ready:
        return args, {"action": "block", "message": "EyrAgents plugin initialization is incomplete"}
    try:
        cwd, home = context(task_id or "default")
        normalized, paths, write = prepare(tool_name, args, cwd, home)
        if tool_name == "terminal":
            workdir = absolute(args.get("workdir") or str(cwd), cwd).resolve()
            if not workdir.is_dir():
                raise ValueError("terminal working directory must exist")
            normalized["workdir"] = str(workdir)
            denial = command_denial(args.get("command"), workdir, home)
            if denial:
                return normalized, {"action": "block", "message": denial}
        if tool_name == "skill_manage":
            from hermes_constants import get_hermes_home
            from tools.skill_manager_tool import _find_skill, _resolve_skill_dir
            name = args.get("name", "")
            if not isinstance(name, str) or not name or "/" in name or "\\" in name:
                raise ValueError("invalid skill name")
            if (home / ".agents/skills" / name).exists():
                raise ValueError("local learning must not shadow a shared skill")
            local_path = get_hermes_home() / "skills"
            local = local_path.resolve()
            if local_path.is_symlink() or local != get_hermes_home().resolve() / "skills":
                raise ValueError("local learning root must not redirect into a shared library")
            if args.get("action") == "create":
                target = _resolve_skill_dir(args.get("name", ""), args.get("category"))
            else:
                entry = _find_skill(args.get("name", ""))
                target = Path(entry["path"]) if entry else local
            if not below(Path(target).resolve(), local):
                raise ValueError("shared/external skills are repository-owned; use an authorized source edit")
            if path_denial(Path(target), True, home):
                raise ValueError("protected learning target")
            # create/edit/default patch implicitly read or replace SKILL.md.
            # Checking only the directory misses a leaf symlink into shared
            # guidance or credential material followed by Hermes atomic writes.
            leaf = "SKILL.md" if args.get("action") in {"create", "edit"} else args.get("file_path") or "SKILL.md"
            attachment = absolute(leaf, Path(target))
            if not below(attachment.resolve(), Path(target).resolve()) or path_denial(attachment, True, home):
                raise ValueError("protected skill attachment")
        root = workspace(cwd)
        standing = [home / "Projects", home / ".agents/skills", Path("/tmp"), Path("/var/tmp"),
                    Path("/usr"), Path("/etc"), Path("/opt"), Path("/sys"), Path("/var/lib/pacman")]
        external = [p for p in paths if not below(p, root) and
                    (write or not any(below(p, r) for r in standing))]
        if external:
            subject = json.dumps([tool_name, sorted(str(p) for p in external)])
            return normalized, {"action": "approve", "message": "EyrAgents: confirm this external " +
                                ("write" if write else "read") + ": " + ", ".join(map(str, external)),
                                "rule_key": "eyragents:" + hashlib.sha256(subject.encode()).hexdigest()}
        return normalized, None
    except Exception:
        # Hook/middleware exceptions are fail-open upstream. Never raise here or
        # expose a command, patch body, credential-bearing value or parser error.
        return args, {"action": "block", "message": "EyrAgents: protected path/command or unverifiable tool input; check the access policy"}


def request(*, tool_name, args, task_id="default", **_):
    normalized, decision = inspect(tool_name, args, task_id)
    if decision and decision["action"] == "block":
        normalized = {**args, _ERROR: True}
    return {"args": normalized}


def pre_tool_call(*, tool_name, args, task_id="default", **_):
    return inspect(tool_name, args, task_id)[1]


def execute(*, tool_name, args, next_call, task_id="default", **_):
    normalized, decision = inspect(tool_name, args, task_id)
    if decision and decision["action"] == "block":
        return json.dumps({"error": decision["message"]})
    # The normal pre-hook owns native approval. This backstop prevents an
    # earlier plugin's approve directive from overriding our hard denials.
    return next_call(normalized)


def register(ctx):
    global _ready
    ctx.register_hook("pre_tool_call", pre_tool_call)
    ctx.register_middleware("tool_request", request)
    ctx.register_middleware("tool_execution", execute)
    try:
        from tools import file_tools
        original = file_tools.get_read_block_error

        def read_error(path):
            try:
                native = original(path)
                if native:
                    return native
                return path_denial(Path(path), False, Path.home().resolve())
            except Exception:
                return "EyrAgents: read target could not be checked"

        file_tools.get_read_block_error = read_error
        _ready = True
    except Exception:
        _ready = False
