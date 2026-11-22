#!/usr/bin/env bash
# Removes the app. Your artifacts and saved data are kept unless you pass --purge.
set -euo pipefail
rm -rf "$HOME/.local/lib/artifact-deck"
rm -f "$HOME/.local/bin/artifact-deck" \
      "$HOME/.local/share/applications/dev.local.ArtifactDeck.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/dev.local.ArtifactDeck.svg"
if [ "${1:-}" = "--purge" ]; then
  rm -rf "$HOME/.local/share/artifact-deck"
  echo "App and all your artifacts/saved data removed."
else
  echo "App removed. Your artifacts are still in ~/.local/share/artifact-deck (use --purge to delete them)."
fi
