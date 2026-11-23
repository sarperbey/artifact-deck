#!/usr/bin/env python3
"""Artifact Deck: GTK4/libadwaita dashboard that runs AI-made artifacts in a
locked-down WebKitGTK view (no network, no popups, no permissions).

Ubuntu 24.04 deps:
    sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-webkit-6.0
Run:
    python3 artifact_deck.py
"""
import json
import os
import re
import sys
import threading
import time
import uuid

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango, WebKit  # noqa: E402

import sandbox  # noqa: E402
import vendor  # noqa: E402

APP_ID = "dev.local.ArtifactDeck"
DATA_DIR = os.path.join(GLib.get_user_data_dir(), "artifact-deck")
ART_DIR = os.path.join(DATA_DIR, "artifacts")
STATE_DIR = os.path.join(DATA_DIR, "state")
# Libraries shipped inside the package win; otherwise use the per-user download folder.
BUNDLED_VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
VENDOR_DIR = (BUNDLED_VENDOR if not vendor.missing_files(BUNDLED_VENDOR, vendor.ALL_FILES)
              else os.path.join(DATA_DIR, "vendor"))

SOURCES = {"claude": "Claude", "gemini": "Gemini", "deepseek": "DeepSeek", "other": "Other"}
TYPES = {"html": "HTML", "js": "JavaScript", "react": "React"}
EXT = {"html": ".html", "js": ".js", "react": ".jsx"}
ACCEPTED = (".html", ".htm", ".js", ".jsx", ".tsx", ".txt")
MAX_BYTES = 5 * 1024 * 1024
SCHEMES = {"system": Adw.ColorScheme.DEFAULT, "light": Adw.ColorScheme.FORCE_LIGHT,
           "dark": Adw.ColorScheme.FORCE_DARK}

CSS = """
.deck-card { padding: 14px; }
.src-claude { color: @orange_3; }
.src-gemini { color: @blue_3; }
.src-deepseek { color: @purple_3; }
.src-other { color: @green_4; }
.side-handle { opacity: 0.5; }
.drop-before { box-shadow: inset 0 2px 0 0 @accent_bg_color; }
.drop-after { box-shadow: inset 0 -2px 0 0 @accent_bg_color; }
"""

# ---------------------------------------------------------------- storage --

class Settings:
    """Tiny key/value store for app preferences (currently just the theme)."""

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.path = os.path.join(DATA_DIR, "settings.json")
        self.data = {}
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.data = data
        except (OSError, ValueError):
            pass

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, self.path)


