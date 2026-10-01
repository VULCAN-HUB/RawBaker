"""Shared neutral workspace styling and precise, keyboard-accessible sliders."""
from pathlib import Path
from PyQt5.QtCore import Qt, QByteArray, QSize
from PyQt5.QtGui import QIcon, QPixmap, QPainter
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QAbstractSpinBox

STYLE = """QWidget { background:#1b1b1e; color:#c6c6cc; font-size:11px; font-family:"Malgun Gothic"; }
QMainWindow { background:#171717; }
QLabel { background:transparent; }
QPushButton { background:#303030; border:1px solid transparent; border-radius:4px; padding:3px 7px; }
QPushButton:hover { background:#3b3b3b; }
QPushButton:pressed,QPushButton:checked { background:#3d394b; color:#ece8f5; }
QPushButton:focus { border:1px solid #81768f; }
QPushButton:disabled { color:#777; background:#262626; }
QPushButton[primary="true"] { background:#d2cfe1; color:#17161c; font-weight:600; }
QPushButton[primary="true"]:hover { background:#ebe8f4; }
QPushButton[quiet="true"] { background:transparent; color:#aaa; }
QPushButton[quiet="true"]:hover { background:#343434; color:#eee; }
QLineEdit,QSpinBox,QDoubleSpinBox,QComboBox,QTextEdit { background:#292929; border:1px solid #393939; border-radius:4px; padding:2px 5px; selection-background-color:#4b455d; }
QLineEdit:focus,QSpinBox:focus,QDoubleSpinBox:focus,QTextEdit:focus { border-color:#81768f; }
QComboBox::drop-down { border:0; width:20px; }
QComboBox QAbstractItemView { background:#303030; selection-background-color:#3d394b; }
QListWidget { background:#1c1c1c; border:0; outline:0; }
QListWidget::item { padding:4px; border:1px solid transparent; border-radius:4px; }
QListWidget::item:hover { background:#2c2c2c; }
QListWidget::item:selected { background:#3c3949; border-color:#565164; color:#efedf5; }
QTabWidget::pane { border:0; }
QTabBar::tab { background:#202020; color:#929292; padding:4px 12px; border-bottom:2px solid transparent; }
QTabBar::tab:selected { color:#efedf5; border-bottom:2px solid #d2cfe1; }
QTabBar::tab:hover { color:#eee; background:#292929; }
QGroupBox { border:0; border-top:1px solid #393939; margin-top:16px; padding-top:16px; font-weight:600; }
QGroupBox::title { subcontrol-origin:margin; left:0; padding:0 6px 0 0; }
QScrollArea,QGraphicsView { border:0; }
QScrollBar:vertical { background:#202020; width:7px; margin:0; }
QScrollBar::handle:vertical { background:#484848; border-radius:3px; min-height:28px; }
QScrollBar:horizontal { background:#202020; height:7px; margin:0; }
QScrollBar::handle:horizontal { background:#484848; border-radius:3px; min-width:28px; }
QScrollBar::add-line,QScrollBar::sub-line { width:0; height:0; }
QScrollBar::add-page,QScrollBar::sub-page { background:transparent; }
QSlider::groove:horizontal { height:3px; background:#494949; border-radius:1px; }
QSlider::sub-page:horizontal { background:#86818e; }
QSlider::handle:horizontal { background:#d9d6df; width:10px; margin:-4px 0; border-radius:4px; }
QCheckBox { spacing:7px; }
QCheckBox::indicator { width:13px; height:13px; border:1px solid #666; border-radius:3px; background:#292929; }
QCheckBox::indicator:checked { background:#92869f; border-color:#92869f; }
QSplitter::handle { background:#111; width:1px; }
QToolTip { background:#393939; color:#eee; border:1px solid #555; padding:5px; }
QMenu { background:#282828; border:1px solid #444; padding:5px; }
QMenu::item { padding:7px 24px; }
QMenu::item:selected { background:#3d394b; }
"""


def slider_row(label, spin):
    """Keep the existing spin as the source of truth, commit drags on release."""
    row = QWidget(); row.setFixedHeight(34)
    box = QHBoxLayout(row); box.setContentsMargins(0, 0, 0, 0); box.setSpacing(6)
    label_widget = QLabel(label); label_widget.setFixedWidth(62); box.addWidget(label_widget)
    spin.setButtonSymbols(QAbstractSpinBox.NoButtons); spin.setFixedWidth(48); spin.setAlignment(Qt.AlignRight)
    spin.setAccessibleName(label)
    slider = QSlider(Qt.Horizontal); slider.setAccessibleName(label)
    scale = 100 if spin.singleStep() < 1 else 1
    slider.setRange(round(spin.minimum()*scale), round(spin.maximum()*scale))
    slider.setSingleStep(max(1, round(spin.singleStep()*scale)))
    slider.setValue(round(spin.value()*scale)); slider.setTracking(False)
    slider.valueChanged.connect(lambda value: spin.setValue(value/scale))
    def sync(value):
        slider.blockSignals(True); slider.setValue(round(value*scale)); slider.blockSignals(False)
    spin.valueChanged.connect(sync)
    box.addWidget(slider, 1); box.addWidget(spin)
    return row


