from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

_MIC_SCALE = 0.1833  # подобрано рендер-тестом под 56x56 фон трей-иконки


def _draw_mic(p: QPainter, cx: float, cy: float, color: str, scale: float = 1.0):
    """Микрофон — та же геометрия, что и в assets/voice2text.svg и overlay.py: капсула
    120x190 rx60, чаша-подставка с вертикальными "ножками" (равный зазор от капсулы
    по всей длине), ножка и основание. cx,cy задают точку, вокруг которой значок
    центрируется по видимым краям (bounding box), а не по центру масс."""
    p.save()
    p.translate(cx, cy - 227.5 * scale)
    if scale != 1.0:
        p.scale(scale, scale)

    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(-60, 90, 120, 190), 60, 60)

    cradle_pen = QPen(QColor(color), 14)
    cradle_pen.setCapStyle(Qt.RoundCap)
    cradle_pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(cradle_pen)
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(-82, 190), QPointF(-82, 220))
    p.drawLine(QPointF(82, 190), QPointF(82, 220))
    p.drawArc(QRectF(-82, 220 - 82, 164, 164), 180 * 16, 180 * 16)

    pole_pen = QPen(QColor(color), 14)
    pole_pen.setCapStyle(Qt.RoundCap)
    p.setPen(pole_pen)
    p.drawLine(QPointF(0, 302), QPointF(0, 358.5))

    base_pen = QPen(QColor(color), 14)
    base_pen.setCapStyle(Qt.RoundCap)
    p.setPen(base_pen)
    p.drawLine(QPointF(-65, 358.5), QPointF(65, 358.5))

    p.restore()


def _draw_mute_slash(p: QPainter, color: str, width: float = 7.0):
    """Диагональная черта поверх иконки микрофона — общепринятый знак
    «звук выключен», не завязанный на цвет фона/состояние."""
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(13, 51), QPointF(51, 13))


_MONO_COLORS = {
    "light": "#f5f5f5",
    "dark": "#1a1a1a",
}


def make_tray_icon(
    state: str,
    monochrome: bool = False,
    mono_variant: str = "light",
    muted: bool = False,
) -> QIcon:
    if monochrome:
        return _make_mono_tray_icon(state, mono_variant, muted)

    S = 64
    pix = QPixmap(S, S)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    cx, cy = 32.0, 32.0

    if state == "idle":
        # Dark navy background, blue mic
        p.setBrush(QColor("#1e2433"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(4, 4, 56, 56, 14, 14)
        _draw_mic(p, cx, cy, "#7aa2f7", scale=_MIC_SCALE)

    elif state == "recording":
        # Dark red bg + pulse rings, red mic + recording dot
        p.setBrush(QColor("#1e1212"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(4, 4, 56, 56, 14, 14)
        for r, a in ((27, 35), (20, 65)):
            p.setBrush(QColor(255, 60, 60, a))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        _draw_mic(p, cx, cy, "#ff6b6b", scale=_MIC_SCALE)
        p.setBrush(QColor("#ff2233"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(cx + 13, cy - 24, 10, 10))

    elif state == "transcribing":
        # Dark purple bg, purple mic, three typing dots
        p.setBrush(QColor("#16132a"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(4, 4, 56, 56, 14, 14)
        _draw_mic(p, cx, cy, "#9d7cd8", scale=_MIC_SCALE)
        p.setBrush(QColor("#9d7cd8"))
        p.setPen(Qt.NoPen)
        for dx in (-10, 0, 10):
            p.drawEllipse(QRectF(cx + dx - 3, cy + 20, 6, 6))

    if muted:
        _draw_mute_slash(p, "#ffffff")

    p.end()
    return QIcon(pix)


def _make_mono_tray_icon(state: str, mono_variant: str, muted: bool = False) -> QIcon:
    """Одноцветный силуэт без фона — состояния различаются только формой
    (точка записи, точки распознавания), а не цветом, чтобы иконка одинаково
    хорошо читалась на любой панели."""
    color = _MONO_COLORS.get(mono_variant, _MONO_COLORS["light"])
    S = 64
    pix = QPixmap(S, S)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    cx, cy = 32.0, 32.0

    _draw_mic(p, cx, cy, color, scale=_MIC_SCALE)

    if state == "recording":
        p.setBrush(QColor(color))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(cx + 13, cy - 24, 10, 10))

    elif state == "transcribing":
        p.setBrush(QColor(color))
        p.setPen(Qt.NoPen)
        for dx in (-10, 0, 10):
            p.drawEllipse(QRectF(cx + dx - 3, cy + 20, 6, 6))

    if muted:
        _draw_mute_slash(p, color)

    p.end()
    return QIcon(pix)
