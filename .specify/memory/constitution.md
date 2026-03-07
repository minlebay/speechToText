<!--
  Sync Impact Report
  ===================
  Version change: 0.0.0 (initial template) -> 1.0.0
  Modified principles: N/A (initial creation)
  Added sections:
    - Core Principles (5 principles)
    - Technology Constraints
    - Development Workflow
    - Governance
  Removed sections: None
  Templates requiring updates:
    - .specify/templates/plan-template.md: N/A (generic, no constitution refs to update)
    - .specify/templates/spec-template.md: N/A (generic, no constitution refs to update)
    - .specify/templates/tasks-template.md: N/A (generic, no constitution refs to update)
  Follow-up TODOs: None
-->

# Voice2Text Constitution

## Core Principles

### I. System Tray First

Voice2Text is a background desktop application with NO main window.
The system tray icon is the sole persistent UI element and MUST
reflect application state via color:

- Green: idle, ready to record
- Red: recording in progress
- Yellow: transcription in progress (waiting for API response)

The app MUST start minimized to the system tray. All user interaction
(settings, quit) is accessed through the tray context menu.
`QApplication.setQuitOnLastWindowClosed(False)` MUST be set.

**Rationale**: The app is a utility that stays out of the way. Users
interact with it via a hotkey, not a window.

### II. Hotkey-Driven Recording

Audio capture MUST be toggled via a single global hotkey using
`pynput.GlobalHotKeys` on X11. The default hotkey is
`<ctrl>+<shift>+h` (configurable in settings).

- First press: start recording (16kHz, mono, int16 via
  `sounddevice.InputStream`). Show tray notification. Icon turns red.
- Second press: stop recording. Icon turns yellow. Audio is encoded
  as WAV in memory and sent to the transcription API in a background
  `threading.Thread`.

Recording MUST NOT start if the API key is empty; a warning
notification MUST be shown instead.

**Rationale**: A toggle hotkey provides the fastest voice capture
workflow without requiring mouse interaction.

### III. Gemini API Transcription

All transcription MUST use the Google Gemini API
(`google-generativeai` SDK) with the `gemini-2.0-flash` model.

- Audio is sent as WAV bytes with `mime_type: "audio/wav"`.
- Prompt: "Transcribe this audio exactly as spoken. The language is
  {language}. Output only the transcription text, nothing else."
- The transcription call MUST run in a background thread, never
  blocking the Qt event loop.
- Results are delivered to the main thread via `pyqtSignal`.

**Rationale**: Gemini provides high-quality multilingual transcription.
Background threading prevents UI freezes during API calls.

### IV. Output Modes

Two output modes MUST be supported, configurable in settings:

- **paste**: Copy transcription to `QApplication.clipboard()`, then
  invoke `xdotool key --clearmodifiers ctrl+v` via `subprocess.Popen`
  to paste into the currently focused input field.
- **clipboard**: Copy transcription to clipboard only (no auto-paste).

On success, a tray notification MUST show the first 50 characters of
the result. On error, a tray notification MUST show the error message.
Icon MUST reset to green in both cases.

**Rationale**: Auto-paste is the primary use case for speed; clipboard
mode provides a fallback for applications where xdotool paste may not
work reliably.

### V. Simplicity and Minimal Dependencies

The application MUST remain a single-purpose tool with a flat module
structure:

- `config.py`: JSON config load/save from
  `~/.config/voice2text/config.json`
- `recorder.py`: Audio capture via sounddevice
- `transcriber.py`: Gemini API call
- `app.py`: Qt application, tray icon, settings dialog, coordination

No abstractions, plugin systems, or feature creep beyond the core
record-transcribe-paste workflow. New modules MUST be justified by a
clear, distinct responsibility that does not fit existing modules.

**Rationale**: This is a small utility. Complexity is the enemy of
reliability for desktop tools.

## Technology Constraints

- **Language**: Python 3.10+
- **GUI Framework**: PyQt5 (system tray, settings dialog, clipboard)
- **Global Hotkey**: pynput (X11 only; Wayland is out of scope)
- **Audio Capture**: sounddevice + numpy (PortAudio backend)
- **Transcription API**: google-generativeai SDK (Gemini)
- **Text Insertion**: xdotool (system dependency, X11 only)
- **Target Platform**: Kubuntu, X11, KDE Plasma 5.27
- **Config Format**: JSON at `~/.config/voice2text/config.json`
- **UI Language**: All user-facing strings MUST be in Russian
- **System Dependencies**: `xdotool`, `portaudio19-dev`
- **Entry Point**: `python -m voice2text` via `__main__.py`

## Development Workflow

- **Thread Safety**: All background work (API calls) MUST use
  `threading.Thread`. Results MUST be delivered to Qt via
  `pyqtSignal` on a `QObject` bridge. Direct Qt widget manipulation
  from background threads is forbidden.
- **State Machine**: The app has exactly three states: `idle`,
  `recording`, `transcribing`. State transitions MUST update the tray
  icon color and MUST be driven by signals, not polling.
- **Error Handling**: All errors (API failures, recording errors) MUST
  result in a tray notification and a reset to idle state. The app
  MUST NOT crash or hang on transient errors.
- **Configuration**: Settings changes MUST be persisted to the JSON
  config file immediately. Hotkey listener MUST be restarted when the
  hotkey binding changes.

## Governance

- This constitution defines the non-negotiable design boundaries for
  Voice2Text. All implementation decisions MUST comply with these
  principles.
- Amendments MUST be documented with a version bump, rationale, and
  updated date.
- Versioning follows semantic versioning:
  - MAJOR: Principle removal or incompatible redefinition
  - MINOR: New principle or materially expanded guidance
  - PATCH: Clarifications, wording, typo fixes
- Any feature proposal that violates a principle MUST either be
  rejected or accompanied by a constitution amendment.

**Version**: 1.0.0 | **Ratified**: 2026-03-07 | **Last Amended**: 2026-03-07
