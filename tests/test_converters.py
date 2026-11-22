import ast
import gzip
import json
import os
import uuid
from pathlib import Path
from queue import Queue
from threading import Event

import pytest

from item40.converters import Target, archive_convert, category, convert_file, convert_worker, publish_files
from item40.i18n import language, set_language, tr
from item40.soundcloud import collection, track_url


def test_lottie_json_is_detected_without_treating_arbitrary_json_as_animation(tmp_path):
    source = tmp_path / "animation.json"
    source.write_text(json.dumps({"layers": [], "fr": 30, "w": 100, "h": 100}), encoding="utf-8")
    assert category(source) == "animation"
    source.write_text('{"data": 1}', encoding="utf-8")
    assert category(source) == "document"


def test_compressed_archive_extension_is_preserved_without_overwriting(tmp_path):
    source = tmp_path / "output.tar.gz"
    source.write_bytes(gzip.compress(b"archive payload"))
    previous = tmp_path / "sample.tar.gz"
    previous.write_bytes(b"previous archive")
    result = publish_files([source], "sample.zip", tmp_path)
    assert result.name == "sample_2.tar.gz"
    assert gzip.decompress(result.read_bytes()) == b"archive payload"
    assert previous.read_bytes() == b"previous archive"


@pytest.mark.parametrize("entry", ["../outside.txt", "C:\\outside.txt", "file.txt:stream"])
def test_archive_conversion_rejects_escaping_paths_before_extraction(tmp_path, monkeypatch, entry):
    from item40 import converters

    monkeypatch.setattr(converters, "ensure_component", lambda *args: tmp_path / "7z.exe")
    commands = []

    def run(args, cancel):
        commands.append(args)
        return f"Path = {entry}\nSize = 100\n"

    monkeypatch.setattr(converters, "run_tool", run)
    with pytest.raises(ValueError):
        archive_convert(tmp_path / "bad.zip", Target("zip", "ZIP", "zip", "archive"), tmp_path,
                        tmp_path, lambda *args, **kwargs: None, Event())
    assert len(commands) == 1


def test_batch_keeps_completed_outputs_and_continues_after_failure(tmp_path, monkeypatch):
    from item40 import converters

    def convert(source, target, work, *args):
        if source.endswith("bad.wav"):
            raise ValueError("Corrupt input")
        work.mkdir(parents=True)
        output = work / "output.txt"
        output.write_text("converted", encoding="utf-8")
        return [output]

    monkeypatch.setattr(converters, "convert_file", convert)
    target = Target("text", "TXT", "txt", "test")
    events = Queue()
    convert_worker(tmp_path, [(str(tmp_path / name), target, {}) for name in ("first.wav", "bad.wav", "last.wav")],
                   tmp_path / "work", tmp_path, events, Event())
    kinds = []
    while not events.empty():
        kinds.append(events.get_nowait()[0])
    assert kinds.count("saved") == 2
    assert kinds.count("file_failed") == 1
    assert kinds[-1] == "completed"
    assert (tmp_path / "first.txt").read_text() == "converted"
    assert (tmp_path / "last.txt").is_file()


def test_translation_keeps_placeholder_formatting_and_source_language():
    previous = language()
    try:
        set_language("en")
        assert tr("Выбрано {0} из {1}", 2, 8) == "Selected 2 of 8"
        assert tr("{0:.0f} кбит/с", 128.1) == "128 kbps"
        set_language("ru")
        assert tr("Выбрано {0} из {1}", 2, 8) == "Выбрано 2 из 8"
    finally:
        set_language(previous)


def test_mpl2_subtitles_use_an_explicit_writer_and_keep_timing(tmp_path):
    source = tmp_path / "captions.srt"
    source.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
    target = Target("subtitle:mpl", "MPL2", "mpl", "subtitle", "mpl2")
    files = convert_file(source, target, tmp_path / "work", tmp_path, lambda *args, **kwargs: None, Event(), {})
    assert files[0].read_text(encoding="utf-8").strip() == "[10][20] Hello"


@pytest.mark.parametrize("url", ["https://soundcloud.com/artist/song", "on.soundcloud.com/short", "https://soundcloud.com/artist/sets/album"])
def test_soundcloud_links(url):
    assert track_url(url).startswith("https://")


@pytest.mark.parametrize("url", ["https://soundcloud.com.evil.test/artist/song", "https://user@soundcloud.com/song", "file:///C:/music.mp3"])
def test_soundcloud_rejects_other_hosts(url):
    with pytest.raises(ValueError):
        track_url(url)


def test_soundcloud_playlist_preserves_unavailable_entries():
    title, tracks = collection({"_type": "playlist", "title": "Album", "entries": [
        {"id": "1", "title": "Song", "url": "https://soundcloud.com/artist/song"}, None]})
    assert title == "Album"
    assert [track.unavailable for track in tracks] == [False, True]


def test_english_catalog_covers_all_translated_messages():
    root = Path(__file__).parents[1] / "item40"
    catalog = json.loads((root / "translations/en.json").read_text(encoding="utf-8"))
    missing = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr"
                    and node.args and isinstance(node.args[0], ast.Constant)):
                message = node.args[0].value
                if message not in catalog:
                    missing.append((path.name, message))
    assert not missing


@pytest.mark.skipif(os.name != "nt", reason="Windows language setting")
def test_interface_language_is_shared_with_the_installer_and_survives_restart(monkeypatch):
    import winreg

    from item40.i18n import save_language, selected_language

    key = "Software\\item40-language-test-" + uuid.uuid4().hex
    monkeypatch.setenv("ITEM40_LANGUAGE_REGISTRY_KEY", key)
    monkeypatch.delenv("ITEM40_UI_LANGUAGE", raising=False)
    try:
        save_language("en")
        assert selected_language() == "en"
        save_language("ru")
        assert selected_language() == "ru"
    finally:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
