import json
import logging
import subprocess
import sys
import threading
import time

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
)

from voice2text.config import get_api_key, load_config, save_config, setup_logging
from voice2text.icons import make_tray_icon

log = logging.getLogger(__name__)
from voice2text.recorder import Recorder


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
from voice2text.transcriber import transcribe


class SignalBridge(QObject):
    toggle_recording = pyqtSignal()
    transcription_ready = pyqtSignal(str)
    error = pyqtSignal(str)


class DeviceMonitor(QObject):
    device_connected = pyqtSignal(str)
    device_disconnected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False

    def start(self):
        self._running = True
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def stop(self):
        self._running = False

    @staticmethod
    def _input_device_names():
        return {name for _, name in _list_pulse_sources()}

    def _run(self):
        prev = self._input_device_names()
        while self._running:
            time.sleep(2)
            curr = self._input_device_names()
            for name in curr - prev:
                self.device_connected.emit(name)
            for name in prev - curr:
                self.device_disconnected.emit(name)
            prev = curr



class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Voice2Text — Настройки")
        self.config = dict(config)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.hotkey_edit = QLineEdit(config["hotkey"])
        form.addRow("Горячая клавиша:", self.hotkey_edit)

        self.output_combo = QComboBox()
        self.output_combo.addItems(["paste", "clipboard"])
        self.output_combo.setCurrentText(config["output_mode"])
        form.addRow("Режим вывода:", self.output_combo)

        self.language_edit = QLineEdit(config["language"])
        form.addRow("Язык:", self.language_edit)

        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["whisper", "gemini", "google_stt"])
        self.backend_combo.setCurrentText(config.get("backend", "whisper"))
        form.addRow("Движок:", self.backend_combo)

        self.whisper_model_combo = QComboBox()
        self.whisper_model_combo.addItems(["tiny", "base", "small", "medium", "large-v3"])
        self.whisper_model_combo.setCurrentText(config.get("whisper_model", "base"))
        form.addRow("Whisper модель:", self.whisper_model_combo)

        self.gemini_model_combo = QComboBox()
        self.gemini_model_combo.addItems([
            "gemini-3.5-flash",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        ])
        self.gemini_model_combo.setCurrentText(config.get("gemini_model", "gemini-3.5-flash"))
        form.addRow("Gemini модель:", self.gemini_model_combo)

        self.device_combo = QComboBox()
        self.device_combo.addItem("По умолчанию (системное)", None)
        for desc, name in _list_pulse_sources():
            self.device_combo.addItem(desc, name)
        current_device = config.get("audio_device")
        if current_device:
            idx = self.device_combo.findData(current_device)
            self.device_combo.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow("Устройство записи:", self.device_combo)

        layout.addLayout(form)

        buttons = QHBoxLayout()
        save_btn = QPushButton("Сохранить")
        cancel_btn = QPushButton("Отмена")
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

    def get_config(self):
        return {
            "hotkey": self.hotkey_edit.text(),
            "output_mode": self.output_combo.currentText(),
            "language": self.language_edit.text(),
            "backend": self.backend_combo.currentText(),
            "whisper_model": self.whisper_model_combo.currentText(),
            "gemini_model": self.gemini_model_combo.currentText(),
            "audio_device": self.device_combo.currentData(),
        }


