#!/usr/bin/env bash
# Synthetic-only reconciliation tests. No host Codex configuration is read.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT
HOME="$TMP" python3 -B - "$ROOT/scripts/reconcile-codex-config.py" "$TMP" <<'PY'
import pathlib
import subprocess
import sys
import tomllib

script, scratch = sys.argv[1], pathlib.Path(sys.argv[2])
template = scratch / "template.toml"
host = scratch / "host.toml"
merged = scratch / "merged.toml"
template.write_text('model_reasoning_effort = "xhigh"\n[features]\nhooks = true\n[hooks]\nPreToolUse = []\n')
checks = 0

def run(mode, path=host):
    return subprocess.run([sys.executable, "-B", script, mode, str(template), str(path)], capture_output=True, text=True)

for delimiter in ('"""', "'''"):
    for header in ('[features]', '[[features]]', '[hooks.state."fixture"]', '["mcp\\u005fservers"."quoted.name"]'):
        text = ('service_tier = "fast"\nmodel = "retired"\n'
                '[features]\nhooks = false\n[hooks]\nPreToolUse = []\n'
                '[mcp_servers.fixture]\nnote = ' + delimiter + '\n'
                + header + '\nkeep = "ordinary synthetic material"\n' + delimiter + '\n'
                'args = [\n["nested", "array"],\n["more"]\n]\n'
                '[hooks.state."fixture:pre_tool_use:0:0"]\ntrusted_hash = "sha256:fixture"\n'
                '[[host_array]]\nname = "one"\n[[host_array]]\nname = "two"\n')
        host.write_text(text)
        before = tomllib.loads(text)
        result = run("merge")
        assert result.returncode == 0, result.stderr
        after = tomllib.loads(result.stdout)
        assert after["mcp_servers"] == before["mcp_servers"]
        assert after["host_array"] == before["host_array"]
        assert after["hooks"]["state"] == before["hooks"]["state"]
        assert after["features"] == {"hooks": True}
        assert after["service_tier"] == "fast" and "model" not in after
        assert delimiter + '\n' + header + '\nkeep = "ordinary synthetic material"\n' + delimiter in result.stdout
        merged.write_text(result.stdout)
        assert run("check", merged).returncode == 0
        assert run("merge", merged).stdout == result.stdout
        assert host.read_text() == text
        checks += 1

# Quoted/escaped headers are decoded by TOML itself, including closing brackets
# and comment characters within keys. Continuations stay byte-for-byte intact.
text = ('["mcp\\u005fservers"."quoted] # name"]\n'
        'value = """first\\\n    second\n[features]\nlast"""\n'
        '["hooks"."sta\\u0074e"."quoted] # name"]\ntrusted_hash = "sha256:fixture"\n')
host.write_text(text)
result = run("merge")
assert result.returncode == 0, result.stderr
after = tomllib.loads(result.stdout)
before = tomllib.loads(text)
assert after["mcp_servers"] == before["mcp_servers"] and after["hooks"]["state"] == before["hooks"]["state"]
assert text in result.stdout.replace('\n\n["hooks"', '\n["hooks"')
checks += 1

# Inline/dotted state under a replaced parent is not a section we can splice.
# Refuse it, rather than silently erase its host-owned trust records.
for text in ('[hooks]\nstate = { fixture = { trusted_hash = "sha256:fixture" } }\n',
             '[hooks]\nstate.fixture.trusted_hash = "sha256:fixture"\n',
             '[mcp_servers.fixture]\nnote = "unterminated\n'):
    host.write_text(text)
    result = run("merge")
    assert result.returncode == 2 and not result.stdout
    assert "sha256:fixture" not in result.stderr and "unterminated" not in result.stderr
    assert host.read_text() == text
    checks += 1

host.write_text('[broken\n')
assert run("check").returncode == 2
checks += 1
print(f"ok: Codex reconciliation ({checks} synthetic preservation/refusal cases)")
PY
