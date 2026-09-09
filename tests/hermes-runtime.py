#!/usr/bin/env python3
"""Offline installed-Hermes dispatch check, run with its venv Python -I -B.

Fake HOME/profile, no model client, account, network, server or live session.
Confirms real plugin loading, middleware and native patch parsing.
"""
import json
import os
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

with tempfile.TemporaryDirectory(prefix="hermes-runtime-") as temporary:
    home = Path(temporary)
    profile = home / ".hermes"
    plugin = profile / "plugins/eyragents"
    plugin.mkdir(parents=True)
    for name in ("plugin.yaml", "__init__.py"):
        shutil.copyfile(ROOT / "hermes/.hermes/plugins/eyragents" / name, plugin / name)
    gate = home / ".agents/hooks/commit-gate"
    gate.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "templates/hooks/commit-gate", gate)
    (profile / "config.yaml").write_text("plugins:\n  enabled: [eyragents]\nterminal:\n  backend: local\n")
    path = os.environ.get("PATH", "/usr/bin:/bin")
    scratch = os.environ.get("TMPDIR", temporary)
    os.environ.clear()
    os.environ.update(HOME=str(home), HERMES_HOME=str(profile), PATH=path,
                      TMPDIR=scratch, HISTFILE="/dev/null", PYTHONDONTWRITEBYTECODE="1",
                      XDG_CONFIG_HOME=str(home / ".config"), XDG_DATA_HOME=str(home / ".local/share"),
                      XDG_CACHE_HOME=str(home / ".cache"), HERMES_MANAGED_DIR=str(home / "managed"),
                      GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
    os.chdir(home)
    from tools import file_tools
    from hermes_cli import plugins
    from hermes_cli.middleware import apply_tool_request_middleware, run_tool_execution_middleware
    plugins.discover_plugins()
    decision = plugins.resolve_pre_tool_block("read_file", {"path": str(home / ".ssh/config")})
    assert decision, "real plugin failed to deny a protected read"
    decision = plugins.resolve_pre_tool_block("terminal", {"command": "git commit -m fixture", "workdir": str(home)})
    assert decision, "real plugin failed to dispatch the commit gate"
    assert not plugins.resolve_pre_tool_block("read_file", {"path": "/usr/lib/os-release"})
    assert file_tools.get_read_block_error(Path("/nonexistent/fixture/.env.unusual"))
    request = apply_tool_request_middleware("read_file", {"path": "/usr/lib/os-release"})
    assert request.payload["path"] == "/usr/lib/os-release"
    for patch_text in (
        "*** Begin Patch\n***Add File: /tmp/eyragents-fixture/.git/config\n+bad\n*** End Patch",
        "***Move File: /tmp/eyragents-fixture/ordinary -> /tmp/eyragents-fixture/.env.unusual",
    ):
        request = apply_tool_request_middleware("patch", {"mode": "patch", "patch": patch_text})
        assert plugins.resolve_pre_tool_block("patch", request.payload), "native parser target escaped guard"
    called = []
    result = run_tool_execution_middleware("write_file", {"path": str(home / ".ssh/config"), "content": "fixture"},
                                           lambda args: called.append(args))
    assert not called and "error" in json.loads(result), "execution backstop failed"
    for name in ("memory", "delegate_task", "execute_code", "session_search", "web_search"):
        assert not plugins.resolve_pre_tool_block(name, {}), f"capability disabled: {name}"
    # Exercise the real public dispatcher, not only individual hook helpers.
    # The witness wraps the actual backend dispatch and never substitutes its
    # result. A denial must happen before that backend is called.
    from model_tools import handle_function_call
    from tools.registry import registry
    from tools.terminal_tool import cleanup_all_environments
    try:
        with patch.object(registry, "dispatch", wraps=registry.dispatch) as dispatch:
            for name, args in (
                ("read_file", {"path": "/nonexistent/eyragents-fixture/.env.unusual"}),
                ("terminal", {"command": "git commit -m fixture", "workdir": str(home)}),
            ):
                result = json.loads(handle_function_call(name, args, task_id="dispatch-fixture"))
                assert "error" in result and "EyrAgents" in result["error"], result
                dispatch.assert_not_called()
            result = json.loads(handle_function_call("read_file", {"path": "/usr/lib/os-release", "limit": 1},
                                                     task_id="dispatch-fixture"))
            assert "error" not in result and result.get("content"), result
            dispatch.assert_called_once()
    finally:
        cleanup_all_environments()
    print("ok:   installed Hermes discovery, middleware, patch parsing, and full native dispatch: protected calls block before backend; ordinary read executes")
