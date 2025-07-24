import asyncio
import threading
import base64
import time
import tkinter as tk
from flask import Flask, jsonify, render_template, redirect, url_for
from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as MediaManager
from winsdk.windows.storage.streams import DataReader
import os
import sys
import webbrowser
import socket
import shutil
import json

import math

from PIL import Image, ImageTk
from PIL import ImageDraw
import io


cached_cover = ''
cached_song_id = ''



def get_exe_dir():
    #print("DEBUG: get_exe_dir")
    """
    Get the directory where the executable is located (not the temp folder).
    """
    if getattr(sys, '_MEIPASS', False):
        return os.path.dirname(sys.executable)  # Path of the .exe
    return os.path.dirname(os.path.abspath(__file__))


SETTINGS_FILE = os.path.join(get_exe_dir(), "now_playing_settings.json")

def save_settings(locked_app=None, layout=None):
    #print("DEBUG: save_settings")
    settings = load_settings()

    if locked_app is not None:
        settings["locked_app"] = locked_app
    elif "locked_app" in settings:
        del settings["locked_app"]

    if layout is not None:
        settings["layout"] = layout
    elif "layout" not in settings:
        settings["layout"] = "horizontal"  # or some default fallback

    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f)
        print(f"Saved settings: {settings}")
    except Exception as e:
        print(f"Error saving settings: {e}")



def load_settings():
    #print("DEBUG: load_settings")
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading settings: {e}")
    return {}  # Default empty settings

def clear_locked_app():
    save_settings(locked_app=None)





def is_significant_change(new_info, old_info):
    #print("DEBUG: is_significant_change")
    if not old_info:
        return True

    keys_to_check = ['title', 'artist', 'app_id', 'status']
    for key in keys_to_check:
        if new_info.get(key) != old_info.get(key):
            return True
    
    if math.fabs(new_info.get('position', 0) - old_info.get('position', 0)) > 0.5:
        return True
    
    return False




def copy_templates():
    #print("DEBUG: copy_templates")
    """
    Copy the external 'templates' folder to the temp directory if needed.
    """
    exe_dir = get_exe_dir()
    temp_dir = getattr(sys, '_MEIPASS', exe_dir)  # Handle both .exe and script

    src_templates = os.path.join(exe_dir, 'templates')
    dest_templates = os.path.join(temp_dir, 'templates')

    # Copy only if the folder exists and is not already copied
    if os.path.exists(src_templates) and not os.path.exists(dest_templates):
        shutil.copytree(src_templates, dest_templates)
        print(f"Copied templates to: {dest_templates}")
    return dest_templates



# Ensure templates are copied
template_folder = copy_templates()

# Detect the base directory (location of the .exe)
base_dir = os.path.dirname(os.path.abspath(__file__))
print(f"Running from: {base_dir}")
print(f"Looking for templates in: {os.path.join(base_dir, 'templates')}")



# Flask app with external templates folder
app = Flask(__name__, template_folder=os.path.join(base_dir, 'templates'))

media_info = {
    'title': 'Unknown',
    'artist': 'Unknown',
    'position': 0,
    'duration': 0,
    'cover': '',
    'app_id': 'Unknown',
    'status': 'Stopped'
}

STATUS_MAP = {
    0: "Closed",
    1: "Stopped",
    5: "Paused",
    4: "Playing"
}

last_update_time = 0
last_position = 0
last_song_id = ""
last_known_position = 0

# Store current layout
template_name = 'horizontal'


locked_app_id = None  # Global lock state


def get_local_ip():
    #print("DEBUG: get_local_ip")
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        return local_ip
    except Exception as e:
        print(f"Error getting local IP: {e}")
        return "127.0.0.1"


def set_layout(layout):
    global template_name
    #print("DEBUG: set_layout")
    template_name = layout

