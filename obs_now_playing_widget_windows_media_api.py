"""
Crypto90's OBS Now Playing Widget (Windows Media API)
Broadcast-ready Windows GSMTC Media Player Overlay for OBS Studio.

Author: Crypto90
Repository: https://github.com/Crypto90/obs-now-playing-widget-windows-api
License: MIT License
"""

import os
import sys
import time
import math
import json
import base64
import socket
import asyncio
import threading
import webbrowser
import subprocess
import datetime
from PIL import Image, ImageTk, ImageDraw
import io

import tkinter as tk
from tkinter import ttk, messagebox
from flask import Flask, jsonify, render_template, redirect, url_for, request

# Check platform and import WinRT media controls
IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes
    try:
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as MediaManager
        )
        from winsdk.windows.storage.streams import DataReader
    except ImportError:
        MediaManager = None
        DataReader = None
else:
    MediaManager = None
    DataReader = None

CURRENT_VERSION = "v1.1.0"
SETTINGS_FILENAME = "now_playing_settings.json"


def enable_high_dpi():
    """Enable Per-Monitor V2 DPI awareness on Windows."""
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def get_exe_dir():
    """Get root directory of the application."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_data_dir():
    """
    Returns a reliable writable directory for config storage.
    Uses executable directory if writable (portable mode),
    otherwise falls back to %LOCALAPPDATA%\Crypto90s_OBS_NowPlayingWidget.
    """
    base_dir = get_exe_dir()
    test_path = os.path.join(base_dir, ".widget_write_test")
    try:
        with open(test_path, "w") as f:
            f.write("ok")
        os.remove(test_path)
        return base_dir
    except (PermissionError, OSError):
        appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        target_dir = os.path.join(appdata, "Crypto90s_OBS_NowPlayingWidget")
        os.makedirs(target_dir, exist_ok=True)
        return target_dir


def get_settings_path():
    return os.path.join(get_data_dir(), SETTINGS_FILENAME)


def load_settings():
    path = get_settings_path()
    legacy_path = os.path.join(get_exe_dir(), SETTINGS_FILENAME)
    target = path if os.path.exists(path) else (legacy_path if os.path.exists(legacy_path) else path)

    defaults = {
        "version": CURRENT_VERSION,
        "layout": "horizontal",
        "port": 5000,
        "locked_app": None,
        "autohide": True
    }

    if os.path.exists(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
                defaults.update(data)
        except Exception as e:
            print(f"Error reading settings: {e}")

    return defaults


def save_settings_data(settings_data):
    path = get_settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings_data, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving settings: {e}")
        return False


def get_local_ip():
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        if not local_ip.startswith("127."):
            return local_ip
    except Exception:
        pass
    return "127.0.0.1"


def find_available_port(preferred_port=5000, max_attempts=20):
    """Find an available TCP port starting from preferred_port."""
    for p in range(preferred_port, preferred_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(('0.0.0.0', p))
                return p
            except OSError:
                continue
    return preferred_port


# Global State
settings = load_settings()
server_port = find_available_port(settings.get("port", 5000))
template_name = settings.get("layout", "horizontal")
locked_app_id = settings.get("locked_app")

media_info = {
    'title': 'No Media Playing',
    'artist': 'Waiting for audio playback...',
    'position': 0,
    'duration': 0,
    'cover': '',
    'app_id': 'Unknown',
    'status': 'Stopped'
}

STATUS_MAP = {
    0: "Closed",
    1: "Stopped",
    4: "Playing",
    5: "Paused"
}

cached_cover = ''
cached_song_id = ''
last_update_time = 0
last_position = 0
last_known_position = 0

# Template directory resolution
def resolve_template_dir():
    exe_dir = get_exe_dir()
    # Check PyInstaller bundled temp dir
    if getattr(sys, '_MEIPASS', False):
        t_path = os.path.join(sys._MEIPASS, 'templates')
        if os.path.exists(t_path):
            return t_path
    # Check current directory
    local_templates = os.path.join(exe_dir, 'templates')
    if os.path.exists(local_templates):
        return local_templates
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')

template_folder = resolve_template_dir()

# Flask Web Server
app = Flask(__name__, template_folder=template_folder)

# Suppress Flask dev server request logging in console
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)


@app.route('/')
def index():
    layout = request.args.get('layout', template_name)
    if layout not in ('horizontal', 'vertical', 'compact'):
        layout = template_name
    return render_template(f'{layout}.html', media=media_info)


@app.route('/horizontal')
def view_horizontal():
    return render_template('horizontal.html', media=media_info)


@app.route('/vertical')
def view_vertical():
    return render_template('vertical.html', media=media_info)


@app.route('/compact')
def view_compact():
    return render_template('compact.html', media=media_info)


@app.route('/media')
def media_endpoint():
    return jsonify(media_info)


@app.route('/api/settings', methods=['GET', 'POST'])
def settings_endpoint():
    global template_name, locked_app_id
    if request.method == 'POST':
        data = request.get_json() or {}
        if 'layout' in data:
            template_name = data['layout']
            settings['layout'] = template_name
        if 'locked_app' in data:
            locked_app_id = data['locked_app']
            settings['locked_app'] = locked_app_id
        save_settings_data(settings)
    return jsonify({
        "layout": template_name,
        "locked_app": locked_app_id,
        "port": server_port
    })


@app.route('/reload')
def reload_endpoint():
    return jsonify({"status": "ok", "layout": template_name})


# Media Extraction Routines
async def extract_cover(thumbnail):
    if not thumbnail or not IS_WINDOWS or DataReader is None:
        return ""
    try:
        stream = await thumbnail.open_read_async()
        reader = DataReader(stream)
        await reader.load_async(stream.size)
        data = bytes(reader.read_buffer(stream.size))
        return f"data:image/png;base64,{base64.b64encode(data).decode('utf-8')}"
    except Exception as e:
        return ""


async def get_media_info():
    global last_update_time, last_position, last_known_position, cached_cover, cached_song_id, locked_app_id
    if not IS_WINDOWS or MediaManager is None:
        return None

    try:
        session_manager = await MediaManager.request_async()
        current_session = session_manager.get_current_session()

        if not current_session:
            return None

        info = await current_session.try_get_media_properties_async()
        playback_info = current_session.get_playback_info()
        timeline = current_session.get_timeline_properties()
        app_id = current_session.source_app_user_model_id or "Unknown"

        # If locked to a specific application, enforce filter
        clean_app = app_id.split("!")[-1] if "!" in app_id else app_id
        if locked_app_id and clean_app != locked_app_id:
            return None

        title = info.title or "Unknown Title"
        artist = info.artist or "Unknown Artist"
        current_song_id = f"{title}-{artist}"
        playback_status = playback_info.playback_status

        current_time = time.time()
        current_timeline_position = int(timeline.position.total_seconds()) if timeline else 0

        if (current_song_id != cached_song_id or abs(current_timeline_position - last_known_position) > 1):
            last_position = current_timeline_position
            last_update_time = current_time

        if playback_status == 4:  # Playing
            elapsed = current_time - last_update_time
            position = last_position + elapsed
        else:
            position = current_timeline_position

        last_update_time = current_time
        last_position = position
        last_known_position = current_timeline_position

        duration = timeline.end_time.total_seconds() if timeline else 0

        # Reload cover if song changed
        if current_song_id != cached_song_id:
            cached_cover = await extract_cover(info.thumbnail) if info.thumbnail else ""
            cached_song_id = current_song_id

        return {
            'title': title,
            'artist': artist,
            'position': position,
            'duration': duration,
            'cover': cached_cover,
            'app_id': clean_app,
            'status': STATUS_MAP.get(playback_status, "Stopped")
        }
    except Exception:
        return None


async def media_worker_loop():
    global media_info
    while True:
        try:
            new_info = await get_media_info()
            if new_info:
                media_info.update(new_info)
            else:
                if not locked_app_id:
                    media_info['status'] = 'Stopped'
        except Exception:
            pass
        await asyncio.sleep(0.8)


def start_media_service():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(media_worker_loop())


# Modern Tkinter Desktop Controller
class OBSWidgetApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Crypto90's OBS Now Playing Widget")
        self.root.geometry("620x520")
        self.root.minsize(560, 460)

        # Windows 11 Dark Slate Palette
        self.BG_MAIN = "#121418"
        self.BG_CARD = "#1a1d24"
        self.BG_HOVER = "#242832"
        self.BORDER_COLOR = "#2a303c"
        self.ACCENT_CYAN = "#00d2ff"
        self.ACCENT_GREEN = "#10b981"
        self.ACCENT_AMBER = "#f59e0b"
        self.ACCENT_RED = "#ef4444"
        self.TEXT_PRIMARY = "#f1f5f9"
        self.TEXT_MUTED = "#94a3b8"

        self.root.configure(bg=self.BG_MAIN)
        self.local_ip = get_local_ip()

        self._configure_styles()
        self._build_header_ui()
        self._build_url_bar_ui()
        self._build_player_preview_ui()
        self._build_controls_ui()
        self._build_console_ui()
        self._build_status_bar_ui()

        # Start periodic GUI updates
        self.update_gui_preview()

        self.log(f"Crypto90's OBS Now Playing Widget {CURRENT_VERSION} initialized.", "info")
        self.log(f"HTTP Server active on port {server_port}", "success")
        self.log(f"Local URL: http://127.0.0.1:{server_port}", "info")
        if self.local_ip != "127.0.0.1":
            self.log(f"LAN URL: http://{self.local_ip}:{server_port}", "info")

    def _configure_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

    def _build_header_ui(self):
        font_family = "Segoe UI" if IS_WINDOWS else "Helvetica"
        header = tk.Frame(self.root, bg=self.BG_CARD, height=44)
        header.pack(fill=tk.X, padx=0, pady=0)

        # Title
        brand_label = tk.Label(
            header,
            text="🎵  Crypto90's OBS Now Playing Widget",
            font=(font_family, 11, "bold"),
            fg=self.TEXT_PRIMARY,
            bg=self.BG_CARD
        )
        brand_label.pack(side=tk.LEFT, padx=14, pady=8)

        # Version Badge
        version_badge = tk.Label(
            header,
            text=CURRENT_VERSION,
            font=(font_family, 8, "bold"),
            fg=self.ACCENT_CYAN,
            bg="#222834",
            padx=6,
            pady=1
        )
        version_badge.pack(side=tk.LEFT, padx=4, pady=8)

        # Port Status Badge
        port_badge = tk.Label(
            header,
            text=f"🟢 Port: {server_port}",
            font=(font_family, 8, "bold"),
            fg=self.ACCENT_GREEN,
            bg="#132e27",
            padx=8,
            pady=2
        )
        port_badge.pack(side=tk.RIGHT, padx=14, pady=8)

    def _build_url_bar_ui(self):
        font_family = "Segoe UI" if IS_WINDOWS else "Helvetica"
        url_frame = tk.Frame(self.root, bg=self.BG_MAIN)
        url_frame.pack(fill=tk.X, padx=14, pady=(10, 4))

        tk.Label(
            url_frame,
            text="OBS Browser Source URL:",
            font=(font_family, 9, "bold"),
            fg=self.TEXT_PRIMARY,
            bg=self.BG_MAIN
        ).pack(anchor="w", pady=(0, 4))

        box = tk.Frame(url_frame, bg=self.BG_CARD, bd=1, relief=tk.FLAT)
        box.pack(fill=tk.X)

        # Localhost URL entry & buttons
        local_url = f"http://127.0.0.1:{server_port}"
        self.url_entry = tk.Entry(
            box,
            bg=self.BG_CARD,
            fg=self.ACCENT_CYAN,
            font=(font_family, 9, "bold"),
            relief=tk.FLAT,
            bd=0
        )
        self.url_entry.insert(0, local_url)
        self.url_entry.configure(state="readonly")
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8, ipady=4)

        self.copy_btn = tk.Button(
            box,
            text="📋 Copy URL",
            command=lambda: self.copy_url(local_url, self.copy_btn),
            bg="#242832",
            fg=self.TEXT_PRIMARY,
            activebackground="#333a48",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            font=(font_family, 8, "bold"),
            cursor="hand2",
            padx=10,
            pady=2
        )
        self.copy_btn.pack(side=tk.LEFT, padx=4, pady=3)

        open_btn = tk.Button(
            box,
            text="🌐 Open",
            command=lambda: webbrowser.open(local_url),
            bg="#0284c7",
            fg="#ffffff",
            activebackground="#0369a1",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            font=(font_family, 8, "bold"),
            cursor="hand2",
            padx=8,
            pady=2
        )
        open_btn.pack(side=tk.LEFT, padx=(0, 6), pady=3)

    def _build_player_preview_ui(self):
        font_family = "Segoe UI" if IS_WINDOWS else "Helvetica"
        preview_container = tk.Frame(self.root, bg=self.BG_CARD, bd=1, relief=tk.FLAT)
        preview_container.pack(fill=tk.X, padx=14, pady=8)

        # Left: Cover Art Thumbnail
        self.cover_label = tk.Label(preview_container, bg="#0f1115", width=70, height=70)
        self.cover_label.pack(side=tk.LEFT, padx=12, pady=10)

        # Right: Info & Track Controls
        info_frame = tk.Frame(preview_container, bg=self.BG_CARD)
        info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 12), pady=10)

        top_row = tk.Frame(info_frame, bg=self.BG_CARD)
        top_row.pack(fill=tk.X)

        self.preview_title = tk.Label(
            top_row,
            text="No Media Playing",
            font=(font_family, 11, "bold"),
            fg=self.TEXT_PRIMARY,
            bg=self.BG_CARD,
            anchor="w"
        )
        self.preview_title.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.status_badge = tk.Label(
            top_row,
            text="⏹ Stopped",
            font=(font_family, 8, "bold"),
            fg=self.TEXT_MUTED,
            bg="#20242d",
            padx=6,
            pady=1
        )
        self.status_badge.pack(side=tk.RIGHT)

        self.preview_artist = tk.Label(
            info_frame,
            text="Waiting for active Windows audio session...",
            font=(font_family, 9),
            fg=self.TEXT_MUTED,
            bg=self.BG_CARD,
            anchor="w"
        )
        self.preview_artist.pack(fill=tk.X, pady=(2, 6))

        # Progress bar
        self.progress_canvas = tk.Canvas(info_frame, height=5, bg="#20242d", highlightthickness=0)
        self.progress_canvas.pack(fill=tk.X)

        time_row = tk.Frame(info_frame, bg=self.BG_CARD)
        time_row.pack(fill=tk.X, pady=(3, 0))

        self.time_label_start = tk.Label(time_row, text="0:00", font=(font_family, 8), fg=self.TEXT_MUTED, bg=self.BG_CARD)
        self.time_label_start.pack(side=tk.LEFT)

        self.app_source_label = tk.Label(time_row, text="Source: None", font=(font_family, 8), fg=self.TEXT_MUTED, bg=self.BG_CARD)
        self.app_source_label.pack(side=tk.LEFT, expand=True)

        self.time_label_end = tk.Label(time_row, text="0:00", font=(font_family, 8), fg=self.TEXT_MUTED, bg=self.BG_CARD)
        self.time_label_end.pack(side=tk.RIGHT)

    def _build_controls_ui(self):
        font_family = "Segoe UI" if IS_WINDOWS else "Helvetica"
        controls = tk.Frame(self.root, bg=self.BG_MAIN)
        controls.pack(fill=tk.X, padx=14, pady=2)

        # Layout selector
        l_box = tk.Frame(controls, bg=self.BG_CARD)
        l_box.pack(side=tk.LEFT, padx=(0, 8), pady=2)

        tk.Label(l_box, text="Layout:", font=(font_family, 8, "bold"), fg=self.TEXT_MUTED, bg=self.BG_CARD).pack(side=tk.LEFT, padx=6)

        self.layout_var = tk.StringVar(value=template_name)
        for l_mode, l_name in [("horizontal", "Horizontal"), ("vertical", "Vertical"), ("compact", "Compact")]:
            rb = tk.Radiobutton(
                l_box,
                text=l_name,
                variable=self.layout_var,
                value=l_mode,
                command=self.on_change_layout,
                bg=self.BG_CARD,
                fg=self.TEXT_MUTED,
                selectcolor="#0f766e",
                activebackground=self.BG_CARD,
                activeforeground=self.ACCENT_CYAN,
                font=(font_family, 8),
                indicatoron=0,
                padx=6,
                pady=2,
                relief=tk.FLAT,
                cursor="hand2"
            )
            rb.pack(side=tk.LEFT)

        # App Lock Button
        self.lock_btn = tk.Button(
            controls,
            text="🔒 Lock Current App" if not locked_app_id else f"🔓 Unlock ({locked_app_id})",
            command=self.toggle_app_lock,
            bg="#b45309" if not locked_app_id else self.ACCENT_GREEN,
            fg="#ffffff",
            activebackground="#d97706" if not locked_app_id else "#059669",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            font=(font_family, 8, "bold"),
            cursor="hand2",
            padx=10,
            pady=3
        )
        self.lock_btn.pack(side=tk.LEFT, padx=4)

        # Ko-fi button on right
        kofi_btn = tk.Button(
            controls,
            text="☕ Buy me a Coffee",
            bg="#d97706",
            fg="#ffffff",
            activebackground="#b45309",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            font=(font_family, 8, "bold"),
            cursor="hand2",
            padx=8,
            pady=3,
            command=lambda: webbrowser.open("https://ko-fi.com/crypto90")
        )
        kofi_btn.pack(side=tk.RIGHT)

    def _build_console_ui(self):
        font_family = "Segoe UI" if IS_WINDOWS else "Helvetica"
        console_container = tk.Frame(self.root, bg=self.BG_MAIN)
        console_container.pack(fill=tk.BOTH, expand=True, padx=14, pady=(6, 4))

        bar = tk.Frame(console_container, bg=self.BG_CARD, height=22)
        bar.pack(fill=tk.X)

        tk.Label(
            bar,
            text="ACTIVITY & DIAGNOSTICS CONSOLE",
            font=(font_family, 8, "bold"),
            fg=self.TEXT_MUTED,
            bg=self.BG_CARD
        ).pack(side=tk.LEFT, padx=8, pady=2)

        tk.Button(
            bar,
            text="Clear Console",
            bg=self.BG_CARD,
            fg=self.TEXT_MUTED,
            activebackground=self.BG_CARD,
            activeforeground=self.TEXT_PRIMARY,
            font=(font_family, 7),
            relief=tk.FLAT,
            bd=0,
            command=self.clear_console,
            cursor="hand2"
        ).pack(side=tk.RIGHT, padx=6)

        log_frame = tk.Frame(console_container, bg="#0f1115")
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(
            log_frame,
            height=5,
            state=tk.DISABLED,
            bg="#0f1115",
            fg="#e2e8f0",
            insertbackground="white",
            highlightbackground=self.BORDER_COLOR,
            font=("Consolas" if IS_WINDOWS else "Courier", 9),
            relief=tk.FLAT,
            padx=6,
            pady=4
        )
        sb = tk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview, bg="#0f1115")
        self.log_text.config(yscrollcommand=sb.set)

        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.log_text.tag_config("error", foreground="#f87171")
        self.log_text.tag_config("info", foreground="#38bdf8")
        self.log_text.tag_config("success", foreground="#34d399")
        self.log_text.tag_config("warn", foreground="#fbbf24")
        self.log_text.tag_config("time", foreground="#64748b")

    def _build_status_bar_ui(self):
        font_family = "Segoe UI" if IS_WINDOWS else "Helvetica"
        self.statusbar = tk.Label(
            self.root,
            text=f"Ready • Local: http://127.0.0.1:{server_port} • Templates: {template_name}",
            bg=self.BG_CARD,
            fg=self.TEXT_MUTED,
            font=(font_family, 8),
            anchor=tk.W,
            padx=12,
            pady=2
        )
        self.statusbar.pack(fill=tk.X, side=tk.BOTTOM)

    def log(self, message, level="info"):
        def _write():
            now = datetime.datetime.now().strftime("%H:%M:%S")
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, f"[{now}] ", "time")
            tag = level if level in ("error", "info", "success", "warn") else "info"
            self.log_text.insert(tk.END, message + "\n", tag)
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)

        if threading.current_thread() is threading.main_thread():
            _write()
        else:
            self.root.after_idle(_write)

    def clear_console(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)

    def copy_url(self, url, btn):
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        orig_text = btn.cget("text")
        btn.config(text="✓ Copied!", bg=self.ACCENT_GREEN)
        self.root.after(1500, lambda: btn.config(text=orig_text, bg="#242832"))
        self.log(f"Copied URL '{url}' to clipboard.", "info")

    def on_change_layout(self):
        global template_name
        template_name = self.layout_var.get()
        settings['layout'] = template_name
        save_settings_data(settings)
        self.log(f"Layout changed to '{template_name}'", "info")
        self.statusbar.config(text=f"Ready • Local: http://127.0.0.1:{server_port} • Template: {template_name}")

    def toggle_app_lock(self):
        global locked_app_id
        if locked_app_id:
            locked_app_id = None
            settings['locked_app'] = None
            save_settings_data(settings)
            self.lock_btn.config(text="🔒 Lock Current App", bg="#b45309", activebackground="#d97706")
            self.log("App lock cleared. Auto-detecting all media sources.", "info")
        else:
            app = media_info.get("app_id")
            if app and app != "Unknown":
                locked_app_id = app
                settings['locked_app'] = locked_app_id
                save_settings_data(settings)
                self.lock_btn.config(text=f"🔓 Unlock ({locked_app_id})", bg=self.ACCENT_GREEN, activebackground="#059669")
                self.log(f"Locked to application '{locked_app_id}'", "success")
            else:
                self.log("No active media player detected to lock onto.", "warn")

    def format_time(self, seconds):
        if not seconds or math.isnan(seconds) or seconds < 0:
            return "0:00"
        seconds = int(seconds)
        m = seconds // 60
        s = seconds % 60
        return f"{m}:{s:02d}"

    def update_gui_preview(self):
        title = media_info.get('title') or "No Media Playing"
        artist = media_info.get('artist') or "Waiting for audio..."
        status = media_info.get('status') or "Stopped"
        app_id = media_info.get('app_id') or "None"
        position = float(media_info.get('position') or 0)
        duration = float(media_info.get('duration') or 0)
        cover_b64 = media_info.get('cover') or ""

        self.preview_title.config(text=title)
        self.preview_artist.config(text=artist)
        self.app_source_label.config(text=f"Source: {app_id}")
        self.time_label_start.config(text=self.format_time(position))
        self.time_label_end.config(text=self.format_time(duration))

        # Status Badge
        if status == "Playing":
            self.status_badge.config(text="▶ Playing", fg=self.ACCENT_GREEN, bg="#132e27")
        elif status == "Paused":
            self.status_badge.config(text="⏸ Paused", fg=self.ACCENT_AMBER, bg="#2e2413")
        else:
            self.status_badge.config(text="⏹ Stopped", fg=self.TEXT_MUTED, bg="#20242d")

        # Progress bar
        self.progress_canvas.delete("all")
        if duration > 0:
            pct = min(1.0, max(0.0, position / duration))
            w = self.progress_canvas.winfo_width()
            self.progress_canvas.create_rectangle(0, 0, w * pct, 5, fill=self.ACCENT_CYAN, width=0)

        # Thumbnail
        try:
            if cover_b64.startswith("data:image"):
                raw = base64.b64decode(cover_b64.split(",")[1])
                img = Image.open(io.BytesIO(raw)).resize((64, 64)).convert("RGBA")
            else:
                img = Image.new("RGBA", (64, 64), (18, 20, 24, 255))
            photo = ImageTk.PhotoImage(img)
            self.cover_label.config(image=photo)
            self.cover_label.image = photo
        except Exception:
            pass

        self.root.after(800, self.update_gui_preview)


def run_flask_server():
    try:
        app.run(host='0.0.0.0', port=server_port, debug=False, use_reloader=False)
    except Exception as e:
        print(f"Flask server error on port {server_port}: {e}")


def main():
    enable_high_dpi()

    # Start async WinRT media listener in background thread
    threading.Thread(target=start_media_service, daemon=True).start()

    # Start Flask web server in background thread
    threading.Thread(target=run_flask_server, daemon=True).start()

    # Launch GUI on main thread
    root = tk.Tk()
    app_gui = OBSWidgetApp(root)

    def on_closing():
        os._exit(0)

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
