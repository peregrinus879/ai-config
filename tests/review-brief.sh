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
import re
import stat
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
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0", "HISTFILE": str(home / "history"),
           "XDG_CONFIG_HOME": str(home / "config"), "XDG_CACHE_HOME": str(home / "cache"),
           "XDG_DATA_HOME": str(home / "data"), "XDG_STATE_HOME": str(home / "state")}
    for name in list(env):
        if name.startswith("GIT_") and name not in ("GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL", "GIT_TERMINAL_PROMPT"):
            del env[name]
    for name in ("MAKEFLAGS", "MFLAGS", "MAKEFILES", "GNUMAKEFLAGS"):
        env.pop(name, None)

    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], env=env, stderr=subprocess.PIPE)

    git("init", "-q")
    (repo / "a.txt").write_text("one\n")
    blocked = repo / "blocked"
    blocked.mkdir(mode=0o700)
    blocked_source = blocked / "old.txt"
    blocked_source.write_text("old tracked source\n")
    # Large unchanged binary and text sources must not inherit artifact limits.
    asset = repo / "image.bin"
    asset.write_bytes(bytes(range(256)) * 4096)
    document = repo / "large-doc.txt"
    document.write_text("ordinary documentation\n" * 40000)
    (repo / "Makefile").write_text(
        ".PHONY: shared lint check broken after-broken\n"
        "shared:\n\t@if [ -n \"$$BATCH_MARKER\" ]; then printf 'shared\\n' >> \"$$BATCH_MARKER\"; fi\n"
        "lint check: shared\n\t@if [ -n \"$$GATE_MARKER\" ]; then printf 'ran\\n' > \"$$GATE_MARKER\"; fi\n"
        "\t@if [ -n \"$$BATCH_MARKER\" ]; then printf '%s\\n' '$@' >> \"$$BATCH_MARKER\"; fi\n"
        "\t@printf 'gate passed\\n'\n"
        "broken:\n\t@printf 'gate failed\\n'; exit 7\n"
        "after-broken:\n\t@printf 'unexpected\\n' >> \"$$BATCH_MARKER\"\n"
        "mutate:\n\t@printf 'changed\\n' >> a.txt\n"
        "generate:\n\t@printf 'generated\\n' > generated.txt\n"
        "stage-empty:\n\t@git add intent-empty.py\n"
        "race:\n\t@printf 'racer\\n' > \"$$RACE_OUT\"\n"
        "expose:\n\t@chmod 755 \"$$EXPOSE_SCRATCH\"\n"
        "forbidden:\n\t@printf 'ran\\n' > \"$$GATE_MARKER\"\n"
        "leak:\n\t@printf '%s%s\\n' 'sk-' 'SYNTHETIC0123456789ABCDEF'; exit 1\n"
    )
    git("add", "a.txt", "Makefile", "image.bin", "large-doc.txt", "blocked/old.txt")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "first")
    (repo / "a.txt").write_text("one\ntwo\n")
    git("add", "a.txt")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "second")
    (repo / "a.txt").write_text("one\ntwo\nthree\n")
    git("add", "a.txt")
    (repo / ".git/info/exclude").write_text("/blocked/\n")
    intent = scratch / "intent.md"
    intent.write_text(intent_text)
    output = scratch / "brief.md"

    def run(expected=0, *args, intent_path=intent, output_path=output, overrides=None, cwd=repo):
        result = subprocess.run(
            [str(brief), "--intent", str(intent_path), "--out", str(output_path), *args],
            cwd=cwd, env={name: value for name, value in {**env, **(overrides or {})}.items() if value is not None},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
        )
        check(result.returncode == expected,
              f"expected exit {expected}, got {result.returncode}: {result.stderr.decode()}")
        return output_path.read_text() if output_path.is_file() else "", result

    def fresh():
        if output.exists():
            output.unlink()

    def snapshot(base=repo, exclude=None):
        observed = {}
        for path in base.rglob("*"):
            if path == exclude:
                continue
            metadata = path.lstat()
            content = (hashlib.sha256(path.read_bytes()).hexdigest() if stat.S_ISREG(metadata.st_mode)
                       else os.readlink(path) if stat.S_ISLNK(metadata.st_mode) else None)
            observed[str(path.relative_to(base))] = (metadata.st_mode, metadata.st_uid, metadata.st_gid,
                                                   metadata.st_nlink, content)
        return observed

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
                 "conditional evidence only", "- combined gates: ok (make exit 0)",
                 "-- lint check`", "runtime/environment", "intent/checkpoint", "verified separately",
                 "raw index/worktree agreement: MATCH", "raw index/worktree mismatch count: 0"):
        check(part in text, "missing evidence: " + part)
    check(text.count("- command:") == 1 and "- lint:" not in text and "- check:" not in text,
          "default gates claimed separate invocations or target results")
    check("superset" not in text and "which equals" not in text, "brief overclaimed tree equality")
    check(snapshot() == before, "fingerprinting wrote Git objects/index/source")
    check(output.stat().st_size < 16384 and "diff --git a/image.bin" not in text
          and "diff --git a/large-doc.txt" not in text, "unchanged large sources bloated small diff")
    accepted = subprocess.run([str(scanner), "outbound", "--root", str(repo), "--scratch-root", str(work),
                               "--", str(output)], input=b"Review.", stdout=subprocess.DEVNULL, env=env)
    check(accepted.returncode == 0, "new brief fails current outbound artifact API")
    cases += 1
    fresh()

    # Shared phony prerequisites run once, and literal requested goal order survives.
    batch_marker = scratch / "batch-marker"
    for targets in (("lint", "check"), ("check", "lint", "check")):
        arguments = [argument for target in targets for argument in ("--gate", target)]
        text, _ = run(0, *arguments, overrides={"BATCH_MARKER": str(batch_marker)})
        check(batch_marker.read_text().splitlines() == ["shared", *dict.fromkeys(targets)],
              "gates repeated a shared prerequisite or reordered Make goals")
        check(text.count("- command:") == 1 and "-- " + " ".join(targets) + "`" in text
              and "no individual target results asserted" in text, "combined command misreported")
        batch_marker.unlink()
        fresh()
        cases += 1
    text, _ = run(1, "--gate", "lint", "--gate", "broken", "--gate", "after-broken",
                  overrides={"BATCH_MARKER": str(batch_marker)})
    check(batch_marker.read_text().splitlines() == ["shared", "lint"], "Make continued after failed goal")
    check("-- lint broken after-broken`" in text and "combined gates: FAIL (make exit 2)" in text
          and "- lint: ok" not in text and "- after-broken:" not in text, "combined failure fabricated target outcomes")
    batch_marker.unlink()
    fresh()
    cases += 1

    # Pass inherited controls into the collector, not just a scrubbed fixture Make.
    before_controls = snapshot()
    for name in ("MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS"):
        for value in ("-n", "-i", "-k", "-j2", " "):
            _, result = run(64, "--gate", "lint", "--gate", "broken", "--gate", "after-broken",
                            overrides={name: value, "GATE_MARKER": str(marker), "BATCH_MARKER": str(batch_marker)})
            check(b"nonempty inherited Make controls" in result.stderr and name.encode() in result.stderr
                  and not output.exists() and not marker.exists() and not batch_marker.exists()
                  and snapshot() == before_controls, "inherited Make controls ran recipes or claimed success")
            cases += 1
    inherited_makefile = scratch / "inherited.mk"
    inherited_makefile.write_text("$(shell printf 'ran\\n' > \"$(GATE_MARKER)\")\n")
    _, result = run(64, overrides={"MAKEFILES": str(inherited_makefile), "GATE_MARKER": str(marker)})
    check(b"MAKEFILES" in result.stderr and not output.exists() and not marker.exists()
          and snapshot() == before_controls, "inherited Makefile was parsed before refusal")
    cases += 1
    inherited_controls = {"MAKEFLAGS": "-n", "MFLAGS": "-i", "GNUMAKEFLAGS": "-j2",
                          "MAKEFILES": str(inherited_makefile), "GATE_MARKER": str(marker)}
    for skipped in ("--plan", "--no-gates"):
        text, _ = run(0, skipped, overrides=inherited_controls)
        check("skipped by " + skipped in text and not marker.exists() and snapshot() == before_controls,
              "no-gate mode interpreted inherited Make controls")
        fresh()
        cases += 1
    text, _ = run(0, "--gate", "lint", overrides={**dict.fromkeys(
        ("MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS", "MAKEFILES"), ""), "GATE_MARKER": str(marker)})
    check("combined gates: ok" in text and marker.exists() and "Makefile dependencies determine recipe order" in text,
          "empty inherited controls refused or normal gate order was misrepresented")
    marker.unlink()
    fresh()
    cases += 1

    check(os.geteuid() != 0, "inaccessible-parent evidence requires a non-root test user")
    git("rm", "--cached", "blocked/old.txt")
    for present in (True, False):
        if not present:
            blocked_source.unlink()
        before_blocked = snapshot()
        blocked.chmod(0o000)
        try:
            try:
                blocked_source.lstat()
            except PermissionError:
                pass
            else:
                raise AssertionError("fixture did not produce a real permission-denied lookup")
            check(not os.path.lexists(blocked_source), "fixture did not reproduce lexists EACCES ambiguity")
            _, result = run(3, "--no-gates")
            check(not output.exists() and b"source path lookup failed; absence cannot be established" in result.stderr,
                  "inaccessible staged deletion was treated as proved absence")
            if present:
                text, _ = run(0, "--plan", overrides=inherited_controls)
                check("worktree observation: not collected" in text and not marker.exists(),
                      "plan inspected inaccessible source or executed inherited Make controls")
                fresh()
                cases += 1
        finally:
            blocked.chmod(0o700)
        check(snapshot() == before_blocked, "lookup refusal changed source or Git state")
        if not present:
            blocked_source.write_text("old tracked source\n")
        cases += 1
    git("restore", "--staged", "--", "blocked/old.txt")
    blocked.chmod(0o000)
    try:
        _, result = run(3, "--no-gates")
        check(not output.exists() and b"absence cannot be established" in result.stderr,
              "inaccessible indexed source was treated as missing")
    finally:
        blocked.chmod(0o700)
    cases += 1

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
                 "-- lint broken`", "- combined gates: FAIL (make exit 2)", "gate failed", "reuse: disabled: failed gates",
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
    check("## Change: working tree against HEAD" in text and "+three" in text and "-- lint absent`" in text
          and "- combined gates: FAIL (make exit 2)" in text and "- check:" not in text,
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
    check("unattested tracked path count: 1" in text and "raw index/worktree agreement: MISMATCH" in text
          and "symlink targets or gitlink contents" in text, "unstaged file-to-link type change treated as attested")
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
    check(fingerprints(later) != fingerprints(changed) and "raw index/worktree agreement: MISMATCH" in changed
          and "reuse: disabled" in changed, "assume-unchanged hid raw source content drift or mismatch")
    fresh()
    source.write_bytes(saved)
    git("update-index", "--no-assume-unchanged", "a.txt")
    cases += 2

    # Raw comparison must not inherit clean-filter normalization or index flags.
    attributes = repo / ".gitattributes"
    attributes.write_text("a.txt filter=fixture\n")
    git("config", "filter.fixture.clean", "printf 'one\\ntwo\\nthree\\n'")
    git("add", attributes.name)
    source.write_bytes(saved + b"hidden by clean filter\n")
    git("diff", "--quiet", "--", "a.txt")
    text, _ = run()
    check("raw index/worktree agreement: MISMATCH" in text and "raw index/worktree mismatch count: 1" in text
          and "reuse: disabled" in text, "clean filter hid raw index/worktree mismatch")
    fresh()
    cases += 1
    for flag in ("assume-unchanged", "skip-worktree"):
        git("update-index", "--" + flag, "a.txt")
        text, _ = run()
        check("raw index/worktree agreement: MISMATCH" in text, flag + " plus filter hid raw mismatch")
        fresh()
        source.write_bytes(saved)
        text, _ = run()
        check("raw index/worktree agreement: MATCH" in text, flag + " prevented actual raw agreement")
        fresh()
        source.write_bytes(saved + b"hidden by clean filter\n")
        git("update-index", "--no-" + flag, "a.txt")
        cases += 2
    source.write_bytes(saved)
    git("config", "--remove-section", "filter.fixture")
    git("rm", "--cached", attributes.name)
    attributes.unlink()

    attributes.write_text("a.txt filter=sideeffect\n")
    filter_marker = repo / ".git/filter-side-effect"
    query_bin = work / "filter-query-bin"
    query_bin.mkdir(mode=0o700)
    query_marker = scratch / "filter-query-called"
    query_shim = query_bin / "git"
    query_shim.write_text("#!/usr/bin/python3 -I\nimport os, sys\nfrom pathlib import Path\n"
                          "if sys.argv[1:3] == ['config', '--name-only']:\n"
                          f"    Path({str(query_marker)!r}).write_text('query\\n')\n"
                          "    print('fixture query error', file=sys.stderr)\n"
                          "    sys.exit(int(os.environ['QUERY_STATUS']))\n"
                          "os.execv('/usr/bin/git', ['git', *sys.argv[1:]])\n")
    query_shim.chmod(0o700)
    query_path = str(query_bin) + os.pathsep + env["PATH"]
    config_target = outside / "config-pipe"
    os.mkfifo(config_target)
    (repo / "a.txt").write_bytes(saved + b"filter-triggering worktree change\n")
    for driver, command in (("clean", "printf 'ran\\n' > .git/filter-side-effect; cat"),
                            ("process", "printf 'ran\\n' > .git/filter-side-effect; exit 1")):
        git("config", "filter.sideeffect." + driver, command)
        before_filter = snapshot()
        if driver == "clean":
            # /dev/null is the reproduced config/diff source mismatch. The shim
            # makes an accidental query of the FIFO fail promptly instead of hang.
            for override, path in (("/dev/null", env["PATH"]), ("", env["PATH"]), (str(config_target), query_path)):
                _, result = run(3, "--worktree", "--no-gates", overrides={"GIT_CONFIG": override,
                                "PATH": path, "QUERY_STATUS": "2", "GATE_MARKER": str(marker)})
                check(result.stderr == b"review-brief: worktree diff refused: GIT_CONFIG override is unsupported\n"
                      and not query_marker.exists() and not output.exists() and not filter_marker.exists()
                      and not marker.exists() and snapshot() == before_filter,
                      "GIT_CONFIG override reached the query, diff, gates or an outside target")
                cases += 1
        for arguments in (("--worktree", "--no-gates"), ("--worktree",)):
            _, result = run(3, *arguments, overrides={"GATE_MARKER": str(marker)})
            check(b"configured Git clean/process filters" in result.stderr and command.encode() not in result.stderr
                  and not output.exists() and not filter_marker.exists() and not marker.exists()
                  and snapshot() == before_filter, "worktree collection executed a filter or ran gates before refusal")
            cases += 1
        for override in ((None, "/dev/null", "") if driver == "clean" else (None,)):
            for arguments, change in ((("--staged", "--no-gates"), "+three"),
                                      (("--range", "HEAD~1..HEAD", "--no-gates"), "+two"),
                                      (("--plan",), "worktree observation: not collected")):
                text, _ = run(0, *arguments, overrides={"GIT_CONFIG": override})
                check(change in text and not filter_marker.exists() and snapshot() == before_filter,
                      "filter refusal changed staged/range/plan semantics or executed a driver")
                fresh()
                cases += 1
        git("config", "--remove-section", "filter.sideeffect")
    config_target.unlink()
    for driver in ("clean", "process"):
        for name, value in (("sideeffect", ""), ("unused", ""), ("unused", "exit 99")):
            git("config", "filter." + name + "." + driver, value)
            before_filter = snapshot()
            _, result = run(3, "--worktree", "--no-gates")
            check(b"configured Git clean/process filters" in result.stderr and not output.exists()
                  and not filter_marker.exists() and snapshot() == before_filter,
                  "empty or unused filter key escaped conservative refusal")
            git("config", "--remove-section", "filter." + name)
            cases += 1
    before_query = snapshot()
    for status in (2, 128):
        _, result = run(3, "--worktree", overrides={"PATH": query_path, "QUERY_STATUS": str(status),
                                                  "GATE_MARKER": str(marker)})
        check(result.stderr == b"review-brief: Git filter configuration query failed; worktree diff refused\n"
              and query_marker.read_text() == "query\n" and not output.exists() and not filter_marker.exists()
              and not marker.exists() and snapshot() == before_query,
              "filter-query error was treated as no filters, exposed diagnostics or executed gates")
        query_marker.unlink()
        cases += 1
    # Effective command-scope configuration is covered without reading its values
    # or consulting untracked/global attributes to decide whether it is active.
    _, result = run(3, "--worktree", "--no-gates", overrides={"GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "filter.sideeffect.clean", "GIT_CONFIG_VALUE_0": "exit 99"})
    check(b"configured Git clean/process filters" in result.stderr and not output.exists(),
          "command-scope Git filter configuration escaped refusal")
    cases += 1
    (repo / "a.txt").write_bytes(saved)
    attributes.unlink()

    git("config", "core.filemode", "false")
    source.chmod(0o755)
    git("diff", "--quiet", "--", "a.txt")
    text, _ = run()
    check("raw index/worktree agreement: MISMATCH" in text and "bytes, modes or deletions do not agree" in text,
          "core.filemode hid executable-mode mismatch")
    fresh()
    git("update-index", "--chmod=+x", "a.txt")
    text, _ = run()
    check("raw index/worktree agreement: MATCH" in text, "matching executable file mode refused")
    fresh()
    source.chmod(0o644)
    text, _ = run()
    check("raw index/worktree agreement: MISMATCH" in text, "staged executable mode change ignored")
    fresh()
    git("update-index", "--chmod=-x", "a.txt")
    git("config", "core.filemode", "true")
    cases += 3

    # HEAD-only paths are still observed, including a deletion left in the checkout.
    deleted = repo / "Makefile"
    deleted_bytes = deleted.read_bytes()
    git("rm", "--cached", deleted.name)
    text, _ = run(0, "--no-gates")
    check("raw index/worktree agreement: MISMATCH" in text and "untracked count: 1" in text,
          "staged deletion left on disk was treated as raw agreement")
    fresh()
    deleted.unlink()
    later, _ = run(0, "--no-gates")
    check("raw index/worktree agreement: MATCH" in later and fingerprints(text) != fingerprints(later),
          "absent staged deletion not covered by source evidence")
    fresh()
    os.mkfifo(deleted)
    text, _ = run(0, "--no-gates")
    check("raw index/worktree agreement: MISMATCH" in text and "not now-untracked contents" in text,
          "staged deletion opened a now-untracked source instead of checking presence")
    fresh()
    deleted.unlink()
    git("restore", "--staged", "--", deleted.name)
    text, _ = run(0, "--no-gates")
    check("raw index/worktree agreement: MISMATCH" in text, "missing indexed source was treated as agreement")
    fresh()
    deleted.write_bytes(deleted_bytes)
    cases += 4

    # Target evidence comes from the raw manifest/index comparison, not link names.
    nested = repo / "nested"
    nested.mkdir()
    links = [repo / "tracked-link", nested / "relative-link", repo / "binary-link"]
    for link, target in zip(links, ("a.txt", "../a.txt", "image.bin")):
        link.symlink_to(target)
        git("add", str(link.relative_to(repo)))
    before_links = snapshot()
    text, _ = run()
    check("raw index/worktree agreement: MATCH" in text and "attested internal tracked file-symlink count: 3" in text
          and "unattested tracked path count: 0" in text and "conditional evidence only" in text,
          "safe tracked file targets did not use collected raw evidence")
    check(snapshot() == before_links, "symlink attestation wrote source/index/Git objects")
    fresh()
    links[0].unlink()
    links[0].symlink_to("./a.txt")
    text, _ = run()
    check("raw index/worktree agreement: MISMATCH" in text and "attested internal tracked file-symlink count: 2" in text,
          "equivalent target name hid raw link-byte mismatch")
    fresh()
    links[0].unlink()
    links[0].symlink_to("a.txt")
    source.write_bytes(saved + b"target drift\n")
    text, _ = run()
    check("raw index/worktree agreement: MISMATCH" in text and "attested internal tracked file-symlink count: 1" in text
          and "unattested tracked path count: 2" in text, "changed tracked target bytes were guessed from link names")
    fresh()
    source.write_bytes(saved)
    text, _ = run(1, "--gate", "mutate")
    check("source-state comparison: CHANGED" in text and "reuse: disabled" in text
          and "attested internal tracked file-symlink count: 3" in text
          and "attested internal tracked file-symlink count: 1" in text, "target drift during gates stayed reusable")
    fresh()
    source.write_bytes(saved)
    for link in links:
        git("rm", "--cached", str(link.relative_to(repo)))
        link.unlink()
    cases += 4

    # These targets must never be opened. FIFOs make accidental reads fail/hang.
    target = repo / "untracked-target"
    external_target = outside / "external-target"
    os.mkfifo(target)
    os.mkfifo(external_target)
    unsafe_link = repo / "unattested-link"
    chain = repo / "untracked-chain"
    chain.symlink_to("a.txt")
    directory_chain = repo / "untracked-directory-chain"
    directory_chain.symlink_to("nested", target_is_directory=True)
    for destination in (target.name, str(external_target), "nested", chain.name, "a.txt/", "a.txt/.",
                        directory_chain.name + "/../a.txt"):
        unsafe_link.symlink_to(destination)
        git("add", unsafe_link.name)
        text, _ = run()
        check("raw index/worktree agreement: UNATTESTED" in text and "attested internal tracked file-symlink count: 0" in text
              and "unattested tracked path count: 1" in text and "reuse: disabled" in text,
              "unsupported target was opened or attested: " + destination)
        fresh()
        unsafe_link.unlink()
        cases += 1
    unsafe_link.symlink_to("/proc/eyragents-review-brief-missing")
    git("add", unsafe_link.name)
    run(2, "--no-gates")
    check(not output.exists(), "external target escaped path refusal")
    git("rm", "--cached", unsafe_link.name)
    unsafe_link.unlink()
    target.unlink()
    external_target.unlink()
    chain.unlink()
    directory_chain.unlink()
    nested.rmdir()
    cases += 1

    # A tracked path reached through a directory alias must not read its contents.
    alias_dir = repo / "alias-dir"
    alias_dir.mkdir()
    alias_source = alias_dir / "source"
    alias_source.write_text("ordinary fixture\n")
    git("add", "alias-dir/source")
    alias_source.unlink()
    alias_dir.rmdir()
    alias_dir.symlink_to(outside, target_is_directory=True)
    os.mkfifo(outside / "source")
    text, _ = run(0, "--no-gates")
    check("raw index/worktree agreement: UNATTESTED" in text and "unattested tracked path count: 1" in text,
          "directory alias opened a non-source target")
    fresh()
    git("restore", "--staged", "--", "alias-dir/source")
    alias_dir.unlink()
    (outside / "source").unlink()
    cases += 1

    git("update-index", "--add", "--cacheinfo", "160000", git("rev-parse", "HEAD").decode().strip(), "module")
    text, _ = run()
    check("raw index/worktree agreement: UNATTESTED" in text and "unattested tracked path count: 1" in text,
          "missing gitlink was treated as raw agreement")
    fresh()
    os.mkfifo(repo / "module")
    text, _ = run(0, "--no-gates")
    check("raw index/worktree agreement: UNATTESTED" in text, "gitlink replacement contents were opened")
    fresh()
    (repo / "module").unlink()
    git("rm", "--cached", "module")
    cases += 2

    # Ignored content is never hashed, and is never inferred from equal endpoints.
    limits_ignore = repo / ".gitignore"
    limits_ignore.write_text("/ignored-input\n")
    git("add", limits_ignore.name)
    ignored_input = repo / "ignored-input"
    ignored_input.write_text("first ignored input\n")
    text, _ = run()
    fresh()
    ignored_input.write_text("changed ignored input\n")
    later, _ = run()
    check(fingerprints(text) == fingerprints(later) and "untracked count: 0" in text
          and "Ignored files, dependencies, runtime/environment, Git configuration and host inputs are not attested" in text
          and "Unknown changes forbid reuse" in text and "not a concurrency lock" in text,
          "ignored-input or runtime limits not explicit")
    fresh()
    ignored_input.unlink()
    os.mkfifo(ignored_input)
    unsafe_link.symlink_to(ignored_input.name)
    git("add", unsafe_link.name)
    text, _ = run()
    check("raw index/worktree agreement: UNATTESTED" in text and "untracked count: 0" in text,
          "ignored symlink target was opened or attested")
    fresh()
    git("rm", "--cached", unsafe_link.name, limits_ignore.name)
    unsafe_link.unlink()
    limits_ignore.unlink()
    ignored_input.unlink()
    cases += 2

    empty = repo / "intent-empty.py"
    empty.write_text("")
    git("add", "--intent-to-add", empty.name)
    text, _ = run(0, "--no-gates")
    check("raw index/worktree agreement: UNATTESTED" in text, "empty intent-to-add fabricated indexed raw agreement")
    fresh()
    cases += 1
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
    git("rm", "--cached", source.name)
    source.write_bytes(b"")
    git("add", "--intent-to-add", source.name)
    text, _ = run(0, "--no-gates")
    check("raw index/worktree agreement: UNATTESTED" in text,
          "intent-to-add replacing an old HEAD path fabricated raw agreement")
    fresh()
    source.write_bytes(saved)
    git("add", source.name)
    cases += 1
    git("restore", "--staged", "a.txt")
    _, result = run(3, "--no-gates")
    check(not output.exists() and b"nothing is staged" in result.stderr, "empty staged change accepted")
    git("add", "a.txt")
    cases += 1

    # Git's checked storage format, not an implicit SHA-1, owns raw blob IDs.
    sha_repo = work / "sha256-repo"
    sha_repo.mkdir(mode=0o700)
    subprocess.run(["git", "init", "-q", "--object-format=sha256", str(sha_repo)], env=env, check=True)
    (sha_repo / "source.txt").write_text("first\n")
    subprocess.run(["git", "add", "source.txt"], cwd=sha_repo, env=env, check=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "first"],
                   cwd=sha_repo, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (sha_repo / "source.txt").write_text("second\n")
    (sha_repo / "file-link").symlink_to("source.txt")
    subprocess.run(["git", "add", "source.txt", "file-link"], cwd=sha_repo, env=env, check=True)
    before_sha = snapshot(sha_repo)
    text, _ = run(0, "--no-gates", cwd=sha_repo)
    check("Git storage object format: sha256" in text and "raw index/worktree agreement: MATCH" in text
          and "attested internal tracked file-symlink count: 1" in text and snapshot(sha_repo) == before_sha,
          "SHA-256 raw agreement failed or wrote Git/source state")
    fresh()
    (sha_repo / "source.txt").write_text("raw mismatch\n")
    text, _ = run(0, "--no-gates", cwd=sha_repo)
    check("raw index/worktree agreement: MISMATCH" in text and "attested internal tracked file-symlink count: 0" in text,
          "SHA-256 raw mismatch was missed")
    fresh()
    cases += 2

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

    # The plan exception owns only a new ignored Markdown leaf in either lane.
    plans = repo / ".eyr-plans"
    plans.mkdir(mode=0o700)
    plans.chmod(0o755)
    stream = plans / "artifact-tests"
    stream.mkdir(mode=0o700)
    lanes = [stream / lane for lane in ("audit", "spar")]
    for lane in lanes:
        lane.mkdir(mode=0o700)
    checkpoint = stream / "checkpoint.md"
    checkpoint.write_text(intent_text)
    candidate = lanes[0] / "brief.md"
    before = snapshot(work)
    run(64, "--plan", intent_path=checkpoint, output_path=candidate)
    check(snapshot(work) == before, "unignored plan output changed the fixture")
    cases += 1
    ignore = repo / ".gitignore"
    ignored_text = "/.eyr-plans/\n/reviews/\n/sub/.eyr-plans/\n/plan.md\n"
    ignore.write_text(ignored_text)
    for lane in lanes:
        candidate = lane / "brief.md"
        before = snapshot(work)
        text, _ = run(0, "--plan", intent_path=checkpoint, output_path=candidate,
                      overrides={"GATE_MARKER": str(marker)})
        check(snapshot(work, exclude=candidate) == before, "plan wrote anything beyond its exact ignored artifact")
        check(stat.S_IMODE(candidate.stat().st_mode) == 0o600 and candidate.stat().st_nlink == 1,
              "repository artifact is not a private single-link file")
        check("worktree observation: not collected" in text and "tracked worktree SHA-256:" not in text
              and "reuse: disabled" in text and "skipped by --plan (read-only)" in text
              and "output creates a repository file" in text and not marker.exists(),
              "repository plan output changed observation or gate scope")
        check(git("check-ignore", "--", str(candidate)).strip() == os.fsencode(candidate)
              and not git("ls-files", "--", str(candidate)), "plan output is not ignored and untracked")
        accepted = subprocess.run([str(scanner), "outbound", "--root", str(repo), "--scratch-root", str(work),
                                   "--", str(candidate)], input=b"Review.", stdout=subprocess.DEVNULL, env=env)
        check(accepted.returncode == 0, "repository brief fails outbound artifact API")
        before = snapshot(work)
        run(64, "--plan", intent_path=checkpoint, output_path=candidate)
        check(snapshot(work) == before, "existing repository plan artifact was clobbered")
        candidate.unlink()
        cases += 2

    candidate = lanes[0] / "brief.md"
    before = snapshot(work)
    # Ordinary repository roots need no TMPDIR. Tool-session paths still require
    # explicit caller scratch under the scanner's independent confinement policy.
    tool_session = re.match(r"^/(?:var/)?tmp/(?:opencode|claude-[^/]+|codex[^/]*)/", str(repo.resolve()))
    run(2 if tool_session else 0, "--plan", intent_path=checkpoint, output_path=candidate,
        overrides={"TMPDIR": None})
    check(snapshot(work, exclude=None if tool_session else candidate) == before,
          "no-TMPDIR plan invocation changed unexpected fixture state")
    if tool_session:
        check(not candidate.exists(), "repository exception bypassed tool-session scratch confinement")
    else:
        candidate.unlink()
    cases += 1

    # A missing worktree leaf can still be tracked; --no-index ignore status
    # alone must not authorize recreating it. Index writes here are fixture-only.
    git("update-index", "--add", "--cacheinfo", "100644", git("rev-parse", "HEAD:a.txt").decode().strip(),
        str(candidate.relative_to(repo)))
    before = snapshot(work)
    run(64, "--plan", intent_path=checkpoint, output_path=candidate)
    check(snapshot(work) == before, "tracked ignored plan output changed source or Git metadata")
    run(64, "--plan", intent_path=checkpoint, output_path=candidate,
        overrides={"GIT_LITERAL_PATHSPECS": "1"})
    check(snapshot(work) == before, "literal-pathspec environment recreated a tracked artifact")
    alternate_index = work / "alternate.index"
    subprocess.run(["git", "-C", str(repo), "read-tree", "--empty"],
                   env={**env, "GIT_INDEX_FILE": str(alternate_index)}, check=True)
    before = snapshot(work)
    run(64, "--plan", intent_path=checkpoint, output_path=candidate,
        overrides={"GIT_INDEX_FILE": str(alternate_index)})
    check(snapshot(work) == before, "alternate index recreated a tracked artifact")
    text, _ = run(0, "--plan", overrides={"GIT_INDEX_FILE": str(alternate_index)})
    check("worktree observation: not collected" in text, "alternate-index scratch plan changed scope")
    fresh()
    check(snapshot(work) == before, "alternate-index scratch plan changed repository state")
    alternate_index.unlink()
    git("restore", "--staged", "--", str(candidate.relative_to(repo)))
    cases += 4

    for refused in (repo / "plan.md", repo / "checkpoint.md", repo / "reviews/brief.md",
                    plans / "checkpoint.md", stream / "checkpoint.md", stream / "reviews/brief.md",
                    stream / "auditor/brief.md",
                    lanes[0] / "nested/brief.md", lanes[1] / "brief.txt", plans / "audit/brief.md",
                    plans / "./spar/brief.md", plans / "../spar/brief.md",
                    plans / "governance/audit/brief.md", plans / "governance/spar/brief.md",
                    plans / "bad.slug/audit/brief.md", plans / "bad slug/spar/brief.md",
                    plans / "-bad/spar/brief.md", repo / "sub/.eyr-plans/artifact-tests/audit/brief.md"):
        before = snapshot(work)
        run(64, "--plan", intent_path=checkpoint, output_path=refused)
        check(snapshot(work) == before, "invalid repository namespace path changed fixture: " + str(refused))
        cases += 1

    for parent, mode in ((plans, 0o775), (plans, 0o757), (stream, 0o750), (stream, 0o770),
                         (stream, 0o500), (lanes[0], 0o755), (lanes[0], 0o707), (lanes[0], 0o1700)):
        original_mode = stat.S_IMODE(parent.stat().st_mode)
        parent.chmod(mode)
        before = snapshot(work)
        run(2, "--plan", output_path=candidate)
        check(snapshot(work) == before, "unsafe plan parent mode accepted or repaired")
        parent.chmod(original_mode)
        cases += 1

    for parent in (plans, stream, lanes[0]):
        held = work / "held-parent"
        parent.rename(held)
        before = snapshot(work)
        run(2, "--plan", output_path=candidate)
        check(snapshot(work) == before, "generator created missing plan directories")
        parent.symlink_to(held, target_is_directory=True)
        before = snapshot(work)
        run(2, "--plan", output_path=candidate)
        check(snapshot(work) == before, "plan output followed a parent escaping the namespace")
        parent.unlink()
        held.rename(parent)
        cases += 2

    # Alias spellings into the namespace are not an alternative entry point.
    for alias_parent, target in ((repo / "review-alias", lanes[0]), (scratch / "review-alias", lanes[0]),
                                 (scratch / "repo-alias", repo)):
        alias_parent.symlink_to(target, target_is_directory=True)
        aliased = alias_parent / candidate.relative_to(target)
        before = snapshot(work)
        run(64, "--plan", output_path=aliased)
        check(snapshot(work) == before, "alias into the plan namespace accepted")
        alias_parent.unlink()
        cases += 1
    lanes[0].rmdir()
    lanes[0].symlink_to(lanes[1], target_is_directory=True)
    before = snapshot(work)
    run(2, "--plan", output_path=candidate)
    check(snapshot(work) == before, "lane symlink into another lane accepted")
    lanes[0].unlink()
    lanes[0].mkdir(mode=0o700)
    candidate.symlink_to(lanes[0] / "missing.md")
    before = snapshot(work)
    run(2, "--plan", output_path=candidate)
    check(snapshot(work) == before, "dangling repository output link clobbered")
    candidate.unlink()
    cases += 2

    # A bounded Git shim changes eligibility during metadata collection, after
    # initial preflight. It never runs a gate or alters the real repository.
    bin_dir = work / "recheck-bin"
    bin_dir.mkdir(mode=0o700)
    shim = bin_dir / "git"
    for mutation, expected, diagnostic in (
            (f"Path({str(ignore)!r}).write_text('# ignore removed during collection\\n')", 64, b"must already be ignored"),
            (f"Path({str(lanes[0])!r}).chmod(0o755)", 2, b"directories must be real, owned and private")):
        shim.write_text("#!/usr/bin/python3 -I\nimport os, sys\nfrom pathlib import Path\n"
                        "if sys.argv[1:] == ['--no-pager', 'log', '-1', '--format=%H %s']:\n"
                        f"    {mutation}\n"
                        "os.execv('/usr/bin/git', ['git', *sys.argv[1:]])\n")
        shim.chmod(0o700)
        # Compare every fixture entry against the exact intentional shim effect.
        if expected == 64:
            ignore.write_text("# ignore removed during collection\n")
        else:
            lanes[0].chmod(0o755)
        expected_state = snapshot(work)
        ignore.write_text(ignored_text)
        lanes[0].chmod(0o700)
        _, result = run(expected, "--plan", output_path=candidate,
                        overrides={"PATH": str(bin_dir) + os.pathsep + env["PATH"]})
        check(diagnostic in result.stderr and snapshot(work) == expected_state,
              "plan eligibility was not rechecked before publication, or refusal had side effects")
        ignore.write_text(ignored_text)
        lanes[0].chmod(0o700)
        cases += 1

    for bad_intent in (leak, near_limit):
        before = snapshot(work)
        run(2, "--plan", intent_path=bad_intent, output_path=candidate)
        check(snapshot(work) == before, "scanner refusal wrote an ignored plan artifact or draft")
        cases += 1
    before = snapshot(work)
    run(64, "--plan", "--gate", "forbidden", output_path=candidate, overrides={"GATE_MARKER": str(marker)})
    check(snapshot(work) == before and not marker.exists(), "repository plan output enabled gates")
    cases += 1
    asset.unlink()
    os.mkfifo(asset)
    before = snapshot(work)
    text, _ = run(0, "--plan", intent_path=checkpoint, output_path=candidate)
    check(snapshot(work, exclude=candidate) == before and "worktree observation: not collected" in text,
          "repository plan output opened source or changed state beyond its artifact")
    candidate.unlink()
    asset.unlink()
    asset.write_bytes(bytes(range(256)) * 4096)
    cases += 1

    # A plan can observe metadata even with inherited sensitive source paths.
    # Change modes remain conservative: no attempt to prove secret-byte equality.
    sensitive.write_text("ordinary synthetic fixture\n")
    git("add", ".env")
    first_source = repo / ".aaa-source"
    git("update-index", "--add", "--cacheinfo", "100644", git("rev-parse", "HEAD:a.txt").decode().strip(), first_source.name)
    os.mkfifo(first_source)
    _, result = run(2, "--no-gates")
    check(not output.exists() and b"before content access" in result.stderr,
          "source read preceded full sensitive-path preflight")
    git("restore", "--staged", "--", first_source.name)
    first_source.unlink()
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
    git("rm", "--cached", sensitive.name)
    sensitive.unlink()
    _, result = run(2, "--no-gates")
    check(not output.exists() and b"before content access" in result.stderr,
          "old HEAD-only sensitive path escaped preflight after staged deletion")
    sensitive.write_text("ordinary synthetic fixture\n")
    git("add", sensitive.name)
    cases += 1
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
