"""UI integration (offscreen): no admin traces on the main window,
shortcut registered, download worker end-to-end, login dialog shape."""
import hashlib

from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from sc.auth import AdminAuth
from sc.catalog import load_catalog
from sc.downloader import DownloadWorker
from sc.ui.admin_login_dialog import AdminLoginDialog
from sc.ui.main_window import MainWindow


def _visible_texts(widget: QWidget) -> list[str]:
    texts = []
    for child in widget.findChildren(QWidget):
        for attr in ("text", "placeholderText", "title"):
            try:
                val = getattr(child, attr)()
            except Exception:
                continue
            if isinstance(val, str) and val:
                texts.append(val)
    return texts


def test_main_window_has_no_admin_traces(qtbot, tmp_path):
    root = tmp_path
    data_dir = root / "data"
    data_dir.mkdir()
    items, errors, _ = load_catalog(
        __import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "catalog.json"
    )
    assert errors == []
    win = MainWindow(
        items=items, config={"download_dir": str(tmp_path), "open_folder_after_download": False},
        config_path=root / ".sc_config.json", data_dir=data_dir,
        catalog_path=data_dir / "catalog.json", draft_path=data_dir / "catalog.draft.json",
        backups_dir=data_dir / "backups", trash_dir=data_dir / "trash",
        audit_log=data_dir / "admin_audit.log", admin_path=data_dir / "admin.json",
    )
    qtbot.addWidget(win)
    win.show()
    texts = " ".join(_visible_texts(win))
    for banned in ("管理", "管理员", "admin", "Admin", "ADMIN"):
        assert banned not in texts, f"banned visible text {banned!r} in {texts!r}"
    # Hidden shortcut exists, window-level, correct sequence.
    assert win._admin_shortcut.key().toString() == QKeySequence("Ctrl+Shift+F12").toString()
    assert win._admin_shortcut.context() == Qt.WindowShortcut
    # Cards rendered for published items.
    assert len(win.cards) == len([i for i in items if i.status == "published"])


def test_login_dialog_has_no_admin_wording(qtbot, tmp_path):
    auth = AdminAuth(tmp_path / "admin.json")
    dlg = AdminLoginDialog(auth, mode="login")
    qtbot.addWidget(dlg)
    texts = " ".join(_visible_texts(dlg))
    assert "管理员" not in texts
    assert "用户名" not in texts
    # Wrong password only says incorrect, no attempt count.
    auth.set_password("CorrectPass123")
    dlg.password_edit.setText("WrongPass123")
    dlg._on_accept()
    assert "口令不正确" in dlg.msg.text()
    assert "还剩" not in dlg.msg.text()


def test_download_worker_end_to_end(qtbot, tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "sample_files").mkdir(parents=True)
    src = data_dir / "sample_files" / "w.bin"
    content = b"worker-content-" + b"Z" * 50
    src.write_bytes(content)
    dest = tmp_path / "dl"
    dest.mkdir()
    worker = DownloadWorker(
        "sample_files/w.bin", dest, "w.bin", len(content),
        hashlib.sha256(content).hexdigest(), data_dir=data_dir,
    )
    loop = QEventLoop()
    got: dict = {}
    worker.succeeded.connect(lambda r: (got.update(ok=True), loop.quit()))
    worker.failed.connect(lambda m: (got.update(ok=False, msg=m), loop.quit()))
    worker.start()
    loop.exec()
    assert got.get("ok") is True, got
    assert (dest / "w.bin").read_bytes() == content
