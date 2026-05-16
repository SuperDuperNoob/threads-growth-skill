import json
from pathlib import Path

class Config:
    def __init__(self, home: Path = None):
        self.home = home or Path.home() / ".orbit"
        self.home.mkdir(parents=True, exist_ok=True)
        self._path = self.home / "config.json"
        if not self._path.exists():
            self._path.write_text("{}")
        self._data = json.loads(self._path.read_text())

    def get(self, key: str):
        parts = key.split(".")
        node = self._data
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def set(self, key: str, value):
        parts = key.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        self._path.write_text(json.dumps(self._data, indent=2))
