#!/usr/bin/env python3
"""Reconcile a host-local Codex config with the portable template.

    reconcile-codex-config.py merge TEMPLATE [HOST]
    reconcile-codex-config.py check TEMPLATE HOST

The template owns every root-level key and every table it defines (auto_review,
features, hooks, agents, permissions). Everything else in HOST is host-only
state that Codex and the desktop app write (projects, marketplaces, plugins,
mcp_servers, shell_environment_policy, desktop, and any table the template does
not know) and is preserved in its original order, trimmed of surrounding blank
lines. One host-written subtable lives under a template-owned table: Codex
records each hook's trusted hash under `hooks.state` after a session, so that
subtable is preserved too and ignored when the owned tables are compared.
One root key is host-owned when the template leaves it out: Codex persists the
`/fast` choice as `service_tier`, so that line survives the merge and never
counts as drift, unless the host root is still exactly the root of a template
this repository once carried, read from Git history: the harness wrote that
root, so a retired key in it is residue and goes like any other. A kept line
carries a marker no template has, so a root the merge wrote never reads as a
template's. The rule is textual: a root written from an uncommitted template,
or edited since, keeps its host-owned key, which then needs the /fast toggle
or a deletion by hand, and a root rewritten to exactly a committed template's
text reads as residue. Outside a repository, or without git, nothing is
residue, and the lookup runs only when the host carries a host-owned key.

`merge` prints the reconciled config: the template text followed by the
host-only tables. `check` exits 0 when HOST already carries the template's
root keys and tables with the template's values and no root key the template
lacks, the host-owned key aside, 1 when it has drifted, and 2 when either file does not parse.
Section boundaries are recognized only at complete TOML prefixes, not inside
multiline strings or arrays. Before emitting any output, merge compares all
host-owned semantics as well as template ownership. Unsupported layouts refuse
without emitting replacement bytes; diagnostics never include config values.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

# Host-written subtables under template-owned tables: Codex stores each hook's
# trusted hash under hooks.state, keyed by config path and hook position.
HOST_SUBTABLES = {"hooks": {"state"}}
# Host-owned root keys when the template does not define them: Codex writes the
# per-session /fast choice here, and it is H's own, not drift.
HOST_ROOT_KEYS = {"service_tier"}
# A kept host-owned line ends with this marker, which no template carries, so a
# root the merge wrote with a host choice in it never matches a template root.
KEPT_MARKER = "# host choice, kept by the reconcile"


def host_subtable(parts: list[str]) -> bool:
    """True for a section a host writes under a template-owned table."""
    return len(parts) >= 2 and parts[1] in HOST_SUBTABLES.get(parts[0], set())


def owned_view(name: str, value):
    """The template-owned part of a host table, with host subtables removed."""
    if isinstance(value, dict) and name in HOST_SUBTABLES:
        return {key: item for key, item in value.items() if key not in HOST_SUBTABLES[name]}
    return value


def split_sections(text: str) -> tuple[str, list[tuple[list[str], str]]]:
    """Use the TOML parser to distinguish headers from multiline value content.

    Parsing prefixes costs more than a regex, but config files are small and
    this avoids a second, incomplete TOML lexer in a preservation boundary.
    """
    root: list[str] = []
    sections: list[tuple[list[str], list[str]]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        parts = []
        if line.lstrip().startswith("["):
            try:
                table = tomllib.loads(line)
                tomllib.loads(text[:offset])
            except tomllib.TOMLDecodeError:
                pass
            else:
                while table:
                    key, table = next(iter(table.items()))
                    parts.append(key)
                    if isinstance(table, list):
                        table = table[0]
        if parts:
            sections.append((parts, [line]))
        elif sections:
            sections[-1][1].append(line)
        else:
            root.append(line)
        offset += len(line)
    return "".join(root), [(parts, "".join(lines)) for parts, lines in sections]


def load(path: str) -> tuple[str, dict]:
    text = Path(path).read_text(encoding="utf-8")
    try:
        return text, tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        raise ValueError("input is not valid TOML") from None


def template_owned(template: dict) -> set[str]:
    return set(template)


def host_owned(key: str, value) -> bool:
    """True for a host-owned root key carrying the string value Codex writes."""
    return key in HOST_ROOT_KEYS and isinstance(value, str)


def exact(text: str) -> str:
    """Root text as written, under one newline policy for the host file and a historical blob, up to its trailing newlines."""
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def template_history(template_path: str) -> set[str]:
    """The root text of every past version of TEMPLATE in its repository, read in one batch; empty without git or a repository."""
    path = Path(template_path).resolve()
    try:
        root = subprocess.run(["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip()
        relative = path.relative_to(Path(root).resolve()).as_posix()
        # Paths are relative to the directory git runs in, so run from the root.
        git = ["git", "-C", root]
        revisions = subprocess.run([*git, "log", "--format=%H", "--", relative], capture_output=True, text=True, check=True).stdout.split()
        specs = "".join(f"{revision}:{relative}\n" for revision in revisions).encode()
        batch = subprocess.run([*git, "cat-file", "--batch"], input=specs, capture_output=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return set()
    roots = set()
    position = 0
    while position < len(batch):
        end = batch.index(b"\n", position)
        fields = batch[position:end].decode().split()
        position = end + 1
        if len(fields) == 3 and fields[1] == "blob":
            size = int(fields[2])
            roots.add(exact(split_sections(batch[position:position + size].decode("utf-8", "replace"))[0]))
            position += size + 1
        # "<revision>:<path> missing" names a version without the file.
    return roots


def template_residue(host_root: str, template_path: str) -> bool:
    """True when the host root is exactly the root of a past template: the harness wrote it, so no key in it is a host choice."""
    return exact(host_root) in template_history(template_path)


def host_root_lines(host: dict, owned: set[str]) -> list[str]:
    """The host-owned root keys the template does not define, re-emitted from their parsed values with the kept marker."""
    return [f"{key} = {json.dumps(host[key])}  {KEPT_MARKER}\n" for key in sorted(HOST_ROOT_KEYS)
            if key in host and key not in owned and host_owned(key, host[key])]


def merge(template_path: str, host_path: str | None) -> str:
    template_text, template = load(template_path)
    template_root, template_sections = split_sections(template_text)
    output = template_root
    host_sections: list[str] = []
    preserved = {}
    preserved_subtables = {}
    if host_path is not None:
        host_text, host = load(host_path)
        owned = template_owned(template)
        host_root, sections = split_sections(host_text)
        kept = host_root_lines(host, owned)
        if kept and template_residue(host_root, template_path):
            kept = []
        if kept:
            output = output.rstrip("\n") + "\n" + "".join(kept) + "\n"
        host_sections = [text for parts, text in sections if parts[0] not in owned or host_subtable(parts)]
        section_keys = {parts[0] for parts, _ in sections}
        preserved = {key: value for key, value in host.items() if key not in owned and key in section_keys}
        if kept:
            preserved.update({key: host[key] for key in HOST_ROOT_KEYS if key in host and key not in owned and host_owned(key, host[key])})
        preserved_subtables = {name: {key: value for key, value in host.get(name, {}).items() if key in keys}
                              for name, keys in HOST_SUBTABLES.items() if isinstance(host.get(name), dict)}
    output += "".join(text for _, text in template_sections)
    if not output.endswith("\n"):
        output += "\n"
    for text in host_sections:
        output += "\n" + text.strip("\n") + "\n"
    try:
        result = tomllib.loads(output)
    except tomllib.TOMLDecodeError:
        raise ValueError("reconciled config does not parse; host layout is unsupported") from None
    for key, value in template.items():
        if owned_view(key, result.get(key)) != value:
            raise ValueError("host state overrode template ownership")
    if set(result) != set(template) | set(preserved) or any(result.get(key) != value for key, value in preserved.items()) or any(
        not isinstance(result.get(name), dict) or any(result[name].get(key) != value for key, value in values.items())
        for name, values in preserved_subtables.items()
    ):
        raise ValueError("host-owned semantics would change; host layout is unsupported")
    return output


def check(template_path: str, host_path: str) -> int:
    _, template = load(template_path)
    host_text, host = load(host_path)
    drifted = [key for key, value in template.items() if owned_view(key, host.get(key)) != value]
    # The template owns the root, so a root key it no longer defines, such as a
    # retired model pin, is drift on its own; merge drops it. What merge keeps is
    # exactly the header sections and the host-owned keys, so an inline table at
    # the root is drift too, and so is a host-owned key in a root the harness wrote.
    host_root, sections = split_sections(host_text)
    section_keys = {parts[0] for parts, _ in sections}
    candidates = [key for key, value in host.items() if key not in template and host_owned(key, value)]
    residue = bool(candidates) and template_residue(host_root, template_path)
    retired = [key for key, value in host.items()
               if key not in template and key not in section_keys and not (host_owned(key, value) and not residue)]
    if drifted:
        print(f"reconcile-codex-config: template-owned keys drifted: {', '.join(drifted)}", file=sys.stderr)
    if retired:
        print(f"reconcile-codex-config: root keys the template retired: {', '.join(retired)}", file=sys.stderr)
    return 1 if drifted or retired else 0


def main() -> None:
    argv = sys.argv[1:]
    if len(argv) in (2, 3) and argv[0] == "merge":
        sys.stdout.write(merge(argv[1], argv[2] if len(argv) == 3 else None))
        return
    if len(argv) == 3 and argv[0] == "check":
        raise SystemExit(check(argv[1], argv[2]))
    print("usage: reconcile-codex-config.py merge TEMPLATE [HOST] | check TEMPLATE HOST", file=sys.stderr)
    raise SystemExit(64)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError):
        print("reconcile-codex-config: invalid input or unsupported layout; no replacement emitted", file=sys.stderr)
        raise SystemExit(2) from None
