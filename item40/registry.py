from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ToolDefinition:
    id: str
    title: str
    category: str
    description: str
    icon: str
    create_view: Callable


def builtin_tools():
    from .ui.audio_page import AudioPage

    return [ToolDefinition("audio.transcribe", "Аудио → текст", "Аудио",
                           "Распознавание аудио в текст.",
                           "audio", AudioPage)]
