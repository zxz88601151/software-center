import time

import pytest

from sc.auth import AdminAuth, AdminSession

PW = "AdminPass123"


@pytest.fixture()
def auth(tmp_path):
    return AdminAuth(tmp_path / "admin.json")


def test_no_default_password(auth):
    assert not auth.is_setup()
    ok, _ = auth.verify("anything")
    assert not ok


def test_setup_policy(auth):
    assert auth.set_password("short1")  # too short
    assert auth.set_password("longpassword")  # no digit
    assert auth.set_password("1234567890")  # no letter
    assert auth.set_password(PW) == []
    assert auth.is_setup()


def test_verify_and_change(auth):
    auth.set_password(PW)
    ok, _ = auth.verify(PW)
    assert ok
    ok, _ = auth.verify("WrongPass123")
    assert not ok
    ok, _ = auth.change_password("WrongPass123", "NewPass1234")
    assert not ok
    ok, _ = auth.change_password(PW, "NewPass1234")
    assert ok
    ok, _ = auth.verify("NewPass1234")
    assert ok


def test_no_plaintext_in_admin_file(auth, tmp_path):
    auth.set_password(PW)
    raw = (tmp_path / "admin.json").read_text(encoding="utf-8")
    assert PW not in raw
    assert auth.scheme() in ("argon2id", "scrypt")


def test_lockout_after_five_and_persists_across_restart(auth, tmp_path):
    auth.set_password(PW)
    for _ in range(5):
        auth.verify("WrongPass123")
    assert auth.is_locked()
    # Correct password is also refused while locked.
    ok, _ = auth.verify(PW)
    assert not ok
    # Restart (new instance) must NOT clear the lock.
    auth2 = AdminAuth(tmp_path / "admin.json")
    assert auth2.is_locked()
    assert auth2.failed_count() == 5


def test_session_timeout():
    s = AdminSession(timeout_seconds=0.05)
    assert s.is_valid()
    time.sleep(0.08)
    assert not s.is_valid()
    s.touch()
    assert s.is_valid()
    s.expire()
    assert not s.is_valid()
