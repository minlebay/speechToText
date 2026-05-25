import logging
import os
import subprocess
import tempfile

log = logging.getLogger(__name__)


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
