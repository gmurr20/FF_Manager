"""Unit tests for the database notification deduplication module."""

import unittest
from unittest.mock import MagicMock, patch

from ff_manager.db import (
    clear_fingerprint,
    compute_fingerprint,
    get_last_fingerprint,
    get_nfl_week,
    save_fingerprint,
)
from ff_manager.models import ActionResult, Player, SwapDecision


class TestComputeFingerprint(unittest.TestCase):
    def test_no_problems_returns_empty_string(self):
        results = [
            ActionResult(
                league_id="1", league_name="L1", platform="ESPN",
                team_id="T1", team_name="Team 1",
                status="NO_ACTION_NEEDED", message="All healthy",
            ),
        ]
        fp = compute_fingerprint(results, "2026_regular_2")
        self.assertEqual(fp, "")

    def test_problems_produce_fingerprint(self):
        results = [
            ActionResult(
                league_id="1", league_name="L1", platform="Sleeper",
                team_id="T1", team_name="Team 1",
                status="NO_REPLACEMENT",
                message="No valid bench replacement found for [Empty K]",
            ),
        ]
        fp = compute_fingerprint(results, "2026_regular_2")
        self.assertTrue(len(fp) == 64)  # SHA-256 hex digest

    def test_same_results_same_week_same_fingerprint(self):
        results = [
            ActionResult(
                league_id="1", league_name="L1", platform="Sleeper",
                team_id="T1", team_name="Team 1",
                status="NO_REPLACEMENT",
                message="No valid bench replacement found for [Empty K]",
            ),
        ]
        fp1 = compute_fingerprint(results, "2026_regular_2")
        fp2 = compute_fingerprint(results, "2026_regular_2")
        self.assertEqual(fp1, fp2)

    def test_different_week_different_fingerprint(self):
        results = [
            ActionResult(
                league_id="1", league_name="L1", platform="Sleeper",
                team_id="T1", team_name="Team 1",
                status="NO_REPLACEMENT",
                message="No valid bench replacement found for [Empty K]",
            ),
        ]
        fp_week2 = compute_fingerprint(results, "2026_regular_2")
        fp_week3 = compute_fingerprint(results, "2026_regular_3")
        self.assertNotEqual(fp_week2, fp_week3)

    def test_different_problems_different_fingerprint(self):
        results_a = [
            ActionResult(
                league_id="1", league_name="L1", platform="Sleeper",
                team_id="T1", team_name="Team 1",
                status="NO_REPLACEMENT",
                message="No valid bench replacement found for [Empty K]",
            ),
        ]
        results_b = [
            ActionResult(
                league_id="1", league_name="L1", platform="ESPN",
                team_id="T1", team_name="Team 1",
                status="FAILED",
                message="Auth error", error="Token expired",
            ),
        ]
        fp_a = compute_fingerprint(results_a, "2026_regular_2")
        fp_b = compute_fingerprint(results_b, "2026_regular_2")
        self.assertNotEqual(fp_a, fp_b)

    def test_swap_results_included_in_fingerprint(self):
        swap = SwapDecision(
            starter=Player("1", "P1", "WR", "WR", ["WR"], "OUT", 0.0),
            replacement=Player("2", "P2", "WR", "BE", ["WR"], "ACTIVE", 12.0),
            slot="WR", reason="Injury: OUT",
        )
        results = [
            ActionResult(
                league_id="1", league_name="L1", platform="Sleeper",
                team_id="T1", team_name="Team 1",
                status="SUCCESS", message="Swapped", swap=swap,
            ),
        ]
        fp = compute_fingerprint(results, "2026_regular_2")
        self.assertTrue(len(fp) == 64)

    def test_order_independent(self):
        """Fingerprint should be the same regardless of result ordering."""
        r1 = ActionResult(
            league_id="1", league_name="L1", platform="ESPN",
            team_id="T1", team_name="Team 1",
            status="FAILED", message="Auth error", error="Token expired",
        )
        r2 = ActionResult(
            league_id="2", league_name="L2", platform="Sleeper",
            team_id="T2", team_name="Team 2",
            status="NO_REPLACEMENT",
            message="No valid bench replacement found for [Empty K]",
        )
        fp_ab = compute_fingerprint([r1, r2], "2026_regular_2")
        fp_ba = compute_fingerprint([r2, r1], "2026_regular_2")
        self.assertEqual(fp_ab, fp_ba)


class TestDatabaseOperations(unittest.TestCase):
    def _make_mock_conn(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return conn, cursor

    def test_get_last_fingerprint_found(self):
        conn, cursor = self._make_mock_conn()
        cursor.fetchone.return_value = ("abc123",)
        result = get_last_fingerprint(conn, "default")
        self.assertEqual(result, "abc123")
        cursor.execute.assert_called_once()

    def test_get_last_fingerprint_not_found(self):
        conn, cursor = self._make_mock_conn()
        cursor.fetchone.return_value = None
        result = get_last_fingerprint(conn, "default")
        self.assertIsNone(result)

    def test_save_fingerprint_calls_upsert(self):
        conn, cursor = self._make_mock_conn()
        save_fingerprint(conn, "default", "abc123")
        cursor.execute.assert_called_once()
        conn.commit.assert_called_once()
        # Verify the SQL contains ON CONFLICT (upsert)
        sql = cursor.execute.call_args[0][0]
        self.assertIn("ON CONFLICT", sql)

    def test_clear_fingerprint_calls_delete(self):
        conn, cursor = self._make_mock_conn()
        clear_fingerprint(conn, "default")
        cursor.execute.assert_called_once()
        conn.commit.assert_called_once()
        sql = cursor.execute.call_args[0][0]
        self.assertIn("DELETE", sql)


class TestGetNflWeek(unittest.TestCase):
    @patch("requests.get")
    def test_get_nfl_week_success(self, mock_get):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"season": "2026", "season_type": "regular", "week": 3}
        mock_get.return_value = mock_resp

        week_str = get_nfl_week(timeout=15, max_retries=3)
        self.assertEqual(week_str, "2026_regular_3")
        mock_get.assert_called_once()

    @patch("time.sleep")
    @patch("requests.get")
    def test_get_nfl_week_retries_on_timeout_and_succeeds(self, mock_get, mock_sleep):
        from requests.exceptions import ReadTimeout
        ok_resp = MagicMock(status_code=200)
        ok_resp.json.return_value = {"season": "2026", "season_type": "regular", "week": 3}
        mock_get.side_effect = [ReadTimeout("Read timed out"), ok_resp]

        week_str = get_nfl_week(timeout=15, max_retries=3, backoff_factor=0.01)
        self.assertEqual(week_str, "2026_regular_3")
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once()

    @patch("time.sleep")
    @patch("requests.get")
    def test_get_nfl_week_falls_back_to_unknown_after_max_retries(self, mock_get, mock_sleep):
        from requests.exceptions import ReadTimeout
        mock_get.side_effect = ReadTimeout("Read timed out")

        week_str = get_nfl_week(timeout=15, max_retries=3, backoff_factor=0.01)
        self.assertEqual(week_str, "unknown")
        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
