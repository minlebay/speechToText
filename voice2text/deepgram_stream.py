import json
import logging
import threading
import time
import urllib.parse

log = logging.getLogger(__name__)

SEND_INTERVAL = 0.1  # сек между отправками аудио в сокет

# Языки, которые flux-general-multi принимает в language_hint
FLUX_LANGUAGES = {"en", "es", "fr", "de", "hi", "ru", "pt", "ja", "it", "nl"}


def is_flux(model):
    return model.startswith("flux")


class DeepgramStream:
    """Потоковое распознавание через WebSocket Deepgram.

    Flux-модели идут через /v2/listen (реплики с пословными обновлениями),
    Nova — через /v1/listen с interim_results.

    read_pcm(offset) должен возвращать сырые PCM-байты записи, начиная с offset.
    on_text(text) вызывается из фонового потока при каждом обновлении текста.
    """

    def __init__(self, api_key, read_pcm, on_text, model="flux-general-multi", language="ru",
                 multilingual=True, sample_rate=48000, channels=1):
        self._api_key = api_key
        self._read_pcm = read_pcm
        self._on_text = on_text
        self._flux = is_flux(model)
        self._frame = 2 * channels
        if self._flux:
            hints = [language] + (["en"] if multilingual else [])
            params = [("model", model), ("encoding", "linear16"), ("sample_rate", sample_rate)]
            params += [("language_hint", h) for h in dict.fromkeys(hints) if h in FLUX_LANGUAGES]
            self._url = "wss://api.deepgram.com/v2/listen?" + urllib.parse.urlencode(params)
        else:
            if multilingual and model.startswith("nova-3"):
                language = "multi"
            self._url = "wss://api.deepgram.com/v1/listen?" + urllib.parse.urlencode({
                "model": model,
                "language": language,
                "encoding": "linear16",
                "sample_rate": sample_rate,
                "channels": channels,
                "interim_results": "true",
                "smart_format": "true",
                "punctuate": "true",
                "endpointing": 100,
            })
        self._ws = None
        self._sent = 0
        self._segments = {}  # Flux: turn_index -> текст; Nova: порядковый номер финала -> текст
        self._interim = ""
        self._error = None
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._lock = threading.Lock()
        self._sender = None
        self._receiver = None

    def start(self):
        self._sender = threading.Thread(target=self._send_loop, daemon=True)
        self._sender.start()

    def _send_loop(self):
        try:
            from websockets.sync.client import connect

            log.info("Deepgram стрим: подключение (%s)", self._url.split("?", 1)[1])
            self._ws = connect(
                self._url,
                additional_headers={"Authorization": f"Token {self._api_key}"},
                open_timeout=10,
            )
            self._connected.set()
            self._receiver = threading.Thread(target=self._recv_loop, daemon=True)
            self._receiver.start()
            while not self._stop.is_set():
                self._send_available()
                self._stop.wait(SEND_INTERVAL)
        except Exception as e:
            log.error("Deepgram стрим: ошибка отправки: %s", e)
            self._error = e
            self._connected.set()

    def _send_available(self, data=None):
        if data is None:
            data = self._read_pcm(self._sent)
        data = data[: len(data) - len(data) % self._frame]
        if data:
            self._ws.send(data)
            self._sent += len(data)

    def _recv_loop(self):
        try:
            for message in self._ws:
                if isinstance(message, bytes):
                    continue
                msg = json.loads(message)
                with self._lock:
                    changed = self._handle(msg)
                    text = self._text(include_interim=True)
                if changed:
                    self._on_text(text)
        except Exception as e:
            if not self._stop.is_set():
                log.error("Deepgram стрим: ошибка приёма: %s", e)
                self._error = e

    def _handle(self, msg):
        kind = msg.get("type")
        if kind in ("Error", "FatalError"):
            log.error("Deepgram стрим: ошибка сервера: %s", msg)
            self._error = RuntimeError(msg.get("description") or msg.get("message") or str(msg))
            return False
        if self._flux:
            if kind != "TurnInfo":
                return False
            transcript = (msg.get("transcript") or "").strip()
            turn = msg.get("turn_index", 0)
            if not transcript or self._segments.get(turn) == transcript:
                return False
            self._segments[turn] = transcript
            return True
        if kind != "Results":
            return False
        alts = msg.get("channel", {}).get("alternatives") or [{}]
        transcript = alts[0].get("transcript", "").strip()
        if msg.get("is_final"):
            if transcript:
                self._segments[len(self._segments)] = transcript
            self._interim = ""
        else:
            self._interim = transcript
        return True

    def _text(self, include_interim=False):
        parts = [self._segments[k] for k in sorted(self._segments)]
        if include_interim and self._interim:
            parts.append(self._interim)
        return " ".join(parts).strip()

    def finish(self, final_pcm, timeout=5.0):
        """Досылает остаток записи, закрывает стрим и возвращает итоговый текст.

        Возвращает None, если стрим не работал — тогда нужен обычный batch-запрос.
        """
        self._connected.wait(timeout)
        self._stop.set()
        if self._sender is not None:
            self._sender.join(timeout)
        if self._ws is None or self._error is not None:
            self.cancel()
            return None
        try:
            self._send_available(final_pcm[self._sent:])
            self._ws.send(json.dumps({"type": "CloseStream"}))
            deadline = time.time() + timeout
            if self._receiver is not None:
                self._receiver.join(max(0.0, deadline - time.time()))
            if self._receiver is not None and self._receiver.is_alive():
                log.warning("Deepgram стрим: не дождались закрытия за %.1f сек", timeout)
                self.cancel()
                return None
        except Exception as e:
            log.error("Deepgram стрим: ошибка завершения: %s", e)
            self.cancel()
            return None
        if self._error is not None:
            return None
        with self._lock:
            result = self._text()
        log.info("Deepgram стрим: итог %d символов (отправлено %d байт)", len(result), self._sent)
        return result

    def cancel(self):
        self._stop.set()
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
