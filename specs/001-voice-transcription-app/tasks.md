# Tasks: Voice Transcription Desktop App

**Input**: Design documents from `/specs/001-voice-transcription-app/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md

**Tests**: Not explicitly requested in the specification. Test tasks are omitted.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Package**: `voice2text/` at repository root
- **Config**: `~/.config/voice2text/config.json`
- **Entry point**: `python -m voice2text`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization, package structure, and dependencies

- [x] T001 Create package directory `voice2text/` with `voice2text/__init__.py`
- [x] T002 Create `requirements.txt` at repo root with: PyQt5>=5.15, pynput>=1.7, sounddevice>=0.4, numpy>=1.24, google-generativeai>=0.8
- [x] T003 Create entry point `voice2text/__main__.py` that imports and calls `main()` from `voice2text/app.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core modules that ALL user stories depend on

**CRITICAL**: No user story work can begin until this phase is complete

- [x] T004 Implement config module in `voice2text/config.py`: `load_config()` reads JSON from `~/.config/voice2text/config.json` with defaults (hotkey: `<ctrl>+<shift>+h`, output_mode: `paste`, language: `ru`), `save_config(cfg)` writes JSON, `get_api_key()` reads `GEMINI_API_KEY` env var via `os.environ.get()`. Create config dir with `os.makedirs(exist_ok=True)` if missing.
- [x] T005 Implement `SignalBridge(QObject)` in `voice2text/app.py`: define `pyqtSignal` for `toggle_recording`, `transcription_ready(str)`, `error(str)` to bridge background threads to Qt main thread.
- [x] T006 Implement `make_icon(color: str) -> QIcon` helper in `voice2text/app.py`: draw filled circle on 64x64 transparent QPixmap using QPainter. Support colors: "green", "red", "yellow".

**Checkpoint**: Foundation ready — config, signals, and icon helper available for all stories.

---

## Phase 3: User Story 1 — Quick Voice-to-Text Entry (Priority: P1) MVP

**Goal**: User presses hotkey to record voice, presses again to stop, transcribed text is pasted into the focused input field.

**Independent Test**: Launch app, open a text editor, press Ctrl+Shift+H, speak, press Ctrl+Shift+H again, verify transcribed text appears in the editor.

### Implementation for User Story 1

- [x] T007 [US1] Implement `Recorder` class in `voice2text/recorder.py`: `__init__(samplerate=16000, channels=1)`, `start()` opens `sounddevice.InputStream` with callback appending `indata.copy()` to frames list, `stop() -> bytes` concatenates numpy arrays and encodes to WAV via `io.BytesIO` + `wave` module.
- [x] T008 [US1] Implement `transcribe(audio_wav: bytes, api_key: str, language: str) -> str` in `voice2text/transcriber.py`: configure `google.generativeai` with api_key, use model `gemini-2.0-flash`, send prompt "Transcribe this audio exactly as spoken. The language is {language}. Output only the transcription text, nothing else." with `{"mime_type": "audio/wav", "data": audio_wav}`, return `response.text.strip()`.
- [x] T009 [US1] Implement `App` class in `voice2text/app.py`: initialize `QApplication`, `QSystemTrayIcon` with green icon, `Recorder`, `SignalBridge`. Implement state machine with three states (`idle`, `recording`, `transcribing`). Connect `toggle_recording` signal to state handler.
- [x] T010 [US1] Implement hotkey listener in `App.__init__` in `voice2text/app.py`: create `pynput.keyboard.GlobalHotKeys` with configured hotkey that emits `SignalBridge.toggle_recording` signal. Start listener as daemon thread.
- [x] T011 [US1] Implement recording toggle handler in `App` in `voice2text/app.py`: on first press (idle → recording) call `Recorder.start()`, set icon red, show tray notification "Запись...". Guard: if `get_api_key()` returns empty, show warning "API ключ не установлен" and do not start.
- [x] T012 [US1] Implement transcription flow in `App` in `voice2text/app.py`: on second press (recording → transcribing) call `Recorder.stop()`, set icon yellow, launch `threading.Thread` that calls `transcribe()` and emits `transcription_ready(text)` or `error(msg)` signal on completion.
- [x] T013 [US1] Implement paste output handler in `App` in `voice2text/app.py`: on `transcription_ready` signal, copy text to `QApplication.clipboard()`, run `subprocess.Popen(["xdotool", "key", "--clearmodifiers", "ctrl+v"])`, show tray notification with first 50 chars of result, set icon green. On `error` signal, show error notification and set icon green.
- [x] T014 [US1] Implement `main()` function in `voice2text/app.py`: create `QApplication`, check `QSystemTrayIcon.isSystemTrayAvailable()`, set `QApplication.setQuitOnLastWindowClosed(False)`, instantiate `App`, call `app.exec_()`.

**Checkpoint**: Core voice-to-text flow works end-to-end with auto-paste. MVP complete.

---

## Phase 4: User Story 2 — Clipboard-Only Mode (Priority: P2)

