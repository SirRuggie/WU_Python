"""Read-only own-user quota and its existing-monitor incident integration."""

import ctypes
import errno
import os
import json
from pathlib import Path
import subprocess
import sys

import pytest
from tools.backup import tmp_quota as q


def test_quota_uses_current_uid_and_converts_limit_blocks_only(monkeypatch, tmp_path):
    monkeypatch.setattr(q.os, "getuid", lambda: 12345)
    captured = []

    def query(fd, uid, data):
        os.fstat(fd)
        captured.append((fd, uid))
        data.bhardlimit = 1000
        data.curspace = 900 * 1024
        data.valid = q.QIF_BLIMITS | q.QIF_SPACE

    monkeypatch.setattr(q, "_query", query)
    result = q.inspect_tmp_quota(tmp_path)
    assert result["uid"] == captured[0][1] == 12345
    assert result["limit_bytes"] == 1000 * 1024
    assert result["used_bytes"] == 900 * 1024 and result["used_percent"] == 90
    assert len(q.quota_issues(result)) == 1
    with pytest.raises(OSError):
        os.fstat(captured[0][0])


@pytest.mark.parametrize(
    "used,warning", [(84999, False), (85000, True), (100000, True), (105000, True)]
)
def test_exact_85_percent_threshold_and_over_quota(used, warning):
    result = q.quota_issues(dict(status="ok", used_bytes=used, limit_bytes=100000))
    assert bool(result) is warning


def test_soft_limit_is_the_earlier_finite_boundary(monkeypatch, tmp_path):
    def query(fd, uid, data):
        data.bhardlimit, data.bsoftlimit, data.curspace = 2000, 1000, 900 * 1024
        data.valid = 3

    monkeypatch.setattr(q, "_query", query)
    result = q.inspect_tmp_quota(tmp_path)
    assert result["hard_limit_bytes"] == 2000 * 1024
    assert result["limit_bytes"] == result["soft_limit_bytes"] == 1000 * 1024
    assert q.quota_issues(result)


def test_explicit_unlimited_is_distinct_from_missing_quota(monkeypatch, tmp_path):
    def query(fd, uid, data):
        data.curspace, data.valid = 12345, 3

    monkeypatch.setattr(q, "_query", query)
    result = q.inspect_tmp_quota(tmp_path)
    assert result["status"] == "unlimited" and result["limit_bytes"] is None
    assert q.quota_issues(result) == []


@pytest.mark.parametrize("valid", [0, q.QIF_SPACE, q.QIF_BLIMITS])
def test_missing_kernel_fields_warn_instead_of_fabricating_healthy(
    monkeypatch, tmp_path, valid
):
    monkeypatch.setattr(
        q, "_query", lambda fd, uid, data: setattr(data, "valid", valid)
    )
    result = q.inspect_tmp_quota(tmp_path)
    assert result["status"] == "unavailable" and q.quota_issues(result)
    assert "used_percent" not in result


@pytest.mark.parametrize("code", [errno.EPERM, errno.ENOSYS, errno.ESRCH])
def test_query_errors_close_fd_and_remain_unknown(monkeypatch, tmp_path, code):
    seen = []

    def fail(fd, uid, data):
        seen.append(fd)
        raise OSError(code, "ignored private detail")

    monkeypatch.setattr(q, "_query", fail)
    result = q.inspect_tmp_quota(tmp_path)
    assert result["status"] == "unavailable" and result["errno"] == code
    assert "private" not in str(result) and q.quota_issues(result)
    with pytest.raises(OSError):
        os.fstat(seen[0])


def test_nonlinux_is_explicitly_unsupported_without_open(monkeypatch):
    monkeypatch.setattr(q.sys, "platform", "darwin")
    monkeypatch.setattr(q.os, "open", lambda *a: pytest.fail("must not open"))
    result = q.inspect_tmp_quota()
    assert result["status"] == "unsupported" and q.quota_issues(result)


class Call:
    def __init__(self, result=0):
        self.calls = []
        self.result = result

    def __call__(self, *args):
        self.calls.append(args)
        return self.result


def test_named_libc_wrapper_preferred(monkeypatch):
    wrapper = Call()
    libc = type("Libc", (), {"quotactl_fd": wrapper})()
    monkeypatch.setattr(q.ctypes, "CDLL", lambda *a, **kw: libc)
    data = q._Dqblk()
    q._query(9, 123, data)
    assert wrapper.calls[0][:3] == (9, q.Q_GET_USER_QUOTA, 123)
    assert (
        ctypes.cast(wrapper.calls[0][3], ctypes.POINTER(q._Dqblk)).contents.valid == 0
    )


