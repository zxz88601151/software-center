"""Drag equivalents via the service layer (UI drag events call these).

Covers: drag-in file -> add, drag PNG -> icon, drag catalog.json ->
import, drag row -> reorder, drag to category -> change_category.
"""
import base64
import hashlib
import json

import pytest

from sc.admin_service import AdminService
from sc.auth import AdminSession
from sc.catalog import save_catalog_atomic
from sc.models import SoftwareItem


@pytest.fixture()
def drag_env(tmp_data, sample_file):
    data = sample_file.read_bytes()
    item = SoftwareItem(
        id="demo", name="Demo", version="1.0", category="工具",
        source="sample_files/demo.bin", file_name="demo.bin",
        size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
        sort_order=10, status="published",
    )
    save_catalog_atomic(tmp_data / "catalog.json", [item])
    svc = AdminService(
        tmp_data, tmp_data / "catalog.json", tmp_data / "catalog.draft.json",
        tmp_data / "backups", tmp_data / "trash", tmp_data / "admin_audit.log",
    )
    return svc, AdminSession(timeout_seconds=3600)


def test_drag_in_file_creates_entry(drag_env, tmp_path):
    svc, session = drag_env
    src = tmp_path / "dragged.bin"
    src.write_bytes(b"dragged-content")
    item = svc.add_item_from_file(session, src, name="Dragged")
    assert item.sha256 == hashlib.sha256(b"dragged-content").hexdigest()
    assert item.size_bytes == len(b"dragged-content")


def test_drag_in_rejects_directory_and_reserved(drag_env, tmp_path):
    svc, session = drag_env
    with pytest.raises(ValueError):
        svc.add_item_from_file(session, tmp_path)
    bad = tmp_path / "NUL.txt"
    bad.write_bytes(b"x")
    with pytest.raises(ValueError):
        svc.add_item_from_file(session, bad)


def test_drag_png_to_icon(drag_env, tmp_path):
    svc, session = drag_env
    png = tmp_path / "icon.png"
    png.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="))
    svc.set_icon_from_file(session, "demo", png)
    assert svc.load_draft()[0].icon == "icons/icon.png"
    txt = tmp_path / "fake.png"
    txt.write_bytes(b"not png")
    with pytest.raises(ValueError):
        svc.set_icon_from_file(session, "demo", txt)


def test_drag_catalog_import(drag_env, tmp_path, tmp_data):
    svc, session = drag_env
    data = (tmp_data / "sample_files" / "demo.bin").read_bytes()
    payload = {"schema_version": 2, "items": [{
        "id": "demo", "name": "Demo2", "version": "2.0", "category": "工具",
        "description": "", "icon": "", "source": "sample_files/demo.bin",
        "file_name": "demo.bin", "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(), "sort_order": 10, "status": "published",
    }]}
    f = tmp_path / "catalog.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    diff = svc.import_catalog_file(session, f)
    assert diff["modified"] == ["demo"]


def test_drag_row_reorder_and_category(drag_env):
    svc, session = drag_env
    svc.reorder(session, ["demo"])
    svc.change_category(session, "demo", "影音")
    item = svc.load_draft()[0]
    assert item.category == "影音"
    assert item.sort_order == 10
