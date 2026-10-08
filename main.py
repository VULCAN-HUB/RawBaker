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
    from PyQt5.QtCore import Qt, QTimer
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    smoke_root = None
    if "--smoke-test" in sys.argv:
        import tempfile
        smoke_root = tempfile.TemporaryDirectory(prefix="rawbaker-smoke-")
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, smoke_root.name)
    app = QApplication(sys.argv)
    app.setApplicationName("RawBaker")
    app.setOrganizationName("RawBaker")

    # Load saved language
    settings = QSettings("RawBaker", "RawBaker")
    lang_key = settings.value("language", "ko")
    if smoke_root and "--smoke-language" in sys.argv:
        requested = sys.argv[sys.argv.index("--smoke-language")+1]
        if requested not in ("ko", "en"):
            raise ValueError("Smoke language must be ko or en")
        lang_key = requested
    lang = load_lang(lang_key)

    # App icon
    icon_path = Path(BASE_DIR) / "assets" / "icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Font fallback for Rajdhani (header logo)
    from PyQt5.QtGui import QFontDatabase, QFont
    font_dir = Path(BASE_DIR) / "assets"
    for ffile in list(font_dir.rglob("*.ttf")) + list(font_dir.rglob("*.otf")):
        QFontDatabase.addApplicationFont(str(ffile))
    app.setFont(QFont("Pretendard", 10))

    if "--legacy" in sys.argv:
        from ui.main_window import MainWindow
        win = MainWindow(lang, lang_key)
    else:
        from ui.editor_window import EditorWindow as StudioWindow
        win = StudioWindow(lang, lang_key, storage_root=Path(smoke_root.name)/"sessions" if smoke_root else None,
                           offer_recovery=not bool(smoke_root))
    win.show()
    if smoke_root:
        # Deterministic startup check for packaged builds, with isolated user state.
        output = Path(sys.argv[sys.argv.index("--smoke-test")+1])
        def smoke_complete():
            result = {"started": True, "title": win.windowTitle(), "qt": "PyQt5", "frozen": bool(getattr(sys, "frozen", False))}
            result["language"] = lang_key
            try:
                from core.studio_smoke import run_smoke
                result["checks"] = run_smoke(Path(smoke_root.name)/"verification")
                if hasattr(win, 'empty_document'):
                    assert not win.empty_document.isHidden()
                    assert not win.command_actions['export_current'][0].isEnabled()
                    assert all(not spin.isEnabled() for spin in win.layer_spins.values())
                    result["checks"]["empty_editor_readiness"] = True
                win.grab().save(str(output.with_suffix(".png")))
                from ui.brand import BrandAbout
                from ui.app_update import current_version, build_target
                from core.app_update import Version
                about = BrandAbout(win)
                about.show(); app.processEvents()
                assert about.updates.controller.state == 'idle'
                assert about.updates.controller.apply() is False
                from version import VERSION_TUPLE
                assert Version(current_version()).base == VERSION_TUPLE[:3]
                if getattr(sys, 'frozen', False) and sys.platform == 'win32':
                    assert build_target() == ('windows', 'x64', 'portable-zip')
                result['checks']['about_update_idle_and_package'] = True
                assert 'Pretendard' in QFontDatabase().families() and 'Rajdhani' in QFontDatabase().families()
                result['checks']['brand_fonts'] = True
                about.licenses.click()
                assert 'SIL OPEN FONT LICENSE' in about.license_text.toPlainText()
                result['checks']['bundled_font_licenses'] = True
                about.pages.setCurrentIndex(0)
                about.grab().save(str(output.with_name(output.stem + '-about.png')))
                about.close()
            except Exception as error:
                result["error"] = str(error)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            win.close(); app.exit(1 if "error" in result else 0)
        QTimer.singleShot(1200, smoke_complete)

    code = app.exec_()
    if smoke_root: smoke_root.cleanup()
    sys.exit(code)


if __name__ == "__main__":
    main()
