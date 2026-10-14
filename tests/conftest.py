import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture()
def tmp_data(tmp_path):
    data = tmp_path / "data"
    (data / "sample_files").mkdir(parents=True)
    (data / "icons").mkdir(parents=True)
    (data / "backups").mkdir(parents=True)
    (data / "trash").mkdir(parents=True)
    return data


@pytest.fixture()
def sample_file(tmp_data):
    p = tmp_data / "sample_files" / "demo.bin"
    p.write_bytes(b"hello-software-center\n" + b"X" * 100)
    return p
