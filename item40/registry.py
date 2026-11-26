from dataclasses import dataclass
from typing import Callable

from .i18n import tr


@dataclass(frozen=True)
class ToolDefinition:
    id: str
    title: str
    category: str
    description: str
    icon: str
    create_view: Callable


def builtin_tools():
    from .converters import TOOL_ID as CONVERTER_TOOL_ID
    from .soundcloud import TOOL_ID as SOUNDCLOUD_TOOL_ID
    from .telegram import TOOL_ID as TELEGRAM_TOOL_ID
    from .tiktok import TOOL_ID as TIKTOK_TOOL_ID
    from .ui.audio_page import AudioPage
    from .ui.converter_page import ConverterPage
    from .ui.soundcloud_page import SoundCloudPage
    from .ui.telegram_page import TelegramPage
    from .ui.tiktok_page import TikTokPage
    from .ui.youtube_page import YouTubePage
    from .youtube import TOOL_ID

    return [ToolDefinition("audio.transcribe", tr('Аудио → текст'), tr('Аудио'),
                           tr('Распознавание аудио в текст.'),
                           "audio", AudioPage),
            ToolDefinition(TOOL_ID, tr('Скачать с YouTube'), "YouTube",
                           tr('Сохранение видео и аудио по ссылке.'),
                           "save", YouTubePage),
            ToolDefinition(TIKTOK_TOOL_ID, tr('Скачать с TikTok'), "TikTok",
                           tr('Сохранение видео и аудио по обычной или короткой ссылке TikTok.'),
                           "save", TikTokPage),
            ToolDefinition(TELEGRAM_TOOL_ID, tr('Скачать эмодзи и стикеры'), "Telegram",
                           tr('Выбор и скачивание оригинальных эмодзи и стикеров из набора по ссылке.'),
                           "save", TelegramPage),
            ToolDefinition(CONVERTER_TOOL_ID, tr('Конвертеры файлов'), tr('Конвертеры'),
                           tr('Аудио, видео, изображения, документы, PDF, книги, архивы и субтитры.'),
                           "refresh", ConverterPage),
            ToolDefinition(SOUNDCLOUD_TOOL_ID, tr('Скачать с SoundCloud'), "SoundCloud",
                           tr('Треки и выбранные песни из плейлистов и альбомов.'), "save", SoundCloudPage)]
