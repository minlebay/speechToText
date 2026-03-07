# Data Model: Voice Transcription Desktop App

**Branch**: `001-voice-transcription-app`
**Date**: 2026-03-07

## Entities

### AppConfig

User-persisted configuration loaded from and saved to
`~/.config/voice2text/config.json`.

| Field        | Type   | Default              | Validation                                |
| ------------ | ------ | -------------------- | ----------------------------------------- |
| hotkey       | string | "<ctrl>+<shift>+h"   | Valid pynput hotkey format                 |
| output_mode  | string | "paste"              | One of: "paste", "clipboard"              |
| language     | string | "ru"                 | Non-empty string (ISO 639-1 recommended)  |

**Persistence**: JSON file. Created on first save if directory/file
does not exist. Loaded at app startup with fallback to defaults.

**Note**: The API key is NOT part of AppConfig. It is read from the
`GEMINI_API_KEY` environment variable via `os.environ.get()`.

### AppState (in-memory only)

Runtime state machine — not persisted.

| State         | Icon Color | Allowed Transitions         |
| ------------- | ---------- | --------------------------- |
| idle          | Green      | idle -> recording           |
| recording     | Red        | recording -> transcribing   |
| transcribing  | Yellow     | transcribing -> idle        |

**Constraints**:
- Hotkey press in `idle` -> transition to `recording`
- Hotkey press in `recording` -> transition to `transcribing`
- Hotkey press in `transcribing` -> ignored (no-op)
- Any error in `recording` or `transcribing` -> transition to `idle`

### RecordingSession (in-memory only)

Transient object that exists only during an active recording.

| Field       | Type         | Description                              |
| ----------- | ------------ | ---------------------------------------- |
| frames      | list[ndarray]| Audio chunks collected by InputStream callback |
| samplerate  | int          | 16000 Hz                                 |
| channels    | int          | 1 (mono)                                 |
| dtype       | string       | "int16"                                  |

**Lifecycle**: Created on recording start, consumed on recording stop
(frames concatenated and encoded to WAV bytes), then discarded.

### TranscriptionResult (in-memory only)

Transient value returned from the Gemini API call.

| Field  | Type   | Description                               |
| ------ | ------ | ----------------------------------------- |
| text   | string | Transcribed text, stripped of whitespace   |

**Lifecycle**: Created by transcriber, delivered to app via pyqtSignal,
consumed by output handler (clipboard/paste), then discarded.

## State Transition Diagram

```text
         hotkey press          hotkey press           API response / error
[idle] ───────────> [recording] ───────────> [transcribing] ───────────> [idle]
  ^                                                                        |
  |                         error during recording                         |
  +------------------------------------------------------------------------+
```

## Relationships

- `AppConfig` is loaded once at startup and updated via `SettingsDialog`.
- `AppState` governs which actions are allowed (hotkey behavior depends on current state).
- `RecordingSession` is owned by `Recorder` and exists only in `recording` state.
- `TranscriptionResult` is produced by `transcriber.transcribe()` and consumed in `transcribing` -> `idle` transition.
