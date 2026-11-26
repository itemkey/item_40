import json
from pathlib import Path
from queue import Queue
from threading import Event

import pytest

from item40 import tiktok, youtube
from item40.youtube import Selection, ToolError

VIDEO_URL = "https://www.tiktok.com/@example.user/video/6718335390845095173"
TOOLS = (Path("yt-dlp"), Path("deno"), Path("ffmpeg"))


@pytest.mark.parametrize(("link", "expected"), [
    (f" {VIDEO_URL}?is_from_webapp=1#comment ", VIDEO_URL),
    (VIDEO_URL.replace("www.", "m.") + "/", VIDEO_URL),
    (VIDEO_URL.replace("https://www.", "http://"), VIDEO_URL),
    (VIDEO_URL.removeprefix("https://"), VIDEO_URL),
    ("https://vm.tiktok.com/ZM123abc/?share=1", "https://vm.tiktok.com/ZM123abc/"),
    ("vt.tiktok.com/ZM123abc", "https://vt.tiktok.com/ZM123abc/"),
    ("https://tiktok.com/t/ZM123abc?share=1", "https://www.tiktok.com/t/ZM123abc/"),
    ("https://m.tiktok.com/share/video/6718335390845095173",
     "https://www.tiktok.com/@_/video/6718335390845095173"),
    ("https://www.tiktok.com/embed/v2/6718335390845095173",
     "https://www.tiktok.com/@_/video/6718335390845095173"),
])
def test_video_and_short_links_are_normalized(link, expected):
    assert tiktok.video_url(link) == expected


@pytest.mark.parametrize("link", [
    "", "--exec something", "file:///video.mp4", "https://example.com/video/123",
    "https://www.tiktok.com.evil.example/@user/video/123",
    "https://user@www.tiktok.com/@user/video/123", "https://www.tiktok.com:443/@user/video/123",
    "https://www.tiktok.com:invalid/@user/video/123", "https://www.tiktok.com/@user",
    "https://www.tiktok.com/@user/live", "https://www.tiktok.com/@user/photo/123",
    "https://www.tiktok.com/@user/video/123/other", "https://vm.tiktok.com/",
    "https://vt.tiktok.com/token/extra", "https://www.tiktok.com/t/",
    "https://www.tik\ntok.com/@user/video/123",
])
def test_non_video_or_invalid_links_are_rejected(link):
    with pytest.raises(ValueError, match="TikTok"):
        tiktok.video_url(link)


def video_info():
    return {"title": "TikTok test", "duration": 5, "formats": [
        {"format_id": "h264_720p", "ext": "mp4", "vcodec": "h264", "acodec": "aac",
         "width": 720, "height": 1280},
    ]}


def test_inspect_loads_combined_video_and_audio_without_resolving_other_services(monkeypatch):
    calls = []

    def run(args, cancel):
        calls.append(args)
        return json.dumps(video_info())

    monkeypatch.setattr(tiktok, "run_tool", run)
    monkeypatch.setattr(tiktok, "ffmpeg_formats", lambda folder: ["mp4"])
    video, muxers = tiktok.inspect("https://vm.tiktok.com/token/", TOOLS, lambda *a, **kw: None, Event())
    assert video.title == "TikTok test"
    assert video.has_audio and video.resolutions == [1280]
    assert muxers == ["mp4"]
    args = calls[0]
    assert args[args.index("--use-extractors") + 1] == "TikTok,vm.tiktok"
    assert "--no-playlist" in args
    assert args[-2:] == ["--", "https://vm.tiktok.com/token/"]


@pytest.mark.parametrize("info", [
    {"_type": "playlist", "entries": [video_info()]},
    {"_type": "multi_video", "entries": [video_info()]},
    {"formats": [{"format_id": "music", "ext": "m4a", "acodec": "aac"}]},
    {"live_status": "is_live"},
    {"formats": [{"format_id": "drm", "ext": "mp4", "vcodec": "h264", "has_drm": True}]},
])
def test_inspect_rejects_collections_photo_posts_live_and_protected_streams(info, monkeypatch):
    monkeypatch.setattr(tiktok, "run_tool", lambda *args: json.dumps(info))
    with pytest.raises(ValueError):
        tiktok.inspect(VIDEO_URL, TOOLS, lambda *a, **kw: None, Event())


@pytest.fixture
def prepared_tools(monkeypatch):
    monkeypatch.setattr(tiktok, "contain_processes", lambda: None)
    monkeypatch.setattr(tiktok, "ensure_media", lambda *args: TOOLS)
    return TOOLS


def test_worker_downloads_and_reports_progress_and_the_completed_file(tmp_path, monkeypatch, prepared_tools):
    source = tmp_path / "source.mp4"

    def run(args, cancel, on_line):
        assert args[args.index("--use-extractors") + 1] == "TikTok,vm.tiktok"
        assert args[-1] == VIDEO_URL
        source.write_bytes(b"downloaded video")
        on_line('progress:{"downloaded_bytes": 5, "total_bytes": 10}')
        on_line("file:" + json.dumps(str(source)))

    monkeypatch.setattr(youtube, "run_tool", run)
    monkeypatch.setattr("item40.audio.probe_audio", lambda path: None)
    video = youtube.video_metadata(video_info(), "TikTok")
    events = Queue()
    tiktok.worker(tmp_path, VIDEO_URL, events, Event(), (video, Selection(stream=video.streams[0]), tmp_path))
    messages = list(events.queue)
    assert messages[-1] == ("downloaded", {"source": source, "readable_audio": True})
    assert any(kind == "progress" and values["progress"] == 0.5 for kind, values in messages)
    assert source.read_bytes() == b"downloaded video"


@pytest.mark.parametrize(("detail", "message"), [
    ("TikTok is requiring login for access", "требует входа"),
    ("This video is private", "недоступен"),
    ("HTTP Error 429", "повторите попытку позже"),
    ("Requested format is not available", "Обновите список"),
    ("No space left on device", "не хватает места"),
    ("Unsupported URL: https://www.tiktok.com/@user", "отдельный видеоролик"),
])
def test_worker_reports_actionable_errors(detail, message, tmp_path, monkeypatch, prepared_tools):
    def fail(*args):
        raise ToolError(detail)

    monkeypatch.setattr(tiktok, "inspect", fail)
    events = Queue()
    tiktok.worker(tmp_path, VIDEO_URL, events, Event())
    kind, values = events.get_nowait()
    assert kind == "failed" and message in values["error"]
    assert values["detail"] == detail


@pytest.mark.parametrize("cancelled", [False, True])
def test_invalid_or_cancelled_requests_do_not_prepare_components(tmp_path, monkeypatch, cancelled):
    def unexpected(*args):
        pytest.fail("Components must not be prepared")

    monkeypatch.setattr(tiktok, "ensure_media", unexpected)
    cancel = Event()
    if cancelled:
        cancel.set()
    events = Queue()
    tiktok.worker(tmp_path, "https://example.com", events, cancel)
    assert events.get_nowait()[0] == ("cancelled" if cancelled else "failed")
