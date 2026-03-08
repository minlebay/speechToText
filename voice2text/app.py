import logging
import subprocess
import sys
import threading

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
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

log = logging.getLogger(__name__)
from voice2text.recorder import Recorder
from voice2text.transcriber import transcribe


class SignalBridge(QObject):
    toggle_recording = pyqtSignal()
    transcription_ready = pyqtSignal(str)
    error = pyqtSignal(str)


def make_icon(color):
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(QColor(color))
    painter.drawEllipse(4, 4, 56, 56)
    painter.end()
    return QIcon(pixmap)


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
        }


class App:
    def __init__(self, qt_app):
        self.qt_app = qt_app
        self.config = load_config()
        self.state = "idle"
        log.info("Инициализация приложения, конфиг: %s", self.config)
        self.recorder = Recorder()
        self.signals = SignalBridge()
        self.tray = QSystemTrayIcon(make_icon("green"))
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
            self.tray.setIcon(make_icon("red"))
            self.tray.setToolTip("Voice2Text — Запись...")
            self.tray.showMessage("Voice2Text", "Запись...", QSystemTrayIcon.Information, 1500)
        elif self.state == "recording":
            audio_data = self.recorder.stop()
            self.state = "transcribing"
            self.tray.setIcon(make_icon("yellow"))
            self.tray.setToolTip("Voice2Text — Обработка...")

            language = self.config["language"]
            backend = self.config.get("backend", "whisper")
            api_key = get_api_key() if backend == "gemini" else ""
            whisper_model = self.config.get("whisper_model", "base")

            def worker():
                try:
                    text = transcribe(audio_data, language=language, backend=backend,
                                      api_key=api_key, whisper_model=whisper_model)
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
        self.tray.setIcon(make_icon("green"))
        self.tray.setToolTip("Voice2Text — Готов")

    def _on_error(self, msg):
        log.error("Ошибка: %s", msg)
        self.tray.showMessage("Voice2Text — Ошибка", msg, QSystemTrayIcon.Critical, 5000)
        self.state = "idle"
        self.tray.setIcon(make_icon("green"))
        self.tray.setToolTip("Voice2Text — Готов")

    def _open_settings(self):
        dialog = SettingsDialog(self.config)
        if dialog.exec_() == QDialog.Accepted:
            new_config = dialog.get_config()
            old_hotkey = self.config["hotkey"]
            self.config = new_config
            save_config(new_config)
            if new_config["hotkey"] != old_hotkey:
                self._stop_hotkey_listener()
                self._start_hotkey_listener()


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
