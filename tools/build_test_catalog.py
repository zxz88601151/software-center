"""Build a test catalog from data/sample_files (dev helper).

Not a runtime dependency. Recomputes size + SHA-256 from disk so the
catalog can never carry hand-typed checksums.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    sample_dir = ROOT / "data" / "sample_files"
    items = []
    for idx, path in enumerate(sorted(sample_dir.glob("*.bin"))):
        data = path.read_bytes()
        items.append(
            {
                "id": path.stem,
                "name": path.stem,
                "version": "1.0.0",
                "category": "工具",
                "description": "test entry",
                "icon": "",
                "source": f"sample_files/{path.name}",
                "file_name": path.name,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "sort_order": (idx + 1) * 10,
                "status": "published",
            }
        )
    out = ROOT / "data" / "catalog.json"
    out.write_text(json.dumps({"schema_version": 2, "items": items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} with {len(items)} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
