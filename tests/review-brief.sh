#!/usr/bin/env bash
# Hermetic brief checks. All HOME, Git writes and synthetic sensitive-path
# fixtures stay in a disposable child of caller TMPDIR or the ordinary tempfile
# fallback. Tested subprocesses get private TMPDIR; no reviewer or host gate.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec /usr/bin/python3 -I - "$ROOT" <<'PY'
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(sys.argv[1])
brief = root / "agents/.agents/skills/spar/scripts/review-brief"
scanner = brief.with_name("spar-payload-scan")
intent_text = "Outcome: fixture review\nNon-goals: deployment\nConstraints: offline\nAcceptance: bounded evidence\n"
cases = 0


def check(condition, message):
    if not condition:
        raise AssertionError(message)


with tempfile.TemporaryDirectory(prefix="review-brief.", dir=os.environ.get("TMPDIR") or None) as temporary:
    work = Path(temporary)
    check(work.parent.resolve() == Path(os.environ.get("TMPDIR") or tempfile.gettempdir()).resolve(),
          "outer fixture ignored explicit TMPDIR or ordinary tempfile fallback")
    check(work.stat().st_mode & 0o077 == 0, "tested subprocess scratch is not private")
    cases += 1
    home, scratch, repo, outside = [work / name for name in ("home", "session", "repo", "outside")]
    for directory in (home, scratch, repo, outside):
        directory.mkdir(mode=0o700)
    env = {**os.environ, "HOME": str(home), "TMPDIR": str(work), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0"}
    for name in list(env):
        if name.startswith("GIT_") and name not in ("GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL", "GIT_TERMINAL_PROMPT"):
            del env[name]
    for name in ("MAKEFLAGS", "MFLAGS", "MAKEFILES", "GNUMAKEFLAGS"):
        env.pop(name, None)

    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], env=env, stderr=subprocess.PIPE)

    git("init", "-q")
    (repo / "a.txt").write_text("one\n")
    # Large unchanged binary and text sources must not inherit artifact limits.
    asset = repo / "image.bin"
    asset.write_bytes(bytes(range(256)) * 4096)
    document = repo / "large-doc.txt"
    document.write_text("ordinary documentation\n" * 40000)
    (repo / "Makefile").write_text(
        "lint check:\n\t@if [ -n \"$$GATE_MARKER\" ]; then printf 'ran\\n' > \"$$GATE_MARKER\"; fi\n"
        "\t@printf 'gate passed\\n'\n"
        "broken:\n\t@printf 'gate failed\\n'; exit 7\n"
        "mutate:\n\t@printf 'changed\\n' >> a.txt\n"
        "generate:\n\t@printf 'generated\\n' > generated.txt\n"
        "stage-empty:\n\t@git add intent-empty.py\n"
        "race:\n\t@printf 'racer\\n' > \"$$RACE_OUT\"\n"
        "expose:\n\t@chmod 755 \"$$EXPOSE_SCRATCH\"\n"
        "forbidden:\n\t@printf 'ran\\n' > \"$$GATE_MARKER\"\n"
        "leak:\n\t@printf '%s%s\\n' 'sk-' 'SYNTHETIC0123456789ABCDEF'; exit 1\n"
    )
    git("add", "a.txt", "Makefile", "image.bin", "large-doc.txt")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "first")
    (repo / "a.txt").write_text("one\ntwo\n")
    git("add", "a.txt")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "second")
    (repo / "a.txt").write_text("one\ntwo\nthree\n")
    git("add", "a.txt")
    intent = scratch / "intent.md"
    intent.write_text(intent_text)
    output = scratch / "brief.md"

    def run(expected=0, *args, intent_path=intent, output_path=output, overrides=None, cwd=repo):
        result = subprocess.run(
            [str(brief), "--intent", str(intent_path), "--out", str(output_path), *args],
            cwd=cwd, env={**env, **(overrides or {})}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
        )
        check(result.returncode == expected,
              f"expected exit {expected}, got {result.returncode}: {result.stderr.decode()}")
        return output_path.read_text() if output_path.is_file() else "", result

    def fresh():
        if output.exists():
            output.unlink()

    def snapshot():
        return {str(path.relative_to(repo)): (path.stat().st_mode, hashlib.sha256(path.read_bytes()).hexdigest())
                for path in repo.rglob("*") if path.is_file()}

    before = snapshot()
    marker = scratch / "gate-marker"
    text, _ = run(0, "--plan", overrides={"GATE_MARKER": str(marker)})
    check(snapshot() == before, "plan changed repository contents, modes or Git metadata")
    check(not marker.exists(), "plan executed default gates")
    check("skipped by --plan (read-only)" in text and "Stat:" not in text
          and "diff below was collected" not in text and "## Change: none, plan review" in text,
          "plan ran gates or claimed a collected diff")
    check("reuse: disabled" in text, "plan pretended to provide gate evidence")
    check("Plan observation scope: HEAD and read-only index entries/flags only" in text
          and "tracked worktree SHA-256:" not in text and "source-state SHA-256:" not in text,
          "plan asserted source observations it did not collect")
    cases += 1
    fresh()
    run(64, "--plan", "--gate", "forbidden", overrides={"GATE_MARKER": str(marker)})
    check(not marker.exists() and not output.exists() and snapshot() == before, "plan gate conflict had side effects")
    run(64, "--plan", output_path=repo / "plan.md")
    check(snapshot() == before, "plan output wrote inside repository")
    cases += 2

    text, _ = run()
    check(git("rev-parse", "HEAD").decode().strip() in text, "full HEAD missing")
    for part in ("index entries SHA-256", "tracked worktree SHA-256", "source-state SHA-256",
                 "### Before gates", "### After gates", "observed fingerprints unchanged",
                 "conditional evidence only", "- lint: ok (make exit 0)", "- check: ok (make exit 0)",
                 "-- lint`", "-- check`", "runtime/environment", "intent/checkpoint", "verified separately"):
        check(part in text, "missing evidence: " + part)
    check("superset" not in text and "which equals" not in text, "brief overclaimed tree equality")
    check(snapshot() == before, "fingerprinting wrote Git objects/index/source")
    check(output.stat().st_size < 16384 and "diff --git a/image.bin" not in text
          and "diff --git a/large-doc.txt" not in text, "unchanged large sources bloated small diff")
    accepted = subprocess.run([str(scanner), "outbound", "--root", str(repo), "--scratch-root", str(work),
                               "--", str(output)], input=b"Review.", stdout=subprocess.DEVNULL, env=env)
    check(accepted.returncode == 0, "new brief fails current outbound artifact API")
    cases += 1
    fresh()

    # No plan source opens, proved using a FIFO in place of a tracked asset.
    asset.unlink()
    os.mkfifo(asset)
    text, _ = run(0, "--plan")
    check("worktree observation: not collected" in text, "plan attempted to hash tracked FIFO")
    fresh()
    run(2, "--no-gates")
    check(not output.exists(), "source streaming opened an unsupported FIFO")
    asset.unlink()
    asset.write_bytes(bytes(range(256)) * 4096)
    cases += 2

    # The streamed digest must cover the end of a file beyond ARTIFACT_MAX.
    text, _ = run()
    fresh()
    with asset.open("r+b") as stream:
        stream.seek(-1, os.SEEK_END)
        stream.write(b"x")
    later, _ = run()
    worktree_hashes = lambda body: [line for line in body.splitlines() if line.startswith("- tracked worktree SHA-256:")]
    check(worktree_hashes(text) != worktree_hashes(later), "large source hashing stopped at artifact limit")
    fresh()
    asset.write_bytes(bytes(range(256)) * 4096)
    cases += 1

    oversized_intent = scratch / "oversized-intent.md"
    oversized_intent.write_text(intent_text + "ordinary prose\n" * 40000)
    run(2, "--plan", intent_path=oversized_intent)
    check(not output.exists(), "large source support removed intent size limit")
    near_limit = scratch / "near-limit-intent.md"
    near_limit.write_text(intent_text + "x" * (512 * 1024 - len(intent_text) - 100))
    run(2, "--plan", intent_path=near_limit)
    check(not output.exists(), "large source support removed final artifact size limit")
    cases += 2

    text, result = run(1, "--gate", "lint", "--gate", "broken")
    for part in ("## Intent", intent_text.strip(), "## Repository state\n\n- head: ", " second", "## Gates",
                 "execution scope when run: working checkout, not an attestation of the index",
                 "- lint: ok", "- broken: FAIL (make exit 2)", "gate failed", "reuse: disabled: failed gates",
                 "## Change: staged index against HEAD", "+three"):
        check(part in text, "failed gate diagnostic/evidence missing: " + part)
    check(result.stdout.startswith(b"brief: ") and result.stdout.endswith(b"staged index against HEAD)\n"),
          "brief did not report the retained artifact")
    cases += 1
    fresh()
    text, _ = run(1, "--gate", "mutate")
    check("source-state comparison: CHANGED" in text and "reuse: disabled" in text,
          "tracked drift falsely reusable")
    (repo / "a.txt").write_text("one\ntwo\nthree\n")
    cases += 1
    fresh()
    text, _ = run(1, "--gate", "generate")
    check("source-state comparison: CHANGED" in text and "untracked contents were not read or hashed" in text,
          "new untracked source omitted")
    (repo / "generated.txt").unlink()
    cases += 1
    fresh()

    # A synthetic sensitive FIFO must never be opened while counting untracked inputs.
    sensitive = repo / ".env"
    os.mkfifo(sensitive)
    untracked = repo / "untracked.txt"
    untracked.write_text("untracked source\n")
    text, _ = run()
    check("untracked count: 1" in text and "reuse: disabled" in text and "NOT their contents" in text,
          "untracked limitations not explicit")
    cases += 1
    fresh()
    untracked.write_text("different untracked bytes\n")
    later, _ = run()
    fingerprints = lambda body: [line for line in body.splitlines() if line.startswith("- source-state SHA-256:")]
    check(fingerprints(text) == fingerprints(later) and "reuse: disabled" in later,
          "untracked content exclusion must never imply reusable evidence")
    fresh()
    cases += 1
    _, result = run(2, "--plan", intent_path=sensitive)
    check(not output.exists() and b"before content access" in result.stderr, "sensitive intent was opened")
    alias = scratch / "alias.md"
    alias.symlink_to(sensitive)
    run(2, "--plan", intent_path=alias)
    check(not output.exists(), "resolved sensitive intent accepted")
    alias.unlink()
    sensitive.unlink()
    untracked.unlink()
    cases += 2

    safe_link = scratch / "linked-intent.md"
    safe_link.symlink_to(intent)
    run(0, "--plan", intent_path=safe_link)
    fresh()
    hardlink = scratch / "hard-intent.md"
    os.link(intent, hardlink)
    run(2, "--plan", intent_path=hardlink)
    check(not output.exists(), "hard-linked intent accepted")
    hardlink.unlink()
    cases += 2

    outside_intent = outside / "intent.md"
    outside_intent.write_text(intent_text)
    run(2, "--plan", intent_path=outside_intent, overrides={"TMPDIR": str(scratch)})
    run(2, "--plan", output_path=outside / "brief.md", overrides={"TMPDIR": str(scratch)})
    alias.symlink_to(outside_intent)
    run(2, "--plan", intent_path=alias, overrides={"TMPDIR": str(scratch)})
    alias.unlink()
    scratch.chmod(0o755)
    run(2, "--plan", overrides={"TMPDIR": str(scratch)})
    scratch.chmod(0o700)
    run(2, "--plan", overrides={"TMPDIR": "/tmp/opencode"})
    run(2, "--plan", overrides={"TMPDIR": ""})
    check(not output.exists() and not (outside / "brief.md").exists(), "outside/private-root refusal left artifact")
    cases += 6
    outside_output = Path("/proc/eyragents-outside-brief.md")
    run(2, "--no-gates", output_path=outside_output)
    check(not outside_output.exists(), "change review wrote outside repository and temp roots")
    cases += 1

    # Output refusal precedes even a safe intent's content read.
    fifo_intent = scratch / "intent-pipe.md"
    os.mkfifo(fifo_intent)
    _, result = run(2, "--plan", intent_path=fifo_intent, output_path=repo / ".git" / "brief.md")
    check(b"before content access" in result.stderr and not (repo / ".git" / "brief.md").exists(),
          "Git-internal output was written or validation happened after intent read")
    cases += 1
    output.write_text("existing\n")
    run(64, "--plan")
    check(output.read_text() == "existing\n", "existing file clobbered")
    fresh()
    output.symlink_to(scratch / "missing.md")
    run(64, "--plan")
    check(output.is_symlink() and not (scratch / "missing.md").exists(), "dangling output link clobbered")
    output.unlink()
    cases += 2
    text, _ = run(64, "--gate", "race", overrides={"RACE_OUT": str(output)})
    check(text == "racer\n", "raced output clobbered")
    fresh()
    cases += 1
    run(2, "--gate", "expose", overrides={"EXPOSE_SCRATCH": str(work)})
    check(not output.exists(), "output accepted scratch that lost its private mode during gates")
    work.chmod(0o700)
    cases += 1

    for args in (("--gate=--eval=bad",), ("--gate", "NAME=value"), ("--gate", "lint check"),
                 ("--no-gates", "--gate", "lint"), ("--staged", "--worktree"), ("--plan", "--range", "HEAD~1..HEAD")):
        run(64, *args)
        check(not output.exists(), "usage conflict wrote an artifact")
        cases += 1
    text, _ = run(0, "--no-gates")
    check("unverified, skipped by --no-gates" in text and "never gate evidence" in text, "no-gates implied verification")
    fresh()
    cases += 1
    text, _ = run(0, "--range", "HEAD~1..HEAD", "--no-gates")
    check("## Change: commits HEAD~1..HEAD" in text and " second" in text and "+two" in text
          and "+three" not in text and "skipped by --no-gates" in text, "range included wrong tree or gate evidence")
    fresh()
    text, _ = run(1, "--worktree", "--gate", "lint", "--gate", "absent")
    check("## Change: working tree against HEAD" in text and "+three" in text and "- lint: ok" in text
          and "- absent: FAIL (make exit 2)" in text and "- check:" not in text,
          "worktree diff, explicit gate selection or missing-target failure wrong")
    fresh()
    cases += 2

    run(2, "--gate", "leak")
    check(not output.exists(), "scanner refusal retained secret-shaped gate diagnostic")
    cases += 1
    leak = scratch / "leaky-intent.md"
    leak.write_text(intent_text + "sk-" + "SYNTHETIC0123456789ABCDEF\n")
    run(2, "--plan", intent_path=leak)
    check(not output.exists(), "scanner refusal retained intent artifact")
    cases += 1
    leak.write_text(intent_text + "OPENAI_API" + "_KEY=sk-" + "SYNTHETIC0123456789ABCDEF\n")
    run(2, "--no-gates", intent_path=leak)
    check(not output.exists(), "scanner refusal retained credential-assignment intent artifact")
    cases += 1
    thin = scratch / "thin-intent.md"
    thin.write_text("Outcome: x\nConstraints: y\n")
    _, result = run(64, intent_path=thin)
    check(not output.exists() and b"Non-goals Acceptance" in result.stderr,
          "incomplete intent accepted or missing required fields not reported")
    cases += 1

    # Replace an already tracked safe path with a sensitive link/hardlink; no diff
    # or fingerprint may read its target before path/metadata refusal.
    source = repo / "a.txt"
    saved = source.read_bytes()
    source.unlink()
    sensitive.write_text(intent_text)
    source.symlink_to(sensitive)
    run(2, "--no-gates")
    check(not output.exists(), "tracked sensitive link accepted")
    source.unlink()
    os.link(sensitive, source)
    run(2, "--no-gates")
    check(not output.exists(), "tracked hardlink accepted")
    source.unlink()
    source.write_bytes(saved)
    sensitive.unlink()
    cases += 2

    source.unlink()
    source.symlink_to("Makefile")
    text, _ = run(0, "--no-gates")
    check("unattested symlink/gitlink count: 1" in text and "symlink targets or gitlink contents" in text,
          "source symlink target treated as attested")
    fresh()
    source.unlink()
    source.write_bytes(saved)
    cases += 1

    # Index flag changes and assume-unchanged edits must not hide behind Git's
    # fast stat/index optimizations. All updates here are fixture-only.
    text, _ = run()
    fresh()
    git("update-index", "--assume-unchanged", "a.txt")
    later, _ = run()
    check(fingerprints(text) != fingerprints(later), "index flags omitted from source state")
    fresh()
    source.write_bytes(saved + b"hidden worktree change\n")
    changed, _ = run()
    check(fingerprints(later) != fingerprints(changed), "assume-unchanged hid raw source content drift")
    fresh()
    source.write_bytes(saved)
    git("update-index", "--no-assume-unchanged", "a.txt")
    cases += 2
    empty = repo / "intent-empty.py"
    empty.write_text("")
    git("add", "--intent-to-add", empty.name)
    entries, flags = git("ls-files", "--stage", "-z"), git("ls-files", "-v", "-z")
    text, _ = run(1, "--gate", "stage-empty")
    check(entries == git("ls-files", "--stage", "-z") and flags == git("ls-files", "-v", "-z"),
          "fixture must change only hidden intent-to-add state")
    check("source-state comparison: CHANGED" in text and "reuse: disabled" in text,
          "intent-to-add transition left an obsolete staged diff reusable")
    fresh()
    git("rm", "--cached", empty.name)
    empty.unlink()
    cases += 1
    git("restore", "--staged", "a.txt")
    _, result = run(3, "--no-gates")
    check(not output.exists() and b"nothing is staged" in result.stderr, "empty staged change accepted")
    git("add", "a.txt")
    cases += 1

    # Repository output remains supported outside plan mode, but cannot attest
    # an unchanged tree after creating itself. Relative paths use caller cwd.
    (repo / "sub").mkdir()
    (repo / "sub" / "intent.md").write_text(intent_text)
    repo_output = repo / "sub" / "brief.md"
    run(0, "--no-gates", cwd=repo / "sub", intent_path=Path("intent.md"), output_path=Path("brief.md"))
    check(repo_output.exists() and "output creates a repository file" in repo_output.read_text(), "repository output scope wrong")
    _, result = run(64, "--no-gates", cwd=repo / "sub", intent_path=Path("intent.md"), output_path=Path("brief.md"))
    check(b"written as a new file only" in result.stderr, "repository output no-clobber diagnostic missing")
    cases += 1

    # A plan can observe metadata even with inherited sensitive source paths.
    # Change modes remain conservative: no attempt to prove secret-byte equality.
    sensitive.write_text("ordinary synthetic fixture\n")
    git("add", ".env")
    _, result = run(2, "--no-gates")
    check(not output.exists() and b"before content access" in result.stderr,
          "newly staged sensitive source reached patch inclusion")
    cases += 1
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "synthetic path fixture")
    source.write_bytes(saved + b"four\n")
    git("add", "a.txt")
    text, _ = run(0, "--plan")
    check("tracked worktree SHA-256:" not in text and "reuse: disabled" in text,
          "plan attested inherited sensitive sources")
    fresh()
    _, result = run(2, "--no-gates")
    check(not output.exists() and b"before content access" in result.stderr,
          "change review attempted to read inherited sensitive source")
    cases += 2
    sensitive.write_text("changed synthetic fixture\n")
    git("add", ".env")
    _, result = run(2, "--no-gates")
    check(not output.exists() and b"before content access" in result.stderr,
          "changed sensitive source reached patch inclusion")
    cases += 1
    sensitive.unlink()
    os.mkfifo(sensitive)
    run(0, "--plan")
    fresh()
    cases += 1
    check(not list(work.rglob(".review-brief.*")), "brief left a draft behind")

print(f"ok: review-brief ({cases} hermetic evidence, refusal and no-clobber cases)")
PY
