"""ESPN Fantasy Football Platform Adapter."""

import datetime
import logging
from typing import Any, Dict, List, Optional

from ff_manager.interfaces import FantasyPlatformClient
from ff_manager.models import Player, Roster, SwapDecision

try:
    import requests
except ImportError:
    requests = None

logger = logging.getLogger(__name__)

# ESPN Lineup Slot ID constants
ESPN_SLOT_ID_TO_NAME: Dict[int, str] = {
    0: "QB",
    1: "TQB",
    2: "RB",
    3: "RB/WR",
    4: "WR",
    5: "WR/TE",
    6: "TE",
    7: "OP",
    8: "DT",
    9: "DE",
    10: "LB",
    11: "DL",
    12: "CB",
    13: "S",
    14: "DB",
    15: "DP",
    16: "D/ST",
    17: "K",
    18: "P",
    19: "HC",
    20: "BE",
    21: "IR",
    22: "UNKNOWN",
    23: "FLEX",
}

ESPN_SLOT_NAME_TO_ID: Dict[str, int] = {
    "QB": 0,
    "TQB": 1,
    "RB": 2,
    "RB/WR": 3,
    "WR": 4,
    "WR/TE": 5,
    "TE": 6,
    "OP": 7,
    "D/ST": 16,
    "DEF": 16,
    "K": 17,
    "BE": 20,
    "BENCH": 20,
    "BN": 20,
    "IR": 21,
    "FLEX": 23,
    "W/R/T": 23,
}

ESPN_POSITION_MAP: Dict[int, str] = {
    1: "QB",
    2: "RB",
    3: "WR",
    4: "TE",
    5: "K",
    6: "P",
    16: "D/ST",
}

ESPN_API_HOSTS = [
    "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl",
    "https://fantasy.espn.com/apis/v3/games/ffl",
]


