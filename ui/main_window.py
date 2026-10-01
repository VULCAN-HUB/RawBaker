import os
import sys
import time
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

BASE_DIR = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parent.parent

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QPushButton, QLabel, QFileDialog, QMessageBox, QStackedWidget,
    QSizePolicy, QDialog, QDialogButtonBox,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSettings, QTimer
from PyQt5.QtGui import QPixmap, QIcon, QFont, QColor, QPalette, QImage

from ui.drop_area import FileListWidget, FileItem
from ui.edit_panel import EditPanel
from ui.options_panel import OptionsPanel
from ui.crop_preview import CropPreviewWidget
from ui.progress_bar import ConvertProgressBar
from core.resizer import centered_aspect_rect
from core.converter import convert_file, ConvertError, RAW_EXTENSIONS, NORMAL_EXTENSIONS
from core.image_io import open_raw, open_raw_preview, open_normal, icc_to_srgb, AUTO_BRIGHT_FACTOR
from core import platform_utils
import version

SUPPORTED_EXTENSIONS = RAW_EXTENSIONS | NORMAL_EXTENSIONS
_RAW_EXTS = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf"}

SETTINGS_ORG = "RawBaker"
SETTINGS_APP = "RawBaker"
_ADJ_CACHE_MAX = 20   # 최대 캐시 항목 수


# ---------------------------------------------------------------------------
# 동적 워커 수 계산 — OOM / Deadlock 방지 (DEF-002)
# ---------------------------------------------------------------------------

def _get_available_ram_mb() -> float:
    """현재 가용 물리 RAM(MB) — 크로스플랫폼 구현은 core.platform_utils 에 위임."""
    return platform_utils.available_ram_mb()


_RAW_EXTS_FOR_MEM = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf"}

def _estimate_peak_memory_mb(jobs: list) -> float:
    """
    배치 내 단일 파일의 파이프라인 피크 메모리 사용량(MB) 추정.

    ※ 피크는 RAW 디코딩 직후가 아니라 **보정 파이프라인 실행 중**에 발생한다.
       core/pipeline.py 의 모든 보정 스텝은 _to_rgb_f32() 로 float32 RGB
       버퍼(12 bytes/px)를 만들고, Vibrance·Hue 등은 추가 중간 배열까지 생성한다.
       따라서 디코딩 expansion 만으로는 과소평가되어 OOM을 유발한다(DEF-002).

    RAW 파일 (open_raw_full → rawpy.postprocess → float32 보정):
        디스크 크기 × 20 배
        근거: 압축 해제 uint8 RGB(~4x) × float32 파이프라인 워킹셋(~5x:
              입력 uint8 + float32 in + float32 out + 중간 복사본)

    일반 이미지 (JPEG/PNG → float32 보정):
        디스크 크기 × 10 배
        근거: 픽셀 디코딩(~3x, JPEG는 더 큼) × float32 워킹셋의 일부

    가장 큰 파일 기준으로 계산 (최악 케이스 보수적 추정).
    추정은 휴리스틱이며 디스크 크기로 센서 해상도를 직접 알 수 없으므로
    보수적으로 잡아 OOM 쪽 오류보다 약간의 throughput 손실을 택한다.
    """
    RAW_MULT  = 20.0
    NORM_MULT = 10.0
    MIN_MB    = 64.0   # 파일 접근 실패 시 최소 가정값

    peak = 0.0
    for job in jobs:
        try:
            size_mb = os.path.getsize(job.get("path", "")) / (1024 * 1024)
        except OSError:
            size_mb = MIN_MB
        ext  = Path(job.get("path", "")).suffix.lower()
        mult = RAW_MULT if ext in _RAW_EXTS_FOR_MEM else NORM_MULT
        peak = max(peak, size_mb * mult)

    return max(peak, MIN_MB)


def _calc_safe_workers(jobs: list) -> int:
    """
    가용 RAM과 파일별 피크 메모리를 런타임에 측정하여
    OOM 없이 병렬 실행 가능한 안전한 워커 수를 반환.

    산출 공식:
        usable_mb   = available_ram_mb × 0.70   (30% 는 OS·GUI·캐시 여유분)
        dynamic     = floor(usable_mb / peak_mb_per_file)
        safe_workers = clamp(dynamic, min=1, max=min(4, cpu_count))

    결과 보장:
        - 최소 1 (단일 파일도 처리 불가한 RAM 부족 시 순차 처리로 강등)
        - 최대 4 (기존 상한 유지, CPU 코어 수 이하)
        - 소용량 파일(JPEG 5MB)은 usable/peak ≫ 4 → 기존과 동일하게 4 워커
    """
    available_mb = _get_available_ram_mb()
    peak_mb      = _estimate_peak_memory_mb(jobs)
    usable_mb    = available_mb * 0.70

    dynamic  = max(1, int(usable_mb / peak_mb))
    cpu_cap  = min(4, os.cpu_count() or 2)
    return min(dynamic, cpu_cap)


# ---------------------------------------------------------------------------
# Worker: 변환
# ---------------------------------------------------------------------------

class ConvertWorker(QThread):
    progress_file = pyqtSignal(int, int, float)
    file_done     = pyqtSignal(int, str, str)
    all_done      = pyqtSignal(int, int)

    def __init__(self, jobs: list, opts: dict):
        """jobs: [{"path": str, "adjustments": dict|None}, ...]"""
        super().__init__()
        self._jobs  = deepcopy(jobs)
        self._protected_inputs = tuple(job["path"] for job in self._jobs)
        self._opts  = deepcopy(opts)
        self._abort = False

    def abort(self):
        self._abort = True

    def _convert_one(self, idx: int, job: dict, t_start: float):
        opts     = self._opts
        src_path = job["path"]
        adj      = job.get("adjustments") or None
        out_dir  = opts.get("out_dir") or str(Path(src_path).parent)

        def cb(pct):
            if not self._abort:
                elapsed = time.time() - t_start
                self.progress_file.emit(idx, pct, elapsed)

        out_path = convert_file(
            src_path=src_path,
            out_dir=out_dir,
            out_format=opts["out_format"],
            jpeg_quality=opts["jpeg_quality"],
            resize_mode=opts["resize_mode"],
            custom_w=opts["custom_w"],
            custom_h=opts["custom_h"],
            exif_mode=opts["exif_mode"],
            adjustments=adj,
            progress_cb=cb,
            on_collision=opts.get("on_collision", "rename"),
            rename_suffix=opts.get("rename_suffix", ""),
            crop_enabled=opts.get("crop_enabled", False),
            crop_landscape=opts.get("crop_landscape", (2400, 1600)),
            crop_portrait=opts.get("crop_portrait", (1066, 1600)),
            crop_rect_landscape=opts.get("crop_rect_landscape"),
            crop_rect_portrait=opts.get("crop_rect_portrait"),
            dpi=opts.get("dpi", 0),
            auto_bright=opts.get("auto_bright", True),
            protected_inputs=self._protected_inputs,
        )

        if out_path is None:
            return None   # 충돌 건너뜀

        return out_path

    def run(self):
        done   = 0
        errors = 0
        t_start = time.time()

        with ThreadPoolExecutor(max_workers=_calc_safe_workers(self._jobs)) as pool:
            futures = {
                pool.submit(self._convert_one, idx, job, t_start): idx
                for idx, job in enumerate(self._jobs)
                if not self._abort
            }
            for future in as_completed(futures):
                if self._abort:
                    break
                idx = futures[future]
                try:
                    res = future.result()
                    if res is None:
                        self.file_done.emit(idx, "skipped", "")
                    else:
                        self.file_done.emit(idx, "done", "")
                        done += 1
                except ConvertError as e:
                    self.file_done.emit(idx, "error", str(e))
                    errors += 1
                except Exception:
                    self.file_done.emit(idx, "error", "변환 중 문제가 발생했습니다.")
                    errors += 1

        self.all_done.emit(done, errors)


