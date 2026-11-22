from __future__ import annotations

import hashlib
import json
import time
import zipfile
from pathlib import Path
from typing import Callable

from .domain import MODEL_REPOS
from .i18n import tr


class Cancelled(Exception):
    pass


def check_cancel(cancel):
    if cancel.is_set():
        raise Cancelled()


def ensure_model(model: str, root: Path, emit: Callable, cancel) -> Path:
    if model not in MODEL_REPOS:
        raise ValueError(tr('Неизвестная модель'))
    folder = root / "models" / model
    required = ("config.json", "model.bin", "tokenizer.json")
    def complete():
        return all((folder / name).is_file() and (folder / name).stat().st_size > 0 for name in required) and any(
            path.stat().st_size > 0 for path in folder.glob("vocabulary.*"))

    if (folder / ".ready").exists() and complete():
        return folder
    from huggingface_hub import HfApi, hf_hub_url
    check_cancel(cancel)
    emit("progress", stage=tr('Скачивание модели · потребуется интернет'), progress=0)
    info = HfApi().model_info(MODEL_REPOS[model], files_metadata=True)
    files = [file for file in info.siblings if file.rfilename in (*required, "preprocessor_config.json")
             or file.rfilename.startswith("vocabulary.")]
    total = sum(file.size or 0 for file in files)
    completed = 0
    for file in files:
        check_cancel(cancel)
        digest = file.lfs.sha256 if file.lfs else file.blob_id
        if not digest:
            raise RuntimeError(tr('Сервер не предоставил контрольную сумму модели.'))

        def progress(kind, **values):
            values["progress"] = (completed + values.get("progress", 0) * (file.size or 0)) / max(total, 1)
            emit(kind, **values)

        download_file(hf_hub_url(MODEL_REPOS[model], file.rfilename, revision=info.sha),
                      folder / file.rfilename, digest, progress, cancel, label=tr('Модель {0}', model))
        completed += file.size or 0
    check_cancel(cancel)
    if not complete():
        raise RuntimeError(tr('Модель скачана не полностью. Повторите загрузку.'))
    (folder / ".ready").write_text(json.dumps({"revision": info.sha}), encoding="utf-8")
    return folder


# Official NVIDIA Windows wheels, pinned with hashes. No pip or system-wide CUDA installation.
GPU_PACKAGES = (
    ("cublas", "https://files.pythonhosted.org/packages/70/61/7d7b3c70186fb651d0fbd35b01dbfc8e755f69fd58f817f3d0f642df20c3/nvidia_cublas_cu12-12.8.4.1-py3-none-win_amd64.whl",
     "47e9b82132fa8d2b4944e708049229601448aaad7e6f296f630f2d1a32de35af"),
    ("cudnn", "https://files.pythonhosted.org/packages/39/6a/5e9910b2b2c9dcddee9aaef372b3db0f08b9f7eaf1d462f859461a79caf9/nvidia_cudnn_cu12-9.8.0.87-py3-none-win_amd64.whl",
     "b4b5cfddc32aa4180f9d390ee99e9a9f55a89e7087329b41aba4319327e22466"),
    ("runtime", "https://files.pythonhosted.org/packages/30/a5/a515b7600ad361ea14bfa13fb4d6687abf500adc270f19e89849c0590492/nvidia_cuda_runtime_cu12-12.8.90-py3-none-win_amd64.whl",
     "c0c6027f01505bfed6c3b21ec546f69c687689aad5f1a377554bc6ca4aa993a8"),
)


def download_file(url: str, destination: Path, expected_hash: str, emit: Callable, cancel, label=tr('GPU-компоненты')):
    import requests

    destination.parent.mkdir(parents=True, exist_ok=True)
    def hash_file(path):
        digest = hashlib.sha256() if len(expected_hash) == 64 else hashlib.sha1()
        if len(expected_hash) == 40:
            digest.update(f"blob {path.stat().st_size}\0".encode())
        with path.open("rb") as stream:
            while block := stream.read(4 * 1024 * 1024):
                check_cancel(cancel)
                digest.update(block)
        return digest.hexdigest()

    if destination.is_file() and hash_file(destination) == expected_hash:
        return
    partial = destination.with_suffix(".part")
    initial = partial.stat().st_size if partial.exists() else 0
    with requests.get(url, headers={"Range": f"bytes={initial}-"} if initial else {},
                      stream=True, timeout=(15, 20)) as response:
        if response.status_code == 416:
            # A complete .part may remain after cancellation during checksum verification.
            response.close()
        else:
            response.raise_for_status()
            resume = initial > 0 and response.status_code == 206
            if not resume:
                initial = 0
            total = initial + int(response.headers.get("Content-Length", 0))
            done = initial
            last = 0.0
            with partial.open("ab" if resume else "wb") as stream:
                for block in response.iter_content(1024 * 1024):
                    check_cancel(cancel)
                    stream.write(block)
                    done += len(block)
                    if time.monotonic() - last > 0.15:
                        last = time.monotonic()
                        stage = (tr('{0}: {1:.0f} / {2:.0f} МБ', label, done / 1e6, total / 1e6) if total > 1_000_000
                                 else tr('{0}: служебные файлы', label))
                        emit("progress", stage=stage,
                             progress=min(0.99, done / total) if total else 0)
    if hash_file(partial) != expected_hash:
        partial.unlink(missing_ok=True)
        raise RuntimeError(tr('Контрольная сумма загрузки не совпала. Повторите попытку.'))
    partial.replace(destination)


def ensure_gpu(root: Path, emit: Callable, cancel) -> Path:
    target = root / "gpu" / "cuda12-cudnn9-v1"
    target.mkdir(parents=True, exist_ok=True)
    if (target / ".ready").exists():
        return target
    for name, url, digest in GPU_PACKAGES:
        check_cancel(cancel)
        done_marker = target / f".{name}.ready"
        if done_marker.exists():
            continue
        archive = target / f"{name}.whl"
        emit("progress", stage=tr('Загрузка GPU-компонентов · {0}', name), progress=0)
        download_file(url, archive, digest, emit, cancel)
        with zipfile.ZipFile(archive) as wheel:
            for member in wheel.infolist():
                check_cancel(cancel)
                path = Path(member.filename)
                if path.suffix.lower() == ".dll" or "license" in path.name.lower():
                    # Only basenames are used; no archive-supplied extraction paths.
                    destination = target / (path.name if path.suffix.lower() == ".dll" else f"{name}-{path.name}")
                    with wheel.open(member) as source, destination.open("wb") as output:
                        import shutil
                        shutil.copyfileobj(source, output)
        done_marker.write_text("1", encoding="utf-8")
        archive.unlink()
    (target / ".ready").write_text(json.dumps({"version": 1}), encoding="utf-8")
    return target
