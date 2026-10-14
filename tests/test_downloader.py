import hashlib
import time

import pytest

from sc.downloader import download_file


@pytest.fixture()
def src(tmp_data, sample_file):
    data = sample_file.read_bytes()
    return sample_file, len(data), hashlib.sha256(data).hexdigest()


def test_download_success(tmp_path, tmp_data, src):
    source, size, sha = src
    dest = tmp_path / "dl"
    dest.mkdir()
    result = download_file("sample_files/demo.bin", dest, "demo.bin", size, sha, data_dir=tmp_data)
    assert result.success, result.error
    final = dest / "demo.bin"
    assert final.is_file()
    assert final.read_bytes() == source.read_bytes()
    assert list(dest.iterdir()) == [final], "no temp residue"


def test_sha_mismatch_fails_and_cleans(tmp_path, tmp_data, src):
    _, size, _ = src
    dest = tmp_path / "dl"
    dest.mkdir()
    result = download_file("sample_files/demo.bin", dest, "demo.bin", size, "0" * 64, data_dir=tmp_data)
    assert not result.success
    assert not (dest / "demo.bin").exists()
    assert list(dest.iterdir()) == []


def test_size_mismatch_fails(tmp_path, tmp_data, src):
    _, _, sha = src
    dest = tmp_path / "dl"
    dest.mkdir()
    result = download_file("sample_files/demo.bin", dest, "demo.bin", 9999, sha, data_dir=tmp_data)
    assert not result.success
    assert not (dest / "demo.bin").exists()


def test_same_name_refused_and_original_untouched(tmp_path, tmp_data, src):
    _, size, sha = src
    dest = tmp_path / "dl"
    dest.mkdir()
    (dest / "demo.bin").write_bytes(b"ORIGINAL")
    result = download_file("sample_files/demo.bin", dest, "demo.bin", size, sha, data_dir=tmp_data)
    assert not result.success
    assert (dest / "demo.bin").read_bytes() == b"ORIGINAL"


def test_reserved_name_refused(tmp_path, tmp_data, src):
    _, size, sha = src
    dest = tmp_path / "dl"
    dest.mkdir()
    result = download_file("sample_files/demo.bin", dest, "NUL.txt", size, sha, data_dir=tmp_data)
    assert not result.success


def test_cancel_cleans_temp(tmp_path, tmp_data, src):
    _, size, sha = src
    dest = tmp_path / "dl"
    dest.mkdir()
    result = download_file("sample_files/demo.bin", dest, "demo.bin", size, sha,
                           data_dir=tmp_data, cancel_flag=lambda: True)
    assert not result.success and result.cancelled
    assert not (dest / "demo.bin").exists()
    assert list(dest.iterdir()) == []


def test_http_non_localhost_rejected(tmp_path):
    dest = tmp_path / "dl"
    dest.mkdir()
    result = download_file("http://example.com/x.bin", dest, "x.bin", 10, "0" * 64)
    assert not result.success


def test_zero_expected_size_rejected(tmp_path, tmp_data, src):
    _, _, sha = src
    dest = tmp_path / "dl"
    dest.mkdir()
    result = download_file("sample_files/demo.bin", dest, "demo.bin", 0, sha, data_dir=tmp_data)
    assert not result.success
