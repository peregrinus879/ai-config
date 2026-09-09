#!/usr/bin/env python3
"""Hermes policy and opaque config-preservation fixtures, no provider calls."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    result = types.ModuleType(name)
    exec(compile(path.read_bytes(), str(path), "exec"), result.__dict__)
    return result


class HermesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.repo = self.home / "Projects/work"
        self.repo.mkdir(parents=True)
        (self.repo / ".git").mkdir()
        self.profile = self.home / ".hermes"
        self.profile.mkdir(mode=0o700)
        self.config = self.profile / "config.yaml"
        self.env = {**os.environ, "HOME": str(self.home), "HERMES_HOME": str(self.profile),
                    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}

    def reconcile(self, mode="install", success=True):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/reconcile-hermes-config.py"),
                                 mode, str(ROOT)], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stderr)
        self.assertNotIn("private-fixture-value", result.stdout + result.stderr)
        return result

    def host(self, value):
        self.config.write_text(yaml.safe_dump(value), encoding="utf-8")
        self.config.chmod(0o600)

    def test_defaults_preservation_and_idempotence(self):
        original = {"providers": {"fixture": {"api_key": "private-fixture-value"}},
                    "skills": {"external_dirs": ["/team/skills"], "trusted_project_dirs": ["/work"]},
                    "plugins": {"enabled": ["other"]}, "display": {"compact": True}}
        self.host(original)
        soul = self.profile / "SOUL.md"
        soul.write_text("Hermes identity", encoding="utf-8")
        self.reconcile()
        data = yaml.safe_load(self.config.read_text())
        self.assertEqual(data["providers"], original["providers"])
        self.assertEqual(data["skills"]["trusted_project_dirs"], ["/work"])
        self.assertEqual(data["plugins"]["enabled"], ["other", "eyragents"])
        self.assertEqual(data["skills"]["external_dirs"], ["/team/skills", "~/.agents/skills"])
        self.assertEqual(data["model"]["default"], "gpt-6-astra")
        self.assertEqual(data["agent"]["reasoning_effort"], "xhigh")
        self.assertEqual(data["agent"]["coding_context"], "auto")
        self.assertNotIn("disabled_toolsets", data["agent"])
        self.assertTrue(data["memory"]["memory_enabled"])
        self.assertTrue(data["curator"]["enabled"])
        self.assertIn("Native learning", data["agent"]["environment_hint"])
        self.assertEqual(soul.read_text(), "Hermes identity")
        before = self.config.stat().st_mtime_ns
        self.reconcile()
        self.reconcile("check")
        self.assertEqual(self.config.stat().st_mtime_ns, before)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)

    def test_refuse_invalid_or_ambiguous_host_unchanged(self):
        for content in ("model: [private-fixture-value", "model: one\nmodel: two\n",
                        "thing: &anchor private-fixture-value\nother: *anchor\n"):
            self.config.write_text(content)
            self.config.chmod(0o600)
            self.reconcile(success=False)
            self.assertEqual(self.config.read_text(), content)
        for value in ({"plugins": {"disabled": ["eyragents"]}},
                      {"model": {"base_url": "https://example.invalid"}},
                      {"model": {"base_url": "https://chatgpt.com.example.invalid/backend-api/codex"}},
                      {"model": {"base_url": "https://chatgpt.com/backend-api/codex?route=other"}},
                      {"model": {"api_key": "private-fixture-value"}},
                      {"model": {"model": "different-model"}},
                      {"skills": {"external_dirs": "wrong-shape"}}):
            self.host(value)
            before = self.config.read_bytes()
            self.reconcile(success=False)
            self.assertEqual(self.config.read_bytes(), before)

    def test_native_model_wizard_endpoint_and_agreeing_alias_survive(self):
        self.reconcile()
        data = yaml.safe_load(self.config.read_text())
        data["model"]["base_url"] = "https://chatgpt.com/backend-api/codex"
        self.host(data)
        for alias in (False, True):
            if alias:
                data["model"]["model"] = "gpt-6-astra"
                self.host(data)
            before = self.config.read_bytes(), self.config.stat().st_mtime_ns
            self.reconcile("check")
            self.reconcile()
            self.assertEqual((self.config.read_bytes(), self.config.stat().st_mtime_ns), before)
        # Also exercise the YAML write path, not only the no-op early return.
        del data["plugins"]
        data["model"]["default"] = "host-drift"
        self.host(data)
        self.reconcile("check", success=False)
        self.reconcile()
        written = yaml.safe_load(self.config.read_text())
        self.assertEqual(written["model"]["base_url"], "https://chatgpt.com/backend-api/codex")
        self.assertEqual(written["model"]["model"], "gpt-6-astra")
        self.assertEqual(written["model"]["default"], "gpt-6-astra")
        self.assertEqual(written["plugins"]["enabled"], ["eyragents"])

    def test_refuse_linked_or_exposed_config(self):
        target = self.base / "keep.yaml"
        target.write_text("display: {}\n")
        self.config.symlink_to(target)
        self.reconcile(success=False)
        self.assertTrue(self.config.is_symlink())
        self.config.unlink()
        os.link(target, self.config)
        self.config.chmod(0o600)
        self.reconcile(success=False)
        self.config.unlink()
        self.host({})
        self.config.chmod(0o644)
        self.reconcile(success=False)

    def policy(self):
        policy = module("hermes_policy", ROOT / "hermes/.hermes/plugins/eyragents/__init__.py")
        policy._ready = True
        # The fake Hermes home lives in this OpenCode session's scratch. Model
        # the foreign-session root separately; the production deny stays fixed.
        policy.OTHER_SESSION_ROOT = self.base / "foreign-tool"
        policy.context = lambda task: (self.repo if task != "child" else self.repo / "sub", self.home)
        (self.repo / "sub").mkdir(exist_ok=True)
        return policy

    def test_path_inventory_and_actual_alias_targets(self):
        policy = self.policy()
        for name in (".env", ".env.custom", "secrets/a.txt", ".aws/anything", ".ssh/config",
                     "auth.json", "credentials.json", "id_ed25519", "private.pem",
                     ".config/gh/hosts.yml", ".hermes/config.yaml"):
            for tool in ("read_file", "write_file", "patch"):
                with self.subTest(name=name, tool=tool):
                    decision = policy.pre_tool_call(tool_name=tool, args={"path": name})
                    self.assertEqual(decision["action"], "block")
        for name in ("README.md", "example.env", "credentials-policy.md"):
            self.assertIsNone(policy.pre_tool_call(tool_name="read_file", args={"path": name}))
        (self.repo / "alias").symlink_to(self.repo / ".env.custom")
        self.assertEqual(policy.pre_tool_call(tool_name="read_file", args={"path": "alias"})["action"], "block")
        (self.repo / "dir-alias").symlink_to(self.home / ".ssh", target_is_directory=True)
        self.assertEqual(policy.pre_tool_call(tool_name="read_file", args={"path": "dir-alias/config"})["action"], "block")
        self.assertEqual(policy.pre_tool_call(tool_name="read_file", args={"path": str(policy.OTHER_SESSION_ROOT / "note")})["action"], "block")

    def test_normalization_task_cwd_and_external_asks(self):
        policy = self.policy()
        output = policy.request(tool_name="read_file", args={"path": "file.txt"}, task_id="child")
        self.assertEqual(output["args"]["path"], str(self.repo / "sub/file.txt"))
        self.assertIsNone(policy.pre_tool_call(tool_name="read_file", args={"path": str(self.home / "Projects/other/a") }))
        for tool in ("read_file", "write_file"):
            # A fake HOME below /tmp inherits its standing temp-read grant.
            # Use a non-granted synthetic path to exercise external reads.
            target = "/srv/eyragents-fixture/a" if tool == "read_file" else str(self.home / "Documents/a")
            decision = policy.pre_tool_call(tool_name=tool, args={"path": target})
            self.assertEqual(decision["action"], "approve")
            self.assertTrue(decision["rule_key"].startswith("eyragents:"))
        self.assertEqual(policy.pre_tool_call(tool_name="write_file", args={"path": ".git/config"})["action"], "block")

    def test_gate_and_fail_closed_dependencies(self):
        policy = self.policy()
        gate = self.home / ".agents/hooks/commit-gate"
        gate.parent.mkdir(parents=True)
        shutil.copy2(ROOT / "templates/hooks/commit-gate", gate)
        with patch.dict(os.environ, self.env):
            self.assertIsNone(policy.pre_tool_call(tool_name="terminal", args={"command": "git status"}))
            for command in ("git commit -m fixture", "git push", "sudo true", "git stash drop"):
                self.assertEqual(policy.pre_tool_call(tool_name="terminal", args={"command": command})["action"], "block")
            gate.unlink()
            self.assertEqual(policy.pre_tool_call(tool_name="terminal", args={"command": "git status"})["action"], "block")

    def test_symlink_parent_traversal_keeps_native_target(self):
        policy = self.policy()
        nested = self.repo / "actual/nested"
        nested.mkdir(parents=True)
        (self.repo / "link").symlink_to(nested, target_is_directory=True)
        output = policy.request(tool_name="write_file", args={"path": "link/../target.txt", "content": "new"})
        self.assertEqual(Path(output["args"]["path"]).resolve(), self.repo / "actual/target.txt")
        self.assertNotEqual(Path(output["args"]["path"]).resolve(), self.repo / "target.txt")

    def test_capability_preservation_and_execution_backstop(self):
        policy = self.policy()
        for name in ("execute_code", "delegate_task", "memory", "session_search", "web_search", "cronjob", "browser_navigate"):
            self.assertIsNone(policy.pre_tool_call(tool_name=name, args={}))
        called = []
        result = policy.execute(tool_name="write_file", args={"path": ".git/config"}, next_call=called.append)
        self.assertFalse(called)
        self.assertIn("error", json.loads(result))
        policy._ready = False
        self.assertEqual(policy.pre_tool_call(tool_name="read_file", args={"path": "README.md"})["action"], "block")

    def test_local_learning_and_shared_skill_ownership(self):
        policy = self.policy()
        local = self.profile / "skills"
        helpers = types.ModuleType("tools.skill_manager_tool")
        helpers._resolve_skill_dir = lambda name, category=None: local / name
        helpers._find_skill = lambda name: {"path": local / name if name == "learned" else self.home / ".agents/skills" / name}
        constants = types.ModuleType("hermes_constants")
        constants.get_hermes_home = lambda: self.profile
        with patch.dict(sys.modules, {"tools": types.ModuleType("tools"), "tools.skill_manager_tool": helpers, "hermes_constants": constants}):
            self.assertIsNone(policy.pre_tool_call(tool_name="skill_manage", args={"action": "create", "name": "learned"}))
            self.assertIsNone(policy.pre_tool_call(tool_name="skill_manage", args={"action": "edit", "name": "learned"}))
            self.assertEqual(policy.pre_tool_call(tool_name="skill_manage", args={"action": "edit", "name": "commit"})["action"], "block")
            (self.home / ".agents/skills/commit").mkdir(parents=True)
            self.assertEqual(policy.pre_tool_call(tool_name="skill_manage", args={"action": "create", "name": "commit"})["action"], "block")
            self.assertEqual(policy.pre_tool_call(tool_name="skill_manage", args={"action": "write_file", "name": "learned", "file_path": "../../plugins/a.py"})["action"], "block")
            (local / "learned").mkdir(parents=True)
            shared = self.repo / "shared-skill.md"
            shared.write_text("keep this shared skill")
            (local / "learned/SKILL.md").symlink_to(shared)
            for action in ("create", "edit", "patch"):
                self.assertEqual(policy.pre_tool_call(tool_name="skill_manage", args={"action": action, "name": "learned"})["action"], "block")
            for action in ("create", "edit"):
                self.assertEqual(policy.pre_tool_call(tool_name="skill_manage", args={"action": action, "name": "learned", "file_path": "references/ordinary.md"})["action"], "block")
            self.assertEqual(shared.read_text(), "keep this shared skill")


if __name__ == "__main__":
    unittest.main()
