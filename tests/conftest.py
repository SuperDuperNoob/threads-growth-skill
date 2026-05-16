import pytest
from pathlib import Path

@pytest.fixture
def orbit_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ORBIT_HOME", str(tmp_path))
    return tmp_path
