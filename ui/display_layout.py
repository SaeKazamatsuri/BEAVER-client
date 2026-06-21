from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

try:
    from screeninfo import get_monitors
except ModuleNotFoundError:
    def get_monitors() -> list[object]:
        return []


@dataclass(frozen=True, slots=True)
class MonitorRect:
    width: int
    height: int
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class WindowRect:
    width: int
    height: int
    x: int
    y: int

    def to_geometry(self) -> str:
        return f"{self.width}x{self.height}+{self.x}+{self.y}"


@dataclass(frozen=True, slots=True)
class DisplayLayoutSnapshot:
    monitor: MonitorRect
    comment_rect: WindowRect
    overlay_rect: WindowRect
    poll_results_rect: WindowRect
    stamp_area_mode: str


class CommentWindow(Protocol):
    def geometry(self, new_geometry: str) -> object:
        ...


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _monitor_rect_from_object(monitor: object) -> MonitorRect | None:
    width = _coerce_int(getattr(monitor, "width", None))
    height = _coerce_int(getattr(monitor, "height", None))
    x = _coerce_int(getattr(monitor, "x", None))
    y = _coerce_int(getattr(monitor, "y", None))
    if width is None or height is None or x is None or y is None:
        return None
    if width <= 0 or height <= 0:
        return None
    return MonitorRect(width=width, height=height, x=x, y=y)


def load_monitor_rects(
    monitor_provider: Callable[[], Sequence[object]] = get_monitors,
) -> tuple[MonitorRect, ...]:
    try:
        monitors = monitor_provider()
    except Exception:
        return ()

    rects: list[MonitorRect] = []
    for monitor in monitors:
        rect = _monitor_rect_from_object(monitor)
        if rect is not None:
            rects.append(rect)
    return tuple(rects)


def build_layout(
    monitor: MonitorRect,
    _stamp_area_mode: str,
) -> DisplayLayoutSnapshot:
    comment_width = max(1, monitor.width // 4)
    comment_rect = WindowRect(
        width=comment_width,
        height=max(1, monitor.height),
        x=monitor.x + monitor.width - comment_width,
        y=monitor.y,
    )
    overlay_rect = comment_rect
    poll_results_rect = WindowRect(
        width=max(1, monitor.width - comment_width),
        height=max(1, monitor.height),
        x=monitor.x,
        y=monitor.y,
    )
    return DisplayLayoutSnapshot(
        monitor=monitor,
        comment_rect=comment_rect,
        overlay_rect=overlay_rect,
        poll_results_rect=poll_results_rect,
        stamp_area_mode="comment",
    )


class DisplayLayoutController:
    def __init__(
        self,
        *,
        root: CommentWindow,
        overlay_geometry_updater: Callable[[WindowRect], None],
        stamp_area_mode_getter: Callable[[], str],
        poll_results_geometry_updater: Callable[[WindowRect], None] | None = None,
        monitor_provider: Callable[[], Sequence[object]] = get_monitors,
    ) -> None:
        self._root = root
        self._overlay_geometry_updater = overlay_geometry_updater
        self._poll_results_geometry_updater = poll_results_geometry_updater
        self._stamp_area_mode_getter = stamp_area_mode_getter
        self._monitor_provider = monitor_provider
        self.active_monitor_index = 0
        self._current_snapshot: DisplayLayoutSnapshot | None = None

    @property
    def current_snapshot(self) -> DisplayLayoutSnapshot | None:
        return self._current_snapshot

    def apply_layout(self) -> DisplayLayoutSnapshot | None:
        monitors = load_monitor_rects(self._monitor_provider)
        return self._apply_from_monitors(monitors)

    def refresh_layout(self) -> DisplayLayoutSnapshot | None:
        return self.apply_layout()

    def switch_display(self) -> DisplayLayoutSnapshot | None:
        monitors = load_monitor_rects(self._monitor_provider)
        if not monitors:
            return None
        self._clamp_monitor_index(len(monitors))
        self.active_monitor_index = (self.active_monitor_index + 1) % len(monitors)
        return self._apply_from_monitors(monitors)

    def _apply_from_monitors(
        self,
        monitors: Sequence[MonitorRect],
    ) -> DisplayLayoutSnapshot | None:
        if not monitors:
            return None
        self._clamp_monitor_index(len(monitors))
        snapshot = build_layout(
            monitors[self.active_monitor_index],
            self._stamp_area_mode_getter(),
        )
        self._root.geometry(snapshot.comment_rect.to_geometry())
        self._overlay_geometry_updater(snapshot.overlay_rect)
        if self._poll_results_geometry_updater is not None:
            self._poll_results_geometry_updater(snapshot.poll_results_rect)
        self._current_snapshot = snapshot
        return snapshot

    def _clamp_monitor_index(self, count: int) -> None:
        if count <= 0:
            self.active_monitor_index = 0
            return
        if self.active_monitor_index < 0:
            self.active_monitor_index = 0
            return
        if self.active_monitor_index >= count:
            self.active_monitor_index = count - 1
