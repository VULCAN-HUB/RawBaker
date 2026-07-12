import sys
import os
import json
from pathlib import Path

# ── Qt 플랫폼 플러그인 경로 (venv 직접 실행 시 필요) ──────────────────────
# PyInstaller exe는 자동 처리되므로 dev 모드일 때만 설정한다.
if not getattr(sys, "frozen", False):
    _base = Path(__file__).parent
    _qt_plugins = _base / "venv" / "Lib" / "site-packages" / "PyQt5" / "Qt5" / "plugins"
    if _qt_plugins.exists():
        os.environ["QT_PLUGIN_PATH"] = str(_qt_plugins)
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(_qt_plugins / "platforms")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QSettings
from PyQt5.QtGui import QIcon

# Ensure local imports work when frozen by PyInstaller
if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = Path(__file__).parent

sys.path.insert(0, str(BASE_DIR))


def load_lang(key: str = "ko") -> dict:
    lang_file = Path(BASE_DIR) / "i18n" / f"lang_{key}.json"
    if not lang_file.exists():
        lang_file = Path(BASE_DIR) / "i18n" / "lang_ko.json"
    with open(lang_file, encoding="utf-8") as f:
        return json.load(f)


def _install_excepthook():
    """처리되지 않은 예외를 조용히 종료하지 않고 대화상자로 표시."""
    import traceback
    def hook(exc_type, exc, tb):
        msg = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(None, "RawBaker 오류", msg[:3500])
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)
    sys.excepthook = hook


def main():
    _install_excepthook()
    app = QApplication(sys.argv)
    app.setApplicationName("RawBaker")
    app.setOrganizationName("RawBaker")

    # Load saved language
    settings = QSettings("RawBaker", "RawBaker")
    lang_key = settings.value("language", "ko")
    lang = load_lang(lang_key)

    # App icon
    icon_path = Path(BASE_DIR) / "assets" / "icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Font fallback for Rajdhani (header logo)
    from PyQt5.QtGui import QFontDatabase
    font_dir = Path(BASE_DIR) / "assets"
    for ffile in font_dir.glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(ffile))

    from ui.main_window import MainWindow
    win = MainWindow(lang, lang_key)
    win.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
