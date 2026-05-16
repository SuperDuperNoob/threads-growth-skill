from __future__ import annotations
from pathlib import Path
from typing import Any
import json

class Config:
    def __init__(self, home: Path | None = None):
        self.home = home or Path.home() / ".orbit"
        self.home.mkdir(parents=True, exist_ok=True)
        self._path = self.home / "config.json"
        if not self._path.exists():
            self._path.write_text("{}")
        self._data = json.loads(self._path.read_text())

    def get(self, key: str) -> Any:
        parts = key.split(".")
        node = self._data
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def set(self, key: str, value: Any) -> None:
        parts = key.split(".")
        node = self._data
        for part in parts[:-1]:
            child = node.get(part)
            if child is None:
                node[part] = {}
                node = node[part]
            elif not isinstance(child, dict):
                raise ValueError(f"Key segment '{part}' exists as a non-dict value")
            else:
                node = child
        node[parts[-1]] = value
        self._path.write_text(json.dumps(self._data, indent=2))
