"""Main window: browse / search / detail / download / settings only.

Deliberately NO admin traces here: no menu, no lock icon, no word
"admin" anywhere in visible text. The only admin entry is a
window-level QShortcut (Ctrl+Shift+F12) that opens the login dialog.
The shortcut is registered on this window only (WindowShortcut),
never as a global hotkey.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..admin_service import AdminService
from ..audit import append_audit
from ..auth import AdminAuth
from ..catalog import categories_of
from ..config import save_config
from ..downloader import DownloadWorker
from ..models import SoftwareItem
from .admin_login_dialog import AdminLoginDialog
from .admin_window import AdminWindow
from .card_widget import CardWidget
from .detail_dialog import DetailDialog
from .settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    def __init__(self, *, items, config, config_path, data_dir, catalog_path,
                 draft_path, backups_dir, trash_dir, audit_log, admin_path, parent=None):
        super().__init__(parent)
        self.items: list[SoftwareItem] = list(items)
        self.config = dict(config)
        self.config_path = Path(config_path)
        self.data_dir = Path(data_dir)
        self.catalog_path = Path(catalog_path)
        self.draft_path = Path(draft_path)
        self.backups_dir = Path(backups_dir)
        self.trash_dir = Path(trash_dir)
        self.audit_log = Path(audit_log)
        self.auth = AdminAuth(admin_path)
        self.service = AdminService(data_dir, catalog_path, draft_path, backups_dir, trash_dir, audit_log)
        self.worker: DownloadWorker | None = None
        self.current_card: CardWidget | None = None
        self.admin_window: AdminWindow | None = None
        self.setWindowTitle("Software Center")
        self.resize(900, 600)
        self._build_ui()
        self._refresh_cards()
        # Hidden entry: window-level shortcut only.
        self._admin_shortcut = QShortcut(QKeySequence("Ctrl+Shift+F12"), self)
        self._admin_shortcut.setContext(Qt.WindowShortcut)
        self._admin_shortcut.activated.connect(self._open_admin_entry)

    # -- layout --------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        top = QVBoxLayout()
        header = QHBoxLayout()
        self.settings_btn = QPushButton("设置")
        header.addStretch(1)
        header.addWidget(self.settings_btn)
        top.addLayout(header)
        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("输入名称或关键词")
        self.category_combo = QComboBox()
        self.category_combo.addItem("全部")
        for c in categories_of(self.items):
            self.category_combo.addItem(c)
        search_row.addWidget(self.search_edit)
        search_row.addWidget(self.category_combo)
        top.addLayout(search_row)
        layout.addLayout(top)
        self.empty_label = QLabel("")
        layout.addWidget(self.empty_label)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.scroll.setWidget(self.grid_host)
        layout.addWidget(self.scroll)
        self.statusBar().showMessage("就绪")
        self.search_edit.textChanged.connect(self._refresh_cards)
        self.category_combo.currentTextChanged.connect(self._refresh_cards)
        self.settings_btn.clicked.connect(self._open_settings)

    def _filtered_items(self) -> list[SoftwareItem]:
        kw = self.search_edit.text().strip().lower()
        cat = self.category_combo.currentText()
        out = []
        for it in self.items:
            if it.status != "published":
                continue
            if cat != "全部" and it.category != cat:
                continue
            if kw and kw not in f"{it.name} {it.description}".lower():
                continue
            out.append(it)
        return sorted(out, key=lambda x: (x.sort_order, x.id))

    def _refresh_cards(self) -> None:
        while self.grid.count():
            child = self.grid.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        shown = self._filtered_items()
        self.cards: list[CardWidget] = []
        if not shown:
            self.empty_label.setText("没有符合条件的软件，可尝试清除筛选。")
        else:
            self.empty_label.setText("")
        for idx, item in enumerate(shown):
            card = CardWidget(item, self.data_dir, parent=self)
            card.download_requested.connect(self._start_download)
            card.detail_requested.connect(self._open_detail)
            if self.worker is not None and self.worker.isRunning():
                card.download_btn.setEnabled(False)
            self.grid.addWidget(card, idx // 3, idx % 3)
            self.cards.append(card)

    # -- detail / settings ---------------------------------------------
    def _open_detail(self, item: SoftwareItem) -> None:
        dlg = DetailDialog(item, self)
        if dlg.exec() == DetailDialog.Accepted:
            self._start_download(item)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.config, self)
        if dlg.exec() == SettingsDialog.Accepted:
            new_cfg = dlg.result_config()
            try:
                save_config(self.config_path, new_cfg)
            except ValueError as exc:
                QMessageBox.warning(self, "设置", str(exc))
                return
            self.config = new_cfg

    # -- download ------------------------------------------------------
    def _start_download(self, item: SoftwareItem) -> None:
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "下载", "已有下载任务在进行中，请等待完成。")
            return
        dest_dir = Path(self.config.get("download_dir", ""))
        if not dest_dir.is_dir():
            QMessageBox.warning(self, "下载", "下载目录无效，请先在设置中选择已存在的目录。")
            return
        self.statusBar().showMessage(f"正在下载 {item.name}…")
        for card in self.cards:
            card.download_btn.setEnabled(False)
        self.current_card = next((c for c in self.cards if c.item.id == item.id), None)
        if self.current_card is not None:
            self.current_card.set_status_text("正在下载…")
        worker = DownloadWorker(item.source, dest_dir, item.file_name, item.size_bytes, item.sha256, data_dir=self.data_dir)
        self.worker = worker
        worker.progress_changed.connect(self._on_progress)
        worker.succeeded.connect(self._on_succeeded)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        worker.finished.connect(self._on_worker_finished)
        worker.start()

    def _on_progress(self, written: int, total: int) -> None:
        pct = int(written * 100 / total) if total else 0
        self.statusBar().showMessage(f"正在下载 {pct}%（{written}/{total}）")
        if self.current_card is not None:
            self.current_card.set_status_text(f"正在下载 {pct}%")

    def _on_succeeded(self, result) -> None:
        # SUCCEEDED is only set by the verifier inside the worker, after
        # all six contract checks passed. The UI never declares success.
        self.statusBar().showMessage("下载成功（已校验）")
        if self.current_card is not None:
            self.current_card.set_status_text("下载成功（已校验）")
        if self.config.get("open_folder_after_download"):
            try:
                target = Path(self.config["download_dir"])
                if sys.platform.startswith("win"):
                    subprocess.Popen(["explorer", str(target)])  # noqa: S603
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(target)])  # noqa: S603
                else:
                    subprocess.Popen(["xdg-open", str(target)])  # noqa: S603
            except OSError:
                pass

    def _on_failed(self, message: str) -> None:
        self.statusBar().showMessage(f"下载失败：{message}")
        if self.current_card is not None:
            self.current_card.set_status_text(f"下载失败：{message}，已删除不完整文件。")

    def _on_cancelled(self) -> None:
        self.statusBar().showMessage("已取消")
        if self.current_card is not None:
            self.current_card.set_status_text("已取消")

    def _on_worker_finished(self) -> None:
        self.worker = None
        self.current_card = None
        for card in self.cards:
            card.download_btn.setEnabled(True)

    # -- hidden admin entry --------------------------------------------
    def _open_admin_entry(self) -> None:
        if self.admin_window is not None and self.admin_window.isVisible():
            self.admin_window.raise_()
            self.admin_window.activateWindow()
            return
        mode = "setup" if not self.auth.is_setup() else "login"
        dlg = AdminLoginDialog(self.auth, mode=mode, parent=self)
        if dlg.exec() != AdminLoginDialog.Accepted:
            return
        session = self.auth.create_session()
        append_audit(self.audit_log, "login", "ok", {"mode": mode})
        win = AdminWindow(self.service, self.auth, session, parent=None)
        self.admin_window = win
        win.show()
        # Refresh user catalog when the admin window closes (published may change).
        win.destroyed.connect(self._reload_catalog_after_admin)

    def _reload_catalog_after_admin(self) -> None:
        self.admin_window = None
        try:
            from ..catalog import load_catalog
            items, errors, _ = load_catalog(self.catalog_path)
        except Exception:  # noqa: BLE001
            return
        if not errors:
            self.items = items
            cats = ["全部"] + categories_of(items)
            cur = self.category_combo.currentText()
            self.category_combo.blockSignals(True)
            self.category_combo.clear()
            self.category_combo.addItems(cats)
            if cur in cats:
                self.category_combo.setCurrentText(cur)
            self.category_combo.blockSignals(False)
            self._refresh_cards()

    # -- close ---------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: D102
        if self.worker is not None and self.worker.isRunning():
            box = QMessageBox(self)
            box.setWindowTitle("退出")
            box.setText("下载正在进行中，如何处理？")
            wait_btn = box.addButton("等待完成", QMessageBox.AcceptRole)
            cancel_btn = box.addButton("取消下载并退出", QMessageBox.DestructiveRole)
            stay_btn = box.addButton("不退出", QMessageBox.RejectRole)
            box.setDefaultButton(stay_btn)
            box.exec()
            clicked = box.clickedButton()
            if clicked is stay_btn:
                event.ignore()
                return
            if clicked is cancel_btn:
                self.worker.request_cancel()
                self.worker.wait(5000)
                event.accept()
                return
            event.ignore()
            return
        super().closeEvent(event)
