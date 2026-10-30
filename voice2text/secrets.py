"""Хранилище секретов Voice2Text.

Основное хранилище — KDE Wallet (kwalletd6/kwalletd5) через D-Bus. Если
KWallet в системе недоступен (например, сессия GNOME), используется Secret
Service через ``secret-tool``. Секреты никогда не пишутся в config.json и не
читаются из переменных окружения.
"""

import logging
import shutil
import subprocess

log = logging.getLogger(__name__)

try:
    from PyQt5.QtCore import QVariant
    from PyQt5.QtDBus import QDBus, QDBusConnection, QDBusMessage

    _HAVE_QTDBUS = True
except ImportError:  # pragma: no cover - PyQt5 без QtDBus
    _HAVE_QTDBUS = False

# Имена записей в хранилище. Используются везде вместо имён переменных окружения.
GEMINI_API_KEY = "gemini_api_key"
DEEPGRAM_API_KEY = "deepgram_api_key"
GOOGLE_SERVICE_ACCOUNT = "google_service_account"

APP_ID = "voice2text"
FOLDER = "Voice2Text"
_CALL_TIMEOUT_MS = 300_000  # пользователь может не сразу ввести пароль от KWallet

_SECRET_TOOL = shutil.which("secret-tool")


class SecretStoreError(RuntimeError):
    """Ошибка хранилища секретов."""


class SecretStoreUnavailable(SecretStoreError):
    """Хранилище секретов недоступно в этой системе."""


def _call(bus, service, path, method, *args):
    message = QDBusMessage.createMethodCall(service, path, "org.kde.KWallet", method)
    message.setArguments(list(args))
    reply = bus.call(message, QDBus.Block, _CALL_TIMEOUT_MS)
    if reply.type() == QDBusMessage.ErrorMessage:
        error = f"{reply.errorName()}: {reply.errorMessage()}"
        if reply.errorName() in (
            "org.freedesktop.DBus.Error.ServiceUnknown",
            "org.freedesktop.DBus.Error.NameHasNoOwner",
            "org.freedesktop.DBus.Error.UnknownObject",
        ):
            raise SecretStoreUnavailable(error)
        raise SecretStoreError(error)
    return reply


def _open_kwallet():
    """Открывает KWallet и возвращает (bus, service, path, handle).

    Бросает SecretStoreUnavailable, если KWallet нет или он отключён.
    """
    if not _HAVE_QTDBUS:
        raise SecretStoreUnavailable("PyQt5.QtDBus недоступен")
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        raise SecretStoreUnavailable("нет соединения с D-Bus сессии")

    last_error = None
    for version in (6, 5):
        service = f"org.kde.kwalletd{version}"
        path = f"/modules/kwalletd{version}"
        try:
            enabled = _call(bus, service, path, "isEnabled").arguments()
            if not enabled or not enabled[0]:
                raise SecretStoreUnavailable("KWallet отключён")
            wallet = _call(bus, service, path, "localWallet").arguments()[0]
            handle = _call(bus, service, path, "open", wallet, _int64(0), APP_ID).arguments()[0]
            if handle is None or handle < 0:
                raise SecretStoreError("не удалось открыть KWallet")
            if not _call(bus, service, path, "hasFolder", handle, FOLDER, APP_ID).arguments()[0]:
                _call(bus, service, path, "createFolder", handle, FOLDER, APP_ID)
            return bus, service, path, handle
        except SecretStoreUnavailable as e:
            last_error = e
        except (IndexError, TypeError) as e:
            last_error = SecretStoreError(f"неожиданный ответ KWallet: {e}")
    raise SecretStoreUnavailable(str(last_error or "KWallet недоступен"))


def _int64(value):
    """D-Bus ждёт для wId тип x (int64), а PyQt по умолчанию шлёт int32."""
    variant = QVariant(value)
    variant.convert(QVariant.LongLong)
    return variant


def _secret_tool_store(name, value):
    result = subprocess.run(
        [_SECRET_TOOL, "store", f"--label=Voice2Text: {name}", "service", APP_ID, "key", name],
        input=value,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise SecretStoreError(result.stderr.strip() or "secret-tool store завершился с ошибкой")


def _secret_tool_lookup(name):
    if not _SECRET_TOOL:
        return ""
    result = subprocess.run(
        [_SECRET_TOOL, "lookup", "service", APP_ID, "key", name],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _secret_tool_delete(name):
    if not _SECRET_TOOL:
        return
    subprocess.run(
        [_SECRET_TOOL, "clear", "service", APP_ID, "key", name],
        capture_output=True,
        text=True,
        timeout=30,
    )


def get_secret(name):
    """Возвращает секрет или пустую строку, если он не задан."""
    try:
        bus, service, path, handle = _open_kwallet()
        reply = _call(bus, service, path, "readPassword", handle, FOLDER, name, APP_ID)
        value = reply.arguments()[0] if reply.arguments() else ""
        return value or ""
    except SecretStoreUnavailable as e:
        log.debug("KWallet недоступен (%s), пробуем Secret Service", e)
        return _secret_tool_lookup(name)
    except SecretStoreError as e:
        log.warning("Не удалось прочитать секрет из KWallet: %s", e)
        return ""


def has_secret(name):
    return bool(get_secret(name))


def set_secret(name, value):
    """Сохраняет секрет в KWallet, при его отсутствии — в Secret Service."""
    try:
        bus, service, path, handle = _open_kwallet()
        _call(bus, service, path, "writePassword", handle, FOLDER, name, value, APP_ID)
        return
    except SecretStoreUnavailable as e:
        log.debug("KWallet недоступен (%s), сохраняем в Secret Service", e)
    if not _SECRET_TOOL:
        raise SecretStoreUnavailable("ни KWallet, ни Secret Service (secret-tool) недоступны")
    _secret_tool_store(name, value)


def delete_secret(name):
    """Удаляет секрет из всех поддерживаемых хранилищ."""
    removed = False
    try:
        bus, service, path, handle = _open_kwallet()
        _call(bus, service, path, "removeEntry", handle, FOLDER, name, APP_ID)
        removed = True
    except SecretStoreUnavailable as e:
        log.debug("KWallet недоступен (%s)", e)
    except SecretStoreError as e:
        log.warning("Не удалось удалить секрет из KWallet: %s", e)
    if _SECRET_TOOL:
        _secret_tool_delete(name)
        removed = True
    if not removed:
        raise SecretStoreUnavailable("ни KWallet, ни Secret Service (secret-tool) недоступны")