async def get_media_info():
    global last_update_time, last_position, last_song_id, last_known_position, cached_cover, cached_song_id, locked_app_id
    #print("DEBUG: get_media_info")
    try:
        session_manager = await MediaManager.request_async()
        current_session = session_manager.get_current_session()

        if not current_session:
            return None

        info = await current_session.try_get_media_properties_async()
        playback_info = current_session.get_playback_info()
        timeline = current_session.get_timeline_properties()
        app_id = current_session.source_app_user_model_id

        current_song_id = f"{info.title}-{info.artist}"
        playback_status = playback_info.playback_status

        current_time = time.time()
        current_timeline_position = int(timeline.position.total_seconds())

        if (
            current_song_id != last_song_id or
            abs(current_timeline_position - last_known_position) > 1
        ):
            last_position = current_timeline_position
            last_update_time = current_time
            last_song_id = current_song_id

        if playback_status == 4:  # Playing
            elapsed_time = current_time - last_update_time
            position = last_position + elapsed_time
        else:
            position = current_timeline_position

        last_update_time = current_time
        last_position = position
        last_known_position = current_timeline_position

        duration = timeline.end_time.total_seconds()
        
        
        
        
        
        
        # only extract cover if the app id matches in case we have locked the app id
        if locked_app_id:
            session_app_id = app_id if new_info else None
            if session_app_id and "!" in session_app_id:
                session_app_id = session_app_id.split("!")[1]
            if session_app_id == locked_app_id:
                # Only reload cover art if song changed
                if current_song_id != cached_song_id:
                    cached_cover = await extract_cover(info.thumbnail) if info.thumbnail else ""
                    cached_song_id = current_song_id
        else:
            # no app id locked, so we can normally update the cover in case if the song changed.
            # Only reload cover art if song changed
            if current_song_id != cached_song_id:
                cached_cover = await extract_cover(info.thumbnail) if info.thumbnail else ""
                cached_song_id = current_song_id
        
        return {
            'title': info.title,
            'artist': info.artist,
            'position': position,
            'duration': duration,
            'cover': cached_cover,
            'app_id': app_id,
            'status': STATUS_MAP.get(playback_status, "Unknown")
        }
    except Exception as e:
        print(f"Error in get_media_info: {e}")
        return None

async def extract_cover(thumbnail):
    #print("DEBUG: extract_cover")
    try:
        stream = await thumbnail.open_read_async()
        reader = DataReader(stream)

        await reader.load_async(stream.size)

        data = bytes(reader.read_buffer(stream.size))

        return f"data:image/png;base64,{base64.b64encode(data).decode('utf-8')}"
    except Exception as e:
        print(f"Error extracting cover: {e}")
        return ""

async def update_media_info():
    global media_info, locked_app_id
    #print("DEBUG: update_media_info")
    while True:
        #print("DEBUG: update_media_info while")
        try:
            new_info = await get_media_info()

            if locked_app_id:
                session_app_id = new_info.get('app_id') if new_info else None
                if session_app_id and "!" in session_app_id:
                    session_app_id = session_app_id.split("!")[1]
                if session_app_id != locked_app_id:
                    await asyncio.sleep(1)
                    continue

            if new_info:
                if is_significant_change(new_info, media_info):
                    media_info.update(new_info)
            else:
                # Reset to default when no session is active
                media_info = {
                    'title': 'Unknown',
                    'artist': 'Unknown',
                    'position': 0,
                    'duration': 0,
                    'cover': '',
                    'app_id': 'Unknown',
                    'status': 'Stopped'
                }
        except Exception as e:
            print(f"Error updating media info: {e}")
        await asyncio.sleep(1)


@app.route('/')
def index():
    #print("DEBUG: /")
    return render_template(f'{template_name}.html', media=media_info)

@app.route('/media')
def media():
    #print("DEBUG: media")
    return jsonify(media_info)

@app.route('/reload')
def reload():
    #print("DEBUG: reload")
    """Force a page reload to reflect layout changes."""
    return redirect(url_for('index'))

def start_async_loop():
    #print("DEBUG: start_async_loop")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(update_media_info())

