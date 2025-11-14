from __future__ import annotations

import html
import queue

import tkinter as tk
from screeninfo import get_monitors
from tkinterweb import HtmlFrame

import app_state as state
import events  # noqa: F401
from constants import BUBBLE_HTML_PATH
from overlay import (
    annotate_entry,
    ensure_overlay_window,
    enqueue_stamp_balloon,
    is_stamp,
    stop_overlay,
    update_overlay_geometry,
)
from ui import create_menu_window, set_always_on_top


def main():
    state.root = tk.Tk()
    root = state.root
    root.title("コメント表示")
    root.overrideredirect(True)

    monitors = get_monitors()
    current_monitor = [0]
    overlay_geometry_state = {"geometry": None, "width": 0, "height": 0}

    def sync_overlay_position(event=None):
        if root is None:
            return
        geometry = root.winfo_geometry()
        if not geometry:
            return
        width = event.width if event is not None else root.winfo_width()
        height = event.height if event is not None else root.winfo_height()
        if width <= 0 or height <= 0:
            return
        state_cache = overlay_geometry_state
        if (
            state_cache["geometry"] == geometry
            and state_cache["width"] == width
            and state_cache["height"] == height
        ):
            return
        state_cache["geometry"] = geometry
        state_cache["width"] = width
        state_cache["height"] = height
        update_overlay_geometry(geometry, width, height)

    def update_monitor_position():
        scr = monitors[current_monitor[0]]
        w, h = scr.width // 4, scr.height
        geometry = f"{w}x{h}+{scr.x + scr.width - w}+{scr.y}"
        root.geometry(geometry)
        root.resizable(False, True)
        update_overlay_geometry(geometry, w, h)

    update_monitor_position()
    root.configure(bg="#fefefe")
    root.attributes("-topmost", True)
    root.update()
    set_always_on_top(root.winfo_id())
    ensure_overlay_window(root)
    update_overlay_geometry(root.winfo_geometry(), root.winfo_width(), root.winfo_height())
    root.bind("<Configure>", sync_overlay_position, add="+")
    sync_overlay_position()

    wrapper = tk.Frame(root, bg="#fefefe")
    wrapper.pack(expand=True, fill="both")

    html_frame = HtmlFrame(
        wrapper, horizontal_scrollbar=False, vertical_scrollbar=False
    )
    html_frame.pack(expand=True, fill="both")

    for child in html_frame.winfo_children():
        if child.winfo_class() == "Scrollbar":
            child.pack_forget()

    with open(BUBBLE_HTML_PATH, encoding="utf-8") as fp:
        bubble_html = fp.read()

    last_html = [""]

    style_block = """
<style>
html, body {
  margin: 0;
  padding: 0;
  height: 100%;
  width: 100%;
  overflow: hidden;
  font-family: "Noto Sans JP", sans-serif;
  background-color: #6dd3f7;
}
#app-root {
  position: relative;
  width: 100%;
  height: 100vh;
  overflow: hidden;
  background-color: #6dd3f7;
}
#comment-column {
  position: relative;
  height: 100%;
  overflow-y: auto;
  padding: 28px 20px 40px 20px;
  box-sizing: border-box;
}
#comment-column::-webkit-scrollbar {
  width: 0;
  height: 0;
}
.comment-wrapper {
  position: relative;
  max-width: 92%;
  margin: 0 auto 24px auto;
}
.comment-wrapper:last-child {
  margin-bottom: 0;
}
.shadow-box {
  position: absolute;
  top: 12px;
  left: 8px;
  width: calc(100% - 16px);
  height: calc(100% - 12px);
  background-color: rgba(11, 31, 51, 0.15);
  border-radius: 32px;
  z-index: 0;
}
.shadow-box::after {
  content: "";
  position: absolute;
  top: 10px;
  left: 10px;
  right: 10px;
  bottom: 10px;
  border: 2px dashed rgba(11, 31, 51, 0.3);
  border-radius: 28px;
}
.comment-box {
  position: relative;
  background-color: #fff;
  border-radius: 32px;
  padding: 32px;
  z-index: 1;
  border: 3px solid #0b1f33;
  box-shadow: 0 16px 32px rgba(11, 31, 51, 0.25);
}
.comment-box::after {
  content: "";
  position: absolute;
  width: 60px;
  height: 60px;
  background-image: url("data:image/svg+xml,%3Csvg width='120' height='120' viewBox='0 0 120 120' xmlns='http://www.w3.org/2000/svg'%3E%3Ccircle cx='20' cy='20' r='3' fill='%230b1f33' fill-opacity='0.12'/%3E%3C/svg%3E");
  background-repeat: repeat;
  top: 18px;
  right: 24px;
  opacity: 0.35;
}
.name-label {
  position: absolute;
  top: -18px;
  left: 32px;
  background-color: #fffdaf;
  padding: 8px 24px;
  border-radius: 999px;
  border: 2px solid #0b1f33;
  font-weight: bold;
  box-shadow: 4px 6px 0 rgba(11, 31, 51, 0.3);
}
.comment-name-time {
  font-size: 14px;
  color: #72809a;
  margin-bottom: 12px;
  text-align: right;
}
.comment-text {
  font-size: 24px;
  line-height: 1.5;
  color: #0b1f33;
  font-weight: 500;
}
.like {
  margin-top: 16px;
  min-height: 16px;
}
</style>
""".strip()

    if "</head>" in bubble_html:
        base_html = bubble_html.replace("</head>", f"{style_block}</head>")
    elif "<body" in bubble_html:
        base_html = bubble_html.replace("<body>", f"<body>{style_block}")
    else:
        base_html = style_block + bubble_html

    comment_placeholder = "<!--COMMENT_COLUMN-->"

    def update_comments():
        try:
            while True:
                raw = state.message_queue.get_nowait()
                entry = annotate_entry(raw)
                if is_stamp(entry):
                    enqueue_stamp_balloon(entry)
                    continue
                state.messages.append(entry)
        except queue.Empty:
            pass

        comment_items = []
        for msg in reversed(state.messages):
            name = html.escape(msg.get("name", ""))
            tstr = html.escape(str(msg.get("time", "")))
            time_part = f"<span style='font-weight:normal;color:#666;'>{tstr}</span>"
            text_html = html.escape(msg.get("text", ""))
            item = f"""
            <div class="comment-wrapper">
              <div class="shadow-box"></div>
              <div class="comment-box">
                <div class="name-label">{name}</div>
                <div class="comment-name-time">{time_part}</div>
                <div class="comment-text">{text_html}</div>
                <div class="like"></div>
              </div>
            </div>
            """
            comment_items.append(item)

        comment_html = "\n".join(comment_items)
        full_html = base_html
        if comment_placeholder in full_html:
            full_html = full_html.replace(comment_placeholder, comment_html, 1)
        else:
            full_html = full_html.replace("</body>", f"{comment_html}</body>")
        if full_html != last_html[0]:
            try:
                html_frame.load_html(full_html)
                last_html[0] = full_html
            except Exception:
                pass
        root.after(500, update_comments)

    def switch_display():
        if not monitors:
            return
        current_monitor[0] = (current_monitor[0] + 1) % len(monitors)
        update_monitor_position()

    create_menu_window(switch_display, root)
    update_comments()

    def on_close():
        try:
            if state.sio.connected:
                state.sio.disconnect()
        except Exception:
            pass
        stop_overlay()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
