"""The half of the shared journal lock that lives in this repo.

The contract with ledger-agent is the *path*, not an import: ledger-agent derives the same one in
`src/ledger_agent/paths.py:journal_lock_path()`. If the two ever disagree, each side takes a lock
nobody else contends for and the serialisation silently stops working while still looking correct
— which is why the derivation is pinned here rather than left to the manual two-terminal check.
"""

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from test_paths import load_app


def test_the_lock_path_matches_the_one_ledger_agent_derives(monkeypatch, tmp_path):
    run = tmp_path / "run"
    monkeypatch.setenv("LEDGER_AGENT_RUN_DIR", str(run))
    app = load_app(monkeypatch, tmp_path)

    digest = hashlib.sha256(str(tmp_path.resolve()).encode()).hexdigest()[:8]
    assert app.journal_lock_path() == run / f"journal-{digest}.lock"


def test_the_lock_path_defaults_under_the_home_run_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("LEDGER_AGENT_RUN_DIR", raising=False)
    app = load_app(monkeypatch, tmp_path)
    assert app.journal_lock_path().parent == Path.home() / ".ledger-agent" / "run"


def test_two_workspaces_do_not_serialise_against_each_other(monkeypatch, tmp_path):
    """Keyed by workspace, so a test workspace never contends with the real one."""
    monkeypatch.setenv("LEDGER_AGENT_RUN_DIR", str(tmp_path / "run"))
    first = load_app(monkeypatch, tmp_path / "a").journal_lock_path()
    second = load_app(monkeypatch, tmp_path / "b").journal_lock_path()
    assert first != second


HOLDER = """
import sys, time, app
with app.journal_lock():
    print("held", flush=True)
    time.sleep(float(sys.argv[1]))
"""


def test_the_lock_actually_excludes_another_process(monkeypatch, tmp_path):
    """flock(2) locks attach to the open file description, so only a *second process* can show
    this: an in-process re-acquire would take a different description and prove nothing."""
    env = {
        **os.environ,
        "ACCOUNTING_DIR": str(tmp_path),
        "LEDGER_AGENT_RUN_DIR": str(tmp_path / "run"),
    }
    repo = Path(__file__).resolve().parent.parent
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLDER, "3"],
        cwd=repo, env=env, stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "held"  # it has the lock before we try

        monkeypatch.setenv("LEDGER_AGENT_RUN_DIR", env["LEDGER_AGENT_RUN_DIR"])
        app = load_app(monkeypatch, tmp_path)
        assert app.journal_lock_path().parent == tmp_path / "run"  # same lock as the holder's
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            with app.journal_lock(timeout_s=1.0):
                pass
        assert time.monotonic() - start >= 1.0  # it waited, rather than sailing through
    finally:
        holder.kill()
        holder.wait()


def test_the_lock_is_released_when_the_holder_exits(monkeypatch, tmp_path):
    env = {
        **os.environ,
        "ACCOUNTING_DIR": str(tmp_path),
        "LEDGER_AGENT_RUN_DIR": str(tmp_path / "run"),
    }
    repo = Path(__file__).resolve().parent.parent
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLDER, "0"],
        cwd=repo, env=env, stdout=subprocess.PIPE, text=True,
    )
    assert holder.stdout.readline().strip() == "held"
    assert holder.wait(timeout=30) == 0

    monkeypatch.setenv("LEDGER_AGENT_RUN_DIR", env["LEDGER_AGENT_RUN_DIR"])
    app = load_app(monkeypatch, tmp_path)
    assert app.journal_lock_path().parent == tmp_path / "run"  # the lock the holder had
    with app.journal_lock(timeout_s=5.0):  # the lock is free again
        pass
