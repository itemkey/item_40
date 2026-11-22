# Сторонние компоненты

item-40 использует компоненты, распространяемые по собственным лицензиям. Исходные лицензии Python-пакетов включены в папку `licenses` готовой сборки.

| Компонент | Лицензия / источник |
| --- | --- |
| Python | [PSF License](https://docs.python.org/3/license.html) |
| PySide6 / Qt / Shiboken | [LGPLv3 / GPLv3 / коммерческая](https://doc.qt.io/qtforpython-6/licenses.html); библиотеки подключаются динамически |
| faster-whisper | [MIT](https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE) |
| CTranslate2 | [MIT](https://github.com/OpenNMT/CTranslate2/blob/master/LICENSE) |
| Whisper / модели | [MIT](https://github.com/openai/whisper/blob/main/LICENSE) |
| PyAV | [BSD-3-Clause](https://github.com/PyAV-Org/PyAV/blob/main/LICENSE.txt) |
| FFmpeg в PyAV | [LGPL/GPL в зависимости от конфигурации сборки](https://ffmpeg.org/legal.html); сведения о конкретных библиотеках находятся в метаданных PyAV |
| ONNX Runtime | [MIT](https://github.com/microsoft/onnxruntime/blob/main/LICENSE) |
| NumPy | [BSD-3-Clause](https://github.com/numpy/numpy/blob/main/LICENSE.txt) |
| Hugging Face Hub / Tokenizers | [Apache-2.0](https://github.com/huggingface/huggingface_hub/blob/main/LICENSE) |
| Requests | [Apache-2.0](https://github.com/psf/requests/blob/main/LICENSE) |
| yt-dlp для Windows | [GPLv3+ для исполняемого файла](https://github.com/yt-dlp/yt-dlp#licensing) |
| Deno | [MIT и лицензии зависимостей](https://github.com/denoland/deno/blob/v2.9.8/LICENSE.md) |
| FFmpeg для скачивания и конвертации | [GPL, сборка Gyan](https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2) |
| Pillow | [HPND](https://github.com/python-pillow/Pillow) |
| pypdfium2 / PDFium | [Apache-2.0, BSD-3-Clause и лицензии зависимостей](https://github.com/pypdfium2-team/pypdfium2) |
| rlottie-python / rlottie | [MIT / LGPL-2.1](https://github.com/laggykiller/rlottie-python) |
| pysubs2 | [MIT](https://github.com/tkarabela/pysubs2) |
| python-docx | [MIT](https://github.com/python-openxml/python-docx) |
| pypdf | [BSD-3-Clause](https://github.com/py-pdf/pypdf) |
| ImageMagick | [ImageMagick License](https://imagemagick.org/license/) |
| Pandoc | [GPL-2.0-or-later](https://github.com/jgm/pandoc) |
| LibreOffice | [MPL-2.0 и лицензии компонентов](https://www.libreoffice.org/about-us/licenses/) |
| calibre | [GPL-3.0](https://github.com/kovidgoyal/calibre) |
| 7-Zip | [LGPL и ограничения unRAR](https://www.7-zip.org/license.txt) |
| Tesseract / tessdata_fast | [Apache-2.0](https://github.com/tesseract-ocr/tesseract) |

yt-dlp, Deno и отдельная сборка FFmpeg загружаются из исходных релизов при первом использовании инструмента YouTube. Версии и SHA‑256 закреплены в `item40/youtube_tools.py`.

Движки конвертации загружаются из официальных дистрибутивов по мере использования. Их версии, URL и SHA‑256 закреплены в `item40/component_manifest.json`. Распакованные дистрибутивы и включённые в них лицензии остаются в пользовательском каталоге компонентов. Для проверки происхождения используются исходные релизы поставщиков, указанные в манифесте.

GPU-библиотеки NVIDIA не включены в установщик. Приложение отдельно скачивает неизменённые официальные Windows wheels с PyPI и извлекает DLL и лицензии в пользовательский каталог. На них распространяются условия NVIDIA; тексты лицензий сохраняются рядом с библиотеками. Требуется совместимый драйвер NVIDIA.

Ссылки на исходники и соответствующие версии зависимостей зафиксированы в `uv.lock`. Qt DLL хранятся отдельно от исполняемого файла и могут быть заменены совместимыми сборками. Приложение не ограничивает отладку изменений библиотек, разрешённую их лицензиями.
