from __future__ import annotations

import ctypes as ct
import os
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .downloads import check_cancel, download_file
from .i18n import tr


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    file: str
    url: str
    sha256: str
    files: tuple[str, ...]


PACKAGES = (
    Package("yt-dlp", "2026.11.21.232659", "yt-dlp.exe",
            "https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/download/2026.11.21.232659/yt-dlp.exe",
            "937b1024a937f0f2b50f6ef85f700383ecc0c96675aba3095801c5a1384cacd1", ("yt-dlp.exe",)),
    Package("deno", "2.9.8", "deno.zip",
            "https://github.com/denoland/deno/releases/download/v2.9.8/deno-x86_64-pc-windows-msvc.zip",
            "cba84b26e0df5ae7f74fc66b86a95b866872a86292ebd84fa1e959927edd93bf", ("deno.exe",)),
    Package("ffmpeg", "9.0.2", "ffmpeg.zip",
            "https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-full_build-shared.zip",
            "8d31e162f1616e37aab3fa2db991b97e1b8dbeb1c8465fd81a81be16ff91b328",
            ("ffmpeg.exe", "ffprobe.exe", "avcodec-63.dll", "avdevice-63.dll", "avfilter-12.dll",
             "avformat-63.dll", "avutil-61.dll", "swresample-7.dll", "swscale-10.dll")),
)


def ensure_tools(root: Path, emit, cancel, names=None) -> list[Path]:
    import requests

    folders = []
    for package in PACKAGES:
        if names is not None and package.name not in names:
            continue
        check_cancel(cancel)
        folder = root / "tools" / "youtube" / package.name / package.version
        ready = folder / ".ready"
        folders.append(folder)
        if ready.is_file() and all((folder / name).is_file() for name in package.files):
            continue
        ready.unlink(missing_ok=True)
        archive = folder / package.file
        stage = tr('Подготовка компонента · {0}', package.name)
        emit("progress", stage=stage, progress=None)
        try:
            download_file(package.url, archive, package.sha256, emit, cancel, label=stage)
        except requests.RequestException as error:
            raise RuntimeError(tr('Не удалось скачать {0}. Проверьте доступ к GitHub и повторите попытку.', package.name)) from error
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as zipped:
                for member in zipped.infolist():
                    check_cancel(cancel)
                    path = PurePosixPath(member.filename)
                    if member.is_dir() or not (path.name in package.files or
                                               path.name.lower().startswith(("license", "copying"))):
                        continue
                    with zipped.open(member) as source, (folder / path.name).open("wb") as output:
                        while block := source.read(1024 * 1024):
                            check_cancel(cancel)
                            output.write(block)
        if not all((folder / name).is_file() for name in package.files):
            raise RuntimeError(tr('Не удалось подготовить {0}: в архиве отсутствуют необходимые файлы.', package.name))
        ready.touch()
        if archive.suffix == ".zip":
            archive.unlink()
    return folders


# Public struct prefixes in the pinned FFmpeg 9 ABI.
class OutputFormat(ct.Structure):
    _fields_ = [(name, ct.c_char_p) for name in ("name", "long_name", "mime_type", "extensions")] + [
        (name, ct.c_int) for name in ("audio", "video", "subtitle", "flags")
    ]


class Codec(ct.Structure):
    _fields_ = [("name", ct.c_char_p), ("long_name", ct.c_char_p), ("type", ct.c_int),
                ("id", ct.c_int), ("capabilities", ct.c_int)]


@dataclass(frozen=True)
class Muxer:
    name: str
    title: str
    extension: str
    video: tuple[str, ...]
    audio: tuple[str, ...]


def ffmpeg_formats(folder: Path) -> list[Muxer]:
    # Skip formats that produce multiple files, require an output device, or emit diagnostic data.
    excluded = {"chromaprint", "crc", "fifo", "framecrc", "framehash", "framemd5", "hash",
                "image2", "image2pipe", "md5", "mkvtimestamp_v2", "mpjpeg", "null", "rtp",
                "rtp_mpegts", "sdl", "sdl2", "streamhash", "tee", "uncodedframecrc"}
    no_file, experimental, hardware = 0x1, 1 << 9, (1 << 18) | (1 << 19)
    with os.add_dll_directory(str(folder)):
        formats = ct.CDLL(str(folder / "avformat-63.dll"))
        codecs = ct.CDLL(str(folder / "avcodec-63.dll"))
        formats.av_muxer_iterate.argtypes = [ct.POINTER(ct.c_void_p)]
        formats.av_muxer_iterate.restype = ct.POINTER(OutputFormat)
        formats.avformat_query_codec.argtypes = [ct.POINTER(OutputFormat), ct.c_int, ct.c_int]
        formats.avformat_query_codec.restype = ct.c_int
        codecs.av_codec_iterate.argtypes = [ct.POINTER(ct.c_void_p)]
        codecs.av_codec_iterate.restype = ct.POINTER(Codec)
        codecs.av_codec_is_encoder.argtypes = [ct.POINTER(Codec)]
        codecs.av_codec_is_encoder.restype = ct.c_int

        encoders = defaultdict(list)
        state = ct.c_void_p()
        while ptr := codecs.av_codec_iterate(ct.byref(state)):
            codec = ptr.contents
            if codecs.av_codec_is_encoder(ptr) and not codec.capabilities & (experimental | hardware):
                encoders[codec.type].append((codec.id, codec.name.decode()))

        result = {}
        state = ct.c_void_p()
        while ptr := formats.av_muxer_iterate(ct.byref(state)):
            muxer = ptr.contents
            name = muxer.name.decode()
            if muxer.flags & no_file or name in excluded or name in result or not (muxer.audio or muxer.video):
                continue
            extension = (muxer.extensions or muxer.name).decode().split(",")[0]
            if not re.fullmatch(r"[a-zA-Z0-9_+-]+", extension):
                continue

            def compatible(media_type, default):
                if not default:
                    return ()
                supported = [(codec_id != default, encoder) for codec_id, encoder in encoders[media_type]
                             if codec_id == default or formats.avformat_query_codec(ptr, codec_id, 0) > 0]
                return tuple(encoder for _, encoder in sorted(supported))

            video, audio = compatible(0, muxer.video), compatible(1, muxer.audio)
            if video or audio:
                result[name] = Muxer(name, (muxer.long_name or muxer.name).decode("utf8", "replace"),
                                     extension, video, audio)
        return [result[name] for name in sorted(result)]
