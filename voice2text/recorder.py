import io
import logging
import os
import subprocess
import tempfile
import wave

log = logging.getLogger(__name__)

SAMPLE_RATE = 48000
SAMPLE_WIDTH = 2  # bytes (s16le)


class Recorder:
    def __init__(self, channels=1, device=None):
        self.channels = channels
        self.device = device  # PulseAudio source name or None (system default)
        self._process = None
        self._temp_file = None

    def set_device(self, device):
        self.device = device
        log.info("Устройство записи: %s", device or "системное по умолчанию")

    def _build_cmd(self, path):
        cmd = [
            "parecord",
            "--rate=48000",
            f"--channels={self.channels}",
            "--format=s16le",
            "--latency-msec=100",
        ]
        if self.device:
            cmd.append(f"--device={self.device}")
        cmd.append(path)
        return cmd

    def start(self):
        self._temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        self._temp_file.close()

        cmd = self._build_cmd(self._temp_file.name)
        log.info("Начало записи: %s", " ".join(cmd))
        try:
            self._process = subprocess.Popen(cmd, stderr=subprocess.PIPE)
        except FileNotFoundError as e:
            os.unlink(self._temp_file.name)
            self._temp_file = None
            raise RuntimeError("parecord не найден. Установите: sudo apt install pulseaudio-utils") from e

    def stop(self):
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
            self._process = None

        if self._temp_file is None:
            return b""

        try:
            with open(self._temp_file.name, "rb") as f:
                data = f.read()
        except Exception as e:
            log.error("Ошибка чтения записи: %s", e)
            data = b""
        finally:
            try:
                os.unlink(self._temp_file.name)
            except Exception:
                pass
            self._temp_file = None

        if len(data) <= 44:  # только WAV-заголовок — нет данных
            log.warning("Нет записанных данных")
            return b""

        duration = (len(data) - 44) / (48000 * self.channels * 2)
        log.info("Записано %d байт (%.1f сек)", len(data), duration)
        return data

    def read_level_window(self, num_bytes=9600):
        """Возвращает последние num_bytes сырых PCM-данных без остановки записи (для индикатора уровня)."""
        if self._temp_file is None:
            return b""
        try:
            size = os.path.getsize(self._temp_file.name)
            if size <= 44:
                return b""
            with open(self._temp_file.name, "rb") as f:
                f.seek(max(44, size - num_bytes))
                return f.read()
        except OSError:
            return b""

    def read_partial_wav(self):
        """Возвращает корректный WAV со всем, что уже записано, без остановки записи."""
        if self._temp_file is None:
            return b""
        try:
            with open(self._temp_file.name, "rb") as f:
                raw = f.read()
        except OSError:
            return b""
        if len(raw) <= 44:
            return b""

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(SAMPLE_WIDTH)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(raw[44:])
        return buf.getvalue()
