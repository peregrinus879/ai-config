#!/usr/bin/env python3
"""Hermetic evidence/termination regressions, no Hermes/model/Herdr service."""
import json
import os
from pathlib import Path
import runpy
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
helper = ROOT / "tests/hermes-live.py"
policy = runpy.run_path(str(helper))
for kind in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
    signal.signal(kind, policy["termination"])
target = Path("/synthetic/approval-probe.txt")
description = "EyrAgents: confirm this external write: " + str(target)
assert policy["approval_subject"]("<write_file> (plugin approval rule)", description, target)
for wrong in (description + ".bak", "Other destination, mentioning " + str(target),
              description + ", /other", "prefix " + description):
    assert not policy["approval_subject"]("<write_file> (plugin approval rule)", wrong, target)
explanatory_reply = b"EyrAgents: confirm this external write. Deny. Timeout, denying command. EYR-APPROVAL-COMPLETE"
assert all(word in policy["clean"](explanatory_reply) for word in ("Deny", "Timeout", "EYR-APPROVAL-COMPLETE"))
assert not policy["approval_records"]([], target), "assistant text was accepted as native evidence"
assert not policy["approval_ready"](policy["clean"](explanatory_reply), [], target), "assistant text triggered UI input"
requested = {"target": str(target), "request": 123, "event": "requested"}
denied = {**requested, "event": "resolved", "choice": "deny"}
assert policy["approval_records"]([requested, denied], target)
assert policy["approval_ready"](policy["clean"](explanatory_reply), [requested, denied], target)
assert not policy["approval_records"]([denied, requested], target)
assert not policy["approval_records"]([requested, {**denied, "request": 456}], target)
assert not policy["approval_records"]([requested, {**denied, "choice": "once"}], target)
assert not policy["approval_records"]([requested, {**denied, "target": "/other"}], target)

with tempfile.TemporaryDirectory(prefix="hermes-helper-fixture-") as temporary:
    base = Path(temporary)
    binary = base / "herdr"
    binary.write_text("#!" + sys.executable + "\n" + r'''
import os,signal,sys,time
from pathlib import Path
root=Path(os.environ['HERDR_CONFIG_PATH']).parent
if sys.argv[3:]==['server']:
    def stopped(*_):
        (root/'server-stopped').write_text('stopped')
        sys.exit(0)
    signal.signal(signal.SIGTERM,stopped)
    (root/'server-ready').write_text(str(os.getpid()))
    while True: time.sleep(1)
else:
    # Keep the helper in a pending readiness RPC when SIGTERM arrives.
    (root/'rpc-ready').write_text(str(os.getpid()))
    time.sleep(60)
''')
    binary.chmod(0o700)
    hdw = base / "hdw"
    hdw.write_text("hdw() { :; }\n")
    env = {**os.environ, "PATH": str(base) + ":/usr/bin:/bin", "HISTFILE": "/dev/null"}
    child = subprocess.Popen([sys.executable, str(helper), "hdw", "--hdw", str(hdw)], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    fixture = None
    handles = []
    try:
        line = child.stdout.readline().strip()
        assert line.startswith("private fixture: /tmp/eyragents-hermes-"), line
        fixture = Path(line.removeprefix("private fixture: "))
        for _ in range(100):
            if (fixture / "server-ready").exists() and (fixture / "rpc-ready").exists():
                break
            assert child.poll() is None, "helper exited before fake server readiness"
            time.sleep(0.05)
        assert (fixture / "server-ready").exists() and (fixture / "rpc-ready").exists()
        # pidfds bind cleanup to these exact fake children even if a regression
        # strands them and their parent exits. Never signal a recycled PID.
        for marker in ("server-ready", "rpc-ready"):
            handles.append(os.pidfd_open(int((fixture / marker).read_text())))
        child.send_signal(signal.SIGTERM)
        out, err = child.communicate(timeout=20)
        assert child.returncode == 143, (child.returncode, err)
        assert "retained failed fixture: " + str(fixture) in out, out
        assert (fixture / "server-stopped").exists(), "owned server survived helper termination"
        assert fixture.exists(), "interrupted diagnostic root was not retained"
        assert all(select.select([handle], [], [], 0)[0] for handle in handles), "helper left a child for fixture rescue"
    finally:
        if child.poll() is None:
            child.send_signal(signal.SIGTERM)
            child.wait(timeout=20)
        closed = len(handles) == 2
        for handle in handles:
            if not select.select([handle], [], [], 0)[0]:
                signal.pidfd_send_signal(handle, signal.SIGTERM)
            closed &= bool(select.select([handle], [], [], 5)[0])
            os.close(handle)
        if fixture and closed:
            shutil.rmtree(fixture)
        elif fixture:
            print("retained interrupted test fixture:", fixture)
    assert closed, "fixture-owned process rescue did not complete"

print("ok: native approval evidence rejects narrative/lookalikes; SIGTERM closes the owned server and reports the retained fixture")