def tool_icon(kind):
    paths = {
        "adjustment": '<circle cx="12" cy="12" r="9"/><path d="M12 3v18"/><path d="M12 3a9 9 0 0 1 0 18Z" fill="#d8d2cb"/>',
        "folder": '<path d="M3 6h7l2 3h9v11H3ZM3 6V4h7l2 2h9v3"/>',
        "clip": '<path d="M5 3v7h6M8 7l3 3-3 3"/><rect x="8" y="14" width="13" height="7"/>',
        "select_rect": '<rect x="4" y="4" width="16" height="16" stroke-dasharray="2 3"/>',
        "color_select": '<path d="m5 16 10-10 3 3-10 10-4 1Zm9-12 2-2 6 6-2 2ZM3 5h4M5 3v4"/>',
        "lasso": '<path d="M8 18C-3 13 4 3 13 4s13 12 2 14S4 15 7 13s7 4 2 8"/>',
        "mask_brush": '<rect x="3" y="3" width="18" height="18"/><path d="m8 16 9-9M7 13l4 4"/><circle cx="9" cy="9" r="2"/>',
        "transform": '<path d="M5 5h14v14H5Z"/><path d="M2 2h5v5H2ZM17 2h5v5h-5ZM17 17h5v5h-5ZM2 17h5v5H2Z"/>',
        "move": '<path d="M12 2v20M2 12h20M9 5l3-3 3 3M9 19l3 3 3-3M5 9l-3 3 3 3M19 9l3 3-3 3"/>',
        "text": '<path d="M4 5V3h16v2M12 3v18M8 21h8"/>',
        "photo": '<rect x="3" y="3" width="18" height="18" rx="1"/><circle cx="8" cy="8" r="2"/><path d="m3 18 6-6 4 4 3-3 5 5"/>',
        "rectangle": '<rect x="4" y="5" width="16" height="14"/>',
        "ellipse": '<ellipse cx="12" cy="12" rx="9" ry="7"/>',
        "fit": '<path d="M9 3H3v6M15 3h6v6M3 15v6h6M21 15v6h-6"/>',
        "plus": '<path d="M12 4v16M4 12h16"/>',
        "trash": '<path d="M4 6h16M9 3h6M6 6l1 15h10l1-15M10 9v9M14 9v9"/>',
        "up": '<path d="m6 14 6-6 6 6"/>',
        "down": '<path d="m6 10 6 6 6-6"/>',
        "left": '<path d="M4 3v18M8 7h12v4H8ZM8 14h8v4H8Z"/>',
        "center": '<path d="M12 2v20M4 6h16v4H4ZM7 14h10v4H7Z"/>',
        "right": '<path d="M20 3v18M4 7h12v4H4ZM8 14h8v4H8Z"/>',
        "top": '<path d="M3 4h18M6 8h4v12H6ZM14 8h4v8h-4Z"/>',
        "middle": '<path d="M2 12h20M6 4h4v16H6ZM14 7h4v10h-4Z"/>',
        "bottom": '<path d="M3 20h18M6 4h4v12H6ZM14 8h4v8h-4Z"/>',
        "view": '<path d="m5 3 13 9-7 1-3 7Z"/>',
        "crop": '<path d="M6 2v16h16M2 6h16v16"/>',
        "brush": '<path d="m10 14 9-11 3 3-11 9M10 14c-5-2-2 7-7 6 6 3 10-1 8-5Z"/>',
        "linear": '<path d="M4 4h16M4 12h16M4 20h16M12 4v16"/><circle cx="12" cy="12" r="3"/>',
        "radial": '<ellipse cx="12" cy="12" rx="9" ry="7"/><circle cx="12" cy="12" r="2"/>',
        "clone": '<path d="M5 20h14v-5H5Zm3-5 2-5c-5-8 9-8 4 0l2 5"/>',
        "heal": '<path d="m4 13 9-9c5-5 11 1 7 6l-10 10c-5 4-11-2-6-7ZM8 9l7 7M10 12h.1M12 10h.1M12 14h.1M14 12h.1"/>',
    }
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><g fill="none" stroke="#d8d2cb" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'+paths[kind]+'</g></svg>'
    pixmap = QPixmap(48, 48); pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap); QSvgRenderer(QByteArray(svg.encode())).render(painter); painter.end()
    icon = QIcon(pixmap)
    return icon

_ASSETS = (Path(__file__).resolve().parent.parent / "assets" / "ui").as_posix()
STYLE += f"QComboBox::down-arrow {{ image:url({_ASSETS}/chevron-down.svg); width:12px; height:12px; }} QTabBar::close-button {{ image:url({_ASSETS}/close.svg); width:12px; height:12px; }}"

STYLE += """
QToolButton { border:1px solid transparent; background:transparent; border-radius:4px; padding:0; }
QToolButton:hover { background:#303035; }
QToolButton:checked { background:#474052; border-color:#655c75; }
QWidget#inspector { background:#171719; border-left:1px solid #303034; }
QLabel[panelHeader="true"] { background:#101012; color:#d8d8dd; border-radius:4px; padding:4px 7px; font-weight:600; }
QGroupBox { margin-top:12px; padding-top:10px; }
QGroupBox::indicator { width:10px; height:10px; }
QCheckBox::indicator { width:10px; height:10px; }
QTabBar::tab { border-bottom:0; }
QTabBar::tab:selected { background:#36323e; border-bottom:0; }
QListWidget#layers::item { min-height:28px; border-radius:5px; }
QListWidget#layers::item:selected { background:#383541; border:1px solid #494453; }
"""

STYLE += f"QListWidget#layers::indicator {{ width:16px; height:16px; }} QListWidget#layers::indicator:checked {{ image:url({_ASSETS}/eye.svg); }} QListWidget#layers::indicator:unchecked {{ image:url({_ASSETS}/eye-off.svg); }}"
