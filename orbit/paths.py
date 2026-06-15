"""Resolution of Orbit's home directory (where config.json + orbit.db live).

Precedence: explicit arg > $ORBIT_HOME > ~/.orbit. The env var lets Keith's Mac
and the Hermes agent on the Beelink point at the same NAS-hosted directory so
they share one config + DB.
"""
from __future__ import annotations
import os
from pathlib import Path


def resolve_orbit_home(home: Path | None = None) -> Path:
    if home is not None:
        return Path(home)
    env = os.environ.get("ORBIT_HOME")
    if env:
        return Path(env)
    return Path.home() / ".orbit"
