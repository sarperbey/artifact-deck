#!/usr/bin/env bash
# Installs Artifact Deck for the current user only (no sudo needed for the app itself).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$HOME/.local/lib/artifact-deck"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"

echo "Checking system packages..."
if ! python3 -c 'import gi
gi.require_version("Gtk","4.0"); gi.require_version("Adw","1"); gi.require_version("WebKit","6.0")' 2>/dev/null; then
  echo "Some required packages are missing. Installing them (needs your password):"
  sudo apt install -y python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-webkit-6.0
fi

mkdir -p "$LIB" "$BIN" "$APPS" "$ICONS"
install -m 644 "$HERE/artifact_deck.py" "$HERE/sandbox.py" "$HERE/vendor.py" "$LIB/"
if [ -d "$HERE/vendor" ]; then rm -rf "$LIB/vendor"; cp -r "$HERE/vendor" "$LIB/vendor"; fi
printf '#!/bin/sh\nexec python3 "%s/artifact_deck.py" "$@"\n' "$LIB" > "$BIN/artifact-deck"
chmod 755 "$BIN/artifact-deck"
install -m 644 "$HERE/data/dev.local.ArtifactDeck.svg" "$ICONS/"
sed "s|^Exec=.*|Exec=$BIN/artifact-deck|" "$HERE/data/dev.local.ArtifactDeck.desktop" > "$APPS/dev.local.ArtifactDeck.desktop"
update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo "Done. Open 'Artifact Deck' from your app grid, or run: artifact-deck"
