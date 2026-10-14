"""Append-only audit log (V2 ch.6.5). JSONL: one object per line.

Never records passwords or hashes. Only event / result / summary.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append_audit(log_path: Path, event: str, result: str, detail: dict | None = None) -> None:
    record = {"time": _now_iso(), "event": event, "result": result, "detail": detail or {}}
    path = Path(log_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_audit(log_path: Path, limit: int = 500) -> list[dict]:
    path = Path(log_path)
    if not path.exists():
        return []
    rows: list[dict] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows[-limit:]
