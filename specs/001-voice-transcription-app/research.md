# Research: Voice Transcription Desktop App

**Branch**: `001-voice-transcription-app`
**Date**: 2026-03-07

## R1: PyQt5 System Tray on KDE Plasma 5.27

**Decision**: Use `QSystemTrayIcon` with `QPixmap`-based colored circle icons.

**Rationale**: QSystemTrayIcon is the standard Qt approach and works
natively on KDE Plasma. Drawing icons programmatically (filled circles
on transparent QPixmap) avoids shipping icon assets and allows dynamic
color changes for state indication.

**Alternatives considered**:
- KStatusNotifierItem (KDE-specific D-Bus protocol): Better Plasma
  integration but requires extra D-Bus bindings and breaks portability.
  QSystemTrayIcon provides the SNI backend automatically on KDE.
- Static icon files with swap: More overhead to manage multiple icon
  files. Programmatic drawing is simpler for solid-color circles.

**Key findings**:
- `QSystemTrayIcon.isSystemTrayAvailable()` MUST be checked at startup.
- `QApplication.setQuitOnLastWindowClosed(False)` is required for
  tray-only apps.
- `showMessage()` method provides native desktop notifications.
- Icon size 64x64 QPixmap with `QPainter` filled ellipse works well.

## R2: pynput Global Hotkeys on X11

**Decision**: Use `pynput.keyboard.GlobalHotKeys` with configurable
hotkey string in pynput format (e.g., `<ctrl>+<shift>+h`).

**Rationale**: pynput provides a simple, well-maintained global hotkey
API for X11. It runs its own listener thread, which integrates cleanly
with Qt via signal bridging.

**Alternatives considered**:
- PyKDE/KGlobalAccel: KDE-specific, complex D-Bus setup, overkill.
- python-xlib direct: Low-level X11 key grabbing, more code, fragile.
- QShortcut: Only works for Qt widgets with focus, not global.

**Key findings**:
- `GlobalHotKeys` runs in a daemon thread — callbacks fire on that
  thread, so they MUST emit a pyqtSignal rather than manipulate Qt
  widgets directly.
- When the hotkey changes in settings, the old listener MUST be
  stopped and a new one created with the updated binding.
- pynput requires X11 access (`DISPLAY` env var); will not work on
  pure Wayland sessions.

## R3: sounddevice Audio Recording

**Decision**: Use `sounddevice.InputStream` with callback mode,
16kHz sample rate, mono channel, int16 dtype.

**Rationale**: sounddevice wraps PortAudio with a clean Python API.
Callback mode allows non-blocking audio capture that collects frames
in a list, then concatenates them on stop.

**Alternatives considered**:
- PyAudio: Older PortAudio wrapper, less Pythonic API, more boilerplate.
- GStreamer (via PyGObject): Powerful but massive dependency for simple
  mic capture.

**Key findings**:
- InputStream callback receives `(indata, frames, time, status)`.
  Append `indata.copy()` to a list (copy is required — buffer is reused).
- On stop: `numpy.concatenate(frames)`, then write to `io.BytesIO`
  using the `wave` module (16-bit PCM, 16kHz, mono).
- System dependency: `portaudio19-dev` must be installed for
  sounddevice to find PortAudio.

## R4: Google Gemini API for Audio Transcription

**Decision**: Use `google-generativeai` SDK with `gemini-2.0-flash`
model, sending WAV bytes inline with a transcription prompt.

**Rationale**: Gemini 2.0 Flash supports audio input natively, offers
fast inference, and provides good multilingual transcription quality.
The SDK handles authentication and request formatting.

**Alternatives considered**:
- OpenAI Whisper API: Proven transcription, but separate service with
  different pricing and SDK.
- Local Whisper (whisper.cpp / faster-whisper): Offline capability but
  requires 1-5 GB RAM and GPU for real-time performance.
- Vosk: Lightweight offline, but lower accuracy for non-English.

**Key findings**:
- `genai.configure(api_key=key)` sets the API key globally.
- `model.generate_content([prompt, {"mime_type": "audio/wav", "data": wav_bytes}])`
  sends audio inline.
- Response text is in `response.text` — strip whitespace before use.
- API call MUST run in `threading.Thread` to avoid blocking Qt event loop.
- Error handling: catch `google.api_core.exceptions` for network/auth
  errors and surface via pyqtSignal.

## R5: xdotool Paste Simulation

**Decision**: Use `subprocess.Popen(["xdotool", "key", "--clearmodifiers", "ctrl+v"])`
to simulate Ctrl+V paste after copying text to clipboard.

**Rationale**: xdotool is the standard X11 tool for simulating
keyboard input. `--clearmodifiers` ensures the hotkey modifier keys
don't interfere with the paste shortcut.

**Alternatives considered**:
- xdg-utils: No keyboard simulation capability.
- python-xlib SendEvent: Complex, fragile, requires deep X11 knowledge.
- ydotool: Wayland alternative, but project targets X11 only.

**Key findings**:
- `--clearmodifiers` is critical — without it, Ctrl+Shift from the
  hotkey may still be held, producing Ctrl+Shift+V instead of Ctrl+V.
- Clipboard MUST be set before invoking xdotool.
- Use `subprocess.Popen` (not `run`) to avoid blocking if xdotool
  hangs; or use `run` with a short timeout.

## R6: JSON Configuration

**Decision**: Plain JSON file at `~/.config/voice2text/config.json`
with 4 fields: `api_key`, `hotkey`, `output_mode`, `language`.

**Rationale**: JSON is human-readable, stdlib-supported (`json` module),
and follows XDG conventions for Linux desktop apps. No external
config library needed.

**Alternatives considered**:
- TOML: Nicer syntax but requires `tomllib` (Python 3.11+) or
  external package.
- YAML: External dependency (PyYAML), overkill for 4 fields.
- QSettings: Qt-specific, less transparent file format.

**Key findings**:
- Create `~/.config/voice2text/` directory on first run if missing
  (`os.makedirs` with `exist_ok=True`).
- Provide sensible defaults for all config fields (hotkey, output_mode,
  language).
- API key MUST be read from `GEMINI_API_KEY` environment variable
  (`os.environ.get("GEMINI_API_KEY", "")`), NOT stored in config file.
  This avoids leaking secrets in plaintext JSON.
- Save immediately on settings change (no deferred writes).
- Load at startup; fall back to defaults if file is missing or corrupt.
