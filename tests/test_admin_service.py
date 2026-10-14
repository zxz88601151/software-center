"""Admin service tests: draft/publish/rollback/trash/drag-equivalents."""
import base64
import hashlib
import json

import pytest

from sc.admin_service import AdminService
from sc.auth import AdminAuth, AdminSession
from sc.catalog import load_catalog, save_catalog_atomic
from sc.models import SoftwareItem


def _item(**over):
    kw = dict(
        id="demo", name="Demo", version="1.0", category="工具",
        source="sample_files/demo.bin", file_name="demo.bin",
        size_bytes=0, sha256="", sort_order=10, status="published",
    )
    kw.update(over)
    return SoftwareItem(**kw)


@pytest.fixture()
def svc(tmp_data, sample_file):
    data = sample_file.read_bytes()
    item = _item(size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    save_catalog_atomic(tmp_data / "catalog.json", [item])
    service = AdminService(
        tmp_data, tmp_data / "catalog.json", tmp_data / "catalog.draft.json",
        tmp_data / "backups", tmp_data / "trash", tmp_data / "admin_audit.log",
    )
    return service


@pytest.fixture()
def session():
    return AdminSession(timeout_seconds=3600)


def test_requires_session(svc):
    with pytest.raises(PermissionError):
        svc.publish(None)
    expired = AdminSession(timeout_seconds=0)
    expired.expire()
    with pytest.raises(PermissionError):
        svc.publish(expired)


def test_draft_does_not_affect_published(svc, session):
    items = svc.load_draft()
    items[0].name = "Changed in draft"
    svc.upsert_item(session, items[0])
    published, _, _ = load_catalog(svc.catalog_path)
    assert published[0].name == "Demo"
    assert svc.has_draft()


def test_publish_and_rollback(svc, session):
    items = svc.load_draft()
    items[0].name = "V2 name"
    svc.upsert_item(session, items[0])
    detail = svc.publish(session)
    assert detail["modified"] == 1
    published, _, _ = load_catalog(svc.catalog_path)
    assert published[0].name == "V2 name"
    assert svc.list_backups()
    svc.rollback(session, svc.list_backups()[-1])
    published, _, _ = load_catalog(svc.catalog_path)
    assert published[0].name == "Demo"


def test_publish_blocked_by_drift(svc, session, tmp_data):
    # Corrupt the source on disk -> publish must be blocked whole-batch.
    (tmp_data / "sample_files" / "demo.bin").write_bytes(b"tampered")
    with pytest.raises(ValueError):
        svc.publish(session)


def test_delete_then_publish_moves_file_to_trash(svc, session, tmp_data):
    svc.delete_item(session, "demo")
    svc.publish(session)
    published, _, _ = load_catalog(svc.catalog_path)
    assert published == []
    assert not (tmp_data / "sample_files" / "demo.bin").exists()
    assert list((tmp_data / "trash").iterdir()), "deleted file must go to trash, not vanish"


def test_add_from_file_computes_size_and_sha(svc, session, tmp_path):
    src = tmp_path / "newtool.bin"
    src.write_bytes(b"brand-new-tool")
    item = svc.add_item_from_file(session, src, name="NewTool", version="1.0", category="工具")
    assert item.size_bytes == len(b"brand-new-tool")
    assert item.sha256 == hashlib.sha256(b"brand-new-tool").hexdigest()
    assert (svc.data_dir / "sample_files" / "newtool.bin").exists()


def test_add_from_file_rejects_directory_and_reserved(svc, session, tmp_path):
    with pytest.raises(ValueError):
        svc.add_item_from_file(session, tmp_path)
    nul = tmp_path / "NUL.txt"
    nul.write_bytes(b"x")
    with pytest.raises(ValueError):
        svc.add_item_from_file(session, nul)
    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")
    with pytest.raises(ValueError):
        svc.add_item_from_file(session, empty)


def test_update_from_file_recomputes(svc, session, tmp_path):
    new = tmp_path / "demo2.bin"
    new.write_bytes(b"updated-content")
    item = svc.update_item_from_file(session, "demo", new)
    assert item.sha256 == hashlib.sha256(b"updated-content").hexdigest()
    assert item.file_name == "demo2.bin"


def test_reorder_and_category_and_status(svc, session):
    svc.change_category(session, "demo", "影音")
    svc.set_status(session, "demo", "hidden")
    svc.reorder(session, ["demo"])
    items = svc.load_draft()
    assert items[0].category == "影音"
    assert items[0].status == "hidden"
    assert items[0].sort_order == 10


def test_set_icon_requires_png(svc, session, tmp_path):
    fake = tmp_path / "icon.png"
    fake.write_bytes(b"not a png")
    with pytest.raises(ValueError):
        svc.set_icon_from_file(session, "demo", fake)
    png = tmp_path / "icon.png"
    png.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="))
    svc.set_icon_from_file(session, "demo", png)
    assert svc.load_draft()[0].icon == "icons/icon.png"


def test_import_rejects_bad_no_partial(svc, session, tmp_path):
    bad = tmp_path / "catalog.json"
    bad.write_text(json.dumps({"schema_version": 2, "items": [
        {"id": "bad", "name": "", "version": "1", "category": "x", "source": "s",
         "file_name": "NUL.txt", "size_bytes": 0, "sha256": "z", "sort_order": 1, "status": "published"}
    ]}), encoding="utf-8")
    with pytest.raises(ValueError):
        svc.import_catalog_file(session, bad)
    # Draft unchanged (still the original item).
    assert svc.load_draft()[0].id == "demo"


def test_inspect_drift(svc, tmp_data):
    assert svc.inspect_drift() == []
    (tmp_data / "sample_files" / "demo.bin").write_bytes(b"drifted")
    assert svc.inspect_drift()


def test_export_manifest(svc, session, tmp_path):
    manifest = svc.export_draft(session, tmp_path / "out.json")
    assert manifest["count"] == 1
    assert len(manifest["digest"]) == 64
