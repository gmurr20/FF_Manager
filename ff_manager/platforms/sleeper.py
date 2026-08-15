"""Sleeper Fantasy Football Platform Adapter."""

import datetime
import logging
from typing import Any, Dict, List, Optional, Set

try:
    import requests
except ImportError:
    requests = None

from ff_manager.interfaces import FantasyPlatformClient
from ff_manager.models import Player, Roster, SwapDecision

logger = logging.getLogger(__name__)

SLEEPER_API_BASE = "https://api.sleeper.app/v1"
SLEEPER_GRAPHQL_URL = "https://sleeper.app/graphql"


class SleeperAdapter(FantasyPlatformClient):
    """Adapter for interacting with Sleeper Fantasy Football API."""

    def __init__(
        self,
        auth_token: Optional[str] = None,
        user_id: Optional[str] = None,
        year: Optional[int] = None,
        session: Optional[Any] = None,
    ):
        """
        Initialize the Sleeper adapter.

        Args:
            auth_token: Sleeper user session token for authenticated write mutations.
            user_id: Sleeper user ID or username.
            year: NFL season year (defaults to current year).
            session: Optional requests.Session instance for testing/mocking.
        """
        self.auth_token = auth_token
        self.user_id = user_id
        self._resolved_user_id: Optional[str] = None
        self.year = year or datetime.date.today().year
        if session is not None:
            self.session = session
        elif requests is not None:
            self.session = requests.Session()
        else:
            self.session = None

        self._players_cache: Optional[Dict[str, Any]] = None
        self._nfl_state_cache: Optional[Dict[str, Any]] = None

    @property
    def platform_name(self) -> str:
        return "Sleeper"

    def _resolve_user_id(self) -> str:
        """Resolve username to numerical Sleeper user_id."""
        if not self.user_id:
            return ""
        if self._resolved_user_id:
            return self._resolved_user_id
        if self.user_id.isdigit():
            self._resolved_user_id = self.user_id
            return self._resolved_user_id

        if self.session is not None:
            try:
                user_resp = self.session.get(f"{SLEEPER_API_BASE}/user/{self.user_id}", timeout=10)
                if user_resp.status_code == 200:
                    self._resolved_user_id = str(user_resp.json().get("user_id", self.user_id))
                    logger.debug(f"[Sleeper] Resolved username '{self.user_id}' to user ID '{self._resolved_user_id}'")
                    return self._resolved_user_id
            except Exception as e:
                logger.warning(f"[Sleeper] Could not resolve user ID from username '{self.user_id}': {e}")

        self._resolved_user_id = self.user_id
        return self._resolved_user_id

    def validate_connection(self) -> bool:
        """Validate connectivity and user configuration."""
        if not self.user_id or self.session is None:
            return False
        try:
            resolved_uid = self._resolve_user_id()
            url = f"{SLEEPER_API_BASE}/user/{resolved_uid or self.user_id}"
            resp = self.session.get(url, timeout=10)
            return resp.status_code == 200
        except Exception:
            return False

    def _get_headers(self) -> Dict[str, str]:
        """Headers for authenticated mutations."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Content-Type": "application/json",
        }
        if self.auth_token:
            headers["authorization"] = self.auth_token
        return headers

    def get_nfl_state(self) -> Dict[str, Any]:
        """Fetch current NFL week and season state from Sleeper."""
        if self._nfl_state_cache is None:
            if self.session is not None:
                try:
                    url = f"{SLEEPER_API_BASE}/state/nfl"
                    resp = self.session.get(url, timeout=10)
                    if resp.status_code == 200:
                        self._nfl_state_cache = resp.json()
                except Exception as e:
                    logger.warning(f"[Sleeper] Could not fetch NFL state: {e}")
            if self._nfl_state_cache is None:
                self._nfl_state_cache = {"week": 1, "season": str(self.year)}
        return self._nfl_state_cache

    def get_players_metadata(self) -> Dict[str, Any]:
        """Fetch all NFL players metadata dictionary from Sleeper (cached in-memory)."""
        if self._players_cache is None:
            if self.session is None:
                raise RuntimeError("HTTP session not initialized (requests library required).")
            logger.info("[Sleeper] Fetching NFL players metadata database...")
            url = f"{SLEEPER_API_BASE}/players/nfl"
            resp = self.session.get(url, timeout=20)
            resp.raise_for_status()
            self._players_cache = resp.json()
            logger.info(f"[Sleeper] Loaded {len(self._players_cache)} players into metadata cache.")
        return self._players_cache

    def set_players_metadata(self, metadata: Dict[str, Any]) -> None:
        """Allow injecting pre-fetched player metadata (useful for unit tests)."""
        self._players_cache = metadata

    def get_user_leagues(self) -> List[Dict[str, Any]]:
        """Fetch all Sleeper leagues for the user in the configured season."""
        if not self.user_id or self.session is None:
            return []

        resolved_user_id = self._resolve_user_id()
        url = f"{SLEEPER_API_BASE}/user/{resolved_user_id}/leagues/nfl/{self.year}"
        resp = self.session.get(url, timeout=10)
        if resp.status_code != 200:
            logger.error(f"[Sleeper] Failed to fetch user leagues ({resp.status_code}): {resp.text}")
            return []

        leagues_data = resp.json()
        result = []
        for l in leagues_data:
            result.append(
                {
                    "league_id": str(l.get("league_id")),
                    "league_name": l.get("name", f"League {l.get('league_id')}"),
                }
            )
        return result

    def get_roster(self, league_id: str, team_id: Optional[str] = None) -> Roster:
        """
        Fetch and normalize the roster for the user's team in a Sleeper league.
        """
        if self.session is None:
            raise RuntimeError("HTTP session not initialized (requests library required).")

        # 1. Fetch league settings to get roster_positions and league name
        league_url = f"{SLEEPER_API_BASE}/league/{league_id}"
        league_resp = self.session.get(league_url, timeout=10)
        league_resp.raise_for_status()
        league_data = league_resp.json()
        league_name = league_data.get("name", f"Sleeper League {league_id}")
        roster_positions: List[str] = league_data.get("roster_positions", [])

        # Filter active starting slots (exclude "BN" / "BE" / "IR")
        starting_slots = [slot for slot in roster_positions if slot not in ("BN", "BE", "IR")]

        # 2. Fetch all league rosters
        rosters_url = f"{SLEEPER_API_BASE}/league/{league_id}/rosters"
        rosters_resp = self.session.get(rosters_url, timeout=10)
        rosters_resp.raise_for_status()
        rosters_data = rosters_resp.json()

        # 3. Identify user's roster
        resolved_uid = self._resolve_user_id()
        target_roster = None
        if team_id:
            for r in rosters_data:
                if str(r.get("roster_id")) == str(team_id):
                    target_roster = r
                    break
        elif resolved_uid:
            for r in rosters_data:
                owner_id = str(r.get("owner_id", ""))
                co_owners = [str(co) for co in r.get("co_owners", []) or []]
                if resolved_uid == owner_id or resolved_uid in co_owners:
                    target_roster = r
                    break

        # Fallback: Match via league users list
        if not target_roster and self.user_id:
            try:
                users_resp = self.session.get(f"{SLEEPER_API_BASE}/league/{league_id}/users", timeout=10)
                if users_resp.status_code == 200:
                    matched_uid = None
                    target_lower = self.user_id.lower()
                    for u in users_resp.json():
                        u_name = str(u.get("username", "")).lower()
                        d_name = str(u.get("display_name", "")).lower()
                        if target_lower in (u_name, d_name) or resolved_uid == str(u.get("user_id")):
                            matched_uid = str(u.get("user_id"))
                            break
                    if matched_uid:
                        for r in rosters_data:
                            owner_id = str(r.get("owner_id", ""))
                            co_owners = [str(co) for co in r.get("co_owners", []) or []]
                            if matched_uid == owner_id or matched_uid in co_owners:
                                target_roster = r
                                break
            except Exception as e:
                logger.warning(f"[Sleeper] Could not match user from league users list: {e}")

        if not target_roster:
            raise ValueError(
                f"Roster for user '{self.user_id}' (ID: {resolved_uid}) not found in Sleeper league '{league_name}' ({league_id})"
            )

        resolved_roster_id = str(target_roster.get("roster_id"))

        # Fetch user team name / users in league for display name
        team_name = f"Team {resolved_roster_id}"
        try:
            users_resp = self.session.get(f"{SLEEPER_API_BASE}/league/{league_id}/users", timeout=10)
            if users_resp.status_code == 200:
                for u in users_resp.json():
                    if str(u.get("user_id")) == str(target_roster.get("owner_id")):
                        team_name = (
                            u.get("metadata", {}).get("team_name")
                            or u.get("display_name")
                            or team_name
                        )
                        break
        except Exception:
            pass

        # 4. Fetch projections / matchups for the current week using league scoring settings
        nfl_state = self.get_nfl_state()
        current_week = nfl_state.get("week", 1)
        scoring_settings = league_data.get("scoring_settings", {})
        projections_map = self._fetch_weekly_projections(
            league_id=league_id,
            week=current_week,
            scoring_settings=scoring_settings,
        )

        # 5. Build Player models
        players_meta = self.get_players_metadata()
        all_roster_player_ids = target_roster.get("players", []) or []
        starters_list = target_roster.get("starters", []) or []
        reserve_list = target_roster.get("reserve", []) or []

        # Map starters to their respective slot position
        starter_slot_map: Dict[str, str] = {}
        empty_starter_slots: List[Player] = []
        for idx, slot_label in enumerate(starting_slots):
            pid = starters_list[idx] if idx < len(starters_list) else None
            if pid and str(pid) != "0":
                starter_slot_map[str(pid)] = slot_label
            else:
                # Add placeholder for empty starting slot
                empty_starter_slots.append(
                    Player(
                        player_id="0",
                        name=f"[Empty {slot_label}]",
                        position=slot_label,
                        lineup_slot=slot_label,
                        eligible_slots=[slot_label],
                        injury_status="EMPTY",
                        projected_points=0.0,
                        is_locked=False,
                    )
                )

        parsed_players: List[Player] = []
        # Include empty starting slot placeholders
        parsed_players.extend(empty_starter_slots)
        for pid in all_roster_player_ids:
            if not pid or pid == "0":
                continue

            meta = players_meta.get(pid, {})
            first_name = meta.get("first_name", "")
            last_name = meta.get("last_name", "")
            full_name = meta.get("full_name") or f"{first_name} {last_name}".strip() or f"Player {pid}"
            position = meta.get("position", "FLEX")
            injury_status = meta.get("injury_status") or meta.get("status")

            if pid in starter_slot_map:
                lineup_slot = starter_slot_map[pid]
            elif pid in reserve_list:
                lineup_slot = "IR"
            else:
                lineup_slot = "BE"

            fantasy_positions = meta.get("fantasy_positions") or [position]
            eligible_slots = list(fantasy_positions)
            if "BE" not in eligible_slots:
                eligible_slots.append("BE")
            if any(pos in ("RB", "WR", "TE") for pos in fantasy_positions) and "FLEX" not in eligible_slots:
                eligible_slots.append("FLEX")

            proj_pts = projections_map.get(pid, 0.0)
            is_locked = self._is_player_locked(meta)

            parsed_players.append(
                Player(
                    player_id=str(pid),
                    name=full_name,
                    position=position,
                    lineup_slot=lineup_slot,
                    eligible_slots=eligible_slots,
                    injury_status=injury_status,
                    projected_points=proj_pts,
                    is_locked=is_locked,
                    team=meta.get("team"),
                )
            )

        return Roster(
            league_id=league_id,
            league_name=league_name,
            team_id=resolved_roster_id,
            team_name=team_name,
            platform=self.platform_name,
            players=parsed_players,
        )

    def _calculate_custom_projected_pts(
        self,
        stats: Dict[str, Any],
        scoring_settings: Optional[Dict[str, float]] = None,
        position: Optional[str] = None,
    ) -> float:
        """
        Calculate custom fantasy projected points by applying the league's scoring settings
        to the player's projected statistical categories.
        """
        if not stats:
            return 0.0

        if scoring_settings and isinstance(scoring_settings, dict):
            total_points = 0.0
            matched = False
            for stat_key, val in stats.items():
                if val is None:
                    continue
                if stat_key in scoring_settings:
                    try:
                        total_points += float(val) * float(scoring_settings[stat_key])
                        matched = True
                    except (ValueError, TypeError):
                        pass

                # Position bonuses (e.g. TE Premium)
                if position == "TE" and stat_key == "rec" and "bonus_rec_te" in scoring_settings:
                    try:
                        total_points += float(val) * float(scoring_settings["bonus_rec_te"])
                    except (ValueError, TypeError):
                        pass

            if matched and total_points != 0.0:
                return round(total_points, 2)

        # Fallback to precalculated PPR / Half PPR / Standard
        if scoring_settings:
            rec = scoring_settings.get("rec", 0.0)
            if rec == 1.0:
                pts = stats.get("pts_ppr") or stats.get("ppr")
            elif rec == 0.5:
                pts = stats.get("pts_half_ppr") or stats.get("half_ppr")
            else:
                pts = stats.get("pts_std") or stats.get("std")
            if pts is not None:
                try:
                    return round(float(pts), 2)
                except (ValueError, TypeError):
                    pass

        pts = (
            stats.get("pts_ppr")
            or stats.get("ppr")
            or stats.get("pts_half_ppr")
            or stats.get("half_ppr")
            or stats.get("pts_std")
            or stats.get("std")
            or 0.0
        )
        try:
            return round(float(pts), 2)
        except (ValueError, TypeError):
            return 0.0

    def _fetch_weekly_projections(
        self,
        league_id: str,
        week: int,
        scoring_settings: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """Fetch projected points per player for the given week from Sleeper projections."""
        projections: Dict[str, float] = {}
        if self.session is None:
            return projections

        nfl_state = self.get_nfl_state()
        season = nfl_state.get("season", str(self.year))
        
        # Fantasy matchups run on regular season scoring; query regular first, then fallback
        season_types_to_try = ["regular"]
        current_stype = nfl_state.get("season_type")
        if current_stype and current_stype not in season_types_to_try:
            season_types_to_try.append(current_stype)

        for stype in season_types_to_try:
            try:
                proj_url = f"https://api.sleeper.app/projections/nfl/{season}/{week}"
                proj_resp = self.session.get(
                    proj_url,
                    params={"season_type": stype},
                    timeout=12,
                )
                if proj_resp.status_code == 200:
                    proj_data = proj_resp.json()
                    if isinstance(proj_data, list):
                        for item in proj_data:
                            pid = str(item.get("player_id", ""))
                            stats = item.get("stats", {}) or {}
                            pos = item.get("player", {}).get("position")
                            if pid:
                                calculated_pts = self._calculate_custom_projected_pts(
                                    stats, scoring_settings=scoring_settings, position=pos
                                )
                                if calculated_pts > 0:
                                    projections[pid] = calculated_pts
                    elif isinstance(proj_data, dict):
                        for pid, item in proj_data.items():
                            stats = item.get("stats", {}) or {} if isinstance(item, dict) else {}
                            pos = item.get("player", {}).get("position") if isinstance(item, dict) else None
                            calculated_pts = self._calculate_custom_projected_pts(
                                stats, scoring_settings=scoring_settings, position=pos
                            )
                            if calculated_pts > 0:
                                projections[str(pid)] = calculated_pts

                    if projections:
                        logger.info(
                            f"[Sleeper] Fetched and calculated weekly projections for {len(projections)} players "
                            f"(Season: {season}, Week: {week}, Type: {stype}, Scoring: {'Custom' if scoring_settings else 'Default'})."
                        )
                        break
            except Exception as e:
                logger.warning(f"[Sleeper] Could not fetch projections from {proj_url} for {stype}: {e}")

        # 2. Fallback: League matchups projections
        if not projections:
            try:
                url = f"{SLEEPER_API_BASE}/league/{league_id}/matchups/{week}"
                resp = self.session.get(url, timeout=10)
                if resp.status_code == 200:
                    matchups = resp.json()
                    for m in matchups:
                        custom_points = m.get("custom_points") or {}
                        players_points = m.get("players_points") or {}
                        for pid, pts in players_points.items():
                            if pts is not None:
                                projections[str(pid)] = float(pts)
                        for pid, pts in custom_points.items():
                            if pts is not None:
                                projections[str(pid)] = float(pts)
            except Exception as e:
                logger.warning(f"[Sleeper] Matchup projections fetch failed: {e}")

        return projections

    def _is_player_locked(self, player_meta: Dict[str, Any]) -> bool:
        """Check if an NFL player's game has started."""
        kickoff = player_meta.get("kickoff_time") or player_meta.get("game_time")
        if kickoff:
            try:
                if isinstance(kickoff, (int, float)):
                    game_dt = datetime.datetime.fromtimestamp(kickoff, tz=datetime.timezone.utc)
                else:
                    game_dt = datetime.datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
                return datetime.datetime.now(datetime.timezone.utc) >= game_dt
            except Exception:
                pass
        return False

    def execute_swap(self, league_id: str, team_id: str, swap: SwapDecision) -> bool:
        """
        Execute roster swap on Sleeper by updating the starting lineup array.
        """
        if self.session is None:
            raise RuntimeError("HTTP session not initialized (requests library required).")

        if not self.auth_token:
            logger.error("[Sleeper] Cannot execute swap: SLEEPER_TOKEN is not configured.")
            return False

        rosters_url = f"{SLEEPER_API_BASE}/league/{league_id}/rosters"
        rosters_resp = self.session.get(rosters_url, timeout=10)
        rosters_resp.raise_for_status()
        rosters_data = rosters_resp.json()

        target_roster = None
        for r in rosters_data:
            if str(r.get("roster_id")) == str(team_id):
                target_roster = r
                break

        if not target_roster:
            logger.error(f"[Sleeper] Roster {team_id} not found in league {league_id}")
            return False

        current_starters: List[str] = list(target_roster.get("starters", []))
        starter_id = swap.starter.player_id
        replacement_id = swap.replacement.player_id

        if swap.starter.is_empty or starter_id not in current_starters:
            # Need to place replacement in an empty slot ('0', '', or unassigned index)
            league_url = f"{SLEEPER_API_BASE}/league/{league_id}"
            league_resp = self.session.get(league_url, timeout=10)
            roster_positions = (
                league_resp.json().get("roster_positions", [])
                if league_resp.status_code == 200
                else []
            )
            starting_slots = [s for s in roster_positions if s not in ("BN", "BE", "IR")]

            filled_idx = None
            for idx, slot in enumerate(starting_slots):
                current_pid = current_starters[idx] if idx < len(current_starters) else "0"
                if current_pid in ("0", "", None) and slot.upper() == swap.slot.upper():
                    filled_idx = idx
                    break

            if filled_idx is None:
                for idx, slot in enumerate(starting_slots):
                    current_pid = current_starters[idx] if idx < len(current_starters) else "0"
                    if current_pid in ("0", "", None) and swap.replacement.can_fill_slot(slot):
                        filled_idx = idx
                        break

            if filled_idx is not None:
                while len(current_starters) <= filled_idx:
                    current_starters.append("0")
                current_starters[filled_idx] = replacement_id
                updated_starters = current_starters
            else:
                logger.error(f"[Sleeper] Could not find vacant slot index for slot {swap.slot}")
                return False
        else:
            updated_starters = [
                replacement_id if pid == starter_id else pid for pid in current_starters
            ]

        rest_url = f"{SLEEPER_API_BASE}/roster/{team_id}/starters"
        headers = self._get_headers()
        payload = {"starters": updated_starters}

        try:
            logger.info(f"[Sleeper] Updating starters for roster {team_id}: {updated_starters}")
            resp = self.session.post(rest_url, json=payload, headers=headers, timeout=10)
            if resp.status_code in (200, 201, 204):
                logger.info(f"[Sleeper] Successfully updated starters via REST: {swap}")
                return True
        except Exception as e:
            logger.warning(f"[Sleeper] REST update starters encountered error: {e}")

        try:
            graphql_query = """
            mutation update_starters($league_id: ID!, $roster_id: ID!, $starters: [ID!]) {
                update_starters(league_id: $league_id, roster_id: $roster_id, starters: $starters)
            }
            """
            variables = {
                "league_id": str(league_id),
                "roster_id": str(team_id),
                "starters": updated_starters,
            }
            gql_resp = self.session.post(
                SLEEPER_GRAPHQL_URL,
                json={"query": graphql_query, "variables": variables},
                headers=headers,
                timeout=10,
            )
            if gql_resp.status_code == 200:
                data = gql_resp.json()
                if "errors" not in data:
                    logger.info(f"[Sleeper] Successfully updated starters via GraphQL: {swap}")
                    return True
                else:
                    logger.error(f"[Sleeper] GraphQL returned errors: {data['errors']}")
            else:
                logger.error(f"[Sleeper] GraphQL update failed ({gql_resp.status_code}): {gql_resp.text}")
        except Exception as e:
            logger.error(f"[Sleeper] GraphQL mutation exception: {e}")

        return False
