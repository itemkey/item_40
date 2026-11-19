import gzip
import json
import os
from queue import Queue
from threading import Event

import pytest
import requests

from item40.telegram import TelegramAPI, TelegramError, pack_name, parse_pack, worker
from item40.telegram_credentials import forget_connection, load_connection, save_connection

TOKEN = "123456:TEST_ONLY_TOKEN"
WEBP = b"RIFF\x04\x00\x00\x00WEBP"
TGS = gzip.compress(json.dumps({"v": "5.5.2", "layers": []}).encode())
WEBM = b"\x1a\x45\xdf\xa3test-video"


def sticker_set():
    return {"name": "TestEmoji", "title": "Тестовый пак", "sticker_type": "custom_emoji", "stickers": [
        {"custom_emoji_id": str(index), "file_id": f"file-{index}", "emoji": "😀", "file_size": len(data),
         "is_animated": index == 2, "is_video": index == 3, "thumbnail": {"file_id": f"thumb-{index}"}}
        for index, data in enumerate((WEBP, TGS, WEBM), 1)
    ]}


class Response:
    def __init__(self, data=None, *, status=200, blocks=()):
        self.data, self.status_code, self.blocks = data, status, blocks

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def json(self):
        return self.data

    def iter_content(self, size):
        yield from self.blocks


def drain(events):
    result = []
    while not events.empty():
        result.append(events.get_nowait())
    return result


@pytest.mark.parametrize("link", [
    "https://t.me/addemoji/TestEmoji", " t.me/addemoji/TestEmoji ",
    "https://telegram.me/addemoji/TestEmoji?foo=1", "tg://addemoji?set=TestEmoji",
])
def test_pack_links(link):
    assert pack_name(link) == "TestEmoji"


@pytest.mark.parametrize("link", [
    "https://t.me/addstickers/TestEmoji", "https://t.me.evil.com/addemoji/TestEmoji",
    "https://user@t.me/addemoji/TestEmoji", "https://t.me/addemoji/../file", "tg://resolve?domain=TestEmoji",
])
def test_other_links_are_rejected(link):
    with pytest.raises(ValueError):
        pack_name(link)


def test_pack_preserves_original_types_and_order():
    pack = parse_pack(sticker_set())
    assert [(emoji.id, emoji.position, emoji.kind) for emoji in pack.emojis] == [
        ("1", 1, "webp"), ("2", 2, "tgs"), ("3", 3, "webm")]
    with pytest.raises(TelegramError, match="тип набора"):
        parse_pack({"sticker_type": "regular"})


def test_selected_originals_and_retry_do_not_overwrite(tmp_path, monkeypatch):
    pack = parse_pack(sticker_set())
    folder = tmp_path / pack.name
    work = folder / ".work"
    work.mkdir(parents=True)
    existing = folder / "002_2.tgs"
    existing.write_bytes(b"existing original")
    failed = {"2"}
    requested = []

    def fake_fetch(self, file_id, destination, **kwargs):
        identity = file_id.split("-")[1]
        requested.append(identity)
        if identity in failed:
            raise TelegramError("Нет ответа Telegram.")
        destination.write_bytes({"1": WEBP, "2": TGS, "3": WEBM}[identity])

    monkeypatch.setattr(TelegramAPI, "fetch", fake_fetch)
    events = Queue()
    worker(tmp_path, TOKEN, "download", {"emojis": pack.emojis[1:], "folder": work}, events, Event())
    result = drain(events)
    assert requested == ["2", "3"]
    assert [values["id"] for kind, values in result if kind == "file_failed"] == ["2"]
    assert (folder / "003_3.webm").read_bytes() == WEBM
    failed.clear()
    worker(tmp_path, TOKEN, "download", {"emojis": pack.emojis[1:2], "folder": work}, events, Event())
    assert (folder / "002_2_2.tgs").read_bytes() == TGS
    assert existing.read_bytes() == b"existing original"
    assert not list(work.iterdir())


def test_incomplete_download_is_removed_and_cancel_is_checked(tmp_path, monkeypatch):
    cancel = Event()
    api = TelegramAPI(TOKEN, cancel, lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "call", lambda *args, **kwargs: {"file_path": "file.bin", "file_size": 20})
    monkeypatch.setattr(api.session, "get", lambda *args, **kwargs: Response(blocks=[b"short"]))
    target = tmp_path / "file.part"
    with pytest.raises(TelegramError, match="не полностью"):
        api.fetch("file", target)
    assert not target.exists()

    def cancelled_blocks():
        yield b"first"
        cancel.set()
        yield b"second"

    monkeypatch.setattr(api.session, "get", lambda *args, **kwargs: Response(blocks=cancelled_blocks()))
    from item40.downloads import Cancelled

    with pytest.raises(Cancelled):
        api.fetch("file", target)
    assert not target.exists()
    api.close()


def test_api_rate_limit_and_redacted_network_error(monkeypatch):
    cancel = Event()
    api = TelegramAPI(TOKEN, cancel, lambda *args, **kwargs: None)
    responses = iter([Response({"parameters": {"retry_after": 1}}, status=429),
                      Response({"ok": True, "result": {"is_bot": True}})])
    monkeypatch.setattr(api.session, "post", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(cancel, "wait", lambda seconds: False)
    assert api.call("getMe") == {"is_bot": True}

    def unavailable(*args, **kwargs):
        raise requests.ConnectionError(f"https://api.telegram.org/bot{TOKEN}/getMe")

    monkeypatch.setattr(api.session, "post", unavailable)
    with pytest.raises(TelegramError) as error:
        api.call("getMe")
    assert TOKEN not in str(error.value)
    assert "api.telegram.org" not in str(error.value)
    api.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_connection_is_encrypted_and_can_be_reopened_and_removed(tmp_path):
    save_connection(tmp_path, TOKEN, "test_bot")
    assert TOKEN.encode() not in (tmp_path / "telegram" / "connection.bin").read_bytes()
    assert load_connection(tmp_path) == (TOKEN, "test_bot")
    forget_connection(tmp_path)
    assert load_connection(tmp_path) is None
