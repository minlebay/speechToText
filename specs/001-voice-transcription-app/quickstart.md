# Quickstart: Voice2Text

## Prerequisites

- Kubuntu with KDE Plasma 5.27 (X11 session)
- Python 3.10+
- System dependencies:

```bash
sudo apt install xdotool portaudio19-dev
```

## Installation

1. Clone the repository and install Python dependencies:

```bash
cd speechToText
pip install -r requirements.txt
```

2. Get a Google Gemini API key from https://aistudio.google.com/apikey

3. Set the API key as an environment variable:

```bash
export GEMINI_API_KEY="your-api-key-here"
```

To make it permanent, add the line above to `~/.bashrc` or `~/.profile`.

## First Run

1. Launch the app:

```bash
python -m voice2text
```

2. A green circle icon appears in the system tray.

3. Right-click the tray icon and select **"Настройки"** (Settings) to configure hotkey, language, and output mode.

## Usage

1. Open any text input (editor, browser, chat).
2. Press **Ctrl+Shift+H** — the tray icon turns red (recording).
3. Speak your text.
4. Press **Ctrl+Shift+H** again — the tray icon turns yellow (processing).
5. Transcribed text is pasted into the focused field automatically.

## Configuration

Settings are stored at `~/.config/voice2text/config.json`:

| Setting      | Description                          | Default              |
| ------------ | ------------------------------------ | -------------------- |
| hotkey       | Global keyboard shortcut             | "<ctrl>+<shift>+h"   |
| output_mode  | "paste" (auto-paste) or "clipboard"  | "paste"              |
| language     | Transcription language hint          | "ru"                 |

## Troubleshooting

- **No tray icon**: Ensure you are on X11, not Wayland (`echo $XDG_SESSION_TYPE`).
- **Hotkey not working**: Check for conflicts with other apps. Try a different binding in settings.
- **"API key not set" warning**: Set `GEMINI_API_KEY` environment variable and restart the app.
- **No sound captured**: Check that your microphone is set as default in system audio settings.
