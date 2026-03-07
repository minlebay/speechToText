import io
import logging
import wave

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

SAMPLE_RATES = [16000, 44100, 48000]


class Recorder:
    def __init__(self, channels=1):
        self.channels = channels
        self.samplerate = self._detect_samplerate()
        self._frames = []
        self._stream = None

    def _detect_samplerate(self):
        for rate in SAMPLE_RATES:
            try:
                sd.check_input_settings(samplerate=rate, channels=self.channels, dtype="int16")
                log.info("Выбрана частота дискретизации: %d Гц", rate)
                return rate
            except sd.PortAudioError:
                log.debug("Частота %d Гц не поддерживается", rate)
        default_rate = int(sd.query_devices(kind="input")["default_samplerate"])
        log.info("Используется частота устройства по умолчанию: %d Гц", default_rate)
        return default_rate

    def _callback(self, indata, frames, time_info, status):
        if status:
            log.warning("Статус аудиопотока: %s", status)
        self._frames.append(indata.copy())

    def start(self):
        self._frames = []
        try:
            log.info("Начало записи (samplerate=%d, channels=%d)", self.samplerate, self.channels)
            self._stream = sd.InputStream(
                samplerate=self.samplerate,
                channels=self.channels,
                dtype="int16",
                callback=self._callback,
            )
            self._stream.start()
        except sd.PortAudioError as e:
            log.error("Не удалось начать запись: %s", e)
            raise RuntimeError(f"Не удалось начать запись: {e}") from e

    def stop(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
                log.info("Запись остановлена")
            except sd.PortAudioError as e:
                log.error("Ошибка при остановке записи: %s", e)
                raise RuntimeError(f"Ошибка при остановке записи: {e}") from e
            finally:
                self._stream = None

        if not self._frames:
            log.warning("Нет записанных данных")
            return b""

        audio = np.concatenate(self._frames)
        log.info("Записано %d сэмплов (%.1f сек)", len(audio), len(audio) / self.samplerate)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # int16 = 2 bytes
            wf.setframerate(self.samplerate)
            wf.writeframes(audio.tobytes())
        return buf.getvalue()