def _pil_to_qpixmap(img) -> QPixmap:
    """PIL.Image(RGB) → QPixmap."""
    import numpy as np
    arr = np.array(img.convert("RGB"))
    h, w, ch = arr.shape
    qimg = QImage(arr.data, w, h, ch * w, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(qimg)


# ---------------------------------------------------------------------------
# Worker: 미리보기 base 이미지 로드 (PIL.Image, ICC 보정 포함)
# ---------------------------------------------------------------------------

class AdjBaseLoader(QThread):
    """RAW 또는 일반 이미지를 ICC 보정된 PIL.Image로 로드해 캐시용으로 반환."""
    loaded = pyqtSignal(str, object)   # path, PIL.Image
    failed = pyqtSignal(str)

    _MAX_SIDE = 1600

    def __init__(self, path: str, bright: float = AUTO_BRIGHT_FACTOR):
        super().__init__()
        self._path = path
        self._bright = bright

    def run(self):
        try:
            from PIL import Image
            ext = Path(self._path).suffix.lower()

            # open_raw_preview / open_normal — 변환 출력과 동일한 색감(WYSIWYG)
            if ext in _RAW_EXTS:
                img = open_raw_preview(self._path, bright=self._bright)
            else:
                img = open_normal(self._path).convert("RGB")

            # 긴 쪽을 _MAX_SIDE 이하로 축소
            w, h = img.size
            longest = max(w, h)
            if longest > self._MAX_SIDE:
                scale = self._MAX_SIDE / longest
                img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

            self.loaded.emit(self._path, img)
        except Exception:
            self.failed.emit(self._path)


# ---------------------------------------------------------------------------
# Worker: 보정 적용 → QPixmap
# ---------------------------------------------------------------------------

class AdjPreviewWorker(QThread):
    """PIL.Image + adjustments → QPixmap."""
    loaded = pyqtSignal(QPixmap)

    def __init__(self, base_img, adjustments: dict):
        super().__init__()
        self._base = base_img
        self._adj  = adjustments

    def run(self):
        try:
            from core.pipeline import apply_adjustments
            img = self._base.copy()
            if self._adj:
                img = apply_adjustments(img, self._adj)
            self.loaded.emit(_pil_to_qpixmap(img))
        except Exception:
            pass




# ---------------------------------------------------------------------------
# 미리보기 로더 — RAW/일반 모두 ICC 보정 후 QPixmap 반환
# ---------------------------------------------------------------------------

class ImagePreviewLoader(QThread):
    """
    모든 파일 형식을 배경 스레드에서 로드.
    - RAW: rawpy 디코딩(open_raw_preview) → 변환 출력과 동일한 색감(WYSIWYG)
    - 일반 이미지: PIL 로드 → ICC→sRGB 변환
    """
    loaded = pyqtSignal(QPixmap)
    failed = pyqtSignal()

    def __init__(self, path: str, bright: float = AUTO_BRIGHT_FACTOR):
        super().__init__()
        self._path = path
        self._bright = bright

    def run(self):
        try:
            ext = Path(self._path).suffix.lower()
            if ext in _RAW_EXTS:
                img = open_raw_preview(self._path, bright=self._bright)   # 출력과 동일한 색감(WYSIWYG)
            else:
                img = open_normal(self._path).convert("RGB")
            self.loaded.emit(_pil_to_qpixmap(img))
        except Exception:
            self.failed.emit()


# ---------------------------------------------------------------------------
# Worker: 목록 썸네일 백그라운드 로더 (대량 추가 시 UI 멈춤 방지)
# ---------------------------------------------------------------------------

class ThumbnailLoader(QThread):
    """일반 이미지 썸네일을 배경 스레드에서 QImage로 로드.

    ※ QPixmap 은 메인 스레드 전용이므로 여기서는 QImage(스레드 안전)만 만들고,
       메인 스레드 슬롯에서 QPixmap 으로 변환해 아이콘에 적용한다.
    """
    thumb_ready = pyqtSignal(str, object)   # path, QImage

    def __init__(self, paths: list):
        super().__init__()
        self._paths = list(paths)
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        for p in self._paths:
            if self._abort:
                break
            try:
                img = QImage(p)
                if not img.isNull():
                    img = img.scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self.thumb_ready.emit(p, img)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Preview Widget
# ---------------------------------------------------------------------------

class PreviewWidget(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._source_pm: Optional[QPixmap] = None
        self._loader: Optional[ImagePreviewLoader] = None
        self._retained: set = set()   # 실행 중 로더 조기 GC 방지
        self._show_placeholder()

    def _show_placeholder(self):
        self._source_pm = None
        self.setPixmap(QPixmap())
        self.setText("No Preview")
        self.setStyleSheet(
            "background:#111111; border:1px solid #222222; "
            "color:#444444; font-size:14px;"
        )

    def _show_loading(self, filename: str):
        self.setPixmap(QPixmap())
        self.setText(f"⏳  {filename}")
        self.setStyleSheet(
            "background:#111111; border:1px solid #222222; color:#666666; font-size:12px;"
        )

    def cancel(self):
        """진행 중인 로더를 취소. 이후 emit이 와도 무시됨."""
        if self._loader and self._loader.isRunning():
            try: self._loader.loaded.disconnect()
            except Exception: pass
            try: self._loader.failed.disconnect()
            except Exception: pass
            self._loader = None

    def load(self, path: str, bright: float = AUTO_BRIGHT_FACTOR):
        self.cancel()
        self._show_loading(Path(path).name)
        self._loader = ImagePreviewLoader(path, bright=bright)
        self._loader.loaded.connect(self._on_loaded)
        self._loader.failed.connect(self._on_failed)
        # 실행 중인 로더의 참조를 finished 까지 유지 (조기 GC 크래시 방지)
        self._retained.add(self._loader)
        self._loader.finished.connect(lambda t=self._loader: self._retained.discard(t))
        self._loader.start()

    def set_pixmap_direct(self, pm: QPixmap):
        """보정 미리보기에서 직접 QPixmap 설정."""
        self._set_pixmap(pm)

    def _on_loaded(self, pm: QPixmap):
        self._set_pixmap(pm)

    def _on_failed(self):
        self.setText("미리보기를 표시할 수 없습니다")
        self.setStyleSheet(
            "background:#111111; border:1px solid #222222; color:#555555; font-size:12px;"
        )

    def _set_pixmap(self, pm: QPixmap):
        self._source_pm = pm
        self._update_scaled()
        self.setStyleSheet("background:#111111; border:1px solid #222222;")

    def _update_scaled(self):
        if self._source_pm and not self._source_pm.isNull():
            scaled = self._source_pm.scaled(
                max(1, self.width() - 10), max(1, self.height() - 10),
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            self.setPixmap(scaled)
            self.setText("")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scaled()


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, lang: dict, lang_key: str, *, project_storage_root=None, offer_recovery=True):
        super().__init__()
        self._lang      = lang
        self._lang_key  = lang_key
        self._items: list[FileItem] = []
        self._worker: Optional[ConvertWorker] = None
        self._converting = False
        self._settings   = QSettings(SETTINGS_ORG, SETTINGS_APP)

        # 보정 모드 상태
        self._edit_item: Optional[FileItem] = None
        self._adj_base_cache: dict[str, object] = {}   # path → PIL.Image
        self._adj_base_loader: Optional[AdjBaseLoader] = None
        self._adj_preview_worker: Optional[AdjPreviewWorker] = None
        # 실행 중 QThread 의 파이썬 참조를 finished 까지 유지해
        # 'QThread: Destroyed while thread is still running' 크래시를 방지한다.
        self._retained_threads: set = set()
        self._adj_timer = QTimer()
        self._adj_timer.setSingleShot(True)
        self._adj_timer.timeout.connect(self._fire_adj_preview)

        self._init_ui()
        self._apply_dark_theme()
        self._restore_settings()
        self._center_window()
        from ui.project_controller import ProjectController
        self.projects = ProjectController(self, project_storage_root, offer_recovery)

    # -----------------------------------------------------------------------
    # UI 구성
    # -----------------------------------------------------------------------

    def _init_ui(self):
        self.setWindowTitle(self._lang["app_title"])
        # 오른쪽 옵션이 눌리지 않도록 최소 크기를 충분히 확보 (이 이하로는 축소 불가)
        self.setMinimumSize(1100, 760)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 4)
        root_layout.setSpacing(6)

        root_layout.addWidget(self._make_header())

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)
        splitter.setStyleSheet("QSplitter::handle { background: #2A2A2A; }")

        splitter.addWidget(self._make_left_panel())
        splitter.addWidget(self._make_center_panel())

        # 오른쪽: 상단 탭(파일 탭 스타일) + 패널 스택
        right_container = QWidget()
        right_container.setMinimumWidth(240)
        right_container.setMaximumWidth(330)
        rc_lay = QVBoxLayout(right_container)
        rc_lay.setContentsMargins(0, 0, 0, 0)
        rc_lay.setSpacing(0)

        # 탭 바
        tabbar = QWidget()
        tabbar.setFixedHeight(34)
        tabbar.setStyleSheet("background:#111111;")
        tb_lay = QHBoxLayout(tabbar)
        tb_lay.setContentsMargins(2, 6, 2, 0)
        tb_lay.setSpacing(3)
        self._mode_btns = {}
        for key, text in (("output", "출력 설정"), ("edit", "보정"), ("size", "크기 조절")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setFixedHeight(28)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(self._tab_btn_style())
            self._mode_btns[key] = b
            tb_lay.addWidget(b, 1)
        self._mode_btns["output"].clicked.connect(lambda: self._set_mode("output"))
        self._mode_btns["edit"].clicked.connect(lambda: self._set_mode("edit"))
        self._mode_btns["size"].clicked.connect(lambda: self._set_mode("size"))
        rc_lay.addWidget(tabbar)

        # 패널 스택 (탭과 연결된 본문)
        self._right_stack = QStackedWidget()
        self._right_stack.setStyleSheet(
            "QStackedWidget{background:#171717; border:1px solid #2E2E2E; border-top:none;}"
        )
        self.options = OptionsPanel(self._lang)
        self.edit_panel = EditPanel()
        self._right_stack.addWidget(self.options)    # index 0 (옵션)
        self._right_stack.addWidget(self.edit_panel) # index 1 (보정)
        rc_lay.addWidget(self._right_stack, stretch=1)

        splitter.addWidget(right_container)
        splitter.setSizes([260, 560, 280])
        root_layout.addWidget(splitter, stretch=1)

        root_layout.addWidget(self._make_bottom_bar())

        # 시그널 연결
        self.options.lang_combo.currentTextChanged.connect(self._on_lang_change)
        self.options.lang_combo.setCurrentText(
            "한국어" if self._lang_key == "ko" else "English"
        )
        self.edit_panel.back_requested.connect(lambda: self._set_mode("output"))
        self.edit_panel.adjustments_changed.connect(self._on_adj_changed)
        self.edit_panel.preview_compare.connect(self._on_preview_compare)
        self.edit_panel.apply_to_all.connect(self._apply_adj_to_all)
        self.options.crop_dims_changed.connect(self._on_crop_dims_changed)
        self.options.crop_cb.toggled.connect(self._on_crop_enabled_toggled)
        self.options.auto_bright_cb.toggled.connect(self._on_auto_bright_changed)
        self._mode_btns["output"].setChecked(True)
        self._crop_orient = "l"

    def _make_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(44)
        w.setStyleSheet("background:#111111; border-bottom:1px solid #222222;")
        layout = QHBoxLayout(w)
        layout.setContentsMargins(12, 4, 12, 4)

        logo_path = Path(BASE_DIR) / "assets" / "logo.png"
        if logo_path.exists():
            pm = QPixmap(str(logo_path)).scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            lbl = QLabel(); lbl.setPixmap(pm); lbl.setFixedSize(40, 40)
            layout.addWidget(lbl)
            layout.addSpacing(6)

        raw_lbl = QLabel("Raw")
        raw_lbl.setFont(QFont("Rajdhani", 22, QFont.Bold))
        raw_lbl.setStyleSheet("color:#FFFFFF;")
        baker_lbl = QLabel("Baker")
        baker_lbl.setFont(QFont("Rajdhani", 22, QFont.Bold))
        baker_lbl.setStyleSheet("color:#D35400;")
        tagline = QLabel("Digital Kiln | Processing & Perfection")
        tagline.setStyleSheet("color:#555555; font-size:11px;")

        layout.addWidget(raw_lbl)
        layout.addWidget(baker_lbl)
        layout.addSpacing(16)
        layout.addWidget(tagline)
        layout.addStretch()

        credit_lbl = QLabel("PROJECT 02  ·  Unknown")
        credit_lbl.setStyleSheet("color:#3A3A3A; font-size:11px; letter-spacing:1px;")
        layout.addWidget(credit_lbl)
        layout.addSpacing(8)

        about_btn = QPushButton("?")
        about_btn.setFixedSize(22, 22)
        about_btn.setToolTip("About RawBaker")
        about_btn.setStyleSheet("""
            QPushButton {
                background:transparent; color:#444444;
                border:1px solid #333333; border-radius:11px;
                font-size:12px; font-weight:bold;
            }
            QPushButton:hover { color:#D35400; border-color:#D35400; }
        """)
        about_btn.clicked.connect(self._show_about)
        layout.addWidget(about_btn)
        return w

    def _make_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(220)
        panel.setMaximumWidth(340)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = QLabel(self._lang["file_list_header"])
        header.setStyleSheet(
            "background:#1A1A1A; color:#D35400; font-weight:bold; "
            "font-size:12px; padding:6px 8px; border-bottom:1px solid #2A2A2A;"
        )
        layout.addWidget(header)

        self.file_list = FileListWidget()
        self.file_list.files_dropped.connect(self._add_files)
        self.file_list.itemSelectionChanged.connect(self._on_selection_change)
        layout.addWidget(self.file_list, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self.add_files_btn = self._small_btn("📄  파일 선택")
        self.add_files_btn.setToolTip("개별 이미지 파일 선택 (RAW · JPG · PNG · TIFF · WebP · BMP)")
        self.add_btn       = self._small_btn("📁  폴더 선택")
        self.add_files_btn.clicked.connect(self._open_files_dialog)
        self.add_btn.clicked.connect(self._open_folder_dialog)
        btn_row.addWidget(self.add_files_btn)
        btn_row.addWidget(self.add_btn)
        layout.addLayout(btn_row)

        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(4)
        self.remove_btn = self._small_btn(self._lang["remove_selected"])
        self.remove_btn.clicked.connect(self._remove_selected)
        btn_row2.addWidget(self.remove_btn)
        layout.addLayout(btn_row2)

        # 완료된 파일만 목록에서 제거하는 보조 버튼
        self.remove_done_btn = self._small_btn("✔  완료 항목 제거")
        self.remove_done_btn.setToolTip("변환이 완료된(✔) 파일만 목록에서 제거합니다")
        self.remove_done_btn.clicked.connect(self._remove_completed)
        layout.addWidget(self.remove_done_btn)
        return panel

    def _make_center_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 중앙: 일반 미리보기 / 크롭 편집기 전환 스택
        self.preview = PreviewWidget()
        self.crop_editor = CropPreviewWidget()
        self.crop_editor.rectChanged.connect(self._on_crop_rect_changed)
        self._center_stack = QStackedWidget()
        self._center_stack.addWidget(self.preview)       # index 0
        self._center_stack.addWidget(self.crop_editor)   # index 1
        layout.addWidget(self._center_stack, stretch=1)

        self.progress_bar = ConvertProgressBar()
        layout.addWidget(self.progress_bar)
        return panel

    def _make_bottom_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(48)
        bar.setStyleSheet("background:#111111; border-top:1px solid #222222;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 4, 12, 4)

        self.status_label = QLabel(self._lang["status_ready"])
        self.status_label.setStyleSheet("color:#888888; font-size:12px;")
        layout.addWidget(self.status_label, stretch=1)

        self.reset_btn = QPushButton(self._lang["reset_btn"])
        self.reset_btn.setFixedSize(90, 34)
        self.reset_btn.setStyleSheet(self._outline_btn_style())
        self.reset_btn.clicked.connect(self._reset)

        self.edit_btn = QPushButton("✏  보정")
        self.edit_btn.setFixedSize(90, 34)
        self.edit_btn.setEnabled(False)
        self.edit_btn.setStyleSheet(self._outline_btn_style())
        self.edit_btn.clicked.connect(self._toggle_edit_mode)

        self.convert_btn = QPushButton(self._lang["convert_btn"])
        self.convert_btn.setFixedSize(150, 34)
        self.convert_btn.setStyleSheet(self._primary_btn_style())
        self.convert_btn.clicked.connect(self._on_convert_clicked)

        layout.addWidget(self.reset_btn)
        layout.addSpacing(6)
        layout.addWidget(self.edit_btn)
        layout.addSpacing(8)
        layout.addWidget(self.convert_btn)
        return bar

    # -----------------------------------------------------------------------
    # 파일 관리
    # -----------------------------------------------------------------------

    def _add_files(self, paths: list):
        if self._converting:
            return  # 변환 중에는 목록 변경 차단
        existing = {item.path for item in self._items}
        skipped  = []
        thumb_paths = []
        for path in paths:
            ext = Path(path).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                skipped.append(Path(path).name)
                continue
            if path in existing:
                continue
            item = FileItem(path, self._lang)
            self.file_list.addItem(item)
            self._items.append(item)
            existing.add(path)
            if item.needs_thumbnail():
                thumb_paths.append(path)

        # 새로 추가된 일반 이미지 썸네일을 배경에서 로드 (UI 멈춤 방지)
        if thumb_paths:
            loader = ThumbnailLoader(thumb_paths)
            loader.thumb_ready.connect(self._on_thumb_ready)
            self._retain(loader)
            loader.start()

        if skipped:
            names = "\n".join(f"• {n}" for n in skipped[:5])
            if len(skipped) > 5:
                names += f"\n… 외 {len(skipped)-5}개"
            QMessageBox.information(
                self, "지원하지 않는 파일",
                f"아래 파일은 지원하지 않는 형식이어서 건너뛰었습니다:\n\n{names}\n\n"
                "지원 형식: RAW(CR2/CR3/NEF/ARW/DNG/ORF/RW2/RAF),\nJPEG, PNG, TIFF, WebP, BMP"
            )
        self._update_status_label()

    def _on_thumb_ready(self, path: str, qimage):
        """배경 로더가 만든 QImage → QPixmap 변환 후 해당 항목 아이콘 적용."""
        try:
            pm = QPixmap.fromImage(qimage)
        except Exception:
            return
        if pm.isNull():
            return
        for item in self._items:
            if isinstance(item, FileItem) and item.path == path and item._thumb_pm is None:
                item.set_thumbnail(pm)
                break

    def _flash_status(self, text: str, color: str = "#27AE60", ms: int = 1800):
        """상태바에 잠깐 메시지를 띄웠다가 원상복구."""
        self.status_label.setStyleSheet(f"color:{color}; font-size:12px; font-weight:bold;")
        self.status_label.setText(text)
        QTimer.singleShot(ms, lambda: self.status_label.setStyleSheet("color:#888888; font-size:12px;"))
        QTimer.singleShot(ms, self._update_status_label)

    def _open_files_dialog(self):
        """개별 이미지 파일 선택 (RAW + 일반 이미지)."""
        raw = "*.cr2 *.cr3 *.nef *.arw *.dng *.orf *.rw2 *.raf"
        norm = "*.jpg *.jpeg *.png *.tiff *.tif *.webp *.bmp"
        filt = ("이미지 파일 (" + raw + " " + norm + ");;"
                "RAW (" + raw + ");;"
                "일반 이미지 (" + norm + ");;"
                "모든 파일 (*.*)")
        paths, _ = QFileDialog.getOpenFileNames(self, "이미지 파일 선택", "", filt)
        if paths:
            self._add_files(paths)

    def _open_folder_dialog(self):
        """폴더를 선택해 하위 폴더 포함 모든 이미지를 재귀 탐색해 추가."""
        folder = QFileDialog.getExistingDirectory(
            self, "이미지 폴더 선택", "", QFileDialog.ShowDirsOnly
        )
        if not folder:
            return
        paths = []
        for root, _, files in os.walk(folder):
            for f in files:
                paths.append(os.path.join(root, f))
        if paths:
            self._add_files(paths)
        else:
            QMessageBox.information(
                self, "폴더 선택",
                "선택한 폴더에 지원 가능한 이미지 파일이 없습니다.\n\n"
                "지원 형식: RAW(CR2/CR3/NEF/ARW/DNG/ORF/RW2/RAF),\nJPEG, PNG, TIFF, WebP, BMP"
            )

    def _remove_items(self, targets: list):
        """
        주어진 항목들을 목록에서 안전하게 제거.

        ※ 크래시 방지: takeItem() 은 itemSelectionChanged 시그널을 재진입
          호출해, 삭제 중인 C++ 객체에 _on_selection_change 가 접근하면서
          세그폴트(프로그램 강제 종료)를 일으킨다. blockSignals 로 재진입을
          차단하고, 모든 제거가 끝난 뒤 UI를 한 번만 갱신한다.
        """
        if not targets:
            return

        # 편집 중인 항목이 제거 대상이면 먼저 보정 모드를 빠져나간다
        if self._edit_item in targets:
            self._exit_edit_mode(restore_preview=False)

        self.file_list.blockSignals(True)
        try:
            for item in targets:
                row = self.file_list.row(item)
                if row >= 0:
                    self.file_list.takeItem(row)
                if isinstance(item, FileItem):
                    self._adj_base_cache.pop(item.path, None)
            target_set = {id(t) for t in targets}
            self._items = [i for i in self._items if id(i) not in target_set]
        finally:
            self.file_list.blockSignals(False)

        # 목록이 비면 미리보기 초기화
        if not self._items:
            self.preview.cancel()
            self.preview._show_placeholder()

        # 시그널을 막아둔 동안 누락된 선택 상태 UI를 수동 갱신
        self._on_selection_change()
        self._update_status_label()

    def _remove_selected(self):
        self._remove_items(list(self.file_list.selectedItems()))

    def _remove_completed(self):
        """변환이 완료된(status == 'done') 항목만 목록에서 제거."""
        done = [
            i for i in self._items
            if isinstance(i, FileItem) and getattr(i, "status", "") == "done"
        ]
        if not done:
            QMessageBox.information(self, "완료 항목 제거",
                                    "완료된 파일이 없습니다.")
            return
        self._remove_items(done)

    def _apply_adj_to_all(self, adj: dict):
        """보정 패널의 '전체 적용' → 목록 모든 파일에 보정값 일괄 복사."""
        import copy
        if not self._items:
            return
        has_existing = any(item.adjustments for item in self._items)
        if has_existing:
            reply = QMessageBox.question(
                self, "전체 보정 적용",
                f"전체 {len(self._items)}개 파일에 현재 보정값을 적용합니다.\n"
                "기존 보정값은 덮어씌워집니다. 계속하시겠습니까?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        for item in self._items:
            item.adjustments = copy.deepcopy(adj)
            item._refresh_display()
        n = len(self._items)
        self.status_label.setStyleSheet("color:#27AE60; font-size:12px; font-weight:bold;")
        self.status_label.setText(f"✔  {n}개 파일에 보정값 적용됨")
        QTimer.singleShot(2500, self._update_status_label)
        QTimer.singleShot(2500, lambda: self.status_label.setStyleSheet("color:#888888; font-size:12px;"))

    def _reset(self, checked=False, *, project_switch=False):
        if not project_switch and hasattr(self, "projects"):
            if self._converting or not self.projects.confirm_leave():
                return
        if self._converting and self._worker:
            self._cancelled = True          # 리셋에 의한 중단 → 폴더 자동 열기 생략
            self._worker.abort()

        # 실행 중인 워커 시그널 차단 (캐시 클리어 후 emit 방지)
        if self._adj_base_loader and self._adj_base_loader.isRunning():
            try: self._adj_base_loader.loaded.disconnect()
            except Exception: pass
            try: self._adj_base_loader.failed.disconnect()
            except Exception: pass
        if self._adj_preview_worker and self._adj_preview_worker.isRunning():
            try: self._adj_preview_worker.loaded.disconnect()
            except Exception: pass

        self._adj_timer.stop()
        self._exit_edit_mode(restore_preview=False)   # 리셋 시 미리보기 복원 생략
        self.file_list.blockSignals(True)
        try:
            self.file_list.clear()
            self._items.clear()
        finally:
            self.file_list.blockSignals(False)
        self._adj_base_cache.clear()
        self.progress_bar.reset()
        self.preview.cancel()              # 진행 중인 로더 취소
        self.preview._show_placeholder()   # 이제 스레드가 완료돼도 덮어쓰지 않음
        self.crop_editor.clear_image()
        self._center_stack.setCurrentIndex(0)
        self._update_status_label()

        if not project_switch and hasattr(self, "projects"):
            self.projects.reset()

    # -----------------------------------------------------------------------
    # 보정 모드
    # -----------------------------------------------------------------------

    def _toggle_edit_mode(self):
        """하단 보정 버튼 토글 — 보정 중이면 출력 모드로, 아니면 보정 모드로."""
        if self._right_stack.currentIndex() == 1:
            self._set_mode("output")
        else:
            self._set_mode("edit")

    # ── 모드 전환 (출력 설정 / 보정 / 크기 조절) ───────────────
    def _set_mode(self, mode: str):
        try:
            self._set_mode_impl(mode)
        except Exception:
            import traceback
            QMessageBox.critical(self, "오류 (모드 전환)",
                                 "문제가 발생했습니다:\n\n" + traceback.format_exc()[:3000])

    def _set_mode_impl(self, mode: str):
        # 보정 모드 진입은 선택 파일이 있어야 함
        if mode == "edit":
            sel = self.file_list.selectedItems()
            if not (sel and isinstance(sel[0], FileItem)) or self._converting:
                mode = "output"

        for k, b in self._mode_btns.items():
            b.setChecked(k == mode)

        if mode == "edit":
            self.options.set_mode("output")
            self._center_stack.setCurrentIndex(0)   # 보정 미리보기는 일반 preview에 표시
            self._enter_edit_mode()
            return

        # output / size 공통: 보정 중이면 빠져나오기
        if self._right_stack.currentIndex() == 1:
            self._exit_edit_mode()
        self._right_stack.setCurrentIndex(0)
        if mode == "size":
            self.options.set_mode("size")
            # 크롭 '사용'을 체크했을 때만 크롭 편집기(박스)를 보여준다.
            # 체크 안 했으면 리사이즈·DPI만 쓰는 것이므로 일반 미리보기를 유지한다.
            if self.options.get_crop_enabled():
                self._center_stack.setCurrentIndex(1)
                # setCurrentIndex 직후 즉시 호출하면 위젯 크기가 0×0이라 아무것도 안 그려짐.
                # 이벤트 루프 한 틱 후 실행해야 레이아웃이 완료된 상태에서 그릴 수 있다.
                QTimer.singleShot(0, self._refresh_crop_editor)
            else:
                self._center_stack.setCurrentIndex(0)
        else:
            self.options.set_mode("output")
            self._center_stack.setCurrentIndex(0)

    # ── 크롭 편집기 ───────────────────────────────────
    def _refresh_crop_editor(self):
        try:
            sel = self.file_list.selectedItems()
            if not (sel and isinstance(sel[0], FileItem)):
                self.crop_editor.clear_image()
                return
            item = sel[0]

            # 캐시 히트 여부와 무관하게 '진짜' 원본 해상도를 먼저 확보한다.
            # (이전에는 캐시 경로에서 set_original_size 가 호출되지 않아 크롭이 1×1로 붕괴됨)
            self._capture_original_size(item.path)

            # ── 1) PIL 캐시가 있으면 바로 표시 ──────────────────────────
            base = self._adj_base_cache.get(item.path)
            if base is not None:
                self._update_crop_editor_image(base)
                return

            # ── 2) 일반 이미지: QImage(path) 즉시 로드 → QPixmap 변환 ──
            #    (썸네일 로더와 동일한 경로 — 한글 경로·대용량 JPG 모두 안정)
            ext = Path(item.path).suffix.lower()
            if ext in NORMAL_EXTENSIONS:
                qimg = QImage(item.path)
                if not qimg.isNull():
                    # 표시용으로 최대 1400px 축소
                    mw, mh = qimg.width(), qimg.height()
                    longest = max(mw, mh) if max(mw, mh) > 0 else 1
                    if longest > 1400:
                        qimg = qimg.scaled(
                            int(mw * 1400 / longest), int(mh * 1400 / longest),
                            Qt.KeepAspectRatio, Qt.SmoothTransformation,
                        )
                    pm = QPixmap.fromImage(qimg)
                    # 원본 해상도는 스케일 전 qimg 기준 (원본 파일 크기)
                    orig_w = int(mw); orig_h = int(mh)
                    self.options.set_original_size(orig_w, orig_h)
                    self._crop_src_size = (pm.width(), pm.height())
                    tw, th = self.options.get_crop_size()
                    rect = self.options.get_crop_rect()
                    ar = (tw / th) if th else 1.0
                    if not rect:
                        rect = centered_aspect_rect((pm.width(), pm.height()), ar)
                    self.crop_editor.set_pixmap(pm)
                    self.crop_editor.set_target_aspect(ar)
                    self.crop_editor.set_rect(rect)
                    self._start_adj_base_load(item.path)   # PIL 품질로 백그라운드 업데이트 예약
                    return

            # ── 3) RAW 등: 비동기 PIL 로드 (원본 크기는 위에서 이미 캡처함) ──
            self.crop_editor.clear_image()
            self._start_adj_base_load(item.path)
        except Exception:
            import traceback
            QMessageBox.critical(self, "오류 (크롭 편집기)",
                                 "문제가 발생했습니다:\n\n" + traceback.format_exc()[:3000])

    def _capture_original_size(self, path: str):
        """선택 사진의 '진짜' 원본 해상도를 options 에 기록한다.
        크롭 편집기가 캐시 히트로 그려질 때도 비율/‘원본으로’가 올바르게 동작하도록
        _refresh_crop_editor 최상단에서 호출한다. 비율 변경마다 호출되므로 경로별로
        캐시해 RAW 파일을 매번 다시 열지 않는다."""
        cache = getattr(self, "_orig_size_cache", None)
        if cache is None:
            cache = self._orig_size_cache = {}
        if path in cache:
            w, h = cache[path]
            self.options.set_original_size(w, h)
            return
        ext = Path(path).suffix.lower()
        try:
            w = h = 0
            if ext in _RAW_EXTS:
                import rawpy
                with rawpy.imread(path) as rp:
                    s = rp.sizes
                    w = int(getattr(s, "width", 0) or 0)
                    h = int(getattr(s, "height", 0) or 0)
                    if w <= 0 or h <= 0:        # 폴백: 센서 배열 모양
                        rh, rw = rp.raw_image.shape[:2]
                        w, h = int(rw), int(rh)
            else:
                qimg = QImage(path)
                if not qimg.isNull():
                    w, h = qimg.width(), qimg.height()
            if w > 0 and h > 0:
                cache[path] = (w, h)
                self.options.set_original_size(w, h)
        except Exception:
            pass

    def _update_crop_editor_image(self, base):
        if base is None:
            self.crop_editor.clear_image()
            return
        tw, th = self.options.get_crop_size()
        rect = self.options.get_crop_rect()
        ar = (tw / th) if th else 1.0
        if not rect:
            rect = centered_aspect_rect(base.size, ar)
        self._crop_src_size = base.size
        self.crop_editor.set_image(base)
        self.crop_editor.set_target_aspect(ar)
        self.crop_editor.set_rect(rect)

    def _on_crop_rect_changed(self, rect):
        """크롭 박스 드래그 → rect만 저장. 스핀박스(출력 픽셀 크기)는 건드리지 않음."""
        self.options.set_crop_rect(rect)

    def _on_crop_dims_changed(self):
        """크기/비율 변경 → 저장된 박스 초기화 후 편집기 갱신."""
        self.options.set_crop_rect(None)
        if self._center_stack.currentIndex() == 1:
            self._refresh_crop_editor()

    def _on_crop_enabled_toggled(self, enabled: bool):
        """크롭 사용 체크 변화에 따라 중앙 표시를 전환한다.
        - 켜면: [크기 조절] 탭 + 크롭 편집기(박스) 표시.
        - 끄면: 크기 조절 탭에 있으면 일반 미리보기로 되돌림(박스 숨김)."""
        if self._converting:
            return
        if enabled:
            self._set_mode("size")   # size 분기에서 get_crop_enabled()=True 라 편집기 표시
        elif self._mode_btns["size"].isChecked():
            # 크기 조절 탭에서 크롭만 끈 경우 — 박스를 치우고 일반 미리보기 복귀
            self._center_stack.setCurrentIndex(0)
            self._reload_current_preview()

    def _enter_edit_mode(self):
        selected = self.file_list.selectedItems()
        if not selected:
            return
        item = selected[0]
        if not isinstance(item, FileItem):
            return

        self._edit_item = item
        self.edit_panel.load(item.path, item.adjustments)
        self._right_stack.setCurrentIndex(1)

        # base 이미지 로드 (캐시 없으면)
        self._start_adj_base_load(item.path)

    def _on_preview_compare(self, show_before: bool):
        """compare 버튼 토글 → 원본 or 보정 후 미리보기 전환."""
        if not self._edit_item:
            return
        if show_before:
            base = self._adj_base_cache.get(self._edit_item.path)
            if base is not None:
                self.preview.set_pixmap_direct(_pil_to_qpixmap(base))
            # base 미로드 시 현재 미리보기 유지
        else:
            self._fire_adj_preview()

    def _exit_edit_mode(self, restore_preview: bool = True):
        if self._edit_item:
            self._edit_item.adjustments = self.edit_panel.get_adjustments()
            self._edit_item._refresh_display()  # ✎ 마크 갱신
            self._edit_item = None
        self._adj_timer.stop()
        self.edit_panel.reset_compare()
        self._right_stack.setCurrentIndex(0)

        if restore_preview:
            selected = self.file_list.selectedItems()
            if selected and isinstance(selected[0], FileItem):
                item = selected[0]
                # 보정값이 있고 base 캐시가 있으면 보정된 미리보기 유지
                if item.adjustments and item.path in self._adj_base_cache:
                    base = self._adj_base_cache[item.path]
                    if self._adj_preview_worker and self._adj_preview_worker.isRunning():
                        try:
                            self._adj_preview_worker.loaded.disconnect()
                        except Exception:
                            pass
                    self._adj_preview_worker = AdjPreviewWorker(base, item.adjustments)
                    self._adj_preview_worker.loaded.connect(self.preview.set_pixmap_direct)
                    self._retain(self._adj_preview_worker)
                    self._adj_preview_worker.start()
                else:
                    # 보정값 없거나 캐시 없으면 원본 로드
                    self.preview.load(item.path, bright=self._current_bright())

    def _start_adj_base_load(self, path: str):
        if path in self._adj_base_cache:
            # 이미 캐시 있으면 바로 미리보기 적용
            self._fire_adj_preview()
            return
        if self._adj_base_loader and self._adj_base_loader.isRunning():
            self._adj_base_loader.loaded.disconnect()
            self._adj_base_loader.failed.disconnect()
            self._adj_base_loader.quit()

        self._adj_base_loader = AdjBaseLoader(path, bright=self._current_bright())
        self._adj_base_loader.loaded.connect(self._on_adj_base_loaded)
        self._adj_base_loader.failed.connect(self._on_adj_base_failed)
        self._retain(self._adj_base_loader)
        self._adj_base_loader.start()

    def _on_adj_base_loaded(self, path: str, img):
        # 캐시 크기 제한
        if len(self._adj_base_cache) >= _ADJ_CACHE_MAX:
            oldest = next(iter(self._adj_base_cache))
            del self._adj_base_cache[oldest]
        self._adj_base_cache[path] = img

        # 지금도 같은 파일을 편집 중이면 미리보기 갱신
        if self._edit_item and self._edit_item.path == path:
            self._fire_adj_preview()

        # 크기 조절(크롭) 모드이고 현재 선택 파일이면 크롭 편집기 갱신
        if self._center_stack.currentIndex() == 1:
            sel = self.file_list.selectedItems()
            if sel and isinstance(sel[0], FileItem) and sel[0].path == path:
                self._update_crop_editor_image(img)

    def _on_adj_base_failed(self, path: str):
        pass  # 로드 실패 시 원본 미리보기 유지

    def _on_adj_changed(self):
        """슬라이더 변경 시: 보정값 저장 + 150 ms debounce로 미리보기 갱신.
        _refresh_display는 여기서 호출하지 않음 — 드래그마다 썸네일 재로드 방지."""
        if self._edit_item:
            self._edit_item.adjustments = self.edit_panel.get_adjustments()
        self._adj_timer.start(150)

    def _fire_adj_preview(self):
        if not self._edit_item:
            return
        path = self._edit_item.path
        base = self._adj_base_cache.get(path)
        if base is None:
            return

        adj = self._edit_item.adjustments

        # 이전 워커가 실행 중이면 결과를 무시하게 disconnect
        if self._adj_preview_worker and self._adj_preview_worker.isRunning():
            try:
                self._adj_preview_worker.loaded.disconnect()
            except Exception:
                pass

        self._adj_preview_worker = AdjPreviewWorker(base, adj)
        self._adj_preview_worker.loaded.connect(self.preview.set_pixmap_direct)
        self._retain(self._adj_preview_worker)
        self._adj_preview_worker.start()

    # -----------------------------------------------------------------------
    # 선택 변경
    # -----------------------------------------------------------------------

    def _on_selection_change(self):
        selected = self.file_list.selectedItems()
        if not selected or not isinstance(selected[0], FileItem):
            self.edit_btn.setEnabled(False)
            return

        item = selected[0]
        self.edit_btn.setEnabled(not self._converting)

        if self._right_stack.currentIndex() == 1:
            # 보정 모드 중: 이전 파일 저장 후 새 파일로 전환
            if self._edit_item and self._edit_item is not item:
                self._edit_item.adjustments = self.edit_panel.get_adjustments()
                self._edit_item._refresh_display()
                if self._edit_item.adjustments:
                    self._flash_status("✎ 이전 파일 보정값이 자동 저장되었습니다")
            self._edit_item = item
            self.edit_panel.load(item.path, item.adjustments)
            self._start_adj_base_load(item.path)
        elif self._center_stack.currentIndex() == 1:
            # 크기 조절(크롭) 모드: 새 사진을 크롭 편집기에 로드
            self._refresh_crop_editor()
        else:
            self.preview.load(item.path, bright=self._current_bright())
            # 보정 모드 진입 전 미리 base 이미지 로드 (캐시 없을 때만)
            if item.path not in self._adj_base_cache:
                self._start_adj_base_load(item.path)

    # -----------------------------------------------------------------------
    # 변환
    # -----------------------------------------------------------------------

    def _on_convert_clicked(self):
        """변환 버튼: 평소엔 변환 시작, 변환 중엔 취소."""
        if self._converting:
            self._cancel_convert()
        else:
            self._start_convert()

    def _cancel_convert(self):
        """진행 중인 변환을 취소."""
        if self._worker and self._worker.isRunning():
            self._cancelled = True
            self._worker.abort()
            self.convert_btn.setEnabled(False)   # 중복 클릭 방지 (all_done 에서 복원)
            self.status_label.setStyleSheet("color:#E67E22; font-size:12px; font-weight:bold;")
            self.status_label.setText("변환을 취소하는 중…")

    def _restore_convert_btn(self):
        """변환 버튼을 기본(시작) 상태로 복원."""
        self.convert_btn.setText(self._lang["convert_btn"])
        self.convert_btn.setStyleSheet(self._primary_btn_style())
        self.convert_btn.setEnabled(True)

    def _start_convert(self):
        if hasattr(self, "projects") and self.projects.busy:
            QMessageBox.information(self, "프로젝트 저장 중", "프로젝트 저장이 끝난 뒤 변환하세요.")
            return
        if not self._items:
            QMessageBox.information(self, self._lang["app_title"], self._lang["no_files"])
            return
        if self._converting:
            return

        out_folder    = self.options.get_output_folder()
        if hasattr(self, "projects"):
            out_folder = self.projects.export_folder(out_folder)
            if out_folder is None:
                return
        cw, ch        = self.options.get_custom_size()
        out_format    = self.options.get_format()
        resize_mode   = self.options.get_resize_mode()

        # 커스텀 크기가 비정상적으로 작거나 큰 경우 확인 (UX #4)
        if resize_mode == "custom":
            bad_w = cw < 16 or cw > 20000
            bad_h = bool(ch) and (ch < 16 or ch > 20000)
            if bad_w or bad_h:
                dim = f"{cw}px" if not ch else f"{cw}×{ch}px"
                reply = QMessageBox.question(
                    self, "크기 확인",
                    f"지정한 출력 크기({dim})가 일반적인 범위를 벗어났습니다.\n"
                    "결과가 너무 작거나 클 수 있습니다. 그대로 변환할까요?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return

        # PNG/TIFF는 무압축에 가까워 용량이 큼 — 대량 변환 시 사전 경고
        if out_format in ("PNG", "TIFF") and len(self._items) >= 20:
            reply = QMessageBox.question(
                self, "용량 주의",
                f"{out_format} 형식은 압축이 거의 없어 파일 용량이 큽니다.\n"
                f"{len(self._items)}개를 변환하면 디스크를 많이 사용할 수 있습니다.\n\n"
                "그래도 계속하시겠습니까?\n"
                "(용량을 줄이려면 JPEG 또는 WebP 형식을 권장합니다.)",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        opts = {
            "out_dir":       out_folder,
            "out_format":    out_format,
            "jpeg_quality":  100,
            "resize_mode":   resize_mode,
            "custom_w":      cw,
            "custom_h":      ch,
            "exif_mode":     self.options.get_exif_mode(),
            "on_collision":  self.options.get_collision_mode(),
            "rename_suffix": self.options.get_rename_suffix(),
            "crop_enabled":  self.options.get_crop_enabled(),
            "crop_landscape": self.options.get_crop_landscape(),
            "crop_portrait":  self.options.get_crop_portrait(),
            "crop_rect_landscape": self.options.get_crop_rect_landscape(),
            "crop_rect_portrait":  self.options.get_crop_rect_portrait(),
            "dpi":            self.options.get_dpi(),
            "auto_bright":    self.options.get_auto_bright(),
        }

        if out_folder:
            self._settings.setValue("last_output_folder", out_folder)
        self._save_ui_settings()   # 마지막 사용 옵션 기억

        # 파일별 보정값 포함
        jobs = [
            {"path": item.path, "adjustments": item.adjustments or None}
            for item in self._items
        ]

        for item in self._items:
            item.set_status("waiting")

        # 완료 후 자동으로 열 출력 폴더 집합 결정
        # (원본과 같은 위치면 각 원본 폴더가 출력 폴더 — 여러 곳일 수 있음)
        if out_folder:
            self._out_dirs = {out_folder}
        else:
            self._out_dirs = {str(Path(j["path"]).parent) for j in jobs}

        self._converting = True
        self._cancelled  = False

        # 변환 버튼을 '취소' 모드로 전환 (진행 중 중단 가능)
        self.convert_btn.setText("■  취소")
        self.convert_btn.setStyleSheet(self._cancel_btn_style())
        self.convert_btn.setEnabled(True)
        self.edit_btn.setEnabled(False)
        # 변환 중에는 목록 조작을 막아 워커 인덱스-목록 불일치를 방지
        self.add_btn.setEnabled(False)
        self.add_files_btn.setEnabled(False)
        self.remove_btn.setEnabled(False)
        self.remove_done_btn.setEnabled(False)
        self.reset_btn.setEnabled(False)
        self.progress_bar.reset()
        self._t_start     = time.time()
        self._done_count  = 0
        self._error_count = 0
        self._skip_count  = 0
        self._total       = len(jobs)

        self._worker = ConvertWorker(jobs, opts)
        self._worker.progress_file.connect(self._on_file_progress)
        self._worker.file_done.connect(self._on_file_done)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.start()

        # 첫 진행 표시까지의 공백 동안 멈춘 것처럼 보이지 않게 안내 (RAW 디코딩 지연)
        has_raw = any(Path(j["path"]).suffix.lower() in _RAW_EXTS for j in jobs)
        self.status_label.setStyleSheet("color:#D35400; font-size:12px; font-weight:bold;")
        self.status_label.setText(
            "변환 중… (RAW는 디코딩에 시간이 걸릴 수 있습니다)" if has_raw else "변환 중…"
        )

    def _on_file_progress(self, idx: int, pct: int, elapsed: float):
        if idx < len(self._items):
            self._items[idx].set_status("converting")
        files_done = self._done_count + self._error_count + self._skip_count
        overall    = int(((files_done + pct / 100) / self._total) * 100)
        eta_str    = ""
        if elapsed > 0 and overall > 0:
            remaining = max(0, elapsed / (overall / 100) - elapsed)
            eta_str = f"~{int(remaining)}s" if remaining < 60 else f"~{int(remaining/60)}m {int(remaining%60)}s"
        self.progress_bar.set_progress(overall, eta_str)
        # 진행 중 실시간 카운트 — 멈춘 듯한 오해 방지 (취소 중에는 덮어쓰지 않음)
        if not getattr(self, "_cancelled", False):
            self.status_label.setStyleSheet("color:#D35400; font-size:12px; font-weight:bold;")
            self.status_label.setText(f"변환 중…  {files_done}/{self._total}")

    def _on_file_done(self, idx: int, status: str, msg: str):
        if idx < len(self._items):
            self._items[idx].set_status(status, msg)
        if status == "done":
            self._done_count += 1
        elif status == "skipped":
            self._skip_count += 1
        else:
            self._error_count += 1
        self._update_status_label()

    def _on_all_done(self, done: int, errors: int):
        self._converting = False
        self._restore_convert_btn()
        # 변환 중 비활성화했던 목록 조작 버튼 복원
        self.add_btn.setEnabled(True)
        self.add_files_btn.setEnabled(True)
        self.remove_btn.setEnabled(True)
        self.remove_done_btn.setEnabled(True)
        self.reset_btn.setEnabled(True)
        cancelled = getattr(self, "_cancelled", False)

        selected = self.file_list.selectedItems()
        self.edit_btn.setEnabled(bool(selected and isinstance(selected[0], FileItem)))
        self.progress_bar.set_progress(100, "")

        # 취소된 경우: 취소 안내만 표시하고 폴더 자동 열기 생략
        if cancelled:
            self.status_label.setStyleSheet("color:#E67E22; font-size:12px; font-weight:bold;")
            self.status_label.setText(f"변환이 취소되었습니다 (완료 {done}개)")
            QTimer.singleShot(3000, lambda: self.status_label.setStyleSheet("color:#888888; font-size:12px;"))
            return

        # 완료 메시지 — 실패/건너뜀을 구분
        skipped = getattr(self, "_skip_count", 0)
        msg = self._lang["convert_done_msg"].format(done=done, total=self._total)
        if skipped > 0:
            msg += f" · 건너뜀 {skipped}개"
        color = "#27AE60" if errors == 0 else "#E74C3C"
        self.status_label.setStyleSheet(f"color:{color}; font-size:12px; font-weight:bold;")

        # 변환 성공 파일이 있으면 출력 폴더 자동 열기 (UX #2)
        out_dirs = sorted(d for d in getattr(self, "_out_dirs", set()) if os.path.isdir(d))
        if done > 0:
            if len(out_dirs) == 1:
                platform_utils.open_in_file_manager(out_dirs[0])   # 탐색기/Finder로 열기
            elif len(out_dirs) > 1:
                # 결과물이 여러 원본 폴더에 흩어진 경우: 자동 열기 대신 안내
                QMessageBox.information(
                    self, "변환 완료",
                    f"변환된 {done}개 파일이 각 원본 폴더에 저장되었습니다.\n"
                    f"(총 {len(out_dirs)}개 폴더)\n\n"
                    "한 곳에 모으려면 옵션에서 출력 폴더를 지정해 변환하세요."
                )

        if errors > 0:
            error_items = [
                f"• {Path(item.path).name}: {item.error_msg}"
                for item in self._items if item.status == "error"
            ]
            if error_items:
                detail = "\n".join(error_items[:10])
                if len(error_items) > 10:
                    detail += f"\n… 외 {len(error_items)-10}개"
                QMessageBox.warning(
                    self, "일부 파일 변환 실패",
                    f"다음 파일을 변환하지 못했습니다:\n\n{detail}\n\n"
                    "파일이 손상되었거나, 저장 공간이 부족하거나,\n다른 프로그램이 사용 중일 수 있습니다.",
                )

        self.status_label.setText(msg)
        QTimer.singleShot(3000, lambda: self.status_label.setStyleSheet("color:#888888; font-size:12px;"))

    # -----------------------------------------------------------------------
    # 공통 헬퍼
    # -----------------------------------------------------------------------

    def _retain(self, thread):
        """실행 중인 QThread 참조를 finished 까지 유지(조기 GC로 인한 크래시 방지)."""
        if thread is None:
            return
        self._retained_threads.add(thread)
        thread.finished.connect(lambda t=thread: self._retained_threads.discard(t))

    def closeEvent(self, event):
        """창 종료 시 진행 중인 모든 워커 스레드를 안전하게 정리."""
        if hasattr(self, "projects") and not self.projects.confirm_leave():
            event.ignore()
            return
        self._save_ui_settings()   # 종료 시점의 옵션도 기억

        # 변환 워커: 중단 신호 후 종료 대기 (in-flight 파일은 마무리 → 손상 방지)
        if self._worker and self._worker.isRunning():
            self._cancelled = True
            self._worker.abort()
            if not self._worker.wait(10000):
                event.ignore()
                return

        # 미리보기·보정 로더 스레드 종료 대기
        threads = [self._adj_base_loader, self._adj_preview_worker,
                   getattr(self.preview, "_loader", None)]
        threads += list(self._retained_threads)
        for th in threads:
            try:
                if th is not None and th.isRunning():
                    if not th.wait(3000):
                        event.ignore()
                        return
            except RuntimeError:
                pass  # 이미 삭제된 객체
        if hasattr(self, "projects"):
            self.projects.shutdown()
        super().closeEvent(event)

    def _update_status_label(self):
        total = len(self._items)
        done  = sum(1 for i in self._items if i.status == "done")
        error = sum(1 for i in self._items if i.status == "error")
        if total == 0:
            self.status_label.setText(self._lang["status_ready"])
        else:
            self.status_label.setText(
                self._lang["status_summary"].format(total=total, done=done, error=error)
            )

    def _load_lang_file(self, key: str) -> dict:
        """언어 JSON 로드 — frozen(exe)에서도 안전하게 BASE_DIR 기준으로 읽음."""
        import json
        lang_file = Path(BASE_DIR) / "i18n" / f"lang_{key}.json"
        if not lang_file.exists():
            lang_file = Path(BASE_DIR) / "i18n" / "lang_ko.json"
        with open(lang_file, encoding="utf-8") as f:
            return json.load(f)

    def _on_lang_change(self, lang_name: str):
        key = "ko" if lang_name == "한국어" else "en"
        if key == self._lang_key:
            return
        try:
            new_lang = self._load_lang_file(key)
        except Exception:
            return  # 로드 실패 시 기존 언어 유지 (크래시 방지)
        self._lang_key = key
        self._lang     = new_lang
        self._settings.setValue("language", key)
        self.options.update_lang(self._lang)
        for item in self._items:
            item.update_lang(self._lang)
        self._update_status_label()

    def _save_ui_settings(self):
        """마지막 사용 옵션을 JSON 문자열로 저장."""
        import json
        try:
            self._settings.setValue("ui_options", json.dumps(self.options.get_settings()))
        except Exception:
            pass

    def _restore_settings(self):
        folder = self._settings.value("last_output_folder", "")
        if folder and os.path.isdir(folder):
            self.options.folder_edit.setText(folder)
            self.options.same_src_cb.setChecked(False)

        # 마지막 사용 옵션(형식·리사이즈·EXIF·충돌처리 등) 복원
        import json
        raw = self._settings.value("ui_options", "")
        if raw:
            try:
                self.options.apply_settings(json.loads(raw))
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # 스타일
    # -----------------------------------------------------------------------

    def _apply_dark_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.Window,          QColor("#111111"))
        palette.setColor(QPalette.WindowText,      QColor("#CCCCCC"))
        palette.setColor(QPalette.Base,            QColor("#1A1A1A"))
        palette.setColor(QPalette.AlternateBase,   QColor("#222222"))
        palette.setColor(QPalette.Text,            QColor("#CCCCCC"))
        palette.setColor(QPalette.Button,          QColor("#1A1A1A"))
        palette.setColor(QPalette.ButtonText,      QColor("#CCCCCC"))
        palette.setColor(QPalette.Highlight,       QColor("#D35400"))
        palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
        self.setPalette(palette)

        # Windows 제목 표시줄도 다크로 — OS가 라이트 모드여도 흰 제목줄이 안 나오게.
        self._apply_dark_titlebar()
        # 표시 직후 한 번 더 적용(첫 페인트 전에 확실히 반영되도록).
        QTimer.singleShot(0, self._apply_dark_titlebar)

    def _apply_dark_titlebar(self):
        """제목 표시줄 다크 강제 — 크로스플랫폼 구현은 core.platform_utils 에 위임
        (Windows만 동작, macOS/Linux는 no-op)."""
        platform_utils.apply_dark_titlebar(self)

    def _primary_btn_style(self) -> str:
        return """
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #C0390B, stop:1 #D35400);
                color:#FFFFFF; border:none; border-radius:5px;
                font-size:13px; font-weight:bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #D35400, stop:1 #E67E22);
            }
            QPushButton:disabled { background:#333333; color:#666666; }
        """

    def _current_bright(self) -> float:
        return AUTO_BRIGHT_FACTOR if self.options.get_auto_bright() else 1.0

    def _on_auto_bright_changed(self, _checked: bool):
        # 자동 밝기가 바뀌면 RAW 디코딩 결과가 달라지므로 base 캐시를 비우고
        # 현재 선택 파일 미리보기를 새 밝기로 다시 디코딩한다.
        # (캐시는 path만 키로 쓰므로 밝기 변경 시 그대로 두면 옛 밝기 이미지가 재사용됨)
        self._adj_base_cache.clear()
        self._reload_current_preview()

    def _reload_current_preview(self):
        if self.file_list.selectedItems():
            self._on_selection_change()

    def _tab_btn_style(self) -> str:
        # 파일 탭 스타일 — 선택 탭이 아래 패널(#171717)과 색·테두리로 연결됨
        return """
            QPushButton{
                background:#141414; color:#888888;
                border:1px solid #2E2E2E; border-bottom:none;
                border-top-left-radius:6px; border-top-right-radius:6px;
                font-size:11px; font-weight:bold; padding:0 2px; margin-top:5px;
            }
            QPushButton:hover{ color:#D35400; }
            QPushButton:checked{
                background:#171717; color:#D35400;
                border:1px solid #2E2E2E; border-bottom:none; margin-top:0px;
            }
        """

    def _cancel_btn_style(self) -> str:
        return """
            QPushButton {
                background:#3A1212; color:#FF6B6B;
                border:1px solid #7A2222; border-radius:5px;
                font-size:13px; font-weight:bold;
            }
            QPushButton:hover { background:#511919; border-color:#FF6B6B; }
            QPushButton:disabled { background:#333333; color:#666666; }
        """

    def _outline_btn_style(self) -> str:
        return """
            QPushButton {
                background:transparent; color:#AAAAAA;
                border:1px solid #444444; border-radius:5px; font-size:12px;
            }
            QPushButton:hover { border-color:#D35400; color:#D35400; }
            QPushButton:disabled { color:#444444; border-color:#2A2A2A; }
        """

    def _small_btn(self, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(28)
        btn.setStyleSheet("""
            QPushButton {
                background:#1E1E1E; color:#AAAAAA;
                border:1px solid #333333; border-radius:3px;
                font-size:11px; padding:0 8px;
            }
            QPushButton:hover { border-color:#D35400; color:#D35400; }
        """)
        return btn

    def _center_window(self):
        from PyQt5.QtWidgets import QDesktopWidget
        screen = QDesktopWidget().availableGeometry()
        size   = self.geometry()
        self.move(
            (screen.width()  - size.width())  // 2,
            (screen.height() - size.height()) // 2,
        )

    def _show_about(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("About RawBaker")
        dlg.setFixedSize(360, 345)
        dlg.setStyleSheet("background:#111111; color:#CCCCCC;")

        layout = QVBoxLayout(dlg)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        banner = QWidget()
        banner.setFixedHeight(90)
        banner.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #C0390B, stop:1 #D35400);"
        )
        b_lay = QHBoxLayout(banner)
        b_lay.setContentsMargins(20, 0, 20, 0)

        logo_path = Path(BASE_DIR) / "assets" / "logo.png"
        if logo_path.exists():
            pm = QPixmap(str(logo_path)).scaled(60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            ll = QLabel(); ll.setPixmap(pm)
            b_lay.addWidget(ll); b_lay.addSpacing(12)

        nc = QVBoxLayout()
        an = QLabel("RawBaker"); an.setFont(QFont("Rajdhani", 22, QFont.Bold))
        an.setStyleSheet("color:#FFFFFF;")
        sn = QLabel("Digital Kiln"); sn.setStyleSheet("color:rgba(255,255,255,0.6); font-size:11px;")
        nc.addWidget(an); nc.addWidget(sn)
        b_lay.addLayout(nc); b_lay.addStretch()
        layout.addWidget(banner)

        body = QWidget(); body.setStyleSheet("background:#111111;")
        b2 = QVBoxLayout(body)
        b2.setContentsMargins(28, 24, 28, 16); b2.setSpacing(10)

        def info_row(lbl, val, vc="#CCCCCC"):
            h = QHBoxLayout()
            l = QLabel(lbl); l.setStyleSheet("color:#555555; font-size:11px;"); l.setFixedWidth(70)
            v = QLabel(val); v.setStyleSheet(f"color:{vc}; font-size:12px; font-weight:bold;")
            h.addWidget(l); h.addWidget(v); h.addStretch()
            return h

        def yt_row():
            """유튜브 링크 행 — 클릭하면 브라우저에서 열림."""
            import webbrowser
            h = QHBoxLayout()
            lbl = QLabel("유튜브")
            lbl.setStyleSheet("color:#555555; font-size:11px;")
            lbl.setFixedWidth(70)
            link = QLabel(
                '<a href="https://www.youtube.com/@unknown8563" '
                'style="color:#FF4444; text-decoration:none; font-size:12px; font-weight:bold;">'
                '▶  @unknown8563</a>'
            )
            link.setOpenExternalLinks(True)
            link.setToolTip("https://www.youtube.com/@unknown8563")
            h.addWidget(lbl); h.addWidget(link); h.addStretch()
            return h

        b2.addLayout(info_row("프로젝트", "PROJECT 02", "#D35400"))
        b2.addLayout(info_row("제작",    version.COMPANY))
        b2.addLayout(info_row("연도",    version.YEAR))
        b2.addLayout(info_row("버전",    version.VERSION_DISPLAY))
        b2.addLayout(yt_row())
        b2.addLayout(info_row("엔진",    "rawpy · Pillow · OpenCV"))
        b2.addLayout(info_row("플랫폼",  platform_utils.platform_label()))
        b2.addSpacing(8)
        desc = QLabel("RAW 파일 및 일반 이미지를\n원하는 형식으로 변환하는 포터블 프로그램.")
        desc.setStyleSheet("color:#555555; font-size:11px;"); desc.setWordWrap(True)
        b2.addWidget(desc); b2.addStretch()
        layout.addWidget(body, stretch=1)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok)
        btn_box.setStyleSheet(
            "QPushButton { background:#D35400; color:#fff; border:none;"
            " border-radius:4px; padding:6px 24px; font-size:12px; }"
            "QPushButton:hover { background:#E67E22; }"
        )
        btn_box.accepted.connect(dlg.accept)
        cb = QWidget(); cb.setStyleSheet("background:#0D0D0D; border-top:1px solid #1E1E1E;")
        cl = QHBoxLayout(cb); cl.setContentsMargins(16, 8, 16, 8)
        cl.addStretch(); cl.addWidget(btn_box)
        layout.addWidget(cb)

        dlg.exec_()
