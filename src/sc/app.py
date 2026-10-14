"""Application assembly: QApplication + MainWindow + event loop."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from .catalog import load_catalog
from .config import load_config
from .ui.main_window import MainWindow


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_main_window() -> MainWindow:
    root = project_root()
    data_dir = root / "data"
    catalog_path = data_dir / "catalog.json"
    items, errors, _ = load_catalog(catalog_path)
    config, recovered = load_config(root / ".sc_config.json")
    if errors:
        # Catalog damaged: refuse to offer downloads (V2 ch.4.1).
        app = QApplication.instance()
        if app is not None:
            QMessageBox.critical(
                None, "目录损坏",
                "软件目录损坏或字段非法，已停止提供下载：\n" + "\n".join(errors[:5]),
            )
        items = []
    if recovered:
        app = QApplication.instance()
        if app is not None:
            QMessageBox.warning(
                None, "配置已恢复", "配置文件损坏，已备份为 .bad 并恢复默认设置。"
            )
    win = MainWindow(
        items=items,
        config=config,
        config_path=root / ".sc_config.json",
        data_dir=data_dir,
        catalog_path=catalog_path,
        draft_path=data_dir / "catalog.draft.json",
        backups_dir=data_dir / "backups",
        trash_dir=data_dir / "trash",
        audit_log=data_dir / "admin_audit.log",
        admin_path=data_dir / "admin.json",
    )
    return win


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    win = build_main_window()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
