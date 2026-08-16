"""Platform-agnostic lineup management and swap evaluation logic."""

import logging
from typing import List, Optional, Set

from ff_manager.interfaces import FantasyPlatformClient
from ff_manager.models import ActionResult, Player, Roster, SwapDecision

logger = logging.getLogger(__name__)


class LineupManager:
    """
    Evaluates fantasy football rosters against health and projection thresholds,
    identifies optimal bench replacements, and coordinates roster swaps.
    """

    def __init__(self, client: FantasyPlatformClient, dry_run: bool = False):
        """
        Initialize the LineupManager.

        Args:
            client: The FantasyPlatformClient implementation (ESPN, Sleeper, etc.).
            dry_run: If True, evaluates decisions without executing mutations on the platform.
        """
        self.client = client
        self.dry_run = dry_run

    def evaluate_and_fix_roster(
        self,
        league_id: str,
        team_id: Optional[str] = None,
    ) -> List[ActionResult]:
        """
        Evaluate a team's roster, find unhealthy starters, and execute replacements.

        Args:
            league_id: Platform league ID.
            team_id: Platform team/roster ID (optional, defaults to user's team).

        Returns:
            List of ActionResults detailing all actions or warnings.
        """
        results: List[ActionResult] = []

        try:
            roster = self.client.get_roster(league_id=league_id, team_id=team_id)
        except Exception as e:
            logger.error(
                f"[{self.client.platform_name}] Failed to fetch roster for league {league_id}: {e}",
                exc_info=True,
            )
            return [
                ActionResult(
                    league_id=league_id,
                    league_name="Unknown",
                    platform=self.client.platform_name,
                    team_id=team_id or "Unknown",
                    team_name="Unknown",
                    status="FAILED",
                    message=f"Failed to fetch roster: {e}",
                    error=str(e),
                )
            ]

        # Check if team has drafted any players yet
        actual_players = [p for p in roster.players if not p.is_empty]
        if not actual_players:
            logger.info(
                f"[{roster.platform}] League '{roster.league_name}' (Team: '{roster.team_name}') "
                f"has no drafted players yet (pre-draft status). Skipping lineup evaluation."
            )
            return [
                ActionResult(
                    league_id=roster.league_id,
                    league_name=roster.league_name,
                    platform=roster.platform,
                    team_id=roster.team_id,
                    team_name=roster.team_name,
                    status="SKIPPED",
                    message="Team has not drafted yet (pre-draft status).",
                )
            ]

        has_projections = roster.has_active_projections
        if not has_projections:
            logger.info(
                f"[{roster.platform}] Projections are not yet published for league '{roster.league_name}'. "
                f"Evaluating rosters strictly by injury status."
            )

        logger.info(
            f"[{roster.platform}] Evaluating roster for '{roster.team_name}' in league '{roster.league_name}' "
            f"({len(roster.starters)} starters, {len(roster.bench)} bench)"
        )

        # Track used bench player IDs during multi-swap processing to prevent collisions
        claimed_bench_ids: Set[str] = set()

        unhealthy_starters: List[Player] = []
        for starter in roster.starters:
            if starter.is_unhealthy_for_roster(has_projections=has_projections):
                unhealthy_starters.append(starter)

        if not unhealthy_starters:
            logger.info(f"[{roster.platform}] All starters are healthy for '{roster.team_name}'.")
            return [
                ActionResult(
                    league_id=roster.league_id,
                    league_name=roster.league_name,
                    platform=roster.platform,
                    team_id=roster.team_id,
                    team_name=roster.team_name,
                    status="NO_ACTION_NEEDED",
                    message="All starters are healthy and scheduled to play.",
                )
            ]

        for starter in unhealthy_starters:
            # Check if starter's game is locked
            if starter.is_locked:
                reason = self._get_unhealthy_reason(starter, has_projections=has_projections)
                logger.warning(
                    f"[{roster.platform}] Starter {starter.name} is {reason}, but their game is locked. Cannot swap."
                )
                results.append(
                    ActionResult(
                        league_id=roster.league_id,
                        league_name=roster.league_name,
                        platform=roster.platform,
                        team_id=roster.team_id,
                        team_name=roster.team_name,
                        status="SKIPPED",
                        message=f"Starter {starter.name} ({starter.position}) is locked ({reason}).",
                    )
                )
                continue

            # Find best eligible replacement on the bench
            replacement = self.find_best_bench_replacement(
                starter=starter,
                bench_players=roster.bench,
                claimed_player_ids=claimed_bench_ids,
                has_projections=has_projections,
            )

            reason = self._get_unhealthy_reason(starter, has_projections=has_projections)

            if not replacement:
                logger.warning(
                    f"[{roster.platform}] No eligible, healthy, unlocked bench replacement found for {starter.name} ({starter.lineup_slot})."
                )
                results.append(
                    ActionResult(
                        league_id=roster.league_id,
                        league_name=roster.league_name,
                        platform=roster.platform,
                        team_id=roster.team_id,
                        team_name=roster.team_name,
                        status="NO_REPLACEMENT",
                        message=(
                            f"No valid bench replacement found for {starter.name} "
                            f"({starter.position}, Slot: {starter.lineup_slot}, {reason})."
                        ),
                    )
                )
                continue

            decision = SwapDecision(
                starter=starter,
                replacement=replacement,
                slot=starter.lineup_slot,
                reason=reason,
            )
            claimed_bench_ids.add(replacement.player_id)

            if self.dry_run:
                logger.info(f"[{roster.platform}] [DRY-RUN] Would execute: {decision}")
                results.append(
                    ActionResult(
                        league_id=roster.league_id,
                        league_name=roster.league_name,
                        platform=roster.platform,
                        team_id=roster.team_id,
                        team_name=roster.team_name,
                        status="SUCCESS (DRY-RUN)",
                        message=f"[DRY-RUN] {decision}",
                        swap=decision,
                    )
                )
            else:
                try:
                    logger.info(f"[{roster.platform}] Executing: {decision}")
                    success = self.client.execute_swap(
                        league_id=roster.league_id,
                        team_id=roster.team_id,
                        swap=decision,
                    )
                    if success:
                        results.append(
                            ActionResult(
                                league_id=roster.league_id,
                                league_name=roster.league_name,
                                platform=roster.platform,
                                team_id=roster.team_id,
                                team_name=roster.team_name,
                                status="SUCCESS",
                                message=f"{decision}",
                                swap=decision,
                            )
                        )
                    else:
                        error_detail = (
                            getattr(self.client, "last_error", None)
                            or "API swap rejected by platform."
                        )
                        results.append(
                            ActionResult(
                                league_id=roster.league_id,
                                league_name=roster.league_name,
                                platform=roster.platform,
                                team_id=roster.team_id,
                                team_name=roster.team_name,
                                status="FAILED",
                                message=f"Platform returned failure executing swap for {starter.name}: {error_detail}",
                                swap=decision,
                                error=error_detail,
                            )
                        )
                except Exception as e:
                    logger.error(
                        f"[{roster.platform}] Error executing swap for {starter.name}: {e}",
                        exc_info=True,
                    )
                    results.append(
                        ActionResult(
                            league_id=roster.league_id,
                            league_name=roster.league_name,
                            platform=roster.platform,
                            team_id=roster.team_id,
                            team_name=roster.team_name,
                            status="FAILED",
                            message=f"Exception executing swap for {starter.name}: {e}",
                            swap=decision,
                            error=str(e),
                        )
                    )

        return results

    def find_best_bench_replacement(
        self,
        starter: Player,
        bench_players: List[Player],
        claimed_player_ids: Set[str],
        has_projections: bool = True,
    ) -> Optional[Player]:
        """
        Identify the highest-projected eligible, unlocked, and healthy bench player
        to replace a given starter.
        """
        eligible_candidates: List[Player] = []

        for candidate in bench_players:
            if candidate.is_empty:
                continue
            if candidate.player_id in claimed_player_ids:
                continue
            if candidate.is_locked:
                continue
            if candidate.is_unhealthy_for_roster(has_projections=has_projections):
                continue
            if not candidate.can_fill_slot(starter.lineup_slot):
                continue

            eligible_candidates.append(candidate)

        if not eligible_candidates:
            return None

        # Sort descending by projected points; tiebreak by player name for determinism
        eligible_candidates.sort(key=lambda p: (p.projected_points, p.name), reverse=True)
        return eligible_candidates[0]

    def _get_unhealthy_reason(self, player: Player, has_projections: bool = True) -> str:
        """Helper to generate a human-readable explanation of why a starter is unhealthy or empty."""
        if player.is_empty:
            return "Empty starting slot"
        reasons = []
        if player.has_unhealthy_injury_status:
            reasons.append(f"Injury: {player.injury_status.strip().upper()}")
        if has_projections and player.projected_points < 1.0:
            reasons.append(f"Projection: {player.projected_points:.1f} pts (< 1.0)")
        return ", ".join(reasons) if reasons else "Inactive"
