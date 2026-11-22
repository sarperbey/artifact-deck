# Installing Artifact Deck

For **Ubuntu 24.04 or newer** (GNOME desktop).

> Status: the library, sandbox and React logic were tested in a headless browser. The GTK window itself has not yet been run on a real desktop, so a small first-launch fix is possible. Section 5 covers the likely problems.

## 1. Quick install (recommended)

1. Keep the whole `artifact-deck` folder together (the `.py` files, `data/`, and the scripts).
2. Open a terminal inside that folder. In the Files app, right-click the folder and choose **Open in Terminal**.
3. Run:

   ```
   bash install.sh
   ```

4. If a package is missing, the script asks for your password and installs it.
5. Open **Artifact Deck** from the app grid (press the Super key and type "Artifact"), or run `artifact-deck` in a terminal.

If `artifact-deck` is "command not found" right after installing, log out and back in once. Ubuntu adds `~/.local/bin` to your path at login.

## 2. Manual install (no script)

```
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-webkit-6.0
cd artifact-deck
python3 artifact_deck.py
```

This runs the app straight from the folder, with no menu entry.

## 3. First run

1. Drag an `.html` file onto the window, or press the folder button.
2. Give it a name, choose who made it, press **Add**.
3. Press **Run**.

The first time you run a **React** artifact, the app asks for a one-time download of its libraries (about 30 MB). Press **Download libraries**. This is the only time the app uses the internet. Each file is checked against the npm registry's checksum, and the app stops if one does not match.

## 4. Update, uninstall

- **Update:** replace the folder with the new version and run `bash install.sh` again. Your artifacts are kept.
- **Uninstall:** `bash uninstall.sh` removes the app but keeps your artifacts.
- **Remove everything:** `bash uninstall.sh --purge` also deletes your library and saved data.

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'gi'` | `sudo apt install python3-gi` |
| `Namespace WebKit not available` or `WebKit 6.0 not found` | `sudo apt install gir1.2-webkit-6.0` |
| `Namespace Adw not available` | `sudo apt install gir1.2-adw-1` |
| `AttributeError` mentioning `AlertDialog`, `ToolbarView` or `NavigationView` | Your libadwaita is older than 1.5. Use Ubuntu 24.04 or newer |
| Window opens but artifacts stay blank or the web process crashes | See the sandbox note below, then open the console (terminal button) for errors |
| "Download failed" for React libraries | Check your internet connection and press the button again |
| `.sh` file will not run by double-click | Always start it with `bash install.sh` from a terminal |
| App icon looks generic | Log out and in, or run `gtk-update-icon-cache -f -t ~/.local/share/icons/hicolor` |

**Sandbox note.** WebKitGTK uses its own process sandbox (bubblewrap). Ubuntu 24.04 restricts unprivileged user namespaces with AppArmor, which can block it. Do **not** work around this by disabling the sandbox (for example with `WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS`). Use the Flatpak route in `packing.md` instead, or ask for help with an AppArmor profile.

**To see errors.** Start the app from a terminal with `artifact-deck`. Python messages appear there.

## 6. Data location

`~/.local/share/artifact-deck/`. Back this folder up to keep your library. In the Flatpak version it is `~/.var/app/dev.local.ArtifactDeck/data/artifact-deck/`.
