"""Admin authentication + session (V2 ch.6).

- No default password, no hard-coded password anywhere.
- Argon2id preferred (argon2-cffi); fallback to stdlib hashlib.scrypt
  when argon2-cffi is unavailable. The fallback is recorded in the
  stored scheme field and in the audit log — never silent downgrade to
  a fast hash or plaintext.
- Lockout state (failed count + lock_until) is persisted in admin.json,
  so restarting the program cannot clear it.
- Session: 15 minutes of inactivity -> expired. Closing the admin
  window ends the session; sessions never survive a restart.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import tempfile
import time
from pathlib import Path

MIN_PASSWORD_LEN = 10
MAX_FAILED = 5
LOCK_SECONDS = 15 * 60
SESSION_TIMEOUT_SECONDS = 15 * 60

try:  # Argon2id preferred
    from argon2.low_level import Type as _ArgonType
    from argon2.low_level import hash_secret_raw as _argon_hash

    _HAS_ARGON2 = True
except Exception:  # pragma: no cover - environment dependent
    _HAS_ARGON2 = False

ARGON2_PARAMS = {"memory_kib": 64 * 1024, "iterations": 3, "parallelism": 1, "salt_len": 16}
SCRYPT_PARAMS = {"n": 32768, "r": 8, "p": 1, "dklen": 32, "salt_len": 16}


def password_policy_errors(password: str) -> list[str]:
    errors: list[str] = []
    if len(password) < MIN_PASSWORD_LEN:
        errors.append(f"password must be at least {MIN_PASSWORD_LEN} characters")
    if not any(ch.isalpha() for ch in password):
        errors.append("password must contain a letter")
    if not any(ch.isdigit() for ch in password):
        errors.append("password must contain a digit")
    return errors


def _derive(password: str, salt: bytes, scheme: str, params: dict) -> bytes:
    if scheme == "argon2id":
        return _argon_hash(
            password.encode("utf-8"),
            salt,
            time_cost=params.get("iterations", 3),
            memory_cost=params.get("memory_kib", 64 * 1024),
            parallelism=params.get("parallelism", 1),
            hash_len=32,
            type=_ArgonType.ID,
        )
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=params.get("n", 32768),
        r=params.get("r", 8),
        p=params.get("p", 1),
        dklen=params.get("dklen", 32),
    )


class AdminSession:
    """An admin login session. Validity is time-based inactivity."""

    def __init__(self, timeout_seconds: int = SESSION_TIMEOUT_SECONDS):
        self.timeout_seconds = timeout_seconds
        self.last_activity = time.monotonic()

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def is_valid(self) -> bool:
        return (time.monotonic() - self.last_activity) <= self.timeout_seconds

    def expire(self) -> None:
        self.last_activity = 0.0


class AdminAuth:
    """Password store + lockout, persisted in a standalone admin.json."""

    def __init__(self, admin_path: Path):
        self.admin_path = Path(admin_path)
        self._data: dict = self._load()

    # -- persistence ---------------------------------------------------
    def _load(self) -> dict:
        try:
            data = json.loads(self.admin_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
        return {}

    def _save(self) -> None:
        self.admin_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".admin.", suffix=".tmp", dir=str(self.admin_path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp_name, self.admin_path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    # -- state ---------------------------------------------------------
    def is_setup(self) -> bool:
        return bool(self._data.get("password_hash_b64"))

    def scheme(self) -> str:
        return str(self._data.get("scheme", ""))

    def failed_count(self) -> int:
        return int(self._data.get("failed_count", 0))

    def lock_remaining_seconds(self) -> float:
        until = float(self._data.get("lock_until", 0) or 0)
        return max(0.0, until - time.time())

    def is_locked(self) -> bool:
        return self.lock_remaining_seconds() > 0

    # -- password operations ------------------------------------------
    def set_password(self, new_password: str) -> list[str]:
        """First-time setup. Caller must ensure no password exists yet."""
        errors = password_policy_errors(new_password)
        if errors:
            return errors
        if self.is_setup():
            return ["admin password is already set; use change_password"]
        scheme = "argon2id" if _HAS_ARGON2 else "scrypt"
        params = dict(ARGON2_PARAMS) if scheme == "argon2id" else dict(SCRYPT_PARAMS)
        salt = secrets.token_bytes(params["salt_len"])
        digest = _derive(new_password, salt, scheme, params)
        self._data = {
            "scheme": scheme,
            "params": params,
            "salt_b64": base64.b64encode(salt).decode("ascii"),
            "password_hash_b64": base64.b64encode(digest).decode("ascii"),
            "failed_count": 0,
            "lock_until": 0,
        }
        self._save()
        return []

    def verify(self, password: str) -> tuple[bool, str]:
        """Returns (ok, status): status in ok/locked/incorrect."""
        if self.is_locked():
            return False, "locked"
        if not self.is_setup():
            return False, "not_setup"
        try:
            salt = base64.b64decode(self._data["salt_b64"])
            expected = base64.b64decode(self._data["password_hash_b64"])
        except (KeyError, ValueError):
            return False, "incorrect"
        scheme = self._data.get("scheme", "scrypt")
        params = self._data.get("params", {})
        digest = _derive(password, salt, scheme, params)
        if secrets.compare_digest(digest, expected):
            self._data["failed_count"] = 0
            self._data["lock_until"] = 0
            self._save()
            return True, "ok"
        failed = int(self._data.get("failed_count", 0)) + 1
        self._data["failed_count"] = failed
        if failed >= MAX_FAILED:
            self._data["lock_until"] = time.time() + LOCK_SECONDS
        self._save()
        return False, "locked" if failed >= MAX_FAILED else "incorrect"

    def change_password(self, old_password: str, new_password: str) -> tuple[bool, str]:
        errors = password_policy_errors(new_password)
        if errors:
            return False, "; ".join(errors)
        if self.is_locked():
            return False, "locked"
        ok, _ = self.verify(old_password)
        if not ok:
            return False, "old password incorrect"
        scheme = "argon2id" if _HAS_ARGON2 else "scrypt"
        params = dict(ARGON2_PARAMS) if scheme == "argon2id" else dict(SCRYPT_PARAMS)
        salt = secrets.token_bytes(params["salt_len"])
        digest = _derive(new_password, salt, scheme, params)
        self._data.update(
            {
                "scheme": scheme,
                "params": params,
                "salt_b64": base64.b64encode(salt).decode("ascii"),
                "password_hash_b64": base64.b64encode(digest).decode("ascii"),
                "failed_count": 0,
                "lock_until": 0,
            }
        )
        self._save()
        return True, "ok"

    def create_session(self) -> AdminSession:
        return AdminSession()
