"""Settings dialog: download dir (existing dirs only) + open-after flag.

Browse uses getExistingDirectory (only existing dirs). Confirm re-validates
existence — never auto-creates a directory from any entry point.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..pathsafe import validate_download_dir


class SettingsDialog(QDialog):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setModal(True)
        self._config = dict(config)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("下载目录（仅可选择已存在的目录）"))
        row = QHBoxLayout()
        self.dir_edit = QLineEdit(config.get("download_dir", ""))
        self.browse_btn = QPushButton("浏览…")
        row.addWidget(self.dir_edit)
        row.addWidget(self.browse_btn)
        layout.addLayout(row)
        self.open_after = QCheckBox("下载完成后打开所在文件夹")
        self.open_after.setChecked(bool(config.get("open_folder_after_download", False)))
        layout.addWidget(self.open_after)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.browse_btn.clicked.connect(self._on_browse)

    def _on_browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "选择下载目录", self.dir_edit.text() or str(Path.home()))
        if chosen:
            self.dir_edit.setText(chosen)

    def _on_accept(self) -> None:
        ok, reason = validate_download_dir(self.dir_edit.text().strip())
        if not ok:
            QMessageBox.warning(self, "设置", f"下载目录无效：{reason}")
            return
        self.accept()

    def result_config(self) -> dict:
        cfg = dict(self._config)
        cfg["download_dir"] = self.dir_edit.text().strip()
        cfg["open_folder_after_download"] = self.open_after.isChecked()
        return cfg
