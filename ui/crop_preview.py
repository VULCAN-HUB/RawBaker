"""
crop_preview.py — 인터랙티브 크롭 편집 캔버스 (Phase 1).

- 박스 안: 컬러 / 박스 밖: 흑백
- 박스 안쪽 드래그: 위치 이동
- 모서리(4곳) 드래그: 가로:세로 비율 고정한 채 크기 조절
- 변경 시 rectChanged(정규화 rect) 시그널 발생
좌표는 모두 정규화(0~1, 원본 이미지 기준)로 저장/통신한다.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QWidget, QSizePolicy
from PyQt5.QtCore import Qt, QRect, QRectF, QPoint, pyqtSignal
from PyQt5.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QBrush


def _pil_to_qpixmap(img):
    import numpy as np
    arr = np.array(img.convert("RGB"))
    h, w, ch = arr.shape
    qimg = QImage(arr.data, w, h, ch * w, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(qimg)


class CropPreviewWidget(QWidget):
    rectChanged = pyqtSignal(tuple)   # (nx, ny, nw, nh)

    _HANDLE = 9          # 모서리 핸들 히트 반경(px)
    _MIN_NORM = 0.05     # 박스 최소 크기(정규화)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self._color: QPixmap | None = None
        self._gray: QPixmap | None = None
        self._src_w = 0
        self._src_h = 0
        self._rect = (0.0, 0.0, 1.0, 1.0)     # 정규화
        self._target_ar = 1.5                  # 픽셀 가로:세로 (예 2400/1600)
        self._drag = None                      # None | 'move' | 'tl'|'tr'|'bl'|'br'
        self._drag_start = None                # (mouse_norm, rect_at_start)
        # setStyleSheet 을 쓰면 Qt 스타일 엔진이 paintEvent를 가로채
        # 커스텀 드로잉이 묻히는 문제가 생긴다 → 배경은 paintEvent 안에서만 칠한다.
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)  # 배경은 우리가 직접 그림

    # ── 공개 API ─────────────────────────────────
    def set_pixmap(self, pm: QPixmap):
        """QPixmap을 직접 받아 컬러/흑백 픽스맵 준비 (PIL 없이 빠른 경로)."""
        if pm is None or pm.isNull():
            self._color = self._gray = None
            self.update()
            return
        self._src_w = pm.width()
        self._src_h = pm.height()
        self._color = pm
        try:
            import numpy as np
            qimg = pm.toImage().convertToFormat(QImage.Format_RGB888)
            ptr = qimg.bits()
            ptr.setsize(qimg.height() * qimg.width() * 3)
            arr = np.frombuffer(ptr, np.uint8).reshape(qimg.height(), qimg.width(), 3).copy()
            lum = (arr[..., 0:1] * 0.299 + arr[..., 1:2] * 0.587 + arr[..., 2:3] * 0.114).astype(np.uint8)
            gray_arr = np.concatenate([lum, lum, lum], axis=2)
            h, w = gray_arr.shape[:2]
            self._gray = QPixmap.fromImage(
                QImage(gray_arr.data, w, h, 3 * w, QImage.Format_RGB888).copy()
            )
        except Exception:
            self._gray = pm   # 변환 실패 시 컬러로 대체
        self.update()

    def set_image(self, pil_image):
        """PIL.Image 를 받아 컬러/흑백 디스플레이 픽스맵 준비."""
        if pil_image is None:
            self._color = self._gray = None
            self.update(); return
        self._src_w, self._src_h = pil_image.size
        disp = pil_image
        longest = max(pil_image.size)
        if longest > 1400:
            s = 1400 / longest
            disp = pil_image.resize((max(1, int(pil_image.width * s)),
                                     max(1, int(pil_image.height * s))))
        self._color = _pil_to_qpixmap(disp)
        self._gray = _pil_to_qpixmap(disp.convert("L"))
        self.update()

    def clear_image(self):
        self._color = self._gray = None
        self.update()

    def set_target_aspect(self, ar: float):
        self._target_ar = ar if ar and ar > 0 else 1.0
        self.update()

    def set_rect(self, rect):
        if rect and len(rect) == 4:
            self._rect = tuple(float(v) for v in rect)
            self.update()

    def get_rect(self):
        return self._rect

    def has_image(self) -> bool:
        return self._color is not None

    # ── 좌표 변환 ─────────────────────────────────
    def _disp_rect(self) -> QRect:
        """이미지가 그려지는 위젯 내 사각형(레터박스 포함)."""
        if not self._color:
            return QRect(0, 0, self.width(), self.height())
        pw, ph = self._color.width(), self._color.height()
        ww, wh = max(1, self.width() - 2), max(1, self.height() - 2)
        scale = min(ww / pw, wh / ph)
        dw, dh = int(pw * scale), int(ph * scale)
        x = (self.width() - dw) // 2
        y = (self.height() - dh) // 2
        return QRect(x, y, dw, dh)

    def _norm_to_px(self, nx, ny):
        dr = self._disp_rect()
        return QPoint(int(dr.x() + nx * dr.width()), int(dr.y() + ny * dr.height()))

    def _px_to_norm(self, px, py):
        dr = self._disp_rect()
        if dr.width() <= 0 or dr.height() <= 0:
            return (0.0, 0.0)
        return ((px - dr.x()) / dr.width(), (py - dr.y()) / dr.height())

    def _box_disp(self) -> QRect:
        nx, ny, nw, nh = self._rect
        tl = self._norm_to_px(nx, ny)
        br = self._norm_to_px(nx + nw, ny + nh)
        return QRect(tl, br)

    # ── 그리기 ───────────────────────────────────
    def paintEvent(self, e):
        p = QPainter(self)
        try:
            self._paint(p)
        except Exception:
            pass
        finally:
            p.end()   # 항상 QPainter를 닫아야 다음 paint가 정상 작동

    def _paint(self, p):
        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, QColor("#111111"))
        if not self._color:
            p.setPen(QColor("#888888"))
            p.drawText(0, 0, W, H, Qt.AlignCenter, "왼쪽 목록에서 파일을 선택하세요")
            return

        dr = self._disp_rect()
        # 1) 전체 흑백
        p.drawPixmap(dr, self._gray)
        # 2) 크롭 영역만 컬러
        box = self._box_disp().intersected(dr)
        if box.width() > 0 and box.height() > 0:
            sx = (box.x() - dr.x()) / dr.width() * self._color.width()
            sy = (box.y() - dr.y()) / dr.height() * self._color.height()
            sw = box.width() / dr.width() * self._color.width()
            sh = box.height() / dr.height() * self._color.height()
            p.drawPixmap(box, self._color, QRectF(sx, sy, sw, sh).toRect())
        # 3) 테두리 + 핸들
        pen = QPen(QColor("#D35400")); pen.setWidth(2)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        p.drawRect(box)
        p.setBrush(QBrush(QColor("#D35400")))
        p.setPen(Qt.NoPen)
        # 모서리 핸들 (8×8 사각형)
        for pt in (box.topLeft(), box.topRight(), box.bottomLeft(), box.bottomRight()):
            p.drawRect(pt.x() - 4, pt.y() - 4, 8, 8)
        # 변 중간 핸들 (6×6 사각형)
        mx = box.left() + box.width() // 2
        my = box.top() + box.height() // 2
        for ex, ey in ((mx, box.top()), (mx, box.bottom()),
                       (box.left(), my), (box.right(), my)):
            p.drawRect(ex - 3, ey - 3, 6, 6)

    # ── 마우스 ───────────────────────────────────
    def _hit(self, pos: QPoint):
        box = self._box_disp()
        h = self._HANDLE
        # 모서리 우선 검사
        corners = {"tl": box.topLeft(), "tr": box.topRight(),
                   "bl": box.bottomLeft(), "br": box.bottomRight()}
        for name, pt in corners.items():
            if abs(pos.x() - pt.x()) <= h and abs(pos.y() - pt.y()) <= h:
                return name
        # 변(edge) 검사 — 박스 안쪽/외곽 h px 이내
        cx, cy = pos.x(), pos.y()
        in_x = box.left() - h <= cx <= box.right() + h
        in_y = box.top() - h <= cy <= box.bottom() + h
        on_left   = abs(cx - box.left())  <= h and in_y
        on_right  = abs(cx - box.right()) <= h and in_y
        on_top    = abs(cy - box.top())   <= h and in_x
        on_bottom = abs(cy - box.bottom()) <= h and in_x
        if on_left:   return "l"
        if on_right:  return "r"
        if on_top:    return "t"
        if on_bottom: return "b"
        if box.contains(pos):
            return "move"
        return None

    def mousePressEvent(self, e):
        if not self._color:
            return
        self._drag = self._hit(e.pos())
        if self._drag:
            self._drag_start = (self._px_to_norm(e.x(), e.y()), self._rect)

    def mouseMoveEvent(self, e):
        if not self._color:
            return
        if not self._drag:
            # 커서 모양
            hit = self._hit(e.pos())
            if hit in ("tl", "br"):
                self.setCursor(Qt.SizeFDiagCursor)
            elif hit in ("tr", "bl"):
                self.setCursor(Qt.SizeBDiagCursor)
            elif hit in ("l", "r"):
                self.setCursor(Qt.SizeHorCursor)
            elif hit in ("t", "b"):
                self.setCursor(Qt.SizeVerCursor)
            elif hit == "move":
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
            return

        (sx, sy), (ox, oy, ow, oh) = self._drag_start
        mx, my = self._px_to_norm(e.x(), e.y())
        dx, dy = mx - sx, my - sy

        if self._drag == "move":
            nx = min(max(0.0, ox + dx), 1.0 - ow)
            ny = min(max(0.0, oy + dy), 1.0 - oh)
            self._rect = (nx, ny, ow, oh)
        elif self._drag in ("tl", "tr", "bl", "br"):
            self._resize_corner(self._drag, mx, my, ox, oy, ow, oh)
        else:
            self._resize_edge(self._drag, mx, my, ox, oy, ow, oh)

        self.update()
        self.rectChanged.emit(self._rect)

    def mouseReleaseEvent(self, e):
        self._drag = None
        self._drag_start = None

    def _resize_edge(self, edge, mx, my, ox, oy, ow, oh):
        """변(edge) 드래그 — 비율 자유, 해당 변만 이동. 반대 변 고정."""
        MIN = self._MIN_NORM
        if edge == "l":
            new_x = min(mx, ox + ow - MIN)
            new_x = max(0.0, new_x)
            self._rect = (new_x, oy, ox + ow - new_x, oh)
        elif edge == "r":
            new_r = max(mx, ox + MIN)
            new_r = min(1.0, new_r)
            self._rect = (ox, oy, new_r - ox, oh)
        elif edge == "t":
            new_y = min(my, oy + oh - MIN)
            new_y = max(0.0, new_y)
            self._rect = (ox, new_y, ow, oy + oh - new_y)
        elif edge == "b":
            new_b = max(my, oy + MIN)
            new_b = min(1.0, new_b)
            self._rect = (ox, oy, ow, new_b - oy)

    def _resize_corner(self, corner, mx, my, ox, oy, ow, oh):
        """모서리 드래그 — 가로:세로(픽셀) 비율 고정. 반대 모서리를 고정점으로."""
        # 고정점(앵커) = 반대 모서리 (정규화)
        anchor_x = ox + ow if "l" in corner else ox       # corner가 left면 앵커는 right
        anchor_y = oy + oh if "t" in corner else oy        # corner가 top이면 앵커는 bottom
        # 정규화 공간에서의 목표 비율: nw/nh = AR_px * (oh_src/ow_src)
        if self._src_w <= 0 or self._src_h <= 0:
            return
        nar = self._target_ar * (self._src_h / self._src_w)   # nw/nh
        # 마우스까지의 폭/높이(부호 무시)
        new_w = abs(mx - anchor_x)
        new_h = abs(my - anchor_y)
        # 비율 고정: 더 큰 쪽 기준으로 맞춤
        if new_w / max(1e-6, nar) >= new_h:
            new_h = new_w / nar
        else:
            new_w = new_h * nar
        new_w = max(self._MIN_NORM, new_w)
        new_h = max(self._MIN_NORM, new_h)
        # corner 방향에 따라 좌상단 결정
        nx = anchor_x - new_w if "l" in corner else anchor_x
        ny = anchor_y - new_h if "t" in corner else anchor_y
        # 경계 클램프 (넘으면 비율 유지하며 축소)
        if nx < 0:
            over = -nx; new_w -= over; new_h = new_w / nar; nx = 0.0
            if "t" in corner: ny = anchor_y - new_h
        if ny < 0:
            over = -ny; new_h -= over; new_w = new_h * nar; ny = 0.0
            if "l" in corner: nx = anchor_x - new_w
        if nx + new_w > 1.0:
            new_w = 1.0 - nx; new_h = new_w / nar
            if "t" in corner: ny = anchor_y - new_h
        if ny + new_h > 1.0:
            new_h = 1.0 - ny; new_w = new_h * nar
            if "l" in corner: nx = anchor_x - new_w
        nx = max(0.0, min(1.0, nx)); ny = max(0.0, min(1.0, ny))
        new_w = max(self._MIN_NORM, min(1.0 - nx, new_w))
        new_h = max(self._MIN_NORM, min(1.0 - ny, new_h))
        self._rect = (nx, ny, new_w, new_h)
