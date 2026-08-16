"""Unit tests for SleeperAdapter using standard unittest."""

import unittest
from unittest.mock import MagicMock

from ff_manager.models import Player, SwapDecision
from ff_manager.platforms.sleeper import SleeperAdapter


class TestSleeperAdapter(unittest.TestCase):
    def setUp(self):
        self.mock_session = MagicMock()

    def test_sleeper_validate_connection(self):
        adapter = SleeperAdapter(
            auth_token="test_token",
            user_id="12345",
            session=self.mock_session,
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        self.mock_session.get.return_value = mock_resp

        self.assertTrue(adapter.validate_connection())

    def test_sleeper_resolve_username_to_user_id(self):
        adapter = SleeperAdapter(
            auth_token="test_token",
            user_id="Gmurr20",
            session=self.mock_session,
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"user_id": "724299076824264704", "username": "gmurr20"}
        self.mock_session.get.return_value = mock_resp

        resolved = adapter._resolve_user_id()
        self.assertEqual(resolved, "724299076824264704")

    def test_sleeper_get_roster_parsing(self):
        adapter = SleeperAdapter(
            auth_token="test_token",
            user_id="user_123",
            year=2024,
            session=self.mock_session,
        )

        adapter.set_players_metadata(
            {
                "4046": {
                    "player_id": "4046",
                    "full_name": "Patrick Mahomes",
                    "position": "QB",
                    "fantasy_positions": ["QB"],
                    "injury_status": None,
                    "team": "KC",
                },
                "6797": {
                    "player_id": "6797",
                    "full_name": "Justin Jefferson",
                    "position": "WR",
                    "fantasy_positions": ["WR"],
                    "injury_status": "OUT",
                    "team": "MIN",
                },
                "7564": {
                    "player_id": "7564",
                    "full_name": "Bench WR Candidate",
                    "position": "WR",
                    "fantasy_positions": ["WR"],
                    "injury_status": None,
                    "team": "DET",
                },
            }
        )

        def fake_get(url, *args, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if url.endswith("/league/league_999"):
                resp.json.return_value = {
                    "name": "My Sleeper League",
                    "roster_positions": ["QB", "WR", "BN", "BN"],
                }
            elif url.endswith("/league/league_999/rosters"):
                resp.json.return_value = [
                    {
                        "roster_id": 1,
                        "owner_id": "user_123",
                        "starters": ["4046", "6797"],
                        "players": ["4046", "6797", "7564"],
                        "reserve": [],
                    }
                ]
            elif url.endswith("/league/league_999/users"):
                resp.json.return_value = [
                    {"user_id": "user_123", "display_name": "Gridiron King"}
                ]
            elif "/matchups/" in url:
                resp.json.return_value = [
                    {
                        "roster_id": 1,
                        "players_points": {"4046": 21.0, "6797": 0.0, "7564": 12.8},
                    }
                ]
            elif "/state/nfl" in url:
                resp.json.return_value = {"week": 1, "season": "2024"}
            else:
                resp.json.return_value = {}
            return resp

        self.mock_session.get.side_effect = fake_get

        roster = adapter.get_roster(league_id="league_999")

        self.assertEqual(roster.league_name, "My Sleeper League")
        self.assertEqual(roster.team_name, "Gridiron King")
        self.assertEqual(len(roster.players), 3)

        starters = roster.starters
        self.assertEqual(len(starters), 2)
        self.assertEqual(starters[0].name, "Patrick Mahomes")
        self.assertEqual(starters[0].lineup_slot, "QB")
        self.assertEqual(starters[0].projected_points, 21.0)

        self.assertEqual(starters[1].name, "Justin Jefferson")
        self.assertEqual(starters[1].lineup_slot, "WR")
        self.assertTrue(starters[1].is_unhealthy)  # OUT

        bench = roster.bench
        self.assertEqual(len(bench), 1)
        self.assertEqual(bench[0].name, "Bench WR Candidate")
        self.assertEqual(bench[0].lineup_slot, "BE")
        self.assertEqual(bench[0].projected_points, 12.8)

    def test_sleeper_execute_swap_graphql(self):
        adapter = SleeperAdapter(
            auth_token="test_jwt_token",
            user_id="user_123",
            year=2024,
            session=self.mock_session,
        )

        def fake_get(url, *args, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if url.endswith("/rosters"):
                resp.json.return_value = [
                    {
                        "roster_id": 1,
                        "starters": ["4046", "6797"],
                        "players": ["4046", "6797", "7564"],
                    }
                ]
            return resp

        self.mock_session.get.side_effect = fake_get

        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {
            "data": {
                "matchup_res": {
                    "roster_id": 1,
                    "starters": ["4046", "7564"],
                },
                "roster_res": {
                    "roster_id": 1,
                    "starters": ["4046", "7564"],
                },
            }
        }
        self.mock_session.post.return_value = mock_post_resp

        starter = Player("6797", "Justin Jefferson", "WR", "WR", ["WR"], "OUT", 0.0)
        replacement = Player("7564", "Bench WR", "WR", "BE", ["WR", "BE"], "ACTIVE", 12.8)
        swap = SwapDecision(starter=starter, replacement=replacement, slot="WR", reason="Injury: OUT")

        success = adapter.execute_swap(league_id="league_999", team_id="1", swap=swap)

        self.assertTrue(success)
        self.mock_session.post.assert_called_once()
        call_args = self.mock_session.post.call_args
        self.assertIn("graphql", call_args[0][0])
        payload = call_args[1]["json"]
        self.assertIn("roster_update_starters", payload["query"])
        self.assertIn('"4046", "7564"', payload["query"])
        self.assertEqual(call_args[1]["headers"]["authorization"], "test_jwt_token")


if __name__ == "__main__":
    unittest.main()
