from __future__ import annotations

import json
import os
from pathlib import Path

_language = os.environ.get("ITEM40_UI_LANGUAGE", "ru")
_catalog = None


def language():
    return _language


def set_language(code):
    global _language
    _language = code if code in {"ru", "en"} else "en"
    os.environ["ITEM40_UI_LANGUAGE"] = _language


def tr(text, *values):
    global _catalog
    if _language == "en":
        if _catalog is None:
            _catalog = json.loads((Path(__file__).parent / "translations" / "en.json").read_text(encoding="utf-8"))
        text = _catalog.get(text, text)
    return text.format(*values) if values else text


def registry_key():
    return os.environ.get("ITEM40_LANGUAGE_REGISTRY_KEY", r"Software\item-40")


def selected_language():
    from PySide6.QtCore import QLocale

    if override := os.environ.get("ITEM40_UI_LANGUAGE"):
        return override if override in {"ru", "en"} else "en"
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_key()) as key:
            code = winreg.QueryValueEx(key, "UILanguage")[0]
            if code in {"ru", "en"}:
                return code
    except OSError:
        pass
    return "ru" if QLocale.system().language() == QLocale.Language.Russian else "en"


def save_language(code):
    import winreg

    if code not in {"ru", "en"}:
        raise ValueError("Unknown language")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, registry_key()) as key:
        winreg.SetValueEx(key, "UILanguage", 0, winreg.REG_SZ, code)


def install_qt_translation(app):
    from PySide6.QtCore import QLibraryInfo, QTranslator

    translator = QTranslator(app)
    if translator.load(f"qtbase_{language()}", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    return translator
