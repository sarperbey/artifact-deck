#!/usr/bin/env bash
# Builds artifact-deck_<version>_all.deb in this folder.
#   ./make-deb.sh               small package; React libraries download on first use
#   ./make-deb.sh --bundle-libs fully offline package (downloads libraries once, now)
set -euo pipefail
VERSION="0.1.0"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG="$(mktemp -d)"
trap 'rm -rf "$PKG"' EXIT
ROOT="$PKG/artifact-deck_${VERSION}_all"

install -d "$ROOT/DEBIAN" "$ROOT/usr/lib/artifact-deck" "$ROOT/usr/bin" \
           "$ROOT/usr/share/applications" "$ROOT/usr/share/icons/hicolor/scalable/apps"
install -m 644 "$HERE/artifact_deck.py" "$HERE/sandbox.py" "$HERE/vendor.py" "$ROOT/usr/lib/artifact-deck/"

if [ "${1:-}" = "--bundle-libs" ]; then
  python3 - "$ROOT/usr/lib/artifact-deck/vendor" <<'PY'
import sys; sys.path.insert(0, ".")
import vendor
vendor.download_all(sys.argv[1], lambda i, t, n: print("  libraries %d/%d %s" % (i, t, n)))
PY
fi

printf '#!/bin/sh\nexec python3 /usr/lib/artifact-deck/artifact_deck.py "$@"\n' > "$ROOT/usr/bin/artifact-deck"
chmod 755 "$ROOT/usr/bin/artifact-deck"
install -m 644 "$HERE/data/dev.local.ArtifactDeck.svg" "$ROOT/usr/share/icons/hicolor/scalable/apps/"
install -m 644 "$HERE/data/dev.local.ArtifactDeck.desktop" "$ROOT/usr/share/applications/"

SIZE=$(du -sk "$ROOT/usr" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<CTRL
Package: artifact-deck
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Installed-Size: $SIZE
Depends: python3, python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, gir1.2-webkit-6.0
Maintainer: Local <local@localhost>
Description: Run AI-made artifacts in a sandbox
 GTK4/libadwaita dashboard for HTML, JavaScript and React artifacts made
 by Claude, Gemini, DeepSeek and others. Artifacts run without network access.
CTRL

dpkg-deb --root-owner-group --build "$ROOT" "$HERE/artifact-deck_${VERSION}_all.deb" >/dev/null
echo "Built: $HERE/artifact-deck_${VERSION}_all.deb"
