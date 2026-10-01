"""Small actionable empty state inside the existing editor viewport."""
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton


class EmptyCanvas(QWidget):
    def __init__(self, canvas, title, hint, actions):
        super().__init__(canvas.viewport())
        layout = QVBoxLayout(self)
        heading = QLabel(title); heading.setAlignment(Qt.AlignCenter)
        heading.setWordWrap(True); layout.addWidget(heading)
        label = QLabel(hint); label.setWordWrap(True); label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
        for text, callback in actions:
            button = QPushButton(text); button.clicked.connect(callback); layout.addWidget(button)
        canvas.viewport().installEventFilter(self)
        self.reposition()

    def reposition(self):
        parent = self.parentWidget()
        self.resize(max(1, min(340, parent.width()-24)), self.sizeHint().height())
        self.move(max(0, (parent.width()-self.width())//2), max(0, (parent.height()-self.height())//2))

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize:
            self.reposition()
        return super().eventFilter(watched, event)
