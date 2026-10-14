from sc.models import SoftwareItem


def _good(**over):
    kw = dict(
        id="demo", name="Demo", version="1.0", category="工具",
        source="sample_files/demo.bin", file_name="demo.bin",
        size_bytes=10, sha256="a" * 64, sort_order=10, status="published",
    )
    kw.update(over)
    return SoftwareItem(**kw)


def test_valid_item():
    assert _good().validate() == []


def test_zero_byte_rejected():
    assert any("size_bytes" in e for e in _good(size_bytes=0).validate())


def test_bad_sha_rejected():
    assert _good(sha256="ABC").validate()
    assert _good(sha256="g" * 64).validate()


def test_bad_filename_rejected():
    assert _good(file_name="NUL.txt").validate()
    assert _good(file_name="../evil.bin").validate()


def test_bad_id_and_status():
    assert _good(id="Bad ID!").validate()
    assert _good(status="deleted").validate()


def test_roundtrip():
    item = _good()
    assert SoftwareItem.from_dict(item.to_dict()).to_dict() == item.to_dict()
