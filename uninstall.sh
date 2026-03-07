#!/bin/bash
set -e

APP_NAME="voice2text"
INSTALL_DIR="$HOME/.local/share/$APP_NAME"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"

echo "=== Удаление Voice2Text ==="

rm -rf "$INSTALL_DIR"
rm -f "$BIN_DIR/$APP_NAME"
rm -f "$DESKTOP_DIR/$APP_NAME.desktop"

echo "Удалено. Конфиг сохранён в ~/.config/voice2text/"
