from __future__ import annotations

import json
import os
import re
import shutil
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from .components import ensure_component, ensure_media
from .downloads import Cancelled, check_cancel
from .i18n import tr
from .youtube import AUDIO_FORMATS, VIDEO_FORMATS, Format, ToolError, convert, run_tool
from .youtube_tools import ffmpeg_formats

TOOL_ID = "files.convert"
GROUPS = {
    "image": set("png jpg jpeg webp tiff tif bmp ico avif heic heif jp2 jxl exr hdr psd svg dds tga pcx ppm pgm pbm xpm 3fr arw cr2 cr3 dng nef orf raf rw2 j2k jpf pnm pam rgb rgba dib cur".split()),
    "animation": {"gif", "apng", "tgs", "lottie"},
    "document": set("doc docx docm dot dotx dotm odt ott fodt sxw stw rtf txt html htm md markdown rst tex textile org docbook wpd wps abw hwp pages".split()),
    "spreadsheet": set("xls xlsx xlsm xlsb xlt xltx ods ots fods sxc stc numbers csv tsv dbf dif slk wk1 wks 123".split()),
    "presentation": set("ppt pptx pptm pps ppsx odp otp fodp sxi sti key pot potx".split()),
    "ebook": set("epub kepub fb2 mobi azw azw3 lit lrf pdb prc snb tcr htmlz txtz rb".split()),
    "archive": set("zip 7z rar tar gz bz2 xz tgz tbz2 txz cab iso arj lzh z cpio rpm deb".split()),
    "subtitle": set("srt ass ssa vtt sub mpl tmp sami smi ttml".split()),
}
GROUP_TITLES = {"media": tr('Аудио и видео'), "image": tr('Изображения'), "animation": tr('Анимации и эмодзи'),
                "document": tr('Документы'), "spreadsheet": tr('Таблицы'), "presentation": tr('Презентации'),
                "ebook": tr('Электронные книги'), "archive": tr('Архивы'), "subtitle": tr('Субтитры'), "pdf": tr('PDF и OCR')}
OFFICE_OUTPUTS = {
    "document": {"docx": "Office Open XML Text", "doc": "MS Word 97", "odt": "writer8", "rtf": "Rich Text Format",
                 "txt": "Text (encoded)", "html": "HTML (StarWriter)", "pdf": "writer_pdf_Export", "epub": "EPUB"},
    "spreadsheet": {"xlsx": "Calc Office Open XML", "xls": "MS Excel 97", "ods": "calc8",
                    "csv": "Text - txt - csv (StarCalc)", "tsv": "Text - txt - csv (StarCalc)",
                    "html": "HTML (StarCalc)", "pdf": "calc_pdf_Export", "dbf": "dBase", "dif": "DIF"},
    "presentation": {"pptx": "Impress MS PowerPoint 2007 XML", "ppt": "MS PowerPoint 97", "odp": "impress8",
                     "pdf": "impress_pdf_Export", "html": "impress_html_Export"},
}
PANDOC_INPUT = {"md": "markdown", "markdown": "markdown", "rst": "rst", "tex": "latex", "textile": "textile",
                "org": "org", "html": "html", "htm": "html", "docx": "docx", "odt": "odt", "rtf": "rtf"}
PANDOC_EXTENSIONS = {"plain": "txt", "markdown": "md", "gfm": "md", "commonmark": "md", "latex": "tex",
                     "html5": "html", "html": "html", "epub3": "epub", "epub2": "epub",
                     "docbook5": "xml", "docbook4": "xml", "jats_archiving": "xml", "tei": "xml"}


@dataclass(frozen=True)
class Target:
    id: str
    title: str
    extension: str
    engine: str
    parameter: str = ""
    video: str = ""
    audio: str = ""
    video_choices: tuple[str, ...] = ()
    audio_choices: tuple[str, ...] = ()


