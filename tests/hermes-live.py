#!/usr/bin/env python3
"""Opt-in local acceptance, never run by CI or the default test target.

approval: real Hermes profile in an owned PTY, observes an external-write
approval and lets it deny on timeout. No approval answers are sent.
hdw: real isolated Herdr server and pane PTYs, with a recording Hermes stub;
checks hdw ha -c composition without selecting any existing user conversation.

Like canary.sh, cross-tool fixtures use a private /tmp root, not another
vendor's private session root. Failures retain that root for exact inspection.
"""
import argparse
import fcntl
import inspect
import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time


def clean(text):
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text.decode(errors="replace"))


def approval_subject(command, description, target):
    # EyrAgents inspect() supplies this complete message; Hermes 0.19's
    # request_tool_approval passes the reason through as the description.
    return (command == "<write_file> (plugin approval rule)"
            and description == "EyrAgents: confirm this external write: " + str(target))


def approval_records(events, target):
    """A model's prose cannot substitute for the observed native callback."""
    pending = set()
    for event in events:
        if event.get("target") != str(target):
            continue
        identity = event.get("request")
        if event.get("event") == "requested":
            pending.add(identity)
        elif event.get("event") == "resolved" and identity in pending and event.get("choice") == "deny":
            return True
    return False


def read_events(path):
    if not path.exists():
        return []
    # A concurrently appended last record is not evidence until newline/flush.
    text = path.read_text()
    return [json.loads(line) for line in text.splitlines(keepends=True) if line.endswith("\n")]


def approval_ready(text, events, target):
    flat = re.sub(r"\s+", " ", text)
    return ("EyrAgents: confirm this external write" in flat and "Deny" in text
            and "Timeout" in text and "denying command" in text
            and "EYR-APPROVAL-COMPLETE" in text and approval_records(events, target))


def termination(signum, _frame):
    # One interruption must unwind finally blocks. Repeated termination during
    # bounded cleanup must not strand the separately-sessioned child server.
    for kind in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(kind, signal.SIG_IGN)
    raise SystemExit(128 + signum)


def stop_child(pid):
    done, status = os.waitpid(pid, os.WNOHANG)
    if done:
        return os.waitstatus_to_exitcode(status)
    os.killpg(pid, signal.SIGTERM)
    for _ in range(50):
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            return os.waitstatus_to_exitcode(status)
        time.sleep(0.1)
    os.killpg(pid, signal.SIGKILL)
    return os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1])