class App:
    def __init__(self, qt_app):
        self.qt_app = qt_app
        self.config = load_config()
        self.state = "idle"
        log.info("Инициализация приложения, конфиг: %s", self.config)
        self.recorder = Recorder(device=self.config.get("audio_device"))
        self.signals = SignalBridge()
        self.device_monitor = DeviceMonitor()
        self.tray = QSystemTrayIcon(make_tray_icon("idle"))
        self.tray.setToolTip("Voice2Text — Готов")

        menu = QMenu()
        settings_action = menu.addAction("Настройки")
        settings_action.triggered.connect(self._open_settings)
        quit_action = menu.addAction("Выход")
        quit_action.triggered.connect(QApplication.quit)
        self.tray.setContextMenu(menu)
        self.tray.show()

        self.signals.toggle_recording.connect(self._on_toggle)
        self.signals.transcription_ready.connect(self._on_transcription)
        self.signals.error.connect(self._on_error)
        self.device_monitor.device_connected.connect(self._on_device_connected)
        self.device_monitor.device_disconnected.connect(self._on_device_disconnected)
        self.device_monitor.start()

        self._start_hotkey_listener()

    def _start_hotkey_listener(self):
        from pynput.keyboard import GlobalHotKeys

        hotkey = self.config["hotkey"]
        try:
            log.info("Регистрация горячей клавиши: %s", hotkey)
            self._hotkey_listener = GlobalHotKeys(
                {hotkey: lambda: self.signals.toggle_recording.emit()}
            )
            self._hotkey_listener.daemon = True
            self._hotkey_listener.start()
        except (ValueError, KeyError) as e:
            default_hotkey = "<ctrl>+<alt>+h"
            log.error("Неверная горячая клавиша '%s': %s, откат на %s", hotkey, e, default_hotkey)
            self.tray.showMessage(
                "Voice2Text",
                f"Неверная горячая клавиша \"{hotkey}\", используется {default_hotkey}",
                QSystemTrayIcon.Warning,
                5000,
            )
            self.config["hotkey"] = default_hotkey
            save_config(self.config)
            self._hotkey_listener = GlobalHotKeys(
                {default_hotkey: lambda: self.signals.toggle_recording.emit()}
            )
            self._hotkey_listener.daemon = True
            self._hotkey_listener.start()

    def _stop_hotkey_listener(self):
        if hasattr(self, "_hotkey_listener"):
            self._hotkey_listener.stop()

    def _on_toggle(self):
        log.debug("Хоткей нажат, текущее состояние: %s", self.state)
        if self.state == "idle":
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
            self.tray.setIcon(make_tray_icon("recording"))
            self.tray.setToolTip("Voice2Text — Запись...")
            self.tray.showMessage("Voice2Text", "Запись...", QSystemTrayIcon.Information, 1500)
        elif self.state == "recording":
            audio_data = self.recorder.stop()
            self.state = "transcribing"
            self.tray.setIcon(make_tray_icon("transcribing"))
            self.tray.setToolTip("Voice2Text — Обработка...")

            language = self.config["language"]
            backend = self.config.get("backend", "whisper")
            api_key = get_api_key() if backend == "gemini" else ""
            whisper_model = self.config.get("whisper_model", "base")
            gemini_model = self.config.get("gemini_model", "gemini-2.5-flash")

            def worker():
                try:
                    text = transcribe(audio_data, language=language, backend=backend,
                                      api_key=api_key, whisper_model=whisper_model,
                                      gemini_model=gemini_model)
                    self.signals.transcription_ready.emit(text)
                except Exception as e:
                    self.signals.error.emit(str(e))

            t = threading.Thread(target=worker, daemon=True)
            t.start()

    def _on_transcription(self, text):
        log.info("Транскрипция получена: %d символов", len(text))
        clipboard = QApplication.clipboard()
        clipboard.setText(text)

        if self.config["output_mode"] == "paste":
            log.debug("Вставка через xdotool")
            subprocess.Popen(["xdotool", "key", "--clearmodifiers", "ctrl+v"])

        preview = text[:50] + ("..." if len(text) > 50 else "")
        self.tray.showMessage("Voice2Text", preview, QSystemTrayIcon.Information, 3000)
        self.state = "idle"
        self.tray.setIcon(make_tray_icon("idle"))
        self.tray.setToolTip("Voice2Text — Готов")

    def _on_error(self, msg):
        log.error("Ошибка: %s", msg)
        self.tray.showMessage("Voice2Text — Ошибка", msg, QSystemTrayIcon.Critical, 5000)
        self.state = "idle"
        self.tray.setIcon(make_tray_icon("idle"))
        self.tray.setToolTip("Voice2Text — Готов")

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
            old_device = self.config.get("audio_device")
            self.config = new_config
            save_config(new_config)
            if new_config["hotkey"] != old_hotkey:
                self._stop_hotkey_listener()
                self._start_hotkey_listener()
            if new_config.get("audio_device") != old_device:
                self.recorder.set_device(new_config.get("audio_device"))


def main():
    import ctypes
    try:
        ctypes.CDLL("libc.so.6").prctl(15, b"voice2text", 0, 0, 0)
    except Exception:
        pass

    setup_logging()
    log.info("Запуск Voice2Text")

    app = QApplication(["voice2text"])

    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.error("Системный трей недоступен")
        return 1

    app.setQuitOnLastWindowClosed(False)
    voice_app = App(app)  # noqa: F841
    return app.exec_()
