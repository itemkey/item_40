from __future__ import annotations

import json
import lzma
import os
import shutil
import struct
import tempfile
import zipfile
import zlib
from contextlib import contextmanager
from pathlib import Path

from .downloads import check_cancel, download_file
from .i18n import tr


@contextmanager
def component_lock(root, cancel, name="components"):
    import msvcrt

    folder = Path(root) / "tools"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / f"{name}.lock").open("a+b") as stream:
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b"0")
            stream.flush()
        while True:
            check_cancel(cancel)
            try:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                cancel.wait(0.2)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def ensure_media(root, emit, cancel, names=("ffmpeg",)):
    from .youtube_tools import PACKAGES, ensure_tools

    packages = [package for package in PACKAGES if package.name in names]
    if all((Path(root) / "tools/youtube" / package.name / package.version / ".ready").is_file()
           and all((Path(root) / "tools/youtube" / package.name / package.version / name).is_file()
                   for name in package.files) for package in packages):
        return ensure_tools(Path(root), emit, cancel, names)
    with component_lock(root, cancel, "media"):
        return ensure_tools(Path(root), emit, cancel, names)


def locate(folder, filename):
    matches = list(folder.rglob(filename))
    if not matches:
        raise RuntimeError(tr('Компонент не содержит файл {0}.', filename))
    return min(matches, key=lambda path: len(path.parts))


def ensure_component(name, root, emit, cancel) -> Path:
    from .youtube import run_tool

    config = json.loads((Path(__file__).parent / "component_manifest.json").read_text(encoding="utf-8"))[name]
    root = Path(root)
    destination = root / "tools" / name / config["version"]
    if (destination / ".ready").is_file():
        try:
            return locate(destination, config["executable"])
        except RuntimeError:
            pass
    with component_lock(root, cancel, name):
        if (destination / ".ready").is_file():
            try:
                return locate(destination, config["executable"])
            except RuntimeError:
                pass
    bootstrap = None
    if config["kind"] in {"7z", "nsis", "calibre"}:
        bootstrap = ensure_component("7zip", root, emit, cancel)
    with component_lock(root, cancel, name):
        if (destination / ".ready").is_file():
            return locate(destination, config["executable"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        for abandoned in destination.parent.glob(f".{name}-*"):
            if abandoned.is_dir() and not abandoned.is_symlink():
                shutil.rmtree(abandoned, ignore_errors=True)
        packages = root / "tools" / "packages"
        packages.mkdir(parents=True, exist_ok=True)
        archive = packages / config["filename"]
        emit("progress", stage=tr('Подготовка компонента · {0}', name), progress=None)
        download_file(config["url"], archive, config["sha256"], emit, cancel, label=name)
        temporary = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=destination.parent))
        try:
            kind = config["kind"]
            if kind == "7zip":
                helper = packages / "7zr-26.06.exe"
                download_file(config["bootstrap_url"], helper, config["bootstrap_sha256"], emit, cancel,
                              label="7-Zip")
                run_tool([helper, "x", "-y", f"-o{temporary}", archive], cancel)
            elif kind == "zip":
                with zipfile.ZipFile(archive) as zipped:
                    for member in zipped.infolist():
                        check_cancel(cancel)
                        target = (temporary / member.filename).resolve()
                        if not target.is_relative_to(temporary.resolve()):
                            raise RuntimeError(tr('Архив компонента содержит некорректный путь.'))
                        zipped.extract(member, temporary)
            elif kind in {"7z", "nsis"}:
                run_tool([bootstrap, "x", "-y", f"-o{temporary}", archive], cancel)
            elif kind == "calibre":
                payload = temporary / ".payload"
                payload.mkdir()
                run_tool([bootstrap, "e", "-y", f"-o{payload}", archive, r".rsrc\EXTRA\EXTRA"], cancel)
                compressed = payload / "EXTRA"
                unpacked = payload / "calibre.zip"
                with compressed.open("rb") as source, unpacked.open("wb") as output:
                    header = source.read(6)
                    if header[:4] != b"LZIP" or header[4] not in {0, 1}:
                        raise RuntimeError("Invalid calibre portable payload")
                    code = header[5]
                    dictionary = (1 << (code & 31)) - ((1 << (code & 31)) // 16) * ((code >> 5) & 7)
                    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[
                        {"id": lzma.FILTER_LZMA1, "dict_size": dictionary, "lc": 3, "lp": 0, "pb": 2}])
                    checksum = 0
                    while not decoder.eof:
                        check_cancel(cancel)
                        block = source.read(1024 * 1024) if decoder.needs_input else b""
                        if not block and decoder.needs_input:
                            raise RuntimeError("Truncated calibre portable payload")
                        data = decoder.decompress(block, max_length=4 * 1024 * 1024)
                        output.write(data)
                        checksum = zlib.crc32(data, checksum)
                    trailer_size = 20 if header[4] == 1 else 12
                    source.seek(-trailer_size, 2)
                    trailer = source.read(trailer_size)
                    expected_crc, expected_size = struct.unpack("<IQ", trailer[:12])
                    if checksum != expected_crc or output.tell() != expected_size:
                        raise RuntimeError("Invalid calibre portable payload checksum")
                run_tool([bootstrap, "x", "-y", f"-o{temporary}", unpacked], cancel)
                shutil.rmtree(payload)
            elif kind == "msi":
                msiexec = Path(os.environ["SystemRoot"]) / "System32" / "msiexec.exe"
                run_tool([msiexec, "/a", archive, "/qn", f"TARGETDIR={temporary}", "/norestart"], cancel)
            executable = locate(temporary, config["executable"])
            if name == "tesseract":
                data = executable.parent / "tessdata"
                data.mkdir(exist_ok=True)
                for language in ("rus", "eng"):
                    model = config["languages"][language]
                    download_file(model["url"], data / f"{language}.traineddata", model["sha256"], emit, cancel,
                                  label=f"OCR · {language}")
            check_cancel(cancel)
            if destination.exists():
                shutil.rmtree(destination)
            temporary.rename(destination)
            (destination / ".ready").touch()
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)
    return locate(destination, config["executable"])
