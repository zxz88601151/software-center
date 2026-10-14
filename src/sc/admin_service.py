"""Admin service: draft -> validate -> publish -> rollback (V2 ch.9).

- Every mutating method requires a valid AdminSession; without one it
  raises PermissionError. The UI is only a caller.
- All edits go to data/catalog.draft.json. Published catalog is untouched
  until publish(). Publish backs up the old catalog (keep last 5),
  then atomically replaces it.
- Deletion moves source + icon into data/trash/ (30-day retention),
  never a direct physical delete.
- size_bytes / sha256 are NEVER hand-editable: they are always computed
  from the on-disk file by this service.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .audit import append_audit
from .auth import AdminSession
from .catalog import (
    catalog_digest,
    catalog_to_data,
    load_catalog,
    parse_catalog_data,
    save_catalog_atomic,
)
from .models import SoftwareItem
from .pathsafe import is_reserved_name, validate_pure_filename, validate_relative_source
from .verifier import sha256_file

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_BACKUPS = 5
TRASH_RETENTION_DAYS = 30


def _require_session(session: AdminSession | None) -> None:
    if session is None or not session.is_valid():
        raise PermissionError("admin session is not valid")
    session.touch()


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "item"


class AdminService:
    def __init__(self, data_dir: Path, catalog_path: Path, draft_path: Path,
                 backups_dir: Path, trash_dir: Path, audit_log: Path):
        self.data_dir = Path(data_dir)
        self.catalog_path = Path(catalog_path)
        self.draft_path = Path(draft_path)
        self.backups_dir = Path(backups_dir)
        self.trash_dir = Path(trash_dir)
        self.audit_log = Path(audit_log)
        for d in (self.data_dir, self.backups_dir, self.trash_dir):
            d.mkdir(parents=True, exist_ok=True)

    # -- draft handling ------------------------------------------------
    def load_published(self) -> list[SoftwareItem]:
        items, errors, _ = load_catalog(self.catalog_path)
        if errors:
            raise ValueError(f"published catalog invalid: {'; '.join(errors)}")
        return items

    def load_draft(self) -> list[SoftwareItem]:
        if not self.draft_path.exists():
            return self.load_published()
        try:
            data = json.loads(self.draft_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"draft unreadable: {exc}") from exc
        items, errors = parse_catalog_data(data)
        if errors:
            raise ValueError(f"draft invalid: {'; '.join(errors)}")
        return items

    def _save_draft(self, items: list[SoftwareItem]) -> None:
        payload = catalog_to_data(items)
        fd, tmp_name = tempfile.mkstemp(prefix=".draft.", suffix=".tmp", dir=str(self.draft_path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp_name, self.draft_path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def has_draft(self) -> bool:
        return self.draft_path.exists()

    def discard_draft(self, session: AdminSession | None) -> None:
        _require_session(session)
        try:
            self.draft_path.unlink()
        except FileNotFoundError:
            pass
        append_audit(self.audit_log, "discard_draft", "ok", {})

    def change_summary(self) -> dict:
        try:
            published = {it.id: it for it in self.load_published()}
        except ValueError:
            published = {}
        try:
            draft = {it.id: it for it in self.load_draft()}
        except ValueError:
            draft = {}
        added = [i for i in draft if i not in published]
        deleted = [i for i in published if i not in draft]
        modified = [i for i in draft if i in published and draft[i].to_dict() != published[i].to_dict()]
        return {"added": added, "modified": modified, "deleted": deleted}

    # -- validation ----------------------------------------------------
    def validate_draft(self, items: list[SoftwareItem] | None = None) -> list[str]:
        if items is None:
            items = self.load_draft()
        errors: list[str] = []
        seen: set[str] = set()
        for item in items:
            if item.id in seen:
                errors.append(f"duplicate id: {item.id!r}")
            seen.add(item.id)
            for e in item.validate():
                errors.append(f"{item.id}: {e}")
            src = (self.data_dir / item.source).resolve()
            if not src.is_file():
                errors.append(f"{item.id}: source file missing: {item.source}")
                continue
            try:
                actual_size = src.stat().st_size
                actual_sha = sha256_file(src)
            except OSError as exc:
                errors.append(f"{item.id}: cannot read source: {exc}")
                continue
            if actual_size != item.size_bytes:
                errors.append(f"{item.id}: size drift: disk {actual_size} != catalog {item.size_bytes}")
            if actual_sha != item.sha256:
                errors.append(f"{item.id}: sha drift for {item.source}")
        return errors

    # -- CRUD ----------------------------------------------------------
    def upsert_item(self, session: AdminSession | None, item: SoftwareItem) -> None:
        _require_session(session)
        errors = item.validate()
        if errors:
            raise ValueError("; ".join(errors))
        items = self.load_draft()
        items = [it for it in items if it.id != item.id] + [item]
        self._save_draft(items)
        append_audit(self.audit_log, "upsert_item", "ok", {"id": item.id})

    def delete_item(self, session: AdminSession | None, item_id: str) -> SoftwareItem:
        """Remove from draft; the source/icon move to trash at publish time
        is handled by publish() comparing published vs draft."""
        _require_session(session)
        items = self.load_draft()
        target = next((it for it in items if it.id == item_id), None)
        if target is None:
            raise KeyError(f"no such item: {item_id}")
        self._save_draft([it for it in items if it.id != item_id])
        append_audit(self.audit_log, "delete_item_draft", "ok", {"id": item_id})
        return target

    def set_status(self, session: AdminSession | None, item_id: str, status: str) -> None:
        _require_session(session)
        if status not in ("published", "hidden"):
            raise ValueError(f"invalid status: {status!r}")
        items = self.load_draft()
        for it in items:
            if it.id == item_id:
                it.status = status
        self._save_draft(items)
        append_audit(self.audit_log, "set_status", "ok", {"id": item_id, "status": status})

    def reorder(self, session: AdminSession | None, ordered_ids: list[str]) -> None:
        _require_session(session)
        items = self.load_draft()
        by_id = {it.id: it for it in items}
        for pos, item_id in enumerate(ordered_ids):
            if item_id in by_id:
                by_id[item_id].sort_order = (pos + 1) * 10
        self._save_draft(items)
        append_audit(self.audit_log, "reorder", "ok", {"order": ordered_ids})

    def change_category(self, session: AdminSession | None, item_id: str, category: str) -> None:
        _require_session(session)
        if not category or not category.strip():
            raise ValueError("category must not be empty")
        items = self.load_draft()
        for it in items:
            if it.id == item_id:
                it.category = category
        self._save_draft(items)
        append_audit(self.audit_log, "change_category", "ok", {"id": item_id, "category": category})

    # -- file-backed operations ---------------------------------------
    def _copy_into_data(self, src_file: Path, rel_target: str) -> str:
        """Copy an outside file into data/ (sample_files/icons)."""
        dest = (self.data_dir / rel_target).resolve()
        if not str(dest).startswith(str(self.data_dir.resolve())):
            raise ValueError("target escapes data directory")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src_file.resolve() != dest:
            shutil.copyfile(src_file, dest)
        return rel_target

    def add_item_from_file(
        self, session: AdminSession | None, src_file: Path, name: str = "",
        version: str = "1.0.0", category: str = "工具", description: str = "",
    ) -> SoftwareItem:
        _require_session(session)
        src = Path(src_file)
        if not src.is_file():
            raise ValueError("dragged path is not a regular file")
        ok, reason = validate_pure_filename(src.name)
        if not ok:
            raise ValueError(f"dragged file name rejected: {reason}")
        rel_source = f"sample_files/{src.name}"
        self._copy_into_data(src, rel_source)
        size = src.stat().st_size
        sha = sha256_file(self.data_dir / rel_source)
        if size <= 0:
            raise ValueError("0-byte files cannot be listed")
        items = self.load_draft()
        base_id = _slugify(name or src.stem)
        item_id = base_id
        n = 2
        existing = {it.id for it in items}
        while item_id in existing:
            item_id = f"{base_id}-{n}"
            n += 1
        max_order = max((it.sort_order for it in items), default=0)
        item = SoftwareItem(
            id=item_id, name=name or src.stem, version=version, category=category,
            description=description, icon="", source=rel_source, file_name=src.name,
            size_bytes=size, sha256=sha, sort_order=max_order + 10, status="published",
        )
        errors = item.validate()
        if errors:
            raise ValueError("; ".join(errors))
        items.append(item)
        self._save_draft(items)
        append_audit(self.audit_log, "add_item_from_file", "ok", {"id": item_id, "source": rel_source})
        return item

    def update_item_from_file(self, session: AdminSession | None, item_id: str, new_file: Path) -> SoftwareItem:
        _require_session(session)
        src = Path(new_file)
        if not src.is_file():
            raise ValueError("update file is not a regular file")
        ok, reason = validate_pure_filename(src.name)
        if not ok:
            raise ValueError(f"update file name rejected: {reason}")
        items = self.load_draft()
        target = next((it for it in items if it.id == item_id), None)
        if target is None:
            raise KeyError(f"no such item: {item_id}")
        old_rel = target.source
        rel_source = f"sample_files/{src.name}"
        # Preserve the old file in trash before replacing.
        old_abs = (self.data_dir / old_rel).resolve()
        if old_abs.is_file() and old_abs != (self.data_dir / rel_source).resolve():
            self._move_to_trash(old_abs)
        self._copy_into_data(src, rel_source)
        target.source = rel_source
        target.file_name = src.name
        target.size_bytes = (self.data_dir / rel_source).stat().st_size
        target.sha256 = sha256_file(self.data_dir / rel_source)
        if target.size_bytes <= 0:
            raise ValueError("0-byte files cannot be listed")
        self._save_draft(items)
        append_audit(self.audit_log, "update_item_from_file", "ok", {"id": item_id, "source": rel_source})
        return target

    def set_icon_from_file(self, session: AdminSession | None, item_id: str, png_file: Path) -> None:
        _require_session(session)
        src = Path(png_file)
        if not src.is_file():
            raise ValueError("icon file is not a regular file")
        if src.suffix.lower() != ".png":
            raise ValueError("icon must be a PNG file")
        with open(src, "rb") as f:
            if f.read(8) != PNG_MAGIC:
                raise ValueError("icon file is not a PNG image")
        rel = f"icons/{src.name}"
        ok, reason = validate_pure_filename(src.name)
        if not ok:
            raise ValueError(f"icon file name rejected: {reason}")
        self._copy_into_data(src, rel)
        items = self.load_draft()
        for it in items:
            if it.id == item_id:
                it.icon = rel
        self._save_draft(items)
        append_audit(self.audit_log, "set_icon", "ok", {"id": item_id, "icon": rel})

    # -- import / export ----------------------------------------------
    def import_catalog_file(self, session: AdminSession | None, catalog_file: Path) -> dict:
        """Full validation first; on any error refuse, never partial import."""
        _require_session(session)
        try:
            data = json.loads(Path(catalog_file).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"import file unreadable: {exc}") from exc
        items, errors = parse_catalog_data(data)
        if errors:
            raise ValueError(f"import rejected: {errors[0]}")
        old = {it.id: it for it in self.load_draft()}
        new = {it.id: it for it in items}
        diff = {
            "added": [i for i in new if i not in old],
            "modified": [i for i in new if i in old and new[i].to_dict() != old[i].to_dict()],
            "deleted": [i for i in old if i not in new],
        }
        self._save_draft(items)
        append_audit(self.audit_log, "import_catalog", "ok", {k: len(v) for k, v in diff.items()})
        return diff

    def export_draft(self, session: AdminSession | None, dest: Path) -> dict:
        _require_session(session)
        items = self.load_draft()
        payload = catalog_to_data(items)
        manifest = {"count": len(items), "digest": catalog_digest(items)}
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        append_audit(self.audit_log, "export_draft", "ok", manifest)
        return manifest

    # -- publish / rollback -------------------------------------------
    def _prune_backups(self) -> None:
        backups = sorted(self.backups_dir.glob("catalog-*.json"))
        for old in backups[:-MAX_BACKUPS] if len(backups) > MAX_BACKUPS else []:
            try:
                old.unlink()
            except OSError:
                pass

    def _move_to_trash(self, file_path: Path) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        dest = self.trash_dir / f"{ts}-{file_path.name}"
        try:
            shutil.move(str(file_path), str(dest))
        except OSError:
            pass

    def cleanup_trash(self, session: AdminSession | None) -> int:
        _require_session(session)
        removed = 0
        now = time.time()
        for entry in self.trash_dir.iterdir():
            try:
                age_days = (now - entry.stat().st_mtime) / 86400
            except OSError:
                continue
            if age_days > TRASH_RETENTION_DAYS:
                try:
                    entry.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed

    def publish(self, session: AdminSession | None) -> dict:
        _require_session(session)
        items = self.load_draft()
        errors = self.validate_draft(items)
        if errors:
            raise ValueError(f"publish blocked by validation: {errors[0]}")
        summary = self.change_summary()
        # Backup current published catalog.
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        backup = self.backups_dir / f"catalog-{ts}.json"
        if self.catalog_path.exists():
            shutil.copyfile(self.catalog_path, backup)
            self._prune_backups()
        # Trash files of deleted items (published but no longer in draft).
        published = {it.id: it for it in self.load_published()} if self.catalog_path.exists() else {}
        draft_ids = {it.id for it in items}
        for item_id, old in published.items():
            if item_id not in draft_ids:
                for rel in (old.source, old.icon):
                    if rel:
                        p = (self.data_dir / rel).resolve()
                        if p.is_file():
                            self._move_to_trash(p)
        save_catalog_atomic(self.catalog_path, items)
        try:
            self.draft_path.unlink()
        except FileNotFoundError:
            pass
        detail = {k: len(v) for k, v in summary.items()}
        detail["digest"] = catalog_digest(items)
        append_audit(self.audit_log, "publish", "ok", detail)
        return detail

    def list_backups(self) -> list[str]:
        return sorted(p.name for p in self.backups_dir.glob("catalog-*.json"))

    def rollback(self, session: AdminSession | None, backup_name: str) -> None:
        """Rollback is itself a publish: backup current, restore selected."""
        _require_session(session)
        backup = (self.backups_dir / backup_name).resolve()
        if not str(backup).startswith(str(self.backups_dir.resolve())):
            raise ValueError("backup name escapes backups directory")
        if not backup.is_file():
            raise FileNotFoundError(f"no such backup: {backup_name}")
        try:
            data = json.loads(backup.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ValueError(f"backup unreadable: {exc}") from exc
        items, errors = parse_catalog_data(data)
        if errors:
            raise ValueError(f"backup invalid: {errors[0]}")
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        if self.catalog_path.exists():
            shutil.copyfile(self.catalog_path, self.backups_dir / f"catalog-{ts}.json")
            self._prune_backups()
        save_catalog_atomic(self.catalog_path, items)
        try:
            self.draft_path.unlink()
        except FileNotFoundError:
            pass
        append_audit(self.audit_log, "rollback", "ok", {"backup": backup_name})

    def inspect_drift(self) -> list[dict]:
        """Recompute size/sha for every published item vs disk (巡检)."""
        out: list[dict] = []
        try:
            items = self.load_published()
        except ValueError:
            return [{"id": "*", "issue": "published catalog invalid"}]
        for item in items:
            src = (self.data_dir / item.source).resolve()
            if not src.is_file():
                out.append({"id": item.id, "issue": "source missing"})
                continue
            try:
                size = src.stat().st_size
                sha = sha256_file(src)
            except OSError as exc:
                out.append({"id": item.id, "issue": str(exc)})
                continue
            if size != item.size_bytes or sha != item.sha256:
                out.append({"id": item.id, "issue": f"drift: disk size={size} sha={sha[:12]}..."})
        return out