def create_gui():
    global locked_app_id
    #print("DEBUG: create_gui")
    root = tk.Tk()
    root.title("Now Playing Widget v1.0.3 © Crypto90")
    root.geometry("400x285")
    root.resizable(False, False)
    root.configure(bg="#1e1e1e")  # Dark background

    # Unified styling for dark mode
    def style_widget(widget):
        #print("DEBUG: style_widget")
        widget.configure(bg="#1e1e1e", fg="white", highlightbackground="#333", highlightcolor="white")

    def shutdown():
        print("Shutting down...")
        os._exit(0)

    root.protocol("WM_DELETE_WINDOW", shutdown)
    
    
    # Create a container frame for two columns
    top_frame = tk.Frame(root, bg="#1e1e1e")
    top_frame.pack(fill="x", pady=(10, 0))
    
    
    # Left column (Layout)
    layout_frame = tk.Frame(top_frame, bg="#1e1e1e")
    layout_frame.pack(side="left", fill="y", expand=True, anchor='w', padx=10)

    label_layout = tk.Label(layout_frame, text="Select Layout:", font=("TkDefaultFont", 10, "bold"))
    style_widget(label_layout)
    label_layout.pack(anchor='w', pady=(0, 0))

    layout_var = tk.StringVar(value=template_name)

    def update_layout():
        global locked_app_id, template_name
        #print("DEBUG: update_layout")
        new_layout = layout_var.get()
        set_layout(new_layout)
        save_settings(locked_app=locked_app_id, layout=new_layout)  # Preserve lock
        os.system('curl http://localhost:5000/reload')


    tk.Radiobutton(
        layout_frame, text="Horizontal", variable=layout_var, value="horizontal",
        command=update_layout, fg="white", bg="#1e1e1e", selectcolor="#333333",
        activebackground="#2e2e2e", activeforeground="white", cursor="hand2"
    ).pack(anchor='w')

    tk.Radiobutton(
        layout_frame, text="Vertical", variable=layout_var, value="vertical",
        command=update_layout, fg="white", bg="#1e1e1e", selectcolor="#333333",
        activebackground="#2e2e2e", activeforeground="white", cursor="hand2"
    ).pack(anchor='w')

    # Right column (Widget URLs)
    url_frame = tk.Frame(top_frame, bg="#1e1e1e")
    url_frame.pack(side="left", fill="y", expand=True, anchor='n', padx=(20, 0))

    tk.Label(url_frame, text="Widget URLs:", font=("TkDefaultFont", 10, "bold"), fg="white", bg="#1e1e1e").pack(anchor='w')

    local_ip = get_local_ip()
    urls = [
        ("http://127.0.0.1:5000", "http://127.0.0.1:5000"),
        (f"http://{local_ip}:5000", f"http://{local_ip}:5000")
    ]

    def open_url(url):
        webbrowser.open_new(url)

    def copy_to_clipboard(url):
        root.clipboard_clear()
        root.clipboard_append(url)
        root.update()
    
    
    # First, find the maximum length of all URL display names
    max_name_length = max(len(name) for name, url in urls)
    for name, url in urls:
        frame = tk.Frame(url_frame, bg="#1e1e1e")
        frame.pack(anchor='w')

        # Set width based on the longest name (in characters)
        link = tk.Label(
            frame,
            text=f"{name}",
            fg="green",
            bg="#1e1e1e",
            cursor="hand2",
            width=max_name_length,  # Enforce equal width
            anchor="w"  # Left-align text inside label
        )
        link.pack(side="left")
        link.bind("<Button-1>", lambda e, url=url: open_url(url))

        copy_button = tk.Button(
            frame,
            text="copy",
            bg="darkgreen",
            fg="white",
            activebackground="#000066",
            activeforeground="white",
            cursor="hand2",
            command=lambda url=url: copy_to_clipboard(url)
        )
        copy_button.pack(side="left", padx=0)
    
    
    tk.Label(root, text="Now playing:", font=("TkDefaultFont", 10, "bold"), fg="white", bg="#1e1e1e").pack(anchor='w', padx=10, pady=(10, 0))
    
    # current title
    #current_title_label = tk.Label(root, text="[00:00] Unknown - Unknown", fg="white", bg="#000000")
    #style_widget(current_title_label)
    #current_title_label.pack(anchor='w', padx=10, pady=(0, 0))
    
    # === New Visual Now Playing Widget ===
    now_playing_frame = tk.Frame(root, bg="#1e1e1e")
    now_playing_frame.pack(fill="x", padx=10, pady=(0, 0))

    cover_label = tk.Label(now_playing_frame, bg="#1e1e1e")
    cover_label.grid(row=0, column=0, rowspan=3, padx=(0, 10))

    song_title_label = tk.Label(now_playing_frame, text="Title", font=("Segoe UI", 10, "bold"), bg="#1e1e1e", fg="white", anchor="w")
    song_title_label.grid(row=0, column=1, sticky="w")

    artist_label = tk.Label(now_playing_frame, text="Artist", font=("Segoe UI", 9), bg="#1e1e1e", fg="#cccccc", anchor="w")
    artist_label.grid(row=1, column=1, sticky="w")

    progress_frame = tk.Frame(now_playing_frame, bg="#1e1e1e")
    progress_frame.grid(row=2, column=1, sticky="we")

    # Progress bar
    progress_canvas = tk.Canvas(progress_frame, height=6, width=300, bg="#333333", highlightthickness=0)
    progress_canvas.pack(fill="x")

    # Time labels frame
    time_label_frame = tk.Frame(progress_frame, bg="#1e1e1e")
    time_label_frame.pack(fill="x", pady=(2, 0))  # Slight padding above

    start_time_label = tk.Label(time_label_frame, text="00:00", font=("Segoe UI", 8), bg="#1e1e1e", fg="white")
    start_time_label.pack(side="left")

    end_time_label = tk.Label(time_label_frame, text="00:00", font=("Segoe UI", 8), bg="#1e1e1e", fg="white")
    end_time_label.pack(side="right")

    
    
    
    
    
    tk.Label(root, text="Media process:", font=("TkDefaultFont", 10, "bold"), fg="white", bg="#1e1e1e").pack(anchor='w', padx=10, pady=(10, 0))
    # Current Playing Process
    
    current_process_label = tk.Label(root, text="None", fg="white", bg="#1e1e1e")
    style_widget(current_process_label)
    current_process_label.pack(anchor='w', padx=10, pady=(0, 0))
    
    
    
    
    
    
    
    
    
    
    
    # Lock Button
    def toggle_lock():
        global locked_app_id, template_name  # Make sure template_name is accessible
        #print("DEBUG: toggle_lock")
        if locked_app_id:
            locked_app_id = None
            save_settings(locked_app=None, layout=template_name)  # Preserve layout
            lock_button.config(text="Lock Current App", bg="darkred", fg="white", activebackground="#660000", activeforeground="white")
        else:
            locked_app_id = media_info.get("app_id")
            if "!" in locked_app_id:
                locked_app_id = locked_app_id.split("!")[1]
            save_settings(locked_app=locked_app_id, layout=template_name)  # Preserve layout
            lock_button.config(text="Unlock App", bg="darkgreen", fg="white", activebackground="#004d00", activeforeground="white")


    
    lock_button = tk.Button(
        root,
        text="Lock Current App",
        command=toggle_lock,
        bg="darkred",
        fg="white",
        activebackground="#660000",  # Darker red
        activeforeground="white",
        cursor="hand2"
    )

    # Frame for Lock and Donate buttons on same row
    button_row = tk.Frame(root, bg="#1e1e1e")
    button_row.pack(fill="x", padx=10, pady=(5, 10))

    # Lock Button (left aligned)
    lock_button = tk.Button(
        button_row,
        text="Lock Current App",
        command=toggle_lock,
        bg="darkred",
        fg="white",
        activebackground="#660000",
        activeforeground="white",
        cursor="hand2"
    )
    lock_button.pack(side="left")

    # Donate Button (right aligned with 10px padding from right)
    donate_button = tk.Button(
        button_row,
        text="Buy me a Coffee ☕",
        command=lambda: webbrowser.open("https://ko-fi.com/crypto90"),
        bg="#f39c12",
        fg="black",
        activebackground="#d68910",
        activeforeground="black",
        cursor="hand2"
    )
    donate_button.pack(side="right", padx=(0, 0))  # Already right-aligned

    
    # Set initial button state
    if locked_app_id:
        lock_button.config(text="Unlock App", bg="darkgreen", fg="white", activebackground="#004d00", activeforeground="white")

    
    
    
    
    
    
    def format_seconds(seconds: int) -> str:
        #print("DEBUG: format_seconds")
        """
        Convert seconds to a human-readable HH:MM:SS or MM:SS format.
        Hours are omitted if not needed.
        """
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60

        if hours > 0:
            return f"{hours:02}:{minutes:02}:{secs:02}"
        else:
            return f"{minutes:02}:{secs:02}"

    
    
    # Update UI loop
    def update_process_label():
        global cached_cover
        #print("DEBUG: update_process_label")
        app_id = media_info.get("app_id", "Unknown")
        status = media_info.get("status", "Stopped")
        
        title = media_info.get("title") or "Unknown"
        artist = media_info.get("artist") or "Unknown"

        # For position and duration, which are numbers, make sure to handle empty string or None
        try:
            position = int(media_info.get("position", 0))
        except (TypeError, ValueError):
            position = 0

        try:
            duration = int(media_info.get("duration", 0))
        except (TypeError, ValueError):
            duration = 0
        
        
        # Update labels
        song_title_label.config(text=title)
        artist_label.config(text=artist)
        start_time_label.config(text=format_seconds(int(position)))
        end_time_label.config(text=format_seconds(int(duration)))

        # Update progress bar
        if duration > 0 and position <= duration:
            percent = position / duration
            progress_canvas.delete("all")
            width = progress_canvas.winfo_width()
            progress_canvas.create_rectangle(0, 0, width * percent, 10, fill="#00cc66", width=0)
        else:
            # Clear progress bar when no media or duration
            progress_canvas.delete("all")

        # Update album art
        try:
            if cached_cover.startswith("data:image") and duration > 0:
                img_data = base64.b64decode(cached_cover.split(",")[1])
                img = Image.open(io.BytesIO(img_data)).resize((60, 60)).convert("RGBA")

                if status == "Paused":
                    

                    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
                    draw = ImageDraw.Draw(overlay)

                    # Dimensions for pause bars
                    bar_width = 6
                    spacing = 6
                    height = 30
                    x_center = img.width // 2

                    # Left bar
                    draw.rectangle(
                        [x_center - spacing - bar_width, (img.height - height) // 2,
                         x_center - spacing, (img.height + height) // 2],
                        fill=(255, 255, 255, 180)
                    )
                    # Right bar
                    draw.rectangle(
                        [x_center + spacing, (img.height - height) // 2,
                         x_center + spacing + bar_width, (img.height + height) // 2],
                        fill=(255, 255, 255, 180)
                    )

                    img = Image.alpha_composite(img, overlay)
            else:
                img = Image.new("RGB", (64, 64), "black")  # fallback black square
            
            cover_img = ImageTk.PhotoImage(img)
            cover_label.config(image=cover_img)
            cover_label.image = cover_img  # Keep reference!
        except Exception as e:
            print(f"Error updating cover: {e}")

        # App ID status
        if "!" in app_id:
            app_id = app_id.split("!")[1]
        if locked_app_id and app_id != locked_app_id:
            current_process_label.config(text=f"Locked ({locked_app_id})")
        else:
            current_process_label.config(text=f"{app_id} ({status})")

        root.after(1000, update_process_label)


    update_process_label()
    
    
    
    
    
    
    
    
    
    
    root.mainloop()

settings = load_settings()
locked_app_id = settings.get("locked_app")
template_name = settings.get("layout", "horizontal")  # fallback default


if __name__ == '__main__':
    threading.Thread(target=start_async_loop, daemon=True).start()
    threading.Thread(target=create_gui, daemon=True).start()
    app.run(host='0.0.0.0', port=5000)
