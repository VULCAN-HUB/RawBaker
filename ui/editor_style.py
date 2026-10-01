"""Independent editor surface tokens; old Studio layout is not used."""
from pathlib import Path
ASSETS = (Path(__file__).resolve().parent.parent / "assets/ui").as_posix()
STYLE = """
QWidget { background:#252527; color:#ceced1; font-family:"Malgun Gothic"; font-size:11px; }
QMainWindow { background:#202022; }
QLabel { background:transparent; }
QMenuBar { background:#1c1c1e; padding:2px; }
QMenuBar::item { padding:3px 9px; background:transparent; }
QMenuBar::item:selected,QMenu::item:selected { background:#47474d; }
QMenu { background:#29292c; border:1px solid #48484c; padding:4px; }
QMenu::item { padding:5px 26px; }
QToolBar { border:0; background:#303033; spacing:3px; padding:3px; }
QToolButton { border:1px solid transparent; background:transparent; padding:3px; border-radius:3px; }
QToolButton:hover { background:#444448; }
QToolButton:checked { background:#55555d; border-color:#777780; }
QPushButton { background:#3a3a3e; border:1px solid #444448; border-radius:3px; padding:3px 8px; }
QPushButton:hover { background:#49494e; }
QPushButton:disabled,QToolButton:disabled,QLineEdit:disabled,QDoubleSpinBox:disabled,QSpinBox:disabled,QComboBox:disabled { color:#777; }
QPushButton[primary="true"] { background:#ceced5; color:#202023; }
QLineEdit,QSpinBox,QDoubleSpinBox,QComboBox,QTextEdit { background:#202022; border:1px solid #3e3e43; border-radius:3px; padding:2px 5px; selection-background-color:#535360; }
QLineEdit:focus,QSpinBox:focus,QDoubleSpinBox:focus,QTextEdit:focus { border-color:#83838f; }
QComboBox::drop-down { border:0; width:18px; }
QComboBox QAbstractItemView { background:#303034; selection-background-color:#555560; }
QDockWidget { titlebar-close-icon:none; }
QDockWidget::title { background:#1b1b1e; padding:5px 7px; }
QDockWidget::close-button,QDockWidget::float-button { padding:0; }
QMainWindow::separator { background:#18181a; width:3px; height:3px; }
QTabWidget::pane { border:0; }
QTabBar::tab { background:#222225; color:#aaaab2; padding:5px 12px; border-right:1px solid #19191b; }
QTabBar::tab:selected { background:#39393e; color:#eeeef2; }
QListWidget { background:#252527; border:0; outline:0; }
QListWidget::item { padding:5px; border:1px solid transparent; }
QListWidget::item:selected { background:#4c4c55; border-color:#5a5a63; color:#eeeef2; }
QListWidget::item:hover { background:#37373c; }
QListWidget#layers::item { min-height:26px; padding:1px 3px; }
QScrollArea,QGraphicsView { border:0; }
QScrollBar:vertical { background:#242426; width:7px; }
QScrollBar::handle:vertical { background:#4d4d53; min-height:24px; border-radius:3px; }
QScrollBar:horizontal { background:#242426; height:7px; }
QScrollBar::handle:horizontal { background:#4d4d53; min-width:24px; }
QScrollBar::add-line,QScrollBar::sub-line { width:0; height:0; }
QScrollBar::add-page,QScrollBar::sub-page { background:transparent; }
QSlider::groove:horizontal { height:3px; background:#55555c; }
QSlider::handle:horizontal { background:#d3d3db; width:9px; margin:-3px 0; border-radius:4px; }
QCheckBox { spacing:5px; }
QCheckBox::indicator { width:11px; height:11px; border:1px solid #66666f; border-radius:2px; }
QCheckBox::indicator:checked { background:#aaaab8; }
QGroupBox { border:0; border-top:1px solid #414148; margin-top:12px; padding-top:10px; }
QGroupBox::title { subcontrol-origin:margin; left:0; padding-right:6px; }
QStatusBar { background:#1d1d20; }
QStatusBar::item { border:0; }
QToolTip { background:#393940; border:1px solid #5b5b64; color:#eee; padding:5px; }
"""
STYLE += f"QComboBox::down-arrow {{ image:url({ASSETS}/chevron-down.svg); }} QTabBar::close-button {{ image:url({ASSETS}/close.svg); width:12px; height:12px; }} QListWidget#layers::indicator {{ width:16px; height:16px; }} QListWidget#layers::indicator:checked {{ image:url({ASSETS}/eye.svg); }} QListWidget#layers::indicator:unchecked {{ image:url({ASSETS}/eye-off.svg); }}"

# Compact, consistent controls with legible active/focus states at high DPI.
STYLE += """
QToolBar#editor-tools { spacing:1px; padding:2px; border-right:1px solid #151517; }
QToolBar#editor-tools QToolButton { min-width:22px; min-height:22px; padding:2px; border-radius:2px; }
QToolBar#editor-tools QToolButton:checked { background:#47434f; border-color:#9992a8; }
QToolButton:focus,QPushButton:focus { border:1px solid #9992a8; }
QDockWidget::title { padding:5px 8px; font-weight:500; }
QListWidget#layers::item:selected { background:#48434f; border-color:#80778f; }
QListWidget#layers::item:selected:hover { background:#514b59; }
"""
STYLE += f"QCheckBox::indicator:checked {{ image:url({ASSETS}/check.svg); background:#aaaab8; }}"
