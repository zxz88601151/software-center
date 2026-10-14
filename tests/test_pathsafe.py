from pathlib import Path

from sc.pathsafe import (
    is_reserved_name,
    is_within_directory,
    validate_download_dir,
    validate_pure_filename,
    validate_relative_source,
)


def test_reserved_variants_all_rejected():
    for name in ["NUL", "nul", "Nul", "NUL.txt", "nul.bin", "Nul .bin", "CON", "con.txt",
                 "PRN", "AUX", "COM1", "com9", "LPT1", "lpt9", "COM1.txt"]:
        assert is_reserved_name(name), name
        ok, _ = validate_pure_filename(name)
        assert not ok, name


def test_reserved_with_directory_prefix():
    assert is_reserved_name("dir/NUL.txt")
    assert is_reserved_name("C:\\x\\NUL")
    assert is_reserved_name("\\\\server\\share\\NUL")


def test_pure_filename_rejects_traversal_and_ads():
    for bad in ["../evil.bin", "a/b.bin", "a\\b.bin", "a:b.bin", "name:stream",
                ".", "..", "a.bin.", "a.bin ", " a.bin", "\\\\?\\C:\\a.bin", "\\\\.\\NUL"]:
        ok, _ = validate_pure_filename(bad)
        assert not ok, bad


def test_pure_filename_accepts_normal():
    ok, _ = validate_pure_filename("setup-v1.2.0.bin")
    assert ok


def test_pure_filename_rejects_control_and_too_long():
    ok, _ = validate_pure_filename("a\x01b.bin")
    assert not ok
    ok, _ = validate_pure_filename("x" * 121 + ".bin")
    assert not ok


def test_relative_source_validation():
    ok, _ = validate_relative_source("sample_files/tool.bin")
    assert ok
    for bad in ["../secret.bin", "/abs.bin", "C:\\evil.bin", "\\\\server\\share\\x.bin",
                "sample_files/NUL.txt", "sample_files/a:b.bin", "\\\\?\\C:\\x.bin"]:
        ok, _ = validate_relative_source(bad)
        assert not ok, bad


def test_within_directory_no_string_prefix_bug(tmp_path):
    base = tmp_path / "dl"
    base.mkdir()
    assert is_within_directory(base, base / "a.bin")
    assert is_within_directory(base, base)
    assert not is_within_directory(base, tmp_path / "dl-evil" / "a.bin")


def test_download_dir_rejects_unc_and_missing(tmp_path):
    ok, _ = validate_download_dir("\\\\server\\share")
    assert not ok
    ok, _ = validate_download_dir(str(tmp_path / "nope"))
    assert not ok
    ok, _ = validate_download_dir(str(tmp_path))
    assert ok
    f = tmp_path / "file.txt"
    f.write_text("x")
    ok, _ = validate_download_dir(str(f))
    assert not ok
