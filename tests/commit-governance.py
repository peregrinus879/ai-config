"""Local-only deterministic governance cases; no real home/config/remote is used."""

import hashlib
import contextlib
import fcntl
import io
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "agents/.agents/skills"
TRAILER = "Co-Authored-By: Test Model <noreply@anthropic.com>"
MESSAGE = "feat: add content\n\n# Kept verbatim.\nBody line.\n\n" + TRAILER + "\n"


class Governance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="governance-", dir=os.environ.get("TMPDIR", "/tmp"))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "re po"
        self.repo.mkdir()
        home = self.root / "home"
        home.mkdir()
        self.env = {"PATH": os.environ["PATH"], "HOME": str(home), "USER": "fixture",
                    "TMPDIR": str(self.root), "GIT_CONFIG_GLOBAL": str(self.root / "gitconfig"),
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C",
                    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
                    "EYRAGENTS_RECORD_ROOT": str(self.root / "records"), "HISTFILE": "/dev/null"}
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "1+test@users.noreply.github.com")
        self.write("a.txt", "one\n")
        self.git("add", "a.txt")
        self.git("commit", "-q", "-m", "chore: seed")
        self.parent = self.git("rev-parse", "HEAD").stdout.strip()

    def run_command(self, command, data=None, ok=True, env=None, cwd=None):
        result = subprocess.run(command, input=data, text=True, capture_output=True,
                                env=env or self.env, cwd=cwd or self.repo, timeout=20)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def git(self, *args, **kwargs):
        return self.run_command(["git", *args], **kwargs)

    def script(self, name, *args, **kwargs):
        skill = "commit" if name.startswith("commit-") else "publish"
        return self.run_command([str(SKILLS / skill / "scripts" / name), *args], **kwargs)

    def write(self, name, data):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode())
        return path

    def record(self, *paths, message=MESSAGE, stage=True):
        result = self.script("commit-candidate", *(["--stage"] if stage else []), "--", *paths, data=message)
        return re.search(r"^candidate-id=([a-f0-9]{64})$", result.stdout, re.M)[1]

    def receipt(self, receipt_id):
        return next((self.root / "records").glob(f"*/{receipt_id}.json"))

    def status(self, receipt_id):
        return json.loads(self.receipt(receipt_id).with_suffix(".status").read_text())

    def hook(self, name, body):
        path = self.write(".git/hooks/" + name, "#!/bin/sh\nset -eu\n" + body + "\n")
        path.chmod(0o755)
        return path

    def git_shim(self, body):
        tools = self.root / "tools"
        tools.mkdir(exist_ok=True)
        wrapper = tools / "git"
        wrapper.write_text("#!/bin/sh\n" + body + "\nexec " + shlex.quote(shutil.which("git")) + ' "$@"\n')
        wrapper.chmod(0o755)
        return {**self.env, "PATH": str(tools) + ":" + self.env["PATH"]}

    def outbound(self):
        remote = self.root / "remote.git"
        self.git("init", "-q", "--bare", str(remote))
        self.git("remote", "add", "origin", str(remote))
        self.git("push", "-q", "-u", "origin", "main")
        self.write("b.txt", "two\n")
        candidate_id = self.record("b.txt")
        self.script("commit-apply", candidate_id)
        return remote

    def binding(self):
        result = self.script("publish-bind")
        receipt_id = re.search(r"^binding-id=([a-f0-9]{64})$", result.stdout, re.M)[1]
        command = result.stdout.split("== command\n", 1)[1].strip()
        return receipt_id, command

    def close_bundle(self, verified=True):
        self.outbound()
        candidate_id = next(path.stem for path in (self.root / "records").glob("*/*.json")
                            if json.loads(path.read_text())["kind"] == "candidate")
        publication_id, command = self.binding()
        if verified:
            self.run_command(["bash", "--noprofile", "--norc", "-c", command])
            self.script("publish-verify", publication_id)
        return candidate_id, publication_id

    def set_status(self, receipt_id, state, **extra):
        self.receipt(receipt_id).with_suffix(".status").write_text(
            json.dumps({"id": receipt_id, "state": state, **extra}))

    def snapshot(self, root):
        result = {}
        for path in [root, *sorted(root.rglob("*"))]:
            info = path.lstat()
            data = os.readlink(path) if stat.S_ISLNK(info.st_mode) else path.read_bytes() if stat.S_ISREG(info.st_mode) else None
            result[str(path.relative_to(root))] = (
                info.st_mode, info.st_uid, info.st_nlink, info.st_ino, info.st_mtime_ns, info.st_ctime_ns, data)
        return result

    def interrupt_close(self, ids, phase, target, *flags):
        runner = '''import os, runpy, stat, sys
runtime = runpy.run_path(sys.argv[1])
phase, target = sys.argv[2:4]
original_atomic = runtime["atomic"]
original_unlink = runtime["Path"].unlink
original_open, original_fdopen = os.open, os.fdopen
original_fsync, original_replace = os.fsync, os.replace
active = False
def atomic(path, *args, **kwargs):
    global active
    active = path.name == target + ".status"
    original_atomic(path, *args, **kwargs)
    if phase == "mark" and active:
        os._exit(91)
    active = False
def open_file(path, flags, *args, **kwargs):
    fd = original_open(path, flags, *args, **kwargs)
    if active and phase == "create" and flags & os.O_CREAT:
        os._exit(91)
    return fd
class Writer:
    def __init__(self, stream):
        self.stream = stream
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return self.stream.__exit__(*args)
    def __getattr__(self, name):
        return getattr(self.stream, name)
    def write(self, data):
        if active and phase in ("partial-write", "write"):
            self.stream.write(data[:len(data) // 2] if phase == "partial-write" else data)
            self.stream.flush()
            os._exit(91)
        return self.stream.write(data)
def fdopen(*args, **kwargs):
    stream = original_fdopen(*args, **kwargs)
    return Writer(stream) if active and "w" in args[1] else stream
def fsync(fd):
    original_fsync(fd)
    if active and phase == "fsync" and stat.S_ISREG(os.fstat(fd).st_mode):
        os._exit(91)
def replace(source, destination):
    if active and phase == "before-replace":
        os._exit(91)
    original_replace(source, destination)
    if active and phase == "replace":
        os._exit(91)
def unlink(path, *args, **kwargs):
    original_unlink(path, *args, **kwargs)
    if path.name == target + "." + phase:
        os._exit(91)
runtime["Records"].close.__globals__["atomic"] = atomic
runtime["Path"].unlink = unlink
os.open, os.fdopen, os.fsync, os.replace = open_file, fdopen, fsync, replace
sys.argv = [sys.argv[1], "candidate", "--close", *sys.argv[4:]]
sys.exit(runtime["main"]())
'''
        result = self.run_command([sys.executable, "-I", "-c", runner,
                                   str(SKILLS / "commit/scripts/governance.py"), phase, target, *ids, *flags], ok=False)
        self.assertEqual(result.returncode, 91, result.stdout + result.stderr)

    def test_close_verified_ancestry_bundle_and_preview_preserve_git_and_lock(self):
        self.outbound()
        first = next((self.root / "records").glob("*/*.json")).stem
        self.write("next.txt", "next\n")
        second = self.record("next.txt")
        self.script("commit-apply", second)
        publication, command = self.binding()
        self.run_command(["bash", "-c", command])
        self.script("publish-verify", publication)
        self.write("pending.txt", "keep active candidate\n")
        ready = self.record("pending.txt")
        store = self.receipt(first).parent
        before_store = self.snapshot(store)
        before_git = self.snapshot(self.repo)
        lock = (store / "lock").stat()
        ids = (first, publication, second)
        result = self.script("commit-candidate", "--close", *ids, "--dry-run")
        self.assertEqual(result.stdout.count("outcome=verified"), 3)
        self.assertEqual(before_store, self.snapshot(store))
        self.assertEqual(before_git, self.snapshot(self.repo))
        result = self.script("commit-candidate", "--close", *ids)
        self.assertEqual(result.stdout.count("outcome=verified"), 3)
        self.assertEqual(before_git, self.snapshot(self.repo))
        self.assertEqual(self.status(ready)["state"], "ready")
        self.assertEqual(sorted(path.name for path in store.iterdir()), [ready + ".json", ready + ".status", "lock"])
        self.assertEqual((lock.st_dev, lock.st_ino), ((store / "lock").stat().st_dev, (store / "lock").stat().st_ino))
        result = self.script("commit-candidate", "--close", *ids)
        self.assertEqual(result.stdout.count("absent:"), 3)
        self.assertNotIn("outcome=verified", result.stdout)

    def test_close_requires_selected_publication_of_actual_committed_id(self):
        candidate, publication = self.close_bundle()
        store = self.receipt(candidate).parent
        before = self.snapshot(store)
        self.assertIn("coverage", self.script("commit-candidate", "--close", candidate, ok=False).stderr)
        self.assertEqual(before, self.snapshot(store))
        self.write("later.txt", "not published\n")
        later = self.record("later.txt")
        self.script("commit-apply", later)
        before = self.snapshot(store)
        for flags in ([], ["--accept-unverified"]):
            result = self.script("commit-candidate", "--close", publication, later, *flags, ok=False)
            self.assertIn("ancestry coverage", result.stderr)
            self.assertEqual(before, self.snapshot(store))

    def test_close_unverified_is_explicit_and_never_claims_success(self):
        candidate, publication = self.close_bundle(verified=False)
        store = self.receipt(candidate).parent
        before = self.snapshot(store)
        before_git = self.snapshot(self.repo)
        before_remote = self.snapshot(self.root / "remote.git")
        self.script("commit-candidate", "--close", publication, candidate, ok=False)
        self.assertEqual(before, self.snapshot(store))
        result = self.script("commit-candidate", "--close", publication, candidate, "--accept-unverified", "--dry-run")
        self.assertEqual(result.stdout.count("outcome=UNVERIFIED"), 2)
        self.assertEqual(before, self.snapshot(store))
        result = self.script("commit-candidate", "--close", publication, candidate, "--accept-unverified")
        self.assertEqual(result.stdout.count("outcome=UNVERIFIED"), 2)
        self.assertNotIn("outcome=verified", result.stdout)
        self.assertNotIn("publish verified", result.stdout)
        self.assertNotIn("successful", result.stdout)
        self.assertEqual(before_git, self.snapshot(self.repo))
        self.assertEqual(before_remote, self.snapshot(self.root / "remote.git"))

    def test_close_rejected_publication_requires_acceptance_to_cover_candidate(self):
        candidate, publication = self.close_bundle(verified=False)
        self.git("config", "push.followTags", "true")
        self.script("publish-bind", "--check", publication, ok=False)
        before = self.snapshot(self.receipt(candidate).parent)
        self.script("commit-candidate", "--close", publication, candidate, ok=False)
        self.assertEqual(before, self.snapshot(self.receipt(candidate).parent))
        preview = self.script("commit-candidate", "--close", publication, "--dry-run")
        self.assertIn("outcome=rejected", preview.stdout)
        self.assertNotIn("outcome=verified", preview.stdout)
        result = self.script("commit-candidate", "--close", publication, candidate, "--accept-unverified")
        self.assertEqual(result.stdout.count("outcome=UNVERIFIED"), 2)

    def test_close_plain_rejected_publication_and_unselected_corrupt_records(self):
        candidate, publication = self.close_bundle(verified=False)
        self.set_status(publication, "rejected")
        store = self.receipt(candidate).parent
        orphan = store / ("f" * 64 + ".json")
        orphan.write_text("unexplained fixture payload")
        orphan.chmod(0o400)
        before_candidate = self.receipt(candidate).read_bytes()
        result = self.script("commit-candidate", "--close", publication)
        self.assertIn("outcome=rejected", result.stdout)
        self.assertNotIn("outcome=verified", result.stdout)
        self.assertEqual(self.receipt(candidate).read_bytes(), before_candidate)
        self.assertEqual(self.status(candidate)["state"], "committed")
        self.assertEqual(orphan.read_text(), "unexplained fixture payload")

    def test_close_verified_commit_mismatch_and_missing_ancestry_objects_refuse(self):
        candidate, publication = self.close_bundle()
        self.set_status(publication, "verified", commit=self.parent)
        store = self.receipt(candidate).parent
        before = self.snapshot(store)
        result = self.script("commit-candidate", "--close", candidate, publication, "--accept-unverified", ok=False)
        self.assertIn("verified status/reviewed commit mismatch", result.stderr)
        self.assertEqual(before, self.snapshot(store))
        reviewed = json.loads(self.receipt(publication).read_text())["reviewed"]
        self.set_status(publication, "verified", commit=reviewed)
        self.set_status(candidate, "committed", commit="f" * 40)
        before = self.snapshot(store)
        self.script("commit-candidate", "--close", candidate, publication, ok=False)
        self.assertEqual(before, self.snapshot(store))

    def test_close_existing_published_wrong_commit_does_not_cover_unpublished_candidate(self):
        candidate, publication = self.close_bundle()
        published = self.status(candidate)["commit"]
        self.write("unpublished.txt", "not published\n")
        unpublished = self.record("unpublished.txt")
        self.script("commit-apply", unpublished)
        self.set_status(unpublished, "committed", commit=published)
        store = self.receipt(candidate).parent
        before_store, before_git = self.snapshot(store), self.snapshot(self.repo)
        for flags in ([], ["--dry-run"], ["--accept-unverified"]):
            result = self.script("commit-candidate", "--close", publication, unpublished, *flags, ok=False)
            self.assertIn("committed candidate mismatch", result.stderr)
            self.assertEqual(before_store, self.snapshot(store))
            self.assertEqual(before_git, self.snapshot(self.repo))

    def test_close_revalidates_each_immutable_commit_field_initially_and_on_recovery(self):
        candidate, publication = self.close_bundle()
        path = self.receipt(candidate)
        value = json.loads(path.read_text())
        original_source = self.status(candidate)
        self.interrupt_close((publication, candidate), "mark", candidate)
        original_marker = self.status(candidate)
        seed_tree = self.git("rev-parse", self.parent + "^{tree}").stdout.strip()
        changes = [{"tree": seed_tree}, {"parent": original_source["commit"]},
                   {"message": value["message"] + "extra line\n"},
                   {"identity": {**value["identity"], "author": ["Other", value["identity"]["author"][1]]}},
                   {"identity": {**value["identity"], "committer": ["Other", value["identity"]["committer"][1]]}},
                   {"identity": {}}, {"identity": {"author": value["identity"]["author"]}}]
        for change in changes:
            payload = json.dumps({**value, **change}, sort_keys=True, separators=(",", ":")) + "\n"
            receipt_id = hashlib.sha256(payload.encode()).hexdigest()
            other = path.with_name(receipt_id + ".json")
            other.write_text(payload)
            other.chmod(0o400)
            source = {**original_source, "id": receipt_id}
            marker = {**original_marker, "id": receipt_id, "payload": payload, "source": source}
            for state in (source, marker):
                other.with_suffix(".status").write_text(json.dumps(state))
                other.with_suffix(".status").chmod(0o600)
                for flags in ([], ["--dry-run"], ["--accept-unverified"]):
                    with self.subTest(change=next(iter(change)), state=state["state"], flags=flags):
                        before_store, before_git = self.snapshot(path.parent), self.snapshot(self.repo)
                        result = self.script("commit-candidate", "--close", publication, receipt_id, *flags, ok=False)
                        self.assertIn("committed candidate mismatch", result.stderr)
                        self.assertEqual(before_store, self.snapshot(path.parent))
                        self.assertEqual(before_git, self.snapshot(self.repo))
            other.unlink()
            before = self.snapshot(path.parent)
            result = self.script("commit-candidate", "--close", receipt_id, ok=False)
            self.assertIn("committed candidate mismatch", result.stderr)
            self.assertEqual(before, self.snapshot(path.parent))

    def test_close_checks_complete_actual_parent_list_and_both_identities(self):
        candidate, publication = self.close_bundle()
        path = self.receipt(candidate)
        value = json.loads(path.read_text())
        raw = self.git("cat-file", "commit", self.status(candidate)["commit"]).stdout.encode()
        runtime = runpy.run_path(str(SKILLS / "commit/scripts/governance.py"))
        self.assertTrue(runtime["candidate_commit"](value, raw)[1])
        parent = b"parent " + value["parent"].encode() + b"\n"
        for changed in (raw.replace(parent, b""), raw.replace(parent, parent * 2),
                        raw.replace(b"author Test", b"author Other"), raw.replace(b"committer Test", b"committer Other"),
                        raw.replace(b"author Test <1+test", b"author Test <2+other"),
                        raw.replace(b"committer Test <1+test", b"committer Test <2+other")):
            self.assertFalse(runtime["candidate_commit"](value, changed)[1])
        self.interrupt_close((publication, candidate), "json", candidate)
        # A historical receipt is not bound to today's checkout or Git identity.
        self.git("checkout", "-q", "--detach", self.parent)
        self.git("config", "user.name", "Current User")
        self.git("config", "user.email", "2+current@users.noreply.github.com")
        before = self.snapshot(self.repo)
        self.script("commit-candidate", "--close", candidate, publication)
        self.assertEqual(before, self.snapshot(self.repo))

    def test_close_ancestry_queries_disable_lazy_fetch_and_git_writes(self):
        candidate, publication = self.close_bundle()
        env = self.git_shim('case "$2" in\nrev-parse) ;;\ncat-file|merge-base)\n'
                            'test "$GIT_NO_LAZY_FETCH" = 1 || exit 92\n'
                            'test "$GIT_OPTIONAL_LOCKS" = 0 || exit 93\n;;\n*) exit 94 ;;\nesac')
        env.update(GIT_NO_LAZY_FETCH="0", GIT_OPTIONAL_LOCKS="1")
        before = self.snapshot(self.repo)
        self.script("commit-candidate", "--close", candidate, publication, env=env)
        self.assertEqual(before, self.snapshot(self.repo))

    def test_close_simple_rejection_not_ready_applying_or_ambiguous_failure(self):
        self.write("b.txt", "two\n")
        rejected = self.record("b.txt")
        self.script("commit-candidate", "--clear", rejected)
        protected = self.record("b.txt")
        store = self.receipt(rejected).parent
        states = [("ready", {}), ("applying", {"reflog_action": "fixture"}),
                  ("rejected", {"created": None, "reflog_action": "fixture"}),
                  ("rejected", {"created": self.parent}), ("rejected", {"reflog_action": ""})]
        for state, extra in states:
            with self.subTest(state=state, extra=extra):
                self.set_status(protected, state, **extra)
                before = self.snapshot(store)
                self.script("commit-candidate", "--close", rejected, protected, "--accept-unverified", ok=False)
                self.assertEqual(before, self.snapshot(store))
        result = self.script("commit-candidate", "--close", rejected)
        self.assertIn("outcome=rejected", result.stdout)
        self.assertEqual(self.status(protected)["state"], "rejected")

    def test_close_invalid_duplicate_and_mixed_arguments_create_no_store(self):
        receipt_id = "a" * 64
        cases = [["--close"], ["--close", "a" * 63], ["--close", "G" * 64], ["--close", "A" * 64],
                 ["--close", "../" + receipt_id], ["--close", receipt_id, receipt_id],
                 ["--close", receipt_id, "--close", "b" * 64],
                 ["--close", receipt_id, "--dry-run", "--dry-run"],
                 ["--close", receipt_id, "--accept-unverified", "--accept-unverified"],
                 ["--close", receipt_id, "--stage"], ["--close", receipt_id, "--message-file", "missing"],
                 ["--close", receipt_id, "--show", receipt_id], ["--close", receipt_id, "--clear", receipt_id],
                 ["--close", receipt_id, "--", "a.txt"], ["--close", receipt_id, "a.txt"],
                 ["--close", receipt_id, "--all"], ["--cl", receipt_id], ["--dry-run", "a.txt"],
                 ["--accept-unverified", "--stage", "a.txt"], ["--show", receipt_id, "--dry-run"]]
        before = self.snapshot(self.repo)
        for args in cases:
            with self.subTest(args=args):
                self.script("commit-candidate", *args, ok=False)
                self.assertFalse((self.root / "records").exists())
                self.assertEqual(before, self.snapshot(self.repo))

    def test_close_absent_store_or_ids_are_honest_noncreating_noops(self):
        for flags in (["--dry-run"], []):
            result = self.script("commit-candidate", "--close", "a" * 64, *flags)
            self.assertIn("absent:", result.stdout)
            self.assertIn("prior outcome unknown", result.stdout)
            self.assertNotIn("outcome=verified", result.stdout)
            self.assertFalse((self.root / "records").exists())
        (self.root / "records").mkdir(mode=0o700)
        self.script("commit-candidate", "--close", "a" * 64, "--dry-run")
        self.assertEqual(list((self.root / "records").iterdir()), [])

    def test_close_without_acquired_lock_never_inspects_a_newly_created_store(self):
        self.write("b.txt", "two\n")
        receipt_id = self.record("b.txt")
        self.script("commit-candidate", "--clear", receipt_id)
        store = self.receipt(receipt_id).parent
        before = self.snapshot(store)
        runtime = runpy.run_path(str(SKILLS / "commit/scripts/governance.py"))
        records = object.__new__(runtime["Records"])
        records.path, records.top, records.lock = store, str(self.repo), None
        output = io.StringIO()
        with contextlib.redirect_stdout(output), mock.patch.object(Path, "lstat", side_effect=AssertionError("unlocked inspection")):
            records.close([receipt_id])
        self.assertIn("absent at inspection", output.getvalue())
        self.assertNotIn("outcome=", output.getvalue())
        self.assertEqual(before, self.snapshot(store))

    def test_close_orphan_corrupt_digest_schema_and_status_mismatch_preserve_all(self):
        self.write("b.txt", "two\n")
        eligible = self.record("b.txt")
        self.script("commit-candidate", "--clear", eligible)
        broken = self.record("b.txt")
        self.script("commit-candidate", "--clear", broken)
        path = self.receipt(broken)
        status_path = path.with_suffix(".status")
        payload, source = path.read_bytes(), status_path.read_bytes()
        for defect in ("payload-missing", "status-missing", "payload-corrupt", "digest", "status-corrupt", "status-array",
                       "status-id", "status-unknown", "status-extra", "kind-state", "commit-shape"):
            with self.subTest(defect=defect):
                if defect == "payload-missing":
                    path.unlink()
                elif defect == "status-missing":
                    status_path.unlink()
                elif defect in ("payload-corrupt", "digest"):
                    path.chmod(0o600)
                    path.write_bytes(b"{" if defect == "payload-corrupt" else payload + b" ")
                elif defect.startswith("status-"):
                    bad = {"status-corrupt": "{", "status-array": "[]", "status-id": json.dumps({"id": "a" * 64, "state": "rejected"}),
                           "status-unknown": json.dumps({"id": broken, "state": "mystery"}),
                           "status-extra": json.dumps({"id": broken, "state": "rejected", "paused": True})}
                    status_path.write_text(bad[defect])
                else:
                    self.set_status(broken, "verified" if defect == "kind-state" else "committed", commit="HEAD")
                before = self.snapshot(path.parent)
                result = self.script("commit-candidate", "--close", eligible, broken, "--accept-unverified", ok=False)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(before, self.snapshot(path.parent))
                if path.exists():
                    path.chmod(0o600)
                path.write_bytes(payload)
                path.chmod(0o400)
                status_path.write_bytes(source)
                status_path.chmod(0o600)
        original = json.loads(payload)
        for changes in ({"version": 2}, {"version": True}, {"kind": "unknown"}, {"toplevel": str(self.root)}, {"toplevel": None}):
            value = {**original, **changes}
            data = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
            receipt_id = hashlib.sha256(data).hexdigest()
            other = path.with_name(receipt_id + ".json")
            other.write_bytes(data)
            other.chmod(0o400)
            self.set_status(receipt_id, "rejected")
            other.with_suffix(".status").chmod(0o600)
            before = self.snapshot(path.parent)
            self.script("commit-candidate", "--close", eligible, receipt_id, ok=False)
            self.assertEqual(before, self.snapshot(path.parent))

    def test_close_refuses_unsafe_files_and_store_paths(self):
        self.write("b.txt", "two\n")
        receipt_id = self.record("b.txt")
        self.script("commit-candidate", "--clear", receipt_id)
        path = self.receipt(receipt_id)
        for target in (path, path.with_suffix(".status"), path.parent / "lock"):
            original, mode = target.read_bytes(), target.stat().st_mode & 0o777
            for defect in ("symlink", "dangling", "hardlink", "public", "directory", "fifo"):
                with self.subTest(target=target.suffix or "lock", defect=defect):
                    external = self.root / "file-target"
                    external.write_bytes(original)
                    external.chmod(0o600)
                    target.unlink()
                    if defect in ("symlink", "dangling"):
                        target.symlink_to(external if defect == "symlink" else self.root / "missing")
                    elif defect == "hardlink":
                        os.link(external, target)
                    elif defect == "directory":
                        target.mkdir(mode=0o700)
                    elif defect == "fifo":
                        os.mkfifo(target, 0o600)
                    else:
                        target.write_bytes(original)
                        target.chmod(0o644)
                    before = self.snapshot(path.parent)
                    self.script("commit-candidate", "--close", receipt_id, "--dry-run", ok=False)
                    self.assertEqual(before, self.snapshot(path.parent))
                    target.rmdir() if defect == "directory" else target.unlink()
                    target.write_bytes(original)
                    target.chmod(mode)
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        for root in ("records", str(alias / "records")):
            before = self.snapshot(path.parent)
            self.script("commit-candidate", "--close", receipt_id,
                        env={**self.env, "EYRAGENTS_RECORD_ROOT": root}, ok=False)
            self.assertEqual(before, self.snapshot(path.parent))
        for directory in (path.parent, path.parent.parent):
            directory.chmod(0o755)
            before = self.snapshot(path.parent)
            self.script("commit-candidate", "--close", receipt_id, ok=False)
            self.assertEqual(before, self.snapshot(path.parent))
            directory.chmod(0o700)
            directory.chmod(0o600)
            try:
                result = self.script("commit-candidate", "--close", receipt_id, ok=False)
                self.assertNotIn("absent:", result.stdout)
            finally:
                directory.chmod(0o700)
        (path.parent / "lock").unlink()
        before = self.snapshot(path.parent)
        self.assertIn("no lock", self.script("commit-candidate", "--close", receipt_id, "--dry-run", ok=False).stderr)
        self.assertEqual(before, self.snapshot(path.parent))

    def test_close_other_worktree_receipts_are_preserved(self):
        candidate, publication = self.close_bundle()
        other = self.root / "other-worktree"
        self.git("worktree", "add", "-q", "-b", "other", str(other))
        before = self.snapshot(self.receipt(candidate).parent)
        result = self.script("commit-candidate", "--close", candidate, publication, "--accept-unverified", cwd=other, ok=False)
        self.assertIn("another worktree", result.stderr)
        self.assertEqual(before, self.snapshot(self.receipt(candidate).parent))

    def test_close_all_interruption_boundaries_resume_without_tombstones(self):
        candidate, publication = self.close_bundle()
        paths = [self.receipt(receipt_id) for receipt_id in (candidate, publication)]
        originals = {path: (path.read_bytes(), path.with_suffix(".status").read_bytes()) for path in paths}
        store = paths[0].parent
        lock = (store / "lock").stat().st_ino
        before_git = self.snapshot(self.repo)
        for phase, target in (("mark", candidate), ("mark", publication), ("json", candidate),
                              ("status", candidate), ("json", publication), ("status", publication)):
            with self.subTest(phase=phase, target=target):
                self.interrupt_close((candidate, publication), phase, target)
                if phase != "mark":
                    for status_path in store.glob("*.status"):
                        self.assertEqual(json.loads(status_path.read_text())["state"], "closing")
                before = self.snapshot(store)
                self.script("commit-candidate", "--close", candidate, publication, "--dry-run")
                self.assertEqual(before, self.snapshot(store))
                # Provenance scanning must tolerate even a payload-less closing marker.
                runner = ('import os, runpy, sys; m=runpy.run_path(sys.argv[1]); '
                          'r=m["Records"](); os.chdir(r.top); r.committed()')
                self.run_command([sys.executable, "-I", "-c", runner, str(SKILLS / "commit/scripts/governance.py")])
                result = self.script("commit-candidate", "--close", candidate, publication)
                self.assertNotIn("outcome=UNVERIFIED", result.stdout)
                self.assertEqual([path.name for path in store.iterdir()], ["lock"])
                self.assertEqual((store / "lock").stat().st_ino, lock)
                self.assertEqual(before_git, self.snapshot(self.repo))
                for path, (payload, source) in originals.items():
                    path.write_bytes(payload)
                    path.chmod(0o400)
                    path.with_suffix(".status").write_bytes(source)
                    path.with_suffix(".status").chmod(0o600)

    def test_close_internal_marker_write_boundaries_leave_no_receipt_copies(self):
        candidate, publication = self.close_bundle()
        paths = [self.receipt(receipt_id) for receipt_id in (candidate, publication)]
        originals = {path: (path.read_bytes(), path.with_suffix(".status").read_bytes()) for path in paths}
        store = paths[0].parent
        lock = (store / "lock").stat().st_ino
        before_git = self.snapshot(self.repo)
        phases = ("fsync", "create", "partial-write", "write", "before-replace", "replace")
        for phase, target in ((phase, target) for phase in phases for target in (candidate, publication)):
            with self.subTest(phase=phase, target=target):
                self.interrupt_close((candidate, publication), phase, target)
                staging = store / f".close-{target}.write"
                self.assertEqual(staging.exists(), phase != "replace")
                if phase == "create":
                    self.assertEqual(staging.read_bytes(), b"")
                if phase == "partial-write":
                    prefix = staging.read_bytes()
                    self.assertTrue(prefix)
                    self.interrupt_close((candidate, publication), phase, target)
                    self.assertEqual(staging.read_bytes(), prefix)
                before = self.snapshot(store)
                self.script("commit-candidate", "--close", candidate, publication, "--dry-run")
                self.assertEqual(before, self.snapshot(store))
                self.script("commit-candidate", "--close", candidate, publication)
                self.assertEqual([path.name for path in store.iterdir()], ["lock"])
                self.assertEqual(lock, (store / "lock").stat().st_ino)
                self.assertEqual(before_git, self.snapshot(self.repo))
                for path, (payload, source) in originals.items():
                    path.write_bytes(payload)
                    path.chmod(0o400)
                    path.with_suffix(".status").write_bytes(source)
                    path.with_suffix(".status").chmod(0o600)

    def test_close_staging_preflight_preserves_mismatched_orphan_and_unsafe_entries(self):
        candidate, publication = self.close_bundle()
        path = self.receipt(candidate)
        originals = path.read_bytes(), path.with_suffix(".status").read_bytes()
        store = path.parent
        self.interrupt_close((candidate, publication), "partial-write", candidate)
        staging = store / f".close-{candidate}.write"
        prefix = staging.read_bytes()
        for defect in ("mismatch", "oversized", "orphan", "symlink", "hardlink", "public", "fifo", "directory"):
            with self.subTest(defect=defect):
                staging.unlink()
                external = self.root / "staging-target"
                external.write_bytes(prefix)
                external.chmod(0o600)
                if defect == "symlink":
                    staging.symlink_to(external)
                elif defect == "hardlink":
                    os.link(external, staging)
                elif defect == "fifo":
                    os.mkfifo(staging, 0o600)
                elif defect == "directory":
                    staging.mkdir(mode=0o700)
                else:
                    staging.write_bytes(b"unknown staging bytes" if defect == "mismatch" else
                                        b"x" * (5 * 1024 * 1024 + 1) if defect == "oversized" else prefix)
                    staging.chmod(0o644 if defect == "public" else 0o600)
                if defect == "orphan":
                    path.unlink()
                    path.with_suffix(".status").unlink()
                before = self.snapshot(store)
                for flags in ([], ["--dry-run"]):
                    result = self.script("commit-candidate", "--close", publication, candidate, *flags, ok=False)
                    self.assertNotIn("close-out complete", result.stdout)
                    self.assertEqual(before, self.snapshot(store))
                staging.rmdir() if defect == "directory" else staging.unlink()
                staging.write_bytes(prefix)
                staging.chmod(0o600)
                if defect == "orphan":
                    path.write_bytes(originals[0])
                    path.chmod(0o400)
                    path.with_suffix(".status").write_bytes(originals[1])
                    path.with_suffix(".status").chmod(0o600)
        unknown = store / ".write-unattributed"
        unknown.write_text("unknown writer; do not sweep\n")
        unknown.chmod(0o600)
        foreign = store / (".close-" + "f" * 64 + ".write")
        foreign.symlink_to(self.root / "missing")
        untouched = {name: self.snapshot(store)[name] for name in (unknown.name, foreign.name, "lock")}
        self.script("commit-candidate", "--close", publication, candidate)
        self.assertFalse(staging.exists())
        self.assertEqual(untouched, {name: self.snapshot(store)[name] for name in untouched})

    def test_close_staging_requires_original_selection_and_unverified_disposition(self):
        candidate, publication = self.close_bundle(verified=False)
        store = self.receipt(candidate).parent
        self.interrupt_close((candidate, publication), "fsync", candidate, "--accept-unverified")
        before = self.snapshot(store)
        for args in ((candidate, publication), (candidate, "--accept-unverified")):
            self.script("commit-candidate", "--close", *args, ok=False)
            self.assertEqual(before, self.snapshot(store))
        result = self.script("commit-candidate", "--close", candidate, publication, "--accept-unverified")
        self.assertEqual(result.stdout.count("outcome=UNVERIFIED"), 2)
        self.assertNotIn("outcome=verified", result.stdout)
        self.assertEqual([path.name for path in store.iterdir()], ["lock"])

    def test_close_staging_resumes_with_reordered_equally_eligible_publications(self):
        candidate, first = self.close_bundle()
        second, _ = self.binding()
        self.script("publish-verify", second)
        publications = sorted((first, second))
        paths = [self.receipt(receipt_id) for receipt_id in (candidate, *publications)]
        originals = {path: (path.read_bytes(), path.with_suffix(".status").read_bytes()) for path in paths}
        store = paths[0].parent
        lock = self.snapshot(store)["lock"]
        before_git = self.snapshot(self.repo)
        for mode in ("verified", "unverified", "mixed"):
            with self.subTest(mode=mode):
                if mode != "verified":
                    self.set_status(publications[0], "ready")
                if mode == "unverified":
                    self.set_status(publications[1], "ready")
                flags = [] if mode == "verified" else ["--accept-unverified"]
                self.interrupt_close((candidate, *reversed(publications)), "fsync", candidate, *flags)
                reordered = (publications[0], candidate, publications[1])
                before = self.snapshot(store)
                self.script("commit-candidate", "--close", *reordered, *flags, "--dry-run")
                self.assertEqual(before, self.snapshot(store))
                marker = json.loads((store / f".close-{candidate}.write").read_text())
                self.assertEqual(marker["coverage"]["id"], publications[1 if mode == "mixed" else 0])
                result = self.script("commit-candidate", "--close", *reordered, *flags)
                verified_count = {"verified": 3, "unverified": 0, "mixed": 2}[mode]
                self.assertEqual(result.stdout.count("outcome=verified"), verified_count)
                self.assertEqual(result.stdout.count("outcome=UNVERIFIED"), 3 - verified_count)
                self.assertEqual([path.name for path in store.iterdir()], ["lock"])
                self.assertEqual(lock, self.snapshot(store)["lock"])
                self.assertEqual(before_git, self.snapshot(self.repo))
                for path, (payload, source) in originals.items():
                    path.write_bytes(payload)
                    path.chmod(0o400)
                    path.with_suffix(".status").write_bytes(source)
                    path.with_suffix(".status").chmod(0o600)

    def test_close_unverified_recovery_requires_flag_and_validates_snapshots(self):
        candidate, publication = self.close_bundle(verified=False)
        path = self.receipt(candidate)
        self.interrupt_close((publication, candidate), "status", publication, "--accept-unverified")
        status_path = path.with_suffix(".status")
        original = status_path.read_bytes()
        before = self.snapshot(path.parent)
        self.script("commit-candidate", "--close", candidate, ok=False)
        self.assertEqual(before, self.snapshot(path.parent))
        marker = json.loads(original)
        for defect in ("payload", "coverage", "outcome", "version", "toplevel"):
            damaged = json.loads(original)
            if defect == "payload":
                damaged["payload"] += " "
            elif defect == "coverage":
                damaged["coverage"]["payload"] += " "
            elif defect == "outcome":
                damaged["outcome"] = "verified"
            elif defect == "version":
                damaged["version"] = 2
            else:
                payload = json.loads(damaged["payload"])
                payload["toplevel"] = str(self.root)
                damaged["payload"] = json.dumps(payload)
            status_path.write_text(json.dumps(damaged))
            before = self.snapshot(path.parent)
            self.script("commit-candidate", "--close", candidate, "--accept-unverified", ok=False)
            self.assertEqual(before, self.snapshot(path.parent))
        status_path.write_bytes(original)
        self.assertEqual(marker["outcome"], "UNVERIFIED")
        path.unlink()  # Resume at the payload/status boundary with no surviving publication.
        result = self.script("commit-candidate", "--close", candidate, publication, "--accept-unverified")
        self.assertEqual(result.stdout.count("outcome=UNVERIFIED"), 1)
        self.assertIn("absent: " + publication, result.stdout)
        self.assertNotIn("outcome=verified", result.stdout)

    def test_close_large_transient_marker_remains_readable_and_resumable(self):
        self.write("b.txt", "two\n")
        receipt_id = self.record("b.txt", message=MESSAGE + "\\" * 300000 + "\n")
        self.script("commit-candidate", "--clear", receipt_id)
        path = self.receipt(receipt_id)
        self.interrupt_close((receipt_id,), "json", receipt_id)
        self.assertGreater(path.with_suffix(".status").stat().st_size, 1024 * 1024)
        runner = ('import os, runpy, sys; m=runpy.run_path(sys.argv[1]); '
                  'r=m["Records"](); os.chdir(r.top); r.committed()')
        self.run_command([sys.executable, "-I", "-c", runner, str(SKILLS / "commit/scripts/governance.py")])
        self.script("commit-candidate", "--close", receipt_id)
        self.assertEqual([entry.name for entry in path.parent.iterdir()], ["lock"])

    def test_close_contention_uses_unchanged_common_directory_lock(self):
        candidate, publication = self.close_bundle()
        store = self.receipt(candidate).parent
        before = self.snapshot(store)
        with (store / "lock").open("rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for flags in ([], ["--dry-run"]):
                result = self.script("commit-candidate", "--close", candidate, publication, *flags, ok=False)
                self.assertIn("another governance operation is active", result.stderr)
                self.assertEqual(before, self.snapshot(store))
        self.script("commit-candidate", "--close", candidate, publication)
        self.assertEqual(before["lock"], self.snapshot(store)["lock"])

    def test_printed_command_carries_its_private_record_root(self):
        self.outbound()
        receipt_id, command = self.binding()
        terminal_env = {k: v for k, v in self.env.items() if k != "EYRAGENTS_RECORD_ROOT"}
        self.run_command(["bash", "--noprofile", "--norc", "-c", command], env=terminal_env, cwd=self.root)
        self.script("publish-verify", receipt_id)

    def test_environment_binding_ignores_session_and_auth_handles(self):
        self.outbound()
        initial = {**self.env, "SSH_TTY": "/dev/pts/900", "SSH_AUTH_SOCK": "/tmp/fake-agent-one",
                   "SSH_CONNECTION": "fixture connection one", "GIT_TRACE2_PARENT_SID": "session-one"}
        result = self.script("publish-bind", env=initial)
        receipt_id = re.search(r"^binding-id=([a-f0-9]{64})$", result.stdout, re.M)[1]
        changed = {**self.env, "SSH_TTY": "/dev/pts/901", "SSH_AUTH_SOCK": "/tmp/fake-agent-two",
                   "SSH_AGENT_PID": "900001", "SSH_CONNECTION": "fixture connection two",
                   "GIT_TRACE2_PARENT_SID": "session-two", "GIT_TERMINAL_PROMPT": "1"}
        self.script("publish-bind", "--check", receipt_id, env=changed)
        fingerprint = json.loads(self.receipt(receipt_id).read_text())["fingerprint"]
        self.assertNotIn("SSH_TTY", fingerprint["environment"])
        self.assertNotIn("SSH_AUTH_SOCK", fingerprint["environment"])
        changed["GIT_SSH_COMMAND"] = "ssh -F /tmp/private-routing-marker"
        result = self.script("publish-bind", "--check", receipt_id, env=changed, ok=False)
        self.assertIn("environment changed: GIT_SSH_COMMAND", result.stderr)
        self.assertNotIn("private-routing-marker", result.stdout + result.stderr)

    def test_environment_binding_tracks_executables_not_unrelated_path_entries(self):
        self.outbound()
        receipt_id, _ = self.binding()
        empty = self.root / "empty-bin"
        empty.mkdir()
        env = {**self.env, "PATH": str(empty) + ":" + self.env["PATH"]}
        self.script("publish-bind", "--check", receipt_id, env=env)
        env = self.git_shim(":")
        result = self.script("publish-bind", "--check", receipt_id, env=env, ok=False)
        self.assertIn("executables changed: git", result.stderr)
        self.assertNotIn(str(self.root / "tools"), result.stdout + result.stderr)

    def test_executable_auth_helper_change_is_not_a_harmless_auth_handle(self):
        self.outbound()
        receipt_id, _ = self.binding()
        env = {**self.env, "GIT_ASKPASS": "/tmp/private-helper-marker"}
        result = self.script("publish-bind", "--check", receipt_id, env=env, ok=False)
        self.assertIn("environment changed: GIT_ASKPASS", result.stderr)
        self.assertNotIn("private-helper-marker", result.stdout + result.stderr)

    def test_path_checks_are_deduplicated_and_batched(self):
        runtime = runpy.run_path(str(SKILLS / "commit/scripts/governance.py"))
        paths = [f"source/file-{number}.txt" for number in range(1000)] * 3
        with mock.patch.object(runtime["subprocess"], "run", return_value=subprocess.CompletedProcess([], 0, b"", b"")) as scanner:
            runtime["scan_paths"](paths)
        self.assertEqual(scanner.call_count, 1)
        self.assertEqual(scanner.call_args.kwargs["input"].count(b"+++ "), 1000)

    def test_inherited_sensitive_path_is_not_scanned_or_read(self):
        self.write(".env.example", "legacy-private-fixture-marker\n")
        self.git("add", ".env.example")
        self.git("commit", "-q", "-m", "chore: inherited fixture")
        old_blob = self.git("rev-parse", "HEAD:.env.example").stdout.strip()
        self.outbound()
        marker = self.root / "forbidden-read"
        env = self.git_shim(f'if test "$2" = ls-tree || {{ test "$2" = cat-file && test "$3" = blob && test "$4" = {old_blob}; }}; then\n'
                            f'touch "{marker}"\nexit 97\nfi')
        result = self.script("publish-bind", env=env)
        self.assertFalse(marker.exists())
        self.assertNotIn("legacy-private-fixture-marker", result.stdout + result.stderr)
        self.assertIn("scan=complete", result.stdout)
        # Reusing an old blob at a new sensitive name must fail before any blob read.
        self.git("update-index", "--add", "--cacheinfo", f"100644,{old_blob},copy/.aws/config")
        self.git("commit", "-q", "-m", "chore: copied sensitive path")
        result = self.script("publish-bind", env=env, ok=False)
        self.assertIn("sensitive-diff-path-v1", result.stderr)
        self.assertFalse(marker.exists())

    def test_rename_to_sensitive_path_with_base_blob_is_blocked(self):
        self.outbound()
        (self.repo / "copy/.aws").mkdir(parents=True)
        self.git("mv", "a.txt", "copy/.aws/config")
        self.git("commit", "-q", "-m", "chore: renamed fixture")
        result = self.script("publish-bind", ok=False)
        self.assertIn("publication changed paths", result.stderr)
        self.assertIn("sensitive-diff-path-v1", result.stderr)

    def test_scanner_relays_only_structurally_safe_locality(self):
        runtime = runpy.run_path(str(SKILLS / "commit/scripts/governance.py"))
        marker = "ghp_" + "F" * 32
        diagnostics = ("SPAR-PAYLOAD FINDING: reply:2: provider-b-token-v1\n"
                       "SPAR-PAYLOAD FINDING: reply:3: " + marker + "\n"
                       "SPAR-PAYLOAD FINDING: " + marker + ":4: provider-b-token-v1\n"
                       "SPAR-PAYLOAD REJECT: reply: " + marker + "\n"
                       "arbitrary Git/private diagnostic " + marker + "\n").encode()
        captured = io.StringIO()
        with mock.patch.object(runtime["subprocess"], "run", return_value=subprocess.CompletedProcess([], 2, b"", diagnostics)):
            with contextlib.redirect_stderr(captured), self.assertRaises(runtime["Refused"]):
                runtime["scan"](b"fixture", label="fixture object")
        self.assertEqual(captured.getvalue(), "fixture object: reply line=2 rule=provider-b-token-v1\n")
        self.assertNotIn(marker, captured.getvalue())

    def test_scanner_reports_real_object_and_line_without_value(self):
        marker = "ghp_" + "G" * 32
        self.write("finding.txt", "ordinary line\n" + marker + "\n")
        oid = self.git("hash-object", "finding.txt").stdout.strip()
        result = self.script("commit-candidate", "--stage", "--", "finding.txt", data=MESSAGE, ok=False)
        self.assertIn(f"blob {oid}: reply line=2 rule=provider-b-token-v1", result.stderr)
        self.assertNotIn(marker, result.stdout + result.stderr)

    def test_staging_refusal_names_add_not_global_option(self):
        self.write("new.txt", "fixture\n")
        env = self.git_shim('if test "$2" = add; then exit 1; fi')
        result = self.script("commit-candidate", "--stage", "--", "new.txt", data=MESSAGE, env=env, ok=False)
        self.assertIn("Git operation refused: add", result.stderr)
        self.assertNotIn("Git operation refused: -C", result.stderr)

    def test_default_preserves_mixed_hunks(self):
        self.write("a.txt", "intended\n")
        self.git("add", "a.txt")
        self.write("a.txt", "intended\nunrelated\n")
        before = self.git("write-tree").stdout
        receipt_id = self.record("a.txt", stage=False)
        self.assertEqual(before, self.git("write-tree").stdout)
        self.script("commit-apply", receipt_id)
        self.assertEqual(self.git("show", "HEAD:a.txt").stdout, "intended\n")
        self.assertEqual((self.repo / "a.txt").read_text(), "intended\nunrelated\n")
        self.assertIn("unrelated", self.git("diff").stdout)

    def test_stage_refuses_mixed_files_before_any_staging(self):
        self.write("a.txt", "intended\n")
        self.git("add", "a.txt")
        self.write("a.txt", "unrelated\n")
        self.write("b.txt", "also intended\n")
        before = (self.repo / ".git/index").read_bytes()
        self.script("commit-candidate", "--stage", "--", "b.txt", "a.txt", data=MESSAGE, ok=False)
        self.assertEqual(before, (self.repo / ".git/index").read_bytes())
        self.assertFalse(list((self.root / "records").glob("*/*.json")))

    def test_default_does_not_stage_new_file(self):
        self.write("b.txt", "new\n")
        self.script("commit-candidate", "--", "b.txt", data=MESSAGE, ok=False)
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout, "")

    def test_bad_message_and_sensitive_path_do_not_stage(self):
        self.write("b.txt", "new\n")
        for message in ("Bad subject\n\n" + TRAILER, "feat: missing trailer\n", MESSAGE + "\nClaude-Session: session_abcdefgh\n"):
            self.script("commit-candidate", "--stage", "--", "b.txt", data=message, ok=False)
        self.write("copy/.aws/config", "fixture\n")
        self.script("commit-candidate", "--stage", "--", "copy", data=MESSAGE, ok=False)
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout, "")
        self.assertFalse(list((self.root / "records").glob("*/*.json")))

    def test_private_record_root_is_enforced(self):
        self.write("b.txt", "new\n")
        records = self.root / "records"
        records.mkdir(mode=0o755)
        records.chmod(0o755)  # The unsafe fixture must not depend on caller umask.
        self.script("commit-candidate", "--stage", "--", "b.txt", data=MESSAGE, ok=False)
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout, "")

    def test_symlink_deletion_subdirectory_and_literal_scope(self):
        (self.repo / "link.txt").symlink_to("a.txt")
        receipt_id = self.record("link.txt")
        value = json.loads(self.receipt(receipt_id).read_text())
        self.assertIn("120000 blob", self.git("ls-tree", value["tree"], "link.txt").stdout)
        self.script("commit-apply", receipt_id)
        (self.repo / "link.txt").unlink()
        first = self.record("link.txt")
        second = self.record("link.txt")
        self.assertNotEqual(first, second)
        self.script("commit-apply", first)
        self.write("folder/new.txt", "nested\n")
        self.script("commit-candidate", "--stage", "--", "new.txt", data=MESSAGE, cwd=self.repo / "folder")
        self.script("commit-candidate", "--", "a.txt", data=MESSAGE, ok=False)
        self.script("commit-candidate", "--", "../outside", data=MESSAGE, ok=False)

    def test_explicit_receipts_coexist_and_consume(self):
        self.write("b.txt", "two\n")
        first = self.record("b.txt")
        second = self.record("b.txt", message=MESSAGE.replace("add content", "other message"))
        self.assertNotEqual(first, second)
        self.assertEqual(self.receipt(first).stat().st_mode & 0o777, 0o400)
        self.assertEqual(hashlib.sha256(self.receipt(first).read_bytes()).hexdigest(), first)
        self.script("commit-apply", ok=False)
        self.script("commit-apply", first)
        self.assertEqual(self.git("log", "-1", "--format=%B").stdout.rstrip(), MESSAGE.rstrip())
        self.script("commit-apply", first, ok=False)
        self.script("commit-apply", second, ok=False)
        self.assertEqual(self.status(first)["state"], "committed")
        self.assertEqual(self.status(second)["state"], "rejected")

    def test_digest_tampering_and_explicit_rejection(self):
        self.write("b.txt", "two\n")
        receipt_id = self.record("b.txt")
        path = self.receipt(receipt_id)
        path.chmod(0o600)
        path.write_bytes(path.read_bytes().replace(b"add content", b"new content"))
        self.script("commit-apply", receipt_id, ok=False)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.parent)
        fresh = self.record("b.txt")
        self.script("commit-candidate", "--clear", fresh)
        self.script("commit-apply", fresh, ok=False)
        self.assertEqual(self.git("show", ":b.txt").stdout, "two\n")

    def test_identity_overrides_and_index_drift_reject_before_commit(self):
        self.write("b.txt", "two\n")
        for key, value in [("GIT_AUTHOR_EMAIL", "other@example.test"), ("GIT_COMMITTER_EMAIL", "other@example.test"),
                           ("GIT_AUTHOR_NAME", "Other"), ("GIT_COMMITTER_NAME", "Other")]:
            receipt_id = self.record("b.txt")
            env = {**self.env, key: value}
            self.script("commit-apply", receipt_id, env=env, ok=False)
            self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.parent)
        receipt_id = self.record("b.txt")
        self.write("c.txt", "three\n")
        self.git("add", "c.txt")
        before = (self.repo / ".git/index").read_bytes()
        self.script("commit-apply", receipt_id, ok=False)
        self.assertEqual(self.git("show", ":c.txt").stdout, "three\n")
        self.assertEqual(before, (self.repo / ".git/index").read_bytes())

    def test_scanner_failure_leaves_no_receipt_or_raw_finding(self):
        marker = "ghp_" + "A" * 32
        self.write("b.txt", marker + "\n")
        result = self.script("commit-candidate", "--stage", "--", "b.txt", data=MESSAGE, ok=False)
        self.assertNotIn(marker, result.stdout + result.stderr)
        self.assertFalse(list((self.root / "records").glob("*/*.json")))
        self.write("copy/.aws/config", "fixture\n")
        self.script("commit-candidate", "--stage", "--", "copy", data=MESSAGE, ok=False)
        self.assertNotIn("copy", self.git("diff", "--cached", "--name-only").stdout)

    def test_binary_non_utf8_and_oversized_receipts_are_metadata_only(self):
        self.outbound()
        assets = {"binary.dat": b"binary-not-for-logs\0\xff",
                  "unreadable.dat": b"non-utf8-not-for-logs\xff",
                  "large.dat": b"oversized-not-for-logs" + b"x" * (1024 * 1024)}
        self.write(".gitattributes", "*.dat diff\n")
        for name, data in assets.items():
            self.write(name, data)
        out = self.script("commit-candidate", "--stage", "--", ".gitattributes", *assets, data=MESSAGE)
        receipt_id = re.search(r"^candidate-id=([a-f0-9]{64})$", out.stdout, re.M)[1]
        value = json.loads(self.receipt(receipt_id).read_text())
        self.assertEqual(value["scan"], "partial")
        self.assertTrue(value["manual_inspection_required"])
        self.assertIn("scan=partial; manual inspection required", out.stdout)
        self.assertNotIn("scan: accepted", out.stdout)
        self.assertEqual({item["reason"] for item in value["unscanned_objects"]}, {"binary", "non-utf8", "size-limit"})
        for item in value["unscanned_objects"]:
            location = item["locations"][0]
            self.assertEqual(location["tree"], value["tree"])
            self.assertEqual(item["size"], len(assets[location["path"]]))
            self.assertEqual(item["oid"], self.git("rev-parse", value["tree"] + ":" + location["path"]).stdout.strip())
        self.assertEqual(hashlib.sha256(self.receipt(receipt_id).read_bytes()).hexdigest(), receipt_id)
        applied = self.script("commit-apply", receipt_id)
        self.git("rm", "-q", "binary.dat")
        self.git("commit", "-q", "-m", "chore: remove transient binary")
        published = self.script("publish-bind")
        binding_id = re.search(r"^binding-id=([a-f0-9]{64})$", published.stdout, re.M)[1]
        bound = json.loads(self.receipt(binding_id).read_text())
        self.assertEqual(bound["scan"], "partial")
        self.assertTrue(bound["manual_inspection_required"])
        self.assertEqual({item["oid"] for item in bound["unscanned_objects"]}, {item["oid"] for item in value["unscanned_objects"]})
        self.assertTrue(any(location["path"] == "binary.dat" for item in bound["unscanned_objects"] for location in item["locations"]))
        shown = self.script("commit-candidate", "--show", receipt_id)
        outputs = out.stdout + out.stderr + applied.stdout + applied.stderr + published.stdout + published.stderr + shown.stdout
        for marker in ("binary-not-for-logs", "non-utf8-not-for-logs", "oversized-not-for-logs"):
            self.assertNotIn(marker, outputs + self.receipt(receipt_id).read_text() + self.receipt(binding_id).read_text())
        command = published.stdout.split("== command\n", 1)[1].strip()
        self.run_command(["bash", "-c", command])
        self.assertIn("scan=partial", self.script("publish-verify", binding_id).stdout)

    def test_manual_inspection_fields_are_digest_bound(self):
        self.write("asset.dat", b"fixture\0")
        receipt_id = self.record("asset.dat")
        path = self.receipt(receipt_id)
        value = json.loads(path.read_text())
        self.assertEqual(value["scan"], "partial")
        value["unscanned_objects"] = []
        value["manual_inspection_required"] = False
        value["scan"] = "complete"
        path.chmod(0o600)
        path.write_text(json.dumps(value))
        self.assertIn("receipt digest mismatch", self.script("commit-apply", receipt_id, ok=False).stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.parent)

    def test_publication_inspection_fields_are_digest_bound(self):
        remote = self.outbound()
        self.write("asset.dat", b"fixture\0")
        self.git("add", "asset.dat")
        self.git("commit", "-q", "-m", "chore: binary asset")
        receipt_id, command = self.binding()
        path = self.receipt(receipt_id)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), receipt_id)
        value = json.loads(path.read_text())
        self.assertTrue(value["unscanned_objects"])
        value["unscanned_objects"] = []
        value["manual_inspection_required"] = False
        value["scan"] = "complete"
        path.chmod(0o600)
        path.write_text(json.dumps(value))
        result = self.run_command(["bash", "-c", command], ok=False)
        self.assertIn("receipt digest mismatch", result.stderr)
        self.script("publish-verify", receipt_id, ok=False)
        self.assertEqual(self.git("--git-dir=" + str(remote), "rev-parse", "main").stdout.strip(), self.parent)

    def test_unreadable_blob_has_exact_metadata_without_raw_errors(self):
        self.outbound()
        self.write("unavailable.dat", "unavailable-private-marker\n")
        self.git("add", "unavailable.dat")
        oid = self.git("rev-parse", ":unavailable.dat").stdout.strip()
        tools = self.root / "tools"
        tools.mkdir()
        wrapper = tools / "git"
        wrapper.write_text('#!/bin/sh\nif test "$1" = --no-replace-objects && test "$2" = cat-file '
                           f'&& test "$3" = blob && test "$4" = {oid}; then\n'
                           'printf "unavailable-private-marker\\n" >&2\nexit 1\nfi\n'
                           f'exec {shlex.quote(shutil.which("git"))} "$@"\n')
        wrapper.chmod(0o755)
        env = {**self.env, "PATH": str(tools) + ":" + self.env["PATH"]}
        result = self.script("commit-candidate", "--", "unavailable.dat", data=MESSAGE, env=env)
        receipt_id = re.search(r"^candidate-id=([a-f0-9]{64})$", result.stdout, re.M)[1]
        value = json.loads(self.receipt(receipt_id).read_text())
        item = value["unscanned_objects"][0]
        self.assertEqual(item["oid"], oid)
        self.assertEqual(item["size"], 27)
        self.assertEqual(item["reason"], "unreadable")
        self.assertNotIn("unavailable-private-marker", result.stdout + result.stderr)
        self.script("commit-apply", receipt_id)
        result = self.script("publish-bind", env=env)
        binding_id = re.search(r"^binding-id=([a-f0-9]{64})$", result.stdout, re.M)[1]
        bound = json.loads(self.receipt(binding_id).read_text())
        self.assertEqual(bound["unscanned_objects"][0]["reason"], "unreadable")
        self.assertNotIn("unavailable-private-marker", result.stdout + result.stderr)

    def test_binary_sensitive_path_and_text_findings_still_block(self):
        self.outbound()
        self.write(".env", b"fixture\0\xff")
        self.script("commit-candidate", "--stage", "--", ".env", data=MESSAGE, ok=False)
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout, "")
        self.git("add", ".env")
        self.git("commit", "-q", "-m", "chore: synthetic sensitive path")
        before = set((self.root / "records").glob("*/*.json"))
        self.script("publish-bind", ok=False)
        self.assertEqual(before, set((self.root / "records").glob("*/*.json")))
        self.git("reset", "--hard", "HEAD~1")
        self.write("asset.dat", b"fixture\0")
        marker = "ghp_" + "C" * 32
        self.write("text.txt", marker + "\n")
        candidate = self.script("commit-candidate", "--stage", "--", "asset.dat", "text.txt", data=MESSAGE, ok=False)
        self.assertNotIn(marker, candidate.stdout + candidate.stderr)
        self.git("commit", "-q", "-m", "chore: synthetic content finding")
        published = self.script("publish-bind", ok=False)
        self.assertNotIn(marker, published.stdout + published.stderr)
        self.assertEqual(before, set((self.root / "records").glob("*/*.json")))

    def test_binary_version_does_not_hide_earlier_text_finding(self):
        self.outbound()
        marker = "ghp_" + "D" * 32
        self.write("asset.dat", marker + "\n")
        self.git("add", "asset.dat")
        self.git("commit", "-q", "-m", "chore: transient text")
        self.write("asset.dat", b"fixture\0")
        self.git("add", "asset.dat")
        self.git("commit", "-q", "-m", "chore: binary version")
        result = self.script("publish-bind", ok=False)
        self.assertNotIn(marker, result.stdout + result.stderr)

    def test_binary_preimage_does_not_block_text_replacement(self):
        self.write("a.txt", b"-- fixture\0\xff\n")
        self.git("add", "a.txt")
        self.git("commit", "-q", "-m", "chore: binary preimage")
        self.write(".gitattributes", "a.txt diff\n")
        self.write("a.txt", "readable replacement\n")
        receipt_id = self.record("a.txt", ".gitattributes")
        self.assertEqual(json.loads(self.receipt(receipt_id).read_text())["scan"], "complete")

    def test_single_text_line_at_the_scan_limit_stays_scannable(self):
        self.outbound()
        self.write("limit.txt", b"x" * (1024 * 1024))
        receipt_id = self.record("limit.txt")
        self.assertEqual(json.loads(self.receipt(receipt_id).read_text())["scan"], "complete")
        self.script("commit-apply", receipt_id)
        binding_id, _ = self.binding()
        self.assertEqual(json.loads(self.receipt(binding_id).read_text())["scan"], "complete")

    def test_hook_change_cas_preserves_original_index(self):
        self.write("b.txt", "two\n")
        self.write("hooked.txt", "hooked\n")
        receipt_id = self.record("b.txt")
        before = (self.repo / ".git/index").read_bytes()
        self.hook("pre-commit", "git add hooked.txt")
        result = self.script("commit-apply", receipt_id, ok=False)
        self.assertIn("exact commit CAS rejected", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.parent)
        self.assertEqual(before, (self.repo / ".git/index").read_bytes())
        self.assertEqual((self.repo / "hooked.txt").read_text(), "hooked\n")

    def test_message_hook_cas(self):
        self.write("b.txt", "two\n")
        receipt_id = self.record("b.txt")
        self.hook("commit-msg", 'printf "changed\\n" >>"$1"')
        result = self.script("commit-apply", receipt_id, ok=False)
        self.assertIn("exact commit CAS rejected", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.parent)

    def test_post_hook_checkout_is_not_switched_back(self):
        self.write("b.txt", "two\n")
        receipt_id = self.record("b.txt")
        self.hook("post-commit", "git checkout -q --detach HEAD")
        result = self.script("commit-apply", receipt_id, ok=False)
        self.assertIn("no safe compensation", result.stderr)
        self.git("symbolic-ref", "-q", "HEAD", ok=False)
        self.assertNotEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.parent)

    def test_concurrent_tip_is_not_rolled_back(self):
        self.write("b.txt", "two\n")
        receipt_id = self.record("b.txt")
        self.hook("post-commit", 'tree=$(git rev-parse HEAD^{tree})\n'
                  'other=$(printf "chore: other actor\\n" | git commit-tree "$tree" -p HEAD)\n'
                  'git update-ref -m other-actor refs/heads/main "$other" HEAD')
        result = self.script("commit-apply", receipt_id, ok=False)
        self.assertIn("no safe compensation", result.stderr)
        self.assertEqual(self.git("log", "-1", "--format=%s").stdout.strip(), "chore: other actor")
        self.assertNotEqual(self.status(receipt_id)["created"], self.git("rev-parse", "HEAD").stdout.strip())

    def test_ambiguous_reflog_and_failed_hook_preserve_state(self):
        self.write("b.txt", "two\n")
        receipt_id = self.record("b.txt")
        hook = self.hook("pre-commit", "exit 1")
        result = self.script("commit-apply", receipt_id, ok=False)
        self.assertIn("Git/hook refused commit", result.stderr)
        self.assertIn("creation outcome unknown", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.parent)
        hook.unlink()
        receipt_id = self.record("b.txt")
        marker = self.root / "nested-once"
        self.hook("post-commit", f'if test ! -e "{marker}"; then\ntouch "{marker}"\n'
                  'git commit -q --allow-empty -m "chore: nested"\nfi')
        result = self.script("commit-apply", receipt_id, ok=False)
        self.assertIn("cannot uniquely identify", result.stderr)
        self.assertEqual(self.git("log", "-1", "--format=%s").stdout.strip(), "chore: nested")

    def test_hook_refusal_diagnostics_are_scanned_capped_and_not_echoed(self):
        self.write("new.txt", "fixture\n")
        marker = "ghp_" + "H" * 32
        bodies = [f'printf "%s\\n" "{marker}" >&2\nexit 1',
                  'printf "private-correspondence-marker\\n" >&2\nexit 1',
                  'i=0\nwhile test "$i" -lt 1000; do printf "long-private-marker\\n" >&2; i=$((i+1)); done\nexit 1']
        for body in bodies:
            receipt_id = self.record("new.txt")
            self.hook("pre-commit", body)
            result = self.script("commit-apply", receipt_id, ok=False)
            self.assertIn("Git/hook refused commit", result.stderr)
            self.assertIn("creation outcome unknown", result.stderr)
            self.assertLess(len(result.stderr), 1024)
            self.assertNotIn(marker, result.stdout + result.stderr)
            self.assertNotIn("private-correspondence-marker", result.stderr)
            self.assertNotIn("long-private-marker", result.stderr)
            self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.parent)

    def test_remote_observation_auth_failure_is_noninteractive_and_unknown(self):
        self.outbound()
        validated = self.root / "noninteractive-validated"
        env = self.git_shim('case " $* " in\n*" ls-remote "*)\ncase " $* " in *" --get-url "*) ;; *)\n'
                            'test "$GIT_TERMINAL_PROMPT" = 0 || exit 91\n'
                            'test "$GIT_ASKPASS" = /bin/false || exit 92\n'
                            'test "$SSH_ASKPASS_REQUIRE" = never || exit 93\n'
                            'test "$GCM_INTERACTIVE" = never || exit 94\n'
                            'if read -r input; then exit 95; fi\n'
                            f'touch "{validated}"\n'
                            'printf "private-auth-error-marker\\n" >&2\nexit 128\n;; esac\n;; esac')
        result = self.script("publish-bind", env=env)
        receipt_id = re.search(r"^binding-id=([a-f0-9]{64})$", result.stdout, re.M)[1]
        result = self.script("publish-verify", receipt_id, env={**env, "GIT_TERMINAL_PROMPT": "1"}, ok=False)
        self.assertIn("authentication/network/transport", result.stderr)
        self.assertIn("outcome unknown", result.stderr)
        self.assertNotIn("private-auth-error-marker", result.stdout + result.stderr)
        self.assertTrue(validated.exists())
        self.assertEqual(self.status(receipt_id)["state"], "ready")

    def test_remote_observation_output_is_bounded_and_not_echoed(self):
        self.outbound()
        env = self.git_shim('case " $* " in\n*" ls-remote "*)\ncase " $* " in *" --get-url "*) ;; *)\n'
                            'while :; do printf "private-response-marker\\n"; done\n;; esac\n;; esac')
        result = self.script("publish-bind", env=env)
        receipt_id = re.search(r"^binding-id=([a-f0-9]{64})$", result.stdout, re.M)[1]
        result = self.script("publish-verify", receipt_id, env=env, ok=False)
        self.assertIn("response limit", result.stderr)
        self.assertIn("outcome unknown", result.stderr)
        self.assertNotIn("private-response-marker", result.stdout + result.stderr)

    def test_remote_observation_malformed_metadata_is_unknown(self):
        self.outbound()
        env = self.git_shim('case " $* " in\n*" ls-remote "*)\ncase " $* " in *" --get-url "*) ;; *)\n'
                            'printf "private-malformed-response\\n"\nexit 0\n;; esac\n;; esac')
        result = self.script("publish-bind", env=env)
        receipt_id = re.search(r"^binding-id=([a-f0-9]{64})$", result.stdout, re.M)[1]
        result = self.script("publish-verify", receipt_id, env=env, ok=False)
        self.assertIn("malformed or ambiguous metadata", result.stderr)
        self.assertIn("outcome unknown", result.stderr)
        self.assertNotIn("private-malformed-response", result.stdout + result.stderr)

    def test_remote_observation_timeout_stops_descendants(self):
        self.outbound()
        marker = self.root / "escaped-child"
        env = self.git_shim('case " $* " in\n*" ls-remote "*)\ncase " $* " in *" --get-url "*) ;; *)\n'
                            f'(sleep 2; touch "{marker}") &\nwait\nexit 128\n;; esac\n;; esac')
        result = self.script("publish-bind", env=env)
        receipt_id = re.search(r"^binding-id=([a-f0-9]{64})$", result.stdout, re.M)[1]
        runner = ('import runpy, sys; path=sys.argv[1]; receipt=sys.argv[2]; module=runpy.run_path(path); '
                  'module["observe_remote"].__globals__["OBSERVE_TIMEOUT"]=0.25; '
                  'sys.argv=[path,"verify",receipt]; sys.exit(module["main"]())')
        started = time.monotonic()
        result = self.run_command([sys.executable, "-I", "-c", runner, str(SKILLS / "commit/scripts/governance.py"), receipt_id], env=env, ok=False)
        self.assertLess(time.monotonic() - started, 3)
        self.assertIn("observation timed out", result.stderr)
        self.assertIn("outcome unknown", result.stderr)
        time.sleep(2.1)
        self.assertFalse(marker.exists())
        self.assertEqual(self.status(receipt_id)["state"], "ready")

    def test_remote_observation_preserves_custom_ssh_transport(self):
        remote = self.outbound()
        self.git("push", "-q", "origin", "HEAD:refs/heads/main")
        transport = self.root / "chosen-ssh"
        argv_log = self.root / "ssh-arguments"
        transport.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" >"{argv_log}"\n'
                             f'exec {shlex.quote(shutil.which("git-upload-pack"))} {shlex.quote(str(remote))}\n')
        transport.chmod(0o755)
        self.git("config", "remote.origin.pushurl", "ssh://fixture.invalid/repository")
        env = {**self.env, "GIT_SSH_COMMAND": shlex.join([str(transport), "-F", "fixture-config"]), "GIT_SSH_VARIANT": "ssh"}
        result = self.script("publish-bind", env=env)
        receipt_id = re.search(r"^binding-id=([a-f0-9]{64})$", result.stdout, re.M)[1]
        self.script("publish-verify", receipt_id, env=env)
        args = argv_log.read_text().splitlines()
        self.assertEqual(args[0], "-oBatchMode=yes")
        self.assertIn("-oStrictHostKeyChecking=yes", args)
        self.assertIn("-oAddKeysToAgent=no", args)
        self.assertIn("-F", args)
        self.assertIn("fixture-config", args)
        result = self.script("publish-bind", env=env)
        fresh_id = re.search(r"^binding-id=([a-f0-9]{64})$", result.stdout, re.M)[1]
        transport.write_text(transport.read_text() + "# changed transport\n")
        result = self.script("publish-bind", "--check", fresh_id, env=env, ok=False)
        self.assertIn("executables changed: ssh", result.stderr)
        self.assertNotIn(str(transport), result.stdout + result.stderr)

    def test_opaque_ssh_transport_is_not_silently_replaced(self):
        self.outbound()
        self.git("config", "remote.origin.pushurl", "ssh://fixture.invalid/repository")
        env = {**self.env, "GIT_SSH_COMMAND": "ssh $PRIVATE_ROUTING_MARKER"}
        result = self.script("publish-bind", env=env)
        receipt_id = re.search(r"^binding-id=([a-f0-9]{64})$", result.stdout, re.M)[1]
        result = self.script("publish-verify", receipt_id, env=env, ok=False)
        self.assertIn("observation unknown", result.stderr)
        self.assertIn("without changing transport", result.stderr)
        self.assertNotIn("PRIVATE_ROUTING_MARKER", result.stdout + result.stderr)

    def test_cooperating_applies_are_serialized_and_index_edits_survive(self):
        self.write("b.txt", "two\n")
        self.write("c.txt", "concurrent\n")
        receipt_id = self.record("b.txt")
        marker = self.root / "entered"
        release = self.root / "release"
        self.hook("pre-commit", f'touch "{marker}"\nwhile test ! -f "{release}"; do sleep 0.02; done')
        command = [str(SKILLS / "commit/scripts/commit-apply"), receipt_id]
        first = subprocess.Popen(command, cwd=self.repo, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: first.poll() is None and first.kill())
        deadline = time.monotonic() + 8
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(marker.exists(), "hook barrier not reached")
        second = subprocess.Popen(command, cwd=self.repo, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: second.poll() is None and second.kill())
        self.git("add", "c.txt")
        before = (self.repo / ".git/index").read_bytes()
        release.touch()
        first.communicate(timeout=15)
        second.communicate(timeout=15)
        self.assertEqual(first.returncode, 0)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(before, (self.repo / ".git/index").read_bytes())
        self.assertEqual(self.git("show", ":c.txt").stdout, "concurrent\n")
        self.git("cat-file", "-e", "HEAD:c.txt", ok=False)

    def test_publish_local_endpoint_and_stale_tracking(self):
        remote = self.outbound()
        receipt_id, command = self.binding()
        bound = json.loads(self.receipt(receipt_id).read_text())
        self.assertEqual(bound["endpoint"], str(remote))
        self.assertIn("-- origin ", command)
        self.assertNotIn(str(remote), command)
        self.assertIn("--no-follow-tags", command)
        self.assertIn("--recurse-submodules=no", command)
        self.script("publish-verify", ok=False)
        self.script("publish-verify", receipt_id, ok=False)
        self.run_command(["bash", "-c", command], cwd=self.root)
        self.assertEqual(self.git("rev-parse", "refs/remotes/origin/main").stdout.strip(), bound["reviewed"])
        self.git("update-ref", "refs/remotes/origin/main", self.parent)
        out = self.script("publish-verify", receipt_id).stdout
        self.assertIn("remote observed:", out)
        self.assertIn("informational only", out)
        self.assertIn("none defined", out)
        self.script("publish-verify", receipt_id, ok=False)

    def test_consecutive_printed_pushes_update_tracking_without_fetch(self):
        remote = self.outbound()
        self.git("config", "remote.origin.push", "refs/heads/main:refs/heads/unreviewed")
        first_id, first_command = self.binding()
        first = json.loads(self.receipt(first_id).read_text())
        self.assertEqual(first["base"], self.parent)
        self.run_command(["bash", "-c", first_command], cwd=self.root)
        self.assertEqual(self.git("rev-parse", "refs/remotes/origin/main").stdout.strip(), first["reviewed"])
        self.script("publish-verify", first_id)
        self.write("next.txt", "next commit\n")
        candidate_id = self.record("next.txt")
        self.script("commit-apply", candidate_id)
        second_id, second_command = self.binding()
        second = json.loads(self.receipt(second_id).read_text())
        self.assertEqual(second["base"], first["reviewed"])
        self.assertNotEqual(second["reviewed"], first["reviewed"])
        self.run_command(["bash", "-c", second_command], cwd=self.root)
        self.assertEqual(self.git("rev-parse", "refs/remotes/origin/main").stdout.strip(), second["reviewed"])
        self.assertEqual(self.git("--git-dir=" + str(remote), "rev-parse", "main").stdout.strip(), second["reviewed"])
        self.assertEqual(self.git("--git-dir=" + str(remote), "for-each-ref", "--format=%(refname)").stdout.splitlines(), ["refs/heads/main"])
        self.script("publish-verify", second_id)

    def test_binding_fingerprint_and_exact_lease(self):
        remote = self.outbound()
        receipt_id, command = self.binding()
        self.git("config", "push.followTags", "true")
        self.script("publish-bind", "--check", receipt_id, ok=False)
        self.run_command(["bash", "-c", command], ok=False)
        fresh, command = self.binding()
        self.git("tag", "-a", "v1", "-m", "version one")
        self.run_command(["bash", "-c", command])
        self.assertEqual(self.git("--git-dir=" + str(remote), "tag").stdout, "")
        self.script("publish-verify", fresh)
        # The original reviewed base cannot be substituted with a newer tip.
        _, command = self.binding()
        reviewed = self.git("rev-parse", "HEAD").stdout.strip()
        tree = self.git("rev-parse", "HEAD^{tree}").stdout.strip()
        other = self.git("--git-dir=" + str(remote), "-c", "user.name=Test", "-c",
                         "user.email=1+test@users.noreply.github.com", "commit-tree", tree,
                         "-p", reviewed, data="chore: another actor\n").stdout.strip()
        self.git("--git-dir=" + str(remote), "update-ref", "refs/heads/main", other)
        self.run_command(["bash", "-c", command], ok=False)

    def test_destination_change_and_rewrites_require_review(self):
        self.outbound()
        receipt_id, command = self.binding()
        self.git("config", "remote.origin.pushurl", str(self.root / "elsewhere.git"))
        self.script("publish-bind", "--check", receipt_id, ok=False)
        self.script("publish-verify", receipt_id, ok=False)
        self.run_command(["bash", "-c", command], ok=False)
        self.git("config", "--unset-all", "remote.origin.pushurl")
        self.script("publish-bind", "--check", receipt_id, ok=False)
        self.git("config", "url." + str(self.root / "first.git") + ".pushInsteadOf", str(self.root / "remote.git"))
        self.git("config", "url." + str(self.root / "second.git") + ".pushInsteadOf", str(self.root / "first.git"))
        self.script("publish-bind", ok=False)

    def test_printed_preflight_blocks_remote_alias_and_url_mutations(self):
        remote = self.outbound()
        alternate = self.root / "alternate.git"
        self.git("clone", "-q", "--bare", str(remote), str(alternate))
        cases = [("remote.origin.url", str(alternate), str(remote)),
                 ("remote.origin.pushurl", str(alternate), None),
                 ("url." + str(alternate) + ".insteadOf", str(remote), None),
                 ("remotes.origin", "origin other", None)]
        for key, replacement, restore in cases:
            with self.subTest(key=key):
                receipt_id, command = self.binding()
                self.git("config", key, replacement)
                self.run_command(["bash", "-c", command], ok=False)
                self.assertEqual(self.status(receipt_id)["state"], "rejected")
                for destination in (remote, alternate):
                    self.assertEqual(self.git("--git-dir=" + str(destination), "rev-parse", "main").stdout.strip(), self.parent)
                self.assertEqual(self.git("rev-parse", "refs/remotes/origin/main").stdout.strip(), self.parent)
                if restore is None:
                    self.git("config", "--unset-all", key)
                else:
                    self.git("config", key, restore)

    def test_local_destination_spaces_and_hookspath(self):
        remote = self.outbound()
        destination = self.root / "push destination.git"
        self.git("clone", "-q", "--bare", str(remote), str(destination))
        self.git("config", "remote.origin.pushurl", str(destination))
        receipt_id, command = self.binding()
        self.run_command(["bash", "-c", command], cwd=self.root)
        self.script("publish-verify", receipt_id)
        hook_dir = self.root / "custom-hooks"
        hook_dir.mkdir()
        self.git("config", "core.hooksPath", str(hook_dir))
        hook = hook_dir / "pre-push"
        hook.write_text("#!/bin/sh\nexit 0\n")
        hook.chmod(0o755)
        receipt_id, _ = self.binding()
        bound = json.loads(self.receipt(receipt_id).read_text())
        self.assertEqual(bound["pre_push_hook"]["target"], str(hook))
        self.assertTrue(bound["hook_review_required"])

    def test_core_hookspath_symlink_is_inventoried_and_runs(self):
        self.outbound()
        hook_dir = self.repo / "custom-hooks"
        hook_dir.mkdir()
        self.git("config", "core.hooksPath", "custom-hooks")
        marker = self.root / "hook-ran"
        body = f'#!/bin/sh\nprintf "%s\\n" "$1" >"{marker}"\n'
        target = self.root / "hook-implementation"
        target.write_text(body)
        target.chmod(0o755)
        (hook_dir / "pre-push").symlink_to(target)
        result = self.script("publish-bind")
        receipt_id = re.search(r"^binding-id=([a-f0-9]{64})$", result.stdout, re.M)[1]
        value = json.loads(self.receipt(receipt_id).read_text())
        hook = value["pre_push_hook"]
        self.assertTrue(value["hook_review_required"])
        self.assertTrue(hook["executable"])
        self.assertTrue(hook["symlink"])
        self.assertEqual(hook["target"], str(target))
        self.assertEqual(hook["link_target"], str(target))
        self.assertEqual(hook["mode"], "0755")
        self.assertEqual(hook["sha256"], hashlib.sha256(body.encode()).hexdigest())
        self.assertIn("pre-push hooks: 1; H's behavior review required", result.stdout)
        self.assertNotIn("printf", result.stdout + result.stderr)
        self.assertFalse(marker.exists())
        command = result.stdout.split("== command\n", 1)[1].strip()
        self.assertIn("--verify", command)
        self.run_command(["bash", "-c", command], cwd=self.root)
        self.assertEqual(marker.read_text(), "origin\n")
        self.assertIn("fingerprint unchanged", self.script("publish-verify", receipt_id).stdout)

    def test_hook_mutation_blocks_preflight_and_post_push_verification(self):
        remote = self.outbound()
        marker = self.root / "hook-ran"
        hook = self.hook("pre-push", f'touch "{marker}"')
        receipt_id, command = self.binding()
        before = hook.stat()
        hook.write_text(hook.read_text().replace("touch", "touch # changed\ntouch"))
        os.utime(hook, ns=(before.st_atime_ns, before.st_mtime_ns))
        result = self.run_command(["bash", "-c", command], ok=False)
        self.assertIn("hook changed", result.stderr)
        self.assertFalse(marker.exists())
        self.assertEqual(self.git("--git-dir=" + str(remote), "rev-parse", "main").stdout.strip(), self.parent)
        self.assertEqual(self.status(receipt_id)["state"], "rejected")
        # A new reviewed hook may run, but changing it after the push is still
        # detected by verify rather than silently validating a different hook.
        hook.write_text(f'#!/bin/sh\ntouch "{marker}"\n')
        fresh, command = self.binding()
        self.run_command(["bash", "-c", command])
        hook.chmod(0o700)
        self.script("publish-verify", fresh, ok=False)
        self.assertEqual(self.status(fresh)["state"], "rejected")

    def test_unsafe_sensitive_or_unreadable_hook_targets_block(self):
        self.outbound()
        target = self.root / "implementation"
        target.write_text("#!/bin/sh\nexit 0\n")
        link = self.repo / ".git/hooks/pre-push"
        link.symlink_to(target)
        for mode in (0o777, 0o000):
            target.chmod(mode)
            self.script("publish-bind", ok=False)
        target.chmod(0o755)
        marker = "ghp_" + "E" * 32
        target.write_text("#!/bin/sh\n# " + marker + "\nexit 0\n")
        result = self.script("publish-bind", ok=False)
        self.assertNotIn(marker, result.stdout + result.stderr)
        link.unlink()
        sensitive = self.write("copy/.aws/config", "#!/bin/sh\nexit 0\n")
        sensitive.chmod(0o755)
        link.symlink_to(sensitive)
        self.script("publish-bind", ok=False)
        link.unlink()
        link.symlink_to(self.root / "missing")
        self.script("publish-bind", ok=False)

    def test_detached_explicit_destination(self):
        self.outbound()
        self.git("checkout", "-q", "--detach", "HEAD")
        self.script("publish-bind", ok=False)
        self.script("publish-bind", "--remote", "origin", "--branch", "main")

    def test_non_utf8_commit_metadata_blocks_binding(self):
        self.outbound()
        parent = self.git("rev-parse", "HEAD").stdout.strip()
        tree = self.git("rev-parse", "HEAD^{tree}").stdout.strip()
        ident = "Test <1+test@users.noreply.github.com> 1767225600 +0000"
        raw = f"tree {tree}\nparent {parent}\nauthor {ident}\ncommitter {ident}\n\nchore: metadata\n\n".encode() + b"\xff\n"
        result = subprocess.run(["git", "hash-object", "-t", "commit", "-w", "--stdin"], input=raw,
                                capture_output=True, cwd=self.repo, env=self.env, check=True)
        oid = result.stdout.decode().strip()
        self.git("update-ref", "refs/heads/main", oid)
        result = self.script("publish-bind", ok=False)
        self.assertIn("metadata scan rejected", result.stderr)
        self.assertIn(oid, result.stderr)
        self.assertNotIn("== command", result.stdout)

    def test_pushurl_is_observed_not_fetch_url(self):
        self.outbound()
        push_remote = self.root / "push.git"
        self.git("clone", "-q", "--bare", str(self.root / "remote.git"), str(push_remote))
        self.git("config", "remote.origin.pushurl", str(push_remote))
        receipt_id, command = self.binding()
        bound = json.loads(self.receipt(receipt_id).read_text())
        self.assertEqual(bound["endpoint"], str(push_remote))
        self.assertEqual(bound["base"], self.parent)
        # Tracking can claim the reviewed ID while the bound push endpoint is
        # still at the base. Verification must observe the endpoint, not infer it.
        self.git("update-ref", "refs/remotes/origin/main", bound["reviewed"])
        self.script("publish-verify", receipt_id, ok=False)
        self.run_command(["bash", "-c", command])
        self.assertEqual(self.git("--git-dir=" + str(self.root / "remote.git"), "rev-parse", "main").stdout.strip(), self.parent)
        result = self.script("publish-verify", receipt_id)
        self.assertIn("remote observed: " + bound["reviewed"], result.stdout)
        self.assertIn("informational only", result.stdout)

    def test_unsafe_destination_scope_and_hooks(self):
        self.outbound()
        cases = [("remote.origin.pushurl", "https://fixture:example-password@example.test/repo"),
                 ("remote.origin.pushurl", "ext::fixture"), ("push.pushOption", "scope=expanded"),
                 ("remote.origin.mirror", "true"), ("remote.origin.receivepack", "custom-command"),
                 ("remotes.origin", "origin other")]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                self.git("config", key, value)
                result = self.script("publish-bind", ok=False)
                if value.startswith("https://"):
                    self.assertIn("embedded endpoint credentials are forbidden", result.stderr)
                self.assertNotIn(value, result.stdout + result.stderr)
                self.assertNotIn("== command", result.stdout)
                self.git("config", "--unset-all", key)
        self.git("config", "--add", "remote.origin.pushurl", str(self.root / "one.git"))
        self.git("config", "--add", "remote.origin.pushurl", str(self.root / "two.git"))
        self.script("publish-bind", ok=False)
        self.git("config", "--unset-all", "remote.origin.pushurl")
        hook = self.root / "hook"
        hook.write_text("#!/bin/sh\nexit 0\n")
        hook.chmod(0o777)
        (self.repo / ".git/hooks/pre-push").symlink_to(hook)
        self.script("publish-bind", ok=False)

    def test_transient_content_merge_resolution_metadata_and_binary(self):
        self.outbound()
        base = self.git("rev-parse", "HEAD").stdout.strip()
        marker = "ghp_" + "B" * 32
        self.write("transient.txt", marker + "\n")
        self.git("add", "transient.txt")
        self.git("commit", "-q", "-m", "chore: temporary")
        self.git("rm", "-q", "transient.txt")
        self.git("commit", "-q", "-m", "chore: remove temporary")
        result = self.script("publish-bind", ok=False)
        self.assertNotIn(marker, result.stdout + result.stderr)
        self.git("reset", "--hard", base)
        self.git("checkout", "-q", "-b", "topic")
        self.write("topic.txt", "topic\n")
        self.git("add", "topic.txt")
        self.git("commit", "-q", "-m", "chore: topic")
        self.git("checkout", "-q", "main")
        self.git("merge", "--no-ff", "--no-commit", "topic")
        self.write("resolution.txt", marker + "\n")
        self.git("add", "resolution.txt")
        self.git("commit", "-q", "-m", "chore: merge")
        self.git("rm", "-q", "resolution.txt")
        self.git("commit", "-q", "-m", "chore: remove resolution")
        self.script("publish-bind", ok=False)
        self.git("reset", "--hard", base)
        self.git("commit", "--allow-empty", "-q", "-m", "chore: metadata\n\n" + marker)
        self.script("publish-bind", ok=False)
        self.git("reset", "--hard", base)
        self.write("binary.dat", b"\0\xfffixture")
        self.git("add", "binary.dat")
        self.git("commit", "-q", "-m", "chore: binary")
        receipt_id, _ = self.binding()
        value = json.loads(self.receipt(receipt_id).read_text())
        self.assertEqual(value["scan"], "partial")
        self.assertEqual(value["unscanned_objects"][0]["reason"], "binary")

    def test_old_topic_merge_does_not_rescan_published_paths(self):
        self.outbound()
        self.git("branch", "old-topic", self.parent)
        self.write(".env.example", "inherited placeholder\n")
        self.git("add", ".env.example")
        self.git("commit", "-q", "-m", "chore: published example")
        self.git("push", "-q", "origin", "main")
        base = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("checkout", "-q", "old-topic")
        self.write("topic.txt", "ordinary change\n")
        self.git("add", "topic.txt")
        self.git("commit", "-q", "-m", "chore: old topic")
        self.git("checkout", "-q", "main")
        self.git("merge", "--no-ff", "--no-commit", "old-topic")
        self.write("resolution.txt", "ordinary merge-only change\n")
        self.write("resolution.dat", b"\0synthetic merge-only asset")
        self.git("add", "resolution.txt", "resolution.dat")
        self.git("commit", "-q", "-m", "chore: merge old topic")
        receipt_id, _ = self.binding()
        value = json.loads(self.receipt(receipt_id).read_text())
        self.assertEqual(value["scan"], "partial")
        self.assertEqual([entry["reason"] for entry in value["unscanned_objects"]], ["binary"])
        self.assertEqual(value["unscanned_objects"][0]["locations"][0]["path"], "resolution.dat")
        # An actual merge-only sensitive path must still be rejected.
        self.git("reset", "--hard", base)
        self.git("merge", "--no-ff", "--no-commit", "old-topic")
        self.write("copy/.aws/config", "synthetic fixture\n")
        self.git("add", "copy/.aws/config")
        self.git("commit", "-q", "-m", "chore: merge with forbidden path")
        self.script("publish-bind", ok=False)

    def test_publish_identity_destructive_no_upstream_and_verifier(self):
        self.outbound()
        base = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("-c", "user.email=other@example.test", "commit", "--allow-empty", "-q", "-m", "chore: identity")
        self.assertIn("IDENTITY", self.script("publish-bind", ok=False).stderr)
        self.git("reset", "--hard", base)
        self.write("Makefile", "verify-published:\n\t@test \"$(REV)\" = \"$(shell git rev-parse HEAD)\"\n")
        receipt_id, command = self.binding()
        self.run_command(["bash", "-c", command])
        self.assertIn("make verify-published", self.script("publish-verify", receipt_id).stdout)
        self.git("checkout", "-q", "-b", "unconfigured")
        self.script("publish-bind", ok=False)
        self.git("checkout", "-q", "main")
        self.git("update-ref", "refs/remotes/origin/main", base)
        self.git("reset", "--hard", self.parent)
        self.git("commit", "--allow-empty", "-q", "-m", "chore: diverge")
        self.assertIn("DESTRUCTIVE", self.script("publish-bind", ok=False).stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
