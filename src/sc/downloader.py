"""Download execution engine (V2 ch.11).

Success contract — ALL six must hold, else FAILED:
1. worker finished normally, not cancelled, no unhandled exception
2. final product is a regular file
3. bytes written == source size
4. on-disk final size == catalog size_bytes (re-stat, never trust counter)
5. on-disk final SHA-256 == catalog sha256 (re-hash, never incremental)
6. target path stayed inside the user download dir

Flow: write same-dir temp file -> verify temp -> os.replace -> final.
Same-name existing final -> refuse before starting, never overwrite/rename.
Any failure -> delete temp, never report success.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

try:
    from PySide6.QtCore import QThread, Signal
except Exception:  # pragma: no cover - allows service tests without Qt
    QThread = object  # type: ignore

    def Signal(*_a, **_k):  # type: ignore
        return None

from .pathsafe import is_within_directory, validate_pure_filename
from .verifier import is_regular_file, sha256_file

CHUNK = 1024 * 256


@dataclass
class DownloadResult:
    success: bool
    bytes_written: int = 0
    error: str = ""
    cancelled: bool = False
    final_path: str = ""


def _is_localhost_http(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return False
    return host in ("localhost", "127.0.0.1", "::1")


def _resolve_local_source(source: str, data_dir: Path | None) -> Path:
    """Resolve a catalog source string to an absolute local path.

    Catalog sources are project-data-relative. Absolute paths are only
    accepted when they are inside the data dir (defence in depth).
    """
    if data_dir is not None and not os.path.isabs(source):
        return (Path(data_dir) / source).resolve()
    p = Path(source)
    if data_dir is not None and is_within_directory(Path(data_dir), p):
        return p.resolve()
    return p


def download_file(
    source: str,
    dest_dir: Path,
    file_name: str,
    expected_size: int,
    expected_sha256: str,
    data_dir: Path | None = None,
    progress_cb=None,
    cancel_flag=None,
) -> DownloadResult:
    ok, reason = validate_pure_filename(file_name)
    if not ok:
        return DownloadResult(False, error=f"invalid file_name: {reason}")
    if expected_size <= 0:
        return DownloadResult(False, error="expected size must be > 0")
    dest_dir = Path(dest_dir)
    if not dest_dir.is_dir():
        return DownloadResult(False, error="download directory does not exist")
    final_path = dest_dir / file_name
    if final_path.exists() or final_path.is_symlink():
        return DownloadResult(False, error=f"target already exists: {file_name}")
    if not is_within_directory(dest_dir, final_path):
        return DownloadResult(False, error="target escapes download directory")

    is_url = source.startswith("http://") or source.startswith("https://")
    if source.startswith("http://") and not _is_localhost_http(source):
        return DownloadResult(False, error="http is only allowed for localhost/test")
    local_path: Path | None = None
    if not is_url:
        local_path = _resolve_local_source(source, data_dir)
        if not is_regular_file(local_path):
            return DownloadResult(False, error="source is not a regular file")
        try:
            source_size = local_path.stat().st_size
        except OSError as exc:
            return DownloadResult(False, error=f"cannot stat source: {exc}")
        if source_size != expected_size:
            return DownloadResult(
                False, error=f"source size {source_size} != expected {expected_size}"
            )

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{file_name}.", suffix=".tmp", dir=str(dest_dir)
    )
    tmp_path = Path(tmp_name)
    bytes_written = 0
    hasher = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as out:
            if is_url:
                req = urllib.request.Request(source, headers={"User-Agent": "Software-Center/1.0"})
                with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
                    length = resp.headers.get("Content-Length")
                    if length is not None and int(length) != expected_size:
                        return DownloadResult(
                            False,
                            error="Content-Length does not match expected size",
                        )
                    while True:
                        if cancel_flag is not None and cancel_flag():
                            return DownloadResult(False, cancelled=True, bytes_written=bytes_written)
                        chunk = resp.read(CHUNK)
                        if not chunk:
                            break
                        out.write(chunk)
                        hasher.update(chunk)
                        bytes_written += len(chunk)
                        if progress_cb:
                            progress_cb(bytes_written, expected_size)
            else:
                assert local_path is not None
                with open(local_path, "rb") as src_f:
                    while True:
                        if cancel_flag is not None and cancel_flag():
                            return DownloadResult(False, cancelled=True, bytes_written=bytes_written)
                        chunk = src_f.read(CHUNK)
                        if not chunk:
                            break
                        out.write(chunk)
                        hasher.update(chunk)
                        bytes_written += len(chunk)
                        if progress_cb:
                            progress_cb(bytes_written, expected_size)
        # Contract checks on the TEMP file, before any rename.
        if cancel_flag is not None and cancel_flag():
            return DownloadResult(False, cancelled=True, bytes_written=bytes_written)
        if bytes_written != expected_size:
            return DownloadResult(
                False,
                error=f"written {bytes_written} != expected {expected_size}",
                bytes_written=bytes_written,
            )
        if not is_regular_file(tmp_path):
            return DownloadResult(False, error="temp file is not a regular file")
        if tmp_path.stat().st_size != expected_size:
            return DownloadResult(False, error="temp file size mismatch")
        if sha256_file(tmp_path) != expected_sha256:
            return DownloadResult(False, error="SHA-256 mismatch")
        if hasher.hexdigest() != expected_sha256:
            return DownloadResult(False, error="SHA-256 mismatch (stream)")
        os.replace(tmp_path, final_path)
        # Re-verify the FINAL file after replace (never trust the counter).
        if not is_regular_file(final_path):
            return DownloadResult(False, error="final product is not a regular file")
        if final_path.stat().st_size != expected_size:
            return DownloadResult(False, error="final file size mismatch")
        if sha256_file(final_path) != expected_sha256:
            try:
                final_path.unlink()
            except OSError:
                pass
            return DownloadResult(False, error="final SHA-256 mismatch")
        return DownloadResult(True, bytes_written=bytes_written, final_path=str(final_path))
    except Exception as exc:  # noqa: BLE001 - any failure is FAILED, never success
        return DownloadResult(False, error=str(exc), bytes_written=bytes_written)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


class DownloadWorker(QThread):  # type: ignore[misc]
    progress_changed = Signal(int, int)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, source, dest_dir, file_name, expected_size, expected_sha256, data_dir=None):
        super().__init__()
        self._args = (source, Path(dest_dir), file_name, expected_size, expected_sha256, data_dir)
        self._cancel = False
        self.result: DownloadResult | None = None

    def request_cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:  # noqa: D102
        source, dest_dir, file_name, size, sha, data_dir = self._args
        result = download_file(
            source,
            dest_dir,
            file_name,
            size,
            sha,
            data_dir=data_dir,
            progress_cb=lambda w, t: self.progress_changed.emit(w, t),
            cancel_flag=lambda: self._cancel,
        )
        self.result = result
        if result.cancelled:
            self.cancelled.emit()
        elif result.success:
            self.succeeded.emit(result)
        else:
            self.failed.emit(result.error or "download failed")
