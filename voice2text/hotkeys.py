"""Глобальные горячие клавиши через KDE KGlobalAccel (D-Bus).

Под Wayland pynput видит нажатия только в XWayland-окнах, а сочетание,
зарегистрированное в KGlobalAccel, ловит сам KWin в любом окне — так
работают горячие клавиши приложений KDE. Сочетания появляются в
«Параметры системы → Комбинации клавиш» как Voice2Text, но источник правды —
наши настройки: при запуске они перезаписывают то, что там сохранено.
"""
import logging

from PyQt5.QtCore import QMetaType, QObject, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtDBus import QDBusArgument, QDBusConnection, QDBusInterface, QDBusMessage
from PyQt5.QtGui import QKeySequence

log = logging.getLogger(__name__)

_SERVICE = "org.kde.kglobalaccel"

# Флаги KGlobalAccel::setShortcut: SetPresent — приложение запущено и ждёт
# нажатий; NoAutoloading — не подменять наше сочетание сохранённым в KDE.
_SET_PRESENT = 2
_NO_AUTOLOADING = 4

# Имена клавиш pynput, которые в нотации QKeySequence пишутся иначе;
# остальные (f1, home, tab, space, ...) совпадают с точностью до регистра.
_QT_KEY_NAMES = {
    "ctrl": "Ctrl", "ctrl_l": "Ctrl", "ctrl_r": "Ctrl",
    "alt": "Alt", "alt_l": "Alt", "alt_r": "Alt",
    "shift": "Shift", "shift_l": "Shift", "shift_r": "Shift",
    "cmd": "Meta", "cmd_l": "Meta", "cmd_r": "Meta",
    "caps_lock": "CapsLock",
    "delete": "Del",
    "enter": "Return",
    "esc": "Esc",
    "insert": "Ins",
    "num_lock": "NumLock",
    "page_down": "PgDown",
    "page_up": "PgUp",
    "print_screen": "Print",
    "scroll_lock": "ScrollLock",
}

_MODIFIER_KEYS = {Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta}


def hotkey_to_qt(hotkey):
    """'<ctrl>+<alt>+s' (формат pynput из настроек) → код сочетания Qt,
    как его ждёт KGlobalAccel; None, если строку не разобрать."""
    parts = []
    for token in hotkey.lower().split("+"):
        token = token.strip()
        if token.startswith("<") and token.endswith(">"):
            name = token[1:-1]
            parts.append(_QT_KEY_NAMES.get(name, name.capitalize()))
        elif len(token) == 1:
            parts.append(token.upper())
        else:
            return None
    seq = QKeySequence("+".join(parts), QKeySequence.PortableText)
    if seq.count() != 1:
        return None
    combined = seq[0]
    key = combined & ~int(Qt.KeyboardModifierMask)
    if key in (0, Qt.Key_unknown) or key in _MODIFIER_KEYS:
        return None
    return combined


def _string_list(values):
    return QDBusArgument(values, QMetaType.QStringList)


def _int_list(values):
    # QDBusArgument(list, QMetaType.Int) PyQt5 молча теряет — массив
    # собираем вручную, иначе D-Bus видит сигнатуру без "ai".
    arg = QDBusArgument()
    arg.beginArray(QMetaType.Int)
    for value in values:
        arg.add(value, QMetaType.Int)
    arg.endArray()
    return arg


class KGlobalAccelHotkeys(QObject):
    COMPONENT = "voice2text"
    COMPONENT_NAME = "Voice2Text"

    activated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bus = QDBusConnection.sessionBus()
        self._iface = QDBusInterface(_SERVICE, "/kglobalaccel", "org.kde.KGlobalAccel", self._bus)
        self._action_ids = {}
        # Путь компонента KGlobalAccel строит из имени, заменяя всё кроме
        # [A-Za-z0-9] на "_" — у "voice2text" он совпадает с именем.
        self._bus.connect(
            _SERVICE, f"/component/{self.COMPONENT}", "org.kde.kglobalaccel.Component",
            "globalShortcutPressed", self._on_pressed,
        )

    @staticmethod
    def is_available():
        bus_iface = QDBusConnection.sessionBus().interface()
        return bus_iface is not None and bool(bus_iface.isServiceRegistered(_SERVICE).value())

    def register(self, action, friendly_name, key):
        """Назначает сочетание key (код Qt) действию action. False, если
        KDE его не принял — обычно сочетание уже занято другим приложением."""
        action_id = [self.COMPONENT, action, self.COMPONENT_NAME, friendly_name]
        self._action_ids[action] = action_id
        self._iface.call("doRegister", _string_list(action_id))
        reply = self._iface.call(
            "setShortcut", _string_list(action_id), _int_list([key]),
            QDBusArgument(_SET_PRESENT | _NO_AUTOLOADING, QMetaType.UInt),
        )
        if reply.type() != QDBusMessage.ReplyMessage:
            log.error("KGlobalAccel.setShortcut(%s): %s", action, reply.errorMessage())
            return False
        return list(reply.arguments()[0]) == [key]

    def release(self):
        """Снимает перехват сочетаний, чтобы после выхода из приложения
        KWin не глотал их впустую."""
        for action_id in self._action_ids.values():
            self._iface.call("setInactive", _string_list(action_id))
        self._action_ids.clear()

    @pyqtSlot(str, str, "qlonglong")
    def _on_pressed(self, component, action, _timestamp):
        if component == self.COMPONENT:
            self.activated.emit(action)
