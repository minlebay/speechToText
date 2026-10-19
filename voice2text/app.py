import json
import logging
import os
import subprocess
import sys
import threading
import time

from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QIcon, QPalette
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSlider,
    QSystemTrayIcon,
    QVBoxLayout,
)

from voice2text import __version__
from voice2text.config import get_api_key, get_deepgram_api_key, load_config, save_config, setup_logging
from voice2text.desktop import KeySender, get_selected_text, is_wayland, set_clipboard
from voice2text.hotkeys import KGlobalAccelHotkeys, hotkey_to_qt
from voice2text.icons import make_tray_icon
from voice2text.overlay import OverlayWindow, compute_level

log = logging.getLogger(__name__)
from voice2text.recorder import SAMPLE_RATE, Recorder


def _list_pulse_sources():
    """Returns [(description, pactl_source_name)] excluding monitor sources."""
    # Try JSON format (PulseAudio 15+ / PipeWire)
    try:
        r = subprocess.run(
            ["pactl", "--format=json", "list", "sources"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0:
            return [
                (s.get("description", s["name"]), s["name"])
                for s in json.loads(r.stdout)
                if not s.get("name", "").endswith(".monitor")
            ]
    except Exception:
        pass
    # Fallback: text parsing
    try:
        r = subprocess.run(["pactl", "list", "sources"], capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            result, name, desc = [], None, None
            for line in r.stdout.splitlines():
                line = line.strip()
                if line.startswith("Name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("Description:"):
                    desc = line.split(":", 1)[1].strip()
                    if name and not name.endswith(".monitor"):
                        result.append((desc, name))
                    name = desc = None
            return result
    except Exception:
        pass
    return []
from voice2text.deepgram_stream import DeepgramStream, is_flux
from voice2text.transcriber import transcribe, transcribe_gemini_code, unload_whisper_model


def _is_source_muted(source_name=None):
    target = source_name or "@DEFAULT_SOURCE@"
    try:
        r = subprocess.run(
            ["pactl", "get-source-mute", target],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0:
            return "yes" in r.stdout.lower()
    except Exception:
        pass
    return False


_OVERLAY_POSITIONS = [
    ("center", "По центру экрана"),
    ("top_left", "Верхний левый угол"),
    ("top_center", "По центру сверху"),
    ("top_right", "Верхний правый угол"),
    ("middle_left", "По центру слева"),
    ("middle_right", "По центру справа"),
    ("bottom_left", "Нижний левый угол"),
    ("bottom_center", "По центру снизу"),
    ("bottom_right", "Нижний правый угол"),
]

_OVERLAY_THEMES = [
    ("dark", "Тёмная"),
    ("light", "Светлая"),
]

_OVERLAY_SHAPES = [
    ("circle", "Круг"),
    ("capsule", "Капсула"),
    ("capsule_glass", "Капсула (стекло KWin)"),
]

_TRAY_MONO_VARIANTS = [
    ("auto", "Авто (по цвету панели)"),
    ("light", "Светлая (для тёмных панелей)"),
    ("dark", "Тёмная (для светлых панелей)"),
]


FINAL_TEXT_HOLD_MS = 800  # сколько показывать итоговый текст в оверлее после вставки


def _backend_api_key(backend):
    if backend == "gemini":
        return get_api_key()
    if backend == "deepgram":
        return get_deepgram_api_key()
    return ""


class SignalBridge(QObject):
    toggle_recording = pyqtSignal()
    toggle_code_recording = pyqtSignal()
    transcription_ready = pyqtSignal(str)
    partial_transcription_ready = pyqtSignal(str)
    error = pyqtSignal(str)


class DeviceMonitor(QObject):
    device_connected = pyqtSignal(str)
    device_disconnected = pyqtSignal(str)
    mute_changed = pyqtSignal(bool)

    def __init__(self, parent=None, device=None):
        super().__init__(parent)
        self._running = False
        self._device_lock = threading.Lock()
        self._device = device

    def start(self):
        self._running = True
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def stop(self):
        self._running = False

    def set_device(self, device):
        with self._device_lock:
            self._device = device

    def _current_device(self):
        with self._device_lock:
            return self._device

    @staticmethod
    def _input_device_names():
        return {name for _, name in _list_pulse_sources()}

    def _run(self):
        prev = self._input_device_names()
        prev_mute = _is_source_muted(self._current_device())
        self.mute_changed.emit(prev_mute)
        while self._running:
            time.sleep(2)
            curr = self._input_device_names()
            for name in curr - prev:
                self.device_connected.emit(name)
            for name in prev - curr:
                self.device_disconnected.emit(name)
            prev = curr

            curr_mute = _is_source_muted(self._current_device())
            if curr_mute != prev_mute:
                self.mute_changed.emit(curr_mute)
                prev_mute = curr_mute



class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Voice2Text — Настройки")
        self.config = dict(config)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.hotkey_edit = QLineEdit(config["hotkey"])
        form.addRow("Горячая клавиша:", self.hotkey_edit)

        self.code_hotkey_edit = QLineEdit(config.get("code_hotkey", "<ctrl>+<alt>+c"))
        form.addRow("Горячая клавиша (режим кода):", self.code_hotkey_edit)

        self.output_combo = QComboBox()
        self.output_combo.addItems(["paste", "clipboard"])
        self.output_combo.setCurrentText(config["output_mode"])
        form.addRow("Режим вывода:", self.output_combo)

        self.language_edit = QLineEdit(config["language"])
        form.addRow("Язык:", self.language_edit)

        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["whisper", "gemini", "google_stt", "deepgram"])
        self.backend_combo.setCurrentText(config.get("backend", "whisper"))
        form.addRow("Движок:", self.backend_combo)

        self.whisper_model_combo = QComboBox()
        self.whisper_model_combo.addItems(["tiny", "base", "small", "medium", "large-v3"])
        self.whisper_model_combo.setCurrentText(config.get("whisper_model", "base"))
        form.addRow("Whisper модель:", self.whisper_model_combo)

        self.gemini_model_combo = QComboBox()
        self.gemini_model_combo.addItems([
            "gemini-3.8-flash",
            "gemini-3.5-flash",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        ])
        self.gemini_model_combo.setCurrentText(config.get("gemini_model", "gemini-3.8-flash"))
        form.addRow("Gemini модель:", self.gemini_model_combo)

        self.deepgram_model_combo = QComboBox()
        self.deepgram_model_combo.addItems([
            "flux-general-multi",
            "nova-3",
        ])
        self.deepgram_model_combo.setToolTip(
            "flux-general-multi — потоковое распознавание во время записи, итог сразу после остановки.\n"
            "nova-3 — запись целиком отправляется после остановки."
        )
        self.deepgram_model_combo.setCurrentText(config.get("deepgram_model", "flux-general-multi"))
        form.addRow("Deepgram модель:", self.deepgram_model_combo)

        self.deepgram_multi_checkbox = QCheckBox(
            "Deepgram: мультиязычный режим — смешанная речь, например ru + en (flux и nova-3)"
        )
        self.deepgram_multi_checkbox.setChecked(config.get("deepgram_multilingual", True))
        form.addRow(self.deepgram_multi_checkbox)

        self.sanitize_checkbox = QCheckBox("Очищать текст от слов-паразитов (доступно только с движком Gemini)")
        self.sanitize_checkbox.setChecked(config.get("sanitize_fillers", False))
        form.addRow(self.sanitize_checkbox)
        self.backend_combo.currentTextChanged.connect(self._update_sanitize_availability)
        self._update_sanitize_availability(self.backend_combo.currentText())

        self.overlay_checkbox = QCheckBox("Показывать оверлей во время записи")
        self.overlay_checkbox.setChecked(config.get("show_overlay", False))
        form.addRow(self.overlay_checkbox)

        self.realtime_checkbox = QCheckBox("Показывать распознанный текст в реальном времени в оверлее")
        self.realtime_checkbox.setChecked(config.get("realtime_transcription", False))
        form.addRow(self.realtime_checkbox)

        self.overlay_position_combo = QComboBox()
        for value, label in _OVERLAY_POSITIONS:
            self.overlay_position_combo.addItem(label, value)
        current_position = config.get("overlay_position", "center")
        idx = self.overlay_position_combo.findData(current_position)
        self.overlay_position_combo.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow("Положение оверлея:", self.overlay_position_combo)

        self.overlay_theme_combo = QComboBox()
        for value, label in _OVERLAY_THEMES:
            self.overlay_theme_combo.addItem(label, value)
        current_theme = config.get("overlay_theme", "dark")
        idx = self.overlay_theme_combo.findData(current_theme)
        self.overlay_theme_combo.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow("Тема оверлея:", self.overlay_theme_combo)

        self.overlay_shape_combo = QComboBox()
        for value, label in _OVERLAY_SHAPES:
            self.overlay_shape_combo.addItem(label, value)
        current_shape = config.get("overlay_shape", "circle")
        idx = self.overlay_shape_combo.findData(current_shape)
        self.overlay_shape_combo.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow("Форма оверлея:", self.overlay_shape_combo)

        glass_opacity_row = QHBoxLayout()
        self.glass_opacity_slider = QSlider(Qt.Horizontal)
        self.glass_opacity_slider.setRange(0, 100)
        self.glass_opacity_slider.setValue(config.get("overlay_glass_opacity", 30))
        self.glass_opacity_label = QLabel(f"{self.glass_opacity_slider.value()}%")
        self.glass_opacity_label.setMinimumWidth(36)
        self.glass_opacity_slider.valueChanged.connect(
            lambda v: self.glass_opacity_label.setText(f"{v}%")
        )
        glass_opacity_row.addWidget(self.glass_opacity_slider)
        glass_opacity_row.addWidget(self.glass_opacity_label)
        form.addRow("Прозрачность стекла:", glass_opacity_row)

        self.overlay_checkbox.toggled.connect(self._update_realtime_availability)
        self.overlay_checkbox.toggled.connect(self.overlay_position_combo.setEnabled)
        self.overlay_checkbox.toggled.connect(self.overlay_theme_combo.setEnabled)
        self.overlay_checkbox.toggled.connect(self.overlay_shape_combo.setEnabled)
        self.overlay_checkbox.toggled.connect(self.glass_opacity_slider.setEnabled)
        self.overlay_position_combo.setEnabled(self.overlay_checkbox.isChecked())
        self.overlay_theme_combo.setEnabled(self.overlay_checkbox.isChecked())
        self.overlay_shape_combo.setEnabled(self.overlay_checkbox.isChecked())
        self.glass_opacity_slider.setEnabled(self.overlay_checkbox.isChecked())
        self._update_realtime_availability(self.overlay_checkbox.isChecked())

        self.tray_mono_checkbox = QCheckBox("Монохромная иконка в трее")
        self.tray_mono_checkbox.setChecked(config.get("tray_icon_monochrome", False))
        form.addRow(self.tray_mono_checkbox)

        self.tray_mono_variant_combo = QComboBox()
        for value, label in _TRAY_MONO_VARIANTS:
            self.tray_mono_variant_combo.addItem(label, value)
        current_mono_variant = config.get("tray_icon_mono_variant", "light")
        idx = self.tray_mono_variant_combo.findData(current_mono_variant)
        self.tray_mono_variant_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.tray_mono_variant_combo.setEnabled(self.tray_mono_checkbox.isChecked())
        self.tray_mono_checkbox.toggled.connect(self.tray_mono_variant_combo.setEnabled)
        form.addRow("Цвет монохромной иконки:", self.tray_mono_variant_combo)

        self.device_combo = QComboBox()
        self.device_combo.addItem("По умолчанию (системное)", None)
        for desc, name in _list_pulse_sources():
            self.device_combo.addItem(desc, name)
        current_device = config.get("audio_device")
        if current_device:
            idx = self.device_combo.findData(current_device)
            self.device_combo.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow("Устройство записи:", self.device_combo)

        version_label = QLabel(__version__)
        version_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("Версия:", version_label)

        layout.addLayout(form)

        buttons = QHBoxLayout()
        save_btn = QPushButton("Сохранить")
        cancel_btn = QPushButton("Отмена")
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

    def _update_sanitize_availability(self, backend):
        enabled = backend == "gemini"
        self.sanitize_checkbox.setEnabled(enabled)

    def _update_realtime_availability(self, overlay_enabled):
        self.realtime_checkbox.setEnabled(overlay_enabled)

    def get_config(self):
        return {
            "hotkey": self.hotkey_edit.text(),
            "code_hotkey": self.code_hotkey_edit.text(),
            "output_mode": self.output_combo.currentText(),
            "language": self.language_edit.text(),
            "backend": self.backend_combo.currentText(),
            "whisper_model": self.whisper_model_combo.currentText(),
            "gemini_model": self.gemini_model_combo.currentText(),
            "deepgram_model": self.deepgram_model_combo.currentText(),
            "deepgram_multilingual": self.deepgram_multi_checkbox.isChecked(),
            "audio_device": self.device_combo.currentData(),
            "sanitize_fillers": self.sanitize_checkbox.isChecked(),
            "show_overlay": self.overlay_checkbox.isChecked(),
            "realtime_transcription": self.overlay_checkbox.isChecked() and self.realtime_checkbox.isChecked(),
            "overlay_position": self.overlay_position_combo.currentData(),
            "overlay_theme": self.overlay_theme_combo.currentData(),
            "overlay_shape": self.overlay_shape_combo.currentData(),
            "overlay_glass_opacity": self.glass_opacity_slider.value(),
            "tray_icon_monochrome": self.tray_mono_checkbox.isChecked(),
            "tray_icon_mono_variant": self.tray_mono_variant_combo.currentData(),
        }


class App:
    def __init__(self, qt_app):
        self.qt_app = qt_app
        self.config = load_config()
        self.state = "idle"
        log.info("Инициализация приложения, конфиг: %s", self.config)
        self.recorder = Recorder(device=self.config.get("audio_device"))
        self.signals = SignalBridge()
        self._mic_muted = False
        self._code_mode = False
        self._code_selection = ""
        self.device_monitor = DeviceMonitor(device=self.config.get("audio_device"))
        self.keys = KeySender()
        self._kglobalaccel = None
        if is_wayland():
            if KGlobalAccelHotkeys.is_available():
                self._kglobalaccel = KGlobalAccelHotkeys()
                self._kglobalaccel.activated.connect(self._on_global_shortcut)
            else:
                log.warning("Wayland без KGlobalAccel: хоткеи pynput сработают только в X11-окнах")
        self.tray = QSystemTrayIcon(self._tray_icon("idle"))
        self.tray.setToolTip("Voice2Text — Готов")
        self.qt_app.paletteChanged.connect(self._on_palette_changed)

        self.overlay = OverlayWindow()
        self.overlay.set_position(self.config.get("overlay_position", "center"))
        self.overlay.set_theme(self.config.get("overlay_theme", "dark"))
        self.overlay.set_shape(self.config.get("overlay_shape", "circle"))
        self.overlay.set_glass_opacity(self.config.get("overlay_glass_opacity", 30))
        self._partial_in_progress = False
        self._record_start_time = None
        self._dg_stream = None
        self._level_timer = QTimer()
        self._level_timer.setInterval(80)
        self._level_timer.timeout.connect(self._update_level)
        self._live_timer = QTimer()
        self._live_timer.setInterval(2500)
        self._live_timer.timeout.connect(self._trigger_partial_transcription)

        menu = QMenu()
        settings_action = menu.addAction("Настройки")
        settings_action.triggered.connect(self._open_settings)
        quit_action = menu.addAction("Выход")
        quit_action.triggered.connect(QApplication.quit)
        self.tray.setContextMenu(menu)
        self.tray.show()

        self.signals.toggle_recording.connect(lambda: self._on_toggle(code_mode=False))
        self.signals.toggle_code_recording.connect(lambda: self._on_toggle(code_mode=True))
        self.signals.transcription_ready.connect(self._on_transcription)
        self.signals.partial_transcription_ready.connect(self._on_partial_transcription)
        self.signals.error.connect(self._on_error)
        self.device_monitor.device_connected.connect(self._on_device_connected)
        self.device_monitor.device_disconnected.connect(self._on_device_disconnected)
        self.device_monitor.mute_changed.connect(self._on_mute_changed)
        self.device_monitor.start()

        self._start_hotkey_listener()
        self.qt_app.aboutToQuit.connect(self._stop_hotkey_listener)
        if self.keys.error:
            self.tray.showMessage("Voice2Text", self.keys.error, QSystemTrayIcon.Warning, 5000)

    def _tray_icon(self, state):
        variant = self.config.get("tray_icon_mono_variant", "auto")
        if variant == "auto":
            variant = self._detect_panel_variant()
        return make_tray_icon(
            state,
            monochrome=self.config.get("tray_icon_monochrome", False),
            mono_variant=variant,
            muted=self._mic_muted,
        )

    def _detect_panel_variant(self):
        """Определяет, светлая или тёмная сейчас цветовая схема (Plasma/GTK
        применяют её и к палитре Qt-приложений), чтобы выбрать контрастный
        цвет для монохромной иконки — светлый силуэт для тёмных панелей,
        тёмный для светлых."""
        color = self.qt_app.palette().color(QPalette.Window)
        luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
        return "dark" if luminance > 140 else "light"

    def _on_palette_changed(self, _palette):
        self.tray.setIcon(self._tray_icon(self.state))

    def _on_mute_changed(self, muted):
        self._mic_muted = muted
        self.tray.setIcon(self._tray_icon(self.state))
        tooltip_suffix = " (микрофон заглушен)" if muted else ""
        self.tray.setToolTip(self.tray.toolTip().split(" (микрофон")[0] + tooltip_suffix)

    def _validate_hotkey(self, hotkey, default, config_key):
        if self._kglobalaccel is not None:
            error = None if hotkey_to_qt(hotkey) is not None else "не разбирается как сочетание Qt"
        else:
            from pynput.keyboard import GlobalHotKeys

            try:
                GlobalHotKeys({hotkey: lambda: None})
                error = None
            except (ValueError, KeyError) as e:
                error = e
        if error is None:
            return hotkey
        log.error("Неверная горячая клавиша '%s': %s, откат на %s", hotkey, error, default)
        self.tray.showMessage(
            "Voice2Text",
            f"Неверная горячая клавиша \"{hotkey}\", используется {default}",
            QSystemTrayIcon.Warning,
            5000,
        )
        self.config[config_key] = default
        save_config(self.config)
        return default

    def _start_hotkey_listener(self):
        hotkey = self._validate_hotkey(self.config["hotkey"], "<ctrl>+<alt>+h", "hotkey")
        code_hotkey = self._validate_hotkey(
            self.config.get("code_hotkey", "<ctrl>+<alt>+c"), "<ctrl>+<alt>+c", "code_hotkey"
        )
        log.info("Регистрация горячих клавиш: %s (запись), %s (код)", hotkey, code_hotkey)
        if self._kglobalaccel is not None:
            for action, key, label in (
                ("toggle_recording", hotkey, "Начать/остановить запись"),
                ("toggle_code_recording", code_hotkey, "Запись в режиме кода"),
            ):
                if not self._kglobalaccel.register(action, label, hotkey_to_qt(key)):
                    log.error("KDE не принял сочетание %s для %s", key, action)
                    self.tray.showMessage(
                        "Voice2Text",
                        f"Сочетание \"{key}\" занято другим приложением KDE — выберите другое в настройках",
                        QSystemTrayIcon.Warning,
                        5000,
                    )
            return

        from pynput.keyboard import GlobalHotKeys

        self._hotkey_listener = GlobalHotKeys({
            hotkey: lambda: self.signals.toggle_recording.emit(),
            code_hotkey: lambda: self.signals.toggle_code_recording.emit(),
        })
        self._hotkey_listener.daemon = True
        self._hotkey_listener.start()

    def _stop_hotkey_listener(self):
        if self._kglobalaccel is not None:
            self._kglobalaccel.release()
        elif hasattr(self, "_hotkey_listener"):
            self._hotkey_listener.stop()

    def _on_global_shortcut(self, action):
        if action == "toggle_recording":
            self.signals.toggle_recording.emit()
        elif action == "toggle_code_recording":
            self.signals.toggle_code_recording.emit()

    def _on_toggle(self, code_mode=False):
        log.debug("Хоткей нажат, текущее состояние: %s, code_mode=%s", self.state, code_mode)
        if self.state == "idle":
            if code_mode:
                if not get_api_key():
                    self.tray.showMessage(
                        "Voice2Text",
                        "API ключ не установлен. Задайте переменную окружения GEMINI_API_KEY_TTS.",
                        QSystemTrayIcon.Warning,
                        3000,
                    )
                    return
            else:
                backend = self.config.get("backend", "whisper")
                if backend == "gemini":
                    api_key = get_api_key()
                    if not api_key:
                        self.tray.showMessage(
                            "Voice2Text",
                            "API ключ не установлен. Задайте переменную окружения GEMINI_API_KEY_TTS.",
                            QSystemTrayIcon.Warning,
                            3000,
                        )
                        return
                elif backend == "deepgram":
                    if not get_deepgram_api_key():
                        self.tray.showMessage(
                            "Voice2Text",
                            "API ключ не установлен. Задайте переменную окружения DEEPGRAM_VOICETOTEXT_KEY.",
                            QSystemTrayIcon.Warning,
                            3000,
                        )
                        return
                elif backend == "google_stt":
                    import os
                    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
                        self.tray.showMessage(
                            "Voice2Text",
                            "Не задан GOOGLE_APPLICATION_CREDENTIALS. Укажите путь к JSON сервисного аккаунта.",
                            QSystemTrayIcon.Warning,
                            3000,
                        )
                        return
            try:
                self.recorder.start()
            except RuntimeError as e:
                log.error("Ошибка начала записи: %s", e)
                self.tray.showMessage("Voice2Text — Ошибка", str(e), QSystemTrayIcon.Critical, 5000)
                return
            self.state = "recording"
            self._code_mode = code_mode
            self._code_selection = get_selected_text() if code_mode else ""
            self.tray.setIcon(self._tray_icon("recording"))
            status = "Запись кода..." if code_mode else "Запись..."
            self.tray.setToolTip(f"Voice2Text — {status}")
            self.tray.showMessage("Voice2Text", status, QSystemTrayIcon.Information, 1500)

            self._record_start_time = time.time()
            realtime = self.config.get("show_overlay") and self.config.get("realtime_transcription", False)
            deepgram = not code_mode and self.config.get("backend") == "deepgram"
            # Flux стримит всегда (итог готов сразу после остановки), Nova — только ради живого текста
            if deepgram and (realtime or is_flux(self.config.get("deepgram_model", "flux-general-multi"))):
                self._start_deepgram_stream()
            if self.config.get("show_overlay"):
                self.overlay.set_text_enabled(self.config.get("realtime_transcription", False))
                self.overlay.show_recording()
                self._level_timer.start()
                if realtime and not deepgram:
                    self._live_timer.start()
        elif self.state == "recording":
            self._level_timer.stop()
            self._live_timer.stop()
            audio_data = self.recorder.stop()
            dg_stream, self._dg_stream = self._dg_stream, None
            self.state = "transcribing"
            self.tray.setIcon(self._tray_icon("transcribing"))
            self.tray.setToolTip("Voice2Text — Обработка...")
            if self.config.get("show_overlay"):
                self.overlay.show_transcribing()

            if self._code_mode:
                api_key = get_api_key()
                gemini_model = self.config.get("gemini_model", "gemini-3.8-flash")

                context_code = self._code_selection

                def worker():
                    try:
                        text = transcribe_gemini_code(audio_data, api_key=api_key, model=gemini_model,
                                                       context_code=context_code)
                        self.signals.transcription_ready.emit(text)
                    except Exception as e:
                        self.signals.error.emit(str(e))
            else:
                language = self.config["language"]
                backend = self.config.get("backend", "whisper")
                api_key = _backend_api_key(backend)
                whisper_model = self.config.get("whisper_model", "base")
                gemini_model = self.config.get("gemini_model", "gemini-3.8-flash")
                deepgram_model = self.config.get("deepgram_model", "flux-general-multi")
                deepgram_multilingual = self.config.get("deepgram_multilingual", True)
                sanitize_fillers = backend == "gemini" and self.config.get("sanitize_fillers", False)

                def worker():
                    try:
                        if dg_stream is not None:
                            text = dg_stream.finish(audio_data[44:])
                            if text is not None:
                                self.signals.transcription_ready.emit(text)
                                return
                            log.warning("Deepgram стрим не удался, повтор обычным запросом")
                        text = transcribe(audio_data, language=language, backend=backend,
                                          api_key=api_key, whisper_model=whisper_model,
                                          gemini_model=gemini_model, sanitize_fillers=sanitize_fillers,
                                          deepgram_model=deepgram_model,
                                          deepgram_multilingual=deepgram_multilingual)
                        self.signals.transcription_ready.emit(text)
                    except Exception as e:
                        self.signals.error.emit(str(e))

            t = threading.Thread(target=worker, daemon=True)
            t.start()

    def _on_transcription(self, text):
        log.info("Транскрипция получена: %d символов", len(text))
        set_clipboard(text)

        if self.config["output_mode"] == "paste":
            if self._code_mode and self._code_selection.strip():
                log.debug("Снятие выделения (без удаления) и переход на новую строку перед вставкой кода")
                self.keys.send("Right")
                self.keys.send("Return")
            log.debug("Вставка через Ctrl+V")
            self.keys.send("ctrl+v")

        preview = text[:50] + ("..." if len(text) > 50 else "")
        self.tray.showMessage("Voice2Text", preview, QSystemTrayIcon.Information, 3000)
        self.state = "idle"
        self.tray.setIcon(self._tray_icon("idle"))
        self.tray.setToolTip("Voice2Text — Готов")
        if self.overlay.has_text():
            # Последние слова стрим присылает уже после остановки — показываем
            # итог целиком и даём его увидеть, прежде чем спрятать оверлей.
            self.overlay.set_partial_text(text)
            QTimer.singleShot(FINAL_TEXT_HOLD_MS, self._hide_overlay_if_idle)
        else:
            self.overlay.hide_overlay()

    def _hide_overlay_if_idle(self):
        if self.state == "idle":
            self.overlay.hide_overlay()

    def _on_error(self, msg):
        log.error("Ошибка: %s", msg)
        self.tray.showMessage("Voice2Text — Ошибка", msg, QSystemTrayIcon.Critical, 5000)
        self.state = "idle"
        self.tray.setIcon(self._tray_icon("idle"))
        self.tray.setToolTip("Voice2Text — Готов")
        self._level_timer.stop()
        self._live_timer.stop()
        if self._dg_stream is not None:
            self._dg_stream.cancel()
            self._dg_stream = None
        self.overlay.hide_overlay()

    def _update_level(self):
        pcm = self.recorder.read_level_window()
        self.overlay.set_level(compute_level(pcm))
        if self._record_start_time is not None:
            self.overlay.set_elapsed(time.time() - self._record_start_time)

    def _start_deepgram_stream(self):
        self._dg_stream = DeepgramStream(
            api_key=get_deepgram_api_key(),
            read_pcm=self.recorder.read_pcm,
            on_text=self.signals.partial_transcription_ready.emit,
            model=self.config.get("deepgram_model", "flux-general-multi"),
            language=self.config["language"],
            multilingual=self.config.get("deepgram_multilingual", True),
            sample_rate=SAMPLE_RATE,
            channels=self.recorder.channels,
        )
        self._dg_stream.start()

    def _trigger_partial_transcription(self):
        if self._partial_in_progress or self.state != "recording":
            return
        wav_bytes = self.recorder.read_partial_wav()
        if len(wav_bytes) <= 44:
            return
        self._partial_in_progress = True

        language = self.config["language"]
        backend = self.config.get("backend", "whisper")
        api_key = _backend_api_key(backend)
        whisper_model = self.config.get("whisper_model", "base")
        gemini_model = self.config.get("gemini_model", "gemini-3.8-flash")
        deepgram_model = self.config.get("deepgram_model", "flux-general-multi")
        deepgram_multilingual = self.config.get("deepgram_multilingual", True)

        def worker():
            try:
                text = transcribe(wav_bytes, language=language, backend=backend,
                                  api_key=api_key, whisper_model=whisper_model,
                                  gemini_model=gemini_model, sanitize_fillers=False,
                                  deepgram_model=deepgram_model,
                                  deepgram_multilingual=deepgram_multilingual)
                self.signals.partial_transcription_ready.emit(text)
            except Exception as e:
                log.debug("Частичная транскрипция не удалась: %s", e)
            finally:
                self._partial_in_progress = False

        threading.Thread(target=worker, daemon=True).start()

    def _on_partial_transcription(self, text):
        if self.state in ("recording", "transcribing"):
            self.overlay.set_partial_text(text)

    def _on_device_connected(self, name):
        preferred = self.config.get("audio_device")
        if preferred and name == preferred:
            self.recorder.set_device(name)
            log.info("Предпочитаемое устройство подключено: %s", name)
            self.tray.showMessage("Voice2Text", f"Микрофон подключён: {name}", QSystemTrayIcon.Information, 3000)

    def _on_device_disconnected(self, name):
        preferred = self.config.get("audio_device")
        if preferred and name == preferred:
            self.recorder.set_device(None)
            log.info("Предпочитаемое устройство отключено: %s, переключение на системное", name)
            self.tray.showMessage(
                "Voice2Text", f"Микрофон отключён: {name}. Используется системное устройство.",
                QSystemTrayIcon.Warning, 4000,
            )

    def _open_settings(self):
        dialog = SettingsDialog(self.config)
        if dialog.exec_() == QDialog.Accepted:
            new_config = dialog.get_config()
            old_hotkey = self.config["hotkey"]
            old_code_hotkey = self.config.get("code_hotkey", "<ctrl>+<alt>+c")
            old_device = self.config.get("audio_device")
            old_backend = self.config.get("backend", "whisper")
            self.config = new_config
            save_config(new_config)
            if old_backend == "whisper" and new_config.get("backend") != "whisper":
                unload_whisper_model()
            if new_config["hotkey"] != old_hotkey or new_config.get("code_hotkey") != old_code_hotkey:
                self._stop_hotkey_listener()
                self._start_hotkey_listener()
            if new_config.get("audio_device") != old_device:
                self.recorder.set_device(new_config.get("audio_device"))
                self.device_monitor.set_device(new_config.get("audio_device"))
            self.overlay.set_position(new_config.get("overlay_position", "center"))
            self.overlay.set_theme(new_config.get("overlay_theme", "dark"))
            self.overlay.set_shape(new_config.get("overlay_shape", "circle"))
            self.overlay.set_glass_opacity(new_config.get("overlay_glass_opacity", 30))
            self.tray.setIcon(self._tray_icon(self.state))


def main():
    import ctypes
    try:
        ctypes.CDLL("libc.so.6").prctl(15, b"voice2text", 0, 0, 0)
    except Exception:
        pass

    setup_logging()
    log.info("Запуск Voice2Text")

    if is_wayland():
        # Окна приложения — X11-клиенты через XWayland: у Wayland-окна Qt5
        # нельзя задать позицию, «поверх всех» и отказ от фокуса, а без них
        # оверлей встаёт куда решит KWin и может увести фокус из окна, куда
        # затем вставляется текст. Нативный блюр KWin тоже работает только
        # через X11-свойство окна (см. overlay.set_kwin_blur_region).
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
        log.info("Wayland-сессия: Qt через %s", os.environ["QT_QPA_PLATFORM"])

    app = QApplication(["voice2text"])

    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.error("Системный трей недоступен")
        return 1

    app.setQuitOnLastWindowClosed(False)
    voice_app = App(app)  # noqa: F841
    return app.exec_()
