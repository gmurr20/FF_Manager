"""Unit tests for ESPNAdapter using standard unittest."""

import unittest
from unittest.mock import MagicMock

from ff_manager.models import Player, SwapDecision
from ff_manager.platforms.espn import ESPNAdapter


class TestESPNAdapter(unittest.TestCase):
    def setUp(self):
        self.mock_session = MagicMock()
        self.mock_session.cookies = MagicMock()
        self.mock_session.headers = MagicMock()

    def test_espn_validate_connection(self):
        adapter = ESPNAdapter(espn_s2="test_s2", swid="{test_swid}")
        self.assertTrue(adapter.validate_connection())

        adapter_empty = ESPNAdapter(espn_s2="", swid="")
        self.assertFalse(adapter_empty.validate_connection())

    def test_espn_get_roster_parsing(self):
        adapter = ESPNAdapter(
            espn_s2="test_s2",
            swid="{1234-SWID}",
            year=2024,
            session=self.mock_session,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "settings": {"name": "Test ESPN League"},
            "status": {"currentScoringPeriod": 1},
            "teams": [
                {
                    "id": 1,
                    "location": "Boston",
                    "nickname": "Bulldogs",
                    "primaryOwner": "{1234-SWID}",
                    "owners": ["{1234-SWID}"],
                    "roster": {
                        "entries": [
                            {
                                "lineupSlotId": 0,  # QB
                                "playerPoolEntry": {
                                    "locked": False,
                                    "player": {
                                        "id": 3139477,
                                        "fullName": "Patrick Mahomes",
                                        "defaultPositionId": 1,  # QB
                                        "eligibleSlots": [0, 7, 20],
                                        "injuryStatus": "ACTIVE",
                                        "proTeamId": 12,
                                        "stats": [
                                            {
                                                "scoringPeriodId": 1,
                                                "statSourceId": 1,  # Projected
                                                "appliedTotal": 22.4,
                                            }
                                        ],
                                    },
                                },
                            },
                            {
                                "lineupSlotId": 20,  # BE
                                "playerPoolEntry": {
                                    "locked": False,
                                    "player": {
                                        "id": 4040715,
                                        "fullName": "Bench RB",
                                        "defaultPositionId": 2,  # RB
                                        "eligibleSlots": [2, 3, 23, 20],
                                        "injuryStatus": "ACTIVE",
                                        "proTeamId": 20,
                                        "stats": [
                                            {
                                                "scoringPeriodId": 1,
                                                "statSourceId": 1,
                                                "appliedTotal": 11.2,
                                            }
                                        ],
                                    },
                                },
                            },
                        ]
                    },
                }
            ],
        }
        self.mock_session.get.return_value = mock_resp

        roster = adapter.get_roster(league_id="123456", team_id="1")

        self.assertEqual(roster.league_name, "Test ESPN League")
        self.assertEqual(roster.team_name, "Boston Bulldogs")
        self.assertEqual(len(roster.players), 2)

        qb = roster.players[0]
        self.assertEqual(qb.name, "Patrick Mahomes")
        self.assertEqual(qb.position, "QB")
        self.assertEqual(qb.lineup_slot, "QB")
        self.assertEqual(qb.projected_points, 22.4)
        self.assertTrue(qb.is_starter)

        bench = roster.players[1]
        self.assertEqual(bench.name, "Bench RB")
        self.assertEqual(bench.lineup_slot, "BE")
        self.assertTrue(bench.is_bench)
        self.assertEqual(bench.projected_points, 11.2)

    def test_espn_execute_swap(self):
        adapter = ESPNAdapter(
            espn_s2="test_s2",
            swid="{1234-SWID}",
            year=2024,
            session=self.mock_session,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        self.mock_session.post.return_value = mock_resp

        starter = Player("101", "Injured WR", "WR", "WR", ["WR", "FLEX"], "OUT", 0.0)
        replacement = Player("202", "Healthy WR", "WR", "BE", ["WR", "FLEX", "BE"], "ACTIVE", 12.5)
        swap = SwapDecision(starter=starter, replacement=replacement, slot="WR", reason="Injury: OUT")

        success = adapter.execute_swap(league_id="123456", team_id="1", swap=swap)

        self.assertTrue(success)
        self.mock_session.post.assert_called_once()
        call_args = self.mock_session.post.call_args
        self.assertIn("transactions", call_args[0][0])
        payload = call_args[1]["json"]
        self.assertEqual(payload["executionType"], "EXECUTE")
        self.assertEqual(len(payload["items"]), 2)
        # Verify replacement moved from 20 (BE) to 4 (WR)
        self.assertEqual(payload["items"][0]["playerId"], 202)
        self.assertEqual(payload["items"][0]["fromLineupSlotId"], 20)
        self.assertEqual(payload["items"][0]["toLineupSlotId"], 4)
        # Verify starter moved from 4 (WR) to 20 (BE)
        self.assertEqual(payload["items"][1]["playerId"], 101)
        self.assertEqual(payload["items"][1]["fromLineupSlotId"], 4)
        self.assertEqual(payload["items"][1]["toLineupSlotId"], 20)


if __name__ == "__main__":
    unittest.main()
