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

def get_exe_dir():
    """
    Get the directory where the executable is located (not the temp folder).
    """
    if getattr(sys, '_MEIPASS', False):
        return os.path.dirname(sys.executable)  # Path of the .exe
    return os.path.dirname(os.path.abspath(__file__))

def copy_templates():
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





def get_local_ip():
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        return local_ip
    except Exception as e:
        print(f"Error getting local IP: {e}")
        return "127.0.0.1"


def set_layout(layout):
    global template_name
    template_name = layout

async def get_media_info():
    global last_update_time, last_position, last_song_id, last_known_position

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
        cover_data = await extract_cover(info.thumbnail) if info.thumbnail else ""
        return {
            'title': info.title,
            'artist': info.artist,
            'position': position,
            'duration': duration,
            'cover': cover_data,
            'app_id': app_id,
            'status': STATUS_MAP.get(playback_status, "Unknown")
        }
    except Exception as e:
        print(f"Error in get_media_info: {e}")
        return None

async def extract_cover(thumbnail):
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
    while True:
        try:
            new_info = await get_media_info()
            if new_info:
                media_info.update(new_info)
        except Exception as e:
            print(f"Error updating media info: {e}")
        await asyncio.sleep(1)

@app.route('/')
def index():
    return render_template(f'{template_name}.html', media=media_info)

@app.route('/media')
def media():
    return jsonify(media_info)

@app.route('/reload')
def reload():
    """Force a page reload to reflect layout changes."""
    return redirect(url_for('index'))

def start_async_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(update_media_info())

def create_gui():
    root = tk.Tk()
    root.title("Now Playing Widget")
    root.geometry("300x200")

    def shutdown():
        print("Shutting down...")
        os._exit(0)  # Force quit all threads and Flask

    root.protocol("WM_DELETE_WINDOW", shutdown)

    tk.Label(root, text="Select Layout:", font=("TkDefaultFont", 10, "bold")).pack(anchor='w')

    
    layout_var = tk.StringVar(value="horizontal")

    def update_layout():
        set_layout(layout_var.get())
        # Force Flask page reload when layout changes
        os.system('curl http://localhost:5000/reload')

    tk.Radiobutton(root, text="Horizontal", variable=layout_var, value="horizontal", command=update_layout).pack(anchor='w')
    tk.Radiobutton(root, text="Vertical", variable=layout_var, value="vertical", command=update_layout).pack(anchor='w')
    
    
    
    
    tk.Label(root, text="Widget URLs:", font=("TkDefaultFont", 10, "bold")).pack(anchor='w')

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

    for name, url in urls:
        frame = tk.Frame(root)
        frame.pack(padx=5, anchor='w')

        link = tk.Label(frame, text=f"{name}", fg="blue", cursor="hand2")
        link.pack(side="left")
        link.bind("<Button-1>", lambda e, url=url: open_url(url))

        copy_button = tk.Button(frame, text="copy", command=lambda url=url: copy_to_clipboard(url))
        copy_button.pack(side="left", padx=5)

    
    
    
    
    
    root.mainloop()

if __name__ == '__main__':
    threading.Thread(target=start_async_loop, daemon=True).start()
    threading.Thread(target=create_gui, daemon=True).start()
    app.run(host='0.0.0.0', port=5000)
