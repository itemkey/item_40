from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlsplit

import requests

from .downloads import Cancelled, check_cancel
from .i18n import tr

TOOL_ID = "telegram.emoji"
MAX_FILE_SIZE = 20 * 1024 * 1024
MAX_THUMBNAIL_SIZE = 1024 * 1024


@dataclass(frozen=True)
class Emoji:
    id: str
    position: int
    file_id: str
    kind: str
    symbol: str
    size: int | None
    thumbnail: str | None


@dataclass(frozen=True)
class EmojiPack:
    name: str
    title: str
    emojis: list[Emoji]


class TelegramError(RuntimeError):
    def __init__(self, message, *, auth=False):
        super().__init__(message)
        self.auth = auth


def pack_name(value: str) -> str:
    link = value.strip()
    if re.match(r"^(?:t\.me|telegram\.me|telegram\.dog)/", link, re.IGNORECASE):
        link = "https://" + link
    try:
        url = urlsplit(link)
        if url.username is not None or url.port is not None:
            raise ValueError
        path = url.path.strip("/").split("/")
        if url.scheme in {"http", "https"} and url.hostname in {"t.me", "telegram.me", "telegram.dog"}:
            name = path[1] if len(path) == 2 and path[0] == "addemoji" else ""
        elif url.scheme == "tg" and url.hostname == "addemoji" and not url.path.strip("/"):
            name = parse_qs(url.query).get("set", [""])[0]
        else:
            name = ""
        if not re.fullmatch(r"[a-zA-Z0-9_]{1,128}", name):
            raise ValueError
        return name
    except ValueError:
        raise ValueError(tr('Вставьте ссылку на эмодзи-пак вида t.me/addemoji/НазваниеПака.')) from None


def parse_pack(result: dict) -> EmojiPack:
    if result.get("sticker_type") != "custom_emoji":
        raise TelegramError(tr('Эта ссылка ведёт на другой тип набора. Выберите эмодзи-пак Telegram.'))
    name = result.get("name", "")
    if not re.fullmatch(r"[a-zA-Z0-9_]{1,128}", name):
        raise TelegramError(tr('Telegram вернул некорректное название пака.'))
    emojis = []
    for position, sticker in enumerate(result.get("stickers", []), 1):
        identity = sticker.get("custom_emoji_id", "")
        file_id = sticker.get("file_id")
        if not re.fullmatch(r"[0-9]{1,32}", identity) or not isinstance(file_id, str) or not file_id:
            raise TelegramError(tr('Telegram вернул неполные сведения об эмодзи. Загрузите пак ещё раз.'))
        kind = "tgs" if sticker.get("is_animated") else "webm" if sticker.get("is_video") else "webp"
        thumbnail = sticker.get("thumbnail") or {}
        emojis.append(Emoji(identity, position, file_id, kind, sticker.get("emoji") or "",
                            sticker.get("file_size"), thumbnail.get("file_id")))
    if not emojis:
        raise TelegramError(tr('В этом паке пока нет эмодзи.'))
    return EmojiPack(name, result.get("title") or name, emojis)


def file_extension(header: bytes, kind: str) -> str:
    if kind == "tgs" and header.startswith(b"\x1f\x8b"):
        return "tgs"
    if kind == "webm" and header.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    if kind == "webp":
        if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
            return "webp"
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            return "png"
    raise TelegramError(tr('Telegram вернул файл с неожиданным форматом. Повторите скачивание.'))