class ESPNAdapter(FantasyPlatformClient):
    """Adapter for interacting with ESPN Fantasy Football API."""

    def __init__(
        self,
        espn_s2: str,
        swid: str,
        year: Optional[int] = None,
        session: Optional[Any] = None,
    ):
        """
        Initialize the ESPN adapter.

        Args:
            espn_s2: ESPN_S2 cookie value.
            swid: SWID cookie value (e.g. '{12345-ABCD-...}').
            year: NFL season year (defaults to current year).
            session: Optional requests.Session instance for testing/mocking.
        """
        self.espn_s2 = espn_s2.strip('"').strip("'") if espn_s2 else ""
        raw_swid = swid.strip('"').strip("'") if swid else ""
        if raw_swid and not raw_swid.startswith("{"):
            raw_swid = "{" + raw_swid
        if raw_swid and not raw_swid.endswith("}"):
            raw_swid = raw_swid + "}"
        self.swid = raw_swid

        self.year = year or datetime.date.today().year
        if session is not None:
            self.session = session
        elif requests is not None:
            self.session = requests.Session()
        else:
            self.session = None

        if self.session is not None:
            self._setup_session()

    @property
    def platform_name(self) -> str:
        return "ESPN"

    def _setup_session(self) -> None:
        """Configure session cookies and headers for ESPN API requests."""
        if hasattr(self.session, "cookies") and hasattr(self.session.cookies, "set"):
            self.session.cookies.set("espn_s2", self.espn_s2, domain=".espn.com")
            self.session.cookies.set("SWID", self.swid, domain=".espn.com")
            self.session.cookies.set("espn_s2", self.espn_s2)
            self.session.cookies.set("SWID", self.swid)
        if hasattr(self.session, "headers") and hasattr(self.session.headers, "update"):
            self.session.headers.update(
                {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                    "X-Fantasy-Platform": "kona-api-web",
                    "X-Fantasy-Source": "kona",
                    "Cookie": f"espn_s2={self.espn_s2}; SWID={self.swid}",
                }
            )

    def validate_connection(self) -> bool:
        """Validate ESPN credentials."""
        return bool(self.espn_s2 and self.swid)

    def get_user_leagues(self) -> List[Dict[str, Any]]:
        """Fetch leagues accessible by this user."""
        return []

    def _fetch_league_data(
        self,
        league_id: str,
        views: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Fetch league data from ESPN with fallback across season years and hosts.
        """
        if self.session is None:
            raise RuntimeError("HTTP session not initialized (requests library required).")

        params = {}
        if views:
            params["view"] = views

        candidate_years = [self.year]
        for y in [datetime.date.today().year, 2024, 2025, 2026]:
            if y not in candidate_years:
                candidate_years.append(y)

        last_error = None
        for yr in candidate_years:
            for host in ESPN_API_HOSTS:
                url = f"{host}/seasons/{yr}/segments/0/leagues/{league_id}"
                try:
                    resp = self.session.get(url, params=params, timeout=10)
                    if resp.status_code in (401, 403, 404):
                        last_error = f"HTTP {resp.status_code} from {url}"
                        continue
                    data = resp.json()
                    if isinstance(data, dict):
                        self.year = yr
                        return data
                except Exception as e:
                    last_error = str(e)
                    continue

        raise ValueError(
            f"Could not load ESPN league data for league {league_id}. "
            f"Please verify your ESPN_S2 cookie, SWID, and league ID. Details: {last_error}"
        )

    def get_roster(self, league_id: str, team_id: Optional[str] = None) -> Roster:
        """
        Fetch and normalize the roster for the target ESPN team.
        """
        data = self._fetch_league_data(
            league_id=league_id,
            views=["mRoster", "mTeam", "mSettings", "mMatchupScore", "mStatus"],
        )

        league_name = data.get("settings", {}).get("name", f"ESPN League {league_id}")
        current_scoring_period = data.get("status", {}).get("currentScoringPeriod", 1)

        # Identify target team
        teams = data.get("teams", [])
        target_team = None
        target_team_id_int = int(team_id) if team_id else None

        if target_team_id_int is not None:
            for t in teams:
                if t.get("id") == target_team_id_int:
                    target_team = t
                    break
        else:
            clean_swid = self.swid.strip("{}").lower()
            for t in teams:
                owners = [str(o).strip("{}").lower() for o in t.get("owners", [])]
                primary_owner = str(t.get("primaryOwner", "")).strip("{}").lower()
                if clean_swid in owners or clean_swid == primary_owner:
                    target_team = t
                    break

            if not target_team and teams:
                target_team = teams[0]

        if not target_team:
            raise ValueError(f"Team {team_id} not found in ESPN league {league_id}")

        resolved_team_id = str(target_team.get("id"))
        raw_name = target_team.get("name")
        location_nickname = f"{target_team.get('location') or ''} {target_team.get('nickname') or ''}".strip()
        team_name = (
            raw_name.strip()
            if raw_name and raw_name.strip()
            else (location_nickname or f"Team {resolved_team_id}")
        )

        # Parse roster entries
        entries = target_team.get("roster", {}).get("entries", []) or []
        parsed_players: List[Player] = []

        for entry in entries:
            player_pool_entry = entry.get("playerPoolEntry", {}) or {}
            player_data = player_pool_entry.get("player", {}) or {}
            lineup_slot_id = entry.get("lineupSlotId", 20)
            lineup_slot_name = ESPN_SLOT_ID_TO_NAME.get(lineup_slot_id, "BE")

            # Extract player attributes
            pid = str(player_data.get("id", ""))
            if not pid or pid == "0":
                continue

            full_name = player_data.get("fullName", f"Player {pid}")
            default_pos_id = player_data.get("defaultPositionId", 0)
            position = ESPN_POSITION_MAP.get(default_pos_id, "FLEX")
            injury_status = player_data.get("injuryStatus", "ACTIVE")

            # Eligible slots
            eligible_slot_ids = player_data.get("eligibleSlots", []) or []
            eligible_slots = [
                ESPN_SLOT_ID_TO_NAME.get(sid, str(sid))
                for sid in eligible_slot_ids
                if sid in ESPN_SLOT_ID_TO_NAME
            ]

            # Projected points for current scoring period
            projected_pts = 0.0
            stats = player_data.get("stats", []) or []
            for stat_entry in stats:
                if (
                    stat_entry.get("scoringPeriodId") == current_scoring_period
                    and stat_entry.get("statSourceId") == 1
                ):
                    projected_pts = float(stat_entry.get("appliedTotal", 0.0))
                    break

            # Locked status
            is_locked = bool(player_pool_entry.get("locked", False))
            if not is_locked:
                pro_team_schedule = player_data.get("proTeamSchedule", {}) or {}
                game_time = pro_team_schedule.get("date")
                if game_time:
                    try:
                        game_dt = datetime.datetime.fromtimestamp(
                            game_time / 1000.0, tz=datetime.timezone.utc
                        )
                        if datetime.datetime.now(datetime.timezone.utc) >= game_dt:
                            is_locked = True
                    except Exception:
                        pass

            parsed_players.append(
                Player(
                    player_id=pid,
                    name=full_name,
                    position=position,
                    lineup_slot=lineup_slot_name,
                    eligible_slots=eligible_slots,
                    injury_status=injury_status,
                    projected_points=projected_pts,
                    is_locked=is_locked,
                    team=str(player_data.get("proTeamId", "")),
                )
            )

        # Check for empty starting slots based on league roster settings
        if parsed_players:
            lineup_slot_counts = (
                data.get("settings", {})
                .get("rosterSettings", {})
                .get("lineupSlotCounts", {})
            )
            if lineup_slot_counts:
                for slot_id_str, count in lineup_slot_counts.items():
                    try:
                        slot_id = int(slot_id_str)
                        if slot_id in (20, 21):  # Skip bench (20) and IR (21)
                            continue
                        slot_name = ESPN_SLOT_ID_TO_NAME.get(slot_id)
                        if not slot_name:
                            continue
                        current_assigned = sum(1 for e in entries if e.get("lineupSlotId") == slot_id)
                        missing_count = count - current_assigned
                        for _ in range(max(0, missing_count)):
                            parsed_players.append(
                                Player(
                                    player_id="0",
                                    name=f"[Empty {slot_name}]",
                                    position=slot_name,
                                    lineup_slot=slot_name,
                                    eligible_slots=[slot_name],
                                    injury_status="EMPTY",
                                    projected_points=0.0,
                                    is_locked=False,
                                )
                            )
                    except (ValueError, TypeError):
                        pass

        return Roster(
            league_id=league_id,
            league_name=league_name,
            team_id=resolved_team_id,
            team_name=team_name,
            platform=self.platform_name,
            players=parsed_players,
        )

    def execute_swap(self, league_id: str, team_id: str, swap: SwapDecision) -> bool:
        """
        Execute roster swap on ESPN.
        Moves replacement from BENCH to target starter slot, and starter from slot to BENCH (if present).
        """
        if self.session is None:
            raise RuntimeError("HTTP session not initialized (requests library required).")

        url = f"https://fantasy.espn.com/apis/v3/games/ffl/seasons/{self.year}/segments/0/leagues/{league_id}/transactions/"
        target_slot_id = ESPN_SLOT_NAME_TO_ID.get(swap.slot.upper(), 20)
        bench_slot_id = ESPN_SLOT_NAME_TO_ID.get("BE", 20)

        items = [
            {
                "playerId": int(swap.replacement.player_id),
                "type": "LINEUP",
                "fromLineupSlotId": bench_slot_id,
                "toLineupSlotId": target_slot_id,
            }
        ]

        if not swap.starter.is_empty and swap.starter.player_id not in ("0", "", None):
            try:
                starter_pid_int = int(swap.starter.player_id)
                items.append(
                    {
                        "playerId": starter_pid_int,
                        "type": "LINEUP",
                        "fromLineupSlotId": target_slot_id,
                        "toLineupSlotId": bench_slot_id,
                    }
                )
            except (ValueError, TypeError):
                pass

        payload = {
            "executionType": "EXECUTE",
            "type": "ROSTER",
            "items": items,
        }

        logger.info(
            f"[ESPN] Sending transaction to {url} for league {league_id}, team {team_id}: {payload}"
        )

        resp = self.session.post(url, json=payload, timeout=10)
        if resp.status_code in (200, 201, 204):
            logger.info(f"[ESPN] Roster swap succeeded: {swap}")
            return True
        else:
            logger.error(
                f"[ESPN] Roster swap failed ({resp.status_code}): {resp.text}"
            )
            return False
