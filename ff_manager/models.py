"""Unified domain models for fantasy football lineup management."""

from dataclasses import dataclass, field
from typing import List, Optional, Set


UNHEALTHY_INJURY_STATUSES: Set[str] = {
    "OUT",
    "DOUBTFUL",
    "IR",
    "PUP",
    "SUSPENDED",
    "INACTIVE",
    "O",
    "D",
    "IR-R",
    "EMPTY",
}

BENCH_SLOT_NAMES: Set[str] = {"BE", "BENCH", "BN"}
IR_SLOT_NAMES: Set[str] = {"IR", "PUP", "SUS"}


@dataclass
class Player:
    """Standardized representation of a fantasy football player."""

    player_id: str
    name: str
    position: str  # e.g., "QB", "RB", "WR", "TE", "K", "DEF", "D/ST"
    lineup_slot: str  # e.g., "QB", "RB", "WR", "TE", "FLEX", "BE", "IR"
    eligible_slots: List[str] = field(default_factory=list)
    injury_status: Optional[str] = None  # e.g., "ACTIVE", "QUESTIONABLE", "DOUBTFUL", "OUT", "IR", "EMPTY"
    projected_points: float = 0.0
    is_locked: bool = False  # True if player's game has kicked off
    team: Optional[str] = None  # NFL team, e.g. "KC"
    opponent: Optional[str] = None

    @property
    def is_empty(self) -> bool:
        """Return True if this represents an unfilled/empty lineup slot placeholder."""
        return (
            self.player_id in ("0", "", None)
            or (self.injury_status and self.injury_status.strip().upper() == "EMPTY")
            or self.name.startswith("[Empty")
        )

    @property
    def is_starter(self) -> bool:
        """Return True if player is currently in an active starting slot."""
        return not self.is_bench and not self.is_ir

    @property
    def is_bench(self) -> bool:
        """Return True if player is on the bench."""
        return self.lineup_slot.upper() in BENCH_SLOT_NAMES

    @property
    def is_ir(self) -> bool:
        """Return True if player is in an IR/PUP slot."""
        return self.lineup_slot.upper() in IR_SLOT_NAMES

    @property
    def has_unhealthy_injury_status(self) -> bool:
        """Return True if player's injury status is OUT, DOUBTFUL, IR, EMPTY, etc."""
        if self.is_empty:
            return True
        if self.injury_status:
            normalized_status = self.injury_status.strip().upper()
            return normalized_status in UNHEALTHY_INJURY_STATUSES
        return False

    @property
    def is_unhealthy(self) -> bool:
        """
        Return True if player meets swap-out criteria:
        1. Slot is empty
        2. Condition A: projected_points < 1.0
        3. Condition B: injury_status is OUT, DOUBTFUL, IR, etc.
        """
        if self.is_empty:
            return True
        return self.has_unhealthy_injury_status or self.projected_points < 1.0

    def is_unhealthy_for_roster(self, has_projections: bool = True) -> bool:
        """
        Evaluate health considering whether week projections are available.
        If projections are unavailable (e.g. off-season), empty slots and injuries are evaluated.
        """
        if self.is_empty:
            return True
        if has_projections:
            return self.is_unhealthy
        return self.has_unhealthy_injury_status

    def can_fill_slot(self, slot_name: str) -> bool:
        """Check if this player is eligible to fill a given lineup slot."""
        slot_upper = slot_name.upper()
        if slot_upper in [s.upper() for s in self.eligible_slots]:
            return True

        # Position direct match fallback
        if self.position.upper() == slot_upper:
            return True

        # Standard FLEX position mapping fallback
        if slot_upper in ("FLEX", "W/R/T", "RB/WR/TE") and self.position.upper() in ("RB", "WR", "TE"):
            return True
        if slot_upper in ("SUPER_FLEX", "OP", "Q/W/R/T") and self.position.upper() in ("QB", "RB", "WR", "TE"):
            return True
        if slot_upper in ("WR/TE", "W/T") and self.position.upper() in ("WR", "TE"):
            return True
        if slot_upper in ("RB/WR", "W/R") and self.position.upper() in ("RB", "WR"):
            return True

        return False


@dataclass
class Roster:
    """Standardized representation of a fantasy football team roster."""

    league_id: str
    league_name: str
    team_id: str
    team_name: str
    platform: str
    players: List[Player] = field(default_factory=list)

    @property
    def starters(self) -> List[Player]:
        """Return all players in active starting slots (including empty slot placeholders)."""
        return [p for p in self.players if p.is_starter]

    @property
    def bench(self) -> List[Player]:
        """Return all players on the bench."""
        return [p for p in self.players if p.is_bench]

    @property
    def unlocked_bench(self) -> List[Player]:
        """Return bench players whose games have not locked yet."""
        return [p for p in self.bench if not p.is_locked and not p.is_empty]

    @property
    def has_active_projections(self) -> bool:
        """Return True if at least one player on the roster has a projection > 0."""
        return any(p.projected_points > 0.0 for p in self.players)


@dataclass
class SwapDecision:
    """Details of a proposed or executed roster swap."""

    starter: Player
    replacement: Player
    slot: str
    reason: str

    def __str__(self) -> str:
        if self.starter.is_empty:
            return (
                f"Filled empty {self.slot} slot with "
                f"[{self.replacement.name} ({self.replacement.position}) - Proj: {self.replacement.projected_points:.1f}]"
            )
        return (
            f"Swap OUT [{self.starter.name} ({self.starter.position}) - {self.reason}] "
            f"for [{self.replacement.name} ({self.replacement.position}) - Proj: {self.replacement.projected_points:.1f}] "
            f"in slot {self.slot}"
        )


@dataclass
class ActionResult:
    """Log result of an evaluation or swap action."""

    league_id: str
    league_name: str
    platform: str
    team_id: str
    team_name: str
    status: str  # "SUCCESS", "SKIPPED", "NO_REPLACEMENT", "FAILED", "NO_ACTION_NEEDED"
    message: str
    swap: Optional[SwapDecision] = None
    error: Optional[str] = None
