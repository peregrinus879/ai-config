"""Exact-candidate and publication receipts for the four shell entrypoints.

Private immutable JSON receipts are SHA-256 addressed; mutable status is separate.
A common-Git-directory flock serializes cooperating operations across worktrees.
This is trusted-repository governance, not isolation from malicious hooks/config
or a same-user process. Git and scanners' rejected bytes never reach diagnostics.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import unquote, urlsplit
import uuid


SCRIPTS = Path(__file__).resolve().parent
SCANNER = SCRIPTS / "../../spar/scripts/spar-payload-scan"
LIMIT = 1024 * 1024
DIAGNOSTIC_LIMIT = 8192
OBSERVE_TIMEOUT = 30
NOREPLY = re.compile(r"[^\s<>@]+@users\.noreply\.github\.com")
# Bind routing, executable selection, config roots/overrides, and TLS policy.
# SSH_AUTH_SOCK/SSH_AGENT_PID are authentication handles, not destination or
# executable selectors. Connection/TTY metadata and prompt policy are excluded.
BOUND_ENV = frozenset("""
HOME XDG_CONFIG_HOME GIT_DIR GIT_COMMON_DIR GIT_WORK_TREE GIT_NAMESPACE
LD_PRELOAD LD_LIBRARY_PATH LD_AUDIT BASH_ENV ENV
GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_INDEX_FILE
GIT_CONFIG GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM GIT_CONFIG_NOSYSTEM
GIT_CONFIG_COUNT GIT_CONFIG_PARAMETERS GIT_EXEC_PATH
GIT_SSH GIT_SSH_COMMAND GIT_SSH_VARIANT GIT_PROXY_COMMAND GIT_ALLOW_PROTOCOL
GIT_PROTOCOL_FROM_USER GIT_PROTOCOL GIT_ASKPASS SSH_ASKPASS
GIT_SSL_NO_VERIFY GIT_SSL_CAINFO GIT_SSL_CAPATH GIT_SSL_VERSION GIT_SSL_CIPHER_LIST
SSL_CERT_FILE SSL_CERT_DIR CURL_CA_BUNDLE
http_proxy https_proxy all_proxy no_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY
""".split())
SCANNER_RULES = frozenset("""
sensitive-diff-path-v1 malformed-diff-path-v1 key-envelope-v1
provider-a-token-v1 provider-b-token-v1 provider-c-token-v1 cloud-access-id-v1
credential-assignment-v1 url-credential-v1 package-auth-value-v1 netrc-value-v1
""".split())


class Refused(Exception):
    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


def require(condition, message, code=2):
    if not condition:
        raise Refused(message, code)


def git(*args, data=None, env=None, check=True):
    result = subprocess.run(["git", "--no-replace-objects", *args], input=data,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    require(not check or result.returncode == 0, "Git operation refused: " + args[0])
    return result.stdout if check else result


def text(*args):
    return git(*args).decode("utf-8").rstrip("\n")


def config(key):
    result = git("config", "--null", "--get-all", key, check=False)
    require(result.returncode in (0, 1), "cannot resolve Git configuration")
    return [v.decode("utf-8") for v in result.stdout.split(b"\0")[:-1]]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def private_dir(path):
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and not info.st_mode & 0o077, "record directory must be private, owned, and not a symlink")


def read_private(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077, "unsafe record file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(LIMIT + 1)
        require(len(data) <= LIMIT, "record exceeds limit")
        return data
    finally:
        os.close(fd)


def atomic(path, data, immutable=False):
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            if immutable:
                os.fchmod(stream.fileno(), 0o400)
        if immutable:
            os.link(name, path)
        else:
            os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class Records:
    def __init__(self):
        self.cwd = os.getcwd()
        self.top = text("rev-parse", "--show-toplevel")
        common = text("rev-parse", "--path-format=absolute", "--git-common-dir")
        root = Path(os.environ.get("EYRAGENTS_RECORD_ROOT", f"/tmp/eyragents-{os.getuid()}"))
        require(root.is_absolute(), "record root must be absolute")
        private_dir(root)
        self.path = root / digest(os.fsencode(common))
        private_dir(self.path)
        self.lock = os.open(self.path / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        info = os.fstat(self.lock)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077, "unsafe record lock")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refused("another governance operation is active; retry after it finishes") from None

    def status(self, receipt_id, state=None, **extra):
        path = self.path / f"{receipt_id}.status"
        if state is not None:
            atomic(path, encoded({"id": receipt_id, "state": state, **extra}))
        value = json.loads(read_private(path))
        require(value["id"] == receipt_id, "status does not match receipt")
        return value

    def create(self, kind, value):
        value = {"version": 1, "kind": kind, "toplevel": self.top,
                 "nonce": uuid.uuid4().hex, **value}
        data = encoded(value)
        require(len(data) <= LIMIT, "receipt exceeds limit; no record created")
        receipt_id = digest(data)
        atomic(self.path / f"{receipt_id}.json", data, immutable=True)
        self.status(receipt_id, "ready")
        return receipt_id

    def read(self, receipt_id, kind, ready=True):
        require(re.fullmatch(r"[a-f0-9]{64}", receipt_id), "an explicit 64-character receipt ID is required")
        data = read_private(self.path / f"{receipt_id}.json")
        require(digest(data) == receipt_id, "receipt digest mismatch")
        value = json.loads(data)
        require(value["version"] == 1 and value["kind"] == kind
                and value["toplevel"] == self.top, "receipt has the wrong kind or worktree")
        status_value = self.status(receipt_id)
        require(not ready or status_value["state"] == "ready", "receipt is already consumed or rejected")
        return value

    def committed(self):
        commits = set()
        for path in self.path.glob("*.status"):
            value = json.loads(read_private(path))
            if value.get("state") == "committed":
                receipt_id = value["id"]
                require(path.stem == receipt_id and re.fullmatch(r"[a-f0-9]{64}", receipt_id), "invalid provenance status")
                data = read_private(self.path / f"{receipt_id}.json")
                require(digest(data) == receipt_id and json.loads(data)["kind"] == "candidate", "invalid provenance receipt")
                commits.add(value["commit"])
        return commits


def scan(data, mode="reply", label="payload"):
    result = subprocess.run([str(SCANNER), mode], input=data,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode:
        # Relay only the scanner's known structural grammar, never arbitrary
        # stderr, free-form rejection messages, or captured payload fragments.
        for line in result.stderr[:DIAGNOSTIC_LIMIT].splitlines()[:16]:
            match = re.fullmatch(rb"SPAR-PAYLOAD FINDING: (reply|diff):([1-9][0-9]{0,8}): ([a-z0-9-]+)", line)
            if match and match[3].decode() in SCANNER_RULES:
                print(f"{label}: {match[1].decode()} line={match[2].decode()} rule={match[3].decode()}", file=sys.stderr)
            for reason, code in (("binary content", "binary-input"), ("non-UTF-8 content", "non-utf8-input"),
                                 (f"{mode} exceeds the review limit", "size-limit")):
                if line == f"SPAR-PAYLOAD REJECT: {mode}: {reason}".encode():
                    print(f"{label}: {mode} reason={code}", file=sys.stderr)
        raise Refused(f"{label}: payload scanner rejected {mode} input; raw diagnostics withheld")


def scan_paths(paths, label="paths"):
    chunk = b""
    start = 1
    for number, path in enumerate(sorted(set(paths)), 1):
        # JSON quoting matches Git's quoting for ordinary UTF-8 names. Control
        # characters are conservatively refused by the scanner, not normalized.
        line = ("+++ " + json.dumps("b/" + path, ensure_ascii=False) + "\n").encode()
        require(len(line) <= LIMIT, f"{label}: path metadata exceeds scanner limit")
        if len(chunk) + len(line) > LIMIT:
            scan(chunk, "diff", f"{label} starting at path {start}")
            chunk = b""
            start = number
        chunk += line
    if chunk:
        scan(chunk, "diff", f"{label} starting at path {start}")


def names(*args):
    return [p.decode("utf-8") for p in git(*args).split(b"\0") if p]


def identity():
    expected_email = config("user.email")
    expected_name = config("user.name")
    require(expected_email and NOREPLY.fullmatch(expected_email[-1]), "Git identity is not a GitHub no-reply address")
    require(expected_name and expected_name[-1], "Git identity has no name")
    result = {}
    for role in ("author", "committer"):
        ident = text("var", f"GIT_{role.upper()}_IDENT")
        match = re.fullmatch(r"(.+) <([^<>]+)> [0-9]+ [+-][0-9]{4}", ident)
        require(match and match[1] == expected_name[-1] and match[2] == expected_email[-1],
                "effective author/committer differs from configured no-reply identity")
        result[role] = [match[1], match[2]]
    return result


def privacy(data, label):
    value = data.decode("utf-8", errors="replace")
    terms = [os.environ.get("HOME", ""), os.environ.get("USER", ""), socket.gethostname()]
    count = sum(bool(term and re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", value, re.I)) for term in terms)
    count += bool(re.search(r"/(?:home|Users)/|Claude-Session:|session_[A-Za-z0-9]{8,}", value))
    print(f"privacy screen ({label}): {count} identifier classes; review required" if count
          else f"privacy screen ({label}): no automatic identifier hits; human review still required")


def scan_blob(oid, locations, unscanned):
    size = int(text("cat-file", "-s", oid))
    reason = "size-limit" if size > LIMIT else None
    data = None
    if not reason:
        result = git("cat-file", "blob", oid, check=False)
        data = result.stdout
        if result.returncode:
            reason = "unreadable"
        elif b"\0" in data:
            reason = "binary"
        else:
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                reason = "non-utf8"
    if reason:
        unscanned.append({"oid": oid, "type": "blob", "size": size, "reason": reason, "locations": locations})
        return None
    # An actual scanner rejection is never converted into manual inspection.
    scan(data, label=f"blob {oid}")
    return data


def diff_paths(unscanned, paths=None):
    excluded = sorted({location["path"] for item in unscanned for location in item["locations"]})
    included = ["."] if paths is None else [":(literal)" + path for path in paths]
    return ["--", *included, *[":(exclude,literal)" + path for path in excluded]]


def scan_diff(*args, unscanned, label="diff", paths=None):
    patch = git(*args, *diff_paths(unscanned, paths))
    # Match the scanner's addition-only scope before UTF-8 decoding: old
    # deleted/context bytes are not new content. Unsupported new blobs have
    # already been inventoried and excluded, even if attributes force text diffs.
    lines = []
    in_hunk = False
    for line in patch.split(b"\n"):
        if line.startswith(b"diff "):
            in_hunk = False
        elif line.startswith(b"@@"):
            in_hunk = True
        if (in_hunk and line.startswith(b"+")) or (not in_hunk and line.startswith((b"diff ", b"--- ", b"+++ ", b"rename ", b"copy "))):
            lines.append(line + b"\n")
    chunk = b""
    for line in lines:
        # A raw value at the scanner limit still fits without the diff's added
        # prefix/newline. Scan that value directly, never waive a size finding.
        if len(line) > LIMIT and line.startswith(b"+") and not line.startswith(b"+++ "):
            scan(line[1:-1], label=label)
            continue
        require(len(line) <= LIMIT, "diff line exceeds scan limit; cannot complete the diff check")
        if len(chunk) + len(line) > LIMIT:
            scan(chunk, "diff", label)
            chunk = b""
        chunk += line
    scan(chunk, "diff", label)
    return b"".join(lines)


def report_inspection(value):
    print("scan=" + value["scan"] + ("; manual inspection required" if value["manual_inspection_required"] else ""))
    for item in value["unscanned_objects"]:
        print("manual-inspection: " + json.dumps(item, sort_keys=True))
    if value["manual_inspection_required"]:
        print("H's approval/publication is conditional on inspecting these exact objects; inspection is not machine-attested")


def candidate(records, args):
    parser = argparse.ArgumentParser(prog="commit-candidate")
    parser.add_argument("--stage", action="store_true")
    parser.add_argument("--message-file")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--show")
    actions.add_argument("--clear")
    parser.add_argument("paths", nargs="*")
    opts = parser.parse_args(args)
    if opts.show or opts.clear:
        require(not opts.stage and not opts.message_file and not opts.paths, "show/clear cannot be combined with candidate options")
        receipt_id = opts.show or opts.clear
        value = records.read(receipt_id, "candidate", ready=False)
        if opts.clear:
            require(records.status(receipt_id)["state"] == "ready", "only a ready candidate can be rejected")
            records.status(receipt_id, "rejected")
            print(f"candidate rejected: {receipt_id}; index and worktree preserved")
        else:
            print(f"candidate-id={receipt_id}\nstatus={records.status(receipt_id)['state']}")
            print(json.dumps(value, indent=2))
        return
    require(opts.paths, "name the intended paths", 64)
    require(not os.environ.get("GIT_INDEX_FILE"), "an alternate caller index is not supported")
    message_path = Path(records.cwd, opts.message_file).resolve() if opts.message_file else None
    if message_path:
        scan_paths([str(Path(records.cwd, opts.message_file).absolute()), str(message_path)])
        with message_path.open("rb") as stream:
            message = stream.read(LIMIT + 1)
    else:
        message = sys.stdin.buffer.read(LIMIT + 1)
    scan(message, label="candidate message")
    message = message.decode("utf-8").rstrip("\n") + "\n"
    lines = message.splitlines()
    require(lines and re.match(r"^(feat|fix|docs|refactor|style|test|chore)(\([^)]+\))?: [a-z0-9]", lines[0])
            and len(lines[0]) <= 50, "invalid conventional subject (maximum 50 characters)")
    require(len(lines) > 2 and not lines[1], "the second message line must be blank")
    require(re.search(r"(?m)^Co-Authored-By: .+ <noreply@(anthropic\.com|openai\.com)>$", message), "missing vendor no-reply co-author trailer")
    require(not re.search(r"claude\.ai/code|Claude-Session:|session_[A-Za-z0-9]{8,}", message, re.I), "message carries session metadata")
    who = identity()
    scan(encoded(who))
    branch = text("symbolic-ref", "-q", "HEAD")
    parent = text("rev-parse", "--verify", "HEAD^{commit}")
    paths = [os.path.relpath(os.path.abspath(os.path.join(records.cwd, p)), records.top) for p in opts.paths]
    require(all(p != "." and p != ".." and not p.startswith("../") and ".git" not in p.split("/") for p in paths), "intended paths must be literal, scoped paths inside the worktree")
    scan_paths(paths)

    def covered(path):
        return any(path == p or path.startswith(p + "/") for p in paths)

    staged = names("diff", "--cached", "--name-only", "--no-renames", "-z")
    require(all(covered(p) for p in staged), "index holds an unrelated staged change")
    if opts.stage:
        unstaged = names("diff", "--name-only", "--no-renames", "-z")
        require(not set(staged).intersection(unstaged), "--stage refuses partially staged mixed files; index unchanged")
        additions = names("ls-files", "--others", "--exclude-standard", "-z")
        scan_paths([p for p in [*unstaged, *additions] if covered(p)])
        to_add = [p for p in paths if os.path.lexists(Path(records.top) / p)
                  or git("ls-files", "--error-unmatch", "--", ":(literal)" + p, check=False).returncode == 0]
        if to_add:
            git("add", "--", *[":(literal)" + p for p in to_add])
    tree = text("write-tree")
    require(tree != text("rev-parse", parent + "^{tree}"), "nothing is staged")
    staged = names("diff", "--name-only", "--no-renames", "-z", parent, tree)
    require(all(covered(p) for p in staged), "index scope changed during preparation")
    scan_paths(staged)
    locations = {}
    for entry in git("ls-tree", "-r", "-z", tree).split(b"\0"):
        if not entry:
            continue
        meta, path = entry.split(b"\t", 1)
        _, kind, oid = meta.decode().split()
        if path.decode("utf-8") in staged:
            require(kind == "blob", "submodule content requires a separate review")
            locations.setdefault(oid, []).append({"tree": tree, "path": path.decode("utf-8")})
    unscanned = []
    for oid, where in locations.items():
        scan_blob(oid, where, unscanned)
    patch = scan_diff("diff", "--no-ext-diff", "--no-textconv", "--no-renames", parent, tree, unscanned=unscanned)
    require(parent == text("rev-parse", "HEAD") and branch == text("symbolic-ref", "-q", "HEAD")
            and who == identity() and tree == text("write-tree"), "candidate changed during scanning")
    value = {"tree": tree, "parent": parent, "branch": branch, "message": message, "identity": who, "paths": paths,
             "scan": "partial" if unscanned else "complete", "unscanned_objects": unscanned,
             "manual_inspection_required": bool(unscanned)}
    receipt_id = records.create("candidate", value)
    print("== stat (scannable paths; manual objects listed below)\n"
          + git("diff", "--stat", "--no-ext-diff", "--no-textconv", parent, tree, *diff_paths(unscanned)).decode("utf-8"), end="")
    print(f"== candidate\ncandidate-id={receipt_id}\ntree={tree}\nparent={parent}\nbranch={branch}")
    report_inspection(value)
    equals = git("diff", "--quiet", check=False).returncode == 0
    print("worktree equals index: " + ("yes (tracked files only)" if equals else "no; worktree gates do not attest this exact tree"))
    print(f"untracked: {len(names('ls-files', '--others', '--exclude-standard', '-z'))} paths; classify separately")
    privacy(b"\n".join(line for line in patch.splitlines() if line.startswith(b"+")) + message.encode(), "candidate")
    print("== message\n" + message, end="")


def apply(records, args):
    require(len(args) == 1, "usage: commit-apply ID", 64)
    receipt_id = args[0]
    value = records.read(receipt_id, "candidate")
    action = "eyragents-" + uuid.uuid4().hex
    records.status(receipt_id, "applying", reflog_action=action)
    created = None
    try:
        require(not os.environ.get("GIT_INDEX_FILE"), "an alternate caller index is not supported")
        for state in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
            require(not Path(text("rev-parse", "--git-path", state)).exists(), "unfinished Git operation; stop for H")
        # Git and its hooks use only this disposable index. The original index
        # is never copied back, even when a hook or another actor edits it.
        with tempfile.TemporaryDirectory(prefix="apply-", dir=records.path) as scratch:
            index = Path(scratch) / "index"
            index.write_bytes(Path(text("rev-parse", "--git-path", "index")).read_bytes())
            env = dict(os.environ, GIT_INDEX_FILE=str(index), GIT_REFLOG_ACTION=action)
            require(git("write-tree", env=env).decode().strip() == value["tree"]
                    and text("rev-parse", "HEAD") == value["parent"]
                    and text("symbolic-ref", "-q", "HEAD") == value["branch"]
                    and identity() == value["identity"], "candidate drifted; present a fresh receipt")
            require(all(git("reflog", "exists", ref, check=False).returncode == 0 for ref in ("HEAD", value["branch"])),
                    "HEAD and branch reflogs are required to identify the created commit")
            index.unlink()
            git("read-tree", value["tree"], env=env)
            result = git("commit", "--quiet", "--cleanup=verbatim", "--file=-", data=value["message"].encode(), env=env, check=False)
        events = set()
        logs = git("reflog", "show", "--all", "--format=%H%x00%gs", check=False)
        for line in logs.stdout.splitlines():
            oid, sep, message = line.partition(b"\0")
            if sep and message.startswith((action + ":").encode()):
                events.add(oid.decode("ascii"))
        if result.returncode and not events:
            if result.stderr:
                # Cap before scanning, and do not echo even scanner-accepted
                # Git/hook text: it can contain private, non-token information.
                try:
                    scan(result.stderr[:DIAGNOSTIC_LIMIT], label="commit stderr (capped)")
                except Refused:
                    pass
                print("commit stderr: raw text withheld", file=sys.stderr)
            raise Refused(f"Git/hook refused commit (exit {result.returncode}); no matching reflog evidence; "
                          f"creation outcome unknown, state preserved; inspect action {action} with H", 3)
        require(len(events) == 1, f"cannot uniquely identify this invocation's commit; state preserved, inspect reflog action {action} with H; matching IDs: "
                + (", ".join(sorted(events)) or "none"))
        created = events.pop()
        raw = git("cat-file", "commit", created)
        headers, _, message = raw.partition(b"\n\n")
        fields = headers.splitlines()
        parents = [line[7:].decode() for line in fields if line.startswith(b"parent ")]
        expected_identities = value["identity"]
        same_identity = all(any(re.fullmatch(re.escape((role + " " + who[0] + " <" + who[1] + ">").encode())
                                            + rb" [0-9]+ [+-][0-9]{4}", line) for line in fields)
                            for role, who in expected_identities.items())
        matches = (result.returncode == 0 and b"tree " + value["tree"].encode() in fields
                   and parents == [value["parent"]] and message == value["message"].encode() and same_identity)
        position = (git("symbolic-ref", "-q", "HEAD", check=False).stdout.strip().decode() == value["branch"]
                    and text("rev-parse", value["branch"]) == created)
        if not matches or not position:
            # Only the exact commit identified by this invocation may be CAS'd.
            # Never sample an arbitrary new tip as the expected old value, and
            # never switch a checkout that a hook or another actor moved.
            compensated = False
            if position and parents == [value["parent"]]:
                compensated = git("update-ref", "--no-deref", "-m", "commit-apply: rejected candidate",
                                  value["branch"], value["parent"], created, check=False).returncode == 0
            raise Refused(f"created {created} differs from the candidate or checkout; "
                          + ("exact commit CAS rejected; index/worktree preserved" if compensated else "no safe compensation; state preserved for H"), 3)
        records.status(receipt_id, "committed", commit=created)
        print(f"hash: {created} {value['message'].splitlines()[0]}\ncandidate-id={receipt_id}")
    except BaseException:
        records.status(receipt_id, "rejected", created=created, reflog_action=action)
        raise


def pre_push_hook():
    hook = Path(text("rev-parse", "--git-path", "hooks/pre-push")).absolute()
    scan_paths([str(hook)])
    target = hook.resolve()
    scan_paths([str(target)])
    value = {"path": str(hook), "target": str(target), "exists": False, "executable": False, "symlink": hook.is_symlink()}
    try:
        link_info = hook.lstat()
    except FileNotFoundError:
        return value
    except OSError:
        raise Refused("cannot inspect effective pre-push hook path") from None
    if value["symlink"]:
        value["link_target"] = os.readlink(hook)
        scan_paths([str(hook.parent / value["link_target"])])
    try:
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid in (0, os.getuid())
                    and info.st_nlink == 1 and not info.st_mode & 0o6022 and info.st_mode & 0o444,
                    "unsafe or unreadable pre-push hook target")
            require(info.st_size <= LIMIT, "pre-push hook exceeds inspection limit")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                data = stream.read(LIMIT + 1)
            after = os.fstat(fd)
            require(all(getattr(after, field) == getattr(info, field) for field in
                        ("st_dev", "st_ino", "st_size", "st_mode", "st_uid", "st_mtime_ns", "st_ctime_ns"))
                    and hook.lstat().st_ino == link_info.st_ino and hook.resolve() == target,
                    "pre-push hook changed during inspection")
        finally:
            os.close(fd)
    except OSError:
        raise Refused("unreadable pre-push hook target; binding refused") from None
    scan(data, label="pre-push hook")
    value.update(exists=True, executable=os.access(hook, os.X_OK), mode=f"{stat.S_IMODE(info.st_mode):04o}",
                 link_mode=f"{stat.S_IMODE(link_info.st_mode):04o}", uid=info.st_uid, size=info.st_size,
                 mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns, sha256=digest(data))
    return value


def ssh_arguments():
    configured = config("core.sshCommand")
    command = os.environ.get("GIT_SSH_COMMAND", configured[-1] if configured else None)
    if command is None:
        return [os.environ.get("GIT_SSH", "ssh")]
    if re.search(r"[\x00-\x1f$`~;&|<>()*?\[\]]", command):
        return None
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    if not argv or argv[0] in ("env", "exec") or "=" in argv[0]:
        return None
    return argv


def transport_fingerprint(endpoint):
    environment = {name: digest(os.fsencode(value)) for name, value in os.environ.items()
                   if name in BOUND_ENV or re.fullmatch(r"GIT_CONFIG_(?:KEY|VALUE)_[0-9]+", name)}
    # PATH often differs between an agent and H's terminal. Bind the actual
    # selected programs rather than unrelated PATH entries or terminal metadata.
    programs = {"git": "git"}
    if endpoint.startswith("ssh://") or (not endpoint.startswith(("https://", "/")) and ":" in endpoint):
        argv = ssh_arguments()
        programs["ssh"] = argv[0] if argv else None
    for name in ("GIT_ASKPASS", "SSH_ASKPASS"):
        if name in os.environ:
            programs[name] = os.environ[name]
    askpass = config("core.askPass")
    if askpass and "GIT_ASKPASS" not in os.environ:
        programs["core.askPass"] = askpass[-1]
    executables = {}
    for name, program in programs.items():
        found = shutil.which(program) if program else None
        if found:
            path = Path(found).resolve()
            info = path.stat()
            executables[name] = digest(encoded([str(path), info.st_dev, info.st_ino, info.st_mode,
                                               info.st_size, info.st_mtime_ns, info.st_ctime_ns]))
        else:
            executables[name] = None
    return environment, executables


def destination(remote):
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", remote), "unsupported remote name")
    require(not config("remotes." + remote), "remote-group collision; destination is ambiguous")
    urls = git("remote", "get-url", "--push", "--all", remote).decode("utf-8").splitlines()
    require(len(urls) == 1, "exactly one push URL is required")
    endpoint = urls[0]
    require(endpoint and not any(ord(c) < 32 or ord(c) == 127 for c in endpoint), "unsupported push destination")
    if "://" in endpoint:
        parts = urlsplit(endpoint)
        require(not any(c.isspace() for c in endpoint), "unsupported URL whitespace")
        require(parts.scheme in ("https", "ssh", "file") and not parts.query and not parts.fragment,
                "unsupported push protocol or URL suffix")
        require(parts.password is None and (parts.scheme == "ssh" or parts.username is None), "embedded endpoint credentials are forbidden")
        if parts.username:
            require(re.fullmatch(r"[A-Za-z0-9._-]+", unquote(parts.username)), "unsupported SSH user")
        require(not re.search(r"[\x00-\x1f\x7f]", unquote(endpoint)), "encoded endpoint controls are forbidden")
        if parts.scheme == "file":
            require(parts.netloc in ("", "localhost") and parts.path.startswith("/"), "unsupported file destination")
            endpoint = str(Path(unquote(parts.path)).resolve())
        else:
            require(parts.hostname and re.fullmatch(r"[A-Za-z0-9.:-]+", parts.hostname)
                    and parts.path.startswith("/") and (parts.port is None or parts.port > 0), "invalid push endpoint")
    elif re.fullmatch(r"(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9.-]+:[^:]+", endpoint):
        require(not endpoint.startswith("-"), "unsupported push endpoint")
    else:
        require(endpoint.startswith(("/", "./", "../")) and ":" not in endpoint, "unsupported push protocol or destination")
        endpoint = str(Path(endpoint).resolve())
    scan(endpoint.encode())
    require(endpoint not in text("remote").splitlines() and not config("remotes." + endpoint), "resolved endpoint collides with a remote or group")
    # Passing the resolved URL must not trigger a second insteadOf rewrite.
    require(text("ls-remote", "--get-url", endpoint) == endpoint, "resolved endpoint would be rewritten again")
    rewrites = git("config", "--null", "--get-regexp", r"^url\..*\.pushinsteadof$", check=False)
    require(rewrites.returncode in (0, 1), "cannot resolve push URL rewrites")
    for entry in rewrites.stdout.split(b"\0"):
        if entry:
            _, _, prefix = entry.partition(b"\n")
            require(not endpoint.startswith(prefix.decode("utf-8")), "resolved push endpoint would be rewritten again")
    require(not any(config("push.pushOption")), "configured push options require separate scope review")
    for key in ("mirror", "receivepack", "vcs"):
        values = config(f"remote.{remote}.{key}")
        require(not values or (key == "mirror" and all(v.lower() in ("false", "no", "off", "0") for v in values)), "remote has scope-expanding or unsupported push configuration")
    hook_state = pre_push_hook()
    keys = r"^(remote\.|remotes\.|url\.|push\.|branch\.|core\.(hookspath|sshcommand|gitproxy|askpass)|ssh\.|protocol\.|http\.|credential\.)"
    settings = git("config", "--null", "--get-regexp", keys, check=False)
    require(settings.returncode in (0, 1), "cannot fingerprint push configuration")
    environment, executables = transport_fingerprint(endpoint)
    fingerprint = {"configuration": digest(settings.stdout), "hook": digest(encoded(hook_state)),
                   "endpoint": digest(endpoint.encode()), "environment": environment, "executables": executables}
    return endpoint, fingerprint, hook_state


def check_binding(records, receipt_id):
    value = records.read(receipt_id, "publish")
    try:
        endpoint, fingerprint, hook = destination(value["remote"])
        previous = value["fingerprint"]
        require(isinstance(previous, dict), "binding fingerprint format changed; rebind and review")
        changed = [component + " changed" for component in ("endpoint", "configuration", "hook")
                   if fingerprint[component] != previous[component]]
        for component in ("environment", "executables"):
            names_changed = sorted(name for name in fingerprint[component].keys() | previous[component].keys()
                                   if fingerprint[component].get(name) != previous[component].get(name))
            if names_changed:
                changed.append(component + " changed: " + ", ".join(names_changed))
        require(not changed, "binding " + "; ".join(changed) + "; rebind and review")
        require(endpoint == value["endpoint"] and hook == value["pre_push_hook"], "binding scope changed; rebind and review")
    except Refused:
        records.status(receipt_id, "rejected")
        raise
    return value


def bind(records, args):
    parser = argparse.ArgumentParser(prog="publish-bind")
    parser.add_argument("--remote")
    parser.add_argument("--branch")
    parser.add_argument("--check")
    parser.add_argument("ref", nargs="?", default="HEAD")
    opts = parser.parse_args(args)
    if opts.check:
        require(not opts.remote and not opts.branch and opts.ref == "HEAD", "--check takes only a binding ID")
        check_binding(records, opts.check)
        print(f"binding unchanged: {opts.check} (point-in-time check)")
        return
    require(bool(opts.remote) == bool(opts.branch), "--remote and --branch are required together", 64)
    reviewed = text("rev-parse", "--verify", "--end-of-options", opts.ref + "^{commit}")
    local = (git("symbolic-ref", "--short", "-q", "HEAD", check=False).stdout.decode().strip()
             if opts.ref == "HEAD" else opts.ref.removeprefix("refs/heads/"))
    remote, branch = opts.remote, opts.branch
    if not remote:
        upstream_remote = config(f"branch.{local}.remote")
        upstream_merge = config(f"branch.{local}.merge")
        require(len(upstream_remote) == len(upstream_merge) == 1 and upstream_merge[0].startswith("refs/heads/"), "no single configured upstream; H must name a destination", 3)
        remote, branch = upstream_remote[0], upstream_merge[0].removeprefix("refs/heads/")
    require(git("check-ref-format", "refs/heads/" + branch, check=False).returncode == 0, "invalid destination branch")
    endpoint, fingerprint, hook = destination(remote)
    tracking = f"refs/remotes/{remote}/{branch}"
    result = git("rev-parse", "--verify", tracking + "^{commit}", check=False)
    require(result.returncode == 0, "no tracking baseline; first publication needs complete-history review", 4)
    base = result.stdout.decode().strip()
    require(git("merge-base", "--is-ancestor", base, reviewed, check=False).returncode == 0, "DESTRUCTIVE: reviewed commit does not descend from the tracking baseline; stop for H", 5)
    ids = text("rev-list", "--reverse", base + ".." + reviewed).splitlines()
    scan(encoded({"remote": remote, "branch": branch, "local": local}))
    print(f"== binding\nremote={remote}\nbranch={branch}\nreviewed={reviewed}\nbase={base} (tracking ref, assumed without a fetch)")
    print("== delta")
    committed = records.committed()
    objects = text("rev-list", "--objects", "--no-object-names", reviewed, "^" + base).splitlines()
    new_objects = set(objects)
    changed_paths = set()
    commit_paths = {}
    postimages = []
    # Combined merge records contain paths differing from every parent. Paths
    # inherited from one parent were already covered there (or in the base).
    # Keep no-renames so a new sensitive name cannot hide behind an old blob.
    for oid in ids:
        commit_paths[oid] = set()
        entries = git("diff-tree", "--root", "-r", "-c", "--no-commit-id", "--raw", "--no-abbrev", "--no-renames", "-z", oid).split(b"\0")
        require(entries[-1] == b"" and len(entries) % 2 == 1, "malformed per-parent path inventory")
        for header, path in zip(entries[0:-1:2], entries[1::2]):
            fields = header.split()
            parents = len(fields[0]) - len(fields[0].lstrip(b":")) if fields else 0
            require(parents > 0 and len(fields) == 2 * parents + 3, "malformed change record")
            path = path.decode("utf-8")
            changed_paths.add(path)
            commit_paths[oid].add(path)
            blob = fields[-2].decode("ascii")
            if blob in new_objects:
                postimages.append((oid, path, blob))
    scan_paths(changed_paths, "publication changed paths")
    unscanned = []
    for oid in objects:
        kind = text("cat-file", "-t", oid)
        if kind == "blob":
            data = scan_blob(oid, [], unscanned)
            if data is not None:
                privacy(data, oid[:12] + " content")
        else:
            require(kind in ("commit", "tree"), f"unsupported outbound object {oid}; binding refused")
    manual = {item["oid"]: item for item in unscanned}
    trees = {}
    for oid, path, blob in postimages:
        if blob in manual:
            if oid not in trees:
                trees[oid] = text("rev-parse", oid + "^{tree}")
            location = {"tree": trees[oid], "path": path}
            if location not in manual[blob]["locations"]:
                manual[blob]["locations"].append(location)
    require(all(item["locations"] for item in unscanned), "cannot locate an outbound manual-inspection object")
    for oid in ids:
        raw = git("cat-file", "commit", oid)
        try:
            scan(raw, label=f"commit {oid} metadata")
        except Refused:
            raise Refused(f"commit {oid}: metadata scan rejected; no raw findings displayed") from None
        headers, _, message = raw.partition(b"\n\n")
        for role in (b"author", b"committer"):
            match = re.search(rb"(?m)^" + role + rb" .+ <([^<>\n]+)> [0-9]+ [+-][0-9]{4}$", headers)
            require(match and NOREPLY.fullmatch(match[1].decode()), f"commit {oid}: IDENTITY finding; no binding recorded")
        if commit_paths[oid]:
            scan_diff("diff-tree", "--root", "-r", "-m", "-p", "--no-ext-diff", "--no-textconv", "--no-renames", oid,
                      paths=sorted(commit_paths[oid]),
                      unscanned=unscanned, label=f"commit {oid} patch")
        privacy(raw, oid[:12] + " metadata")
        provenance = "made through commit-apply" if oid in committed else "commit-apply provenance unknown"
        print(f"{oid} {json.dumps(message.decode().splitlines()[0] if message else '')} [{provenance}; gates still required]")
    scan_diff("diff", "--no-ext-diff", "--no-textconv", "--no-renames", base, reviewed, unscanned=unscanned, label="publication flat diff")
    require(destination(remote) == (endpoint, fingerprint, hook), "destination/configuration/hook changed during scan")
    value = {"remote": remote, "branch": branch, "local": local, "tracking": tracking, "reviewed": reviewed,
             "base": base, "endpoint": endpoint, "fingerprint": fingerprint, "pre_push_hook": hook,
             "hook_review_required": hook["executable"], "scan": "partial" if unscanned else "complete",
             "unscanned_objects": unscanned, "manual_inspection_required": bool(unscanned)}
    receipt_id = records.create("publish", value)
    print(f"binding-id={receipt_id}")
    report_inspection(value)
    print("flat diff and merge-explicit patches: checked for scannable paths; listed manual objects excluded")
    print("scope: Git command binds one branch; follow-tags and submodule pushes disabled; no configured push options")
    print(f"pre-push hooks: {int(hook['executable'])}; " + ("H's behavior review required" if hook["executable"] else "no executable hook"))
    print("pre-push hook: " + json.dumps(hook, sort_keys=True))
    print("CI status: unknown; separate verification required")
    if not ids:
        print("tracking baseline equals reviewed commit; remote state is not yet observed")
    checker = SCRIPTS / "../../publish/scripts/publish-bind"
    command = ["git", "-C", records.top, "-c", "push.followTags=false", "-c", "push.recurseSubmodules=no",
               "-c", "http.followRedirects=false",
               "push", "--no-follow-tags", "--recurse-submodules=no", "--verify",
               f"--force-with-lease=refs/heads/{branch}:{base}", "--", remote, f"{reviewed}:refs/heads/{branch}"]
    preflight = ["env", "EYRAGENTS_RECORD_ROOT=" + str(records.path.parent),
                 str(checker.resolve()), "--check", receipt_id]
    print("== command\n(cd " + shlex.quote(records.top) + " && "
          + shlex.join(preflight) + ") && " + shlex.join(command))


def observe_remote(endpoint, branch):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="/bin/false",
               SSH_ASKPASS="/bin/false", SSH_ASKPASS_REQUIRE="never", GCM_INTERACTIVE="never")
    is_ssh = endpoint.startswith("ssh://") or (not endpoint.startswith(("https://", "/")) and ":" in endpoint)
    if is_ssh:
        argv = ssh_arguments()
        require(argv, "remote observation unknown: cannot make this SSH shell command noninteractive without changing transport")
        variants = config("ssh.variant")
        variant = os.environ.get("GIT_SSH_VARIANT", variants[-1] if variants else "auto")
        require(argv and (variant == "ssh" or (variant == "auto" and Path(argv[0]).name in ("ssh", "ssh.exe"))),
                "remote observation unknown: unsupported noninteractive SSH transport variant; transport not substituted")
        # OpenSSH uses the first obtained value. Put noninteractive options
        # before the original arguments, retaining the chosen executable and
        # its routing/config arguments. Host-key checks are tightened, not skipped.
        options = ["-oBatchMode=yes", "-oNumberOfPasswordPrompts=0", "-oConnectionAttempts=1",
                   "-oConnectTimeout=10", "-oStrictHostKeyChecking=yes", "-oUpdateHostKeys=no",
                   "-oAddKeysToAgent=no", "-oControlMaster=no", "-oControlPersist=no"]
        env["GIT_SSH_COMMAND"] = shlex.join([argv[0], *options, *argv[1:]])
        env["GIT_SSH_VARIANT"] = "ssh"
    command = ["git", "--no-replace-objects", "-c", "http.followRedirects=false", "-c", "credential.interactive=false",
               "ls-remote", "--exit-code", "--refs", "--", endpoint, "refs/heads/" + branch]
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, env=env, start_new_session=True)
    except OSError:
        raise Refused("bound destination observation could not start; push outcome unknown") from None
    output = bytearray()
    deadline = time.monotonic() + OBSERVE_TIMEOUT
    try:
        with selectors.DefaultSelector() as reader:
            reader.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not reader.select(remaining):
                    raise subprocess.TimeoutExpired(command, OBSERVE_TIMEOUT)
                block = os.read(process.stdout.fileno(), DIAGNOSTIC_LIMIT + 1)
                if not block:
                    break
                output.extend(block)
                require(len(output) <= DIAGNOSTIC_LIMIT, "bound destination observation exceeded the response limit; push outcome unknown")
        process.wait(timeout=max(0.001, deadline - time.monotonic()))
    except BaseException as error:
        # Own the whole group, including a transport/helper that outlived Git.
        # Do not leave a password prompt or delayed network child behind.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            raise Refused("remote observation stopped but process cleanup could not be confirmed; push outcome unknown") from None
        if isinstance(error, subprocess.TimeoutExpired):
            raise Refused("remote observation timed out; push outcome unknown; observation process group stopped") from None
        raise
    finally:
        process.stdout.close()
    require(process.returncode in (0, 2), "bound destination observation unavailable (authentication/network/transport); push outcome unknown")
    pattern = rb"(?:[0-9a-f]{40}|[0-9a-f]{64})\t" + re.escape(("refs/heads/" + branch).encode()) + rb"\n?"
    require((process.returncode == 2 and not output) or (process.returncode == 0 and re.fullmatch(pattern, output)),
            "bound destination observation returned malformed or ambiguous metadata; push outcome unknown")
    return bytes(output)


def verify(records, args):
    require(len(args) == 1, "usage: publish-verify ID", 64)
    receipt_id = args[0]
    value = check_binding(records, receipt_id)
    rows = observe_remote(value["endpoint"], value["branch"]).decode("utf-8").splitlines()
    expected = value["reviewed"] + "\trefs/heads/" + value["branch"]
    require(rows == [expected], "bound destination does not currently equal the reviewed commit; point-in-time observation, not proof the push never landed")
    print(f"remote observed: {value['reviewed']} at bound push destination (point in time)")
    tracking = git("rev-parse", "--verify", value["tracking"], check=False).stdout.decode().strip() or "absent"
    print(f"local tracking: {tracking}; informational only, no fetch performed")
    report_inspection(value)
    if value["hook_review_required"]:
        print("pre-push hook: fingerprint unchanged; H's behavior review is not machine-attested")
    print("CI status: unknown; separate verification required")
    os.chdir(records.top)
    if Path("Makefile").is_file() and re.search(r"(?m)^verify-published:", Path("Makefile").read_text()):
        print("published verification: make verify-published", flush=True)
        result = subprocess.run(["make", "verify-published", "REV=" + value["reviewed"]])
        require(result.returncode == 0, "published verification failed", 4)
    elif Path("package.json").is_file() and json.loads(Path("package.json").read_text()).get("scripts", {}).get("verify-published"):
        print("published verification: npm run verify-published", flush=True)
        result = subprocess.run(["npm", "run", "verify-published", "--", value["reviewed"]])
        require(result.returncode == 0, "published verification failed", 4)
    else:
        print("published verification: none defined; remote observed without deployment verification")
    records.status(receipt_id, "verified", commit=value["reviewed"])
    print("ok: publish verified")


def main():
    try:
        require(len(sys.argv) >= 2, "entrypoint required", 64)
        records = Records()
        os.chdir(records.top)
        operation = {"candidate": candidate, "apply": apply, "bind": bind, "verify": verify}[sys.argv[1]]
        operation(records, sys.argv[2:])
    except Refused as error:
        print(f"governance: {error}", file=sys.stderr)
        return error.code
    except (OSError, ValueError, KeyError, UnicodeError):
        print("governance: unreadable, malformed, or missing state; operation refused without raw diagnostics", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
