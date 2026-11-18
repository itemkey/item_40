from __future__ import annotations

import ctypes as ct
import json
import logging
import os
import re
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .downloads import Cancelled, check_cancel
from .youtube_tools import ensure_tools, ffmpeg_formats

TOOL_ID = "youtube.download"
BAD_LINK = "Вставьте ссылку на отдельный ролик YouTube."


@dataclass(frozen=True)
class Format:
    muxer: str
    extension: str
    video: str = ""
    audio: str = ""


VIDEO_FORMATS = {
    "MP4": Format("mp4", "mp4", "libx264", "aac"),
    "MKV": Format("matroska", "mkv", "libx264", "aac"),
    "WebM": Format("webm", "webm", "libvpx-vp9", "libopus"),
    "MOV": Format("mov", "mov", "libx264", "aac"),
    "AVI": Format("avi", "avi", "mpeg4", "libmp3lame"),
}
AUDIO_FORMATS = {
    "MP3": Format("mp3", "mp3", audio="libmp3lame"),
    "M4A": Format("ipod", "m4a", audio="aac"),
    "WAV": Format("wav", "wav", audio="pcm_s16le"),
    "FLAC": Format("flac", "flac", audio="flac"),
    "OGG": Format("ogg", "ogg", audio="libvorbis"),
    "Opus": Format("opus", "opus", audio="libopus"),
    "AAC": Format("adts", "aac", audio="aac"),
    "AIFF": Format("aiff", "aiff", audio="pcm_s16be"),
}
CODEC_NAMES = {"libx264": "h264", "libvpx-vp9": "vp9", "libopus": "opus", "libvorbis": "vorbis", "libmp3lame": "mp3"}
STEREO_ENCODERS = {"libmp3lame", "libshine", "libtwolame", "wmav1", "wmav2"}


@dataclass(frozen=True)
class Stream:
    id: str
    extension: str
    video: str
    audio: str
    width: int | None
    height: int | None
    fps: float | None
    bitrate: float | None
    language: str | None


@dataclass(frozen=True)
class Video:
    title: str
    duration: float | None
    streams: list[Stream]

    @property
    def resolutions(self):
        return sorted({s.height for s in self.streams if s.video and s.height}, reverse=True)

    @property
    def has_audio(self):
        return any(s.audio for s in self.streams)


@dataclass(frozen=True)
class Selection:
    format: Format | None = None
    height: int | None = None
    stream: Stream | None = None

    def selector(self, has_audio: bool) -> str:
        if self.stream:
            return self.stream.id
        if not self.format.video:
            return "ba/b"
        limit = f"[height={self.height}]" if self.height else ""
        if self.format.audio and has_audio:
            return f"bv{limit}+ba/b{limit}"
        return f"bv{limit}/b{limit}"


def video_url(value: str) -> str:
    try:
        url = urlsplit(value.strip())
        if url.scheme not in {"http", "https"} or url.username is not None or url.port is not None:
            raise ValueError
    except ValueError:
        raise ValueError(BAD_LINK) from None
    path = url.path.strip("/").split("/")
    video_id = ""
    if url.hostname == "youtu.be" and len(path) == 1:
        video_id = path[0]
    elif url.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        if path == ["watch"]:
            video_id = parse_qs(url.query).get("v", [""])[0]
        elif len(path) == 2 and path[0] in {"shorts", "live", "embed", "v"}:
            video_id = path[1]
    if not re.fullmatch(r"[\w-]{11}", video_id, re.ASCII):
        raise ValueError(BAD_LINK)
    return f"https://www.youtube.com/watch?v={video_id}"


def video_metadata(info: dict) -> Video:
    if info.get("live_status") in {"is_live", "is_upcoming"}:
        raise ValueError("Скачивание будет доступно после завершения трансляции и публикации записи.")
    streams = []
    for item in reversed(info.get("formats", [])):
        stream_id, extension = item.get("format_id", ""), item.get("ext", "")
        if (item.get("has_drm") or not re.fullmatch(r"[\w.-]+", stream_id, re.ASCII) or
                not re.fullmatch(r"[a-zA-Z0-9]+", extension)):
            continue
        video, audio = (item.get(key) or "none" for key in ("vcodec", "acodec"))
        if video == audio == "none":
            continue
        streams.append(Stream(stream_id, extension, "" if video == "none" else video,
                              "" if audio == "none" else audio, item.get("width"), item.get("height"),
                              item.get("fps"), item.get("tbr") or item.get("abr"), item.get("language")))
    if not streams:
        raise ValueError("YouTube не предоставил доступных потоков для этого ролика.")
    return Video(info.get("title") or info.get("id") or "YouTube", info.get("duration"), streams)


