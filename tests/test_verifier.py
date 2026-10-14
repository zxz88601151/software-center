import hashlib

from sc.verifier import is_regular_file, sha256_file, verify_file


def test_sha_and_verify(tmp_path):
    p = tmp_path / "a.bin"
    data = b"abc123"
    p.write_bytes(data)
    assert sha256_file(p) == hashlib.sha256(data).hexdigest()
    assert verify_file(p, len(data), hashlib.sha256(data).hexdigest())[0]


def test_size_mismatch(tmp_path):
    p = tmp_path / "a.bin"
    p.write_bytes(b"abc")
    ok, reason = verify_file(p, 999, hashlib.sha256(b"abc").hexdigest())
    assert not ok and "size" in reason


def test_sha_mismatch(tmp_path):
    p = tmp_path / "a.bin"
    p.write_bytes(b"abc")
    ok, _ = verify_file(p, 3, "0" * 64)
    assert not ok


def test_directory_is_not_regular_file(tmp_path):
    assert not is_regular_file(tmp_path)
    ok, _ = verify_file(tmp_path, 0, "0" * 64)
    assert not ok


def test_missing_file(tmp_path):
    ok, _ = verify_file(tmp_path / "nope.bin", 1, "0" * 64)
    assert not ok
