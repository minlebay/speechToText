import json
import logging
import os

log = logging.getLogger(__name__)

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "voice2text")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
LOG_FILE = os.path.join(CONFIG_DIR, "voice2text.log")

DEFAULTS = {
    "hotkey": "<ctrl>+<shift>+h",
    "output_mode": "paste",
    "language": "ru",
    "backend": "whisper",
    "whisper_model": "base",
    "gemini_model": "gemini-3.5-flash",
    "audio_device": None,
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
    key = os.environ.get("GEMINI_API_KEY_TTS", "")
    if not key:
        log.warning("GEMINI_API_KEY_TTS не установлен")
    return key
