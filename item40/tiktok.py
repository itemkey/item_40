from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib.parse import urlsplit

from .components import ensure_media
from .downloads import Cancelled, check_cancel
from .i18n import tr
from .youtube import ToolError, contain_processes, download, run_tool, video_metadata, ytdlp_args
from .youtube_tools import ffmpeg_formats

TOOL_ID = "tiktok.download"
EXTRACTORS = "TikTok,vm.tiktok"


def video_url(value: str) -> str:
    value = value.strip()
    if re.match(r"(?:(?:www|m|vm|vt)\.)?tiktok\.com/", value, re.IGNORECASE):
        value = "https://" + value
    try:
        if any(character.isspace() or ord(character) < 32 for character in value):
            raise ValueError
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or url.username is not None or url.port is not None:
            raise ValueError
        if url.hostname in {"tiktok.com", "www.tiktok.com", "m.tiktok.com"}:
            match = re.fullmatch(r"/@([\w.-]+)/video/([0-9]+)/?", url.path, re.ASCII)
            if match:
                return f"https://www.tiktok.com/@{match[1]}/video/{match[2]}"
            match = re.fullmatch(r"/(?:share/video|embed(?:/v2)?)/([0-9]+)/?", url.path)
            if match:
                return f"https://www.tiktok.com/@_/video/{match[1]}"
            match = re.fullmatch(r"/t/([\w-]+)/?", url.path, re.ASCII)
            if match:
                return f"https://www.tiktok.com/t/{match[1]}/"
        elif url.hostname in {"vm.tiktok.com", "vt.tiktok.com"}:
            if re.fullmatch(r"/[\w-]+/?", url.path, re.ASCII):
                return f"https://{url.hostname}/{url.path.strip('/')}/"
    except ValueError:
        pass
    raise ValueError(tr('Вставьте ссылку на отдельный ролик TikTok или короткую ссылку vm.tiktok.com / vt.tiktok.com.'))


def inspect(url, tools, emit, cancel):
    emit("progress", stage=tr('Получение списка форматов TikTok'), progress=None)
    result = run_tool([*ytdlp_args(tools, extractors=EXTRACTORS),
                       "--dump-single-json", "--skip-download", "--", url], cancel)
    info = json.loads(result)
    if info.get("_type", "video") != "video":
        raise ValueError(tr('По этой ссылке не найден отдельный видеоролик TikTok.'))
    video = video_metadata(info, "TikTok")
    if not any(stream.video for stream in video.streams):
        raise ValueError(tr('По этой ссылке не найден видеоролик. Фотопубликации TikTok не поддерживаются.'))
    return video, ffmpeg_formats(tools[2])


def worker(root, url, events, cancel, request=None):
    def emit(kind, **values):
        events.put((kind, values))

    try:
        check_cancel(cancel)
        url = video_url(url)
        contain_processes()
        tools = ensure_media(Path(root), emit, cancel, ("yt-dlp", "deno", "ffmpeg"))
        if request is None:
            video, muxers = inspect(url, tools, emit, cancel)
            check_cancel(cancel)
            emit("inspected", video=video, muxers=muxers)
        else:
            source, readable_audio = download(url, *request, tools, emit, cancel,
                                               service="TikTok", extractors=EXTRACTORS)
            check_cancel(cancel)
            emit("downloaded", source=source, readable_audio=readable_audio)
    except Cancelled:
        emit("cancelled")
    except ToolError as error:
        detail = str(error)
        lowered = detail.lower()
        if "no space left on device" in lowered or "not enough space" in lowered:
            message = tr('На диске не хватает места для скачивания или конвертации.')
        elif "requested format is not available" in lowered:
            message = tr('Выбранный поток недоступен. Обновите список форматов.')
        elif request is not None and any(value in lowered for value in
                                        ("invalid argument", "encoder", "could not write header")):
            message = tr('FFmpeg не смог записать этот формат с выбранными кодеками. Попробуйте другой вариант.')
        elif any(value in lowered for value in ("private", "unavailable", "not available", "not found",
                                                "login", "log in", "sign in", "http error 404")):
            message = tr('Ролик TikTok недоступен, удалён или требует входа в аккаунт.')
        elif "unsupported url" in lowered or "no suitable extractor" in lowered:
            message = tr('По этой ссылке не найден отдельный видеоролик TikTok.')
        else:
            message = tr('TikTok отклонил запрос или недоступен. Проверьте подключение и повторите попытку позже.')
        logging.warning("TikTok: %s", detail)
        emit("failed", error=message, detail=detail)
    except (ValueError, RuntimeError) as error:
        emit("failed", error=str(error))
    except OSError as error:
        emit("failed", error=tr('Не удалось запустить загрузку или записать файл. {0}', error))
    except Exception:
        logging.exception("TikTok worker failed")
        emit("failed", error=tr('Не удалось завершить загрузку. Повторите попытку.'))
