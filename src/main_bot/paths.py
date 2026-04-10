"""Paths anchored to the repository root (parent of ``src/``)."""
from pathlib import Path


def project_root() -> Path:
    """Repository root directory."""
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = project_root()
