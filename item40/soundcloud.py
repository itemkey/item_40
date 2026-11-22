from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .components import ensure_media
from .converters import media_targets, publish_files
from .downloads import Cancelled, check_cancel
from .i18n import tr
from .youtube import Format, Selection, ToolError, download, run_tool, video_metadata, ytdlp_args

TOOL_ID = "soundcloud.download"


@dataclass(frozen=True)
class Track:
    id: str
    url: str
    title: str
    artist: str
    duration: float | None
    unavailable: bool = False
    preview: bool = False


def track_url(value):
    value = value.strip()
    if value.startswith(("soundcloud.com/", "on.soundcloud.com/", "snd.sc/")):
        value = "https://" + value
    try:
        url = urlsplit(value)
        if (url.scheme not in {"http", "https"} or url.username is not None or url.port is not None
                or url.hostname not in {"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com",
                                        "on.soundcloud.com", "snd.sc"} or not url.path.strip("/")):
            raise ValueError
        parts = url.path.strip("/").split("/")
        if url.hostname in {"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"}:
            if len(parts) < 2 or parts[1] in {"tracks", "likes", "reposts", "albums", "comments"}:
                raise ValueError
        return urlunsplit(("https", url.netloc, url.path, url.query, ""))
    except ValueError:
        raise ValueError(tr('Вставьте ссылку на трек, плейлист или альбом SoundCloud.')) from None


def collection(info):
    entries = info.get("entries") if info.get("_type") in {"playlist", "multi_video"} else [info]
    tracks = []
    for index, item in enumerate(entries or []):
        if item is None:
            tracks.append(Track(f"missing-{index}", "", tr('Недоступный трек'), "", None, True))
            continue
        url = item.get("webpage_url") or item.get("url") or ""
        if url.startswith("https://api.soundcloud.com/tracks/"):
            url = item.get("webpage_url") or url
        if not url.startswith(("https://soundcloud.com/", "https://www.soundcloud.com/", "https://api.soundcloud.com/")):
            url = ""
        formats = item.get("formats") or []
        preview = bool(formats) and all(re.search(r"preview|snippet", fmt.get("format_id", "")) for fmt in formats)
        tracks.append(Track(str(item.get("id") or index), url, item.get("title") or tr('Недоступный трек'),
                            item.get("uploader") or item.get("artist") or "", item.get("duration"),
                            not url or item.get("availability") in {"private", "needs_auth"}, preview))
    if not tracks:
        raise ValueError(tr('По этой ссылке не найдены доступные треки.'))
    return info.get("title") or "SoundCloud", tracks


def worker(root, action, params, events, cancel):
    def emit(kind, **values):
        events.put((kind, values))
    try:
        tools = ensure_media(root, emit, cancel, ("yt-dlp", "deno", "ffmpeg"))
        if action == "inspect":
            emit("progress", stage=tr('Получение списка треков SoundCloud'), progress=None)
            result = run_tool([*ytdlp_args(tools, playlist=True), "--ignore-errors",
                               "--dump-single-json", "--skip-download", "--", params["url"]], cancel)
            title, tracks = collection(json.loads(result))
            emit("inspected", title=title, tracks=tracks, targets=media_targets(tools[2], audio_only=True))
        else:
            for index, track in enumerate(params["tracks"]):
                check_cancel(cancel)
                work = Path(params["work"]) / str(index)
                work.mkdir()
                try:
                    emit("started", id=track.id)
                    info = json.loads(run_tool([*ytdlp_args(tools), "--dump-single-json", "--skip-download",
                                               "--", track.url], cancel))
                    formats = [fmt for fmt in info.get("formats", []) if not fmt.get("has_drm")]
                    full = [fmt for fmt in formats if not re.search(r"preview|snippet", fmt.get("format_id", ""))]
                    if not full and not params.get("allow_preview"):
                        raise ValueError(tr('Доступен только ознакомительный фрагмент. Разрешите скачивание фрагментов.'))
                    info["formats"] = full or formats
                    video = video_metadata(info, "SoundCloud")
                    target = params["target"]
                    if target is None:
                        selection = Selection(stream=video.streams[0])
                    else:
                        output = Format(target.parameter, target.extension, audio=params.get("audio_codec") or target.audio)
                        selection = Selection(format=output)
                    source, _ = download(track.url, video, selection, work, tools, emit, cancel,
                                         service="SoundCloud", metadata=True)
                    check_cancel(cancel)
                    result = publish_files([source], video.title + ".audio", params["output"])
                    emit("saved", id=track.id, result=result)
                except (ToolError, ValueError, OSError) as error:
                    message = str(error)[-1500:]
                    emit("file_failed", id=track.id, error=message)
                finally:
                    shutil.rmtree(work, ignore_errors=True)
        emit("completed")
    except Cancelled:
        emit("cancelled")
    except (ToolError, ValueError, RuntimeError, OSError) as error:
        emit("failed", error=str(error)[-2000:])