def test_x86_64_syscall_fallback_is_exact_read_only_user_query(monkeypatch):
    syscall = Call()
    libc = type("Libc", (), {"syscall": syscall})()
    monkeypatch.setattr(q.ctypes, "CDLL", lambda *a, **kw: libc)
    monkeypatch.setattr(q.platform, "machine", lambda: "x86_64")
    q._query(9, 123, q._Dqblk())
    assert syscall.calls[0][:4] == (443, 9, 0x80000700, 123)


def test_unknown_architecture_never_guesses_syscall(monkeypatch):
    monkeypatch.setattr(q.ctypes, "CDLL", lambda *a, **kw: object())
    monkeypatch.setattr(q.platform, "machine", lambda: "unknown")
    with pytest.raises(q._UnsupportedQuota):
        q._query(9, 123, q._Dqblk())


def test_actual_kernel_error_is_not_read_as_zero_usage(monkeypatch):
    call = Call(result=-1)
    libc = type("Libc", (), {"quotactl_fd": call})()
    monkeypatch.setattr(q.ctypes, "CDLL", lambda *a, **kw: libc)
    monkeypatch.setattr(q.ctypes, "get_errno", lambda: errno.EPERM)
    with pytest.raises(OSError) as error:
        q._query(9, 123, q._Dqblk())
    assert error.value.errno == errno.EPERM


def test_monitor_joins_quota_to_existing_incident_and_health_path(
    monkeypatch, tmp_path
):
    # All inspection and notification boundaries are mocked. This is not a live
    # main() invocation and cannot send either Discord or Healthchecks traffic.
    from tools.backup import monitor as m
    from datetime import datetime, timezone

    now = 1800000000
    stamp = datetime.fromtimestamp(now, timezone.utc).isoformat()
    state, config = tmp_path / "state", tmp_path / "config"
    state.mkdir()
    config.mkdir()
    (config / "r2-enabled").touch()
    for kind in m.JOBS:
        (state / (kind + "-status.json")).write_text(
            json.dumps(dict(local_success=stamp, remote_success=stamp))
        )
    monkeypatch.setattr(m, "STATE", state)
    monkeypatch.setattr(m, "CONFIG", config)
    monkeypatch.setattr(m.time, "time", lambda: now)
    inspections = []

    def inspect(name):
        inspections.append(name)
        return (
            dict(ActiveState="active", UnitFileState="enabled")
            if name.endswith(".timer")
            else dict(LoadState="loaded", Result="success")
        )

    monkeypatch.setattr(m, "inspect_unit", inspect)
    quota = dict(status="ok", used_bytes=900, limit_bytes=1000, used_percent=90)
    monkeypatch.setattr(m, "inspect_tmp_quota", lambda: quota)
    monkeypatch.setattr(
        m, "dotenv_values", lambda path: dict(CWL_BACKUP_ALERT_CHANNEL_ID="111")
    )
    deliveries, pings = [], []

    def deliver(current, previous, at, send):
        deliveries.append((current, at))
        assert send is m.send_discord
        return dict(issues=current, notified_at=at)

    monkeypatch.setattr(m, "deliver", deliver)
    monkeypatch.setattr(
        m, "send_discord", lambda *args: pytest.fail("live notification forbidden")
    )
    monkeypatch.setattr(
        m, "ping_external", lambda url, healthy: pings.append((url, healthy))
    )
    m.main()
    health = json.loads((state / "monitor-health.json").read_text())
    assert health["tmp_user_quota"] == quota
    assert len(health["issues"]) == 1 and "85%" in health["issues"][0]
    assert deliveries == [(health["issues"], now)]
    assert len(inspections) == 2 * len(m.JOBS)
    assert pings == [("", False)]


def test_imports_from_absolute_file_and_package_without_pythonpath(tmp_path):
    root = Path(__file__).parents[1]
    script = root / "tools/backup/monitor.py"
    direct = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import runpy; m=runpy.run_path("
            + repr(str(script))
            + ",run_name='import_only'); assert m['JOBS']['mongo'][1] == 5400; assert callable(m['inspect_tmp_quota'])",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert direct.returncode == 0, direct.stderr
    package = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; sys.path.insert(0,"
            + repr(str(root))
            + "); import tools.backup.monitor as m; assert m.JOBS['mongo'][1] == 5400; assert callable(m.inspect_tmp_quota)",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert package.returncode == 0, package.stderr


def test_quota_incident_stays_stable_while_high_usage_changes():
    first = q.quota_issues(dict(status="ok", used_bytes=860, limit_bytes=1000))
    later = q.quota_issues(dict(status="ok", used_bytes=970, limit_bytes=1000))
    assert first == later
    from tools.backup import monitor as m

    notified = []
    previous = dict(issues=first, notified_at=100)
    assert m.deliver(later, previous, 200, notified.append) == previous
    assert notified == []
