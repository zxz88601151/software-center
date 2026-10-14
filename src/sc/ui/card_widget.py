"""Card widget: display only, never downloads or touches the FS directly."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import SoftwareItem


def _format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


class CardWidget(QWidget):
    download_requested = Signal(object)
    detail_requested = Signal(object)

    def __init__(self, item: SoftwareItem, icon_dir, parent=None):
        super().__init__(parent)
        self.item = item
        layout = QVBoxLayout(self)
        self.icon_label = QLabel("📦")
        self.icon_label.setAlignment(Qt.AlignCenter)
        if item.icon:
            pix = QPixmap(str(icon_dir / item.icon))
            if not pix.isNull():
                self.icon_label.setPixmap(pix.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.icon_label.setText("")
        layout.addWidget(self.icon_label)
        name = QLabel(f"{item.name}  {item.version}")
        name.setWordWrap(True)
        layout.addWidget(name)
        meta = QLabel(f"{item.category} · {_format_size(item.size_bytes)}")
        layout.addWidget(meta)
        desc = QLabel(item.description or "")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)
        row = QHBoxLayout()
        self.detail_btn = QPushButton("详情")
        self.download_btn = QPushButton("下载")
        row.addWidget(self.detail_btn)
        row.addWidget(self.download_btn)
        layout.addLayout(row)
        self.detail_btn.clicked.connect(lambda: self.detail_requested.emit(item))
        self.download_btn.clicked.connect(lambda: self.download_requested.emit(item))

    def set_downloading(self, downloading: bool, text: str = "") -> None:
        self.download_btn.setEnabled(not downloading)
        self.status_label.setText(text)

    def set_status_text(self, text: str) -> None:
        self.status_label.setText(text)
