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
    from .telegram import TOOL_ID as TELEGRAM_TOOL_ID
    from .ui.audio_page import AudioPage
    from .ui.telegram_page import TelegramPage
    from .ui.youtube_page import YouTubePage
    from .youtube import TOOL_ID

    return [ToolDefinition("audio.transcribe", "Аудио → текст", "Аудио",
                           "Распознавание аудио в текст.",
                           "audio", AudioPage),
            ToolDefinition(TOOL_ID, "Скачать с YouTube", "YouTube",
                           "Сохранение видео и аудио по ссылке.",
                           "save", YouTubePage),
            ToolDefinition(TELEGRAM_TOOL_ID, "Скачать эмодзи", "Telegram",
                           "Выбор и скачивание оригинальных эмодзи из пака по ссылке.",
                           "save", TelegramPage)]