def save_download(source: Path, title: str) -> Path:
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")[:120].rstrip(" .") or "YouTube"
    if re.fullmatch(r"CON|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³]", stem.split(".")[0], re.IGNORECASE):
        stem = "_" + stem
    index = 1
    while True:
        suffix = "" if index == 1 else f"_{index}"
        target = source.parent.parent / f"{stem}{suffix}{source.suffix}"
        try:
            if os.name == "nt":
                source.rename(target)
            else:
                os.link(source, target)
            return target
        except FileExistsError:
            index += 1


def contain_processes():
    if os.name != "nt":
        return
    from ctypes import wintypes as wt

    class BasicLimits(ct.Structure):
        _fields_ = [("per_process_time", ct.c_int64), ("per_job_time", ct.c_int64),
                    ("flags", wt.DWORD), ("minimum", ct.c_size_t), ("maximum", ct.c_size_t),
                    ("processes", wt.DWORD), ("affinity", ct.c_size_t), ("priority", wt.DWORD),
                    ("scheduling", wt.DWORD)]

    class ExtendedLimits(ct.Structure):
        _fields_ = [("basic", BasicLimits), ("counters", ct.c_uint64 * 6), ("memory", ct.c_size_t * 4)]

    kernel = ct.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ct.c_void_p, wt.LPCWSTR]
    kernel.CreateJobObjectW.restype = wt.HANDLE
    kernel.SetInformationJobObject.argtypes = [wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD]
    kernel.GetCurrentProcess.restype = wt.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    job = kernel.CreateJobObjectW(None, None)
    # The worker owns the non-inheritable handle. Windows closes it even on forced cancellation.
    if (not job or not kernel.SetInformationJobObject(job, 9, ct.byref(limits), ct.sizeof(limits))
            or not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess())):
        raise ct.WinError(ct.get_last_error())


class ToolError(RuntimeError):
    pass


