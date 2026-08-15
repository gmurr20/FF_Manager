"""Unit tests for LineupManager core swap logic using unittest."""

import unittest
from typing import List

from ff_manager.core.lineup_manager import LineupManager
from ff_manager.interfaces import FantasyPlatformClient
from ff_manager.models import Player, Roster, SwapDecision


class MockFantasyClient(FantasyPlatformClient):
    """Mock implementation of FantasyPlatformClient for unit testing."""

    def __init__(self, roster: Roster):
        self._roster = roster
        self.swaps_executed: List[SwapDecision] = []

    @property
    def platform_name(self) -> str:
        return "MockPlatform"

    def get_user_leagues(self):
        return [{"league_id": self._roster.league_id, "league_name": self._roster.league_name}]

    def get_roster(self, league_id: str, team_id=None) -> Roster:
        return self._roster

    def execute_swap(self, league_id: str, team_id: str, swap: SwapDecision) -> bool:
        self.swaps_executed.append(swap)
        return True

    def validate_connection(self) -> bool:
        return True


class TestLineupManager(unittest.TestCase):
    def test_healthy_lineup_no_swaps(self):
        """Test that a fully healthy roster with positive projections requires no actions."""
        players = [
            Player("1", "Patrick Mahomes", "QB", "QB", ["QB"], "ACTIVE", 21.5, is_locked=False),
            Player("2", "Christian McCaffrey", "RB", "RB", ["RB", "FLEX"], "ACTIVE", 18.2, is_locked=False),
            Player("3", "Justin Jefferson", "WR", "WR", ["WR", "FLEX"], "ACTIVE", 16.0, is_locked=False),
            Player("4", "Travis Kelce", "TE", "TE", ["TE", "FLEX"], "ACTIVE", 12.0, is_locked=False),
            Player("5", "Bench QB", "QB", "BE", ["QB", "BE"], "ACTIVE", 15.0, is_locked=False),
            Player("6", "Bench RB", "RB", "BE", ["RB", "FLEX", "BE"], "ACTIVE", 10.0, is_locked=False),
        ]
        roster = Roster("101", "League 1", "T1", "My Team", "MockPlatform", players)
        client = MockFantasyClient(roster)
        manager = LineupManager(client=client, dry_run=False)

        results = manager.evaluate_and_fix_roster("101", "T1")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "NO_ACTION_NEEDED")
        self.assertEqual(len(client.swaps_executed), 0)

    def test_injured_starter_swapped_with_highest_projected_bench(self):
        """Test that an OUT starter is replaced with the highest projected eligible bench player."""
        players = [
            # Injured WR starter
            Player("1", "Davante Adams", "WR", "WR", ["WR", "FLEX"], "OUT", 0.0, is_locked=False),
            # Other healthy starter
            Player("2", "Saquon Barkley", "RB", "RB", ["RB", "FLEX"], "ACTIVE", 15.0, is_locked=False),
            # Bench candidates
            Player("3", "Bench WR Lower", "WR", "BE", ["WR", "FLEX", "BE"], "ACTIVE", 8.5, is_locked=False),
            Player("4", "Bench WR Higher", "WR", "BE", ["WR", "FLEX", "BE"], "ACTIVE", 13.2, is_locked=False),
            Player("5", "Bench QB", "QB", "BE", ["QB", "BE"], "ACTIVE", 18.0, is_locked=False),
        ]
        roster = Roster("101", "League 1", "T1", "My Team", "MockPlatform", players)
        client = MockFantasyClient(roster)
        manager = LineupManager(client=client, dry_run=False)

        results = manager.evaluate_and_fix_roster("101", "T1")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "SUCCESS")
        self.assertEqual(len(client.swaps_executed), 1)
        swap = client.swaps_executed[0]
        self.assertEqual(swap.starter.player_id, "1")
        self.assertEqual(swap.replacement.player_id, "4")  # Bench WR Higher (13.2 pts)
        self.assertEqual(swap.slot, "WR")

    def test_low_projection_starter_swapped(self):
        """Test Condition A: starter with < 1.0 projected points is swapped even if status is not explicitly OUT."""
        players = [
            Player("1", "Suspicious Starter", "RB", "RB", ["RB", "FLEX"], "QUESTIONABLE", 0.0, is_locked=False),
            Player("2", "Bench RB", "RB", "BE", ["RB", "FLEX", "BE"], "ACTIVE", 11.4, is_locked=False),
        ]
        roster = Roster("101", "League 1", "T1", "My Team", "MockPlatform", players)
        client = MockFantasyClient(roster)
        manager = LineupManager(client=client, dry_run=False)

        results = manager.evaluate_and_fix_roster("101", "T1")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "SUCCESS")
        self.assertEqual(len(client.swaps_executed), 1)
        self.assertEqual(client.swaps_executed[0].starter.player_id, "1")
        self.assertEqual(client.swaps_executed[0].replacement.player_id, "2")

    def test_locked_starter_cannot_be_swapped(self):
        """Test that a locked starter whose game already started is skipped."""
        players = [
            Player("1", "Late Injured Thursday Starter", "WR", "WR", ["WR"], "OUT", 0.0, is_locked=True),
            Player("2", "Bench WR", "WR", "BE", ["WR", "BE"], "ACTIVE", 14.0, is_locked=False),
        ]
        roster = Roster("101", "League 1", "T1", "My Team", "MockPlatform", players)
        client = MockFantasyClient(roster)
        manager = LineupManager(client=client, dry_run=False)

        results = manager.evaluate_and_fix_roster("101", "T1")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "SKIPPED")
        self.assertIn("locked", results[0].message.lower())
        self.assertEqual(len(client.swaps_executed), 0)

    def test_locked_bench_players_ignored(self):
        """Test that locked bench players are never chosen as replacements."""
        players = [
            Player("1", "Injured WR", "WR", "WR", ["WR", "FLEX"], "OUT", 0.0, is_locked=False),
            # Locked bench player with highest projection
            Player("2", "Locked Stud Bench WR", "WR", "BE", ["WR", "FLEX", "BE"], "ACTIVE", 20.0, is_locked=True),
            # Unlocked bench player with lower projection
            Player("3", "Available Bench WR", "WR", "BE", ["WR", "FLEX", "BE"], "ACTIVE", 9.5, is_locked=False),
        ]
        roster = Roster("101", "League 1", "T1", "My Team", "MockPlatform", players)
        client = MockFantasyClient(roster)
        manager = LineupManager(client=client, dry_run=False)

        results = manager.evaluate_and_fix_roster("101", "T1")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "SUCCESS")
        self.assertEqual(client.swaps_executed[0].replacement.player_id, "3")

    def test_unhealthy_bench_players_ignored(self):
        """Test that bench players who are also OUT or projected 0 are not chosen."""
        players = [
            Player("1", "Starter WR", "WR", "WR", ["WR", "FLEX"], "OUT", 0.0, is_locked=False),
            # Bench WR that is also OUT
            Player("2", "Injured Bench WR", "WR", "BE", ["WR", "FLEX", "BE"], "OUT", 0.0, is_locked=False),
            # Bench WR with 0 projected points
            Player("3", "Zero Proj Bench WR", "WR", "BE", ["WR", "FLEX", "BE"], "ACTIVE", 0.0, is_locked=False),
            # Healthy Bench WR
            Player("4", "Healthy Bench WR", "WR", "BE", ["WR", "FLEX", "BE"], "ACTIVE", 7.0, is_locked=False),
        ]
        roster = Roster("101", "League 1", "T1", "My Team", "MockPlatform", players)
        client = MockFantasyClient(roster)
        manager = LineupManager(client=client, dry_run=False)

        results = manager.evaluate_and_fix_roster("101", "T1")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "SUCCESS")
        self.assertEqual(client.swaps_executed[0].replacement.player_id, "4")

    def test_no_valid_bench_replacement(self):
        """Test reporting when no eligible bench player exists."""
        players = [
            Player("1", "Injured Kicker", "K", "K", ["K"], "OUT", 0.0, is_locked=False),
            Player("2", "Bench RB", "RB", "BE", ["RB", "BE"], "ACTIVE", 12.0, is_locked=False),
        ]
        roster = Roster("101", "League 1", "T1", "My Team", "MockPlatform", players)
        client = MockFantasyClient(roster)
        manager = LineupManager(client=client, dry_run=False)

        results = manager.evaluate_and_fix_roster("101", "T1")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "NO_REPLACEMENT")
        self.assertEqual(len(client.swaps_executed), 0)

    def test_multi_swap_no_bench_collisions(self):
        """Test that two injured starters are replaced by two distinct bench players."""
        players = [
            Player("1", "Starter WR1", "WR", "WR", ["WR", "FLEX"], "OUT", 0.0, is_locked=False),
            Player("2", "Starter WR2", "WR", "WR", ["WR", "FLEX", "BE"], "DOUBTFUL", 0.0, is_locked=False),
            Player("3", "Bench WR A", "WR", "BE", ["WR", "FLEX", "BE"], "ACTIVE", 14.0, is_locked=False),
            Player("4", "Bench WR B", "WR", "BE", ["WR", "FLEX", "BE"], "ACTIVE", 10.0, is_locked=False),
        ]
        roster = Roster("101", "League 1", "T1", "My Team", "MockPlatform", players)
        client = MockFantasyClient(roster)
        manager = LineupManager(client=client, dry_run=False)

        results = manager.evaluate_and_fix_roster("101", "T1")

        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.status == "SUCCESS" for r in results))
        self.assertEqual(len(client.swaps_executed), 2)

        replacements = [s.replacement.player_id for s in client.swaps_executed]
        self.assertEqual(len(set(replacements)), 2)
        self.assertIn("3", replacements)
        self.assertIn("4", replacements)

    def test_flex_slot_replacement(self):
        """Test replacing an injured FLEX starter with the best eligible RB/WR/TE."""
        players = [
            Player("1", "Injured FLEX", "WR", "FLEX", ["WR", "FLEX"], "OUT", 0.0, is_locked=False),
            Player("2", "Bench TE", "TE", "BE", ["TE", "FLEX", "BE"], "ACTIVE", 8.0, is_locked=False),
            Player("3", "Bench RB", "RB", "BE", ["RB", "FLEX", "BE"], "ACTIVE", 15.2, is_locked=False),
        ]
        roster = Roster("101", "League 1", "T1", "My Team", "MockPlatform", players)
        client = MockFantasyClient(roster)
        manager = LineupManager(client=client, dry_run=False)

        results = manager.evaluate_and_fix_roster("101", "T1")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "SUCCESS")
        self.assertEqual(client.swaps_executed[0].replacement.player_id, "3")

    def test_dry_run_mode_does_not_execute_swaps(self):
        """Test that dry_run=True records decisions without calling execute_swap."""
        players = [
            Player("1", "Injured QB", "QB", "QB", ["QB"], "OUT", 0.0, is_locked=False),
            Player("2", "Bench QB", "QB", "BE", ["QB", "BE"], "ACTIVE", 18.0, is_locked=False),
        ]
        roster = Roster("101", "League 1", "T1", "My Team", "MockPlatform", players)
        client = MockFantasyClient(roster)
        manager = LineupManager(client=client, dry_run=True)

        results = manager.evaluate_and_fix_roster("101", "T1")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "SUCCESS (DRY-RUN)")
        self.assertEqual(len(client.swaps_executed), 0)

    def test_unprojected_week_evaluates_only_injury_status(self):
        """Test that when all projections are 0 (e.g. offseason/preseason), healthy starters are not flagged."""
        players = [
            Player("1", "Healthy Starter 1", "QB", "QB", ["QB"], "ACTIVE", 0.0, is_locked=False),
            Player("2", "Healthy Starter 2", "RB", "RB", ["RB", "FLEX"], None, 0.0, is_locked=False),
            Player("3", "Injured Starter", "WR", "WR", ["WR", "FLEX"], "OUT", 0.0, is_locked=False),
            Player("4", "Healthy Bench", "WR", "BE", ["WR", "FLEX", "BE"], "ACTIVE", 0.0, is_locked=False),
        ]
        roster = Roster("101", "League 1", "T1", "My Team", "MockPlatform", players)
        client = MockFantasyClient(roster)
        manager = LineupManager(client=client, dry_run=False)

        results = manager.evaluate_and_fix_roster("101", "T1")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "SUCCESS")
        self.assertEqual(results[0].swap.starter.player_id, "3")
        self.assertEqual(results[0].swap.replacement.player_id, "4")

    def test_empty_starter_slot_filled_from_bench(self):
        """Test that an unfilled/empty starter slot is automatically filled by the best bench player."""
        players = [
            # Empty RB slot placeholder
            Player("0", "[Empty RB]", "RB", "RB", ["RB"], "EMPTY", 0.0, is_locked=False),
            # Bench candidates
            Player("10", "Backup RB 1", "RB", "BE", ["RB", "FLEX", "BE"], "ACTIVE", 9.5, is_locked=False),
            Player("11", "Backup RB 2", "RB", "BE", ["RB", "FLEX", "BE"], "ACTIVE", 14.2, is_locked=False),
        ]
        roster = Roster("101", "League 1", "T1", "My Team", "MockPlatform", players)
        client = MockFantasyClient(roster)
        manager = LineupManager(client=client, dry_run=False)

        results = manager.evaluate_and_fix_roster("101", "T1")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "SUCCESS")
        self.assertEqual(client.swaps_executed[0].replacement.player_id, "11")
        self.assertEqual(client.swaps_executed[0].slot, "RB")
        self.assertIn("Filled empty RB slot", str(client.swaps_executed[0]))


if __name__ == "__main__":
    unittest.main()