def approval(root, binary):
    for name in ("HERMES_YOLO_MODE", "HERMES_SAFE_MODE", "HERMES_IGNORE_RULES", "HERMES_IGNORE_USER_CONFIG"):
        if name in os.environ:
            raise RuntimeError("inherited policy override; no approval check performed")
    if "HERMES_HOME" in os.environ and os.environ["HERMES_HOME"] != str(Path.home() / ".hermes"):
        raise RuntimeError("approval check requires the managed default profile")
    project = root / "project"
    project.mkdir()
    (project / ".git").mkdir()
    target = root / "approval-probe.txt"
    events = root / "approval-events.jsonl"
    bootstrap = root / "observe-approval.py"
    # Observe the real callback using Python's profiling API, without replacing
    # a native function or changing its arguments/decision. Only the exact
    # synthetic target and fixed event/decision fields are recorded. The normal
    # CLI entrypoint still owns startup, policy loading, UI and authentication.
    bootstrap.write_text(
        "import importlib.util,json,sys,threading\n"
        "target,events=sys.argv[1:3]\n"
        "origin=importlib.util.find_spec('cli').origin\n" + inspect.getsource(approval_subject) +
        "def observe(frame,event,result):\n"
        " if event not in ('call','return') or frame.f_code.co_name != '_approval_callback' or frame.f_code.co_filename != origin: return\n"
        " if not approval_subject(frame.f_locals.get('command'),frame.f_locals.get('description'),target): return\n"
        " record={'target':target,'request':id(frame),'event':'requested' if event=='call' else 'resolved'}\n"
        " if event=='return': record['choice']=result if result in ('once','session','always','deny') else 'unknown'\n"
        " with open(events,'a',encoding='utf-8') as output: output.write(json.dumps(record)+'\\n')\n"
        "sys.setprofile(observe)\nthreading.setprofile(observe)\n"
        "sys.argv=['hermes','--cli','chat','--source','tool']\n"
        "from hermes_cli.main import main\nmain()\n")
    interpreter = Path(binary).with_name("python")
    assert interpreter.is_file(), "approval observer requires the installed Hermes venv Python"
    prompt = (
        "H authorized this synthetic permission check. Call native write_file exactly once to create "
        + str(target) + " with content 'temporary approval fixture'. This exact target is outside the current project. "
        "Wait for its native permission decision; nobody will approve it, so let it time out. "
        "Do not retry through another tool or path, change any other files, save memory, or alter policy. "
        "After the decision, report whether the write happened, then print the three words EYR APPROVAL COMPLETE "
        "joined by hyphens. Do not print the joined marker while waiting."
    )
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(project)
        os.environ.update(TERM="xterm-256color", HISTFILE="/dev/null")
        os.execv(str(interpreter), [str(interpreter), "-I", "-B", str(bootstrap), str(target), str(events)])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 140, 0, 0))
    output = bytearray()
    sent = saw_ask = saw_denial = False
    ready_at = None
    eof_count = 0
    last_eof = 0
    status = None
    start = time.monotonic()
    try:
        while time.monotonic() - start < 240:
            if not sent and time.monotonic() - start > 8:
                os.write(fd, prompt.encode() + b"\r")
                sent = True
            if select.select([fd], [], [], 0.2)[0]:
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                output.extend(data)
                if b"\x1b[6n" in data:
                    os.write(fd, b"\x1b[1;1R")
                if len(output) > 3_000_000:
                    break
                text = clean(output)
                flat = re.sub(r"\s+", " ", text)
                saw_ask |= "EyrAgents: confirm this external write" in flat and "Deny" in text
                saw_denial |= "Timeout" in text and "denying command" in text
                if approval_ready(text, read_events(events), target) and ready_at is None:
                    ready_at = time.monotonic()
            now = time.monotonic()
            if ready_at is not None and now - ready_at > 1 and now - last_eof > 2 and eof_count < 3:
                # Let the completed turn settle. EOF has no affirmative
                # selection semantics, unlike an Enter-bearing slash command.
                os.write(fd, b"\x04")
                last_eof = now
                eof_count += 1
            done, value = os.waitpid(pid, os.WNOHANG)
            if done:
                status = os.waitstatus_to_exitcode(value)
                break
    finally:
        if status is None:
            status = stop_child(pid)
        os.close(fd)
        (root / "approval-output.txt").write_bytes(output)
    records = read_events(events)
    witnessed = approval_records(records, target)
    result = {"prompt_text_seen": saw_ask, "timeout_text_seen": saw_denial, "native_callback_denied": witnessed,
              "target_absent": not target.exists(), "cli_exit": status}
    print(json.dumps(result))
    assert saw_ask and saw_denial and witnessed and not target.exists() and status == 0, "interactive approval not verified"


def executable(path, text):
    path.write_text(text)
    path.chmod(0o700)