def run_tool(args, cancel, on_line=None):
    check_cancel(cancel)
    environment = os.environ.copy()
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    bundle = getattr(sys, "_MEIPASS", None)
    if os.name == "nt" and bundle:
        kernel = ct.windll.kernel32
        kernel.SetDllDirectoryW(None)
        root = os.path.normcase(bundle)
        environment["PATH"] = os.pathsep.join(part for part in environment.get("PATH", "").split(os.pathsep)
                                              if not os.path.normcase(part).startswith(root))
    try:
        process = subprocess.Popen([str(arg) for arg in args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env=environment)
    finally:
        if os.name == "nt" and bundle:
            kernel.SetDllDirectoryW(bundle)
    errors = deque(maxlen=20)

    def collect_errors():
        for line in process.stderr:
            errors.append(line.strip()[:1500])

    with process:
        reader = threading.Thread(target=collect_errors, daemon=True)
        reader.start()
        result = []
        try:
            for line in process.stdout:
                check_cancel(cancel)
                if on_line:
                    on_line(line.strip())
                else:
                    result.append(line)
        finally:
            if sys.exc_info()[0] and process.poll() is None:
                process.kill()
            reader.join()
        check_cancel(cancel)
        if process.wait():
            raise ToolError("\n".join(errors))
    return "".join(result)


def ytdlp_args(tools):
    ytdlp, deno, ffmpeg = tools
    return [ytdlp / "yt-dlp.exe", "--ignore-config", "--no-plugin-dirs", "--no-playlist",
            "--encoding", "utf-8", "--socket-timeout", "20", "--abort-on-unavailable-fragments",
            "--no-js-runtimes", "--js-runtimes", f"deno:{deno / 'deno.exe'}",
            "--ffmpeg-location", ffmpeg]


def inspect(url, tools, emit, cancel):
    emit("progress", stage="Получение списка форматов YouTube", progress=None)
    result = run_tool([*ytdlp_args(tools), "--dump-single-json", "--skip-download", "--", url], cancel)
    return video_metadata(json.loads(result)), ffmpeg_formats(tools[2])


def download(url, video, selection, folder, tools, emit, cancel):
    emit("progress", stage="Скачивание с YouTube", progress=None)
    files = []

    def progress(line):
        if line.startswith("file:"):
            files.append(Path(json.loads(line.removeprefix("file:"))))
        elif line.startswith("progress:"):
            info = json.loads(line.removeprefix("progress:"))
            size = info.get("total_bytes") or info.get("total_bytes_estimate")
            done = info.get("downloaded_bytes") or 0
            fraction = min(done / size, 1) if isinstance(size, (float, int)) and size > 0 else None
            emit("progress", stage=f"Скачивание с YouTube · {done / 1e6:.1f} МБ", progress=fraction)

    options = ["--fixup", "never"] if selection.stream else ["--merge-output-format", "mkv"]
    run_tool([*ytdlp_args(tools), "-f", selection.selector(video.has_audio), *options,
              "--no-simulate", "--progress", "--newline", "--progress-delta", "0.2",
              "--progress-template", "download:progress:%(progress)j", "--print", "after_move:file:%(filepath)j",
              "-o", folder / "source.%(ext)s", "--", url], cancel, progress)
    if (len(files) != 1 or files[0].parent.resolve() != folder.resolve()
            or not files[0].is_file() or not files[0].stat().st_size):
        raise RuntimeError("Не удалось найти скачанный файл.")
    source = files[0]
    if selection.format:
        source = convert(source, selection.format, video.duration, tools[2], emit, cancel)

    from .audio import probe_audio

    try:
        probe_audio(str(source))
        readable_audio = True
    except ValueError:
        readable_audio = False
    return source, readable_audio


def convert(source, output, duration, ffmpeg, emit, cancel):
    emit("progress", stage="Конвертация файла", progress=None)
    info = run_tool([ffmpeg / "ffprobe.exe", "-v", "error", "-show_entries",
                     "stream=codec_type,codec_name,channels", "-of", "json", source], cancel)
    codecs = {}
    for stream in json.loads(info).get("streams", []):
        codecs.setdefault(stream["codec_type"], stream)
    target = source.parent / f"output.{output.extension}"
    args = [ffmpeg / "ffmpeg.exe", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-nostats", "-progress", "pipe:1", "-i", source]
    for media_type, encoder in (("video", output.video), ("audio", output.audio)):
        if not encoder:
            continue
        if media_type not in codecs:
            raise ValueError("В ролике отсутствует дорожка, необходимая для выбранного формата.")
        kind = media_type[0]
        codec = codecs[media_type]
        chosen = "copy" if CODEC_NAMES.get(encoder, encoder) == codec.get("codec_name") else encoder
        args.extend(("-map", f"0:{kind}:0", f"-c:{kind}", chosen))
        if chosen in STEREO_ENCODERS and codec.get("channels", 0) > 2:
            args.extend(("-ac", "2"))
        if chosen == "libx264":
            args.extend(("-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                         "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2"))
        elif chosen == "libvpx-vp9":
            args.extend(("-deadline", "good", "-cpu-used", "4", "-crf", "31", "-b:v", "0"))
        elif chosen == "libmp3lame":
            args.extend(("-q:a", "2"))

    def progress(line):
        if duration and line.startswith("out_time_us="):
            value = line.partition("=")[2]
            if value.isdigit():
                emit("progress", stage="Конвертация файла", progress=min(int(value) / 1e6 / duration, 1))

    run_tool([*args, "-f", output.muxer, target], cancel, progress)
    if not target.is_file() or not target.stat().st_size:
        raise RuntimeError("FFmpeg не создал итоговый файл.")
    return target


def worker(root, url, events, cancel, request=None):
    def emit(kind, **values):
        events.put((kind, values))

    try:
        contain_processes()
        tools = ensure_tools(Path(root), emit, cancel)
        if request is None:
            video, muxers = inspect(url, tools, emit, cancel)
            emit("inspected", video=video, muxers=muxers)
        else:
            source, readable_audio = download(url, *request, tools, emit, cancel)
            check_cancel(cancel)
            emit("downloaded", source=source, readable_audio=readable_audio)
    except Cancelled:
        emit("cancelled")
    except ToolError as error:
        detail = str(error)
        lowered = detail.lower()
        if "no space left on device" in lowered or "not enough space" in lowered:
            message = "На диске не хватает места для скачивания или конвертации."
        elif request is not None and ("invalid argument" in lowered or "encoder" in lowered or
                                    "could not write header" in lowered):
            message = "FFmpeg не смог записать этот формат с выбранными кодеками. Попробуйте другой вариант."
        elif "private video" in lowered or "video unavailable" in lowered or "not available in your country" in lowered:
            message = "Ролик недоступен или закрыт для просмотра."
        elif "requested format is not available" in lowered:
            message = "Выбранный поток недоступен. Обновите список форматов."
        elif "sign in" in lowered or "http error 403" in lowered or "http error 429" in lowered:
            message = "YouTube отклонил запрос. Попробуйте другой доступный ролик или повторите загрузку позже."
        else:
            message = "Не удалось обработать ссылку. Проверьте подключение и повторите попытку."
        logging.warning("YouTube: %s", detail)
        emit("failed", error=message, detail=detail)
    except (ValueError, RuntimeError) as error:
        emit("failed", error=str(error))
    except OSError as error:
        emit("failed", error=f"Не удалось запустить загрузку или записать файл. {error}")
    except Exception:
        logging.exception("YouTube worker failed")
        emit("failed", error="Не удалось завершить загрузку. Повторите попытку.")
