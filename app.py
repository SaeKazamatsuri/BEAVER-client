from __future__ import annotations

import queue
import tkinter as tk

from screeninfo import get_monitors

from services.events import disconnect_session
from services.transcription_service import (
    start_transcription_service,
    stop_transcription_service,
)
from state import app_state as state
from ui.comment_ui import COMMENT_COLUMN_BG, CommentListView, comment_entry_from_message
from ui.overlay import (
    annotate_entry,
    ensure_overlay_window,
    enqueue_stamp_balloon,
    is_stamp,
    stop_overlay,
    update_overlay_geometry,
)
from ui.windows import create_menu_window, set_always_on_top

COMMENT_POLL_INTERVAL_MS = 100


def main() -> None:
    state.root = tk.Tk()
    root = state.root
    root.title("コメント表示")
    root.overrideredirect(True)

    monitors = get_monitors()
    current_monitor = [0]
    overlay_geometry_state = {"geometry": None, "width": 0, "height": 0}

    def _apply_overlay_geometry(geometry: str, width: int, height: int) -> None:
        if not geometry or width <= 0 or height <= 0:
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

    def _comment_rect(scr: object) -> tuple[int, int, int, int]:
        width = int(getattr(scr, "width"))
        height = int(getattr(scr, "height"))
        x = int(getattr(scr, "x"))
        y = int(getattr(scr, "y"))
        comment_w = max(1, width // 4)
        comment_h = max(1, height)
        comment_x = x + width - comment_w
        comment_y = y
        return comment_w, comment_h, comment_x, comment_y

    def _overlay_rect(scr: object) -> tuple[int, int, int, int]:
        screen_width = int(getattr(scr, "width"))
        screen_height = int(getattr(scr, "height"))
        screen_x = int(getattr(scr, "x"))
        screen_y = int(getattr(scr, "y"))
        comment_w, _, _, _ = _comment_rect(scr)
        mode = getattr(state, "stamp_area_mode", "comment")
        if mode == "left75":
            overlay_w = max(1, screen_width - comment_w)
            overlay_h = max(1, screen_height)
            overlay_x = screen_x
            overlay_y = screen_y
            return overlay_w, overlay_h, overlay_x, overlay_y
        overlay_w = max(1, comment_w)
        overlay_h = max(1, screen_height)
        overlay_x = screen_x + screen_width - overlay_w
        overlay_y = screen_y
        return overlay_w, overlay_h, overlay_x, overlay_y

    def _apply_layout(update_root: bool) -> None:
        if not monitors:
            return
        scr = monitors[current_monitor[0]]
        comment_w, comment_h, comment_x, comment_y = _comment_rect(scr)
        comment_geometry = f"{comment_w}x{comment_h}+{comment_x}+{comment_y}"
        if update_root:
            root.geometry(comment_geometry)
            root.resizable(False, True)

        overlay_w, overlay_h, overlay_x, overlay_y = _overlay_rect(scr)
        overlay_geometry = f"{overlay_w}x{overlay_h}+{overlay_x}+{overlay_y}"
        _apply_overlay_geometry(overlay_geometry, overlay_w, overlay_h)

    def sync_overlay_position(event: tk.Event | None = None) -> None:
        if getattr(state, "stamp_area_mode", "comment") != "comment":
            return
        geometry = root.winfo_geometry()
        width = int(event.width) if event is not None else root.winfo_width()
        height = int(event.height) if event is not None else root.winfo_height()
        _apply_overlay_geometry(geometry, width, height)

    def update_monitor_position() -> None:
        _apply_layout(update_root=True)

    update_monitor_position()
    root.configure(bg=COMMENT_COLUMN_BG)
    root.attributes("-topmost", True)
    root.update()
    set_always_on_top(root.winfo_id())
    ensure_overlay_window(root)
    _apply_layout(update_root=False)
    root.bind("<Configure>", sync_overlay_position, add="+")
    sync_overlay_position()

    def request_layout_refresh() -> None:
        if state.root is None:
            return
        try:
            state.root.after(0, lambda: _apply_layout(update_root=False))
        except Exception:
            pass

    state.request_layout_refresh = request_layout_refresh
    start_transcription_service(
        lambda: state.CURRENT_SESSION if state.session_ready else None,
        state.record_transcription_service_update,
        state.append_transcription_item,
    )

    wrapper = tk.Frame(root, bg=COMMENT_COLUMN_BG)
    wrapper.pack(expand=True, fill="both")

    comment_list = CommentListView(wrapper)
    comment_list.pack(expand=True, fill="both")

    rendered_generation, existing_comments = state.snapshot_messages()
    if existing_comments:
        comment_list.set_comments(existing_comments)
    rendered_generation_state = [rendered_generation]

    def update_comments() -> None:
        generation, comments = state.snapshot_messages()
        if generation != rendered_generation_state[0]:
            comment_list.clear()
            if comments:
                comment_list.set_comments(comments)
            rendered_generation_state[0] = generation

        try:
            while True:
                raw = state.message_queue.get_nowait()
                entry = annotate_entry(raw)
                if is_stamp(entry):
                    if entry.get("_from_history"):
                        continue
                    enqueue_stamp_balloon(entry)
                    continue
                comment_entry = comment_entry_from_message(entry)
                if comment_entry is None:
                    continue
                state.append_message(comment_entry)
                comment_list.add_comment(comment_entry)
        except queue.Empty:
            pass

        root.after(COMMENT_POLL_INTERVAL_MS, update_comments)

    def switch_display() -> None:
        if not monitors:
            return
        current_monitor[0] = (current_monitor[0] + 1) % len(monitors)
        update_monitor_position()

    create_menu_window(switch_display, root)
    update_comments()

    def on_close() -> None:
        disconnect_session(show_status=False)
        stop_transcription_service()
        stop_overlay()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
