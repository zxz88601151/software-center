"""Admin console: one table for everything, drag-and-drop first (V2 ch.7-9).

- Left: category list. Middle: item table (drag rows to reorder).
  Bottom: edit form for the selected row.
- size / sha are READ-ONLY in the form (computed by the service).
- Draft -> validate -> publish. Publish / rollback / password change /
  delete require confirmation; rollback re-verifies the password.
- Session timeout: a timer checks the session every 30 s; on expiry
  the window closes and the session ends. Closing the window ends the
  session — there is no "minimise and stay logged in".
- Drag-and-drop is registered ONLY here, never on the main window.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..admin_service import AdminService
from ..audit import read_audit
from ..auth import AdminAuth, AdminSession
from ..models import SoftwareItem
from .admin_login_dialog import AdminLoginDialog


class AdminWindow(QWidget):
    def __init__(self, service: AdminService, auth: AdminAuth, session: AdminSession, parent=None):
        super().__init__(parent)
        self.service = service
        self.auth = auth
        self.session = session
        self.setWindowTitle("控制台")
        self.setAcceptDrops(True)
        self._items: list[SoftwareItem] = []
        self._selected_id: str | None = None
        self._build_ui()
        self._reload()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check_session)
        self._timer.start(30_000)

    # -- layout --------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.status_label = QLabel("")
        self.validate_btn = QPushButton("校验")
        self.publish_btn = QPushButton("发布")
        self.discard_btn = QPushButton("放弃草稿")
        self.audit_btn = QPushButton("审计")
        self.inspect_btn = QPushButton("巡检")
        self.import_btn = QPushButton("导入")
        self.export_btn = QPushButton("导出")
        self.rollback_btn = QPushButton("回滚")
        self.change_pw_btn = QPushButton("改口令")
        self.exit_btn = QPushButton("退出")
        for w in (self.status_label, self.validate_btn, self.publish_btn, self.discard_btn,
                  self.audit_btn, self.inspect_btn, self.import_btn, self.export_btn,
                  self.rollback_btn, self.change_pw_btn, self.exit_btn):
            top.addWidget(w)
        top.addStretch(1)
        root.addLayout(top)

        mid = QHBoxLayout()
        self.category_list = QListWidget()
        self.category_list.setMaximumWidth(150)
        mid.addWidget(self.category_list)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["名称", "版本", "分类", "大小", "SHA-256", "状态"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setDragEnabled(True)
        self.table.setAcceptDrops(True)
        self.table.setDragDropMode(QAbstractItemView.InternalMove)
        self.table.setDropIndicatorShown(True)
        mid.addWidget(self.table)
        root.addLayout(mid)

        form = QVBoxLayout()
        self.f_name = QLineEdit()
        self.f_version = QLineEdit()
        self.f_category = QComboBox()
        self.f_category.setEditable(True)
        self.f_desc = QLineEdit()
        self.f_file = QLineEdit()
        self.f_file.setReadOnly(True)
        self.f_size = QLineEdit()
        self.f_size.setReadOnly(True)
        self.f_sha = QLineEdit()
        self.f_sha.setReadOnly(True)
        self.f_status = QComboBox()
        self.f_status.addItems(["published", "hidden"])
        self.f_order = QSpinBox()
        self.f_order.setRange(0, 100000)
        for label, w in (("名称", self.f_name), ("版本", self.f_version), ("分类", self.f_category),
                         ("描述", self.f_desc), ("文件名", self.f_file), ("大小（自动）", self.f_size),
                         ("SHA-256（自动）", self.f_sha), ("状态", self.f_status), ("排序", self.f_order)):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(w)
            form.addLayout(row)
        btns = QHBoxLayout()
        self.save_btn = QPushButton("保存到草稿")
        self.delete_btn = QPushButton("删除")
        self.copy_btn = QPushButton("复制一条")
        self.new_btn = QPushButton("新增")
        self.update_file_btn = QPushButton("更新版本（选文件）")
        self.icon_btn = QPushButton("换图标（选 PNG）")
        for w in (self.save_btn, self.delete_btn, self.copy_btn, self.new_btn, self.update_file_btn, self.icon_btn):
            btns.addWidget(w)
        form.addLayout(btns)
        root.addLayout(form)

        self.validate_btn.clicked.connect(self._on_validate)
        self.publish_btn.clicked.connect(self._on_publish)
        self.discard_btn.clicked.connect(self._on_discard)
        self.audit_btn.clicked.connect(self._on_audit)
        self.inspect_btn.clicked.connect(self._on_inspect)
        self.import_btn.clicked.connect(self._on_import)
        self.export_btn.clicked.connect(self._on_export)
        self.rollback_btn.clicked.connect(self._on_rollback)
        self.change_pw_btn.clicked.connect(self._on_change_pw)
        self.exit_btn.clicked.connect(self.close)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.category_list.itemClicked.connect(lambda _it: self._reload())
        self.save_btn.clicked.connect(self._on_save)
        self.delete_btn.clicked.connect(self._on_delete)
        self.copy_btn.clicked.connect(self._on_copy)
        self.new_btn.clicked.connect(self._on_new)
        self.update_file_btn.clicked.connect(self._on_update_file)
        self.icon_btn.clicked.connect(self._on_icon)

    # -- data ----------------------------------------------------------
    def _reload(self) -> None:
        try:
            items = self.service.load_draft()
        except ValueError as exc:
            QMessageBox.warning(self, "控制台", str(exc))
            return
        self._items = sorted(items, key=lambda it: (it.sort_order, it.id))
        cats = ["全部"]
        for it in self._items:
            if it.category not in cats:
                cats.append(it.category)
        cur = self.category_list.currentItem().text() if self.category_list.currentItem() else "全部"
        self.category_list.clear()
        self.category_list.addItems(cats)
        for i in range(self.category_list.count()):
            if self.category_list.item(i).text() == cur:
                self.category_list.setCurrentRow(i)
        shown = self._items if cur in (None, "全部") else [it for it in self._items if it.category == cur]
        self.table.setRowCount(len(shown))
        for r, it in enumerate(shown):
            for c, val in enumerate([it.name, it.version, it.category, str(it.size_bytes), it.sha256[:12] + "…", it.status]):
                cell = QTableWidgetItem(val)
                cell.setData(Qt.UserRole, it.id)
                self.table.setItem(r, c, cell)
        summary = self.service.change_summary()
        n = len(summary["added"]) + len(summary["modified"]) + len(summary["deleted"])
        self.status_label.setText(f"草稿状态：已改 {n} 条 · 未发布" if n else "草稿状态：无未发布变更")
        self.f_category.clear()
        self.f_category.addItems([c for c in cats if c != "全部"])

    def _current_item(self) -> SoftwareItem | None:
        if self._selected_id is None:
            return None
        return next((it for it in self._items if it.id == self._selected_id), None)

    def _on_select(self) -> None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return
        item_id = self.table.item(rows[0].row(), 0).data(Qt.UserRole)
        it = next((x for x in self._items if x.id == item_id), None)
        if it is None:
            return
        self._selected_id = it.id
        self.f_name.setText(it.name)
        self.f_version.setText(it.version)
        self.f_category.setCurrentText(it.category)
        self.f_desc.setText(it.description)
        self.f_file.setText(it.file_name)
        self.f_size.setText(str(it.size_bytes))
        self.f_sha.setText(it.sha256)
        self.f_status.setCurrentText(it.status)
        self.f_order.setValue(it.sort_order)

    # -- actions -------------------------------------------------------
    def _guard(self) -> bool:
        if not self.session.is_valid():
            QMessageBox.warning(self, "控制台", "会话已超时，请重新登录")
            self.close()
            return False
        return True

    def _on_validate(self) -> None:
        if not self._guard():
            return
        errors = self.service.validate_draft()
        if errors:
            QMessageBox.warning(self, "校验", "\n".join(errors[:10]))
        else:
            QMessageBox.information(self, "校验", "全部通过")

    def _on_publish(self) -> None:
        if not self._guard():
            return
        summary = self.service.change_summary()
        text = (f"新增 {len(summary['added'])} 条，修改 {len(summary['modified'])} 条，"
                f"删除 {len(summary['deleted'])} 条。确认发布？")
        if QMessageBox.question(self, "发布", text) != QMessageBox.Yes:
            return
        try:
            detail = self.service.publish(self.session)
        except (ValueError, PermissionError) as exc:
            QMessageBox.warning(self, "发布", str(exc))
            return
        QMessageBox.information(self, "发布", f"已发布：{detail}")
        self._reload()

    def _on_discard(self) -> None:
        if not self._guard():
            return
        if QMessageBox.question(self, "放弃草稿", "放弃未发布的草稿？") != QMessageBox.Yes:
            return
        self.service.discard_draft(self.session)
        self._reload()

    def _on_audit(self) -> None:
        if not self._guard():
            return
        rows = read_audit(self.service.audit_log)
        dlg = QMessageBox(self)
        dlg.setWindowTitle("审计")
        dlg.setText("\n".join(json.dumps(r, ensure_ascii=False) for r in rows[-50:]) or "暂无记录")
        dlg.exec()

    def _on_inspect(self) -> None:
        if not self._guard():
            return
        drift = self.service.inspect_drift()
        if not drift:
            QMessageBox.information(self, "巡检", "全部一致，无漂移")
        else:
            QMessageBox.warning(self, "巡检", "\n".join(f"{d['id']}: {d['issue']}" for d in drift))

    def _on_import(self) -> None:
        if not self._guard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "导入目录文件", "", "JSON (*.json)")
        if not path:
            return
        try:
            diff = self.service.import_catalog_file(self.session, Path(path))
        except (ValueError, PermissionError) as exc:
            QMessageBox.warning(self, "导入", str(exc))
            return
        QMessageBox.information(self, "导入", f"已导入为草稿：新增 {len(diff['added'])}，修改 {len(diff['modified'])}，删除 {len(diff['deleted'])}")
        self._reload()

    def _on_export(self) -> None:
        if not self._guard():
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出草稿", "catalog-draft.json", "JSON (*.json)")
        if not path:
            return
        manifest = self.service.export_draft(self.session, Path(path))
        QMessageBox.information(self, "导出", f"已导出：{manifest}")

    def _on_rollback(self) -> None:
        if not self._guard():
            return
        backups = self.service.list_backups()
        if not backups:
            QMessageBox.information(self, "回滚", "暂无备份")
            return
        name, ok = QInputDialog.getItem(self, "回滚", "选择备份：", backups, 0, False)
        if not ok:
            return
        dlg = AdminLoginDialog(self.auth, mode="login", parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        if QMessageBox.question(self, "回滚", f"回滚到 {name}？") != QMessageBox.Yes:
            return
        try:
            self.service.rollback(self.session, name)
        except (ValueError, PermissionError) as exc:
            QMessageBox.warning(self, "回滚", str(exc))
            return
        QMessageBox.information(self, "回滚", "已回滚")
        self._reload()

    def _on_change_pw(self) -> None:
        if not self._guard():
            return
        old, ok = QInputDialog.getText(self, "改口令", "旧口令：", QLineEdit.Password)
        if not ok:
            return
        new1, ok = QInputDialog.getText(self, "改口令", "新口令：", QLineEdit.Password)
        if not ok:
            return
        new2, ok = QInputDialog.getText(self, "改口令", "再次输入新口令：", QLineEdit.Password)
        if not ok or new1 != new2:
            QMessageBox.warning(self, "改口令", "两次新口令不一致")
            return
        ok2, msg = self.auth.change_password(old, new1)
        if not ok2:
            QMessageBox.warning(self, "改口令", msg)
        else:
            QMessageBox.information(self, "改口令", "已修改")

    def _on_save(self) -> None:
        if not self._guard():
            return
        it = self._current_item()
        if it is None:
            QMessageBox.warning(self, "保存", "请先选中一条")
            return
        it.name = self.f_name.text().strip()
        it.version = self.f_version.text().strip()
        it.category = self.f_category.currentText().strip()
        it.description = self.f_desc.text()
        it.status = self.f_status.currentText()
        it.sort_order = self.f_order.value()
        try:
            self.service.upsert_item(self.session, it)
        except (ValueError, PermissionError) as exc:
            QMessageBox.warning(self, "保存", str(exc))
            return
        self._reload()

    def _on_delete(self) -> None:
        if not self._guard():
            return
        it = self._current_item()
        if it is None:
            return
        if QMessageBox.question(self, "删除", f"删除条目 {it.name}？发布后源文件进回收站，30 天内可恢复。") != QMessageBox.Yes:
            return
        self.service.delete_item(self.session, it.id)
        self._selected_id = None
        self._reload()

    def _on_copy(self) -> None:
        if not self._guard():
            return
        it = self._current_item()
        if it is None:
            return
        import copy as _copy
        clone = _copy.copy(it)
        clone.id = it.id + "-copy"
        clone.name = it.name + " 副本"
        clone.sort_order = max((x.sort_order for x in self._items), default=0) + 10
        try:
            self.service.upsert_item(self.session, clone)
        except (ValueError, PermissionError) as exc:
            QMessageBox.warning(self, "复制", str(exc))
            return
        self._reload()

    def _on_new(self) -> None:
        if not self._guard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择软件文件", "")
        if not path:
            return
        try:
            self.service.add_item_from_file(self.session, Path(path))
        except (ValueError, PermissionError) as exc:
            QMessageBox.warning(self, "新增", str(exc))
            return
        self._reload()

    def _on_update_file(self) -> None:
        if not self._guard():
            return
        it = self._current_item()
        if it is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择新版本文件", "")
        if not path:
            return
        try:
            self.service.update_item_from_file(self.session, it.id, Path(path))
        except (ValueError, PermissionError) as exc:
            QMessageBox.warning(self, "更新", str(exc))
            return
        self._reload()

    def _on_icon(self) -> None:
        if not self._guard():
            return
        it = self._current_item()
        if it is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择 PNG 图标", "", "PNG (*.png)")
        if not path:
            return
        try:
            self.service.set_icon_from_file(self.session, it.id, Path(path))
        except (ValueError, PermissionError) as exc:
            QMessageBox.warning(self, "图标", str(exc))
            return
        self._reload()

    # -- drag & drop ---------------------------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: D102
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: D102
        if not self._guard():
            return
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if not path.is_file():
                QMessageBox.warning(self, "拖入", f"拖入只接受普通文件：{path.name}")
                continue
            try:
                if path.name == "catalog.json":
                    self.service.import_catalog_file(self.session, path)
                elif path.suffix.lower() == ".png" and self._current_item() is not None:
                    self.service.set_icon_from_file(self.session, self._current_item().id, path)
                else:
                    self.service.add_item_from_file(self.session, path)
            except (ValueError, PermissionError) as exc:
                QMessageBox.warning(self, "拖入", str(exc))
                continue
        event.acceptProposedAction()
        self._reload()

    def _check_session(self) -> None:
        if not self.session.is_valid():
            QMessageBox.warning(self, "控制台", "会话已超时，已退出")
            self.close()

    def closeEvent(self, event) -> None:  # noqa: D102
        self.session.expire()
        if self.service.change_summary()["added"] or self.service.change_summary()["modified"] or self.service.change_summary()["deleted"]:
            QMessageBox.information(self, "控制台", "未发布草稿已保留，下次登录可继续。")
        super().closeEvent(event)
