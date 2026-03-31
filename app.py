from __future__ import annotations

import queue
import tkinter as tk

from services.events import disconnect_session
from services.transcription_service import (
    start_transcription_service,
    stop_transcription_service,
)
from state import app_state as state
from ui.comment_ui import COMMENT_COLUMN_BG, CommentListView, comment_entry_from_message
from ui.display_layout import DisplayLayoutController
from ui.overlay import (
    annotate_entry,
    bind_overlay_canvas,
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
    root.configure(bg=COMMENT_COLUMN_BG)
    root.resizable(False, True)
    root.attributes("-topmost", True)
    layout_controller = DisplayLayoutController(
        root=root,
        overlay_geometry_updater=update_overlay_geometry,
        stamp_area_mode_getter=lambda: "comment",
    )
    layout_controller.apply_layout()
    root.update()
    set_always_on_top(root.winfo_id())
    start_transcription_service(
        lambda: state.CURRENT_SESSION if state.session_ready else None,
        state.record_transcription_service_update,
        state.append_transcription_item,
    )

    wrapper = tk.Frame(root, bg=COMMENT_COLUMN_BG)
    wrapper.pack(expand=True, fill="both")

    comment_list = CommentListView(wrapper)
    comment_list.pack(expand=True, fill="both")
    bind_overlay_canvas(comment_list.overlay_canvas)
    layout_controller.refresh_layout()

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
        layout_controller.switch_display()

    create_menu_window(switch_display, layout_controller.refresh_layout, root)
    update_comments()

    def on_close() -> None:
        disconnect_session(show_status=False)
        stop_transcription_service()
        stop_overlay()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