def category(path):
    path = Path(path)
    suffix = path.suffix.lower().lstrip(".")
    if suffix == "pdf":
        return "pdf"
    if suffix == "json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and all(key in data for key in ("layers", "fr", "w", "h")):
                return "animation"
            if isinstance(data, dict) and isinstance(data.get("events"), list) and "styles" in data:
                return "subtitle"
        except (ValueError, OSError):
            pass
        return "document"
    if suffix == "txt":
        try:
            with path.open(encoding="utf-8-sig") as stream:
                first_line = stream.readline(500)
            if re.match(r"\d{1,2}:\d{2}:\d{2}[:=]", first_line):
                return "subtitle"
        except (OSError, UnicodeError):
            pass
    for name, extensions in GROUPS.items():
        if suffix in extensions:
            return name
    return "media"


def media_targets(folder, *, audio_only=False):
    presets = {**({} if audio_only else VIDEO_FORMATS), **AUDIO_FORMATS}
    result = [Target(f"media:{name.lower()}", name, fmt.extension, "ffmpeg", fmt.muxer, fmt.video, fmt.audio)
              for name, fmt in presets.items()]
    for muxer in ffmpeg_formats(folder):
        video = () if audio_only else muxer.video
        if not video and not muxer.audio:
            continue
        extension = ({"matroska": "mka", "asf": "wma", "ipod": "m4a"}.get(muxer.name, muxer.extension)
                     if audio_only else muxer.extension)
        result.append(Target(f"ffmpeg:{muxer.name}", f"{muxer.name} · {muxer.title}", extension, "ffmpeg",
                             muxer.name, video[0] if video else "", muxer.audio[0] if muxer.audio else "",
                             video, muxer.audio))
    return result


def targets_for(path, root, emit, cancel):
    group = category(path)
    if group == "media":
        folder = ensure_media(root, emit, cancel)[0]
        info = json.loads(run_tool([folder / "ffprobe.exe", "-v", "error", "-show_streams", "-of", "json", path], cancel))
        types = {stream["codec_type"] for stream in info.get("streams", [])}
        if not types.intersection({"audio", "video"}):
            raise ValueError(tr('Файл не содержит поддерживаемых аудио- или видеодорожек.'))
        result = media_targets(folder, audio_only="video" not in types)
        if "audio" not in types:
            result = [target for target in result if target.video]
        return group, result
    if group in {"image", "animation"}:
        magick = ensure_component("imagemagick", root, emit, cancel)
        formats = run_tool([magick, "-list", "format"], cancel)
        result = []
        for line in formats.splitlines():
            match = re.match(r"\s*([A-Z0-9]+)\*?\s+([r-]w[+-])\s+(.+)", line)
            if not match or match[1] in {"AI", "HTML", "HTM", "JSON", "INFO", "TXT", "VID", "PDF", "PS", "PS2", "PS3", "EPS", "EPS2", "EPS3", "SVG", "SVGZ", "MVG", "MSL", "XPS", "EPDF", "EPI", "EPSF", "EPSI", "EPT", "EPT2", "EPT3", "FLV", "MPG", "MPEG", "MPEG2", "M2V", "M4V", "WMV"}:
                continue
            name = match[1].lower()
            if re.fullmatch(r"[a-z0-9]{2,8}", name):
                result.append(Target(f"image:{name}", match[1], "jpg" if name == "jpeg" else name, "image", name))
        result.insert(0, Target("image:pdf", "PDF", "pdf", "image_pdf"))
        result.extend(Target(f"ocr:{ext}", f"OCR → {ext.upper()}", ext, "ocr") for ext in ("txt", "docx"))
        if group == "animation":
            for name in ("webm", "mp4"):
                fmt = VIDEO_FORMATS["WebM" if name == "webm" else "MP4"]
                result.append(Target(f"animation:{name}", name.upper(), name, "animation", fmt.muxer, fmt.video))
        return group, sorted({target.id: target for target in result}.values(), key=lambda t: t.title)
    if group == "pdf":
        return group, [Target(f"pdf:{ext}", ext.upper(), ext, "pdf") for ext in ("png", "jpg", "tiff", "txt", "docx")]
    if group in OFFICE_OUTPUTS:
        result = [Target(f"office:{ext}", ext.upper(), ext, "office", filter_name)
                  for ext, filter_name in OFFICE_OUTPUTS[group].items()]
        if group == "presentation":
            result.extend(Target(f"slides:{ext}", ext.upper(), ext, "slides") for ext in ("png", "jpg"))
        if group == "document" and Path(path).suffix.lower().lstrip(".") in PANDOC_INPUT:
            pandoc = ensure_component("pandoc", root, emit, cancel)
            formats = run_tool([pandoc, "--list-output-formats"], cancel).splitlines()
            for name in formats:
                if re.fullmatch(r"[a-z0-9_-]+", name) and name not in {"chunkedhtml", "revealjs", "s5", "slideous", "slidy", "dzslides"}:
                    extension = PANDOC_EXTENSIONS.get(name, name)
                    result.append(Target(f"pandoc:{name}", f"{name} · Pandoc", extension, "pandoc", name))
        return group, result
    if group == "ebook":
        calibre = ensure_component("calibre", root, emit, cancel)
        command = "from calibre.customize.ui import available_output_formats; print(' '.join(sorted(available_output_formats())))"
        formats = run_tool([calibre.parent / "calibre-debug.exe", "-c", command], cancel).split()
        return group, [Target(f"ebook:{ext}", ext.upper(), ext, "ebook") for ext in formats if re.fullmatch(r"[a-z0-9]+", ext)]
    if group == "archive":
        return group, [Target(f"archive:{ext}", ext.upper(), ext, "archive") for ext in ("zip", "7z", "tar", "tar.gz", "tar.bz2", "tar.xz")]
    if group == "subtitle":
        from pysubs2.formats import FILE_EXTENSION_TO_FORMAT_IDENTIFIER

        formats = {key.lstrip("."): value for key, value in FILE_EXTENSION_TO_FORMAT_IDENTIFIER.items()}
        formats.update(mpl="mpl2", tmp="tmp")
        return group, [Target(f"subtitle:{ext}", ext.upper(), ext, "subtitle", identifier)
                       for ext, identifier in sorted(formats.items())]
    raise ValueError(tr('Для этого файла не найдены доступные преобразования.'))


