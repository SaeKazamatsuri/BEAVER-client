from __future__ import annotations

import unittest
from dataclasses import dataclass

from ui.display_layout import (
    DisplayLayoutController,
    MonitorRect,
    WindowRect,
    build_layout,
)


@dataclass(frozen=True, slots=True)
class _FakeMonitor:
    width: int
    height: int
    x: int
    y: int


class _RootDouble:
    def __init__(self) -> None:
        self.geometry_calls: list[str] = []

    def geometry(self, new_geometry: str) -> None:
        self.geometry_calls.append(new_geometry)


class _RectDouble:
    def __init__(self) -> None:
        self.rect_calls: list[WindowRect] = []

    def update(self, rect: WindowRect) -> None:
        self.rect_calls.append(rect)


class BuildLayoutTests(unittest.TestCase):
    def test_comment_mode_uses_right_quarter_and_poll_results_use_left_area(self) -> None:
        monitor = MonitorRect(width=1920, height=1080, x=0, y=0)

        snapshot = build_layout(monitor, "comment")

        expected_comment_rect = WindowRect(width=480, height=1080, x=1440, y=0)
        expected_poll_results_rect = WindowRect(width=1440, height=1080, x=0, y=0)
        self.assertEqual(snapshot.comment_rect, expected_comment_rect)
        self.assertEqual(snapshot.overlay_rect, expected_comment_rect)
        self.assertEqual(snapshot.poll_results_rect, expected_poll_results_rect)
        self.assertEqual(snapshot.stamp_area_mode, "comment")

    def test_non_comment_mode_still_uses_right_quarter(self) -> None:
        monitor = MonitorRect(width=1920, height=1080, x=100, y=20)

        snapshot = build_layout(monitor, "left75")

        expected_rect = WindowRect(width=480, height=1080, x=1540, y=20)
        self.assertEqual(snapshot.comment_rect, expected_rect)
        self.assertEqual(snapshot.overlay_rect, expected_rect)
        self.assertEqual(
            snapshot.poll_results_rect,
            WindowRect(width=1440, height=1080, x=100, y=20),
        )
        self.assertEqual(snapshot.stamp_area_mode, "comment")


