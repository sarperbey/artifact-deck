# Packing Artifact Deck

Three ways to package the app, from simplest to safest. Pick one.

| Option | Best for | Effort | Extra sandbox | Tested here |
|---|---|---|---|---|
| **A. Zip + `install.sh`** | Your own machines, sharing with a friend | Very low | No | Install and uninstall tested in a fake home folder |
| **B. `.deb` package** | A clean install and removal on Ubuntu | Low | No | Package build tested, GTK launch untested |
| **C. Flatpak** | The strongest isolation | Medium | Yes | Built and running on Ubuntu 24.04 |

If you are unsure, use **A** now and move to **C** later.

---

## Before any option: what must stay together

The app is three Python files that must sit in the same folder: `artifact_deck.py`, `sandbox.py`, `vendor.py`. The `data/` folder holds the icon and menu entry.

**Optional: bundle the React libraries.** By default each user downloads about 30 MB of libraries on first React run. To ship them inside the package, so the app never touches the internet:

```
cd artifact-deck
python3 -c "import vendor; vendor.download_all('vendor')"
```

This creates a `vendor/` folder next to the app. The app uses it automatically when all library files are present, and `install.sh` copies it along.

---

## Option A: Zip + install.sh

1. Go to the folder that contains `artifact-deck`.
2. Run `zip -r artifact-deck.zip artifact-deck -x "*.deb" "*/__pycache__/*"` (needs `sudo apt install zip`), or right-click the folder in the Files app and choose **Compress**.
3. Send the zip. The receiver unzips it and runs `bash install.sh` inside (see `install.md`).

To release an update, send a new zip. Running `install.sh` again overwrites the app and keeps the user's artifacts.

---

## Option B: .deb package

Build:

```
bash make-deb.sh                # small, libraries download on first use
bash make-deb.sh --bundle-libs  # fully offline, about 30 MB larger
```

You get `artifact-deck_0.1.0_all.deb` in the same folder.

Install, check and remove:

```
sudo apt install ./artifact-deck_0.1.0_all.deb   # also pulls in the GTK/WebKit packages
apt show artifact-deck
sudo apt remove artifact-deck                    # your artifacts in ~/.local/share are kept
```

What the package contains:

- `/usr/lib/artifact-deck/` the Python files (and `vendor/` if bundled)
- `/usr/bin/artifact-deck` the launcher
- `/usr/share/applications/` and `/usr/share/icons/` the menu entry and icon

Releasing a new version: change `VERSION` at the top of `make-deb.sh`, rebuild, and install over the old one with the same `apt install ./file.deb` command.

Notes:

- The `Depends:` line lists exactly the packages the app imports, so apt installs them for you.
- This package is for personal or small-group use. Publishing to a public repository or a PPA needs extra files (a changelog, copyright file, signed sources) that are not included.

---

## Option C: Flatpak (strongest isolation)

The app then runs in its own container with no network permission at all, so even a hostile artifact has nowhere to send data. This is the best match for "run locally and safely". It has been built and run successfully on Ubuntu 24.04 (GNOME runtime 50).

**Step 1.** The libraries are already bundled in `vendor/` in this repo. If you removed them, re-download (see the optional step above) - a Flatpak with no network permission cannot fetch them later.

**Step 2.** Install the tools once:

```
sudo apt install flatpak flatpak-builder
flatpak remote-add --if-not-exists --user flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak remote-ls flathub --runtime | grep -E "org.gnome.(Platform|Sdk)"   # note the newest version number
flatpak install --user flathub org.gnome.Platform//<version> org.gnome.Sdk//<version>
```

**Step 3.** Save this as `dev.local.ArtifactDeck.yml` inside the `artifact-deck` folder, replacing `<version>` with the number from step 2:

```yaml
app-id: dev.local.ArtifactDeck
runtime: org.gnome.Platform
runtime-version: '<version>'
sdk: org.gnome.Sdk
command: artifact-deck
finish-args:
  - --socket=wayland
  - --socket=fallback-x11
  - --share=ipc
  - --device=dri
  - --filesystem=xdg-data/artifact-deck:create
  # No --share=network on purpose.
modules:
  - name: artifact-deck
    buildsystem: simple
    build-commands:
      - install -d /app/lib/artifact-deck
      - cp -r artifact_deck.py sandbox.py vendor.py vendor /app/lib/artifact-deck/
      - install -Dm755 launcher.sh /app/bin/artifact-deck
      - install -Dm644 data/dev.local.ArtifactDeck.svg /app/share/icons/hicolor/scalable/apps/dev.local.ArtifactDeck.svg
      - install -Dm644 data/dev.local.ArtifactDeck.desktop /app/share/applications/dev.local.ArtifactDeck.desktop
    sources:
      - type: dir
        path: .
      - type: script
        dest-filename: launcher.sh
        commands:
          - exec python3 /app/lib/artifact-deck/artifact_deck.py "$@"
```

**Step 4.** Build, install and run:

```
flatpak-builder --user --install --force-clean build-dir dev.local.ArtifactDeck.yml
flatpak run dev.local.ArtifactDeck
```

**Step 5.** Share it as a single file:

```
flatpak build-bundle ~/.local/share/flatpak/repo artifact-deck.flatpak dev.local.ArtifactDeck
```

The receiver installs it with `flatpak install --user artifact-deck.flatpak`.

Things to know:

- Data moves to `~/.var/app/dev.local.ArtifactDeck/data/artifact-deck/`. Copy your old `artifact-deck` folder there to migrate.
- The file picker opens through the system portal, so the app can only see files you choose. Drag-and-drop works the same way.
- The GNOME runtime should include WebKitGTK 6.0. If the build complains about `WebKit`, check the runtime's release notes.
- Publishing on Flathub requires an app ID you own (such as `io.github.yourname.ArtifactDeck`) and AppStream metadata. That is not needed for personal use.

---

## Not recommended

- **Snap:** possible, but WebKitGTK and GTK4 packaging there is harder than with Flatpak, with no extra benefit for you.
- **AppImage:** bundling WebKitGTK is heavy and fragile.
- **PyInstaller:** it does not handle GTK and WebKit libraries well.

## Release checklist

1. Run the app from the folder (`python3 artifact_deck.py`) and add, run and delete one artifact.
2. Run a React artifact, with the libraries bundled or downloaded.
3. Build the package.
4. Install it on a second account or a fresh machine and open it from the app grid.
5. Remove it and confirm your artifacts folder is still there.
