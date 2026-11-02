"""Read the caller's Linux /tmp block quota, not filesystem-wide free space.

This is a read-only Q_GETQUOTA query. Linux quota block limits are in 1024-byte
units, while dqb_curspace is already bytes. Unknown quota state is never reported
as healthy or replaced with a filesystem-capacity estimate.
"""

from __future__ import annotations

import ctypes
import errno
import os
import platform
import sys

QUOTA_BLOCK_BYTES = 1024
Q_GET_USER_QUOTA = 0x80000700
QIF_BLIMITS = 1
QIF_SPACE = 2
WARN_PERCENT = 85
# Linux arch/x86/entry/syscalls/syscall_64.tbl: quotactl_fd. Never guess on other
# architectures; use libc's named wrapper there or report unsupported.
X86_64_QUOTACTL_FD = 443


class _Dqblk(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "bhardlimit",
            "bsoftlimit",
            "curspace",
            "ihardlimit",
            "isoftlimit",
            "curinodes",
            "btime",
            "itime",
        )
    ] + [("valid", ctypes.c_uint32)]


class _UnsupportedQuota(Exception):
    pass


def _query(fd, uid, data):
    libc = ctypes.CDLL(None, use_errno=True)
    wrapper = getattr(libc, "quotactl_fd", None)
    if wrapper is not None:
        wrapper.argtypes = [
            ctypes.c_int,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        wrapper.restype = ctypes.c_int
        result = wrapper(fd, Q_GET_USER_QUOTA, uid, ctypes.byref(data))
    else:
        if platform.machine().lower() not in {"x86_64", "amd64"}:
            raise _UnsupportedQuota
        syscall = getattr(libc, "syscall", None)
        if syscall is None:
            raise _UnsupportedQuota
        syscall.argtypes = [
            ctypes.c_long,
            ctypes.c_int,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        syscall.restype = ctypes.c_long
        result = syscall(
            X86_64_QUOTACTL_FD, fd, Q_GET_USER_QUOTA, uid, ctypes.byref(data)
        )
    if result != 0:
        code = ctypes.get_errno() or errno.EIO
        raise OSError(code, "User quota query failed")


def inspect_tmp_quota(path="/tmp"):
    """Return one structured observation of this process user's block quota."""
    report = {
        "path": os.fspath(path),
        "uid": getattr(os, "getuid", lambda: None)(),
        "source": "linux_user_quota",
    }
    if sys.platform != "linux":
        return {**report, "status": "unsupported", "reason": "not_linux"}
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        data = _Dqblk()
        _query(fd, report["uid"], data)
        if data.valid & (QIF_BLIMITS | QIF_SPACE) != QIF_BLIMITS | QIF_SPACE:
            return {**report, "status": "unavailable", "reason": "missing_quota_fields"}
        hard = int(data.bhardlimit) * QUOTA_BLOCK_BYTES
        soft = int(data.bsoftlimit) * QUOTA_BLOCK_BYTES
        limits = [value for value in (hard, soft) if value]
        used = int(data.curspace)
        if not limits:
            return {
                **report,
                "status": "unlimited",
                "used_bytes": used,
                "limit_bytes": None,
                "hard_limit_bytes": hard,
                "soft_limit_bytes": soft,
            }
        limit = min(limits)
        return {
            **report,
            "status": "ok",
            "used_bytes": used,
            "limit_bytes": limit,
            "hard_limit_bytes": hard,
            "soft_limit_bytes": soft,
            "used_percent": round(used * 100 / limit, 2),
        }
    except _UnsupportedQuota:
        return {**report, "status": "unsupported", "reason": "no_known_query_interface"}
    except OSError as error:
        return {
            **report,
            "status": "unavailable",
            "reason": "query_failed",
            "errno": error.errno,
        }
    finally:
        if fd is not None:
            os.close(fd)


def quota_issues(report):
    """Join the existing incident path; missing observations cannot mean healthy."""
    if report.get("status") == "unlimited":
        return []
    if report.get("status") != "ok":
        return [
            "/tmp: could not inspect this user's quota; monitoring needs attention."
        ]
    used, limit = report["used_bytes"], report["limit_bytes"]
    if used * 100 >= limit * WARN_PERCENT:
        # Keep the incident identity stable while usage fluctuates. Exact usage
        # belongs in monitor-health.json, not in the six-hour deduplication key.
        return [
            f"/tmp: this user's temporary-space quota is at least {WARN_PERCENT}% used."
        ]
    return []
