from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

AUDIO_EXTENSIONS = (".m4a", ".mp3", ".wav", ".flac", ".aac", ".ogg", ".opus", ".wma", ".aiff", ".aif",
                    ".amr", ".m4b", ".caf", ".mp4", ".webm", ".mkv", ".mov")
AUDIO_FILTER = "Аудио и видео (" + " ".join("*" + ext for ext in AUDIO_EXTENSIONS) + ");;Все файлы (*)"
MODEL_REPOS = {"small": "Systran/faster-whisper-small", "large-v3": "Systran/faster-whisper-large-v3"}
MODEL_LABELS = {"small": "Быстро · small", "large-v3": "Точно · large-v3"}
STATUS_LABELS = {"queued": "В очереди", "running": "Обработка", "completed": "Готово",
                 "cancelled": "Отменено", "failed": "Ошибка", "interrupted": "Прервано"}


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
    for item in segments:
        seg = asdict(item) if isinstance(item, Segment) else item
        text = seg["text"].strip()
        if not text:
            continue
        gap = seg["start"] - last_end
        previous = current[-1] if current else ""
        if current and (gap >= 1.5 or (sum(map(len, current)) >= 650 and previous.endswith((".", "!", "?", "…")))):
            paragraphs.append(" ".join(current))
            current = []
        current.append(text)
        last_end = seg["end"]
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)
