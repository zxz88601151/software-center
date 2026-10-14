"""Domain model: SoftwareItem (V2 ch.10). No Qt dependency."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .pathsafe import validate_pure_filename, validate_relative_source

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
VALID_STATUSES = ("published", "hidden")


@dataclass
class SoftwareItem:
    id: str
    name: str
    version: str
    category: str
    description: str = ""
    icon: str = ""
    source: str = ""
    file_name: str = ""
    size_bytes: int = 0
    sha256: str = ""
    sort_order: int = 0
    status: str = "published"

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.id, str) or not ID_RE.match(self.id or ""):
            errors.append(f"invalid id: {self.id!r}")
        if not isinstance(self.name, str) or not self.name.strip():
            errors.append("name must not be empty")
        if not isinstance(self.version, str) or not self.version.strip():
            errors.append("version must not be empty")
        if not isinstance(self.category, str) or not self.category.strip():
            errors.append("category must not be empty")
        ok, reason = validate_relative_source(self.source)
        if not ok:
            errors.append(f"invalid source: {reason}")
        ok, reason = validate_pure_filename(self.file_name)
        if not ok:
            errors.append(f"invalid file_name: {reason}")
        if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool):
            errors.append("size_bytes must be an integer")
        elif self.size_bytes <= 0:
            errors.append("size_bytes must be > 0 (0-byte entries are rejected)")
        if not isinstance(self.sha256, str) or not SHA_RE.match(self.sha256 or ""):
            errors.append("sha256 must be 64 lowercase hex characters")
        if not isinstance(self.sort_order, int) or isinstance(self.sort_order, bool):
            errors.append("sort_order must be an integer")
        if self.status not in VALID_STATUSES:
            errors.append(f"invalid status: {self.status!r}")
        if self.icon:
            if not isinstance(self.icon, str):
                errors.append("icon must be a string")
            else:
                ok, reason = validate_relative_source(self.icon)
                if not ok:
                    errors.append(f"invalid icon: {reason}")
        return errors

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "category": self.category,
            "description": self.description,
            "icon": self.icon,
            "source": self.source,
            "file_name": self.file_name,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "sort_order": self.sort_order,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SoftwareItem":
        if not isinstance(data, dict):
            raise ValueError("item must be an object")
        item = cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            version=data.get("version", ""),
            category=data.get("category", ""),
            description=data.get("description", ""),
            icon=data.get("icon", ""),
            source=data.get("source", ""),
            file_name=data.get("file_name", ""),
            size_bytes=data.get("size_bytes", 0),
            sha256=data.get("sha256", ""),
            sort_order=data.get("sort_order", 0),
            status=data.get("status", "published"),
        )
        return item
