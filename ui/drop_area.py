from PyQt5.QtWidgets import QListWidget, QListWidgetItem, QAbstractItemView
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QIcon, QPixmap, QColor, QPainter, QFont

import os
from pathlib import Path


STATUS_COLORS = {
    "waiting":    "#888888",
    "converting": "#D35400",
    "done":       "#27AE60",
    "error":      "#E74C3C",
    "skipped":    "#C9A227",
}

STATUS_ICONS = {
    "waiting":    "⏳",
    "converting": "🔄",
    "done":       "✅",
    "error":      "❌",
    "skipped":    "⏭️",
}


def make_placeholder_pixmap(size: int = 56) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(QColor("#1E1E1E"))
    painter = QPainter(pm)
    painter.setPen(QColor("#555555"))
    font = QFont("Arial", 8)
    painter.setFont(font)
    painter.drawText(pm.rect(), Qt.AlignCenter, "RAW")
    painter.end()
    return pm


# 플레이스홀더는 모든 항목이 동일하므로 한 번만 만들어 공유 (재생성 병목 방지)
_PLACEHOLDER_CACHE = None


def _shared_placeholder() -> QPixmap:
    global _PLACEHOLDER_CACHE
    if _PLACEHOLDER_CACHE is None:
        _PLACEHOLDER_CACHE = make_placeholder_pixmap(56)
    return _PLACEHOLDER_CACHE


class FileListWidget(QListWidget):
    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setIconSize(QSize(56, 56))
        self.setSpacing(2)
        self.setStyleSheet("""
            QListWidget {
                background: #1A1A1A;
                border: 1px solid #2A2A2A;
                color: #CCCCCC;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 4px;
                border-bottom: 1px solid #222222;
            }
            QListWidget::item:selected {
                background: #2C2C2C;
                color: #D35400;
            }
            QListWidget::item:hover {
                background: #222222;
            }
        """)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isfile(path):
                paths.append(path)
            elif os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for f in files:
                        paths.append(os.path.join(root, f))
        if paths:
            self.files_dropped.emit(paths)


class FileItem(QListWidgetItem):
    SUPPORTED = {
        ".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf",
        ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp", ".bmp",
    }

    def __init__(self, path: str, lang: dict):
        super().__init__()
        self.path = path
        self.status = "waiting"
        self.error_msg = ""
        self.adjustments: dict = {}
        self._lang = lang
        self._thumb_pm = None   # 썸네일 캐시 (디스크 재로드 방지)
        self._refresh_display()

    def _refresh_display(self):
        name = Path(self.path).name
        ext = Path(self.path).suffix.lower()
        size_str = self._file_size()
        icon_ch = STATUS_ICONS.get(self.status, "⏳")
        status_label = self._lang.get(f"status_{self.status}", self.status)
        adj_mark = " ✎" if self.adjustments else ""
        self.setText(f"{icon_ch}  {name}{adj_mark}\n    {ext.upper()[1:]}  {size_str}  —  {status_label}")

        # Thumbnail
        pm = self._make_thumbnail()
        self.setIcon(QIcon(pm))
        self.setSizeHint(QSize(220, 64))

    # 일반 이미지 확장자 (썸네일을 디스크에서 로드 가능한 형식)
    _THUMB_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"}

    def _make_thumbnail(self) -> QPixmap:
        # 실제 썸네일이 비동기로 채워지기 전까지는 플레이스홀더만 반환.
        # ※ 추가 시점에 디스크 동기 로드를 하지 않아 대량 추가 시 UI 멈춤을 방지(UX).
        if self._thumb_pm is not None:
            return self._thumb_pm
        return _shared_placeholder()

    def needs_thumbnail(self) -> bool:
        """아직 썸네일이 없고, 디스크에서 로드 가능한 일반 이미지인가."""
        return (self._thumb_pm is None
                and Path(self.path).suffix.lower() in self._THUMB_EXTS)

    def set_thumbnail(self, pm: QPixmap):
        """백그라운드 로더가 만든 썸네일을 적용 (아이콘만 갱신)."""
        self._thumb_pm = pm
        self.setIcon(QIcon(pm))
        self.setSizeHint(QSize(220, 64))

    def _file_size(self) -> str:
        try:
            b = os.path.getsize(self.path)
            if b < 1024:
                return f"{b}B"
            elif b < 1024 * 1024:
                return f"{b/1024:.1f}KB"
            else:
                return f"{b/1024/1024:.1f}MB"
        except Exception:
            return ""

    def set_status(self, status: str, error_msg: str = ""):
        self.status = status
        self.error_msg = error_msg
        self._refresh_display()

    def update_lang(self, lang: dict):
        self._lang = lang
        self._refresh_display()