def office_convert(source, target, work, root, emit, cancel):
    soffice = ensure_component("libreoffice", root, emit, cancel)
    profile = work / "office-profile"
    parameter = f"{target.extension}:{target.parameter}"
    if target.extension in {"csv", "tsv"}:
        delimiter = "44" if target.extension == "csv" else "9"
        parameter += f":{delimiter},34,76,1,,0,false,true,false,false,false,-1"
    if target.extension == "html" and category(source) == "document":
        parameter += ":EmbedImages"
    run_tool([soffice, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore", "--nodefault",
              "--convert-to", parameter, "--outdir", work, source], cancel)
    files = [path for path in work.iterdir() if path.is_file() and path.suffix.lower() == f".{target.extension}"]
    if not files:
        raise RuntimeError(tr('LibreOffice не создал результат. Проверьте формат исходного файла.'))
    return files


def text_document(text, target, output):
    if target == "txt":
        output.write_text(text, encoding="utf-8")
    else:
        from docx import Document

        document = Document()
        for index, page in enumerate(text.split("\f")):
            if index:
                document.add_page_break()
            for line in page.splitlines():
                document.add_paragraph(line)
        document.save(output)


def recognize_image(image, work, root, emit, cancel, options):
    tesseract = ensure_component("tesseract", root, emit, cancel)
    image_path = work / "ocr-input.png"
    image.convert("RGB").save(image_path)
    languages = options.get("ocr_language", "rus+eng")
    if languages not in {"rus", "eng", "rus+eng"}:
        raise ValueError(tr('Выберите русский или английский язык OCR.'))
    return run_tool([tesseract, image_path, "stdout", "--tessdata-dir", tesseract.parent / "tessdata",
                     "-l", languages, "--psm", "3"], cancel)