class TelegramAPI:
    def __init__(self, token: str, cancel, emit):
        if not re.fullmatch(r"[0-9]+:[a-zA-Z0-9_-]+", token):
            raise TelegramError(tr('Проверьте токен бота из @BotFather.'), auth=True)
        self.token = token
        self.cancel = cancel
        self.emit = emit
        self.session = requests.Session()

    def close(self):
        self.session.close()

    def wait_retry(self, response, attempt) -> bool:
        if attempt >= 2:
            return False
        seconds = 1 + attempt
        if response is not None and response.status_code == 429:
            try:
                seconds = max(1, int(response.json().get("parameters", {}).get("retry_after", 3)))
            except (ValueError, TypeError, AttributeError):
                seconds = 3
        elif response is not None and response.status_code < 500:
            return False
        self.emit("progress", stage=tr('Ожидание ответа Telegram · {0} с', seconds), progress=None)
        if self.cancel.wait(seconds):
            raise Cancelled()
        return True

    def call(self, method: str, **params):
        for attempt in range(3):
            check_cancel(self.cancel)
            try:
                with self.session.post(f"https://api.telegram.org/bot{self.token}/{method}",
                                       json=params, timeout=(10, 10), allow_redirects=False) as response:
                    if response.status_code == 429 or response.status_code >= 500:
                        if self.wait_retry(response, attempt):
                            continue
                        raise TelegramError(tr('Telegram временно ограничил запросы. Повторите попытку позже.'))
                    if response.status_code in {401, 404}:
                        raise TelegramError(tr('Токен бота недействителен. Подключите бота заново.'), auth=True)
                    if response.status_code != 200:
                        message = (tr('Эмодзи-пак не найден или недоступен. Проверьте ссылку.')
                                   if method == "getStickerSet" else tr('Telegram не смог предоставить этот файл.'))
                        raise TelegramError(message)
                    data = response.json()
                    if not isinstance(data, dict) or not data.get("ok") or "result" not in data:
                        raise TelegramError(tr('Telegram вернул неполный ответ. Повторите попытку.'))
                    check_cancel(self.cancel)
                    return data["result"]
            except requests.RequestException:
                if self.wait_retry(None, attempt):
                    continue
                raise TelegramError(tr('Нет ответа Telegram. Проверьте подключение к интернету.')) from None
            except (ValueError, TypeError):
                raise TelegramError(tr('Не удалось прочитать ответ Telegram. Повторите попытку.')) from None

    def fetch(self, file_id: str, destination: Path, *, limit=MAX_FILE_SIZE):
        info = self.call("getFile", file_id=file_id)
        path = info.get("file_path", "")
        parts = PurePosixPath(path).parts
        if not path or path.startswith("/") or ".." in parts or not re.fullmatch(r"[a-zA-Z0-9_./-]+", path):
            raise TelegramError(tr('Telegram не предоставил путь к файлу. Загрузите пак ещё раз.'))
        expected = info.get("file_size")
        if expected is not None and (not isinstance(expected, int) or expected < 1 or expected > limit):
            raise TelegramError(tr('Файл превышает допустимый размер скачивания.'))
        try:
            for attempt in range(3):
                check_cancel(self.cancel)
                try:
                    with self.session.get(f"https://api.telegram.org/file/bot{self.token}/{path}", stream=True,
                                          timeout=(10, 10), allow_redirects=False) as response:
                        if response.status_code == 429 or response.status_code >= 500:
                            if self.wait_retry(response, attempt):
                                continue
                        if response.status_code != 200:
                            raise TelegramError(tr('Не удалось получить файл Telegram. Повторите скачивание.'))
                        done = 0
                        with destination.open("wb") as output:
                            for block in response.iter_content(64 * 1024):
                                check_cancel(self.cancel)
                                done += len(block)
                                if done > limit:
                                    raise TelegramError(tr('Файл превышает допустимый размер скачивания.'))
                                output.write(block)
                        if not done or expected is not None and done != expected:
                            raise TelegramError(tr('Файл скачан не полностью. Повторите попытку.'))
                    check_cancel(self.cancel)
                    return
                except requests.RequestException:
                    if self.wait_retry(None, attempt):
                        continue
                    raise TelegramError(tr('Загрузка прервана. Проверьте подключение к интернету.')) from None
        except BaseException:
            destination.unlink(missing_ok=True)
            raise


def thumbnail_cache(root: Path, bot_id: str, pack: EmojiPack, emoji: Emoji) -> Path:
    return root / "telegram" / "thumbnails" / bot_id / pack.name / f"{emoji.id}.img"


def save_original(source: Path, emoji: Emoji) -> Path:
    with source.open("rb") as stream:
        extension = file_extension(stream.read(12), emoji.kind)
    stem = f"{emoji.position:03d}_{emoji.id}"
    index = 1
    while True:
        suffix = "" if index == 1 else f"_{index}"
        target = source.parent.parent / f"{stem}{suffix}.{extension}"
        try:
            if os.name == "nt":
                source.rename(target)
            else:
                os.link(source, target)
                source.unlink()
            return target
        except FileExistsError:
            index += 1


def worker(root, token, action, params, events, cancel):
    def emit(kind, **values):
        events.put((kind, values))

    api = None
    try:
        api = TelegramAPI(token, cancel, emit)
        if action == "connect":
            bot = api.call("getMe")
            if not bot.get("is_bot") or not bot.get("username"):
                raise TelegramError(tr('Telegram не подтвердил подключение бота.'), auth=True)
            emit("connected", username=bot["username"])
        elif action == "inspect":
            pack = parse_pack(api.call("getStickerSet", name=params["name"]))
            emit("pack", pack=pack)
            for emoji in pack.emojis:
                check_cancel(cancel)
                if not emoji.thumbnail:
                    continue
                path = thumbnail_cache(Path(root), token.partition(":")[0], pack, emoji)
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if not path.is_file():
                        temporary = path.with_suffix(".part")
                        api.fetch(emoji.thumbnail, temporary, limit=MAX_THUMBNAIL_SIZE)
                        temporary.replace(path)
                    emit("thumbnail", id=emoji.id, path=path)
                except TelegramError as error:
                    if error.auth:
                        raise
                    continue
                except OSError:
                    continue
            emit("completed")
        elif action == "download":
            emojis, folder = params["emojis"], Path(params["folder"])
            for index, emoji in enumerate(emojis):
                check_cancel(cancel)
                emit("progress", stage=tr('Скачивание эмодзи · {0} из {1}', index + 1, len(emojis)),
                     progress=index / len(emojis))
                temporary = folder / f"{emoji.id}.part"
                try:
                    api.fetch(emoji.file_id, temporary)
                    check_cancel(cancel)
                    result = save_original(temporary, emoji)
                    emit("saved", id=emoji.id, path=result)
                except TelegramError as error:
                    if error.auth:
                        raise
                    emit("file_failed", id=emoji.id, error=str(error))
                finally:
                    temporary.unlink(missing_ok=True)
            emit("completed")
    except Cancelled:
        emit("cancelled")
    except TelegramError as error:
        emit("failed", error=str(error), auth=error.auth)
    except OSError:
        emit("failed", error=tr('Не удалось записать файл. Проверьте папку и свободное место на диске.'))
    except Exception:
        # Requests exceptions and their URLs contain the bot token. Emit only fixed messages.
        emit("failed", error=tr('Не удалось завершить операцию Telegram. Повторите попытку.'))
    finally:
        if api:
            api.close()
