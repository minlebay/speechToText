import json
import logging
import os

from voice2text.secrets import (
    DEEPGRAM_API_KEY,
    GEMINI_API_KEY,
    GOOGLE_SERVICE_ACCOUNT,
    get_secret,
)

log = logging.getLogger(__name__)

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "voice2text")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
LOG_FILE = os.path.join(CONFIG_DIR, "voice2text.log")

DEFAULTS = {
    "hotkey": "<ctrl>+<shift>+h",
    "code_hotkey": "<ctrl>+<alt>+c",
    "output_mode": "paste",
    "language": "ru",
    "backend": "whisper",
    "whisper_model": "base",
    "gemini_model": "gemini-3.8-flash",
    "deepgram_model": "flux-general-multi",
    # Код языка (ru, en, sr, de, …) или auto — автоопределение.
    # Допустимые значения зависят от выбранной модели Deepgram.
    "deepgram_language_mode": "auto",
    "audio_device": None,
    "sanitize_fillers": False,
    "show_overlay": False,
    "realtime_transcription": False,
    "hide_notifications": False,
    "overlay_position": "center",
    "overlay_theme": "dark",
    "overlay_shape": "circle",
    "overlay_glass_opacity": 30,
    "tray_icon_monochrome": False,
    "tray_icon_mono_variant": "auto",
}


def setup_logging():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    log.info("Логирование инициализировано, файл: %s", LOG_FILE)


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # Старый булев флаг и удалённые режимы приводим к актуальным.
            if "deepgram_language_mode" not in cfg and "deepgram_multilingual" in cfg:
                cfg["deepgram_language_mode"] = "ru" if cfg["deepgram_multilingual"] else "auto"
            # «ru_en» убран: Nova-3 не умеет жёстко ограничивать пару языков,
            # поэтому сводим его к строгому русскому, чтобы не было uk/ar.
            if cfg.get("deepgram_language_mode") == "ru_en":
                cfg["deepgram_language_mode"] = "ru"
            elif cfg.get("deepgram_language_mode") == "single":
                cfg["deepgram_language_mode"] = "auto"
            for key, value in DEFAULTS.items():
                cfg.setdefault(key, value)
            log.info("Конфиг загружен: %s", CONFIG_FILE)
            return cfg
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Ошибка чтения конфига: %s, используются значения по умолчанию", e)
    return dict(DEFAULTS)


def save_config(cfg):
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.chmod(CONFIG_FILE, 0o600)
    log.info("Конфиг сохранён: %s", CONFIG_FILE)


def get_api_key():
    key = get_secret(GEMINI_API_KEY)
    if not key:
        log.warning("API-ключ Gemini не задан в хранилище секретов")
    return key


def get_deepgram_api_key():
    key = get_secret(DEEPGRAM_API_KEY)
    if not key:
        log.warning("API-ключ Deepgram не задан в хранилище секретов")
    return key


def get_google_service_account():
    """Возвращает данные сервисного аккаунта Google из хранилища секретов."""
    raw = get_secret(GOOGLE_SERVICE_ACCOUNT)
    if not raw:
        log.warning("JSON сервисного аккаунта Google не задан в хранилище секретов")
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        log.error("JSON сервисного аккаунта Google повреждён: %s", e)
        return None
