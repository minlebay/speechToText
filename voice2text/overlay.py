import logging
import math
import random

import numpy as np
from PyQt5.QtCore import QPointF, QRect, QRectF, Qt, QTimer
from PyQt5.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient, QRegion
from PyQt5.QtWidgets import QApplication, QGraphicsDropShadowEffect, QLabel, QVBoxLayout, QWidget

log = logging.getLogger(__name__)

try:
    from Xlib import Xatom
    from Xlib.display import Display as _XDisplay
except Exception:
    _XDisplay = None

_xlib_display = None
_xlib_unavailable = False


def _get_xlib_display():
    """Отдельное соединение с X-сервером для нативных свойств окна KWin —
    Qt/xcb не даёт установить _KDE_NET_WM_BLUR_BEHIND_REGION напрямую."""
    global _xlib_display, _xlib_unavailable
    if _xlib_unavailable or _XDisplay is None:
        return None
    if _xlib_display is None:
        try:
            _xlib_display = _XDisplay()
        except Exception as e:
            log.debug("Xlib-дисплей недоступен, нативный блюр KWin отключён: %s", e)
            _xlib_unavailable = True
            return None
    return _xlib_display


def _stadium_region_rects(x, y, w, h):
    """Разбивает область со скруглением radius=h/2 (форма нашей капсулы) на
    набор прямоугольников: два круглых торца плюс прямоугольник посередине.
    Без этого KWin размывал бы весь прямоугольный bounding box, и по углам
    капсулы торчали бы квадратные «уши» блюра за пределами скругления."""
    radius = h / 2
    region = QRegion(QRect(int(x + radius), int(y), int(max(0, w - 2 * radius)), int(h)))
    region += QRegion(QRect(int(x), int(y), int(h), int(h)), QRegion.Ellipse)
    region += QRegion(QRect(int(x + w - h), int(y), int(h), int(h)), QRegion.Ellipse)
    return [(r.x(), r.y(), r.width(), r.height()) for r in region.rects()]


def set_kwin_blur_region(win_id: int, rects):
    """Просит компоузитор (KWin на Plasma) реально размывать рабочий стол
    под окном в наборе прямоугольников rects=[(x, y, w, h), ...] в локальных
    координатах окна. rects=None снимает блюр. Это нативный эффект KDE, а не
    подделка — на других окружениях (не Plasma/KWin) просто не действует."""
    display = _get_xlib_display()
    if display is None:
        return
    try:
        window = display.create_resource_object("window", win_id)
        atom = display.intern_atom("_KDE_NET_WM_BLUR_BEHIND_REGION")
        if not rects:
            window.change_property(atom, Xatom.CARDINAL, 32, [])
        else:
            values = []
            for x, y, w, h in rects:
                values.extend([int(x), int(y), int(w), int(h)])
            window.change_property(atom, Xatom.CARDINAL, 32, values)
        display.flush()
    except Exception as e:
        log.debug("Не удалось обновить регион блюра KWin: %s", e)


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

_THEMES = {
    "dark": {
        "recording": {
            "bg": QColor(24, 16, 16, 255),
            "ring": QColor(255, 60, 60),
            "mic": "#ff6b6b",
            "border": QColor(255, 60, 60),
        },
        "transcribing": {
            "bg": QColor(14, 20, 16, 255),
            "ring": QColor(70, 220, 120),
            "mic": "#46dc78",
            "border": QColor(255, 60, 60),
        },
    },
    "light": {
        "recording": {
            "bg": QColor(255, 255, 255, 255),
            "ring": QColor(220, 38, 38),
            "mic": "#dc2626",
            "border": QColor(220, 38, 38),
        },
        "transcribing": {
            "bg": QColor(255, 255, 255, 255),
            "ring": QColor(22, 163, 74),
            "mic": "#16a34a",
            "border": QColor(220, 38, 38),
        },
    },
}


def _theme_colors(theme, state):
    theme_map = _THEMES.get(theme, _THEMES["dark"])
    return theme_map.get(state, theme_map["recording"])


