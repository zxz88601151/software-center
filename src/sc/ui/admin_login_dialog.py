"""Login dialog: a single password field, nothing else.

Per V2 ch.6.1: no title wording naming the admin, no username, no
"remember password", no hint of remaining attempts. Wrong password
only says the password is incorrect. Lockout shows remaining time.

The dialog only collects the password; verification happens in the
auth service (AdminAuth), never in dialog code.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ..auth import AdminAuth


class AdminLoginDialog(QDialog):
    """mode 'login' or 'setup' (first-time password setup)."""

    def __init__(self, auth: AdminAuth, mode: str = "login", parent=None):
        super().__init__(parent)
        self.auth = auth
        self.mode = mode
        self.setWindowTitle("")
        self.setModal(True)
        layout = QVBoxLayout(self)
        if mode == "setup":
            layout.addWidget(QLabel("请设置口令（至少 10 位，须混合字母与数字）"))
            self.pw1 = QLineEdit()
            self.pw1.setEchoMode(QLineEdit.Password)
            self.pw1.setPlaceholderText("口令")
            self.pw2 = QLineEdit()
            self.pw2.setEchoMode(QLineEdit.Password)
            self.pw2.setPlaceholderText("再次输入口令")
            layout.addWidget(self.pw1)
            layout.addWidget(self.pw2)
            self.password_edit = self.pw1
        else:
            self.pw = QLineEdit()
            self.pw.setEchoMode(QLineEdit.Password)
            self.pw.setPlaceholderText("口令")
            layout.addWidget(QLabel("口令"))
            layout.addWidget(self.pw)
            self.password_edit = self.pw
        self.msg = QLabel("")
        layout.addWidget(self.msg)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def entered_password(self) -> str:
        return self.password_edit.text()

    def _on_accept(self) -> None:
        if self.mode == "setup":
            if self.pw1.text() != self.pw2.text():
                self.msg.setText("两次输入不一致")
                return
            errors = self.auth.set_password(self.pw1.text())
            if errors:
                self.msg.setText("; ".join(errors))
                return
            self.accept()
            return
        if self.auth.is_locked():
            mins = int(self.auth.lock_remaining_seconds() // 60) + 1
            self.msg.setText(f"已锁定，请 {mins} 分钟后再试")
            return
        ok, status = self.auth.verify(self.pw.text())
        if ok:
            self.accept()
            return
        if status == "locked":
            self.msg.setText("已锁定，请 15 分钟后再试")
        else:
            self.msg.setText("口令不正确")
