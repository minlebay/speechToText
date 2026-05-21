#!/bin/bash
set -e

APP_NAME="voice2text"
INSTALL_DIR="$HOME/.local/share/$APP_NAME"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Установка Voice2Text ==="

# Проверка системных зависимостей
for cmd in xdotool python3; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Ошибка: $cmd не найден. Установите: sudo apt install $cmd"
        exit 1
    fi
done

if ! dpkg -s portaudio19-dev &>/dev/null 2>&1; then
    echo "Ошибка: portaudio19-dev не установлен. Установите: sudo apt install portaudio19-dev"
    exit 1
fi

# Проверка python3-venv
if ! python3 -m venv --help &>/dev/null 2>&1; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    echo "Ошибка: python3-venv не установлен. Установите: sudo apt install python${PY_VER}-venv"
    exit 1
fi

# Создание директории установки
mkdir -p "$INSTALL_DIR"

# Копирование файлов приложения
cp -r "$SCRIPT_DIR/voice2text" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"

# Создание виртуального окружения и установка зависимостей
echo "Создание виртуального окружения..."
python3 -m venv "$INSTALL_DIR/venv"
echo "Установка зависимостей..."
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

# Создание скрипта запуска
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/$APP_NAME" << 'LAUNCHER'
#!/bin/bash
# Загружаем export-переменные из .bashrc (обходя проверку интерактивности)
if [ -f "$HOME/.bashrc" ]; then
    eval "$(grep -E '^\s*export\s+' "$HOME/.bashrc")"
fi
cd "$HOME/.local/share/voice2text"
exec "$HOME/.local/share/voice2text/venv/bin/python" -m voice2text "$@"
LAUNCHER
chmod +x "$BIN_DIR/$APP_NAME"

# Установка иконки приложения
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$ICON_DIR"
cp "$SCRIPT_DIR/voice2text/assets/voice2text.svg" "$ICON_DIR/voice2text.svg"

# Создание .desktop файла
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/$APP_NAME.desktop" << EOF
[Desktop Entry]
Name=Voice2Text
Comment=Голосовой ввод текста
Exec=$BIN_DIR/$APP_NAME
Icon=voice2text
Type=Application
Categories=Utility;Audio;
StartupNotify=false
X-GNOME-Autostart-enabled=false
EOF

echo ""
echo "=== Установка завершена ==="
echo ""
echo "Запуск: $APP_NAME"
echo ""
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo "ВНИМАНИЕ: $BIN_DIR не в PATH."
    echo "Добавьте в ~/.bashrc:"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
fi
echo "Для Gemini движка установите GEMINI_API_KEY_TTS в ~/.bashrc:"
echo "  export GEMINI_API_KEY_TTS=\"ваш_ключ\""