**Goal**: User can switch to clipboard-only mode where transcription is copied to clipboard without auto-pasting.

**Independent Test**: Set output_mode to "clipboard" in settings, record and transcribe, verify text is in clipboard but NOT auto-pasted.

### Implementation for User Story 2

- [x] T015 [US2] Update paste output handler in `voice2text/app.py`: check `config["output_mode"]` — if "paste" run xdotool paste, if "clipboard" only copy to clipboard without xdotool. Show notification in both cases.

**Checkpoint**: Both output modes (paste and clipboard) work independently.

---

## Phase 5: User Story 3 — App Configuration (Priority: P2)

**Goal**: User can configure hotkey, output mode, and language via a settings dialog from the tray menu.

**Independent Test**: Open settings from tray, change hotkey to a different binding, save, verify new hotkey works.

### Implementation for User Story 3

- [x] T016 [US3] Implement `SettingsDialog(QDialog)` in `voice2text/app.py`: fields for hotkey (`QLineEdit`), output mode (`QComboBox` with "paste"/"clipboard"), language (`QLineEdit`). Labels in Russian: "Горячая клавиша", "Режим вывода", "Язык". "Сохранить" and "Отмена" buttons. Load current config values on open, return updated config dict on accept.
- [x] T017 [US3] Add tray context menu to `App.__init__` in `voice2text/app.py`: create `QMenu` with "Настройки" action (opens `SettingsDialog`) and "Выход" action (calls `QApplication.quit()`). Set menu on `QSystemTrayIcon`.
- [x] T018 [US3] Implement settings save handler in `App` in `voice2text/app.py`: on dialog accept, call `save_config()` with new values. If hotkey changed, stop old `GlobalHotKeys` listener and create new one with updated binding.

**Checkpoint**: Settings dialog works, config persists, hotkey rebinding works live.

---

## Phase 6: User Story 4 — System Tray Presence (Priority: P3)

**Goal**: Tray icon provides visual state feedback (green/red/yellow) and context menu access.

**Independent Test**: Launch app, verify green icon. Record → red. Processing → yellow. Complete → green. Right-click → menu with Settings and Quit.

### Implementation for User Story 4

- [x] T019 [US4] Verify tray icon state transitions in `voice2text/app.py`: ensure all state changes (idle→recording→transcribing→idle, plus error→idle) update the tray icon via `make_icon()`. Add tray tooltip text reflecting current state: "Voice2Text — Готов", "Voice2Text — Запись...", "Voice2Text — Обработка...".

**Checkpoint**: All tray icon states and context menu working correctly.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Error handling, edge cases, and final validation

- [x] T020 Add error handling for microphone failures in `voice2text/recorder.py`: catch `sounddevice` exceptions in `start()` and `stop()`, raise descriptive error that `App` catches and surfaces via error notification.
- [x] T021 Add error handling for Gemini API failures in `voice2text/transcriber.py`: catch `google.api_core.exceptions` and network errors, raise descriptive error that `App` catches via `error` signal.
- [x] T022 Add hotkey-during-transcription guard in `voice2text/app.py`: if state is `transcribing`, ignore hotkey press (no-op).
- [x] T023 Run quickstart.md validation: follow all steps in `specs/001-voice-transcription-app/quickstart.md` end-to-end on target system.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 completion — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 — core MVP
- **US2 (Phase 4)**: Depends on Phase 3 (extends paste handler from US1)
- **US3 (Phase 5)**: Depends on Phase 2 (settings dialog + hotkey restart)
- **US4 (Phase 6)**: Depends on Phase 3 (tray icon states built in US1, this validates them)
- **Polish (Phase 7)**: Depends on all user stories being complete

### User Story Dependencies

- **US1 (P1)**: Depends on Foundational only — no other story dependencies
- **US2 (P2)**: Depends on US1 (extends the output handler)
- **US3 (P2)**: Can start after Foundational — independent of US1/US2
- **US4 (P3)**: Depends on US1 (validates icon states built during US1)

### Within Each User Story

- Models/utilities before services
- Services before UI integration
- Core implementation before polish

### Parallel Opportunities

- T001 and T002 can run in parallel (different files)
- T007 and T008 can run in parallel (recorder.py and transcriber.py are independent)
- US3 (Phase 5) can run in parallel with US2 (Phase 4) since they touch different parts of app.py
- T020 and T021 can run in parallel (different files)

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (config, signals, icons)
3. Complete Phase 3: User Story 1 (record → transcribe → paste)
4. **STOP and VALIDATE**: Test full voice-to-text cycle end-to-end
5. App is usable at this point with default settings

### Incremental Delivery

1. Setup + Foundational → project structure ready
2. US1 → Core voice-to-text with auto-paste (MVP!)
3. US2 → Add clipboard-only mode option
4. US3 → Add settings dialog for customization
5. US4 → Validate tray icon states and polish
6. Polish → Error handling, edge cases, quickstart validation

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- All UI strings MUST be in Russian per constitution
- API key comes from `GEMINI_API_KEY` env var, not config file
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