def pdf_convert(source, target, work, root, emit, cancel, options):
    import pypdfium2 as pdfium

    output = work / f"output.{target.extension}"
    text_pages = []
    files = []
    with closing(pdfium.PdfDocument(str(source))) as pdf:
        for index in range(len(pdf)):
            check_cancel(cancel)
            emit("progress", stage=tr('Обработка страниц · {0} из {1}', index + 1, len(pdf)), progress=index / len(pdf))
            with closing(pdf[index]) as page:
                if target.extension in {"txt", "docx"}:
                    with closing(page.get_textpage()) as text_page:
                        text = text_page.get_text_range()
                    if not text.strip() and options.get("ocr", True):
                        with closing(page.render(scale=300 / 72)) as bitmap:
                            text = recognize_image(bitmap.to_pil(), work, root, emit, cancel, options)
                    text_pages.append(text)
                else:
                    with closing(page.render(scale=options.get("dpi", 150) / 72)) as bitmap:
                        path = work / f"page_{index + 1:03d}.{target.extension}"
                        bitmap.to_pil().convert("RGB").save(path)
                        files.append(path)
    if target.extension in {"txt", "docx"}:
        text_document("\f".join(text_pages), target.extension, output)
        return [output]
    return files


def animation_frames(source, work, cancel):
    from rlottie_python import LottieAnimation

    if source.suffix.lower() == ".lottie":
        import zipfile

        with zipfile.ZipFile(source) as archive:
            name = next(name for name in archive.namelist() if name.startswith("animations/") and name.endswith(".json"))
            animation = LottieAnimation.from_data(archive.read(name).decode("utf-8"))
    else:
        animation = (LottieAnimation.from_tgs(str(source)) if source.suffix.lower() == ".tgs"
                     else LottieAnimation.from_file(str(source)))
    folder = work / "frames"
    folder.mkdir()
    with animation:
        count = animation.lottie_animation_get_totalframe()
        fps = animation.lottie_animation_get_framerate()
        for index in range(count):
            check_cancel(cancel)
            animation.render_pillow_frame(frame_num=index).save(folder / f"{index:06d}.png")
    return folder, fps


