import unittest
from unittest.mock import Mock

from gentrace.gui import GenTraceGui, calculate_autofit_width


class GuiHelpersTests(unittest.TestCase):
    def test_autofit_uses_longest_heading_or_value(self):
        width = calculate_autofit_width(
            "状態",
            ["完了", "とても長いモデル名"],
            lambda value: len(value) * 10,
        )
        self.assertEqual(width, 114)

    def test_autofit_obeys_minimum_and_maximum(self):
        self.assertEqual(calculate_autofit_width("A", [], lambda _value: 1), 40)
        self.assertEqual(
            calculate_autofit_width("A", ["long"], lambda _value: 1000),
            600,
        )

    def test_periodic_refresh_reuses_last_applied_filters(self):
        gui = object.__new__(GenTraceGui)
        gui.database = Mock()
        gui.database.change_token.return_value = (0, 0, 0, 0)
        gui._last_change_token = None
        gui._force_refresh = True
        gui.refresh = Mock()
        gui._show_selection = Mock()
        gui.root = Mock()

        gui._periodic_refresh()

        gui.refresh.assert_called_once_with(use_applied_filters=True)
        gui._show_selection.assert_called_once_with()
        gui.root.after.assert_called_once_with(2000, gui._periodic_refresh)

    def test_query_with_applied_filters_does_not_read_in_progress_input(self):
        gui = object.__new__(GenTraceGui)
        gui.database = Mock()
        gui.database.list_jobs.return_value = []
        gui._current_filters = Mock(side_effect=AssertionError("入力途中の条件を参照しました"))
        applied_filters = (1000, 2000, "completed", "model")

        rows = gui._query_rows(applied_filters)

        self.assertEqual(rows, [])
        gui._current_filters.assert_not_called()
        gui.database.list_jobs.assert_called_once_with(
            status="completed",
            model_query="model",
            started_after=1000,
            started_before=2000,
        )


if __name__ == "__main__":
    unittest.main()
