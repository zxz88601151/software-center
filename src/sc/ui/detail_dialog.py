"""Detail dialog: display only. Its Download button reuses the same
download service as the card — no second download implementation."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..models import SoftwareItem


def _format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


class DetailDialog(QDialog):
    def __init__(self, item: SoftwareItem, parent=None):
        super().__init__(parent)
        self.item = item
        self.setWindowTitle(item.name)
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{item.name}  {item.version}"))
        layout.addWidget(QLabel(f"分类：{item.category}"))
        layout.addWidget(QLabel(f"大小：{_format_size(item.size_bytes)}"))
        layout.addWidget(QLabel(f"文件名：{item.file_name}"))
        desc = QLabel(item.description or "")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        self.download_btn = QPushButton("下载")
        layout.addWidget(self.download_btn)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.download_btn.clicked.connect(self.accept)
