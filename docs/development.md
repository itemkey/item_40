# Разработка

Python 3.12 и uv. Зависимости зафиксированы в `uv.lock`.

```powershell
uv sync --frozen --extra dev
uv run python run.py
uv run ruff check item40 tests run.py
uv run pytest
```

Проверка распознавания настоящего файла:

```powershell
uv run python scripts/transcribe_smoke.py --device cpu recording.m4a
uv run python scripts/transcribe_smoke.py --device cuda --model large-v3 recording.m4a
```

Параметр окружения `ITEM40_DATA_DIR` задаёт каталог служебных данных для тестирования. Поддерживается старый параметр `MASTERSKAYA_DATA_DIR`. При обновлении с 0.1.0 используются прежние каталог данных и база SQLite; модели не перемещаются и не скачиваются повторно.

Новые установки используют `%LOCALAPPDATA%\item-40`. История и настройки хранятся в SQLite. Каталог TXT задаётся отдельно в настройках. Смена каталога применяется к новым результатам; уже созданные файлы остаются на прежнем месте.

## Сборка

```powershell
uv run python packaging/create_icon.py
uv run pyinstaller --noconfirm --clean packaging/item40.spec
& 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' packaging/installer.iss
```

Результат: `dist/item-40` и установщик в `dist`. Для сборки установщика подходит Inno Setup 6 или 7.

## Выпуск

Обновите версии в `pyproject.toml`, `item40/__init__.py`, `packaging/version.txt`, `packaging/installer.iss` и текст `RELEASE_NOTES.md`. Выполните `uv lock`.

GitHub Actions запускает проверки и собирает установщик и ZIP. После отправки новой версии в `main` создаётся релиз `v<версия>` с SHA256SUMS.txt. Существующие релизы не перезаписываются. Выпуск также можно запустить вручную или тегом; тег должен совпадать с версией приложения. Описание релиза берётся из `RELEASE_NOTES.md`.

Идентификатор AppId в установщике постоянный: `{066C3D60-D933-4FBC-8C9E-D95B978C10AC}`. При обновлении сохраняется существующий путь установки. Старый `Masterskaya.exe` заменяется на `item-40.exe`. Пользовательские данные находятся вне папки приложения и при обновлении не удаляются.

Установщик не имеет цифровой подписи. Локальная проверка сборки не заменяет проверку на чистой Windows.
