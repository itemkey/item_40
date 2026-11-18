import pytest

from item40.youtube import AUDIO_FORMATS, VIDEO_FORMATS, Selection, save_download, video_metadata, video_url


@pytest.mark.parametrize("link", [
    " https://www.youtube.com/watch?v=aqz-KE-bpKQ&list=123 ",
    "https://youtu.be/aqz-KE-bpKQ?si=abc",
    "https://m.youtube.com/shorts/aqz-KE-bpKQ",
    "https://www.youtube.com/live/aqz-KE-bpKQ",
])
def test_youtube_url_is_normalized_to_a_single_video(link):
    assert video_url(link) == "https://www.youtube.com/watch?v=aqz-KE-bpKQ"


@pytest.mark.parametrize("link", [
    "https://www.youtube.com/playlist?list=123",
    "https://youtube.com.example/watch?v=aqz-KE-bpKQ",
    "https://example@youtube.com/watch?v=aqz-KE-bpKQ",
    "--exec something",
])
def test_non_video_youtube_urls_are_rejected(link):
    with pytest.raises(ValueError):
        video_url(link)


def test_stream_and_transcode_selection():
    video = video_metadata({"title": "Ролик", "live_status": "was_live", "formats": [
        {"format_id": "sb", "ext": "mhtml", "vcodec": "none", "acodec": "none", "height": 30},
        {"format_id": "137", "ext": "mp4", "vcodec": "avc1", "height": 1080},
        {"format_id": "251-1", "ext": "webm", "acodec": "opus"},
        {"format_id": "proof", "ext": "mp4", "height": 2160, "vcodec": "avc1", "has_drm": True},
    ]})
    assert video.resolutions == [1080]
    assert video.has_audio
    assert Selection(stream=video.streams[0]).selector(video.has_audio) == "251-1"
    assert Selection(AUDIO_FORMATS["MP3"]).selector(video.has_audio) == "ba/b"
    assert Selection(VIDEO_FORMATS["MP4"], 1080).selector(video.has_audio) == "bv[height=1080]+ba/b[height=1080]"
    with pytest.raises(ValueError, match="трансляции"):
        video_metadata({"live_status": "is_live"})


def test_completed_download_is_renamed_without_overwriting_an_existing_file(tmp_path):
    work = tmp_path / ".item40-youtube-test"
    work.mkdir()
    original = tmp_path / "_CON.mp3"
    original.write_bytes(b"previous download")
    incoming = work / "output.mp3"
    incoming.write_bytes(b"next download")
    result = save_download(incoming, "CON")
    assert result == tmp_path / "_CON_2.mp3"
    assert result.read_bytes() == b"next download"
    assert original.read_bytes() == b"previous download"
