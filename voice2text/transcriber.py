import io
import logging

log = logging.getLogger(__name__)

_whisper_model = None
_whisper_model_name = None


def _get_whisper_model(model_name):
    global _whisper_model, _whisper_model_name
    if _whisper_model is None or _whisper_model_name != model_name:
        from faster_whisper import WhisperModel

        log.info("Загрузка модели faster-whisper '%s'...", model_name)
        _whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")
        _whisper_model_name = model_name
        log.info("Модель загружена")
    return _whisper_model


def transcribe_whisper(audio_wav, language="ru", model_name="base"):
    try:
        import numpy as np
        import wave

        log.info("Whisper транскрипция (%d байт, язык=%s, модель=%s)", len(audio_wav), language, model_name)

        buf = io.BytesIO(audio_wav)
        with wave.open(buf, "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

        model = _get_whisper_model(model_name)
        segments, info = model.transcribe(audio, language=language, beam_size=5)
        result = " ".join(seg.text.strip() for seg in segments).strip()

        log.info("Транскрипция получена: %d символов", len(result))
        return result
    except Exception as e:
        log.error("Ошибка Whisper транскрипции: %s", e)
        raise RuntimeError(f"Ошибка транскрипции: {e}") from e


def transcribe_gemini(audio_wav, api_key, language="ru"):
    try:
        from google import genai
        from google.genai import types

        log.info("Gemini транскрипция (%d байт, язык=%s)", len(audio_wav), language)
        client = genai.Client(api_key=api_key)

        prompt = (
            f"Transcribe this audio exactly as spoken. "
            f"The primary language is {language}, but the speaker may mix in "
            f"other languages (e.g. English technical terms). "
            f"Preserve each word in its original language. "
            f"Output only the transcription text, nothing else."
        )

        audio_part = types.Part.from_bytes(data=audio_wav, mime_type="audio/wav")

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[prompt, audio_part],
        )

        raw = response.text.strip()
        result = raw.strip("\"'`*_~«»—\n")
        for char in ("`", "*", "_", "~", '"', "'"):
            if result.startswith(char) and result.endswith(char):
                result = result.strip(char)
        log.info("Транскрипция получена: %d символов", len(result))
        return result
    except Exception as e:
        log.error("Ошибка Gemini транскрипции: %s", e)
        raise RuntimeError(f"Ошибка транскрипции: {e}") from e


def transcribe_google_stt(audio_wav, language="ru"):
    try:
        from google.cloud import speech

        log.info("Google STT транскрипция (%d байт, язык=%s)", len(audio_wav), language)

        client = speech.SpeechClient()

        lang_map = {"ru": "ru-RU", "en": "en-US", "de": "de-DE", "fr": "fr-FR", "es": "es-ES"}
        lang_code = lang_map.get(language, language if "-" in language else f"{language}-{language.upper()}")

        audio = speech.RecognitionAudio(content=audio_wav)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=44100,
            language_code=lang_code,
            alternative_language_codes=["en-US"] if lang_code != "en-US" else [],
        )

        response = client.recognize(config=config, audio=audio)
        result = " ".join(r.alternatives[0].transcript for r in response.results).strip()

        log.info("Транскрипция получена: %d символов", len(result))
        return result
    except Exception as e:
        log.error("Ошибка Google STT транскрипции: %s", e)
        raise RuntimeError(f"Ошибка транскрипции: {e}") from e


def transcribe(audio_wav, language="ru", backend="whisper", api_key="", whisper_model="base"):
    if backend == "whisper":
        return transcribe_whisper(audio_wav, language, whisper_model)
    elif backend == "google_stt":
        return transcribe_google_stt(audio_wav, language)
    else:
        return transcribe_gemini(audio_wav, api_key, language)
