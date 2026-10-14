"""Path safety rules — single implementation point (V2 ch.12).

All download / drag-in / catalog validation share this module so the
rules cannot drift between three hand-written copies.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)

MAX_FILENAME_LEN = 120

_DEVICE_PREFIXES = ("\\\\?\\", "\\\\.\\")


def _main_name(name: str) -> str:
    """Main name = part before the first dot, trailing dots/spaces peeled."""
    stripped = name.strip().strip(". ")
    if "." in stripped:
        stripped = stripped.split(".", 1)[0]
    return stripped.strip().upper()


def is_reserved_name(name: str) -> bool:
    """True if the main name (case-insensitive) is a Windows reserved name.

    Covers NUL, nul, NUL.txt, 'Nul .bin' (main name peeled of trailing
    space -> NUL). The caller is responsible for splitting directory
    components; this checks a single component / file name.
    """
    if not isinstance(name, str):
        return False
    base = name.replace("/", "\\").split("\\")[-1]
    return _main_name(base) in RESERVED_NAMES


def validate_pure_filename(name) -> tuple[bool, str]:
    """Validate a pure file name (file_name field / dragged file name).

    Returns (ok, reason). Empty reason means ok.
    """
    if not isinstance(name, str):
        return False, "file_name must be a string"
    if name == "":
        return False, "file_name must not be empty"
    if len(name) > MAX_FILENAME_LEN:
        return False, "file_name exceeds 120 characters"
    if "/" in name or "\\" in name:
        return False, "file_name must not contain path separators"
    if ":" in name:
        return False, "file_name must not contain ':' (drive / ADS)"
    if name.startswith(_DEVICE_PREFIXES) or name.startswith("\\\\"):
        return False, "file_name must not contain device / UNC prefix"
    if any(ord(ch) < 32 for ch in name):
        return False, "file_name must not contain control characters"
    if name.strip() == "":
        return False, "file_name must not be blank"
    if name in (".", ".."):
        return False, "file_name must not be '.' or '..'"
    if name.endswith(".") or name.endswith(" "):
        return False, "file_name must not end with '.' or space"
    if name != name.strip():
        return False, "file_name must not have leading/trailing whitespace"
    if is_reserved_name(name):
        return False, f"file_name uses reserved device name: {name!r}"
    return True, ""


def contains_device_prefix(value: str) -> bool:
    if not isinstance(value, str):
        return False
    v = value.strip()
    return v.startswith(_DEVICE_PREFIXES) or v.startswith("\\\\.\\")


def validate_relative_source(source: str) -> tuple[bool, str]:
    """Validate a catalog `source` path: project-data-relative only."""
    if not isinstance(source, str) or source == "":
        return False, "source must be a non-empty string"
    if contains_device_prefix(source):
        return False, "source must not use device prefix"
    if source.startswith("\\\\"):
        return False, "source must not be a UNC path"
    if re.match(r"^[A-Za-z]:", source):
        return False, "source must not contain a drive letter"
    if source.startswith("/") or source.startswith("\\"):
        return False, "source must be a relative path"
    parts = [p for p in re.split(r"[/\\]", source) if p not in ("", ".")]
    if ".." in parts:
        return False, "source must not contain '..'"
    for part in parts:
        if part in (".", ".."):
            return False, "source must not contain '.' / '..' components"
        if is_reserved_name(part):
            return False, f"source component uses reserved name: {part!r}"
        if ":" in part:
            return False, "source must not contain ':' (ADS)"
    return True, ""


def is_within_directory(base: Path, target: Path) -> bool:
    """True iff resolved target is inside resolved base (no string-prefix bug)."""
    try:
        base_r = Path(base).resolve()
        target_r = Path(target).resolve()
    except (OSError, RuntimeError):
        return False
    return target_r == base_r or base_r in target_r.parents


def validate_download_dir(path_str: str) -> tuple[bool, str]:
    """A download dir must be an existing local writable directory.

    UNC paths are rejected in V2: only local directories are accepted.
    """
    if not isinstance(path_str, str) or path_str.strip() == "":
        return False, "download directory must not be empty"
    if path_str.startswith("\\\\"):
        return False, "UNC paths are not accepted as download directory"
    if contains_device_prefix(path_str):
        return False, "device prefix not accepted as download directory"
    if re.match(r"^[A-Za-z]:", path_str) is None and not path_str.startswith("/"):
        # Relative download dirs are rejected: must be absolute.
        return False, "download directory must be an absolute path"
    p = Path(path_str)
    if not p.exists():
        return False, "download directory does not exist (not auto-created)"
    if not p.is_dir():
        return False, "download directory is not a directory"
    if not os.access(p, os.W_OK):
        return False, "download directory is not writable"
    return True, ""