# Палитра для формы "капсула" — тёплая (свет) / нейтрально-тёмная (тьма) подложка
# с янтарной волной, независимо от состояния (запись/распознавание), как в
# обычных приложениях голосовых заметок.
_CAPSULE_THEMES = {
    "light": {
        "bg": QColor(245, 240, 231),
        "text": QColor(96, 92, 84),
        "wave": QColor(196, 120, 54),
    },
    "dark": {
        "bg": QColor(22, 24, 29),
        "text": QColor(158, 162, 170),
        "wave": QColor(255, 176, 64),
    },
}


def _capsule_colors(theme):
    return _CAPSULE_THEMES.get(theme, _CAPSULE_THEMES["dark"])

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
    GLOW_MARGIN = 14  # запас по краям под мягкое красное свечение рамки

    N_MATRIX_COLUMNS = 9
    MATRIX_TRAIL_LEN = 9
    MATRIX_LENS_STRENGTH = 0.85
    N_BARS = 120

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE + 2 * self.GLOW_MARGIN, self.SIZE + 2 * self.GLOW_MARGIN)
        self._state = "recording"
        self._theme = "dark"
        self._level = 0.0
        self._phase = 0.0
        self._matrix_phase = 0.0
        self._matrix_columns = self._make_matrix_columns()
        self._bar_wobble = self._make_bar_wobble()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def _make_bar_wobble(self):
        # У каждого луча своя пара частот и фаз, а не общая функция от индекса —
        # иначе лучи выглядят как один и тот же узор, скопированный по кругу.
        rng = random.Random(2024)
        return [
            {
                "f1": rng.uniform(0.7, 1.9),
                "f2": rng.uniform(1.8, 3.6),
                "p1": rng.uniform(0, 2 * math.pi),
                "p2": rng.uniform(0, 2 * math.pi),
            }
            for _ in range(self.N_BARS)
        ]

    def _make_matrix_columns(self):
        rng = random.Random(1337)
        columns = []
        for _ in range(self.N_MATRIX_COLUMNS):
            columns.append({
                "speed": rng.uniform(0.5, 1.4),
                "offset": rng.uniform(0, 100),
                "chars": [rng.choice("01") for _ in range(40)],
            })
        return columns

    def set_state(self, state):
        self._state = state
        self.update()

    def set_theme(self, theme):
        self._theme = theme if theme in _THEMES else "dark"
        self.update()

    def set_level(self, level):
        level = max(0.0, min(1.0, level))
        # Экспоненциальное сглаживание — движение выглядит живым, а не дёрганым.
        self._level = self._level * 0.55 + level * 0.45

    def _tick(self):
        self._phase += 0.12
        self._matrix_phase += 0.22
        self.update()

    def paintEvent(self, event):
        colors = _theme_colors(self._theme, self._state)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx = cy = self.GLOW_MARGIN + self.SIZE / 2
        base_r = self.SIZE * 0.22

        # Сплошная непрозрачная подложка — оверлей должен быть одинаково хорошо
        # виден и на тёмном, и на светлом рабочем столе, а не полагаться на
        # прозрачность, из-за которой он сливался с фоном по краям.
        bg = colors["bg"]
        border_w = 2.0
        grad_r = self.SIZE / 2 - border_w / 2
        p.setBrush(QBrush(QColor(bg.red(), bg.green(), bg.blue(), 255)))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(cx - grad_r, cy - grad_r, grad_r * 2, grad_r * 2))

        # Чёткая рамка круга — граница оверлея должна читаться независимо от
        # того, что находится под ним на экране.
        border_pen = QPen(colors["border"], border_w)
        p.setPen(border_pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(cx - grad_r, cy - grad_r, grad_r * 2, grad_r * 2))

        # Мягкое красное свечение снаружи рамки, как на референсе — резкий
        # переход держим у внешнего края рамки, дальше плавно гасим до нуля.
        border_color = colors["border"]
        outer_edge = grad_r + border_w / 2
        glow_r = outer_edge + self.GLOW_MARGIN
        glow_gradient = QRadialGradient(cx, cy, glow_r)
        edge_stop = max(0.0, min(1.0, outer_edge / glow_r))
        transparent = QColor(border_color.red(), border_color.green(), border_color.blue(), 0)
        glow_gradient.setColorAt(0.0, transparent)
        glow_gradient.setColorAt(edge_stop, transparent)
        glow_gradient.setColorAt(edge_stop, QColor(border_color.red(), border_color.green(), border_color.blue(), 150))
        glow_gradient.setColorAt(1.0, transparent)
        p.setBrush(QBrush(glow_gradient))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(cx - glow_r, cy - glow_r, glow_r * 2, glow_r * 2))

        if self._state == "recording":
            idle = 0.5 + 0.5 * math.sin(self._phase)
            voice = self._level

            outer_max = self.SIZE / 2 - 6
            gap = base_r * 0.18
            r_start = base_r + gap
            max_extent = max(0.0, outer_max - r_start)

            n_bars = self.N_BARS
            # Более узкие столбики с заметным зазором между ними — иначе на
            # малой громкости короткие "отдыхающие" полоски сливаются в
            # сплошное красное кольцо вместо отдельных штрихов на белом.
            bar_width = max(1.0, min(6.0, (2 * math.pi * r_start / n_bars) * 0.4))
            alpha = max(0, min(255, int(40 + 190 * voice)))
            bar_color = QColor(colors["ring"])
            bar_color.setAlpha(alpha)
            pen = QPen(bar_color)
            pen.setWidthF(bar_width)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)

            resting = max_extent * (0.03 + 0.02 * idle)
            for i in range(n_bars):
                # У каждого луча своя пара частот/фаз (см. _make_bar_wobble) — без этого
                # столбики "дышат" по общей формуле от индекса и выглядят одним узором,
                # скопированным по кругу, а не независимым эквалайзером.
                w = self._bar_wobble[i]
                wobble = 0.5 + 0.5 * (
                    0.6 * math.sin(self._phase * w["f1"] + w["p1"])
                    + 0.4 * math.sin(self._phase * w["f2"] + w["p2"])
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

            # Масштаб и смещение подобраны рендер-тестом по видимым краям иконки (bounding
            # box), чтобы отступы сверху и снизу внутри круга были одинаковыми.
            mic_scale = base_r / 162.0
            mic_offset = 227.5 * mic_scale
            _draw_mic(p, cx, cy - mic_offset, colors["mic"], scale=mic_scale)
        else:  # transcribing — «цифровой дождь» из 0/1, ярче к центру круга
            self._draw_matrix_rain(p, cx, cy, colors["ring"], base_r)

        p.end()

    def _draw_matrix_rain(self, p, cx, cy, color, base_r):
        radius = base_r * 1.7
        char_h = base_r * 0.24

        clip = QPainterPath()
        clip.addEllipse(QPointF(cx, cy), radius, radius)
        p.save()
        p.setClipPath(clip)

        font = QFont("monospace")
        font.setBold(True)
        font.setPixelSize(max(8, int(char_h * 0.9)))
        p.setFont(font)

        n_cols = len(self._matrix_columns)
        col_width = (radius * 2) / n_cols
        rows = int(radius * 2 / char_h) + self.MATRIX_TRAIL_LEN + 2

        for i, col in enumerate(self._matrix_columns):
            x = cx - radius + col_width * (i + 0.5)
            head = self._matrix_phase * col["speed"] * 4 + col["offset"]
            head_row = int(head) % rows

            for j in range(self.MATRIX_TRAIL_LEN):
                row = head_row - j
                y = cy - radius + row * char_h
                dist = math.hypot(x - cx, y - cy)
                if dist > radius:
                    continue
                edge_fade = max(0.0, 1.0 - (dist / radius) ** 1.4)
                trail_fade = max(0.0, 1.0 - j / self.MATRIX_TRAIL_LEN)
                alpha = edge_fade * trail_fade
                if alpha <= 0.02:
                    continue
                glyph_color = QColor(color)
                glyph_color.setAlphaF(min(1.0, alpha))
                p.setPen(glyph_color)
                ch = col["chars"][(head_row - j) % len(col["chars"])]
                # Символы ближе к центру круга крупнее — лёгкий эффект лупы,
                # к краю плавно сходящий к обычному размеру.
                lens = 1.0 + self.MATRIX_LENS_STRENGTH * max(0.0, 1.0 - dist / radius) ** 2
                p.save()
                p.translate(x, y)
                p.scale(lens, lens)
                p.drawText(
                    QRectF(-char_h, -char_h / 2, char_h * 2, char_h),
                    Qt.AlignCenter,
                    ch,
                )
                p.restore()
        p.restore()


class CapsuleIndicator(QWidget):
    """Горизонтальная капсула с «живым» эквалайзером и таймером записи —
    альтернативная форма оверлея в стиле голосовых заметок."""

    WIDTH = 240
    HEIGHT = 76
    SHADOW_MARGIN = 16
    N_BARS = 24

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.WIDTH + 2 * self.SHADOW_MARGIN, self.HEIGHT + 2 * self.SHADOW_MARGIN)
        self._state = "recording"
        self._theme = "dark"
        self._level = 0.0
        self._phase = 0.0
        self._elapsed = 0
        self._bar_wobble = self._make_bar_wobble()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

        # Настоящая мягкая размытая тень средствами Qt вместо ручных
        # concentric-колец — те выглядели слоями, а не единым размытием.
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 130))
        self.setGraphicsEffect(shadow)

    def _make_bar_wobble(self):
        rng = random.Random(4242)
        return [
            {
                "f1": rng.uniform(0.7, 1.9),
                "f2": rng.uniform(1.8, 3.6),
                "p1": rng.uniform(0, 2 * math.pi),
                "p2": rng.uniform(0, 2 * math.pi),
            }
            for _ in range(self.N_BARS)
        ]

    def set_state(self, state):
        self._state = state
        self.update()

    def set_theme(self, theme):
        self._theme = theme if theme in _CAPSULE_THEMES else "dark"
        self.update()

    def set_level(self, level):
        level = max(0.0, min(1.0, level))
        self._level = self._level * 0.55 + level * 0.45

    def set_elapsed(self, seconds):
        self._elapsed = max(0, int(seconds))
        self.update()

    def _tick(self):
        self._phase += 0.12
        self.update()

    def paintEvent(self, event):
        colors = _capsule_colors(self._theme)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        pill = QRectF(self.SHADOW_MARGIN, self.SHADOW_MARGIN, self.WIDTH, self.HEIGHT)
        radius = self.HEIGHT / 2

        self._draw_pill_background(p, pill, radius, colors)

        if self._state == "recording":
            self._draw_bars(p, pill, colors)
        else:
            self._draw_processing_wave(p, pill, colors)
        self._draw_timer(p, pill, colors)

        p.end()

    def _draw_pill_background(self, p, pill, radius, colors):
        """Обычная непрозрачная подложка. GlassCapsuleIndicator переопределяет
        этот метод, оставляя вместо заливки лишь лёгкую тонировку — сам блюр
        того, что под окном, делает композитор (KWin), а не мы."""
        p.setBrush(QBrush(colors["bg"]))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(pill, radius, radius)

    def _draw_bars(self, p, pill, colors):
        pad_left = pill.height() * 0.42
        wave_w = pill.width() * 0.5
        cy = pill.center().y()
        max_h = pill.height() * 0.6

        n = self.N_BARS
        spacing = wave_w / n
        bar_w = max(2.0, min(4.0, spacing * 0.55))
        voice = self._level

        pen = QPen(colors["wave"])
        pen.setWidthF(bar_w)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)

        resting = max_h * 0.08
        for i in range(n):
            w = self._bar_wobble[i]
            wobble = 0.5 + 0.5 * (
                0.6 * math.sin(self._phase * w["f1"] + w["p1"])
                + 0.4 * math.sin(self._phase * w["f2"] + w["p2"])
            )
            wobble = max(0.0, min(1.0, wobble))
            bar_h = resting + wobble * voice * max_h * 2.2
            bar_h = min(max_h, bar_h)

            x = pill.left() + pad_left + spacing * (i + 0.5)
            p.drawLine(QPointF(x, cy - bar_h / 2), QPointF(x, cy + bar_h / 2))

    def _draw_processing_wave(self, p, pill, colors):
        """Текущая синусоида вместо эквалайзера — визуально явно отличает
        «идёт распознавание» от живой реакции на голос при записи. Огибающая
        зафиксирована (выше в центре, ниже к краям капсулы), бежит только
        сама волна — так линия никогда не становится плоской."""
        pad_left = pill.height() * 0.42
        wave_w = pill.width() * 0.5
        cy = pill.center().y()
        amplitude = pill.height() * 0.22
        freq = 2.6

        n_points = 48
        path = QPainterPath()
        for i in range(n_points + 1):
            t = i / n_points
            x = pill.left() + pad_left + t * wave_w
            envelope = math.sin(math.pi * t)
            y = cy + amplitude * envelope * math.sin(2 * math.pi * freq * t - self._phase * 2.8)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)

        pen = QPen(colors["wave"])
        pen.setWidthF(max(2.5, pill.height() * 0.05))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

    def _draw_timer(self, p, pill, colors):
        minutes, seconds = divmod(self._elapsed, 60)
        text = f"{minutes}:{seconds:02d}"

        font = QFont("monospace")
        font.setBold(False)
        font.setPixelSize(max(10, int(pill.height() * 0.26)))
        p.setFont(font)
        p.setPen(colors["text"])

        text_rect = QRectF(
            pill.left() + pill.height() * 0.42 + pill.width() * 0.5 + 8,
            pill.top(),
            pill.right() - (pill.left() + pill.height() * 0.42 + pill.width() * 0.5 + 8) - pill.height() * 0.3,
            pill.height(),
        )
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)