class Library:
    def __init__(self):
        for d in (ART_DIR, STATE_DIR, VENDOR_DIR):
            os.makedirs(d, exist_ok=True)
        self.path = os.path.join(DATA_DIR, "library.json")
        self.items = []
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self.items = [a for a in data if isinstance(a, dict)
                              and re.fullmatch(r"[0-9a-f]{12}", str(a.get("id", "")))
                              and a.get("type") in EXT and a.get("source") in SOURCES
                              and isinstance(a.get("name"), str)
                              and isinstance(a.get("tags", []), list)]
                for a in self.items:
                    a.setdefault("fav", False)
                    a.setdefault("runs", 0)
                    a.setdefault("created", 0)
                    a.setdefault("last_run", 0)
                    a.setdefault("tags", [])
        except (OSError, ValueError):
            pass

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.items, f, indent=2)
        os.replace(tmp, self.path)

    def code_path(self, a):
        return os.path.join(ART_DIR, a["id"] + EXT[a["type"]])

    def read_code(self, a):
        try:
            with open(self.code_path(a), encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def write_code(self, a, code):
        with open(self.code_path(a), "w", encoding="utf-8") as f:
            f.write(code)

    def add(self, name, source, type_, code, tags):
        a = {"id": uuid.uuid4().hex[:12], "name": name or "Untitled", "source": source,
             "type": type_, "tags": tags, "fav": False, "runs": 0,
             "created": int(time.time()), "last_run": 0}
        self.write_code(a, code)
        self.items.insert(0, a)
        self.save()
        return a

    def remove(self, a):
        idx = self.items.index(a)
        code = self.read_code(a)
        self.items.pop(idx)
        try:
            os.remove(self.code_path(a))
        except OSError:
            pass
        self.save()
        return a, code, idx

    def restore(self, a, code, idx):
        self.write_code(a, code)
        self.items.insert(min(idx, len(self.items)), a)
        self.save()

    def move(self, a, to):
        """Put artifact `a` at position `to` (counted after it is taken out of the list)."""
        self.items.remove(a)
        self.items.insert(max(0, min(to, len(self.items))), a)
        self.save()

# ----------------------------------------------------------------- runner --

class RunnerPage(Adw.NavigationPage):
    def __init__(self, lib, art):
        super().__init__(title=art["name"])
        self.lib, self.art = lib, art
        self.count = 0
        self.errors = 0
        # A fake, never-resolved origin gives each artifact its own storage.
        self.base = "https://artifact-%s.invalid/" % art["id"]

        ucm = WebKit.UserContentManager()
        ucm.register_script_message_handler("deck", None)
        ucm.connect("script-message-received::deck", self.on_message)
        ucm.add_script(WebKit.UserScript.new(
            sandbox.BRIDGE_JS, WebKit.UserContentInjectedFrames.ALL_FRAMES,
            WebKit.UserScriptInjectionTime.START, None, None))

        # One private storage folder per artifact, so its saved data survives
        # between runs and never mixes with another artifact's.
        data_dir = os.path.join(STATE_DIR, art["id"], "data")
        cache_dir = os.path.join(STATE_DIR, art["id"], "cache")
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(cache_dir, exist_ok=True)
        session = WebKit.NetworkSession.new(data_dir, cache_dir)
        self.web = WebKit.WebView(user_content_manager=ucm, network_session=session)
        settings = self.web.get_settings()
        for prop, val in (("enable-media-stream", False), ("enable-webrtc", False),
                          ("javascript-can-open-windows-automatically", False),
                          ("allow-modal-dialogs", False),
                          ("allow-file-access-from-file-urls", False),
                          ("allow-universal-access-from-file-urls", False)):
            try:
                settings.set_property(prop, val)
            except TypeError:
                pass
        self.web.connect("permission-request", self.on_permission)
        self.web.connect("decide-policy", self.on_policy)

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=art["name"],
                                                subtitle="Sandboxed \u00b7 network blocked"))
        restart = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Restart")
        restart.connect("clicked", lambda *_: self.run())
        reset = Gtk.Button(icon_name="edit-clear-all-symbolic", tooltip_text="Reset saved data")
        reset.connect("clicked", self.on_reset)
        self.console_btn = Gtk.ToggleButton(icon_name="utilities-terminal-symbolic",
                                            tooltip_text="Console")
        header.pack_end(self.console_btn)
        header.pack_end(reset)
        header.pack_end(restart)

        self.banner = Adw.Banner(title="This artifact tries to use the Claude API, which "
                                       "isn't available here, so part of it may not work.",
                                 button_label="Dismiss")
        self.banner.connect("button-clicked", lambda *_: self.banner.set_revealed(False))

        self.buf = Gtk.TextBuffer()
        view = Gtk.TextView(buffer=self.buf, editable=False, cursor_visible=False,
                            monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                            left_margin=8, right_margin=8, top_margin=6, bottom_margin=6)
        self.scroller = Gtk.ScrolledWindow(min_content_height=160, child=view)
        revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
                                child=self.scroller)
        self.console_btn.bind_property("active", revealer, "reveal-child")

        self.libs_page = Adw.StatusPage(
            icon_name="folder-download-symbolic", title="One-time download needed",
            description="React artifacts need a few JavaScript libraries (about 30 MB). "
                        "They are downloaded once, checked against the npm registry's "
                        "checksums, and then everything runs offline.")
        self.dl_btn = Gtk.Button(label="Download libraries", halign=Gtk.Align.CENTER)
        self.dl_btn.add_css_class("suggested-action")
        self.dl_btn.add_css_class("pill")
        self.dl_btn.connect("clicked", self.on_download)
        self.libs_page.set_child(self.dl_btn)

        self.stack = Gtk.Stack(vexpand=True)
        self.stack.add_named(self.web, "web")
        self.stack.add_named(self.libs_page, "libs")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self.stack)
        box.append(Gtk.Separator())
        box.append(revealer)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.add_top_bar(self.banner)
        toolbar.set_content(box)
        self.set_child(toolbar)

        self.connect("hidden", self.on_hidden)
        self.run()

    # -- running --

    def run(self):
        self.buf.set_text("")
        self.count = self.errors = 0
        self.banner.set_revealed(False)
        code = self.lib.read_code(self.art)
        needed = sandbox.needed_files(self.art["type"], code)
        if vendor.missing_files(VENDOR_DIR, needed):
            self.stack.set_visible_child_name("libs")
            return
        self.stack.set_visible_child_name("web")
        self.web.load_html(sandbox.build_srcdoc(self.art["type"], code, VENDOR_DIR), self.base)

    def on_download(self, _btn):
        self.dl_btn.set_sensitive(False)
        self.libs_page.set_description("Starting download\u2026")

        def progress(i, total, name):
            text = ("Downloading %s (%d of %d)\u2026" % (name, i + 1, total)) if name \
                else "Finishing\u2026"
            GLib.idle_add(self.libs_page.set_description, text)

        def work():
            try:
                vendor.download_all(VENDOR_DIR, progress)
                GLib.idle_add(self.download_done, None)
            except Exception as e:  # network or checksum problems
                GLib.idle_add(self.download_done, str(e))

        threading.Thread(target=work, daemon=True).start()

    def download_done(self, error):
        self.dl_btn.set_sensitive(True)
        if error:
            self.libs_page.set_description("Download failed: %s. Check your connection "
                                           "and try again." % error)
        else:
            self.run()
        return False

    # -- reset saved data --

    def on_reset(self, _btn):
        dlg = Adw.AlertDialog(heading="Reset saved data?",
                              body="This clears everything this artifact has saved, such as "
                                   "scores, settings and entries.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("reset", "Reset")
        dlg.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_close_response("cancel")
        dlg.connect("response", lambda _d, r: self.do_reset() if r == "reset" else None)
        dlg.present(self)

    def do_reset(self):
        manager = self.web.get_network_session().get_website_data_manager()

        def done(mgr, res):
            try:
                mgr.clear_finish(res)
            except GLib.Error as e:
                self.log("error", "Could not reset saved data: %s" % e.message)
                return
            self.run()
        manager.clear(WebKit.WebsiteDataTypes.ALL, 0, None, done)

    # -- sandbox policy --

    def on_permission(self, web, request):
        request.deny()
        self.log("warn", "Denied a permission request")
        return True

    def on_policy(self, web, decision, dtype):
        # Block ALL resource loads (fetch, XHR, images, fonts, etc.) to external origins
        # This is defense-in-depth beyond CSP connect-src 'none'
        if dtype == WebKit.PolicyDecisionType.RESPONSE:
            uri = decision.get_response().get_uri() or ""
            if not (uri.startswith(("about:", "data:", "blob:")) or uri.startswith(self.base)):
                decision.ignore()
                self.log("warn", "Blocked resource: " + uri[:200])
                return True
        # Block navigation to external sites
        if dtype in (WebKit.PolicyDecisionType.NAVIGATION_ACTION,
                     WebKit.PolicyDecisionType.NEW_WINDOW_ACTION):
            uri = decision.get_navigation_action().get_request().get_uri() or ""
            if not (uri.startswith(("about:", "data:")) or uri.startswith(self.base)):
                decision.ignore()
                self.log("warn", "Blocked navigation to " + uri[:200])
                return True
        return False

    # -- console --

    def on_message(self, ucm, value):
        try:
            data = json.loads(value.to_string())
        except (ValueError, TypeError):
            return
        if not isinstance(data, dict):
            return
        level = str(data.get("l", "log"))[:10]
        if level == "api":
            self.banner.set_revealed(True)
            return
        self.log(level, str(data.get("m", ""))[:2000])

    def log(self, level, msg):
        if self.count > 2000:
            return
        self.count += 1
        if level == "error":
            self.errors += 1
        self.buf.insert(self.buf.get_end_iter(), "[%s] %s\n" % (level, msg))
        self.console_btn.set_tooltip_text(
            "Console (%d lines, %d errors)" % (self.count, self.errors))
        GLib.idle_add(self.scroll_end)

    def scroll_end(self):
        adj = self.scroller.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return False

    def on_hidden(self, *_):
        try:
            self.web.terminate_web_process()
        except Exception:
            pass

# ----------------------------------------------------------------- window --

class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, default_width=1000, default_height=700,
                         title="Artifact Deck")
        self.lib = Library()
        self.settings = Settings()
        self.side_rows = []

        css = Gtk.CssProvider()
        if hasattr(css, "load_from_string"):
            css.load_from_string(CSS)
        else:
            css.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.setup_theme()

        self.toasts = Adw.ToastOverlay()
        self.nav = Adw.NavigationView()
        self.toasts.set_child(self.nav)
        self.set_content(self.toasts)

        add_btn = Gtk.Button(icon_name="document-open-symbolic", tooltip_text="Add from file")
        add_btn.connect("clicked", self.on_add_file)
        paste_btn = Gtk.Button(icon_name="edit-paste-symbolic", tooltip_text="Add from clipboard")
        paste_btn.connect("clicked", self.on_add_clipboard)
        self.search_btn = Gtk.ToggleButton(icon_name="system-search-symbolic",
                                           tooltip_text="Search")
        self.fav_btn = Gtk.ToggleButton(icon_name="starred-symbolic",
                                        tooltip_text="Favorites only")
        self.fav_btn.connect("toggled", lambda *_: self.flow.invalidate_filter())

        self.sidebar_btn = Gtk.ToggleButton(icon_name="sidebar-show-symbolic",
                                            tooltip_text="Show sidebar", active=True)
        theme_btn = Gtk.MenuButton(icon_name="preferences-desktop-appearance-symbolic",
                                   tooltip_text="Appearance", menu_model=self.build_theme_menu())

        header = Adw.HeaderBar()
        header.pack_start(self.sidebar_btn)
        header.pack_start(add_btn)
        header.pack_start(paste_btn)
        header.pack_end(theme_btn)
        header.pack_end(self.search_btn)
        header.pack_end(self.fav_btn)

        self.entry = Gtk.SearchEntry(hexpand=True)
        self.entry.connect("search-changed", lambda *_: self.flow.invalidate_filter())
        self.search_bar = Gtk.SearchBar(child=self.entry)
        self.search_bar.connect_entry(self.entry)
        self.search_bar.set_key_capture_widget(self)
        self.search_btn.bind_property("active", self.search_bar, "search-mode-enabled",
                                      GObject.BindingFlags.BIDIRECTIONAL)

        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                min_children_per_line=1, max_children_per_line=4,
                                column_spacing=12, row_spacing=12, valign=Gtk.Align.START,
                                margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        self.flow.set_filter_func(self.filter_func)
        scroller = Gtk.ScrolledWindow(child=self.flow, vexpand=True)

        empty = Adw.StatusPage(icon_name="applications-science-symbolic",
                               title="No artifacts yet",
                               description="Drop an HTML, JavaScript or React file here, "
                                           "or paste code from the clipboard.")
        self.stack = Gtk.Stack()
        self.stack.add_named(empty, "empty")
        self.stack.add_named(scroller, "grid")

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.add_top_bar(self.search_bar)
        toolbar.set_content(self.stack)

        # -- sidebar: every artifact, drag to reorder, bin to delete --
        self.side_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.side_list.add_css_class("navigation-sidebar")
        self.side_list.set_placeholder(Gtk.Label(label="No artifacts yet", margin_top=24,
                                                 css_classes=["dim-label"]))
        self.side_list.connect("row-activated", self.on_side_activated)
        side_scroll = Gtk.ScrolledWindow(child=self.side_list, vexpand=True,
                                         hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.side_title = Adw.WindowTitle(title="Artifacts", subtitle="")
        side_header = Adw.HeaderBar(show_end_title_buttons=False)
        side_header.set_title_widget(self.side_title)
        sidebar = Adw.ToolbarView()
        sidebar.add_top_bar(side_header)
        sidebar.set_content(side_scroll)

        self.split = Adw.OverlaySplitView(sidebar=sidebar, content=toolbar,
                                          min_sidebar_width=220, max_sidebar_width=320,
                                          sidebar_width_fraction=0.28, show_sidebar=True)
        self.sidebar_btn.bind_property("active", self.split, "show-sidebar",
                                       GObject.BindingFlags.BIDIRECTIONAL
                                       | GObject.BindingFlags.SYNC_CREATE)
        # On narrow windows the sidebar becomes a slide-over panel.
        self.set_size_request(360, 400)
        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 640sp"))
        bp.add_setter(self.split, "collapsed", True)
        bp.add_setter(self.split, "show-sidebar", False)
        self.add_breakpoint(bp)

        self.nav.add(Adw.NavigationPage(title="Artifact Deck", child=self.split))

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self.on_drop)
        self.add_controller(drop)

        self.refresh()

    # -- theme --

    def setup_theme(self):
        scheme = self.settings.get("theme", "system")
        if scheme not in SCHEMES:
            scheme = "system"
        action = Gio.SimpleAction.new_stateful(
            "theme", GLib.VariantType.new("s"), GLib.Variant.new_string(scheme))
        action.connect("change-state", self.on_theme)
        self.add_action(action)
        Adw.StyleManager.get_default().set_color_scheme(SCHEMES[scheme])

    def on_theme(self, action, value):
        scheme = value.get_string()
        if scheme not in SCHEMES:
            return
        action.set_state(value)
        Adw.StyleManager.get_default().set_color_scheme(SCHEMES[scheme])
        self.settings.set("theme", scheme)

    def build_theme_menu(self):
        section = Gio.Menu()
        section.append("Follow system", "win.theme::system")
        section.append("Light", "win.theme::light")
        section.append("Dark", "win.theme::dark")
        menu = Gio.Menu()
        menu.append_section("Appearance", section)
        return menu

    # -- sidebar --

    def build_sidebar(self):
        self.side_list.remove_all()
        self.side_rows = []
        for a in self.lib.items:
            row = self.make_side_row(a)
            self.side_rows.append(row)
            self.side_list.append(row)
        n = len(self.lib.items)
        self.side_title.set_subtitle("%d artifact%s" % (n, "" if n == 1 else "s") if n else "")

    def make_side_row(self, a):
        row = Gtk.ListBoxRow(activatable=True)
        row.art = a

        handle = Gtk.Image(icon_name="list-drag-handle-symbolic", tooltip_text="Drag to reorder")
        handle.add_css_class("side-handle")
        handle.set_cursor_from_name("grab")
        dot = Gtk.Label(label="\u25cf")
        dot.add_css_class("src-" + a["source"])
        name = Gtk.Label(label=a["name"], xalign=0, ellipsize=Pango.EllipsizeMode.END)
        sub = Gtk.Label(label="%s \u00b7 %s" % (SOURCES.get(a["source"], "Other"),
                                                TYPES[a["type"]]), xalign=0)
        sub.add_css_class("dim-label")
        sub.add_css_class("caption")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        text.append(name)
        text.append(sub)
        trash = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                           tooltip_text="Delete")
        trash.add_css_class("flat")
        trash.connect("clicked", self.on_delete, a)

        box = Gtk.Box(spacing=8, margin_top=4, margin_bottom=4)
        for w in (handle, dot, text, trash):
            box.append(w)
        row.set_child(box)

        # Drag by the handle; every row accepts drops.
        src = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        src.connect("prepare", lambda *_: Gdk.ContentProvider.new_for_value(
            GObject.Value(GObject.TYPE_STRING, a["id"])))
        src.connect("drag-begin", lambda s, _d: s.set_icon(Gtk.WidgetPaintable.new(row), 12, 20))
        handle.add_controller(src)

        tgt = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        tgt.connect("motion", self.on_side_motion, row)
        tgt.connect("leave", lambda *_: self.clear_drop_marks())
        tgt.connect("drop", self.on_side_drop, row)
        row.add_controller(tgt)

        # Keyboard: Alt+Up / Alt+Down moves the focused row.
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_side_key, a)
        row.add_controller(keys)
        return row

    def on_side_activated(self, _list, row):
        if self.split.get_collapsed():
            self.split.set_show_sidebar(False)
        self.on_run(None, row.art)

    def clear_drop_marks(self):
        for r in self.side_rows:
            r.remove_css_class("drop-before")
            r.remove_css_class("drop-after")

    def on_side_motion(self, _tgt, _x, y, row):
        self.clear_drop_marks()
        row.add_css_class("drop-after" if y > row.get_height() / 2 else "drop-before")
        return Gdk.DragAction.MOVE

    def on_side_drop(self, _tgt, value, _x, y, row):
        self.clear_drop_marks()
        src = next((a for a in self.lib.items if a["id"] == value), None)
        if src is None or src is row.art:
            return False
        dst = self.lib.items.index(row.art) + (1 if y > row.get_height() / 2 else 0)
        if self.lib.items.index(src) < dst:
            dst -= 1
        self.lib.move(src, dst)
        GLib.idle_add(self.after_move, src)     # rebuild once the drag has finished
        return True

    def on_side_key(self, _ctrl, keyval, _code, state, a):
        if not state & Gdk.ModifierType.ALT_MASK or keyval not in (Gdk.KEY_Up, Gdk.KEY_Down):
            return False
        idx = self.lib.items.index(a)
        to = idx - 1 if keyval == Gdk.KEY_Up else idx + 1
        if 0 <= to < len(self.lib.items):
            self.lib.move(a, to)
            self.after_move(a)
        return True

    def after_move(self, a):
        self.refresh()
        for r in self.side_rows:
            if r.art is a:
                r.grab_focus()
        return False

    # -- library view --

    def filter_func(self, child):
        a = child.get_child().art
        if self.fav_btn.get_active() and not a["fav"]:
            return False
        q = self.entry.get_text().strip().lower()
        if q:
            hay = " ".join([a["name"], a["source"], a["type"]] + a.get("tags", [])).lower()
            return q in hay
        return True

    def refresh(self):
        self.flow.remove_all()
        for a in self.lib.items:
            self.flow.append(self.make_card(a))
        self.stack.set_visible_child_name("grid" if self.lib.items else "empty")
        self.build_sidebar()

    def make_card(self, a):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.add_css_class("card")
        card.add_css_class("deck-card")
        card.art = a

        title = Gtk.Label(label=a["name"], xalign=0, hexpand=True,
                          ellipsize=Pango.EllipsizeMode.END)
        title.add_css_class("title-4")
        star = Gtk.ToggleButton(icon_name="starred-symbolic", active=a["fav"],
                                valign=Gtk.Align.CENTER, tooltip_text="Favorite")
        star.add_css_class("flat")
        star.connect("toggled", self.on_fav, a)
        trash = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                           tooltip_text="Delete")
        trash.add_css_class("flat")
        trash.connect("clicked", self.on_delete, a)
        top = Gtk.Box(spacing=4)
        for w in (title, star, trash):
            top.append(w)

        dot = Gtk.Label(label="\u25cf")
        dot.add_css_class("src-" + a["source"])
        sub = Gtk.Label(label="%s \u00b7 %s" % (SOURCES.get(a["source"], "Other"),
                                                TYPES[a["type"]]), xalign=0)
        sub.add_css_class("dim-label")
        sub.add_css_class("caption")
        meta = Gtk.Box(spacing=6)
        meta.append(dot)
        meta.append(sub)

        run = Gtk.Button(label="Run", halign=Gtk.Align.START)
        run.add_css_class("suggested-action")
        run.connect("clicked", self.on_run, a)

        card.append(top)
        card.append(meta)
        if a.get("tags"):
            tags = Gtk.Label(label=", ".join(a["tags"]), xalign=0, wrap=True)
            tags.add_css_class("dim-label")
            tags.add_css_class("caption")
            card.append(tags)
        card.append(run)
        return card

    def on_run(self, _btn, a):
        a["runs"] += 1
        a["last_run"] = int(time.time())
        self.lib.save()
        self.nav.push(RunnerPage(self.lib, a))

    def on_fav(self, btn, a):
        a["fav"] = btn.get_active()
        self.lib.save()
        self.flow.invalidate_filter()

    def on_delete(self, _btn, a):
        removed = self.lib.remove(a)
        self.refresh()
        toast = Adw.Toast(title="Deleted \u201c%s\u201d" % a["name"])
        toast.set_button_label("Undo")

        def undo(*_):
            self.lib.restore(*removed)
            self.refresh()
        toast.connect("button-clicked", undo)
        self.toasts.add_toast(toast)

    # -- adding --

    def on_add_file(self, *_):
        dlg = Gtk.FileDialog(title="Add artifact")
        flt = Gtk.FileFilter()
        flt.set_name("Artifacts")
        for ext in ACCEPTED:
            flt.add_pattern("*" + ext)
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(flt)
        dlg.set_filters(store)
        dlg.set_default_filter(flt)
        dlg.open(self, None, self.file_chosen)

    def file_chosen(self, dlg, res):
        try:
            self.load_file(dlg.open_finish(res))
        except GLib.Error:
            return

    def on_drop(self, _target, value, _x, _y):
        files = value.get_files()
        if not files:
            return False
        self.load_file(files[0])
        return True

    def load_file(self, f):
        name = f.get_basename() or ""
        if not name.lower().endswith(ACCEPTED):
            self.toasts.add_toast(Adw.Toast(title="Only HTML, JavaScript and React files "
                                                  "can be added"))
            return
        try:
            ok, data, _etag = f.load_contents(None)
        except GLib.Error:
            self.toasts.add_toast(Adw.Toast(title="Could not read that file"))
            return
        if len(data) > MAX_BYTES:
            self.toasts.add_toast(Adw.Toast(title="File is larger than 5 MB"))
            return
        self.confirm_add(data.decode("utf-8", "replace"), os.path.splitext(name)[0], name)

    def on_add_clipboard(self, *_):
        clip = Gdk.Display.get_default().get_clipboard()

        def done(cb, res):
            try:
                text = cb.read_text_finish(res)
            except GLib.Error:
                text = None
            if text and text.strip():
                self.confirm_add(text, "", "")
            else:
                self.toasts.add_toast(Adw.Toast(title="Clipboard has no text"))
        clip.read_text_async(None, done)

    def confirm_add(self, code, default_name, filename):
        if not default_name:
            m = re.search(r"<title>([^<]{1,80})</title>", code, re.I)
            default_name = m.group(1).strip() if m else ""
        type_ = sandbox.detect_type(code, filename)

        name_row = Adw.EntryRow(title="Name")
        name_row.set_text(default_name)
        src_row = Adw.ComboRow(title="Made with")
        src_row.set_model(Gtk.StringList.new(list(SOURCES.values())))
        tags_row = Adw.EntryRow(title="Tags (comma separated)")
        rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        rows.add_css_class("boxed-list")
        for r in (name_row, src_row, tags_row):
            rows.append(r)

        dlg = Adw.AlertDialog(heading="Add artifact", body="Detected type: " + TYPES[type_])
        dlg.set_extra_child(rows)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("add", "Add")
        dlg.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("add")
        dlg.set_close_response("cancel")

        def on_response(_d, response):
            if response != "add":
                return
            source = list(SOURCES)[src_row.get_selected()]
            tags = [t.strip() for t in tags_row.get_text().split(",") if t.strip()]
            self.lib.add(name_row.get_text().strip(), source, type_, code, tags)
            self.refresh()
        dlg.connect("response", on_response)
        dlg.present(self)

class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        win = self.props.active_window or MainWindow(self)
        win.present()

if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
