# Feature Specification: Voice Transcription Desktop App

**Feature Branch**: `001-voice-transcription-app`
**Created**: 2026-03-07
**Status**: Draft
**Input**: User description: "Desktop voice transcription app for Linux (KDE Plasma) that captures voice input via a global hotkey and transcribes it using a cloud API, then inserts the recognized text into the currently focused input field or clipboard."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Quick Voice-to-Text Entry (Priority: P1)

A desktop user presses a keyboard shortcut to start recording their voice. They speak a sentence or paragraph, then press the same shortcut again to stop recording. Within a few seconds, the transcribed text appears in whatever input field they had focused (text editor, chat window, browser form, etc.) as if they had typed it.

**Why this priority**: This is the core value proposition — hands-free text entry into any application. Without this, the app has no purpose.

**Independent Test**: User opens a text editor, presses the hotkey, speaks "Hello world", presses the hotkey again, and sees "Hello world" appear in the editor.

**Acceptance Scenarios**:

1. **Given** the app is running in the system tray and idle, **When** the user presses the configured hotkey, **Then** audio recording begins from the default microphone and the tray icon changes to indicate recording.
2. **Given** the app is recording, **When** the user presses the hotkey again, **Then** recording stops, the tray icon changes to indicate processing, the audio is sent for transcription, and the resulting text is pasted into the currently focused input field.
3. **Given** the app has completed transcription, **When** the text is delivered, **Then** a brief notification appears showing a preview of the transcribed text and the tray icon returns to idle state.

---

### User Story 2 - Clipboard-Only Mode (Priority: P2)

A user prefers to review transcribed text before inserting it. They configure the app to copy transcription results to the clipboard only, without auto-pasting. After recording and transcription, they manually paste (Ctrl+V) wherever they choose.

**Why this priority**: Some applications or workflows may not support automated paste. Clipboard-only mode provides a reliable fallback.

**Independent Test**: User sets output mode to "clipboard only" in settings, records audio, and verifies the transcribed text is in the clipboard without it being auto-pasted anywhere.

**Acceptance Scenarios**:

1. **Given** the output mode is set to clipboard-only, **When** transcription completes, **Then** the text is copied to the system clipboard but NOT automatically pasted.
2. **Given** the text is in the clipboard, **When** the user presses Ctrl+V in any application, **Then** the transcribed text is pasted.

---

### User Story 3 - App Configuration (Priority: P2)

A user wants to customize the app behavior: change the keyboard shortcut, set their preferred language for transcription, switch between paste and clipboard-only modes, and enter their cloud API credentials.

**Why this priority**: Without configuration, the app cannot authenticate with the transcription service and users cannot tailor behavior to their workflow.

**Independent Test**: User opens settings from the tray menu, changes the hotkey and language, saves, and verifies the new hotkey triggers recording and transcription uses the new language.

**Acceptance Scenarios**:

1. **Given** the app is running, **When** the user right-clicks the tray icon and selects "Settings", **Then** a settings dialog appears with fields for hotkey, output mode, and language.
2. **Given** the user changes the hotkey in settings and saves, **When** they press the new hotkey, **Then** recording starts using the new binding.
3. **Given** the user changes the language setting, **When** they record and transcribe audio, **Then** the transcription result reflects the selected language.

---

### User Story 4 - System Tray Presence (Priority: P3)

The app runs as a background utility with a system tray icon that provides visual feedback about the current state (idle, recording, processing). The user can access settings and quit the app from the tray context menu.

**Why this priority**: The tray icon is the only persistent UI. It provides essential state awareness and access to app controls.

**Independent Test**: User launches the app and verifies the tray icon appears, changes color during recording and processing, and offers a context menu with Settings and Quit options.

**Acceptance Scenarios**:

1. **Given** the app is launched, **When** it finishes initializing, **Then** a tray icon appears in the system tray with an idle-state visual indicator.
2. **Given** the app is idle, **When** the user right-clicks the tray icon, **Then** a context menu appears with "Settings" and "Quit" options.
3. **Given** the app state changes (idle -> recording -> processing -> idle), **When** each transition occurs, **Then** the tray icon updates its visual indicator to reflect the current state.

---

### Edge Cases

- What happens when the user presses the hotkey while transcription is still in progress from a previous recording? The app MUST ignore the hotkey press until it returns to idle state.
- What happens when the cloud API returns an error (invalid key, network timeout, quota exceeded)? The app MUST show an error notification and return to idle state without crashing.
- What happens when no microphone is available or the microphone fails mid-recording? The app MUST show an error notification and return to idle state.
- What happens when the API key environment variable is not set? The app MUST show a warning notification prompting the user to set the environment variable and MUST NOT start recording.
- What happens when the configured hotkey conflicts with another application's shortcut? The app MUST still attempt to register the hotkey; if registration fails, it MUST notify the user.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST capture audio from the default system microphone when recording is active.
- **FR-002**: System MUST toggle recording on/off via a single user-configurable global keyboard shortcut.
- **FR-003**: System MUST send recorded audio to a cloud transcription service and receive text results.
- **FR-004**: System MUST support two output modes: auto-paste into focused field, or clipboard-only.
- **FR-005**: System MUST display a persistent system tray icon that visually indicates current state (idle, recording, processing).
- **FR-006**: System MUST provide a settings dialog accessible from the tray context menu for configuring: keyboard shortcut, output mode, and transcription language. API credentials MUST be read from an environment variable.
- **FR-007**: System MUST persist user settings between app restarts.
- **FR-008**: System MUST show desktop notifications for recording start, transcription results (preview), and errors.
- **FR-009**: System MUST prevent recording when API credentials are not configured, showing a warning instead.
- **FR-010**: System MUST remain responsive during transcription (no UI freezing while waiting for cloud API response).

### Key Entities

- **Recording Session**: A captured audio segment with start/stop boundaries and raw audio data.
- **Transcription Result**: The text output from the cloud service for a given recording session.
- **App Configuration**: User preferences including hotkey binding, output mode, and language setting. API key is sourced from an environment variable, not stored in config.
- **App State**: The current operational mode of the application — one of: idle, recording, or processing.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can complete a full voice-to-text cycle (press hotkey, speak, press hotkey, see text) in under 10 seconds for a single sentence.
- **SC-002**: Transcription accuracy for clear speech in a quiet environment exceeds 90% word accuracy for the configured language.
- **SC-003**: The app remains responsive at all times — tray icon interactions and settings dialog open within 1 second even during active transcription.
- **SC-004**: The app starts and is ready to accept hotkey input within 3 seconds of launch.
- **SC-005**: 100% of cloud API errors result in a user-visible notification rather than a silent failure or crash.
- **SC-006**: Settings changes take effect immediately without requiring an app restart.
- **SC-007**: The app consumes less than 50 MB of memory while idle and less than 150 MB during active recording/transcription.

## Assumptions

- The user's desktop environment supports system tray icons (standard on KDE Plasma).
- The user has a working microphone connected and configured as the default input device.
- The user has internet connectivity for cloud API transcription calls.
- The target desktop environment uses X11 (not Wayland) for global hotkey and paste simulation support.
- The user will obtain their own cloud API key and set it as an environment variable before launching the app.
- Audio quality from the default microphone is sufficient for speech recognition (no noise cancellation is provided by the app).
