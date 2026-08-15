"""Configuration management using environment variables and .env files."""

import os
from dataclasses import dataclass, field
from typing import List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get_env_list(key: str, default: str = "") -> List[str]:
    """Parse comma-separated string from environment variable into list."""
    val = os.getenv(key, default)
    if not val:
        return []
    return [item.strip() for item in val.split(",") if item.strip()]


@dataclass
class Config:
    """Application configuration."""

    # General
    dry_run: bool = field(
        default_factory=lambda: os.getenv("DRY_RUN", "false").lower() in ("true", "1", "yes")
    )
    season_year: Optional[int] = field(
        default_factory=lambda: int(os.getenv("SEASON_YEAR")) if os.getenv("SEASON_YEAR") else None
    )
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper()
    )

    # ESPN Configuration
    espn_s2: Optional[str] = field(default_factory=lambda: os.getenv("ESPN_S2"))
    espn_swid: Optional[str] = field(default_factory=lambda: os.getenv("ESPN_SWID") or os.getenv("SWID"))
    espn_league_ids: List[str] = field(
        default_factory=lambda: _get_env_list("ESPN_LEAGUE_IDS")
    )
    espn_team_id: Optional[str] = field(default_factory=lambda: os.getenv("ESPN_TEAM_ID"))

    # Sleeper Configuration
    sleeper_token: Optional[str] = field(default_factory=lambda: os.getenv("SLEEPER_TOKEN"))
    sleeper_user_id: Optional[str] = field(
        default_factory=lambda: os.getenv("SLEEPER_USER_ID") or os.getenv("SLEEPER_USERNAME")
    )
    sleeper_league_ids: List[str] = field(
        default_factory=lambda: _get_env_list("SLEEPER_LEAGUE_IDS")
    )

    # Email / Notification Configuration
    smtp_host: Optional[str] = field(default_factory=lambda: os.getenv("SMTP_HOST"))
    smtp_port: int = field(
        default_factory=lambda: int(os.getenv("SMTP_PORT", "587"))
    )
    smtp_user: Optional[str] = field(default_factory=lambda: os.getenv("SMTP_USER"))
    smtp_password: Optional[str] = field(default_factory=lambda: os.getenv("SMTP_PASSWORD"))
    email_to: Optional[str] = field(default_factory=lambda: os.getenv("NOTIFICATION_EMAIL_TO"))
    email_from: Optional[str] = field(
        default_factory=lambda: os.getenv("NOTIFICATION_EMAIL_FROM")
    )
    force_email: bool = field(
        default_factory=lambda: os.getenv("FORCE_EMAIL", "false").lower() in ("true", "1", "yes")
    )

    @classmethod
    def load(cls) -> "Config":
        """Factory method to load configuration."""
        return cls()
