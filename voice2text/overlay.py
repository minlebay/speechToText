import logging
import math

import numpy as np
from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt5.QtGui import QBrush, QColor, QPainter, QPen, QRadialGradient
from PyQt5.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

log = logging.getLogger(__name__)


def _draw_mic(p: QPainter, cx: float, cy: float, color: str, scale: float = 1.0):
    """Микрофон — та же геометрия, что и в assets/voice2text.svg: капсула 120x190 rx60,
    чаша-подставка с вертикальными "ножками" (равный зазор от капсулы по всей длине,
    не только на дуге), ножка и основание."""
    p.save()
    p.translate(cx, cy)
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

_STATE_COLORS = {
    "recording": {"bg": QColor(30, 18, 18, 235), "ring": QColor(255, 60, 60), "mic": "#ff6b6b"},
    "transcribing": {"bg": QColor(22, 19, 42, 235), "ring": QColor(157, 124, 216), "mic": "#9d7cd8"},
}

# Точки привязки оверлея: доля (fx, fy) свободного места на экране, куда сдвигать окно.
POSITIONS = {
    "center": (0.5, 0.5),
    "top_left": (0.0, 0.0),
    "top_center": (0.5, 0.0),
    "top_right": (1.0, 0.0),
    "middle_left": (0.0, 0.5),
    "middle_right": (1.0, 0.5),
    "bottom_left": (0.0, 1.0),
    "bottom_center": (0.5, 1.0),
    "bottom_right": (1.0, 1.0),
}


def compute_level(pcm_bytes: bytes) -> float:
    """Уровень громкости (0..1) для среза 16-bit mono PCM, с перцептивным усилением тихой речи."""
    usable = len(pcm_bytes) // 2 * 2
    if usable < 2:
        return 0.0
    arr = np.frombuffer(pcm_bytes[:usable], dtype=np.int16).astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(arr ** 2)))
    return min(1.0, (rms * 8.0) ** 0.6)


class PulseIndicator(QWidget):
    """Круглый индикатор с иконкой микрофона и пульсирующими кольцами."""

    SIZE = 180

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._state = "recording"
        self._level = 0.0
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def set_state(self, state):
        self._state = state
        self.update()

    def set_level(self, level):
        level = max(0.0, min(1.0, level))
        # Экспоненциальное сглаживание — движение выглядит живым, а не дёрганым.
        self._level = self._level * 0.55 + level * 0.45

    def _tick(self):
        self._phase = (self._phase + 0.12) % (2 * math.pi)
        self.update()

    def paintEvent(self, event):
        colors = _STATE_COLORS.get(self._state, _STATE_COLORS["recording"])
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.SIZE / 2, self.SIZE / 2
        base_r = self.SIZE * 0.22

        # Радиальный ореол-подложка — чтобы оверлей был виден на любом фоне
        # рабочего стола, а не сливался с ним по краям.
        bg = colors["bg"]
        grad_r = self.SIZE / 2
        gradient = QRadialGradient(cx, cy, grad_r)
        gradient.setColorAt(0.0, QColor(bg.red(), bg.green(), bg.blue(), 235))
        gradient.setColorAt(0.6, QColor(bg.red(), bg.green(), bg.blue(), 140))
        gradient.setColorAt(1.0, QColor(bg.red(), bg.green(), bg.blue(), 0))
        p.setBrush(QBrush(gradient))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(cx - grad_r, cy - grad_r, grad_r * 2, grad_r * 2))

        if self._state == "recording":
            idle = 0.5 + 0.5 * math.sin(self._phase)
            voice = self._level

            outer_max = self.SIZE / 2 - 6
            gap = base_r * 0.18
            r_start = base_r + gap
            max_extent = max(0.0, outer_max - r_start)

            n_bars = 24
            bar_width = max(2.0, min(6.0, (2 * math.pi * r_start / n_bars) * 0.55))
            alpha = max(0, min(255, int(70 + 170 * voice)))
            bar_color = QColor(colors["ring"])
            bar_color.setAlpha(alpha)
            pen = QPen(bar_color)
            pen.setWidthF(bar_width)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)

            resting = max_extent * (0.05 + 0.03 * idle)
            for i in range(n_bars):
                # Две несинхронные синусоиды на столбик — разные столбики "дышат"
                # не в такт друг другу, получается эффект живого эквалайзера.
                wobble = 0.5 + 0.5 * (
                    0.6 * math.sin(self._phase * 1.3 + i * 0.9)
                    + 0.4 * math.sin(self._phase * 2.7 + i * 2.3)
                )
                wobble = max(0.0, min(1.0, wobble))
                bar_len = resting + wobble * voice * max_extent * 3.6
                r_end = min(outer_max, r_start + bar_len)

                angle = (2 * math.pi * i / n_bars) - math.pi / 2
                x1 = cx + r_start * math.cos(angle)
                y1 = cy + r_start * math.sin(angle)
                x2 = cx + r_end * math.cos(angle)
                y2 = cy + r_end * math.sin(angle)
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

            # Бейдж под иконкой микрофона, слегка светлеет при громком голосе.
            badge = QColor(colors["ring"])
            badge.setAlpha(int(35 + 70 * voice))
            p.setBrush(badge)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(cx - base_r, cy - base_r, base_r * 2, base_r * 2))
        else:  # transcribing — вращающаяся дуга
            pen = QPen(colors["ring"], 4)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            r = base_r * 1.6
            start = int((-self._phase * 180 / math.pi) * 16) % (360 * 16)
            p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), start, 100 * 16)

        # Масштаб и смещение подобраны рендер-тестом по видимым краям иконки (bounding box),
        # чтобы отступы сверху и снизу внутри круга были одинаковыми.
        mic_scale = base_r / 162.0
        mic_offset = 227.5 * mic_scale
        _draw_mic(p, cx, cy - mic_offset, colors["mic"], scale=mic_scale)
        p.end()


