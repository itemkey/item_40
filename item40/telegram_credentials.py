from __future__ import annotations

import ctypes as ct
import json
import os
import tempfile
from ctypes import wintypes as wt
from pathlib import Path


class Blob(ct.Structure):
    _fields_ = [("size", wt.DWORD), ("data", ct.POINTER(ct.c_ubyte))]


def protect(data: bytes, *, decrypt=False) -> bytes:
    if os.name != "nt":
        raise OSError("Сохранение токена поддерживается в Windows.")
    crypt = ct.WinDLL("crypt32", use_last_error=True)
    kernel = ct.WinDLL("kernel32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ct.POINTER(Blob), ct.c_void_p, ct.c_void_p, ct.c_void_p,
                         ct.c_void_p, wt.DWORD, ct.POINTER(Blob)]
    function.restype = wt.BOOL
    kernel.LocalFree.argtypes = [ct.c_void_p]
    kernel.LocalFree.restype = ct.c_void_p
    buffer = (ct.c_ubyte * len(data)).from_buffer_copy(data)
    source, target = Blob(len(data), buffer), Blob()
    if not function(ct.byref(source), None, None, None, None, 1, ct.byref(target)):
        raise OSError("Не удалось открыть или сохранить подключение Telegram в этом профиле Windows.")
    try:
        return ct.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def save_connection(root: Path, token: str, username: str):
    folder = root / "telegram"
    folder.mkdir(parents=True, exist_ok=True)
    payload = protect(json.dumps({"token": token, "username": username}).encode("utf-8"))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".connection-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, folder / "connection.bin")
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def load_connection(root: Path) -> tuple[str, str] | None:
    path = root / "telegram" / "connection.bin"
    if not path.is_file():
        return None
    try:
        saved = json.loads(protect(path.read_bytes(), decrypt=True))
        if not isinstance(saved["token"], str) or not isinstance(saved["username"], str):
            raise ValueError
        return saved["token"], saved["username"]
    except (OSError, ValueError, KeyError, TypeError):
        raise OSError("Не удалось прочитать сохранённое подключение Telegram. Подключите бота заново.") from None


def forget_connection(root: Path):
    (root / "telegram" / "connection.bin").unlink(missing_ok=True)