def hdw(root, source):
    binary = shutil.which("herdr")
    assert binary and source.is_file(), "Herdr or the selected hdw source is missing"
    project = root / "project"
    project.mkdir()
    home = root / "home"
    home.mkdir()
    for name in ("config", "data", "cache", "state", "runtime", "bin"):
        (root / name).mkdir(mode=0o700)
    name = "eyr-" + root.name.rsplit("-", 1)[-1]
    result_path = root / "hermes-argv.json"
    env = {"HOME": str(home), "PATH": str(root / "bin") + ":/usr/bin:/bin", "SHELL": "/bin/bash",
           "LANG": "C.UTF-8", "TERM": "xterm-256color", "HISTFILE": "/dev/null",
           "HERDR_CONFIG_PATH": str(root / "config.toml"), "EYR_HDW_RESULT": str(result_path)}
    for key, directory in (("CONFIG", "config"), ("DATA", "data"), ("CACHE", "cache"),
                           ("STATE", "state"), ("RUNTIME_DIR", "runtime")):
        env["XDG_" + key + ("" if key == "RUNTIME_DIR" else "_HOME")] = str(root / directory)
    executable(root / "shell", "#!/bin/bash\nexec /bin/bash --noprofile --rcfile " + shlex.quote(str(root / "bashrc")) + " -i\n")
    (root / "bashrc").write_text("export EDITOR=true\nsource " + shlex.quote(str(source)) +
                                "\nPS1='EYR_FIXTURE> '\nprintf 'EYR_SHELL_READY\\n'\n")
    executable(root / "bin/hermes", "#!/usr/bin/python3\nimport json,os,sys\n"
               "path=os.environ['EYR_HDW_RESULT']\n"
               "with open(path+'.tmp','w') as f:\n"
               " json.dump({'argv':sys.argv[1:],'cwd':os.getcwd(),'workspace':os.environ.get('HERDR_WORKSPACE_ID')},f)\n"
               "os.replace(path+'.tmp',path)\n")
    (root / "config.toml").write_text(
        "onboarding=false\n[terminal]\ndefault_shell=" + json.dumps(str(root / "shell")) +
        "\n[update]\nversion_check=false\nmanifest_check=false\n[server]\nheadless_cols=160\nheadless_rows=60\n"
        "[ui.sound]\nenabled=false\n[ui.toast]\ndelivery='off'\n[ui.toast.clipboard]\nenabled=false\n")

    def rpc(*args):
        result = subprocess.run([binary, "--session", name, *args], env=env, cwd=project,
                                text=True, capture_output=True, timeout=10)
        if result.returncode:
            raise RuntimeError("private Herdr RPC failed: " + " ".join(args) + ": " + result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else None

    with (root / "server.log").open("w") as log:
        server = subprocess.Popen([binary, "--session", name, "server"], env=env, cwd=project,
                                  stdout=log, stderr=log, start_new_session=True)
        connected = False
        try:
            for _ in range(50):
                if server.poll() is not None:
                    raise RuntimeError("private Herdr server exited before readiness")
                try:
                    rpc("workspace", "list")
                    connected = True
                    break
                except (RuntimeError, subprocess.TimeoutExpired):
                    time.sleep(0.2)
            assert connected, "private namespace did not become ready"
            created = rpc("workspace", "create", "--cwd", str(project))["result"]
            caller = created["root_pane"]["pane_id"]
            original = created["workspace"]["workspace_id"]
            rpc("pane", "wait-output", caller, "--match", "EYR_SHELL_READY", "--timeout", "10000")
            before = rpc("workspace", "list")["result"]["workspaces"]
            rpc("pane", "run", caller, "hdw ha -c")
            for _ in range(100):
                if result_path.exists():
                    break
                time.sleep(0.1)
            assert result_path.exists(), "hdw did not reach the recording Hermes executable"
            invocation = json.loads(result_path.read_text())
            after = rpc("workspace", "list")["result"]["workspaces"]
            assert invocation["argv"] == ["-c"] and invocation["cwd"] == str(project)
            assert invocation["workspace"] != original and len(after) == len(before) + 1
            pane = rpc("pane", "list", "--workspace", invocation["workspace"])["result"]["panes"]
            assert len(pane) == 3, "new workspace lacks the three-pane layout"
            print(json.dumps({"isolated_session": name, "new_workspaces": 1, "panes": len(pane),
                              "hermes_argv": invocation["argv"], "physical_cwd_preserved": True}))
        finally:
            if connected and server.poll() is None:
                try:
                    rpc("server", "stop")
                except (RuntimeError, subprocess.TimeoutExpired):
                    pass
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(server.pid, signal.SIGTERM)
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(server.pid, signal.SIGKILL)
                    server.wait()


if __name__ == "__main__":
    for kind in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(kind, termination)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("approval", "hdw"))
    parser.add_argument("--hermes", type=Path)
    parser.add_argument("--hdw", type=Path)
    args = parser.parse_args()
    if args.mode == "approval" and (not args.hermes or not args.hermes.is_file()):
        parser.error("--hermes must name the installed executable")
    if args.mode == "hdw" and (not args.hdw or not args.hdw.is_file()):
        parser.error("--hdw must name the selected sibling helper source")
    root = Path(tempfile.mkdtemp(prefix="eyragents-hermes-", dir="/tmp"))
    print("private fixture:", root, flush=True)
    try:
        if args.mode == "approval":
            approval(root, str(args.hermes))
        else:
            hdw(root, args.hdw.resolve())
    except BaseException:
        print("retained failed fixture:", root, flush=True)
        raise
    else:
        shutil.rmtree(root)
        print("ok: local acceptance; owned fixture and processes closed")
