# Implementation Plan: Voice Transcription Desktop App

**Branch**: `001-voice-transcription-app` | **Date**: 2026-03-07 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-voice-transcription-app/spec.md`

## Summary

Build a Python system tray application for Kubuntu (X11, KDE Plasma 5.27) that
captures voice input via a global hotkey (pynput), records audio (sounddevice),
transcribes it using Google Gemini API, and either auto-pastes (xdotool) or
copies the result to clipboard. The app has no main window — all interaction
happens through the tray icon and a settings dialog.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: PyQt5 (>=5.15), pynput (>=1.7), sounddevice (>=0.4), numpy (>=1.24), google-generativeai (>=0.8)
**Storage**: JSON file at `~/.config/voice2text/config.json`
**Testing**: pytest (unit tests for config, recorder, transcriber modules)
**Target Platform**: Kubuntu, X11, KDE Plasma 5.27
**Project Type**: desktop-app (system tray utility)
**Performance Goals**: Full voice-to-text cycle under 10 seconds; app startup under 3 seconds; <50 MB idle memory
**Constraints**: X11 only (no Wayland); requires system deps xdotool + portaudio19-dev
**Scale/Scope**: Single-user desktop utility, 4 Python modules, ~500-800 LOC

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle                      | Status | Evidence                                                                                      |
| ------------------------------ | ------ | --------------------------------------------------------------------------------------------- |
| I. System Tray First           | PASS   | No main window. Tray icon with green/red/yellow states. `setQuitOnLastWindowClosed(False)`.   |
| II. Hotkey-Driven Recording    | PASS   | Single toggle hotkey via pynput. Default `<ctrl>+<shift>+h`. API key guard.                   |
| III. Gemini API Transcription  | PASS   | google-generativeai SDK, gemini-2.0-flash model, background thread, pyqtSignal bridge.        |
| IV. Output Modes               | PASS   | "paste" (clipboard + xdotool) and "clipboard" (clipboard only). Notifications on result/error.|
| V. Simplicity                  | PASS   | Flat 4-module structure: config.py, recorder.py, transcriber.py, app.py. No abstractions.     |

All gates pass. No violations to justify.

## Project Structure

### Documentation (this feature)

```text
specs/001-voice-transcription-app/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
voice2text/
├── __init__.py          # Package marker
├── __main__.py          # Entry point: python -m voice2text
├── app.py               # QApplication, QSystemTrayIcon, SettingsDialog, SignalBridge, hotkey coordination
├── recorder.py          # Recorder class: sounddevice InputStream, WAV encoding
├── transcriber.py       # transcribe() function: Gemini API call
└── config.py            # load_config() / save_config(): JSON at ~/.config/voice2text/config.json

requirements.txt         # Python dependencies at repo root
```

**Structure Decision**: Flat single-package layout per Constitution Principle V.
No src/ or tests/ hierarchy — the app is a small utility with 4 modules.
Entry point is `python -m voice2text` which invokes `__main__.py`.

## Complexity Tracking

> No violations found. Table intentionally empty.
