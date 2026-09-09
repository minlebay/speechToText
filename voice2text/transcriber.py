import io
import logging

log = logging.getLogger(__name__)

_whisper_model = None
_whisper_model_name = None


def _get_whisper_model(model_name):
    global _whisper_model, _whisper_model_name
    if _whisper_model is None or _whisper_model_name != model_name:
        unload_whisper_model()
        from faster_whisper import WhisperModel

        log.info("Загрузка модели faster-whisper '%s'...", model_name)
        _whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")
        _whisper_model_name = model_name
        log.info("Модель загружена")
    return _whisper_model


def unload_whisper_model():
    global _whisper_model, _whisper_model_name
    if _whisper_model is not None:
        log.info("Выгрузка модели faster-whisper '%s' из памяти", _whisper_model_name)
        _whisper_model = None
        _whisper_model_name = None
        import gc

        gc.collect()


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


def transcribe_gemini(audio_wav, api_key, language="ru", model="gemini-3.8-flash", sanitize_fillers=False):
    try:
        from google import genai
        from google.genai import types

        log.info(
            "Gemini транскрипция (%d байт, язык=%s, модель=%s, очистка=%s)",
            len(audio_wav), language, model, sanitize_fillers,
        )
        client = genai.Client(api_key=api_key)

        if sanitize_fillers:
            prompt = (
                f"Transcribe this audio. "
                f"The primary language is {language}, but the speaker may mix in "
                f"other languages (e.g. English technical terms). "
                f"Preserve each word in its original language. "
                f"Aggressively clean the transcript of verbal disfluencies in whatever "
                f"language is spoken: remove ALL filler words and hesitation sounds, no "
                f"matter where they occur in the sentence. In Russian this includes 'э', "
                f"'э-э', 'эм', 'ну', 'вот', 'это', 'это самое', 'так сказать', 'собственно', "
                f"'собственно говоря', 'значит', 'короче', 'короче говоря', 'типа', "
                f"'как бы', 'в общем', 'в общем-то', 'в принципе', 'получается', 'как его', "
                f"'ну вот'. In English this includes 'um', 'uh', 'uh huh', 'er', 'like', "
                f"'you know', 'I mean', 'well', 'so', 'right', 'okay so', 'actually', "
                f"'basically', 'kind of', 'sort of', 'just', 'literally' (used as a filler), "
                f"'anyway'. Apply the same aggressive removal to filler words in any other "
                f"language present in the audio. Also remove false starts, stutters, "
                f"immediate word/phrase repetitions, and self-corrections (keep only the "
                f"final corrected version). "
                f"Do not change the meaning, do not add or omit any actual information, "
                f"do not paraphrase or summarize — only strip disfluencies so the result "
                f"reads as clean, fluent speech. "
                f"Output only the transcription text, nothing else."
            )
        else:
            prompt = (
                f"Transcribe this audio exactly as spoken. "
                f"The primary language is {language}, but the speaker may mix in "
                f"other languages (e.g. English technical terms). "
                f"Preserve each word in its original language. "
                f"Output only the transcription text, nothing else."
            )

        audio_part = types.Part.from_bytes(data=audio_wav, mime_type="audio/wav")

        gen_config = None
        if "2.5" in model or "3.5" in model:
            gen_config = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            )

        response = client.models.generate_content(
            model=model,
            contents=[prompt, audio_part],
            config=gen_config,
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


def transcribe_gemini_code(audio_wav, api_key, model="gemini-3.8-flash", context_code=""):
    try:
        from google import genai
        from google.genai import types

        log.info(
            "Gemini code-mode транскрипция (%d байт, модель=%s, контекст=%d символов)",
            len(audio_wav), model, len(context_code),
        )
        client = genai.Client(api_key=api_key)

        context_block = ""
        if context_code.strip():
            context_block = (
                "The user currently has the following text/code selected in their "
                "editor — it is the context the spoken instruction refers to (e.g. "
                "a variable or collection name, or a code snippet to refactor). "
                "Reuse its exact names, types and style where relevant; incorporate "
                "it into the generated code as implied by the instruction, but do not "
                "repeat it verbatim unless the instruction asks for that.\n"
                f"Selected context:\n{context_code.strip()}\n\n"
            )

        prompt = (
            f"{context_block}"
            "The audio is a spoken coding instruction in English, for example "
            "'write in Go a loop over a variable named x' or "
            "'in SQL, select username joined with the department table'. "
            "Identify the target programming language or SQL dialect from the "
            "instruction. If none is stated explicitly, infer the most fitting "
            "one from context (e.g. SQL for database queries). "
            "Generate only the code that implements what was asked, in that "
            "language. Output raw code only — no markdown code fences, no "
            "explanations, no comments about which language was used."
        )

        audio_part = types.Part.from_bytes(data=audio_wav, mime_type="audio/wav")

        gen_config = None
        if "2.5" in model or "3.5" in model:
            gen_config = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            )

        response = client.models.generate_content(
            model=model,
            contents=[prompt, audio_part],
            config=gen_config,
        )

        result = response.text.strip().strip("`\n")
        lines = result.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        result = "\n".join(lines).strip()

        log.info("Код сгенерирован: %d символов", len(result))
        return result
    except Exception as e:
        log.error("Ошибка Gemini code-mode транскрипции: %s", e)
        raise RuntimeError(f"Ошибка генерации кода: {e}") from e


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


def transcribe(audio_wav, language="ru", backend="whisper", api_key="", whisper_model="base",
               gemini_model="gemini-3.8-flash", sanitize_fillers=False):
    if backend == "whisper":
        return transcribe_whisper(audio_wav, language, whisper_model)
    elif backend == "google_stt":
        return transcribe_google_stt(audio_wav, language)
    else:
        return transcribe_gemini(audio_wav, api_key, language, gemini_model, sanitize_fillers)
