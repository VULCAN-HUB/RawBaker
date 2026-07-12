from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QProgressBar
from PyQt5.QtCore import Qt


class ConvertProgressBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)

        self.pct_label = QLabel("0%")
        self.pct_label.setFixedWidth(40)
        self.pct_label.setStyleSheet("color:#D35400; font-weight:bold; font-size:12px;")
        self.pct_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setStyleSheet("""
            QProgressBar {
                background: #222222;
                border: none;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #D35400, stop:1 #E67E22
                );
                border-radius: 4px;
            }
        """)

        self.eta_label = QLabel("")
        self.eta_label.setFixedWidth(110)
        self.eta_label.setStyleSheet("color:#888888; font-size:11px;")

        layout.addWidget(self.pct_label)
        layout.addWidget(self.bar, stretch=1)
        layout.addWidget(self.eta_label)

    def set_progress(self, pct: int, eta_str: str = ""):
        pct = max(0, min(100, pct))
        self.bar.setValue(pct)
        self.pct_label.setText(f"{pct}%")
        self.eta_label.setText(eta_str)

    def reset(self):
        self.set_progress(0, "")
