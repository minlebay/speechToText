"""Буфер обмена, выделение и эмуляция клавиш — отдельно для X11 и Wayland.

Под Wayland xclip/xdotool работают только с XWayland-окнами, а само
приложение (X11-клиент через XWayland) не может молча поставить буфер
обмена: KWin синхронизирует X11-буфер в Wayland, только пока в фокусе
X11-окно. Поэтому там — wl-clipboard (протокол data-control, фокус не нужен)
и виртуальная клавиатура через /dev/uinput: доступ к нему systemd-logind
выдаёт пользователю активной сессии (uaccess), root не нужен.
"""
import logging
import os
import subprocess
import time

from PyQt5.QtWidgets import QApplication

log = logging.getLogger(__name__)


def is_wayland():
    return os.environ.get("XDG_SESSION_TYPE") == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))


def get_selected_text():
    """Читает текущее PRIMARY-выделение (обновляется автоматически при
    выделении текста мышью/клавиатурой, без имитации Ctrl+C — синтетический
    Ctrl+C небезопасен, например в терминале это SIGINT, а не копирование)."""
    if is_wayland():
        cmd = ["wl-paste", "--primary", "--no-newline"]
    else:
        cmd = ["xclip", "-o", "-selection", "primary"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1)
        if r.returncode == 0:
            return r.stdout
    except Exception as e:
        log.debug("Не удалось прочитать выделение через %s: %s", cmd[0], e)
    return ""


def set_clipboard(text):
    if is_wayland():
        try:
            subprocess.run(
                ["wl-copy", "--type", "text/plain;charset=utf-8"],
                input=text, text=True, check=True, timeout=3,
            )
            return
        except Exception as e:
            log.error("wl-copy не сработал (%s), пробуем буфер обмена Qt", e)
    QApplication.clipboard().setText(text)


class KeySender:
    """Нажатия клавиш в активном окне: xdotool под X11, виртуальная
    клавиатура uinput под Wayland. Сочетания — в нотации xdotool
    ("ctrl+v", "Right", "Return")."""

    KEY_DELAY = 0.012  # как задержка по умолчанию у xdotool

    def __init__(self):
        self._uinput = None
        self._codes = {}
        self.error = None
        if is_wayland():
            self._open_uinput()

    def _open_uinput(self):
        try:
            from evdev import UInput
            from evdev import ecodes as e

            self._codes = {
                "ctrl": e.KEY_LEFTCTRL,
                "shift": e.KEY_LEFTSHIFT,
                "v": e.KEY_V,
                "Right": e.KEY_RIGHT,
                "Return": e.KEY_ENTER,
            }
            class WriteOnlyUInput(UInput):
                def _find_device(self, fd):
                    # Читать своё устройство нам не нужно, а /dev/input/event*
                    # закрыт на чтение — evdev иначе ~2 с ждёт прав на него.
                    return None

            # Устройство создаём заранее и держим открытым: композитору нужно
            # время, чтобы подхватить новую клавиатуру, и нажатия, отправленные
            # сразу после создания, теряются.
            self._uinput = WriteOnlyUInput({e.EV_KEY: list(self._codes.values())}, name="voice2text-keyboard")
            log.info("Виртуальная клавиатура uinput создана")
        except Exception as e:
            self.error = f"Нет доступа к /dev/uinput ({e}), автовставка работает только в X11-окнах"
            log.error(self.error)

    def send(self, combo):
        if self._uinput is None:
            subprocess.run(["xdotool", "key", "--clearmodifiers", combo])
            return
        from evdev import ecodes as e

        keys = [self._codes[name] for name in combo.split("+")]
        for key in keys:
            self._uinput.write(e.EV_KEY, key, 1)
            self._uinput.syn()
            time.sleep(self.KEY_DELAY)
        for key in reversed(keys):
            self._uinput.write(e.EV_KEY, key, 0)
            self._uinput.syn()
            time.sleep(self.KEY_DELAY)