# Тонировка стекла — чистый белый/почти чёрный, а не мутно-серый: живой цвет
# схемы KDE оказался «грязным» на глаз и, что хуже, не менялся вместе с
# выбором темы оверлея (тёмная/светлая), потому что читался из системы, а не
# из наших настроек. Теперь тонировка снова зависит от темы оверлея.
_GLASS_TINT = {
    "light": QColor(255, 255, 255),
    "dark": QColor(14, 15, 18),
}


class GlassCapsuleIndicator(CapsuleIndicator):
    """Та же капсула, но подложка — не сплошная заливка, а лёгкая тонировка
    поверх настоящего блюра KWin (см. set_kwin_blur_region): рабочий стол
    под окном размывает сам компоузитор, мы только тонируем и добавляем
    блик/ободок для стеклянного вида."""

    DEFAULT_OPACITY_PERCENT = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self._opacity_percent = self.DEFAULT_OPACITY_PERCENT

    def set_opacity(self, percent):
        self._opacity_percent = max(0, min(100, int(percent)))
        self.update()

    def _draw_pill_background(self, p, pill, radius, colors):
        pill_path = QPainterPath()
        pill_path.addRoundedRect(pill, radius, radius)

        tint = QColor(_GLASS_TINT.get(self._theme, _GLASS_TINT["dark"]))
        tint.setAlpha(round(self._opacity_percent / 100 * 255))
        p.save()
        p.setClipPath(pill_path)
        p.fillRect(pill, tint)
        p.restore()

        # Блик растягиваем на всю капсулу (не только верхнюю часть) — иначе
        # там, где заканчивался прямоугольник блика, был виден шов/полоса:
        # градиент ещё не успевал погаснуть до нуля, а прямоугольник уже
        # обрывался.
        grad = QRadialGradient(pill.center().x(), pill.top(), pill.width() * 0.7)
        grad.setColorAt(0.0, QColor(255, 255, 255, 60))
        grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.save()
        p.setClipPath(pill_path)
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawRect(pill)
        p.restore()

        rim = QPen(QColor(255, 255, 255, 70), 1.2)
        p.setPen(rim)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(pill.adjusted(0.6, 0.6, -0.6, -0.6), radius, radius)


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

        self._circle = PulseIndicator(self)
        self._capsule = CapsuleIndicator(self)
        self._capsule_glass = GlassCapsuleIndicator(self)
        self._capsule.hide()
        self._capsule_glass.hide()
        layout.addWidget(self._circle, 0, Qt.AlignHCenter)
        layout.addWidget(self._capsule, 0, Qt.AlignHCenter)
        layout.addWidget(self._capsule_glass, 0, Qt.AlignHCenter)

        self.text_label = QLabel(self)
        self.text_label.setWordWrap(True)
        self.text_label.setAlignment(Qt.AlignCenter)
        self.text_label.setMaximumWidth(360)
        self.text_label.hide()
        layout.addWidget(self.text_label, 0, Qt.AlignHCenter)

        self._show_text = False
        self._position = "center"
        self._theme = "dark"
        self._shape = "circle"
        self._apply_label_style()

    @property
    def indicator(self):
        if self._shape == "capsule":
            return self._capsule
        if self._shape == "capsule_glass":
            return self._capsule_glass
        return self._circle

    def set_position(self, position):
        self._position = position if position in POSITIONS else "center"

    def set_theme(self, theme):
        self._theme = theme if theme in _THEMES else "dark"
        self._circle.set_theme(self._theme)
        self._capsule.set_theme(self._theme)
        self._capsule_glass.set_theme(self._theme)
        self._apply_label_style()

    def set_shape(self, shape):
        self._shape = shape if shape in ("circle", "capsule", "capsule_glass") else "circle"
        self._circle.setVisible(self._shape == "circle")
        self._capsule.setVisible(self._shape == "capsule")
        self._capsule_glass.setVisible(self._shape == "capsule_glass")
        if self._shape != "capsule_glass":
            self._clear_blur_region()

    def set_glass_opacity(self, percent):
        self._capsule_glass.set_opacity(percent)

    def _apply_label_style(self):
        if self._theme == "light":
            style = (
                "QLabel {"
                "  color: #202024;"
                "  background-color: rgba(255, 255, 255, 235);"
                "  border: 2px solid rgba(220, 38, 38, 220);"
                "  border-radius: 10px;"
                "  padding: 10px 16px;"
                "  font-size: 14px;"
                "}"
            )
        else:
            style = (
                "QLabel {"
                "  color: #e8e8f0;"
                "  background-color: rgba(20, 20, 30, 235);"
                "  border: 2px solid rgba(255, 60, 60, 200);"
                "  border-radius: 10px;"
                "  padding: 10px 16px;"
                "  font-size: 14px;"
                "}"
            )
        self.text_label.setStyleSheet(style)

    def set_text_enabled(self, enabled):
        self._show_text = enabled
        if not enabled:
            self.text_label.hide()
            self.text_label.setText("")

    def show_recording(self):
        self.indicator.set_state("recording")
        self.indicator.set_level(0.0)
        if hasattr(self.indicator, "set_elapsed"):
            self.indicator.set_elapsed(0)
        if self._show_text:
            self.text_label.setText("")
            self.text_label.show()
        self._recenter_and_show()

    def _update_blur_region(self):
        if self._shape != "capsule_glass":
            return
        win_id = int(self.winId())
        margin = self._capsule_glass.SHADOW_MARGIN
        x = self._capsule_glass.x() + margin
        y = self._capsule_glass.y() + margin
        rects = _stadium_region_rects(x, y, self._capsule_glass.WIDTH, self._capsule_glass.HEIGHT)
        set_kwin_blur_region(win_id, rects)

    def _clear_blur_region(self):
        if not self.testAttribute(Qt.WA_WState_Created):
            return
        set_kwin_blur_region(int(self.winId()), None)

    def show_transcribing(self):
        self.indicator.set_state("transcribing")
        self._recenter_and_show()

    def set_level(self, level):
        self.indicator.set_level(level)

    def set_elapsed(self, seconds):
        if hasattr(self.indicator, "set_elapsed"):
            self.indicator.set_elapsed(seconds)

    def set_partial_text(self, text):
        if self._show_text:
            self.text_label.setText(text)
            self._recenter_and_show()

    def hide_overlay(self):
        self._clear_blur_region()
        self.hide()
        self.text_label.setText("")

    def _compute_position(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            return None
        geo = screen.availableGeometry()
        margin = 24
        fx, fy = POSITIONS.get(self._position, POSITIONS["center"])
        avail_w = max(0, geo.width() - self.width() - 2 * margin)
        avail_h = max(0, geo.height() - self.height() - 2 * margin)
        x = geo.x() + margin + int(fx * avail_w)
        y = geo.y() + margin + int(fy * avail_h)
        return x, y

    def _recenter_and_show(self):
        self.adjustSize()
        pos = self._compute_position()
        if pos is not None:
            self.move(*pos)
        self.show()
        self.raise_()
        # Регион блюра — в локальных координатах окна, поэтому обновляем его
        # каждый раз, когда меняется размер/раскладка (например, показался
        # или изменился текст живой транскрипции над капсулой).
        self._update_blur_region()
