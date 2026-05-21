from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen, QPixmap


def _draw_mic(p: QPainter, cx: float, cy: float, color: str):
    bw, bh = 14.0, 15.0
    ar = 11.0

    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(cx - bw / 2, cy - bh, bw, bh * 1.3), bw / 2, bw / 2)

    pen = QPen(QColor(color), 2.5)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    arc_top = cy + 2.0
    p.drawArc(QRectF(cx - ar, arc_top, ar * 2, ar * 1.2), 0, 180 * 16)

    pole_top = arc_top + ar * 1.2
    pole_bot = cy + 22.0
    p.drawLine(int(cx), int(pole_top), int(cx), int(pole_bot))
    p.drawLine(int(cx - 8), int(pole_bot), int(cx + 8), int(pole_bot))


def make_tray_icon(state: str) -> QIcon:
    S = 64
    pix = QPixmap(S, S)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    cx, cy = 32.0, 34.0

    if state == "idle":
        # Dark navy background, blue mic
        p.setBrush(QColor("#1e2433"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(4, 4, 56, 56, 14, 14)
        _draw_mic(p, cx, cy, "#7aa2f7")

    elif state == "recording":
        # Dark red bg + pulse rings, red mic + recording dot
        p.setBrush(QColor("#1e1212"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(4, 4, 56, 56, 14, 14)
        for r, a in ((27, 35), (20, 65)):
            p.setBrush(QColor(255, 60, 60, a))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(cx - r, cy - r + 4, r * 2, r * 2))
        _draw_mic(p, cx, cy, "#ff6b6b")
        p.setBrush(QColor("#ff2233"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(cx + 13, cy - 26, 10, 10))

    elif state == "transcribing":
        # Dark purple bg, purple mic, three typing dots
        p.setBrush(QColor("#16132a"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(4, 4, 56, 56, 14, 14)
        _draw_mic(p, cx, cy - 4, "#9d7cd8")
        p.setBrush(QColor("#9d7cd8"))
        p.setPen(Qt.NoPen)
        for dx in (-10, 0, 10):
            p.drawEllipse(QRectF(cx + dx - 3, cy + 22, 6, 6))

    p.end()
    return QIcon(pix)
