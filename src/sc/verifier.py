"""Integrity verifier: size + SHA-256 over the on-disk file (V2 ch.11)."""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def is_regular_file(path: Path) -> bool:
    """True only for a real regular file (not dir, device, symlink-to-other)."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode)


def verify_file(path: Path, expected_size: int, expected_sha256: str) -> tuple[bool, str]:
    """Verify one on-disk file against size + SHA-256. Returns (ok, reason)."""
    if not is_regular_file(path):
        return False, "target is not a regular file"
    try:
        actual_size = path.stat().st_size
    except OSError as exc:
        return False, f"cannot stat target: {exc}"
    if actual_size != expected_size:
        return False, f"size mismatch: got {actual_size}, expected {expected_size}"
    try:
        actual_sha = sha256_file(path)
    except OSError as exc:
        return False, f"cannot hash target: {exc}"
    if actual_sha != expected_sha256:
        return False, "SHA-256 mismatch"
    return True, ""
