#!/usr/bin/env python3
"""Opaque, preservation-first reconciliation of the default Hermes profile.

The template owns explicit leaves. Skill-library and plugin lists are additive;
all other host values retain their parsed semantics. YAML comments/formatting
are app-owned. Never print host values, parser exceptions, or merged contents.
Malformed, duplicate-key, aliased, linked, or unsafe configuration refuses.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
import stat
import sys
import tempfile

import yaml


class Refusal(Exception):
    pass


class UniqueLoader(yaml.SafeLoader):
    pass


def mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise Refusal("configuration requires unique string keys")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


def load(path: Path) -> dict:
    try:
        if path.stat().st_size > 2_000_000:
            raise Refusal("configuration exceeds the reconciliation size limit")
        text = path.read_text(encoding="utf-8")
        if any(isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None)
               for event in yaml.parse(text)):
            raise Refusal("YAML anchors and aliases require manual reconciliation")
        value = yaml.load(text, Loader=UniqueLoader)
        if value is None:
            value = {}
        if not isinstance(value, dict):
            raise Refusal("configuration must be a mapping")
        return value
    except (OSError, UnicodeError, yaml.YAMLError, TypeError, ValueError) as from_error:
        raise Refusal("configuration could not be parsed; original preserved") from from_error


ADDITIVE = {("skills", "external_dirs"), ("plugins", "enabled")}


def reconcile(host: dict, template: dict, prefix=()) -> dict:
    result = copy.deepcopy(host)
    for key, value in template.items():
        here = (*prefix, key)
        if isinstance(value, dict):
            original = result.get(key, {})
            if not isinstance(original, dict):
                # Hermes also accepts the old string model shorthand.
                if here == ("model",) and isinstance(original, str):
                    original = {}
                else:
                    raise Refusal("managed section has an incompatible host layout")
            result[key] = reconcile(original, value, here)
        elif here in ADDITIVE:
            original = result.get(key, [])
            if not isinstance(original, list) or not all(isinstance(x, str) for x in original):
                raise Refusal("managed list has an incompatible host layout")
            result[key] = original + [x for x in value if x not in original]
        else:
            result[key] = copy.deepcopy(value)
    return result


def safe_parent(path: Path) -> None:
    """Parents may be readable, but must be real, owned and not writable by others."""
    for parent in (path, *path.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022:
            # Root's normal /tmp sticky parent is allowed for isolated fixtures.
            if parent == Path("/tmp") and info.st_uid == 0 and info.st_mode & stat.S_ISVTX:
                continue
            raise Refusal("configuration parent is linked or writable by others")
        if info.st_uid not in (0, os.getuid()):
            raise Refusal("configuration parent has foreign ownership")


def run(mode: str, root: Path) -> None:
    home = Path(os.environ["HOME"])
    if not home.is_absolute() or home == Path("/") or home.resolve() != home:
        raise Refusal("HOME must be a real, absolute, non-root directory")
    safe_parent(home)
    profile = home / ".hermes"
    if os.environ.get("HERMES_HOME", str(profile)) != str(profile):
        raise Refusal("deployment manages only the default ~/.hermes profile")
    if profile.is_symlink():
        raise Refusal("Hermes profile must be a real directory")
    if not profile.exists():
        if mode == "check":
            raise Refusal("Hermes profile is missing")
        profile.mkdir(mode=0o700)
    safe_parent(profile)
    if profile.stat().st_uid != os.getuid():
        raise Refusal("Hermes profile must be owned by the caller")
    config = profile / "config.yaml"
    host = {}
    before = None
    if config.exists() or config.is_symlink():
        info = config.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
            raise Refusal("Hermes config must be an owned, single-link regular file")
        if info.st_mode & 0o077:
            raise Refusal("Hermes config must be private; review its permissions first")
        before = config.read_bytes()
        host = load(config)
    template = load(root / "templates/hermes/config.yaml")
    guidance = (root / "agents/.agents/shared-guidance.md").read_text(encoding="utf-8")
    template["agent"]["environment_hint"] = template["agent"]["environment_hint"].replace("@eyragents-guidance@", guidance)
    plugins = host.get("plugins", {})
    if isinstance(plugins, dict) and "eyragents" in plugins.get("disabled", []):
        raise Refusal("host explicitly disables the EyrAgents plugin; resolve that choice first")
    merged = reconcile(host, template)
    # Hermes 0.19 hermes_cli/auth.py DEFAULT_CODEX_BASE_URL and
    # _update_config_for_provider write this canonical endpoint even for
    # OAuth. Preserve that supported app state and an agreeing model alias;
    # refuse conflicting routes/credentials without printing or deleting them.
    # model.default/provider remain template-owned, unlike these host aliases.
    if isinstance(host.get("model"), dict):
        model = host["model"]
        if model.get("api_key"):
            raise Refusal("inline model.api_key requires an explicit provider reconciliation")
        if model.get("base_url") not in (None, "", "https://chatgpt.com/backend-api/codex"):
            raise Refusal("model.base_url conflicts with the managed Codex endpoint")
        if model.get("model") not in (None, "", template["model"]["default"]):
            raise Refusal("model.model conflicts with the managed model selection")
    if mode == "check":
        if before is None or merged != host:
            raise Refusal("Hermes managed configuration is missing or drifted; run make restow")
        print("ok:   Hermes managed leaves and additive libraries/plugins match")
        return
    if before is not None and merged == host:
        print("ok:   Hermes configuration already matches; host settings preserved")
        return
    content = yaml.safe_dump(merged, sort_keys=False, allow_unicode=True)
    if yaml.load(content, Loader=UniqueLoader) != merged:
        raise Refusal("YAML round-trip changed configuration semantics")
    fd, temporary = tempfile.mkstemp(prefix=".config.yaml.", dir=profile)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        # Refuse concurrent app rewrites instead of losing a new model/trust choice.
        if (config.exists() or config.is_symlink()) != (before is not None):
            raise Refusal("Hermes config changed during reconciliation")
        if before is not None and (config.is_symlink() or config.read_bytes() != before):
            raise Refusal("Hermes config changed during reconciliation")
        os.replace(temporary, config)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print("ok:   reconciled private Hermes configuration; host settings preserved")


if __name__ == "__main__":
    try:
        if len(sys.argv) != 3 or sys.argv[1] not in ("install", "check"):
            raise Refusal("usage: reconcile-hermes-config.py install|check REPOSITORY")
        run(sys.argv[1], Path(sys.argv[2]).resolve())
    except Refusal as error:
        print(f"FAIL: Hermes reconciliation: {error}", file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError, TypeError, KeyError):
        # Never leak a YAML excerpt, host value, or secret-bearing exception.
        print("FAIL: Hermes reconciliation refused; check layout, private permissions, provider overrides and managed settings", file=sys.stderr)
        sys.exit(1)
