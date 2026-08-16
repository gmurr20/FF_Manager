"""Abstract interface defining the fantasy platform adapter contract."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from ff_manager.models import Roster, SwapDecision


class FantasyPlatformClient(ABC):
    """Abstract Base Class for fantasy platform integrations (ESPN, Sleeper, etc.)."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the human-readable platform name (e.g. 'ESPN', 'Sleeper')."""
        pass

    @abstractmethod
    def get_user_leagues(self) -> List[Dict[str, Any]]:
        """
        Fetch all leagues accessible by the authenticated user.
        
        Returns:
            List of dicts with keys: 'league_id', 'league_name', 'team_id', 'team_name'
        """
        pass

    @abstractmethod
    def get_roster(self, league_id: str, team_id: Optional[str] = None) -> Roster:
        """
        Fetch and normalize the current roster for the specified team.

        Args:
            league_id: Platform-specific league identifier.
            team_id: Platform-specific team/roster identifier. If omitted,
                     the adapter resolves the authenticated user's team.

        Returns:
            Standardized Roster object containing starters and bench players.
        """
        pass

    @abstractmethod
    def execute_swap(self, league_id: str, team_id: str, swap: SwapDecision) -> bool:
        """
        Execute a roster swap on the fantasy platform.

        Args:
            league_id: Platform-specific league identifier.
            team_id: Platform-specific team/roster identifier.
            swap: The SwapDecision containing the starter and replacement players.

        Returns:
            True if the swap succeeded, False otherwise.
        """
        pass

    @abstractmethod
    def validate_connection(self) -> bool:
        """
        Validate authentication credentials and connectivity to the platform.

        Returns:
            True if credentials are valid and platform is reachable.
        """
        pass


class EmailClient(ABC):
    """Abstract Base Class for email delivery backends (Resend, SendGrid, Postmark, etc.)."""

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if backend credentials and configuration are present."""
        pass

    @abstractmethod
    def send_email(
        self,
        to: str | List[str],
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
        from_email: Optional[str] = None,
    ) -> bool:
        """
        Send an email via this delivery backend.

        Args:
            to: Recipient email address or list of recipient email addresses.
            subject: Email subject line.
            html_content: Rendered HTML body content.
            text_content: Optional plain-text fallback body content.
            from_email: Optional sender address override.

        Returns:
            True if the email was sent successfully, False otherwise.
        """
        pass