class OverlayWindow(QWidget):
    """Небольшой оверлей по центру экрана, сигнализирующий о записи/обработке."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignHCenter)

        self.indicator = PulseIndicator(self)
        layout.addWidget(self.indicator, 0, Qt.AlignHCenter)

        self.text_label = QLabel(self)
        self.text_label.setWordWrap(True)
        self.text_label.setAlignment(Qt.AlignCenter)
        self.text_label.setMaximumWidth(360)
        self.text_label.setStyleSheet(
            "QLabel {"
            "  color: #e8e8f0;"
            "  background-color: rgba(20, 20, 30, 200);"
            "  border-radius: 10px;"
            "  padding: 10px 16px;"
            "  font-size: 14px;"
            "}"
        )
        self.text_label.hide()
        layout.addWidget(self.text_label, 0, Qt.AlignHCenter)

        self._show_text = False
        self._position = "center"

    def set_position(self, position):
        self._position = position if position in POSITIONS else "center"

    def set_text_enabled(self, enabled):
        self._show_text = enabled
        if not enabled:
            self.text_label.hide()
            self.text_label.setText("")

    def show_recording(self):
        self.indicator.set_state("recording")
        self.indicator.set_level(0.0)
        if self._show_text:
            self.text_label.setText("")
            self.text_label.show()
        self._recenter_and_show()

    def show_transcribing(self):
        self.indicator.set_state("transcribing")
        self._recenter_and_show()

    def set_level(self, level):
        self.indicator.set_level(level)

    def set_partial_text(self, text):
        if self._show_text:
            self.text_label.setText(text)
            self._recenter_and_show()

    def hide_overlay(self):
        self.hide()
        self.text_label.setText("")

    def _recenter_and_show(self):
        self.adjustSize()
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            margin = 24
            fx, fy = POSITIONS.get(self._position, POSITIONS["center"])
            avail_w = max(0, geo.width() - self.width() - 2 * margin)
            avail_h = max(0, geo.height() - self.height() - 2 * margin)
            x = geo.x() + margin + int(fx * avail_w)
            y = geo.y() + margin + int(fy * avail_h)
            self.move(x, y)
        self.show()
        self.raise_()
