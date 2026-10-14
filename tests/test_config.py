import json

from sc.config import load_config, save_config


def test_missing_config_uses_defaults(tmp_path):
    cfg, recovered = load_config(tmp_path / "cfg.json")
    assert not recovered
    assert cfg["download_dir"]
    assert cfg["open_folder_after_download"] is False


def test_corrupt_config_backed_up_and_recovered(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text("{not json", encoding="utf-8")
    cfg, recovered = load_config(p)
    assert recovered
    assert (tmp_path / "cfg.json.bad").exists()
    assert cfg["download_dir"]


def test_save_rejects_nonexistent_dir_no_autocreate(tmp_path):
    p = tmp_path / "cfg.json"
    missing = tmp_path / "does-not-exist"
    try:
        save_config(p, {"download_dir": str(missing), "open_folder_after_download": False})
    except ValueError:
        pass
    else:
        raise AssertionError("save must refuse a non-existing download dir")
    assert not missing.exists(), "config save must never auto-create the dir"
    assert not p.exists()


def test_save_and_reload_atomic(tmp_path):
    p = tmp_path / "cfg.json"
    save_config(p, {"download_dir": str(tmp_path), "open_folder_after_download": True})
    cfg, _ = load_config(p)
    assert cfg["download_dir"] == str(tmp_path)
    assert cfg["open_folder_after_download"] is True
    assert json.loads(p.read_text(encoding="utf-8"))["download_dir"] == str(tmp_path)
