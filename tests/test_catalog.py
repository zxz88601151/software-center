import hashlib
import json
from pathlib import Path

from sc.catalog import load_catalog, parse_catalog_data


def _item(**over):
    kw = dict(
        id="demo", name="Demo", version="1.0", category="工具",
        source="sample_files/demo.bin", file_name="demo.bin",
        size_bytes=10, sha256="a" * 64, sort_order=10, status="published",
    )
    kw.update(over)
    return kw


def test_real_catalog_loads():
    root = Path(__file__).resolve().parents[1]
    items, errors, version = load_catalog(root / "data" / "catalog.json")
    assert errors == []
    assert version == 2
    assert len(items) >= 3
    assert all(it.size_bytes > 0 for it in items)


def test_zero_byte_entry_rejected(tmp_path):
    data = {"schema_version": 2, "items": [_item(size_bytes=0)]}
    _, errors = parse_catalog_data(data)
    assert errors


def test_duplicate_id_rejected():
    data = {"schema_version": 2, "items": [_item(), _item()]}
    _, errors = parse_catalog_data(data)
    assert errors


def test_bad_sha_rejected():
    data = {"schema_version": 2, "items": [_item(sha256="xyz")]}
    _, errors = parse_catalog_data(data)
    assert errors


def test_reserved_filename_rejected():
    data = {"schema_version": 2, "items": [_item(file_name="NUL.txt")]}
    _, errors = parse_catalog_data(data)
    assert errors


def test_v1_migration_fills_fields():
    raw = {"schema_version": 1, "items": [
        {"id": "old", "name": "Old", "version": "1.0", "category": "工具",
         "source": "sample_files/old.bin", "size_bytes": 5, "sha256": "b" * 64}
    ]}
    items, errors = parse_catalog_data(raw)
    assert errors == []
    assert items[0].file_name == "old.bin"
    assert items[0].status == "published"
    assert items[0].sort_order == 10
