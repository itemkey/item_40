from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("ITEM40_DATA_DIR") or os.environ.get("MASTERSKAYA_DATA_DIR")
    base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    legacy = base / "Masterskaya"
    # Existing installations keep their data and downloaded models in place.
    root = Path(override) if override else legacy if legacy.exists() else base / "item-40"
    root.mkdir(parents=True, exist_ok=True)
    return root


def database_path(root: Path) -> Path:
    legacy = root / "masterskaya.sqlite3"
    return legacy if legacy.exists() else root / "item-40.sqlite3"


def default_output_dir() -> Path:
    from PySide6.QtCore import QStandardPaths
    documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    return (Path(documents) if documents else Path.home() / "Documents") / "item-40"
