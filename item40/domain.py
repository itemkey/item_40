from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .i18n import language, tr

AUDIO_EXTENSIONS = (".m4a", ".mp3", ".wav", ".flac", ".aac", ".ogg", ".opus", ".wma", ".aiff", ".aif",
                    ".amr", ".m4b", ".caf", ".mp4", ".webm", ".mkv", ".mov")
AUDIO_FILTER = tr('Аудио и видео (') + " ".join("*" + ext for ext in AUDIO_EXTENSIONS) + tr(');;Все файлы (*)')
MODEL_REPOS = {"small": "Systran/faster-whisper-small", "large-v3": "Systran/faster-whisper-large-v3"}
MODEL_LABELS = {"small": tr('Быстро · small'), "large-v3": tr('Точно · large-v3')}
STATUS_LABELS = {"queued": tr('В очереди'), "running": tr('Обработка'), "completed": tr('Готово'),
                 "cancelled": tr('Отменено'), "failed": tr('Ошибка'), "interrupted": tr('Прервано')}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class JobRequest:
    source: str
    model: str = "small"
    language: str | None = None
    device: str = "auto"
    tool_id: str = "audio.transcribe"
    id: str = field(default_factory=lambda: uuid4().hex)
    source_files: list[str] = field(default_factory=list)

    @property
    def files(self) -> list[str]:
        return self.source_files or [self.source]


def job_files(job: dict) -> list[str]:
    return json.loads(job["options"]).get("source_files") or [job["source"]]


def source_label(job: dict) -> str:
    files = job_files(job)
    first = Path(files[0]).name
    count = len(files)
    if language() == "en":
        return first if count == 1 else f"{count} files · {first}"
    ending = tr('файл') if count % 10 == 1 and count % 100 != 11 else (
        tr('файла') if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14) else tr('файлов'))
    return first if count == 1 else f"{count} {ending} · {first}"


def result_stem(job: dict) -> str:
    return Path(job["source"]).stem + ("_объединено" if len(job_files(job)) > 1 else "")


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class JobEvent:
    kind: str
    data: dict[str, Any] = field(default_factory=dict)


def format_transcript(segments: list[dict] | list[Segment]) -> str:
    """Paragraphs follow pauses; preserve the recognizer's words and punctuation."""
    paragraphs: list[str] = []
    current: list[str] = []
    last_end = 0.0
    last_source = None
    for item in segments:
        seg = asdict(item) if isinstance(item, Segment) else item
        text = seg["text"].strip()
        if not text:
            continue
        gap = seg["start"] - last_end
        previous = current[-1] if current else ""
        source = seg.get("source_index", 0)
        if current and (source != last_source or gap >= 1.5 or
                        (sum(map(len, current)) >= 650 and previous.endswith((".", "!", "?", "…")))):
            paragraphs.append(" ".join(current))
            current = []
        current.append(text)
        last_end = seg["end"]
        last_source = source
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)
