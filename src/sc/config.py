"""User configuration (V2 ch.13.1).

- Location: project root `.sc_config.json` (kept separate from admin.json).
- Missing -> defaults. Corrupt -> back up as `.bad`, restore defaults, flag it.
- Writes are atomic (temp file + os.replace), never direct overwrite.
- Download dir: only an already-existing directory is accepted, never
  auto-created by any entry point.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .pathsafe import validate_download_dir

DEFAULT_CONFIG: dict = {
    "download_dir": "",
    "open_folder_after_download": False,
}


def default_download_dir() -> str:
    downloads = Path.home() / "Downloads"
    if downloads.is_dir():
        return str(downloads)
    return str(Path.home())


def load_config(path: Path) -> tuple[dict, bool]:
    """Returns (config, recovered_from_corrupt)."""
    if not Path(path).exists():
        cfg = dict(DEFAULT_CONFIG)
        cfg["download_dir"] = default_download_dir()
        return cfg, False
    try:
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("config root must be an object")
    except (OSError, ValueError, json.JSONDecodeError):
        bad = Path(str(path) + ".bad")
        try:
            if Path(path).exists():
                Path(path).replace(bad)
        except OSError:
            pass
        cfg = dict(DEFAULT_CONFIG)
        cfg["download_dir"] = default_download_dir()
        return cfg, True
    cfg = dict(DEFAULT_CONFIG)
    cfg.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
    if not isinstance(cfg.get("download_dir"), str) or not cfg["download_dir"]:
        cfg["download_dir"] = default_download_dir()
    if not isinstance(cfg.get("open_folder_after_download"), bool):
        cfg["open_folder_after_download"] = False
    return cfg, False


def validate_config(cfg: dict) -> list[str]:
    errors: list[str] = []
    ok, reason = validate_download_dir(cfg.get("download_dir", ""))
    if not ok:
        errors.append(f"download_dir: {reason}")
    return errors


def save_config(path: Path, cfg: dict) -> None:
    """Atomic save. Raises ValueError if download_dir is not an existing dir."""
    ok, reason = validate_download_dir(cfg.get("download_dir", ""))
    if not ok:
        raise ValueError(f"refusing to save config: download_dir: {reason}")
    payload = {
        "download_dir": cfg["download_dir"],
        "open_folder_after_download": bool(cfg.get("open_folder_after_download", False)),
    }
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(prefix=".sc_config.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