def image_convert(source, target, work, root, emit, cancel, options):
    from PIL import Image

    if target.engine == "ocr":
        magick = ensure_component("imagemagick", root, emit, cancel)
        raster = work / "ocr-source.png"
        run_tool([magick, f"{source}[0]", raster], cancel)
        with Image.open(raster) as image:
            text = recognize_image(image, work, root, emit, cancel, options)
        output = work / f"output.{target.extension}"
        text_document(text, target.extension, output)
        return [output]
    magick = ensure_component("imagemagick", root, emit, cancel)
    frames = None
    animated_lottie = source.suffix.lower() in {".tgs", ".json", ".lottie"}
    if animated_lottie:
        frames, fps = animation_frames(source, work, cancel)
        image_source = str(frames / "*.png")
    else:
        image_source, fps = str(source), options.get("fps") or 30
    if target.engine == "animation" or target.extension == "apng":
        ffmpeg = ensure_media(root, emit, cancel)[0]
        output = work / f"output.{target.extension}"
        inputs = ["-framerate", str(fps), "-i", frames / "%06d.png"] if frames else ["-i", source]
        encoder = "apng" if target.extension == "apng" else target.video
        codec = ["-c:v", encoder, "-an"]
        if target.video == "libx264":
            codec += ["-pix_fmt", "yuv420p", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2"]
        elif encoder == "libvpx-vp9":
            codec += ["-pix_fmt", "yuva420p", "-auto-alt-ref", "0"]
        run_tool([ffmpeg / "ffmpeg.exe", "-hide_banner", "-loglevel", "error", "-nostdin", *inputs, *codec, output], cancel)
        return [output]
    if target.engine == "image_pdf":
        # Render through ImageMagick to handle vector and uncommon input formats, then create PDF in Pillow.
        raster = work / "page.png"
        run_tool([magick, f"{image_source}[0]" if not frames else frames / "000000.png",
                  "-background", options.get("background", "white"), "-alpha", "remove", "-alpha", "off", raster], cancel)
        output = work / "output.pdf"
        with Image.open(raster) as image:
            image.convert("RGB").save(output, "PDF", resolution=150)
        return [output]
    animated_output = target.extension in {"gif", "webp", "apng", "tiff", "tif", "miff"}
    inputs = ["-delay", f"1x{round(fps)}", image_source] if frames and animated_output else [image_source]
    if not animated_output:
        inputs = [frames / f"{options.get('frame', 0):06d}.png" if frames else f"{source}[{options.get('frame', 0)}]"]
    output = work / f"output.{target.extension}"
    args = [magick, *inputs]
    if target.extension == "ico":
        args += ["-resize", "256x256>"]
    if options.get("width"):
        args += ["-resize", f"{options['width']}x"]
    if target.extension in {"jpg", "jpeg", "bmp"}:
        args += ["-background", options.get("background", "white"), "-alpha", "remove", "-alpha", "off"]
    args += ["-quality", str(options.get("quality", 90))]
    if animated_output:
        args += ["-coalesce", "-loop", "0"]
    dependency = ensure_media(root, emit, cancel)[0] if source.suffix.lower() == ".apng" else None
    run_tool([*args, output], cancel, extra_path=dependency)
    return [path for path in work.glob(f"output*.{target.extension}") if path.is_file()]


def validate_archive_listing(listing):
    for line in listing.splitlines():
        if line.startswith("Path = "):
            name = line[7:]
            path = PureWindowsPath(name)
            if path.is_absolute() or path.drive or ".." in path.parts or ":" in name:
                raise ValueError(tr('Архив содержит путь за пределами рабочей папки.'))
        if line.startswith(("Symbolic Link =", "Hard Link =", "Reparse Tag =")) or re.match(r"Attributes = .*\bl[rwx-]{9}", line):
            raise ValueError(tr('Архив содержит ссылки. Выберите архив с обычными файлами.'))


def archive_convert(source, target, work, root, emit, cancel):
    executable = ensure_component("7zip", root, emit, cancel)
    listing = run_tool([executable, "l", "-slt", "-ba", "-sccUTF-8", source], cancel)
    validate_archive_listing(listing)
    extracted = work / "contents"
    extracted.mkdir()
    run_tool([executable, "x", "-y", f"-o{extracted}", source], cancel)
    contents = list(extracted.iterdir())
    if len(contents) == 1 and contents[0].suffix.lower() == ".tar" and source.suffix.lower() in {"gz", ".gz", ".bz2", ".xz", ".tgz", ".txz", ".tbz2"}:
        nested = work / "uncompressed"
        nested.mkdir()
        listing = run_tool([executable, "l", "-slt", "-ba", "-sccUTF-8", contents[0]], cancel)
        validate_archive_listing(listing)
        run_tool([executable, "x", "-y", f"-o{nested}", contents[0]], cancel)
        extracted = nested
    for item in extracted.rglob("*"):
        if item.is_symlink() or not item.resolve().is_relative_to(extracted.resolve()):
            raise ValueError(tr('Архив содержит ссылку за пределы рабочей папки.'))
    intermediate = work / ("output.tar" if target.extension.startswith("tar.") else f"output.{target.extension}")
    kind = "tar" if target.extension.startswith("tar.") else target.extension
    run_tool([executable, "a", f"-t{kind}", intermediate, "."], cancel, cwd=extracted)
    if target.extension.startswith("tar."):
        output = work / f"output.{target.extension}"
        compressor = {"gz": "gzip", "bz2": "bzip2", "xz": "xz"}[target.extension.rsplit(".", 1)[1]]
        run_tool([executable, "a", f"-t{compressor}", output, intermediate], cancel)
        return [output]
    return [intermediate]


def convert_file(source, target, work, root, emit, cancel, options):
    source, work = Path(source), Path(work)
    work.mkdir(parents=True, exist_ok=True)
    check_cancel(cancel)
    if target.engine == "ffmpeg":
        folder = ensure_media(root, emit, cancel)[0]
        info = json.loads(run_tool([folder / "ffprobe.exe", "-v", "error", "-show_format", "-show_streams", "-of", "json", source], cancel))
        present = {stream["codec_type"] for stream in info["streams"]}
        video = options.get("video_codec", target.video)
        audio = options.get("audio_codec", target.audio) if "audio" in present else ""
        # The shared media converter places output beside its input. Keep that input inside this operation's workspace.
        staged = work / ("input" + source.suffix)
        try:
            os.link(source, staged)
        except OSError:
            shutil.copy2(source, staged)
        output = Format(target.parameter, target.extension, video, audio)
        duration = float(info.get("format", {}).get("duration") or 0)
        return [convert(staged, output, duration, folder, emit, cancel, options=options)]
    if target.engine in {"image", "image_pdf", "animation", "ocr"}:
        return image_convert(source, target, work, root, emit, cancel, options)
    if target.engine == "pdf":
        return pdf_convert(source, target, work, root, emit, cancel, options)
    if target.engine in {"office", "slides"}:
        if target.engine == "slides":
            pdf = Target("office:pdf", "PDF", "pdf", "office", "impress_pdf_Export")
            pdf_path = office_convert(source, pdf, work, root, emit, cancel)[0]
            return pdf_convert(pdf_path, target, work, root, emit, cancel, options)
        return office_convert(source, target, work, root, emit, cancel)
    output = work / f"output.{target.extension}"
    if target.engine == "pandoc":
        executable = ensure_component("pandoc", root, emit, cancel)
        input_format = PANDOC_INPUT.get(source.suffix.lstrip(".").lower(), "markdown")
        run_tool([executable, "-f", input_format, "-t", target.parameter, "--standalone", source, "-o", output], cancel)
    elif target.engine == "ebook":
        executable = ensure_component("calibre", root, emit, cancel)
        run_tool([executable, source, output], cancel)
    elif target.engine == "archive":
        return archive_convert(source, target, work, root, emit, cancel)
    elif target.engine == "subtitle":
        import pysubs2

        try:
            subtitles = pysubs2.load(str(source), encoding="utf-8-sig", fps=options.get("fps") or 25)
        except UnicodeDecodeError:
            subtitles = pysubs2.load(str(source), encoding="cp1251", fps=options.get("fps") or 25)
        subtitles.save(str(output), format_=target.parameter or None, fps=options.get("fps") or 25)
    else:
        raise ValueError(tr('Неизвестное преобразование.'))
    if not output.exists():
        raise RuntimeError(tr('Компонент не создал выходной файл.'))
    return [output]


def publish_files(files, source, folder):
    from .youtube import save_download

    if not files or any(not path.exists() or path.is_file() and not path.stat().st_size for path in files):
        raise ValueError(tr('Преобразование не создало готовых файлов.'))
    folder = Path(folder)
    if len(files) > 1 or files[0].is_dir():
        staged = files[0]
        if len(files) > 1:
            staged = files[0].parent / "result"
            staged.mkdir()
            for path in files:
                path.rename(staged / path.name)
        index = 1
        while True:
            result = folder / (Path(source).stem + (f"_{index}" if index > 1 else ""))
            try:
                staged.rename(result)
                return result
            except FileExistsError:
                index += 1
    return save_download(files[0], Path(source).stem, "".join(files[0].suffixes), directory=folder)


def inspect_worker(root, files, events, cancel):
    def emit(kind, **values):
        events.put((kind, values))
    try:
        for index, path in enumerate(files):
            check_cancel(cancel)
            try:
                group, targets = targets_for(path, root, emit, cancel)
                emit("inspected", path=path, group=group, targets=targets)
            except (ValueError, RuntimeError, OSError) as error:
                emit("file_failed", path=path, error=str(error))
        emit("completed")
    except Cancelled:
        emit("cancelled")


def convert_worker(root, requests, work, output, events, cancel):
    def emit(kind, **values):
        events.put((kind, values))
    try:
        for index, (source, target, options) in enumerate(requests):
            check_cancel(cancel)
            emit("started", path=source)
            task_work = Path(work) / str(index)
            try:
                files = convert_file(source, target, task_work, root, emit, cancel, options)
                check_cancel(cancel)
                result = publish_files(files, source, output)
                emit("saved", path=source, result=result)
            except (ValueError, RuntimeError, OSError) as error:
                detail = str(error)
                emit("file_failed", path=source, error=detail[-2000:])
            finally:
                shutil.rmtree(task_work, ignore_errors=True)
        emit("completed")
    except Cancelled:
        emit("cancelled")
    except ToolError as error:
        emit("failed", error=str(error))