class DisplayLayoutControllerTests(unittest.TestCase):
    def test_switch_display_moves_comment_and_overlay_to_next_monitor(self) -> None:
        monitors = [
            _FakeMonitor(width=1920, height=1080, x=0, y=0),
            _FakeMonitor(width=1920, height=1080, x=1920, y=0),
        ]
        root = _RootDouble()
        overlay = _RectDouble()
        poll_results = _RectDouble()
        controller = DisplayLayoutController(
            root=root,
            overlay_geometry_updater=overlay.update,
            poll_results_geometry_updater=poll_results.update,
            stamp_area_mode_getter=lambda: "comment",
            monitor_provider=lambda: monitors,
        )

        initial_snapshot = controller.apply_layout()
        switched_snapshot = controller.switch_display()

        self.assertIsNotNone(initial_snapshot)
        self.assertIsNotNone(switched_snapshot)
        assert initial_snapshot is not None
        assert switched_snapshot is not None
        self.assertEqual(initial_snapshot.comment_rect.x, 1440)
        self.assertEqual(switched_snapshot.comment_rect.x, 3360)
        self.assertEqual(switched_snapshot.overlay_rect.x, 3360)
        self.assertEqual(switched_snapshot.poll_results_rect.x, 1920)
        self.assertEqual(root.geometry_calls[-1], switched_snapshot.comment_rect.to_geometry())
        self.assertEqual(overlay.rect_calls[-1], switched_snapshot.overlay_rect)
        self.assertEqual(poll_results.rect_calls[-1], switched_snapshot.poll_results_rect)

    def test_clamps_monitor_index_when_monitor_count_shrinks(self) -> None:
        monitors = [
            _FakeMonitor(width=1920, height=1080, x=0, y=0),
            _FakeMonitor(width=1920, height=1080, x=1920, y=0),
        ]
        root = _RootDouble()
        overlay = _RectDouble()

        def provider() -> list[_FakeMonitor]:
            return list(monitors)

        controller = DisplayLayoutController(
            root=root,
            overlay_geometry_updater=overlay.update,
            stamp_area_mode_getter=lambda: "comment",
            monitor_provider=provider,
        )

        controller.switch_display()
        monitors.pop()

        snapshot = controller.refresh_layout()

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(controller.active_monitor_index, 0)
        self.assertEqual(snapshot.comment_rect, WindowRect(width=480, height=1080, x=1440, y=0))
        self.assertEqual(snapshot.overlay_rect, snapshot.comment_rect)
        self.assertEqual(snapshot.poll_results_rect, WindowRect(width=1440, height=1080, x=0, y=0))

    def test_switch_display_applies_same_snapshot_to_root_and_overlay(self) -> None:
        monitors = [
            _FakeMonitor(width=1920, height=1080, x=0, y=0),
            _FakeMonitor(width=1920, height=1080, x=1920, y=0),
        ]
        root = _RootDouble()
        overlay = _RectDouble()
        poll_results = _RectDouble()
        controller = DisplayLayoutController(
            root=root,
            overlay_geometry_updater=overlay.update,
            poll_results_geometry_updater=poll_results.update,
            stamp_area_mode_getter=lambda: "comment",
            monitor_provider=lambda: monitors,
        )

        controller.apply_layout()
        root.geometry_calls.clear()
        overlay.rect_calls.clear()
        poll_results.rect_calls.clear()

        snapshot = controller.switch_display()

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(root.geometry_calls, [snapshot.comment_rect.to_geometry()])
        self.assertEqual(overlay.rect_calls, [snapshot.overlay_rect])
        self.assertEqual(poll_results.rect_calls, [snapshot.poll_results_rect])
        self.assertEqual(controller.current_snapshot, snapshot)

    def test_refresh_layout_keeps_active_monitor_when_mode_input_changes(self) -> None:
        monitors = [
            _FakeMonitor(width=1920, height=1080, x=0, y=0),
            _FakeMonitor(width=1920, height=1080, x=1920, y=0),
        ]
        stamp_area_mode = ["comment"]
        root = _RootDouble()
        overlay = _RectDouble()
        poll_results = _RectDouble()
        controller = DisplayLayoutController(
            root=root,
            overlay_geometry_updater=overlay.update,
            poll_results_geometry_updater=poll_results.update,
            stamp_area_mode_getter=lambda: stamp_area_mode[0],
            monitor_provider=lambda: monitors,
        )

        comment_snapshot = controller.switch_display()
        stamp_area_mode[0] = "left75"
        root.geometry_calls.clear()
        overlay.rect_calls.clear()
        poll_results.rect_calls.clear()

        left75_snapshot = controller.refresh_layout()

        self.assertIsNotNone(comment_snapshot)
        self.assertIsNotNone(left75_snapshot)
        assert comment_snapshot is not None
        assert left75_snapshot is not None
        self.assertEqual(controller.active_monitor_index, 1)
        self.assertEqual(comment_snapshot.comment_rect, left75_snapshot.comment_rect)
        self.assertEqual(comment_snapshot.overlay_rect, left75_snapshot.overlay_rect)
        self.assertEqual(
            left75_snapshot.overlay_rect,
            WindowRect(width=480, height=1080, x=3360, y=0),
        )
        self.assertEqual(
            left75_snapshot.poll_results_rect,
            WindowRect(width=1440, height=1080, x=1920, y=0),
        )
        self.assertEqual(root.geometry_calls, [left75_snapshot.comment_rect.to_geometry()])
        self.assertEqual(overlay.rect_calls, [left75_snapshot.overlay_rect])
        self.assertEqual(poll_results.rect_calls, [left75_snapshot.poll_results_rect])


if __name__ == "__main__":
    unittest.main()
