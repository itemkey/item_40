from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from .paths import default_output_dir


def output_directory(store) -> Path:
    return Path(store.setting("output_dir", str(default_output_dir())))


def write_text_atomic(destination: Path, text: str):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                         prefix=".item40-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def save_result(store, job_id: str) -> Path | None:
    job = store.get(job_id)
    if not job or job["status"] != "completed":
        return None
    destination = Path(job["output_path"]) if job["output_path"] else None
    reserved = False
    try:
        if destination is None:
            directory = output_directory(store)
            directory.mkdir(parents=True, exist_ok=True)
            stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(job["source"]).stem).strip(" .")[:160] or "audio"
            if stem.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                                              *(f"LPT{i}" for i in range(1, 10))}:
                stem = "_" + stem
            index = 1
            while True:
                destination = directory / (stem + (f"_{index}" if index > 1 else "") + ".txt")
                try:
                    with destination.open("x", encoding="utf-8"):
                        pass
                    reserved = True
                    break
                except FileExistsError:
                    index += 1
        write_text_atomic(destination, job["transcript"])
        store.update(job_id, output_path=str(destination), output_error="")
        return destination
    except OSError as error:
        if reserved and destination:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
        store.update(job_id, output_error=f"Не удалось сохранить TXT: {error}")
        return None
